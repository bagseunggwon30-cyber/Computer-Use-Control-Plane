param(
 [Parameter(Mandatory=$true)][ValidateSet('original','candidate')][string]$Mode,
 [Parameter(Mandatory=$true)][string]$Root,
 [Parameter(Mandatory=$true)][string]$SourcePath,
 [Parameter(Mandatory=$true)][string]$ScenarioPath,
 [Parameter(Mandatory=$true)][string]$AssemblyPath
)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'This oracle requires Windows PowerShell 5.1.'}
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
$OutputEncoding=$utf8
$manifest=Get-Content -Raw -LiteralPath (Join-Path $Root 'tests\fixtures\legacy-observation\source-manifest.json') | ConvertFrom-Json
$source=[IO.File]::ReadAllText($SourcePath).Replace("`r`n","`n")
$sha=[Security.Cryptography.SHA256]::Create()
function Hash([string]$Value) { return [BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($Value))).Replace('-','').ToLowerInvariant() }
if ((Hash $source) -ne $manifest.normalized_sha256) { throw 'Immutable observation oracle source mismatch.' }
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) {throw 'Observation oracle source parse failed.'}
Add-Type -LiteralPath $AssemblyPath
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase
$scenarioJson=[IO.File]::ReadAllText($ScenarioPath)
[PcuCp.LegacyObservation.Qualification.FixtureState]::Reset($scenarioJson)
$scenario=$scenarioJson | ConvertFrom-Json
if($scenario.Culture){[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$scenario.Culture);[Threading.Thread]::CurrentThread.CurrentUICulture=[Threading.Thread]::CurrentThread.CurrentCulture}
foreach($record in $manifest.functions) {
 $matches=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $record.name},$true))
 if ($matches.Count -ne 1) {throw "Expected one function: $($record.name)"}
 $fn=$matches[0]
 if($fn.Extent.StartOffset -ne $record.start_utf16 -or $fn.Extent.EndOffset -ne $record.end_utf16 -or (Hash $fn.Extent.Text) -ne $record.sha256) {throw "AST pin mismatch: $($record.name)"}
 $text=$fn.Extent.Text
 foreach($seam in $manifest.type_seams.PSObject.Properties) {
  $actual=([regex]::Matches($text,[regex]::Escape($seam.Name))).Count
  $expected=0
  if($record.type_seams.PSObject.Properties.Name -contains $seam.Name){$expected=[int]$record.type_seams.($seam.Name)}
  if($actual -ne $expected){throw "Type seam count mismatch: $($record.name)/$($seam.Name)"}
  $text=$text.Replace($seam.Name,[string]$seam.Value)
 }
 Invoke-Expression $text
}
# These load/process/emit boundaries are inert; all acquisition is through the closed fixture types.
function _Ensure-Win32Native {return [PcuCp.LegacyObservation.Qualification.FixtureState]::EnsureWin32()}
function _Ensure-UIA {return [PcuCp.LegacyObservation.Qualification.FixtureState]::EnsureUia()}
function Get-Process { [CmdletBinding()]param([int]$Id) $name=[PcuCp.LegacyObservation.Qualification.FixtureState]::ProcessName($Id); if($null -ne $name){return [pscustomobject]@{ProcessName=$name}} }
$Script:Captured=$null
function _Emit {param($Payload,[int]$ExitCode=0) $Script:Captured=[ordered]@{payload=$Payload;exit_code=$ExitCode};throw 'OBSERVATION_EMIT_SENTINEL'}
if($Mode -eq 'candidate') {
 . (Join-Path $Root 'scripts\cucp-legacy-observation-adapter.ps1')
 function _Require-LegacyObservation {
  if($Script:_LegacyObservationActions){return}
  $Script:_LegacyObservationProvider=New-Object PcuCp.LegacyObservation.Qualification.ScriptedObservationProvider
  $Script:_LegacyObservationPrimitives=New-Object PcuCp.LegacyObservation.ObservationPrimitives($Script:_LegacyObservationProvider)
  $Script:_LegacyObservationActions=New-Object PcuCp.LegacyObservation.ObservationActions($Script:_LegacyObservationProvider)
 }
}
$X=0;$Y=0;$TargetHwnd=0;$TargetMatch='';$ClickInset=3;$ScanRadius=0;$ScanStep=6;$SkipUia=$false
$Match='';$Label='';$Role='';$MaxElements=400;$MinSize=6;$ClickRefine='none';$Button='left';$Script:_HasCoordinates=$true
foreach($option in $scenario.Options.PSObject.Properties){ if($option.Name -eq 'HasCoordinates'){$Script:_HasCoordinates=[bool]$option.Value}else{Set-Variable -Name $option.Name -Value $option.Value} }
$errorText=$null;$returnValue=$null
try {
 switch($scenario.Operation) {
  'hit-test' {_Action-HitTest}
  'hit-scan' {_Action-HitScan}
  'uia-tree' {_Action-UiaTree}
  'uia-find' {_Action-UiaFind}
  'click' {_Action-Click}
  'refine' {$returnValue=_Resolve-UiaPointRefinement -X $X -Y $Y -Inset $ClickInset}
  'guard' {$returnValue=_Test-CoordsInTarget -X $X -Y $Y -ExpectedHwnd $TargetHwnd -ExpectedMatch $TargetMatch}
  'fusion' {
   $rootEl=[PcuCp.LegacyObservation.Qualification.FixtureState]::Element('root')
   $element=[PcuCp.LegacyObservation.Qualification.FixtureState]::Element('a')
   $ocr=[pscustomobject]@{cx=10;cy=10;score=80;text='Run'}
   $fusion=_Resolve-OcrUiaFusionCandidate -RootEl $rootEl -Elements @($element) -OcrCandidates @($ocr)
   $expectedElement=$element
   if($scenario.ExpectedElement){$expectedElement=[PcuCp.LegacyObservation.Qualification.FixtureState]::Element([string]$scenario.ExpectedElement)}
   $returnValue=[ordered]@{element_identity=[object]::ReferenceEquals($fusion.Element,$expectedElement);current_identity=[object]::ReferenceEquals($fusion.Current,$expectedElement.IdentityCurrent);root_identity=[object]::ReferenceEquals($rootEl,[PcuCp.LegacyObservation.Qualification.FixtureState]::Element('root'));pattern=$fusion.PatternName;score=$fusion.FusionScore;match=$fusion.UiaMatch;depth=$fusion.ParentClimbDepth}
  }
  default {throw 'Unsupported fixture operation.'}
 }
} catch {if($_.Exception.Message -ne 'OBSERVATION_EMIT_SENTINEL'){$errorText=$_.Exception.Message}}
$result=[ordered]@{schema='cucp.observation-oracle/v1';runtime=[ordered]@{powershell=$PSVersionTable.PSVersion.ToString();clr=[Environment]::Version.ToString();culture=[Threading.Thread]::CurrentThread.CurrentCulture.Name};scenario=$scenario.Name;mode=$Mode;captured=$Script:Captured;return_value=$returnValue;error=$errorText;acquisition=@([PcuCp.LegacyObservation.Qualification.FixtureState]::Trace);inert_mutations=[PcuCp.LegacyObservation.Qualification.FixtureState]::Mutations}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Depth 40 -Compress))
$sha.Dispose()
