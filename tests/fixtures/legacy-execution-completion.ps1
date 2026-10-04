param([string]$Source,[string]$DiagnosticSource,[string]$InputPath,[string]$HostPath,[int]$ExpectedMajor)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne $ExpectedMajor){throw 'Unexpected PowerShell parser version'}
if($ExpectedMajor -eq 5 -and $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
# Independent renderer characterization: the existing envelope admits depth 0,
# but the PS5 cmdlet's own parameter contract requires depth at least 1.
$zeroDepthOutput=$null;$zeroDepthError=$null
try{$zeroDepthOutput=Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject 'fixture' -Depth 0}
catch{$zeroDepthError=$_.Exception.Message}
$names=@('_Execution-Require','_Execution-Fields','_Execution-EncodeWire','_Execution-DecodeWire',
 '_Execution-ValidateEffect','_Execution-Dispatch','_Execution-EffectMayChangeState',
 '_Execution-WriteChunks','_Execution-WriteDiagnostic','_Invoke-LegacyExecutionEffectLoop','_Invoke-LegacyExecutionHost')
foreach($load in @(@{path=$Source;names=$names},@{path=$DiagnosticSource;names=@('_Diagnostic-PreparePayload')})){
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($load.path,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Production transport source did not parse'}
 foreach($name in $load.names){
  $found=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
  if($found.Count -ne 1){throw "Expected one production function: $name"}
  . ([scriptblock]::Create($found[0].Extent.Text))
 }
}
# Sole acquisition leaf: record an owned-write request, never write history or
# invoke a provider. The real validator/dispatcher/state classification stay intact.
function _Trajectory-Append {param($Kind,$Payload) $script:dispatches++;return}
$env:CUCP_NATIVE_HOST=$HostPath;$env:CUCP_EXECUTION_DIAGNOSTICS='0'
$rows=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $env:CUCP_COMPLETION_FIXTURE=[string]$case.fixture
 $fixture=Get-Content -LiteralPath $case.fixture -Raw -Encoding UTF8|ConvertFrom-Json
 $parsed=$fixture.completion|ConvertFrom-Json
 $exitType=if($null -eq $parsed.exit){$null}else{$parsed.exit.GetType().FullName}
 $depthType=if($null -eq $parsed.json_depth){$null}else{$parsed.json_depth.GetType().FullName}
 $operation=switch($case.family){'execution'{'workflow-run'};'interaction'{'click-point'};'diagnostics'{'perf'}}
 $entry=switch($case.family){'execution'{'legacy-execution-session'};'interaction'{'legacy-interaction-session'};'diagnostics'{'legacy-diagnostic-session'}}
 $startup=[ordered]@{schema='cucp.execution-start/v1';operation=$operation;rest=@();brief=$false;cache_seconds=5;vision_available=$false;culture=''}
 if($case.family -ceq 'interaction'){$startup.schema='cucp.interaction-start/v1';$startup['double']=$false;$startup['right_click']=$false}
 if($case.family -ceq 'diagnostics'){
  $startup.schema='cucp.diagnostic-start/v1';$startup['context']=[ordered]@{}
  foreach($key in @('audit_directory','cache_directory','wrapper_log','cli_path','changelog_path','temp_root','benchmark_schema','release_schema')){$startup.context[$key]='fixture'}
 }
 $state=@{family=[string]$case.family;operation=$operation;live=$false;sensitive=$false;paths=@{};clocks=@{};
  rest=@();pipeline_output=(New-Object Collections.ArrayList)}
 if($case.family -ceq 'interaction'){[void]$state.pipeline_output.Add('buffered pipeline fixture')}
 $script:dispatches=0;$script:errorText=$null
 $previous=[Console]::Out;$capture=New-Object IO.StringWriter
 try {
  [Console]::SetOut($capture)
  $pipeline=@(& {try {_Invoke-LegacyExecutionHost -EntryPoint $entry -Startup $startup -State $state}
   catch {$script:errorText=$_.Exception.Message}})
 } finally {[Console]::SetOut($previous)}
 [void]$rows.Add(@{case=$case.case;error=$script:errorText;pipeline=$pipeline;pipeline_types=@(foreach($item in $pipeline){$item.GetType().FullName});console=$capture.ToString();
  dispatches=$script:dispatches;state_effect_seen=$state.state_effect_seen;live_effect_seen=$state.live_effect_seen;
  phase=$state.diagnostic_phase;exit_type=$exitType;depth_type=$depthType})
 $capture.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{major=$PSVersionTable.PSVersion.Major;zero_depth_output=$zeroDepthOutput;zero_depth_error=$zeroDepthError;rows=@($rows)} -Depth 20 -Compress))
