param(
  [Parameter(Mandatory=$true)][string]$InputPath,
  [Parameter(Mandatory=$true)][string]$SourcePath,
  [Parameter(Mandatory=$true)][ValidateSet('ps51','ps7')][string]$Runtime
)
$ErrorActionPreference='Stop'
$strictUtf8=New-Object Text.UTF8Encoding -ArgumentList $false,$true
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if ($env:OS -ne 'Windows_NT') { throw 'This observation gate requires a real Windows host.' }
if ($Runtime -eq 'ps51' -and ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1)) { throw 'Expected Windows PowerShell 5.1.' }
if ($Runtime -eq 'ps7' -and $PSVersionTable.PSVersion.Major -ne 7) { throw 'Expected PowerShell 7.' }
function Get-BytesSha256([byte[]]$Bytes) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
$manifestPath=Join-Path $PSScriptRoot 'original-functions.json'
$manifestInfo=New-Object IO.FileInfo -ArgumentList $manifestPath
if ($manifestInfo.Length -gt 65536) { throw 'Oversized immutable manifest.' }
$manifestBytes=[IO.File]::ReadAllBytes($manifestPath)
$manifestHash=Get-BytesSha256 $manifestBytes
if ($manifestHash -cne '8cba53d610ec92f31be4a9a3d71b946b14ca8b023cda3f1979cba81fdff7f487') { throw 'Pinned original manifest changed.' }
$original=$strictUtf8.GetString($manifestBytes) | Microsoft.PowerShell.Utility\ConvertFrom-Json
# SourcePath is materialized from the manifest's immutable, published Git tree
# into a caller-owned temporary directory. Never execute the baseline script.
$sourceInfo=New-Object IO.FileInfo -ArgumentList $SourcePath
if ($sourceInfo.Length -gt 2097152) { throw 'Oversized original source.' }
$sourceBytes=[IO.File]::ReadAllBytes($SourcePath)
$sourceHash=Get-BytesSha256 $sourceBytes
if ($sourceHash -cne $original.source_sha256 -or $sourceBytes.Length -ne $original.source_bytes) { throw 'Pinned Git source bytes changed.' }
$sourceText=$strictUtf8.GetString($sourceBytes).TrimStart([char]0xFEFF)
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Pinned original Git source did not parse.' }
$expected=@{
  '_History-PickBestStrategy'='82c82f36c700fbd1a5c225d91255b8cae2e5d54b3e3a8cbaaec41201c78f371d'
  '_History-Stats'='c21bcbd4182a0639650758639e0ce556a9b946cd1529a7327cc55daa75477997'
  '_AppStrategy-Read'='29de16bdfafe2ac8cbdd44fc8bf6f8800e4f121716ce81066958342d66edd6f9'
  '_AppStrategy-LastGood'='a7f6283ea0f8735af59ad7bb0789b4b01c29240c0586d7cc8af902a2f94e8e91'
}
if ($original.functions.Count -ne 4) { throw 'Expected exactly four original functions.' }
$seen=@{}
foreach ($entry in $original.functions) {
  if (-not $expected.ContainsKey($entry.name) -or $seen.ContainsKey($entry.name)) { throw 'Unexpected or duplicate original function.' }
  $functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $entry.name},$true))
  if ($functions.Count -ne 1) { throw 'Expected one pinned function AST extent.' }
  $body=$functions[0].Extent.Text
  $bytes=[Text.Encoding]::UTF8.GetBytes($body)
  if ((Get-BytesSha256 $bytes) -cne $expected[$entry.name] -or $bytes.Length -ne $entry.utf8_bytes) { throw 'Original function AST body changed.' }
  if ($entry.byte_start -lt 0 -or $entry.byte_end -gt $sourceBytes.Length -or ($entry.byte_end-$entry.byte_start) -ne $bytes.Length) { throw 'Invalid pinned source span.' }
  $span=New-Object byte[] $bytes.Length
  [Array]::Copy($sourceBytes,[int]$entry.byte_start,$span,0,$span.Length)
  if ((Get-BytesSha256 $span) -cne $expected[$entry.name]) { throw 'Original source span changed.' }
  . ([scriptblock]::Create($body))
  $seen[$entry.name]=$true
}
function Encode-Wire($Value) {
  if ($null -eq $Value) { return @{kind='null'} }
  if ($Value -is [Collections.IDictionary]) {
    return @{kind='hashtable';properties=@(foreach ($key in $Value.Keys) { @{name=[string]$key;value=(Encode-Wire $Value[$key])} })}
  }
  if ($Value -is [string] -or $Value -is [ValueType]) {
    $encoded=$Value
    if ($Value -is [DateTime]) { $encoded=$Value.ToString('o',[Globalization.CultureInfo]::InvariantCulture) }
    return @{kind='scalar';type=$Value.GetType().Name;value=$encoded}
  }
  if ($Value -is [Collections.IEnumerable]) { return @{kind='array';items=@(foreach ($item in $Value) { Encode-Wire $item })} }
  return @{kind='object';properties=@(foreach ($property in $Value.PSObject.Properties) { @{name=$property.Name;value=(Encode-Wire $property.Value)} })}
}
$inputInfo=New-Object IO.FileInfo -ArgumentList $InputPath
if ($inputInfo.Length -gt 16777216) { throw 'Oversized fixture input.' }
$inputBytes=[IO.File]::ReadAllBytes($InputPath)
if ($inputBytes.Length -gt 16777216) { throw 'Oversized fixture input.' }
$inputHash=Get-BytesSha256 $inputBytes
# Direct assignment is essential: PS5 emits a root JSON array as one pipeline
# object. Wrapping ConvertFrom-Json in @() can silently turn N cases into one.
$envelope=$strictUtf8.GetString($inputBytes) | Microsoft.PowerShell.Utility\ConvertFrom-Json
if (@($envelope.PSObject.Properties).Count -ne 2 -or $null -eq $envelope.PSObject.Properties['fixtures'] -or $envelope.schema -cne 'cucp.history-reducer-input/v1') { throw 'Invalid input envelope.' }
$fixtures=$envelope.fixtures
if ($fixtures -isnot [array] -or $fixtures.Count -lt 1 -or $fixtures.Count -gt 2048) { throw 'Expected 1..2048 fixtures in the envelope array.' }
$owned=Join-Path ([IO.Path]::GetTempPath()) ('cucp-history-qualification-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($owned)
$all=New-Object Collections.ArrayList
$ids=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
$oldCulture=[Threading.Thread]::CurrentThread.CurrentCulture
$oldUiCulture=[Threading.Thread]::CurrentThread.CurrentUICulture
try {
  foreach ($fixture in $fixtures) {
    # This is an internal oracle for the canonical Python fixture generator,
    # not an arbitrary-JSON public API. ConvertFrom-Json cannot recover duplicate
    # property spelling already collapsed by its runtime-specific reader.
    foreach ($property in $fixture.PSObject.Properties) {
      if ($property.Name -cnotin @('id','operation','culture','exists','lines','label','match','lookback','app_key')) { throw 'Unknown fixture member.' }
    }
    foreach ($required in @('id','operation','culture','exists','lines')) {
      if ($null -eq $fixture.PSObject.Properties[$required]) { throw 'Missing fixture member.' }
    }
    foreach ($optional in @('label','match','app_key')) {
      if ($null -ne $fixture.PSObject.Properties[$optional] -and ($fixture.$optional -isnot [string] -or $fixture.$optional.Length -gt 1048576)) { throw 'Invalid optional fixture string.' }
    }
    if ($null -ne $fixture.PSObject.Properties['lookback']) {
      if (($fixture.lookback -isnot [int] -and $fixture.lookback -isnot [long]) -or $fixture.lookback -lt [int]::MinValue -or $fixture.lookback -gt [int]::MaxValue) { throw 'Expected Int32 lookback.' }
    }
    if ($fixture.id -isnot [string] -or $fixture.id.Length -lt 1 -or $fixture.id.Length -gt 200 -or -not $ids.Add($fixture.id)) { throw 'Invalid/duplicate fixture identity.' }
    if ($fixture.operation -cnotin @('pick','stats','app-read','last-good')) { throw 'Unknown operation.' }
    if ($fixture.exists -isnot [bool] -or $fixture.lines -isnot [array] -or $fixture.lines.Count -gt 4096) { throw 'Invalid captured file data.' }
    if ($fixture.culture -isnot [string] -or $fixture.culture -cnotin @('','en-US','ko-KR','tr-TR','de-DE')) { throw 'Unsupported culture.' }
    if (-not $fixture.exists -and $fixture.lines.Count) { throw 'Missing file cannot carry lines.' }
    $capturedLength=0L
    foreach ($line in $fixture.lines) {
      if ($line -isnot [string] -or $line.Length -gt 1048576 -or $line.Contains("`r") -or $line.Contains("`n")) { throw 'Invalid physical line.' }
      $capturedLength += $line.Length
      if ($capturedLength -gt 4194304) { throw 'Capture exceeds 4 Mi characters.' }
    }
    [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($fixture.culture)
    [Threading.Thread]::CurrentThread.CurrentUICulture=[Globalization.CultureInfo]::GetCultureInfo($fixture.culture)
    $path=Join-Path $owned 'synthetic.jsonl'
    if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) }
    if ($fixture.exists) { [IO.File]::WriteAllLines($path,[string[]]$fixture.lines,(New-Object Text.UTF8Encoding($false))) }
    $Script:HistoryFile=$path;$Script:AppStrategyFile=$path
    $writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
    try {
      $value=$null
      switch -CaseSensitive ($fixture.operation) {
        'pick' {
          $lookback=5;if ($null -ne $fixture.lookback) { $lookback=[int]$fixture.lookback }
          $value=_History-PickBestStrategy -Label ([string]$fixture.label) -Match ([string]$fixture.match) -LookbackN $lookback
        }
        'stats' { $value=_History-Stats }
        'app-read' { $value=@(_AppStrategy-Read) }
        'last-good' { $value=_AppStrategy-LastGood -AppKey ([string]$fixture.app_key) }
      }
      $result=[ordered]@{id=$fixture.id;operation=$fixture.operation;wire=(Encode-Wire $value);compact_json=(Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $value -Depth 100 -Compress);console=$writer.ToString();errors=@()}
    } catch {
      $result=[ordered]@{id=$fixture.id;operation=$fixture.operation;wire=$null;compact_json=$null;console=$writer.ToString();errors=@($_.Exception.GetType().FullName+': '+$_.Exception.Message)}
    } finally { [Console]::SetOut($previous);$writer.Dispose() }
    [void]$all.Add($result)
  }
} finally {
  [Threading.Thread]::CurrentThread.CurrentCulture=$oldCulture
  [Threading.Thread]::CurrentThread.CurrentUICulture=$oldUiCulture
  # Only a freshly created, harness-owned directory is ever deleted.
  [IO.Directory]::Delete($owned,$true)
}
if ($all.Count -ne $fixtures.Count) { throw 'Fixture execution count mismatch.' }
$report=[ordered]@{schema='cucp.history-reducer-qualification/v1';runtime=$Runtime;kind='windows-observation';manifest_sha256=$manifestHash;source_sha256=$sourceHash;input_sha256=$inputHash;host=@{ps_version=$PSVersionTable.PSVersion.ToString();clr=[Environment]::Version.ToString();os=[Environment]::OSVersion.ToString();culture=$oldCulture.Name};results=@($all)}
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $report -Depth 100 -Compress))
