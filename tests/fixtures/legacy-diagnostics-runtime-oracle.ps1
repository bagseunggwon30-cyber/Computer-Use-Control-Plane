param([string]$Source,[string]$InputPath,[string]$AdapterSource,[string]$BridgeSource,[switch]$ProductionEntry)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
# Only source and fixture reads are real. Every effect seam below is installed
# before the selected original function definitions can execute.
$sourceText=[IO.File]::ReadAllText($Source)
$fixtures=ConvertFrom-Json ([IO.File]::ReadAllText($InputPath))
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Selected source parse failed'}
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

function Encode-Wire($Value){
 if($null -eq $Value){return @{kind='scalar';value=$null}}
 if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
 if($Value -is [Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(Encode-Wire $Value[$key])}})}}
 if($Value -is [Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){Encode-Wire $item})}}
 return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(Encode-Wire $p.Value)}})}
}
function Capture-Effect {
 param([string]$Kind,[string]$Name='', [string[]]$Argv=@(),$Data=$null)
 [void]$script:trace.Add([ordered]@{kind=$Kind;name=$Name;argv=@($Argv);data=$Data})
 if($Kind -eq 'Timestamp'){return '2026-10-02T00:00:00.0000000Z'}
 if($Kind -eq 'Clock'){
  if($Name -eq 'start'){return 0}
  $value=37
  if($script:fixture.clocks -and $script:clockCursor -lt $script:fixture.clocks.Count){$value=[int]$script:fixture.clocks[$script:clockCursor]}
  if($Name -eq 'stop'){$script:clockCursor++}
  return $value
 }
 if($Kind -in @('Sleep','Notice')){return}
 if($script:cursor -ge $script:fixture.replies.Count){throw "Fixture exhausted at ${Kind}:$Name"}
 $value=$script:fixture.replies[$script:cursor];$script:cursor++
 if($null -ne $value -and $value.PSObject.Properties['throw']){throw $value.throw}
 Write-Output -NoEnumerate $value
}
function Start-CapturedClock([string]$Scope){
 Capture-Effect Clock start -Data $Scope | Out-Null
 $clock=[pscustomobject]@{Scope=$Scope;Elapsed=[pscustomobject]@{TotalMilliseconds=37};ElapsedMilliseconds=37}
 $clock|Add-Member ScriptMethod Stop { $ms=Capture-Effect Clock stop -Data $this.Scope; $this.Elapsed.TotalMilliseconds=$ms; $this.ElapsedMilliseconds=$ms }
 return $clock
}
function Get-Date { [datetime]::Parse((Capture-Effect Timestamp o),[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind) }
function Invoke-CapturedNodeVersion { $r=Capture-Effect NodeVersion; $script:LASTEXITCODE=$r.exit; return $r.output }
function Test-Path { param([string]$LiteralPath,[string]$Path,[string]$PathType);if($PathType -eq 'Leaf'){return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath -PathType Leaf};if(-not $LiteralPath){$LiteralPath=$Path};Capture-Effect FileExists -Data $LiteralPath }
function Get-ChildItem {
 param([string]$LiteralPath,[string]$Filter,[switch]$Recurse,[switch]$File,[string]$ErrorAction)
 $filterValue=$null;if($Filter){$filterValue=$Filter}
 $r=Capture-Effect ListFiles -Data ([ordered]@{path=$LiteralPath;recurse=[bool]$Recurse;filter=$filterValue;file=[bool]$File})
 foreach($item in @($r)) {if($null -ne $item){$date=[datetime]::MinValue;if($item.last_write_time){$date=[datetime]$item.last_write_time};[pscustomobject]@{FullName=[string]$item.full_name;Length=$item.length;LastWriteTime=$date}}}
}
function Get-Item {param([string]$LiteralPath);Capture-Effect FileStat -Data $LiteralPath}
function Get-Content {param([string]$LiteralPath,[switch]$Raw);Capture-Effect ReadText -Data $LiteralPath}
function Invoke-Cucp {param([string[]]$ArgList,[switch]$CaptureJson);$r=Capture-Effect Cli -Argv $ArgList;[pscustomobject]@{ExitCode=$r.exit;Json=$r.json}}
function Invoke-NativeHelper {param([string[]]$ArgList);$r=Capture-Effect Native -Argv $ArgList;[pscustomobject]@{ExitCode=$r.exit;Json=$r.json}}
function _Helper-IsUp {Capture-Effect HelperUp}
function _Ensure-Win32Loaded {Capture-Effect EnsureWin32}
function _Ensure-UIALoaded {Capture-Effect EnsureUia}
function _Find-CodexCli {Capture-Effect FindCodex}
function Assert-Authorized {param([string[]]$ArgList);$blocked=Capture-Effect AssertAuthorized -Argv $ArgList;if($blocked -is [bool] -and $blocked){throw 'captured authorization gate blocked'}}
function Write-Notice {param([string]$Level,[string]$Message);Capture-Effect Notice -Name $Level -Data $Message | Out-Null}
function Invoke-Appshot {
 param([string]$Match,[switch]$Semantic,[switch]$NoCache,[int]$CacheMaxSeconds)
 $max=$null;if($PSBoundParameters.ContainsKey('CacheMaxSeconds')){$max=$CacheMaxSeconds}
 Capture-Effect Appshot -Data ([ordered]@{match=$Match;semantic=[bool]$Semantic;no_cache=[bool]$NoCache;cache_max_seconds=$max})
}
function Get-CacheKey {param([string]$Match);Capture-Effect CacheKey -Data $Match}
function _Get-UIAffordances {param([string]$FocusedWindow,[int]$MaxElements);$v=Capture-Effect Uia -Data ([ordered]@{focused_window=$FocusedWindow;max_elements=$MaxElements});foreach($item in @($v)){if($null -ne $item){$item}}}
function Invoke-MacroMetrics {param([string[]]$Rest);Capture-Effect Macro metrics -Argv $Rest}
function Invoke-MacroWindows {param([string[]]$Rest);Capture-Effect Macro windows -Argv $Rest}
function Invoke-MacroFindLabel {param([string[]]$Rest);Capture-Effect Macro find-label -Argv $Rest}
function Capture-HealthQuick {Capture-Effect Macro health-quick}
function Start-Sleep {param([int]$Milliseconds);Capture-Effect Sleep -Data $Milliseconds | Out-Null}
function _Enumerate-Win32Windows {param($Match);$v=Capture-Effect Windows;foreach($item in @($v)){if($null -ne $item){$item}}}
function Get-Process {
 param([string]$ErrorAction)
 $v=Capture-Effect Processes;$ordinal=0
 foreach($item in @($v)){
  if($null -eq $item){continue}
  $proc=[pscustomobject]@{Id=$item.id;ProcessName=$item.name;diagnostic_ordinal=$ordinal};$ordinal++
  $mapping=@{PrivateMemorySize64='private_bytes';StartTime='started_at';TotalProcessorTime='cpu_ms';PriorityClass='priority'}
  foreach($key in $mapping.Keys){
   $field=$mapping[$key]
   if($item.PSObject.Properties[$field]){
    $value=$item.$field
    if($key -eq 'StartTime'){$value=[datetime]$value}
    if($key -eq 'TotalProcessorTime'){$value=[pscustomobject]@{TotalMilliseconds=$value}}
    $proc|Add-Member NoteProperty $key $value
   } else { $proc|Add-Member ScriptProperty $key {throw 'captured inaccessible process property'} }
  }
  $proc
 }
}
function Get-CapturedMetric($Metrics,[string]$Name,[switch]$Date) {
 if(-not $Metrics.PSObject.Properties[$Name]){throw 'captured inaccessible process property'}
 if($Date){return [datetimeoffset]::Parse([string]$Metrics.$Name,[Globalization.CultureInfo]::InvariantCulture).DateTime}
 return $Metrics.$Name
}
# Capture full unformatted reports separately from exact public Console text.
function ConvertTo-Json {
 [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject,[int]$Depth=2,[switch]$Compress)
 process { if($InputObject.schema -in @('cucp.macro.perf/v2','cucp.benchmark/v1','cucp.diagnose-lag/v1') -or $null -ne $InputObject.components -or $null -ne $InputObject.PSObject.Properties['helper_running']){$script:payload=Encode-Wire $InputObject}; Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $InputObject -Depth $Depth -Compress:$Compress }
}
function Replace-Once([string]$Text,[string]$Old,[string]$New){
 $n=([regex]::Matches($Text,[regex]::Escape($Old))).Count
 if($n -ne 1){throw "Expected one exact acquisition seam; found $n"}
 return $Text.Replace($Old,$New)
}
function Replace-Pattern([string]$Text,[string]$Pattern,[string]$New){
 $regex=[regex]::new($Pattern)
 if($regex.Matches($Text).Count -ne 1){throw "Expected one bounded acquisition region: $Pattern"}
 return $regex.Replace($Text,[Text.RegularExpressions.MatchEvaluator]{param($m) $New})
}
$names=@('_Read-OptValue','_Read-Switch','_Iif','Invoke-MacroPerf','Invoke-MacroDiagnoseLag','Invoke-MacroHealthQuick','Invoke-MacroHealthDetail','Invoke-MacroSelfTest','Invoke-MacroBenchmark')
if($ProductionEntry){$names=@($names|Where-Object {$_ -ne '_Iif'})}
$definitions=@{}
foreach($name in $names){
 $nodes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($nodes.Count -ne 1){throw "Expected unique original definition $name"}
 $body=$nodes[0].Extent.Text
 # Production loads current public delegates byte-for-byte. Benchmark remains
 # the current original body and still receives the exact acquisition seams.
 if($ProductionEntry -and $name -cin @('Invoke-MacroPerf','Invoke-MacroDiagnoseLag','Invoke-MacroHealthQuick','Invoke-MacroHealthDetail','Invoke-MacroSelfTest')){
  $operation=switch($name){'Invoke-MacroPerf'{'perf'};'Invoke-MacroDiagnoseLag'{'diagnose-lag'};'Invoke-MacroHealthQuick'{'health-quick'};'Invoke-MacroHealthDetail'{'health-detail'};'Invoke-MacroSelfTest'{'self-test'}}
  Fixture-ValidatePublicDelegate $nodes[0] $operation
  $definitions[$name]=$body;continue
 }
 $scope=switch($name){'Invoke-MacroPerf'{'perf-sample'};'Invoke-MacroBenchmark'{'benchmark-sample'};'Invoke-MacroHealthQuick'{'health-quick'};'Invoke-MacroDiagnoseLag'{'diagnose-lag'};default{$null}}
 if($scope){$body=Replace-Once $body '[System.Diagnostics.Stopwatch]::StartNew()' "(Start-CapturedClock '$scope')"}
 if($name -in @('Invoke-MacroHealthQuick','Invoke-MacroHealthDetail')){
  $body=Replace-Once $body '& node --version 2>&1' 'Invoke-CapturedNodeVersion'
  $prefix=if($name -eq 'Invoke-MacroHealthQuick'){'.health-quick-probe-'}else{'.health-probe-'}
  $probe='(?s)    if \(-not \(Test-Path \$Script:AuditDir\)\).*?    \$auditOk = \$true'
  $new="    Capture-Effect AuditProbe -Name '$prefix' -Data `$Script:AuditDir | Out-Null`n    `$auditOk = `$true"
  $body=Replace-Pattern $body $probe $new
 }
 if($name -in @('Invoke-MacroHealthQuick','Invoke-MacroDiagnoseLag')){
  $tail='(?s)      \$fs = \[System.IO.File\]::Open\(\$Script:WrapperLog.*?      \} finally \{ \$fs.Dispose\(\) \}'
  $new=@'
      $capturedTail=Capture-Effect TailBytes -Data ([ordered]@{path=$Script:WrapperLog;max_bytes=65536})
      $tailStr=[string]$capturedTail.text
      $matches=[regex]::Matches($tailStr,'TIMEOUT')
      $recentTimeoutCount=$matches.Count
'@
  $body=Replace-Pattern $body $tail $new
 }
 if($name -eq 'Invoke-MacroPerf'){
  $body=Replace-Once $body 'Invoke-MacroHealthQuick -Rest @()' 'Capture-HealthQuick'
  $body=Replace-Once $body 'Get-ChildItem -LiteralPath $Script:CacheDir -Filter "appshot-*.json" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue' "Capture-Effect ClearAppshotCache -Name 'appshot-*.json' -Data `$Script:CacheDir | Out-Null"
 }
 if($name -eq 'Invoke-MacroDiagnoseLag'){
  $body=Replace-Once $body '[Environment]::ProcessorCount' '(Capture-Effect ProcessorCount)'
  $body=Replace-Once $body 'Join-Path $env:TEMP "computer-use-control-plane"' '$script:fixtureTempRoot'
  $insert=@'
    foreach ($p in $matching) {
      $previousOrdinal=$null;$previousProcess=$byPidT0[$p.Id]
      if($previousProcess){$previousOrdinal=[int]$previousProcess.diagnostic_ordinal}
      $capturedMetrics=Capture-Effect ProcessMetrics -Data ([ordered]@{current_ordinal=[int]$p.diagnostic_ordinal;previous_ordinal=$previousOrdinal})
'@
  $body=Replace-Once $body '    foreach ($p in $matching) {' $insert
  $body=Replace-Once $body '$p.PrivateMemorySize64' '(Get-CapturedMetric $capturedMetrics private_bytes)'
  $body=Replace-Once $body '$p.StartTime' '(Get-CapturedMetric $capturedMetrics started_at -Date)'
  $body=Replace-Once $body '$p.TotalProcessorTime.TotalMilliseconds' '(Get-CapturedMetric $capturedMetrics current_cpu_ms)'
  $body=Replace-Once $body '$prev.TotalProcessorTime.TotalMilliseconds' '(Get-CapturedMetric $capturedMetrics previous_cpu_ms)'
  $body=Replace-Once $body '$p.PriorityClass' '(Get-CapturedMetric $capturedMetrics priority)'

 }
 $definitions[$name]=$body
}
foreach($name in $names){. ([scriptblock]::Create($definitions[$name]))}

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

$output=New-Object Collections.ArrayList
foreach($f in $fixtures){
 $script:fixture=$f;$script:cursor=0;$script:clockCursor=0;$script:trace=New-Object Collections.ArrayList;$script:payload=$null
 $Brief=[bool]$f.brief
 $Script:AuditDir='C:\fixture\audit';$Script:CacheDir='C:\fixture\cache';$Script:WrapperLog='C:\fixture\wrapper.log';$Script:CliPath='C:\fixture\cli.mjs';$script:fixtureTempRoot='C:\fixture\computer-use-control-plane'
 if($f.context){
  foreach($mapping in @(@('audit_dir','AuditDir'),@('cache_dir','CacheDir'),@('wrapper_log','WrapperLog'),@('cli_path','CliPath'),@('temp_root','fixtureTempRoot'))){
   if($f.context.PSObject.Properties[$mapping[0]]){Set-Variable -Scope Script -Name $mapping[1] -Value $f.context.($mapping[0])}
  }
 }
 $Script:CucpV14Schema=@{Benchmark='cucp.benchmark/v1'}
 $fixtureCulture='en-US';if($null -ne $f.PSObject.Properties['culture'] -and $f.culture -is [string]){$fixtureCulture=$f.culture}
 [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($fixtureCulture)
 $old=[Console]::Out;$writer=New-Object IO.StringWriter;[Console]::SetOut($writer)
 try {
  $fn=switch($f.operation){'perf'{'Invoke-MacroPerf'};'benchmark'{'Invoke-MacroBenchmark'};'health-quick'{'Invoke-MacroHealthQuick'};'health-detail'{'Invoke-MacroHealthDetail'};'self-test'{'Invoke-MacroSelfTest'};'diagnose-lag'{'Invoke-MacroDiagnoseLag'};default{throw 'Unknown runtime diagnostic fixture'}}
  $rc=if($ProductionEntry){& $fn -Rest @($f.rest)}elseif($AdapterSource){_Invoke-LegacyDiagnosticFamily -Operation ([string]$f.operation) -Rest @($f.rest)}else{& $fn -Rest @($f.rest)}
  $record=[ordered]@{state='complete';payload=$script:payload;exit=[int]$rc;console=$writer.ToString();effects=(Encode-Wire @($script:trace));consumed=$script:cursor}
 }catch{$record=[ordered]@{state='error';error=$_.Exception.Message;console=$writer.ToString();effects=(Encode-Wire @($script:trace));consumed=$script:cursor}}
 finally{[Console]::SetOut($old);$writer.Dispose()}
 [void]$output.Add($record)
}
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @($output) -Depth 100 -Compress))
