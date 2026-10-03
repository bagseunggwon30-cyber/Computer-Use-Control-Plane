param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Manifest,[Parameter(Mandatory=$true)][string]$CasePath,[string]$Stubs,[switch]$TestWrongBinding,[ValidateSet('none','duplicate','changed')][string]$TestTypeExtentFault='none')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
function Hash-Text([string]$Text) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
if(-not $Stubs){throw 'An inert acquisition facade is required'}
$pin=[IO.File]::ReadAllText($Manifest,[Text.Encoding]::UTF8)|ConvertFrom-Json
$entry=@($pin.files|Where-Object{$_.path -eq 'scripts/cucp-helper-server.ps1'})[0]
$sourceText=[IO.File]::ReadAllText($Source,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
if((Hash-Text $sourceText) -cne $entry.normalized_sha256){throw 'Published server source hash mismatch'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Published server source AST parse failed'}
$verified=New-Object Collections.ArrayList
foreach($record in $entry.functions) {
  $matches=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $record.name},$true))
  if($matches.Count -ne 1){throw "Expected exact function: $($record.name)"}
  $node=$matches[0]
  if($node.Extent.StartOffset -ne $record.start_utf16 -or $node.Extent.EndOffset -ne $record.end_utf16 -or (Hash-Text $node.Extent.Text) -cne $record.sha256){throw "Published AST extent changed: $($record.name)"}
  [void]$verified.Add(@{record=$record;node=$node})
}

# Source and original function hashes above remain unchanged. This explicit
# acquisition seam alters ONLY type-name AST extents in the listed functions:
# TypeExpressionAst / TypeConstraintAst and a bare first New-Object argument.
# Every other UTF-16 code unit is copied from the verified original. In
# particular, action branches, arguments, strings and query order are retained.
# Native loader definitions and their assembly-qualified WinRT literals are
# outside this seam. They are verified above but never imported or executed.
$loaderNames=@('_Ensure-Win32Loaded','_Server-Ensure-OCR','_Server-Ensure-UIA')
$importNames=@('_Log','_Action-Windows','_Action-Health','_Action-Focused','_Action-ModalDetect','_Action-OcrScreenFast','_Action-UiaFindFast','_Dispatch')
$fixturePrefix='CucpFixture.'
$typeCounts=[ordered]@{
  'HelperWin32'=18
  'HelperWin32+RECT'=2
  'System.Windows.Automation.AutomationElement'=4
  'System.Windows.Automation.OrCondition'=1
  'System.Windows.Automation.PropertyCondition'=2
  'System.Windows.Automation.ControlType'=2
  'System.Windows.Automation.TreeScope'=4
  'System.Windows.Automation.WindowPattern'=1
  'System.Windows.Forms.Screen'=1
  'System.Windows.Forms.SystemInformation'=1
  'Windows.Media.Ocr.OcrEngine'=1
  'System.Drawing.Bitmap'=1
  'System.Drawing.Graphics'=1
  'System.Drawing.Size'=1
  'System.Drawing.Imaging.ImageFormat'=1
  'WindowsRuntimeSystemExtensions'=1
  'Windows.Storage.StorageFile'=2
  'Windows.Storage.FileAccessMode'=1
  'Windows.Storage.Streams.IRandomAccessStream'=1
  'Windows.Graphics.Imaging.BitmapDecoder'=2
  'Windows.Graphics.Imaging.SoftwareBitmap'=1
  'Windows.Media.Ocr.OcrResult'=1
  'System.Windows.Automation.Condition'=2
}
$seen=@{};$functions=New-Object Collections.ArrayList;$sites=New-Object Collections.ArrayList;$faultInjected=$false
foreach($item in $verified){
  $record=$item.record;$node=$item.node
  if($record.parent_function -or $loaderNames -ccontains $record.name){continue}
  if($importNames -cnotcontains $record.name){throw "Unplanned oracle function: $($record.name)"}
  $edits=New-Object Collections.ArrayList
  foreach($part in @($node.FindAll({param($n) $n -is [Management.Automation.Language.TypeExpressionAst] -or $n -is [Management.Automation.Language.TypeConstraintAst] -or $n -is [Management.Automation.Language.StringConstantExpressionAst]},$true))){
    $extent=$null;$name=$null;$kind=$null
    if($part -is [Management.Automation.Language.TypeExpressionAst] -or $part -is [Management.Automation.Language.TypeConstraintAst]){
      $extent=$part.TypeName.Extent;$name=$part.TypeName.FullName;$kind='type'
    }elseif($part.Parent -is [Management.Automation.Language.CommandAst] -and $part.Parent.GetCommandName() -ceq 'New-Object' -and $part.Parent.CommandElements.Count -gt 1 -and $part.Parent.CommandElements[1] -eq $part){
      if($part.StringConstantType -ne [Management.Automation.Language.StringConstantType]::BareWord){throw 'Unplanned quoted New-Object type'}
      $extent=$part.Extent;$name=$part.Value;$kind='new-object'
    }
    if(-not $name){continue}
    if(-not $typeCounts.Contains($name)){
      if($name -cmatch '^(HelperWin32|Windows\.|WindowsRuntime|System\.Windows\.|System\.Drawing\.|CucpFixture\.)'){throw "Unplanned acquisition type: $name"}
      continue
    }
    if($extent.Text -cne $name){throw "Nonliteral oracle type extent: $name"}
    $start=$extent.StartOffset-$node.Extent.StartOffset;$end=$extent.EndOffset-$node.Extent.StartOffset
    if($start -lt 0 -or $end -gt $node.Extent.Text.Length -or $end -le $start){throw 'Oracle type extent is out of bounds'}
    [void]$edits.Add(@{start=$start;end=$end;name=$name})
    [void]$sites.Add(@{function=$record.name;kind=$kind;start_utf16=$extent.StartOffset;end_utf16=$extent.EndOffset;original=$name;replacement=$fixturePrefix+$name})
    $seen[$name]=1+[int]$seen[$name]
  }
  # Negative qualification changes only the in-memory edit plan. Neither fault
  # can reach compilation/import: the original overlap/text guard must refuse.
  if($TestTypeExtentFault -ne 'none' -and -not $faultInjected -and $edits.Count){
    $first=$edits[0]
    if($TestTypeExtentFault -eq 'duplicate'){[void]$edits.Add(@{start=$first.start;end=$first.end;name=$first.name})}
    else{$first.name='FixtureChangedType'}
    $faultInjected=$true
  }
  $body=$node.Extent.Text;$previous=$body.Length;$applied=0
  # Windows PowerShell 5.1 does not sort hashtable keys by -Property start.
  # A calculated numeric dictionary lookup works there as well as on PS6+.
  foreach($edit in @($edits|Sort-Object -Property {[int]$_['start']} -Descending)){
    $overlap=$edit.end -gt $previous
    $actual=$body.Substring($edit.start,$edit.end-$edit.start)
    if($overlap -or $actual -cne $edit.name){
      # Bounded, non-executable per-site evidence precedes the refusal. No body
      # or request data is emitted; the prefix is at most 128 UTF-16 code units.
      $diagnostic=@{schema='cucp.oracle-type-extent-refusal/v1';function=$record.name;reason=$(if($overlap){'overlap_or_order'}else{'text_mismatch'});start_utf16=$node.Extent.StartOffset+$edit.start;end_utf16=$node.Extent.StartOffset+$edit.end;previous_start_utf16=$node.Extent.StartOffset+$previous;expected_type=$edit.name;actual_prefix=$actual.Substring(0,[Math]::Min(128,$actual.Length));applied=$applied;planned=$edits.Count}
      [Console]::Error.WriteLine((ConvertTo-Json -InputObject $diagnostic -Depth 4 -Compress))
      throw 'Overlapping or changed oracle type extent'
    }
    $body=$body.Substring(0,$edit.start)+$fixturePrefix+$edit.name+$body.Substring($edit.end)
    $previous=$edit.start;$applied++
  }
  # A second AST parse proves the mechanically produced body is still a single
  # definition with the same name; only this pinned function becomes executable.
  $rewriteTokens=$null;$rewriteErrors=$null
  $rewriteAst=[Management.Automation.Language.Parser]::ParseInput($body,[ref]$rewriteTokens,[ref]$rewriteErrors)
  if($rewriteErrors.Count -or $rewriteAst.EndBlock.Statements.Count -ne 1 -or $rewriteAst.EndBlock.Statements[0] -isnot [Management.Automation.Language.FunctionDefinitionAst] -or $rewriteAst.EndBlock.Statements[0].Name -cne $record.name){throw 'Invalid substituted oracle function'}
  [void]$functions.Add(@{name=$record.name;original_sha256=$record.sha256;substituted_sha256=(Hash-Text $body);body=$body})
}
if($functions.Count -ne $importNames.Count -or $sites.Count -ne 52){throw 'Oracle substitution scope changed'}
foreach($name in $typeCounts.Keys){if($seen[$name] -ne $typeCounts[$name]){throw "Oracle type substitution count changed: $name"}}

# The fixture is pinned before compilation. Unique namespace names never ask
# the runtime to resolve native Windows/WinRT types. The assembly guard is
# fail-closed for EVERY substituted type, including enums and nested RECT.
$facadeText=[IO.File]::ReadAllText($Stubs,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
$facadeHash=Hash-Text $facadeText
if($facadeHash -cne '0c19cfcd11a7d5f0c21f9433400a1e365361ae74d3662595b719b28301656148'){throw 'Inert oracle facade hash mismatch'}
$emitted=@(Microsoft.PowerShell.Utility\Add-Type -TypeDefinition $facadeText -ReferencedAssemblies @('System.dll','System.Core.dll','System.Web.Extensions.dll') -PassThru -ErrorAction Stop)
$anchors=@($emitted|Where-Object{$_.FullName -ceq 'CucpFixture.HelperFixture'})
if($anchors.Count -ne 1){throw 'Missing unique oracle fixture assembly'}
$fixtureAssembly=$anchors[0].Assembly
$resolved=New-Object Collections.ArrayList
foreach($typeName in $typeCounts.Keys){
  $resolvedName=$fixturePrefix+$typeName
  $type=$resolvedName -as [type]
  # Negative qualification can only force a harmless, wrong-assembly type.
  # The unchanged guard below must refuse it before importing any action.
  if($TestWrongBinding){$type=[string]}
  $expected=$fixtureAssembly.GetType($resolvedName,$false,$false)
  if(-not $type -or -not $expected -or $type.Assembly -ne $fixtureAssembly -or -not [object]::ReferenceEquals($type,$expected)){throw "Unsafe oracle type resolution: $resolvedName"}
  [void]$resolved.Add($type.FullName)
}
$seam=@{schema='cucp.oracle-type-seam/v1';source_sha256=$entry.normalized_sha256;facade_sha256=$facadeHash;type_substitutions=@($sites);guarded_types=@($resolved);functions=@($functions|ForEach-Object{@{name=$_.name;original_sha256=$_.original_sha256;substituted_sha256=$_.substituted_sha256}})}
foreach($function in $functions){. ([scriptblock]::Create($function.body))}
$c=[IO.File]::ReadAllText($CasePath,[Text.Encoding]::UTF8)|ConvertFrom-Json
if($c.culture){[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$c.culture);[Threading.Thread]::CurrentThread.CurrentUICulture=[Threading.Thread]::CurrentThread.CurrentCulture}
function Convert-Case($Value) {
  if($null -eq $Value){return $null}
  if($Value -is [array]){$a=New-Object Collections.ArrayList;foreach($v in $Value){[void]$a.Add((Convert-Case $v))};return ,$a.ToArray()}
  if($Value -is [Management.Automation.PSCustomObject]){$r=@{};foreach($p in $Value.PSObject.Properties){$r[$p.Name]=Convert-Case $p.Value};return $r}
  return $Value
}
$PipeName='fixture';$Script:_StartedAt=[DateTime]::UtcNow;$Script:_RequestCount=0;$Script:_Win32Loaded=$false;$Script:_UIALoaded=$false;$Script:_OCREngine=$null;$Script:_OCRError=$null
# These acquisition seams are deliberate fixtures. No top-level server loop,
# process launch, lock mutation, input, screen capture, or real UIA is executed.
$script:effects=New-Object Collections.ArrayList
function Add-Type { param($AssemblyName,$LiteralPath,$TypeDefinition) if($TypeDefinition -or $LiteralPath){throw 'unplanned Add-Type'};if($AssemblyName -eq 'UIAutomationClient' -and $Stubs){[CucpFixture.HelperFixture]::Trace('uia.loadModal',@())};if($AssemblyName -eq 'System.Drawing' -and $Stubs){[CucpFixture.HelperFixture]::Trace('ocr.loadDrawing',@())} }
function _Ensure-Win32Loaded { if($Script:_Win32Loaded){return $true};if($Stubs){[CucpFixture.HelperFixture]::Trace('win32.ensure',@())};[void]$script:effects.Add('ensure_win32');if($c.win32){$Script:_Win32Loaded=$true;return $true};return $false }
function _Server-Ensure-UIA { if($Script:_UIALoaded){return $true};if($Stubs){[CucpFixture.HelperFixture]::Trace('uia.load',@())};[void]$script:effects.Add('ensure_uia');if($c.uia){$Script:_UIALoaded=$true;return $true};return $false }
function _Server-Ensure-OCR {
  if($Script:_OCREngine){return $true}
  if($Stubs){[CucpFixture.HelperFixture]::Trace('ocr.initialize',@())}
  [void]$script:effects.Add('ensure_ocr')
  if($c.ocr){[CucpFixture.HelperFixture]::Trace('ocr.createProfile',@());$Script:_OCREngine=New-Object CucpFixture.Windows.Media.Ocr.OcrEngine;return $true}
  $Script:_OCRError='owned fixture init failure';return $false
}
function Remove-Item { param($LiteralPath,[switch]$Force) if($Stubs){[CucpFixture.HelperFixture]::Trace('ocr.removeTemp',@([string]$LiteralPath))} }

[CucpFixture.HelperFixture]::Initialize(($c|ConvertTo-Json -Depth 50 -Compress))
$results=New-Object Collections.ArrayList
foreach($r in $c.requests){
  $value=$null;$errorValue=$null
  try {$value=_Dispatch -Action ([string]$r.action) -Args (Convert-Case $r.args)}catch{$errorValue=$_.Exception.Message}
  # Real time/PID are not deterministically replaceable in the exact function.
  if($value -and $value.schema -eq 'cucp.health/v1'){$value.pid=123;$value.uptime_s=0}
  $exitValue=0;if($errorValue -or $value.status -eq 'error'){$exitValue=1}elseif($value.status -eq 'partial'){$exitValue=2}elseif($value.status -eq 'fallback_required'){$exitValue=99};[void]$results.Add(@{id=$r.id;exit_code=$exitValue;result=$value;error=$errorValue})
}
# Keep the collection as an array even at cardinality zero or one. An untyped
# assignment from an if/pipeline loses the empty collection's JSON shape on PS5.
[object[]]$trace=@([CucpFixture.HelperFixture]::Effects.ToArray())
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{responses=@($results);effects=@($script:effects);calls=$trace;request_count=$Script:_RequestCount;oracle_seam=$seam} -Depth 50 -Compress))
