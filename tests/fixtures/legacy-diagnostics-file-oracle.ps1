param([string]$Source,[string]$InputPath,[string]$AdapterSource,[string]$BridgeSource,[switch]$ProductionEntry)
# The caller supplies the pinned original source. Parse definitions only: never
# dot-source the wrapper, invoke its dispatcher, or acquire a real diagnostic file.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Selected diagnostic source did not parse'}
if($ProductionEntry -and (-not $AdapterSource -or [IO.Path]::GetFullPath($Source) -cne [IO.Path]::GetFullPath($BridgeSource))){throw 'Production entries must come from current main with support hooks'}
if($ProductionEntry){
 # Import only the inert AST validator; never execute the guard driver's body.
 $guardTokens=$null;$guardErrors=$null
 $guardAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'legacy-diagnostics-adapter-guards.ps1'),[ref]$guardTokens,[ref]$guardErrors)
 if($guardErrors.Count){throw 'Public delegate validator failed to parse'}
 $validator=@($guardAst.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Fixture-ValidatePublicDelegate'},$true))
 if($validator.Count -ne 1){throw 'Expected one inert public delegate validator'}
 . ([scriptblock]::Create($validator[0].Extent.Text))
}

$fixtures=Microsoft.PowerShell.Management\Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Encode-Wire($Value) {
 if($null -eq $Value){return @{kind='scalar';value=$null}}
 if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
 if($Value -is [Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(Encode-Wire $Value[$key])}})}}
 if($Value -is [Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){Encode-Wire $item})}}
 return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(Encode-Wire $p.Value)}})}
}
function Capture-Effect {
 param([string]$Kind,[string]$Name='',[string[]]$Argv=@(),$Data=$null)
 [void]$script:trace.Add([ordered]@{kind=$Kind;name=$Name;argv=@($Argv);data=$Data})
 if($Kind -eq 'Timestamp'){return '2026-10-02T00:00:00.0000000Z'}
 if($Kind -eq 'Clock'){
  if($Name -eq 'start'){return 0}
  $time=37
  if($null -ne $script:fixture.clocks -and $script:clockCursor -lt @($script:fixture.clocks).Count){$time=[int]$script:fixture.clocks[$script:clockCursor]}
  if($Name -eq 'stop'){$script:clockCursor++}
  return $time
 }
 if($Kind -in @('Sleep','Notice')){return}
 if($script:cursor -ge @($script:fixture.replies).Count){throw "Fixture exhausted at ${Kind}:$Name"}
 $value=$script:fixture.replies[$script:cursor];$script:cursor++
 if($null -ne $value -and $value.PSObject.Properties['throw']){throw $value.throw}
 Write-Output -NoEnumerate $value
}
function New-FakeStopwatch {
 param([string]$Scope)
 $null=Capture-Effect 'Clock' -Name 'start' -Data $Scope
 $value=[pscustomobject]@{Scope=$Scope;Stopped=$false;Milliseconds=0}
 $value | Add-Member ScriptProperty Elapsed {
  $ms=if($this.Stopped){$this.Milliseconds}else{[int](Capture-Effect 'Clock' -Name 'elapsed' -Data $this.Scope)}
  return [pscustomobject]@{TotalMilliseconds=$ms}
 }
 $value | Add-Member ScriptMethod Stop {
  $this.Milliseconds=[int](Capture-Effect 'Clock' -Name 'stop' -Data $this.Scope)
  $this.Stopped=$true
 }
 return $value
}
function Get-Date {
 $timestamp=Capture-Effect 'Timestamp' -Name 'o'
 return [DateTime]::Parse($timestamp,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind)
}
function Test-Path {param([string]$LiteralPath,[string]$PathType) if($PathType -eq 'Leaf'){return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath -PathType Leaf};Capture-Effect 'FileExists' -Data $LiteralPath}
function Get-ChildItem {
 param([string]$LiteralPath,[string]$Filter,[string]$ErrorAction,[switch]$Recurse,[switch]$File)
 $items=Capture-Effect 'ListFiles' -Data ([ordered]@{path=$LiteralPath;recurse=[bool]$Recurse;filter=$Filter;file=[bool]$File})
 foreach($item in @($items)){
  if($null -eq $item){continue}
  [pscustomobject]@{FullName=$item.full_name;Length=$item.length;LastWriteTime=[datetime]$item.last_write_time}
 }
}
function Get-Content {
 param([string]$LiteralPath,[string]$Encoding,[string]$ErrorAction)
 # Acquisition already happened in the fixture. Preserve Get-Content's pipeline
 # behavior for empty, singleton, and multiple lines after consuming one reply.
 $lines=Capture-Effect 'ReadLines' -Data $LiteralPath
 foreach($line in @($lines)){Write-Output $line}
}
function Resolve-Path {
 param([string]$LiteralPath,[string]$ErrorAction)
 $path=Capture-Effect 'ResolvePath' -Data $LiteralPath
 if($path){return [pscustomobject]@{Path=$path}}
}
function ConvertTo-Json {
 [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject,[int]$Depth=2,[switch]$Compress)
 process{
  # Capture the raw PowerShell object independently of public depth-limited JSON.
  if($InputObject.schema -in @('cucp.audit-summary/v1','cucp.release-notes/v1','cucp.observation/v1')){$script:payload=Encode-Wire $InputObject}
  Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $InputObject -Depth $Depth -Compress:$Compress
 }
}
function Replace-ExactSeam {
 param([string]$Text,[string]$Old,[string]$New,[int]$Count=1,[string]$Label)
 $matches=[regex]::Matches($Text,[regex]::Escape($Old)).Count
 if($matches -ne $Count){throw "Expected $Count $Label seams, found $matches"}
 return $Text.Replace($Old,$New)
}

$names=@('_Read-OptValue','_Read-Switch','_Emit-Envelope','_New-ObservationEnvelope','_Cucp-RedactSecrets',
 'Invoke-MacroAuditSummary','Invoke-MacroLogTail','Invoke-MacroReleaseNotes')
if($ProductionEntry){$names=@($names|Where-Object {$_ -ne '_Cucp-RedactSecrets'})}
foreach($name in $names){
 $found=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($found.Count -ne 1){throw "Expected one original diagnostic function: $name"}
 $text=$found[0].Extent.Text
 # Keep current audit-summary on its original body. The migrated two file
 # reports load current public delegates without replacing their statements.
 if($ProductionEntry -and $name -cin @('Invoke-MacroLogTail','Invoke-MacroReleaseNotes')){
  $operation=if($name -ceq 'Invoke-MacroLogTail'){'log-tail'}else{'release-notes'}
  Fixture-ValidatePublicDelegate $found[0] $operation
  . ([scriptblock]::Create($text));continue
 }
 if($name -eq 'Invoke-MacroLogTail'){
  $text=Replace-ExactSeam $text '[System.Diagnostics.Stopwatch]::StartNew()' '(New-FakeStopwatch -Scope ''log-tail'')' -Label 'log stopwatch'
  # Replace only the bounded binary acquisition, retaining the original catch,
  # line splitting, truncation, filter, redaction, envelope and Console branches.
  $pattern='(?s)\$fs = \[System\.IO\.File\]::Open\(\$logPath, \[System\.IO\.FileMode\]::Open, \[System\.IO\.FileAccess\]::Read, \[System\.IO\.FileShare\]::ReadWrite\)\s+try \{.*?\} finally \{ \$fs\.Dispose\(\) \}'
  $matches=[regex]::Matches($text,$pattern)
  if($matches.Count -ne 1){throw "Expected one bounded log-tail read seam, found $($matches.Count)"}
  $replacement=@'
$capturedTail = Capture-Effect 'TailBytes' -Data ([ordered]@{path=$logPath;max_bytes=$maxBytes})
    $totalBytes = [int64]$capturedTail.total_bytes
    $tailBytes = [int]$capturedTail.tail_bytes
    $tailText = [string]$capturedTail.text
'@
  $match=$matches[0]
  $text=$text.Remove($match.Index,$match.Length).Insert($match.Index,$replacement)
 }
 if($name -eq 'Invoke-MacroReleaseNotes'){
  $text=Replace-ExactSeam $text 'Join-Path $PSScriptRoot "..\CHANGELOG.md"' '$script:changelogPath' -Label 'changelog owned path'
 }
 if($text -match '\[System\.IO\.|\[IO\.|::StartNew\(|&\s+\$PSCommandPath|&\s+powershell|Start-Process|SendKeys\]::'){
  throw "Unintercepted diagnostic effect in $name"
 }
 . ([scriptblock]::Create($text))
}


# Load exact shared transport and adapter definitions. Only leaf acquisitions and
# deterministic context/clock providers below are replaced for this fixture.
if($AdapterSource){
 foreach($load in @(@{path=$BridgeSource;bridge=$true},@{path=$AdapterSource;bridge=$false})){
  $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($load.path,[ref]$t,[ref]$e)
  if($e.Count){throw 'Adapter qualification source failed to parse'}
  $nodes=@($a.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true))
  foreach($node in $nodes){
   $take=if($load.bridge){$node.Name -like '_Execution-*' -or $node.Name -in @('_Invoke-LegacyExecutionHost','_Invoke-LegacyExecutionEffectLoop')}else{$node.Name -like '_Diagnostic-*' -or $node.Name -eq '_Invoke-LegacyDiagnosticFamily'}
   if($take){. ([scriptblock]::Create($node.Extent.Text))}
  }
 }
 function _Diagnostic-Clock($State,[string]$Name,[string]$Scope){Capture-Effect Clock -Name $Name -Data $Scope}
 function _Diagnostic-NodeVersion {Capture-Effect NodeVersion}
 function _Diagnostic-TailBytes([string]$Path,[int]$Maximum){Capture-Effect TailBytes -Data ([ordered]@{path=$Path;max_bytes=$Maximum})}
 function _Diagnostic-AuditProbe([string]$Directory,[string]$Prefix){Capture-Effect AuditProbe -Name $Prefix -Data $Directory | Out-Null}
 function _Diagnostic-ClearAppshotCache([string]$Directory){Capture-Effect ClearAppshotCache -Name 'appshot-*.json' -Data $Directory | Out-Null}
 function _Diagnostic-ProcessorCount {Capture-Effect ProcessorCount}
 function _Diagnostic-ProcessMetrics($State,[int]$CurrentOrdinal,$PreviousOrdinal){Capture-Effect ProcessMetrics -Data ([ordered]@{current_ordinal=$CurrentOrdinal;previous_ordinal=$PreviousOrdinal})}
 function _Diagnostic-CapturedMacro([string]$Name,[string[]]$Argv){Capture-Effect Macro -Name $Name -Argv $Argv}
 function _Diagnostic-GetContext {
  $cl='C:\fixture\CHANGELOG.md';$temp='C:\fixture\computer-use-control-plane'
  if($script:fixture.context){
   if($script:fixture.context.PSObject.Properties['changelog_path']){$cl=$script:fixture.context.changelog_path}
   if($script:fixture.context.PSObject.Properties['temp_root']){$temp=$script:fixture.context.temp_root}
  }
  return [pscustomobject][ordered]@{audit_directory=$Script:AuditDir;cache_directory=$Script:CacheDir;wrapper_log=$Script:WrapperLog;
    cli_path=$Script:CliPath;changelog_path=$cl;temp_root=$temp;benchmark_schema='cucp.benchmark/v1';release_schema='cucp.release-notes/v1'}
 }
}

function Context-Value {
 param([string]$Name,[string]$Fallback)
 if($null -ne $script:fixture.context -and $null -ne $script:fixture.context.PSObject.Properties[$Name]){
  $value=$script:fixture.context.$Name
  if($value -is [string]){return $value}
 }
 return $Fallback
}
$all=New-Object Collections.ArrayList
foreach($fixture in $fixtures){
 $script:fixture=$fixture;$script:trace=New-Object Collections.ArrayList
 $script:cursor=0;$script:clockCursor=0;$script:payload=$null
 $Brief=[bool]$fixture.brief
 $Script:AuditDir=Context-Value 'audit_dir' 'C:\fixture\audit'
 $Script:CacheDir=Context-Value 'cache_dir' 'C:\fixture\cache'
 $Script:WrapperLog=Context-Value 'wrapper_log' 'C:\fixture\wrapper.log'
 $Script:CliPath=Context-Value 'cli_path' 'C:\fixture\cli.mjs';if($fixture.context -and $fixture.context.PSObject.Properties['cli_path'] -and $null -eq $fixture.context.cli_path){$Script:CliPath=$null}
 $script:changelogPath=Context-Value 'changelog_path' 'C:\fixture\CHANGELOG.md'
 $Script:CucpV14Schema=@{ReleaseNotes='cucp.release-notes/v1';Benchmark='cucp.benchmark/v1'}
 # Original wrapper invocations each initialize their own compiled regex cache.
 $Script:_LogRedactRegex=$null
 $oldCulture=[Threading.Thread]::CurrentThread.CurrentCulture
 $fixtureCulture='en-US';if($null -ne $fixture.PSObject.Properties['culture'] -and $fixture.culture -is [string]){$fixtureCulture=$fixture.culture}
 [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($fixtureCulture)
 $writer=New-Object IO.StringWriter;$old=[Console]::Out;[Console]::SetOut($writer)
 try{
  $function=switch($fixture.operation){
   'audit-summary'{'Invoke-MacroAuditSummary'}
   'log-tail'{'Invoke-MacroLogTail'}
   'release-notes'{'Invoke-MacroReleaseNotes'}
   default{throw "Unsupported file diagnostic fixture: $($fixture.operation)"}
  }
  $exit=if($ProductionEntry){& $function -Rest @($fixture.rest)}elseif($AdapterSource){_Invoke-LegacyDiagnosticFamily -Operation ([string]$fixture.operation) -Rest @($fixture.rest)}else{& $function -Rest @($fixture.rest)}
  $result=@{state='complete';payload=$script:payload;exit=[int]$exit;console=$writer.ToString();effects=(Encode-Wire @($script:trace));consumed=$script:cursor}
 }catch{
  $result=@{state='error';error=$_.Exception.Message;console=$writer.ToString();effects=(Encode-Wire @($script:trace));consumed=$script:cursor}
 }finally{
  [Console]::SetOut($old);$writer.Dispose()
  [Threading.Thread]::CurrentThread.CurrentCulture=$oldCulture
 }
 [void]$all.Add($result)
}
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
