param(
 [string]$Source,[string]$BaselineSource,[string]$InputPath,
 [string]$SharedSource,[string]$AdapterSource,[string]$OracleSource,
 [switch]$ValidateDescriptors,[switch]$AllowPortableHost
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if(-not $AllowPortableHost -and ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1)){throw 'Expected Windows PowerShell 5.1'}
if(-not $OracleSource){$OracleSource=Join-Path $PSScriptRoot 'legacy-interaction-oracle.ps1'}
$oracle=Get-Content -LiteralPath $OracleSource -Raw -Encoding UTF8

# Reuse the accepted oracle's captured native leaves and result envelope. No
# process bridge, source corpus, or legacy algorithm is copied into this runner.
# The source transport functions are AST-loaded, never the script entry point.
$install=@'
$st=$null;$se=$null;$sa=[Management.Automation.Language.Parser]::ParseFile($SharedSource,[ref]$st,[ref]$se)
if($se.Count){throw 'Shared execution source did not parse'}
$required=@('_Execution-Require','_Execution-Fields','_Execution-EncodeWire','_Execution-DecodeWire',
 '_Execution-ValidateEffect','_Execution-Dispatch')
if(-not $ValidateDescriptors){$required+=@('_Read-StandaloneConfirmation','_Invoke-LegacyCompatibility',
 '_Execution-WriteChunks','_Execution-WriteDiagnostic','_Invoke-LegacyExecutionEffectLoop','_Invoke-LegacyExecutionHost')}
foreach($name in $required){
 $definition=@($sa.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($definition.Count -ne 1){throw "Required shared interaction transport function is absent: $name"}
}
foreach($definition in @($sa.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and
 ($n.Name -like '_Execution-*' -or $n.Name -in $required)},$true))){. ([scriptblock]::Create($definition.Extent.Text))}
$at=$null;$ae=$null;$aa=[Management.Automation.Language.Parser]::ParseFile($AdapterSource,[ref]$at,[ref]$ae)
if($ae.Count){throw 'Interaction adapter source did not parse'}
$definitions=@($aa.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true))
foreach($name in @('_Interaction-ValidateEffect','_Interaction-Dispatch','_Invoke-LegacyInteractionFamily',
 'Invoke-MacroFindLabel','Invoke-MacroClickPoint','Invoke-MacroClickLabel','Invoke-MacroSafeType',
 'Invoke-MacroIconFind','Invoke-MacroIconClick','Invoke-MacroOcrClick','Invoke-MacroPrecisionValidate')){
 if(@($definitions|Where-Object {$_.Name -ceq $name}).Count -ne 1){throw "Required interaction hook is absent: $name"}
}
foreach($definition in $definitions){
 $body=$definition.Extent.Text
 if($definition.Name -ceq '_Interaction-Dispatch'){
  # Only clock/ID nondeterminism and output observation are intercepted. The
  # actual family dispatch, descriptor validation, framing and host stay intact.
  $body=$body.Replace('[Diagnostics.Stopwatch]::StartNew()','(New-FakeStopwatch)')
  $body=$body.Replace("[guid]::NewGuid().ToString('N').Substring(0,12)",'(New-CapturedObservationId)')
  if(-not $body.Contains('[Console]::Out.Write([string]$d)')){throw 'Missing interaction raw Console capture seam'}
  $body=$body.Replace('[Console]::Out.Write([string]$d)',"Capture-Effect 'Console' -Name 'write' -Data ([string]`$d)")
  if(-not $body.Contains('[void]$State.pipeline_output.Add([string]$d)')){throw 'Missing interaction pipeline capture seam'}
  $body=$body.Replace('[void]$State.pipeline_output.Add([string]$d)',"Capture-Effect 'PipelineOutput' -Data ([string]`$d);[void]`$State.pipeline_output.Add([string]`$d)")
 }
 . ([scriptblock]::Create($body))
}
$Script:CacheDir='C:\fixture'
'@

if($ValidateDescriptors){
 # Install exactly the same captured leaves as the original oracle without
 # loading its accepted macro bodies or entering its fixture loop.
 $ot=$null;$oe=$null;$oa=[Management.Automation.Language.Parser]::ParseInput($oracle,[ref]$ot,[ref]$oe)
 if($oe.Count){throw 'Interaction oracle did not parse'}
 foreach($definition in @($oa.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true))){
  if($definition.Name -cne 'ConvertTo-Json'){. ([scriptblock]::Create($definition.Extent.Text))}
 }
 . ([scriptblock]::Create($install))
 $rows=New-Object Collections.ArrayList
 foreach($row in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
  $script:fixture=[pscustomobject]@{replies=@($null)};$script:cursor=0
  $script:trace=New-Object Collections.ArrayList;$script:pipeline=New-Object Collections.ArrayList
  $state=@{family='interaction';operation=[string]$row.operation;live=[bool]$row.live;sensitive=[bool]$row.sensitive;
   rest=@();paths=@{};clocks=@{};pipeline_output=(New-Object Collections.ArrayList);live_effect_seen=$false;
   interaction_observations=(New-Object Collections.ArrayList);interaction_screenshots=(New-Object Collections.ArrayList);
   interaction_cache_keys=(New-Object Collections.ArrayList);interaction_anchor_records=(New-Object Collections.ArrayList)}
  if($null -ne $row.receipts){
   foreach($key in @('observations','screenshots','cache_keys')){
    foreach($value in @($row.receipts.$key)){[void]$state['interaction_'+$key].Add([string]$value)}
   }
   foreach($record in @($row.receipts.anchor_records)){
    [void]$state.interaction_anchor_records.Add((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $record -Depth 100 -Compress))
   }
  }
  $effect=$row.effect;$errorText=$null
  try {
   if($row.shared){
    $effect.data=_Execution-EncodeWire $effect.data
    # The shared validator alone decodes the tagged data, then calls the hook.
    _Execution-ValidateEffect $effect $state
    _Execution-Dispatch $effect $state | Out-Null
   }else{
    _Interaction-ValidateEffect $effect $state
    _Interaction-Dispatch $effect $state | Out-Null
   }
  }catch{$errorText=$_.Exception.Message}
  [void]$rows.Add(@{error=$errorText;effects=(Encode-Wire @($script:trace));consumed=$script:cursor})
 }
 [Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @($rows) -Depth 100 -Compress))
 return
}

if(-not $env:CUCP_INTERACTION_TEST_HOST){throw 'CUCP_INTERACTION_TEST_HOST must name the actual compiled native host'}
if(-not (Test-Path -LiteralPath $env:CUCP_INTERACTION_TEST_HOST -PathType Leaf)){throw 'Configured interaction native host is missing'}
if([IO.Path]::GetExtension($env:CUCP_INTERACTION_TEST_HOST) -notin @('.exe','.dll')){throw 'Interaction test host must be a compiled executable or DLL'}
$env:CUCP_NATIVE_HOST=$env:CUCP_INTERACTION_TEST_HOST

# Every replacement is a narrow harness seam and must match exactly once. The
# unmodified oracle file and its 854 ordinary + 12 boundary inputs stay shared.
$marker='$Script:CucpV14Schema='
if(([regex]::Matches($oracle,[regex]::Escape($marker))).Count -ne 1){throw 'Missing unique oracle installation seam'}
$oracle=$oracle.Replace($marker,$install+"`n"+$marker)
$capture='if([object]::ReferenceEquals([Console]::Out,$script:topConsole))'
if(([regex]::Matches($oracle,[regex]::Escape($capture))).Count -ne 1){throw 'Missing unique payload capture seam'}
# Protocol/startup JSON is compressed. Only the final user-facing report may
# become the oracle payload, including array/scalar reports with no schema key.
$oracle=$oracle.Replace($capture,'if(-not $Compress -and [object]::ReferenceEquals([Console]::Out,$script:topConsole))')
$invoke='$exit=& $function @named'
if(([regex]::Matches($oracle,[regex]::Escape($invoke))).Count -ne 1){throw 'Missing unique oracle invocation seam'}
$oracle=$oracle.Replace($invoke,@'
$emitted=@(& $function @named)
if($emitted.Count -lt 1 -or $emitted[-1] -isnot [int]){throw 'Interaction adapter did not return a final integer'}
$exit=$emitted[-1]
$actualPipeline=@(if($emitted.Count -gt 1){$emitted[0..($emitted.Count-2)]})
if($actualPipeline.Count -ne $script:pipeline.Count){throw 'Interaction adapter lost or duplicated buffered pipeline output'}
for($pi=0;$pi -lt $actualPipeline.Count;$pi++){
 if($actualPipeline[$pi] -isnot [string] -or $actualPipeline[$pi] -cne $script:pipeline[$pi]){throw 'Interaction adapter changed pipeline output order or type'}
}
'@)
& ([scriptblock]::Create($oracle)) -Source $Source -BaselineSource $BaselineSource -InputPath $InputPath -AllowPortableHost:$AllowPortableHost
