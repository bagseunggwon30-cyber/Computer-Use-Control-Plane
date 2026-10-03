param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Manifest,[Parameter(Mandatory=$true)][string]$CasePath,[string]$Stubs)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
function Hash-Text([string]$Text) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
$pin=[IO.File]::ReadAllText($Manifest,[Text.Encoding]::UTF8)|ConvertFrom-Json
$entry=@($pin.files|Where-Object{$_.path -eq 'scripts/cucp-helper-server.ps1'})[0]
$sourceText=[IO.File]::ReadAllText($Source,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
if((Hash-Text $sourceText) -cne $entry.normalized_sha256){throw 'Published server source hash mismatch'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Published server source AST parse failed'}
foreach($record in $entry.functions) {
  $matches=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $record.name},$true))
  if($matches.Count -ne 1){throw "Expected exact function: $($record.name)"}
  $node=$matches[0]
  if($node.Extent.StartOffset -ne $record.start_utf16 -or $node.Extent.EndOffset -ne $record.end_utf16 -or (Hash-Text $node.Extent.Text) -cne $record.sha256){throw "Published AST extent changed: $($record.name)"}
  if(-not $record.parent_function){. ([scriptblock]::Create($node.Extent.Text))}
}
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
function Add-Type { param($AssemblyName,$LiteralPath,$TypeDefinition) if($TypeDefinition -or $LiteralPath){throw 'unplanned Add-Type'};if($AssemblyName -eq 'UIAutomationClient' -and $Stubs){[HelperFixture]::Trace('uia.loadModal',@())};if($AssemblyName -eq 'System.Drawing' -and $Stubs){[HelperFixture]::Trace('ocr.loadDrawing',@())} }
function _Ensure-Win32Loaded { if($Script:_Win32Loaded){return $true};if($Stubs){[HelperFixture]::Trace('win32.ensure',@())};[void]$script:effects.Add('ensure_win32');if($c.win32){$Script:_Win32Loaded=$true;return $true};return $false }
function _Server-Ensure-UIA { if($Script:_UIALoaded){return $true};if($Stubs){[HelperFixture]::Trace('uia.load',@())};[void]$script:effects.Add('ensure_uia');if($c.uia){$Script:_UIALoaded=$true;return $true};return $false }
function _Server-Ensure-OCR {
  if($Script:_OCREngine){return $true}
  if($Stubs){[HelperFixture]::Trace('ocr.initialize',@())}
  [void]$script:effects.Add('ensure_ocr')
  if($c.ocr){[HelperFixture]::Trace('ocr.createProfile',@());$Script:_OCREngine=New-Object Windows.Media.Ocr.OcrEngine;return $true}
  $Script:_OCRError='owned fixture init failure';return $false
}
function Remove-Item { param($LiteralPath,[switch]$Force) if($Stubs){[HelperFixture]::Trace('ocr.removeTemp',@([string]$LiteralPath))} }

if($Stubs){Microsoft.PowerShell.Utility\Add-Type -Path $Stubs -ReferencedAssemblies @("System.dll","System.Core.dll","System.Web.Extensions.dll") -ErrorAction Stop;[HelperFixture]::Initialize(($c|ConvertTo-Json -Depth 50 -Compress))
  foreach($typeName in @('HelperWin32','System.Windows.Automation.AutomationElement','System.Drawing.Bitmap','System.Drawing.Graphics','System.Windows.Forms.Screen','System.Windows.Forms.SystemInformation','System.Drawing.Size','System.Drawing.Imaging.ImageFormat','Windows.Storage.StorageFile','Windows.Graphics.Imaging.BitmapDecoder','Windows.Graphics.Imaging.SoftwareBitmap','Windows.Storage.Streams.IRandomAccessStream','Windows.Media.Ocr.OcrEngine','WindowsRuntimeSystemExtensions')){
    $type=$typeName -as [type]
    if(-not $type -or $type.Assembly -ne [HelperFixture].Assembly){throw "Unsafe oracle type resolution: $typeName"}
  }
}
$results=New-Object Collections.ArrayList
foreach($r in $c.requests){
  $value=$null;$errorValue=$null
  try {$value=_Dispatch -Action ([string]$r.action) -Args (Convert-Case $r.args)}catch{$errorValue=$_.Exception.Message}
  # Real time/PID are not deterministically replaceable in the exact function.
  if($value -and $value.schema -eq 'cucp.health/v1'){$value.pid=123;$value.uptime_s=0}
  $exitValue=0;if($errorValue -or $value.status -eq 'error'){$exitValue=1}elseif($value.status -eq 'partial'){$exitValue=2}elseif($value.status -eq 'fallback_required'){$exitValue=99};[void]$results.Add(@{id=$r.id;exit_code=$exitValue;result=$value;error=$errorValue})
}
$trace=if($Stubs){@([HelperFixture]::Effects)}else{@()};[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{responses=@($results);effects=@($script:effects);calls=$trace;request_count=$Script:_RequestCount} -Depth 50 -Compress))
