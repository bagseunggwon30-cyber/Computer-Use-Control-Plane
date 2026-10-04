# Read-only diagnostic. This is separate from all unchanged actual-entry proof.
param(
 [Parameter(Mandatory=$true)][ValidateSet('original','candidate','shared-current','intended-current','candidate-warm')][string]$Mode,
 [Parameter(Mandatory=$true)][string]$Root,
 [Parameter(Mandatory=$true)][string]$SourcePath,
 [Parameter(Mandatory=$true)][string]$ReadinessPath,
 [Parameter(Mandatory=$true)][string]$ProbeAssembly,
 [string]$InitializerAssembly
)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Provider diagnostics require Windows PowerShell 5.1.'}
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
$OutputEncoding=$utf8
Add-Type -LiteralPath $ProbeAssembly
[PcuCp.ObservationProviderProbe.ProviderLoadProbe]::Start()
$ready=[IO.File]::ReadAllText($ReadinessPath) | ConvertFrom-Json
$manifest=[IO.File]::ReadAllText((Join-Path $Root 'tests\fixtures\legacy-observation\source-manifest.json')) | ConvertFrom-Json
$source=[IO.File]::ReadAllText($SourcePath).Replace("`r`n","`n")
$sha=[Security.Cryptography.SHA256]::Create()
$sourceHash=[BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($source))).Replace('-','').ToLowerInvariant()
$sha.Dispose()
if($sourceHash -cne $manifest.normalized_sha256){throw 'Provider diagnostic immutable-source mismatch.'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Provider diagnostic source parse failed.'}
foreach($name in @('_Ensure-Win32Native','_Ensure-UIA')){
 $functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
 if($functions.Count -ne 1){throw 'Provider diagnostic expected one original loader.'}
 Invoke-Expression $functions[0].Extent.Text
}
$Script:_Win32Loaded=$false;$Script:_UIALoaded=$false
$stages=New-Object System.Collections.ArrayList
function Snapshot([string]$Stage){
 $assemblies=@(foreach($assembly in [AppDomain]::CurrentDomain.GetAssemblies()){
  if($assembly.GetName().Name -match 'UIAutomation|WindowsBase|LegacyObservation'){
   [ordered]@{name=$assembly.FullName;location=$assembly.Location;image_runtime=$assembly.ImageRuntimeVersion;module_id=$assembly.ManifestModule.ModuleVersionId.ToString()}
  }
 })
 [void]$stages.Add([ordered]@{stage=$Stage;assemblies=$assemblies})
}
Snapshot 'before-original-loaders'
$win32=_Ensure-Win32Native
Snapshot 'after-original-win32'
$uia=_Ensure-UIA
Snapshot 'after-original-uia'
$originalUiaType=[System.Windows.Automation.AutomationElement]
$primedRoot=$null
if($Mode -in @('intended-current','candidate-warm')){
 if(-not $InitializerAssembly){throw 'Intended diagnostic requires the fixed compiled initializer.'}
 Add-Type -LiteralPath $InitializerAssembly
 $primedRoot=[PcuCp.ObservationIntendedProvider.PublicUiaInitialization]::FromOwnedHandle([long]$ready.hwnd)
 if($primedRoot.Current.NativeWindowHandle -ne $ready.hwnd -or $primedRoot.Current.ProcessId -ne $ready.pid){throw 'Compiled initialization escaped owned HWND/PID.'}
 Snapshot 'after-fixed-public-initialization'
}
$originalElement=$null;$originalCurrent=$null
if($Mode -in @('shared-current','intended-current')){
 $originalElement=$originalUiaType::FromHandle([IntPtr][long]$ready.hwnd)
 $originalCurrent=$originalElement.Current
 Snapshot 'after-original-cross-boundary-acquisition'
}
$provider=$null
$crossBoundary=$null
if($Mode -ne 'original'){
 . (Join-Path $Root 'scripts\cucp-legacy-observation-adapter.ps1')
 _Require-LegacyObservation
 $provider=$Script:_LegacyObservationProvider
 Snapshot 'after-candidate-construction'
 if($Mode -in @('shared-current','intended-current')){
 $directBounds=$null;$directBoundsError=$null
 try{$directBounds=$provider.Bounds($originalCurrent)}catch{$directBoundsError=$_.Exception.Message}
 try{
  $crossPayload=$Script:_LegacyObservationPrimitives.MatchPayload($originalCurrent,'')
  $crossBoundary=[ordered]@{element_assembly=$originalElement.GetType().Assembly.FullName;current_type=$originalCurrent.GetType().AssemblyQualifiedName;direct_bounds=$directBounds;direct_bounds_error=$directBoundsError;payload=$crossPayload;error=$null}
 }catch{$crossBoundary=[ordered]@{element_assembly=$originalElement.GetType().Assembly.FullName;current_type=$originalCurrent.GetType().AssemblyQualifiedName;direct_bounds=$directBounds;direct_bounds_error=$directBoundsError;payload=$null;error=$_.Exception.Message}}
 Snapshot 'after-shared-current-boundary'
 }
}
$ownedBoundaries=New-Object System.Collections.ArrayList
if($Mode -in @('intended-current','candidate-warm')){
 foreach($control in @(@{key='run';id='RunButton';pattern='Invoke'},@{key='edit';id='FixtureEdit';pattern='Value'})){
  $ownedGeometry=$ready.($control.key)
  $ownedHwnd=$provider.WindowFromPoint([int]$ownedGeometry.center_x,[int]$ownedGeometry.center_y)
  if($ownedHwnd -le 0){throw 'Owned button/edit has no Win32 handle at its known center.'}
  $ownedElement=$originalUiaType::FromHandle([IntPtr]$ownedHwnd)
  $ownedCurrent=$ownedElement.Current
  $nativeElement=$provider.FromHandle($ownedHwnd)
  $patternKind=[Enum]::Parse([PcuCp.LegacyObservation.ObservationPattern],[string]$control.pattern)
  $ownedPattern=$provider.Pattern($ownedElement,$patternKind)
  $patternReadOnly=$null;if($control.pattern -eq 'Value'){$patternReadOnly=$provider.ValueReadOnly($ownedPattern)}
  $ownedPayload=$Script:_LegacyObservationPrimitives.MatchPayload($ownedCurrent,$control.pattern+'Pattern')
  [void]$ownedBoundaries.Add([ordered]@{control=$control.key;point_x=[int]$ownedGeometry.center_x;point_y=[int]$ownedGeometry.center_y;expected_hwnd=$ownedHwnd;original_hwnd=$ownedCurrent.NativeWindowHandle;candidate_hwnd=$nativeElement.Current.NativeWindowHandle;original_pid=$ownedCurrent.ProcessId;candidate_pid=$nativeElement.Current.ProcessId;automation_identity=[System.Windows.Automation.Automation]::Compare($ownedElement,$nativeElement);element_type=$ownedElement.GetType().AssemblyQualifiedName;current_type=$ownedCurrent.GetType().AssemblyQualifiedName;direct_bounds=$provider.Bounds($ownedCurrent);payload=$ownedPayload;pattern_type=$ownedPattern.GetType().AssemblyQualifiedName;value_readonly=$patternReadOnly})
 }
 Snapshot 'after-owned-button-edit-boundaries'
}
$records=New-Object System.Collections.ArrayList
$errorText=$null
try{
 if(-not $win32 -or -not $uia){throw 'Original load boundary is unavailable.'}
 if($Mode -eq 'original'){
  $rootElement=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$ready.hwnd)
  Snapshot 'after-original-from-handle'
  $elements=$rootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
 }else{
  $rootElement=$provider.FromHandle([long]$ready.hwnd)
  Snapshot 'after-candidate-from-handle'
  $elements=$provider.Descendants($rootElement)
 }
 foreach($element in $elements){
  if($records.Count -ge 24){break}
  $current=$element.Current
  $pattern=$null;try{$patternType=$element.GetType().Assembly.GetType('System.Windows.Automation.InvokePattern');$patternId=$patternType.GetField('Pattern').GetValue($null);$pattern=$element.GetCurrentPattern($patternId)}catch{}
  $providerDescription=$null;try{$providerDescription=$element.GetCurrentPropertyValue($element.GetType().GetField('ProviderDescriptionProperty').GetValue($null))}catch{$providerDescription=$_.Exception.Message}
  [void]$records.Add([ordered]@{element_assembly=$element.GetType().Assembly.FullName;current_type=$current.GetType().AssemblyQualifiedName;name=$current.Name;automation_id=$current.AutomationId;role=$current.LocalizedControlType;offscreen=$current.IsOffscreen;invoke_pattern_type=if($pattern){$pattern.GetType().AssemblyQualifiedName}else{$null};provider_description=$providerDescription})
 }
 Snapshot 'after-descendant-properties'
}catch{$errorText=$_.Exception.Message;Snapshot 'after-diagnostic-error'}
$result=[ordered]@{schema='cucp.observation-provider-diagnostic/v1';mode=$Mode;source_hash=$sourceHash;pid=$PID;powershell=$PSVersionTable.PSVersion.ToString();clr=[Environment]::Version.ToString();thread_apartment=[Threading.Thread]::CurrentThread.ApartmentState.ToString();target_pid=[int]$ready.pid;target_hwnd=[long]$ready.hwnd;original_resolved_uia_type=$originalUiaType.AssemblyQualifiedName;shared_current_boundary=$crossBoundary;owned_object_boundaries=@($ownedBoundaries);stages=@($stages);records=@($records);first_chance_uia=@([PcuCp.ObservationProviderProbe.ProviderLoadProbe]::Snapshot());first_chance_dropped=[PcuCp.ObservationProviderProbe.ProviderLoadProbe]::Dropped;error=$errorText}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Depth 12 -Compress))
if($errorText){exit 1}
