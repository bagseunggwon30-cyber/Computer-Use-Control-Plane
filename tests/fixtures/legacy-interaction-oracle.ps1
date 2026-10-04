param([string]$Source,[string]$BaselineSource,[string]$InputPath,[switch]$AllowPortableHost)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if(-not $AllowPortableHost -and ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1)){throw 'Expected Windows PowerShell 5.1'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Accepted source did not parse'}
function Encode-Wire($Value) {
 if($null -eq $Value){return @{kind='scalar';value=$null}}
 if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
 # Detect empty pipeline output before passing it through a function argument,
 # which converts AutomationNull to ordinary null. PS5 serializes a retained
 # AutomationNull property as {}, while a real null remains null.
 if($Value -is [Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){
  $encoded=if($null -eq $Value[$key] -and @($Value[$key]).Count -eq 0){@{kind='object';properties=@()}}else{Encode-Wire $Value[$key]}
  @{name=[string]$key;value=$encoded}
 })}}
 if($Value -is [Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){
  if($null -eq $item -and @($item).Count -eq 0){@{kind='object';properties=@()}}else{Encode-Wire $item}
 })}}
 return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){
  $encoded=if($null -eq $p.Value -and @($p.Value).Count -eq 0){@{kind='object';properties=@()}}else{Encode-Wire $p.Value}
  @{name=$p.Name;value=$encoded}
 })}
}
function Capture-Effect {
 param([string]$Kind,[string]$Name='', [string[]]$Argv=@(),$Data=$null,[bool]$Live=$false)
 # Snapshot data now: original mutable records can receive extra properties later.
 $dataCopy=if($null -eq $Data){$null}else{Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $Data -Depth 80 -Compress | ConvertFrom-Json}
 [void]$script:trace.Add([ordered]@{kind=$Kind;name=$Name;argv=@($Argv);data=$dataCopy;live=$Live;quiet=$false;brief=$false;confirm_sensitive=$false})
 if($Kind -in @('Sleep','TrajectoryAppend','PointCacheWrite','Notice')){return}
 if($Kind -eq 'Console'){[Console]::Out.Write([string]$Data);return}
 if($Kind -eq 'PipelineOutput'){[void]$script:pipeline.Add([string]$Data);return}
 if($script:cursor -ge $script:fixture.replies.Count){throw "Fixture exhausted at ${Kind}:$Name"}
 $value=$script:fixture.replies[$script:cursor];$script:cursor++
 if($value -and $value.PSObject.Properties['throw']){throw $value.throw}
 Write-Output -NoEnumerate $value
}
function New-FakeStopwatch {
 $v=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalMilliseconds=37};ElapsedMilliseconds=37}
 $v|Add-Member ScriptMethod Stop {};return $v
}
function New-CapturedObservationId {return '0123456789ab'}
function Get-Date {return [DateTime]::Parse('2026-10-02T00:00:00.0000000Z').ToUniversalTime()}
function Start-Sleep {param([int]$Milliseconds) Capture-Effect 'Sleep' -Data $Milliseconds}
function Invoke-NativeHelper {
 param([string[]]$ArgList)
 Capture-Effect 'Native' -Argv $ArgList -Live ($ArgList[1] -in @('focus','click','type','shortcut'))
}
function Invoke-Cucp {param([string[]]$ArgList) Capture-Effect 'Cucp' -Argv $ArgList -Live $true}
function Invoke-Appshot {param([string]$Match,[switch]$Semantic,[switch]$NoCache) Capture-Effect 'Appshot' -Data ([ordered]@{match=$Match;semantic=[bool]$Semantic;no_cache=[bool]$NoCache})}
function _Enumerate-Win32Windows {param([string]$Match) Capture-Effect 'Win32Windows' -Data ([ordered]@{match=$Match})}
function _Get-UIAffordances {param([string]$FocusedWindow,[int]$MaxElements) Capture-Effect 'UIAffordances' -Data ([ordered]@{focused_window=$FocusedWindow;max_elements=$MaxElements})}
function _Invoke-CodexVision {param([string]$ScreenshotPath,[string]$Description) Capture-Effect 'Vision' -Data ([ordered]@{screenshot_path=$ScreenshotPath;description=$Description})}
function Write-Notice {param([string]$Level,[string]$Message) Capture-Effect 'Notice' -Name $Level -Data $Message}
function Write-CapturedPipeline {param([string]$Value) Capture-Effect 'PipelineOutput' -Data $Value}
function Write-CapturedRaw {param([string]$Value) Capture-Effect 'Console' -Name 'write' -Data $Value}
function _Trajectory-Append {param([string]$Kind,$Payload) Capture-Effect 'TrajectoryAppend' -Name $Kind -Data $Payload}
function _Native-HitTestPoint {param([int]$X,[int]$Y,[int]$TargetHwnd,[string]$TargetMatch) Capture-Effect 'HitTestPoint' -Data ([ordered]@{x=$X;y=$Y;target_hwnd=$TargetHwnd;target_match=$TargetMatch})}
function _PointPlan-ReadCache {param([string]$Key,[int]$MaxAgeSeconds) Capture-Effect 'PointCacheRead' -Data ([ordered]@{key=$Key;max_age_seconds=$MaxAgeSeconds})}
function _PointPlan-WriteCache {param([string]$Key,$Payload) Capture-Effect 'PointCacheWrite' -Data ([ordered]@{key=$Key;payload=$Payload})}
function _Build-CoordProfile {param([bool]$HasPoint,[int]$X,[int]$Y,[int64]$TargetHwnd,[string]$TargetMatch) Capture-Effect 'CoordProfile' -Data ([ordered]@{has_point=$HasPoint;x=$X;y=$Y;target_hwnd=$TargetHwnd;target_match=$TargetMatch})}
function _AnchorHistory-Score {param($Record) Capture-Effect 'AnchorScore' -Data ([ordered]@{record=$Record})}
function _AnchorHistory-Append {param($Record) Capture-Effect 'AnchorAppend' -Data ([ordered]@{record=$Record})}
function ConvertTo-Json {
 [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject,[int]$Depth=2,[switch]$Compress)
 begin{$values=New-Object Collections.ArrayList}
 process{[void]$values.Add($InputObject)}
 end{
  # Match the real cmdlet's pipeline aggregation: zero objects emit nothing,
  # one emits that object, multiple emit an array. Nested icon-find output is
  # captured by its own writer and must not replace the externally emitted data.
  if($values.Count -eq 0){return}
  $value=$null
  if($values.Count -eq 1){$value=$values[0]}else{$value=@($values)}
  if([object]::ReferenceEquals([Console]::Out,$script:topConsole)){$script:payload=Encode-Wire $value}
  Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $value -Depth $Depth -Compress:$Compress
 }
}
$names=@('_Read-OptValue','_Read-Switch','Get-CacheKey','Get-ElementCenter','Find-Element','_New-ObservationEnvelope',
 'Invoke-MacroFindLabel','Invoke-MacroClickPoint','Invoke-MacroClickLabel','Invoke-MacroSafeType',
 'Invoke-MacroIconFind','Invoke-MacroIconClick','Invoke-MacroOcrClick','Invoke-MacroPrecisionValidate')
foreach($name in $names){
 $found=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($found.Count -ne 1){throw "Expected one accepted function: $name"}
 $text=$found[0].Extent.Text
 $text=$text.Replace('[System.Diagnostics.Stopwatch]::StartNew()','(New-FakeStopwatch)')
 $text=$text.Replace('[guid]::NewGuid().ToString("N").Substring(0, 12)','(New-CapturedObservationId)')
 if($name -eq 'Invoke-MacroClickLabel'){$text=$text.Replace('Write-Output ','Write-CapturedPipeline ')}
 $text=$text.Replace('[Console]::Out.Write($r.Raw)','Write-CapturedRaw $r.Raw')
 $text=$text.Replace('[Console]::Out.Write($rClick.Raw)','Write-CapturedRaw $rClick.Raw')
 if($text.Contains('& powershell') -or $text.Contains('& $PSCommandPath') -or $text.Contains('SendKeys]::') -or $text.Contains('Start-Process')){throw "Unintercepted effect in $name"}
 . ([scriptblock]::Create($text))
}
# The accepted cache-key wrapper delegates to a migrated pure kernel. Load its
# already-qualified original body only; never load its storage/native neighbors.
$bt=$null;$be=$null;$ba=[Management.Automation.Language.Parser]::ParseFile($BaselineSource,[ref]$bt,[ref]$be)
if($be.Count){throw 'Baseline source did not parse'}
$cacheKey=@($ba.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_PointPlan-CacheKey'},$true))
if($cacheKey.Count -ne 1){throw 'Expected one original pure point cache-key function'}
. ([scriptblock]::Create($cacheKey[0].Extent.Text))
$Script:CucpV14Schema=@{PrecisionValidate='cucp.precision-validate/v1'}
$all=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$fixture;$script:trace=New-Object Collections.ArrayList;$script:pipeline=New-Object Collections.ArrayList;$script:cursor=0;$script:payload=$null
 $AllowLiveControl=[bool]$fixture.allow_live;$Brief=[bool]$fixture.brief;$CacheSeconds=if($null -ne $fixture.cache_seconds){[int]$fixture.cache_seconds}else{5}
 $writer=New-Object IO.StringWriter;$old=[Console]::Out;[Console]::SetOut($writer);$script:topConsole=[Console]::Out
 try {
  $function=switch($fixture.operation){
   'find-label'{'Invoke-MacroFindLabel'};'click-point'{'Invoke-MacroClickPoint'};'click-label'{'Invoke-MacroClickLabel'}
   'safe-type'{'Invoke-MacroSafeType'};'icon-find'{'Invoke-MacroIconFind'};'icon-click'{'Invoke-MacroIconClick'}
   'ocr-click'{'Invoke-MacroOcrClick'};'precision-validate'{'Invoke-MacroPrecisionValidate'}
  }
  $named=@{Rest=@($fixture.rest)}
  if($fixture.operation -eq 'click-label'){$named.Double=[bool]$fixture.double;$named.RightClick=[bool]$fixture.right_click}
  $exit=& $function @named
  $r=@{state='complete';payload=$script:payload;exit=[int]$exit;effects=(Encode-Wire @($script:trace));pipeline=@($script:pipeline);consumed=$script:cursor;console=$writer.ToString()}
 }catch{$r=@{state='error';error=$_.Exception.Message;effects=(Encode-Wire @($script:trace));pipeline=@($script:pipeline);consumed=$script:cursor;console=$writer.ToString()}}
 finally{[Console]::SetOut($old);$writer.Dispose()}
 [void]$all.Add($r)
}
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
