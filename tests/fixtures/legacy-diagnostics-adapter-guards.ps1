param([Parameter(Mandatory=$true)][string]$BridgeSource,[Parameter(Mandatory=$true)][string]$AdapterSource,[Parameter(Mandatory=$true)][string]$InputPath)
# Fixed Windows boundary driver. Python owns all cases, assertions and test files.
# Descriptors contain inert data only; no script, command or provider dispatch.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
$loads=@(
 @{path=$BridgeSource;names=@('_Execution-Require','_Execution-Fields','_Execution-DecodeWire','_Execution-ValidateEffect')},
 @{path=$AdapterSource;names=@('_Diagnostic-Require','_Diagnostic-Fields','_Diagnostic-ArgvEquals','_Diagnostic-Value','_Diagnostic-IntOption','_Diagnostic-NewState','_Diagnostic-Limit','_Diagnostic-ValidateEffect','_Diagnostic-PreparePayload','_Diagnostic-ProcessMetrics','_Diagnostic-AssertOwnedRoot','_Diagnostic-PathEquals','_Diagnostic-AuditProbe','_Diagnostic-ClearAppshotCache')}
)
foreach($load in $loads){
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($load.path,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ('Qualification source did not parse: '+$load.path)}
 foreach($name in $load.names){
  $definitions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
  if($definitions.Count -ne 1){throw ('Expected one selected definition: '+$name)}
  . ([scriptblock]::Create($definitions[0].Extent.Text))
 }
}
function Fixture-State($Case){
 $state=_Diagnostic-NewState -Operation $Case.op -Rest $Case.rest -Context $Case.context
 if($Case.seed){foreach($property in $Case.seed.PSObject.Properties){
  switch -CaseSensitive ($property.Name){
   'rows' {foreach($rows in $property.Value){[void]$state.diagnostic_process_lists.Add([object[]]@($rows));[void]$state.diagnostic_process_rows.Add([object[]]@($rows))}}
   'order' {$state.diagnostic_metric_order=@($property.Value)}
   'cursor' {$state.diagnostic_metric_cursor=$property.Value}
   'counts' {foreach($p in $property.Value.PSObject.Properties){$state.diagnostic_counts[$p.Name]=$p.Value}}
   'audit_files' {foreach($path in $property.Value){$state.diagnostic_audit_files[$path]=$true}}
   'cache_path' {$state.diagnostic_cache_path=$property.Value}
   'changelog' {$state.diagnostic_changelog=$property.Value}
   'live' {$state.live=$property.Value}
   'sensitive' {$state.sensitive=$property.Value}
   default {throw 'Unknown inert state fixture field'}
  }
 }}
 return $state
}
function Fixture-Types($Value,[string]$Path,$Types){
 if($Value -is [hashtable]){$Types[$Path]='hashtable';foreach($key in $Value.Keys){Fixture-Types $Value[$key] ($Path+'.'+$key) $Types}}
 elseif($Value -is [array]){$Types[$Path]='array';for($i=0;$i -lt $Value.Count;$i++){Fixture-Types $Value[$i] ($Path+'['+$i+']') $Types}}
 elseif($null -ne $Value -and $Value -isnot [string] -and $Value -isnot [ValueType]){$Types[$Path]='object';foreach($p in $Value.PSObject.Properties){Fixture-Types $p.Value ($Path+'.'+$p.Name) $Types}}
}
function Fixture-Process($Spec,[string]$Label){
 if($null -eq $Spec){return $null}
 $start=if($Spec.start.kind -ceq 'offset'){[DateTimeOffset]::ParseExact($Spec.start.text,'o',[Globalization.CultureInfo]::InvariantCulture)}else{[datetime]::SpecifyKind([datetime]::ParseExact($Spec.start.text,'yyyy-MM-dd HH:mm:ss',[Globalization.CultureInfo]::InvariantCulture),[DateTimeKind]$Spec.start.kind)}
 $p=[pscustomobject]@{FixtureLabel=$Label;FixtureFailures=@($Spec.failures);FixtureNulls=@($Spec.nulls);FixtureStart=$start}
 $p|Add-Member ScriptProperty PrivateMemorySize64 {[void]$script:events.Add($this.FixtureLabel+'.memory');if($this.FixtureFailures -contains 'memory'){throw 'Synthetic memory getter inaccessible'};if($this.FixtureNulls -contains 'memory'){return $null};return [long]4096}
 $p|Add-Member ScriptProperty StartTime {[void]$script:events.Add($this.FixtureLabel+'.start');if($this.FixtureFailures -contains 'start'){throw 'Synthetic start getter inaccessible'};if($this.FixtureNulls -contains 'start'){return $null};return $this.FixtureStart}
 $p|Add-Member ScriptProperty TotalProcessorTime {[void]$script:events.Add($this.FixtureLabel+'.cpu');if($this.FixtureFailures -contains 'cpu'){throw 'Synthetic CPU getter inaccessible'};if($this.FixtureNulls -contains 'cpu'){return $null};if($this.FixtureLabel -ceq 'previous'){return [timespan]::FromMilliseconds(1200)};return [timespan]::FromMilliseconds(2300)}
 $p|Add-Member ScriptProperty PriorityClass {[void]$script:events.Add($this.FixtureLabel+'.priority');if($this.FixtureFailures -contains 'priority'){throw 'Synthetic priority getter inaccessible'};if($this.FixtureNulls -contains 'priority'){return $null};return 'Normal'}
 return $p
}
function Fixture-PathKey([string]$Path){$full=[IO.Path]::GetFullPath($Path);if($full.Length -gt 3){$full=$full.TrimEnd([char[]]@('\','/'))};return $full}
function Fixture-CapturedPath($Case){
 $script:pathEntries=@{};foreach($entry in $Case.entries){$script:pathEntries[$entry.FullName]=$entry};$script:pathCase=$Case
 switch -CaseSensitive ($Case.action){
  'root' {return _Diagnostic-AssertOwnedRoot $Case.path}
  'equal' {return @(_Diagnostic-PathEquals $Case.path $Case.other)}
  'probe' {_Diagnostic-AuditProbe $Case.path $Case.prefix;return}
  'clear' {_Diagnostic-ClearAppshotCache $Case.path;return}
  default {throw 'Unknown captured path fixture action'}
 }
}
function Fixture-Owned($Case){
 # Only the Python-created fixture root and fixed children acquire real I/O.
 $root=[IO.Path]::GetFullPath($Case.root)
 if([IO.Path]::GetFileName($root) -cnotmatch '^cucp-diagnostic-guards-[a-zA-Z0-9_-]+$'){throw 'Invalid disposable fixture root'}
 $null=_Diagnostic-AssertOwnedRoot $root
 if([IO.File]::ReadAllText((Join-Path $root '.fixture-owner')) -cne $Case.nonce){throw 'Disposable fixture ownership mismatch'}
 $audit=Join-Path $root 'audit';$cache=Join-Path $root 'cache';$target=Join-Path $root 'junction-target';$junction=Join-Path $cache 'appshot-junction.json'
 switch -CaseSensitive ($Case.action){
  'junction' {$null=New-Item -ItemType Junction -Path $junction -Target $target -ErrorAction Stop;return [int][IO.File]::GetAttributes($junction)}
  'probe' {_Diagnostic-AuditProbe $audit '.health-quick-probe-';return}
  'probe-upper' {_Diagnostic-AuditProbe $audit.ToUpperInvariant() '.health-quick-probe-';return}
  'probe-trailing' {_Diagnostic-AuditProbe ($audit+'\') '.health-quick-probe-';return}
  'probe-escape' {_Diagnostic-AuditProbe $audit '..\junction-target\escaped-probe-';return}
  'root-junction' {return _Diagnostic-AssertOwnedRoot $junction}
  'clear-upper' {_Diagnostic-ClearAppshotCache ($cache.ToUpperInvariant()+'\');return}
  default {throw 'Unknown owned fixture action'}
 }
}

function Fixture-ValidatePublicDelegate($Definition,[string]$Operation){
 if($Definition.IsFilter -or $Definition.IsWorkflow -or ($null -ne $Definition.Parameters -and $Definition.Parameters.Count -ne 0)){throw 'Unexpected public function form'}
 $body=$Definition.Body;$parameters=@($body.ParamBlock.Parameters)
 if($parameters.Count -ne 1 -or $parameters[0].Name.VariablePath.UserPath -cne 'Rest' -or $parameters[0].StaticType -ne [string[]] -or $parameters[0].DefaultValue -or $parameters[0].Attributes.Count -ne 1 -or $parameters[0].Attributes[0] -isnot [Management.Automation.Language.TypeConstraintAst] -or ($null -ne $body.ParamBlock.Attributes -and $body.ParamBlock.Attributes.Count -ne 0)){throw 'Unexpected public delegate parameters'}
 if($body.BeginBlock -or $body.ProcessBlock -or $body.DynamicParamBlock -or ($null -ne $body.EndBlock.Traps -and $body.EndBlock.Traps.Count -ne 0) -or $body.EndBlock.Statements.Count -ne 1){throw 'Unexpected public delegate statements'}
 $statement=$body.EndBlock.Statements[0]
 if($statement -is [Management.Automation.Language.ReturnStatementAst]){$statement=$statement.Pipeline}
 if($statement -isnot [Management.Automation.Language.PipelineAst] -or $statement.PipelineElements.Count -ne 1){throw 'Expected one fixed delegate pipeline'}
 $command=$statement.PipelineElements[0]
 if($command -isnot [Management.Automation.Language.CommandAst] -or $command.GetCommandName() -cne '_Invoke-LegacyDiagnosticFamily' -or $command.CommandElements.Count -ne 5 -or $command.InvocationOperator -ne [Management.Automation.Language.TokenKind]::Unknown -or ($null -ne $command.Redirections -and $command.Redirections.Count -ne 0)){throw 'Expected one direct family call'}
 $elements=$command.CommandElements
 if($elements[1] -isnot [Management.Automation.Language.CommandParameterAst] -or $elements[1].ParameterName -cne 'Operation' -or $elements[1].Argument -or $elements[2] -isnot [Management.Automation.Language.StringConstantExpressionAst] -or $elements[2].Value -cne $Operation -or $elements[3] -isnot [Management.Automation.Language.CommandParameterAst] -or $elements[3].ParameterName -cne 'Rest' -or $elements[3].Argument -or $elements[4] -isnot [Management.Automation.Language.VariableExpressionAst] -or $elements[4].VariablePath.UserPath -cne 'Rest' -or $elements[4].Splatted){throw 'Delegate changed its fixed operation or argv forwarding'}
}
function Fixture-PublicDelegate($Case){
 $names=@{'perf'='Invoke-MacroPerf';'diagnose-lag'='Invoke-MacroDiagnoseLag';'health-quick'='Invoke-MacroHealthQuick';'health-detail'='Invoke-MacroHealthDetail';'log-tail'='Invoke-MacroLogTail';'self-test'='Invoke-MacroSelfTest';'release-notes'='Invoke-MacroReleaseNotes';'audit-summary'='Invoke-MacroAuditSummary'}
 if($Case.operation -cnotin @($names.Keys)){throw 'Unknown production diagnostic delegate'}
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($BridgeSource,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Current main failed to parse'}
 $name=$names[$Case.operation]
 $found=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
 if($found.Count -ne 1){throw 'Expected exactly one current public delegate'}
 Fixture-ValidatePublicDelegate $found[0] $Case.operation
 # Only the AST-proven single call executes. No real family/session definition
 # is loaded in this driver; this same-scope stub is the sole call destination.
 $script:delegateCalls=New-Object Collections.ArrayList;$Brief=[bool]$Case.brief
 function _Invoke-LegacyDiagnosticFamily {param([string]$Operation,[string[]]$Rest) [void]$script:delegateCalls.Add(@{operation=$Operation;rest=@($Rest);brief=[bool]$Brief});return 31}
 . ([scriptblock]::Create($found[0].Extent.Text))
 $exit=& $name -Rest @($Case.rest)
 return @{exit=$exit;calls=@($script:delegateCalls)}
}

$cases=Microsoft.PowerShell.Utility\ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($InputPath,[Text.Encoding]::UTF8))
# Captured leaves live in this script's scope, the same scope as the selected
# source definitions. Never mix real owned I/O with these intercepted requests.
if(@($cases|Where-Object {$_.mode -ceq 'captured-path'}).Count){
 if(@($cases|Where-Object {$_.mode -ceq 'actual-owned'}).Count){throw 'Captured and actual owned fixture modes cannot be mixed'}
 function Test-Path {param([string]$LiteralPath) [void]$script:events.Add(@{command='Test-Path';path=$LiteralPath});return $script:pathEntries.ContainsKey((Fixture-PathKey $LiteralPath))}
 function Get-Item {param([string]$LiteralPath,[switch]$Force,[string]$ErrorAction) [void]$script:events.Add(@{command='Get-Item';path=$LiteralPath});$key=Fixture-PathKey $LiteralPath;if(-not $script:pathEntries.ContainsKey($key)){throw 'Unseeded synthetic path'};return $script:pathEntries[$key]}
 function Get-ChildItem {param([string]$LiteralPath,[string]$Filter,[string]$ErrorAction) [void]$script:events.Add(@{command='Get-ChildItem';path=$LiteralPath;filter=$Filter});foreach($item in $script:pathCase.cache_entries){$item}}
 function New-Item {param([string]$ItemType,[string]$Path,[switch]$Force) [void]$script:events.Add(@{command='New-Item';path=$Path;item_type=$ItemType});$script:pathEntries[$Path]=[pscustomobject]@{FullName=$Path;Attributes=16}}
 function Set-Content {param([string]$LiteralPath,$Value,[string]$Encoding) [void]$script:events.Add(@{command='Set-Content';path=$LiteralPath;value=$Value;encoding=$Encoding})}
 function Remove-Item {param([string]$LiteralPath,[switch]$Force,[string]$ErrorAction) [void]$script:events.Add(@{command='Remove-Item';path=$LiteralPath})}
 foreach($name in @('Test-Path','Get-Item','Get-ChildItem','New-Item','Set-Content','Remove-Item')){
  if((Get-Command $name).CommandType -ne 'Function'){throw 'Captured leaf binding was not installed'}
 }
 # Call an actual loaded source helper before any write-capable case. This
 # sentinel exists only in memory, so real cmdlet resolution cannot pass.
 $script:events=New-Object Collections.ArrayList
 $script:pathEntries=@{'C:\fixture-binding-probe'=[pscustomobject]@{FullName='C:\fixture-binding-probe';Attributes=16}}
 $null=_Diagnostic-AssertOwnedRoot 'C:\fixture-binding-probe'
 if(@($script:events|Where-Object {$_.command -ceq 'Get-Item' -and $_.path -ceq 'C:\fixture-binding-probe'}).Count -ne 2){throw 'Loaded helper did not resolve captured leaves'}
}
$results=New-Object Collections.ArrayList
foreach($case in $cases){
 $script:events=New-Object Collections.ArrayList;$r=[ordered]@{id=$case.id;state='ok';value=$null;error=$null;events=@()}
 try {
  switch -CaseSensitive ($case.mode){
   'validate' {
    $state=Fixture-State $case;$steps=New-Object Collections.ArrayList
    foreach($step in $case.steps){
     if($step.action -ceq 'snapshot'){[void]$state.diagnostic_process_lists.Add([object[]]@());continue}
     if($step.action -cne 'effect'){throw 'Unknown validator fixture step'}
     $v=[ordered]@{state='ok';error=$null;wire_kind=$step.effect.data.kind;decoded_fields=@();cursor=$state.diagnostic_metric_cursor}
     try {_Execution-ValidateEffect $step.effect $state;$v.decoded_fields=@($step.effect.data.PSObject.Properties.Name)}catch{$v.state='error';$v.error=$_.Exception.Message}
     $v.cursor=$state.diagnostic_metric_cursor;[void]$steps.Add($v)
    }
    $r.value=[ordered]@{steps=@($steps);counts=$state.diagnostic_counts;cursor=$state.diagnostic_metric_cursor}
   }
   'state-copy' {$context=$case.context;$rest=[string[]]@($case.rest);$state=_Diagnostic-NewState $case.op $rest $context;$context.cache_directory=$case.changed_cache;$rest[0]=$case.changed_arg;$r.value=@{context=$state.context;rest=@($state.rest)}}
   'payload' {$p=$case.payload;$prepared=_Diagnostic-PreparePayload $p (Fixture-State $case);$types=@{};Fixture-Types $prepared '$' $types;$r.value=@{payload=$prepared;types=$types;same_reference=[object]::ReferenceEquals($p,$prepared)}}
   'metrics' {$state=Fixture-State $case;$current=Fixture-Process $case.current 'current';$previous=Fixture-Process $case.previous 'previous';[void]$state.diagnostic_process_lists.Add([object[]]@($previous));[void]$state.diagnostic_process_lists.Add([object[]]@($current));$ordinal=if($null -eq $previous){$null}else{0};$r.value=@{metrics=(_Diagnostic-ProcessMetrics $state 0 $ordinal);source_start=$current.FixtureStart.ToString('o')}}
   'captured-path' {$r.value=Fixture-CapturedPath $case}
   'actual-owned' {$r.value=Fixture-Owned $case}
   'public-delegate' {$r.value=Fixture-PublicDelegate $case}
   default {throw 'Unknown diagnostic fixture mode'}
  }
 }catch{$r.state='error';$r.error=$_.Exception.Message}
 $r.events=@($script:events);[void]$results.Add($r)
}
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @($results) -Depth 100 -Compress))
