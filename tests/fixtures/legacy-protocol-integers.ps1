param([string]$Source,[string]$DiagnosticSource,[string]$InputPath)
# Inert protocol validation only. Every reachable acquisition/append leaf is a
# same-scope counter; the real entry points, dispatchers and providers are not loaded.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
foreach($load in @(
 @{path=$Source;names=@('_Read-OptValue','_Read-Switch','_Execution-Require','_Execution-Fields','_Execution-EncodeWire','_Execution-DecodeWire','_Execution-ValidateEffect','_Precision-Require','_Precision-Fields','_Precision-ReadEffect','Invoke-MacroAppProfile')},
 @{path=$DiagnosticSource;names=@('_Diagnostic-Require','_Diagnostic-Fields','_Diagnostic-ArgvEquals','_Diagnostic-Value','_Diagnostic-IntOption','_Diagnostic-NewState','_Diagnostic-Limit','_Diagnostic-ValidateEffect')}
)){
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($load.path,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ('Protocol source failed to parse: '+$load.path)}
 foreach($name in $load.names){
  $found=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
  if($found.Count -ne 1){throw ('Expected one protocol definition: '+$name)}
  . ([scriptblock]::Create($found[0].Extent.Text))
 }
}
function Fixture-Leaf {$script:leafCalls++;return [pscustomobject]@{Json=$null}}
function _Build-CoordMap {param($From,$X,$Y,$NormX,$NormY,$HasNorm,$TargetHwnd,$TargetMatch) Fixture-Leaf}
function _Native-HitTestPoint {param($X,$Y,$TargetHwnd,$TargetMatch) Fixture-Leaf}
function _Build-CoordProfile {param($HasPoint,$X,$Y,$TargetHwnd,$TargetMatch) Fixture-Leaf}
function _PointPlan-CacheKey {param($X,$Y,$Radius,$Step,$ClickInset,$TargetHwnd,$TargetMatch,$Precheck,$CoordSignature) return 'owned-key'}
function _PointPlan-ReadCache {param($Key,$MaxAgeSeconds) Fixture-Leaf}
function _Invoke-LegacyCompatibility {param($Operation,$Arguments) if($Operation -cne 'app-profile-advance'){throw 'Unexpected pure operation'};return $script:profileState}
function _AppStrategy-Append {param($AppKey,$AppType,$Strategy,$Confidence,$Score,$Process,$Class,$Title) $script:leafCalls++;return [pscustomobject]@{success=$true}}
function Fixture-Effect([string]$Kind,$Data,[string[]]$Argv=@(),[string]$Name=''){
 return [pscustomobject]@{kind=$Kind;name=$Name;argv=[object[]]$Argv;data=(_Execution-EncodeWire $Data);live=$false;quiet=$false;brief=$false;confirm_sensitive=$false}
}
function Fixture-Value($Case){
 switch -CaseSensitive ($Case.representation){
  'int32' {return [int]$Case.value};'int64' {return [long]$Case.value}
  'double' {return [double]$Case.value};'decimal' {return [decimal]$Case.value}
  'json' {return ,$Case.value};default {throw 'Unknown inert numeric representation'}
 }
}
function Fixture-Run($Case,$Value){
 $expected=[int]$Case.expected_number
 if($Case.field -cin @('execution_elapsed','execution_sleep')){
  $state=@{family='execution';live=$false;sensitive=$false}
  $effect=if($Case.field -ceq 'execution_elapsed'){Fixture-Effect 'HistoryAppend' ([pscustomobject]@{success=$true;elapsed_ms=$Value}) @('label','match','strategy')}else{Fixture-Effect 'Sleep' $Value}
  _Execution-ValidateEffect $effect $state;return
 }
 if($Case.field -cin @('precision_x','precision_y','precision_age')){
  $x=0;$y=0;if($Case.field -ceq 'precision_x'){$x=$expected};if($Case.field -ceq 'precision_y'){$y=$expected}
  $state=@{operation='point-plan';rest=@('--x',"$x",'--y',"$y");reads=0;cache_seconds=5;cache_dir='C:\fixture\cache';profile=[pscustomobject]@{coord_signature='fixed'};precheck=[pscustomobject]@{matched=$true}}
  if($Case.field -ceq 'precision_age'){
   $state.reads=2;$state.rest+=@('--cache-ttl',"$expected")
   $effect=[pscustomobject]@{kind='cache-read';args=[pscustomobject]@{directory=$state.cache_dir;key='owned-key';max_age_seconds=$Value}}
  }else{
   $p=[ordered]@{x=$x;y=$y;target_hwnd=[long]0;target_match=''}
   if($Case.field -ceq 'precision_x'){$p.x=$Value}else{$p.y=$Value}
   switch -CaseSensitive ($Case.variant){
    'coord-map' {$state.operation='coord-anchor';$p.from='screen';$p.norm_x=0;$p.norm_y=0;$p.has_norm=$false}
    'hit-test' {}
    'coord-profile' {$state.reads=1;$p.has_point=$true}
    default {throw 'Unknown inert precision kind'}
   }
   $effect=[pscustomobject]@{kind=$Case.variant;args=[pscustomobject]$p}
  }
  $null=_Precision-ReadEffect $effect $state;return
 }
 if($Case.field -ceq 'profile_score'){
  $script:AppStrategyFile='C:\fixture\history.jsonl';$Brief=$false
  $confidence=if($expected -ge 75){'high'}else{'medium'}
  $query=[pscustomobject]@{kind='record';argv=@('app','type','route',$confidence,"$expected",'proc','class','title')}
  $ready=[pscustomobject]@{state='complete';queries=@($query);payload=[pscustomobject]@{schema='cucp.app-profile/v1';elapsed_ms=0;strategy_persistence=[pscustomobject]@{record=$null;recorded=$false}};json_depth=8;exit=0;brief=''}
  $script:profileState=[pscustomobject]@{facade='cucp.app-profile-controller/v1';kernel_evaluations=2;state='query';queries=@($query);query=$query;record_completion=$ready;record_authorization=[pscustomobject]@{schema='cucp.app-profile-record-authorization/v1';history_file=$script:AppStrategyFile;strategy_score=[pscustomobject]@{total_score=$Value;confidence=$confidence};query=$query}}
  $previous=[Console]::Out;$capture=New-Object IO.StringWriter
  try{[Console]::SetOut($capture);$null=Invoke-MacroAppProfile -Rest @('--record-strategy')}finally{[Console]::SetOut($previous);$capture.Dispose()}
  return
 }
 $context=[pscustomobject]@{audit_directory='C:\fixture\audit';cache_directory='C:\fixture\cache';wrapper_log='C:\fixture\wrapper.log';cli_path='C:\fixture\cli.mjs';changelog_path='C:\fixture\CHANGELOG.md';temp_root='C:\fixture\temp';benchmark_schema='benchmark';release_schema='release'}
 $op='self-test';$rest=@();$kind='';$payload=$null
 switch -CaseSensitive ($Case.field){
  'diagnostic_tail' {$op='log-tail';$rest=@('--max-bytes',"$expected");$kind='TailBytes';$payload=[pscustomobject]@{path=$context.wrapper_log;max_bytes=$Value}}
  'diagnostic_current' {$op='diagnose-lag';$kind='ProcessMetrics';$payload=[pscustomobject]@{current_ordinal=$Value;previous_ordinal=0}}
  'diagnostic_previous' {$op='diagnose-lag';$kind='ProcessMetrics';$payload=[pscustomobject]@{current_ordinal=0;previous_ordinal=$Value}}
  'diagnostic_sleep' {$op='diagnose-lag';$rest=@('--sample-ms',"$expected");$kind='Sleep';$payload=$Value}
  'diagnostic_age' {$kind='Appshot';$payload=[pscustomobject]@{match='selftest-cache';semantic=$false;no_cache=$false;cache_max_seconds=$Value}}
  'diagnostic_count' {$kind='Uia';$rest=@('--deep');$payload=[pscustomobject]@{focused_window='';max_elements=$Value}}
  default {throw 'Unknown inert integer field'}
 }
 $state=_Diagnostic-NewState -Operation $op -Rest $rest -Context $context
 if($kind -ceq 'Sleep'){[void]$state.diagnostic_process_lists.Add([object[]]@())}
 if($kind -ceq 'ProcessMetrics'){
  foreach($i in @(0,1)){$pidValue=if($i -eq 0 -and $Case.variant -ceq 'no-previous'){43}else{42};[void]$state.diagnostic_process_lists.Add([object[]]@());[void]$state.diagnostic_process_rows.Add([object[]]@([pscustomobject]@{id=$pidValue}))}
  $state.diagnostic_counts['processor-count']=1;$state.diagnostic_metric_order=@(0)
 }
 $effect=Fixture-Effect 'Diagnostic' ([pscustomobject]@{name='';value=$payload}) @() $kind
 _Execution-ValidateEffect $effect $state
}
$rows=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:leafCalls=0;$value=Fixture-Value $case;$errorText=$null
 try{Fixture-Run $case $value}catch{$errorText=$_.Exception.Message}
 [void]$rows.Add([pscustomobject]@{id=$case.id;accepted=($null -eq $errorText);error=$errorText;leaf_calls=$script:leafCalls;type=if($null -eq $value){'null'}else{$value.GetType().Name}})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject ([object[]]$rows.ToArray()) -Depth 8 -Compress))
