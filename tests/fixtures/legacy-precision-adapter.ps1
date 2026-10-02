# Integration draft. NativeHost legacy-precision-session is a read-only planner session.
# Fixed cache/history terminal writes use prevalidated bytes and a commit receipt.
function _Precision-EncodeWire($Value) {
  if($null -eq $Value){return @{kind='scalar';value=$null}}
  if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
  if($Value -is [System.Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(_Precision-EncodeWire $Value[$key])}})}}
  if($Value -is [System.Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){_Precision-EncodeWire $item})}}
  return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(_Precision-EncodeWire $p.Value)}})}
}
function _Precision-Require($Condition,[string]$Message) {
  if (-not $Condition) { $failure=New-Object InvalidOperationException -ArgumentList $Message;$failure.Data['precision_protocol']=$true;throw $failure }
}
function _Precision-Fields($Value,[string[]]$Names) {
  _Precision-Require ($null -ne $Value -and $Value -isnot [array] -and $Value -isnot [string] -and $Value -isnot [ValueType]) 'Expected an precision protocol object.'
  $properties=@($Value.PSObject.Properties)
  _Precision-Require ($properties.Count -eq $Names.Count -and @($properties | Where-Object {$_.Name -cnotin $Names}).Count -eq 0) 'Unexpected precision protocol fields.'
}
function _Precision-DecodeWire($Wire) {
  _Precision-Require ($null -ne $Wire -and $Wire.kind -is [string]) 'Missing precision wire tag.'
  switch -CaseSensitive ($Wire.kind) {
    'scalar' {
      _Precision-Fields $Wire @('kind','value')
      _Precision-Require ($null -eq $Wire.value -or $Wire.value -is [string] -or $Wire.value -is [ValueType]) 'Invalid scalar wire value.'
      Write-Output -NoEnumerate $Wire.value;return
    }
    'array' {
      _Precision-Fields $Wire @('kind','items');_Precision-Require ($Wire.items -is [array]) 'Wire array items must be an array.'
      $items=New-Object Collections.ArrayList
      foreach($item in $Wire.items){[void]$items.Add((_Precision-DecodeWire $item))}
      Write-Output -NoEnumerate ([object[]]$items.ToArray());return
    }
    'object' {
      _Precision-Fields $Wire @('kind','properties');_Precision-Require ($Wire.properties -is [array]) 'Wire object properties must be an array.'
      $object=[ordered]@{}
      foreach($property in $Wire.properties){
        _Precision-Fields $property @('name','value');_Precision-Require ($property.name -is [string] -and -not $object.Contains($property.name)) 'Invalid or duplicate wire property.'
        $object[$property.name]=_Precision-DecodeWire $property.value
      }
      Write-Output -NoEnumerate ([pscustomobject]$object);return
    }
    default {throw 'Unknown precision wire kind.'}
  }
}
function _Precision-WriteChunks($Writer,[long]$Id,[string]$Target,$Value) {
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $bytes=$utf8.GetBytes((ConvertTo-Json -InputObject $Value -Depth 100 -Compress))
  for($offset=0;$offset -lt $bytes.Length;$offset+=49152){
    $count=[Math]::Min(49152,$bytes.Length-$offset)
    $frame=[ordered]@{kind='part';id=$Id;data=[Convert]::ToBase64String($bytes,$offset,$count)}
    if($Target){$frame['target']=$Target}
    $Writer.WriteLine((ConvertTo-Json -InputObject $frame -Compress))
  }
  $end=[ordered]@{kind='end';id=$Id};if($Target){$end['target']=$Target}
  $Writer.WriteLine((ConvertTo-Json -InputObject $end -Compress));$Writer.Flush()
}
function _Precision-StartProcess {
  param([switch]$Storage)
  $command=if($Storage){"legacy-precision-storage"}else{"legacy-precision-session"}
  $native=$env:CUCP_NATIVE_HOST
  if(-not $native){$native=Join-Path $PSScriptRoot '..\pcucp-next\bin\native\PcuCp.NativeHost.exe'}
  $native=[IO.Path]::GetFullPath($native)
  if(-not (Test-Path -LiteralPath $native -PathType Leaf)){throw 'Matching native precision runtime missing.'}
  $psi=New-Object Diagnostics.ProcessStartInfo
  switch([IO.Path]::GetExtension($native).ToLowerInvariant()){
    '.dll' {if($native.Contains('"') -or $native.Contains("`r") -or $native.Contains("`n")){throw 'Invalid native DLL path.'};$psi.FileName=(Get-Command dotnet.exe -CommandType Application -ErrorAction Stop).Source;$psi.Arguments='"'+$native+'" '+$command}
    '.exe' {$psi.FileName=$native;$psi.Arguments=$command}
    default {throw 'Native precision runtime must be an executable or DLL.'}
  }
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$psi
  [void]$process.Start()
  return $process
}
function _Precision-ReadMessage($Reader,[long]$ExpectedId){
  $buffer=New-Object IO.MemoryStream;$target=$null
  try{
    while($true){
      $line=$Reader.ReadLine();if($null -eq $line){throw 'Precision session closed; terminal outcome may be uncertain. No write is retried.'}
      if($line.Length -gt 70000){throw 'Precision output frame exceeds its bound.'}
      $frame=$line|ConvertFrom-Json -ErrorAction Stop
      if($frame.kind -ceq 'part'){_Precision-Fields $frame @('kind','target','id','data')}elseif($frame.kind -ceq 'end'){_Precision-Fields $frame @('kind','target','id')}else{throw 'Invalid precision output frame.'}
      _Precision-Require ($frame.id -is [int] -or $frame.id -is [long]) 'Invalid precision frame id.'
      _Precision-Require ([long]$frame.id -eq $ExpectedId -and $frame.target -is [string]) 'Precision message does not match outstanding sequence.'
      if($null -eq $target){$target=$frame.target}else{_Precision-Require ($target -ceq $frame.target) 'Interleaved precision messages.'}
      if($frame.kind -ceq 'end'){break}
      _Precision-Require ($frame.data -is [string]) 'Invalid precision frame data.'
      $bytes=[Convert]::FromBase64String($frame.data);_Precision-Require ($bytes.Length -le 49152) 'Oversized precision data chunk.'
      $buffer.Write($bytes,0,$bytes.Length)
    }
    $wire=(New-Object Text.UTF8Encoding($false,$true)).GetString($buffer.ToArray())|ConvertFrom-Json -ErrorAction Stop
    return [pscustomobject]@{target=$target;id=$ExpectedId;value=(_Precision-DecodeWire $wire)}
  }finally{$buffer.Dispose()}
}
function _Precision-Reply($Writer,[long]$Id,$Value,$ErrorMessage){
  $reply=if($null -ne $ErrorMessage){@{state='error';message=$ErrorMessage}}else{@{state='ok';value=$Value}}
  _Precision-WriteChunks $Writer $Id '' (_Precision-EncodeWire $reply)
}
function _Precision-AssertArgv($Actual,[string[]]$Expected){
  _Precision-Require ($Actual -is [array] -and $Actual.Count -eq $Expected.Count) 'Invalid precision argv shape.'
  for($i=0;$i -lt $Expected.Count;$i++){_Precision-Require ($Actual[$i] -is [string] -and $Actual[$i] -ceq $Expected[$i]) 'Precision argv changed.'}
}
function _Precision-ReadEffect($Effect,$State){
  _Precision-Fields $Effect @('kind','args');_Precision-Require ($Effect.kind -is [string]) 'Invalid precision read kind.'
  $p=$Effect.args;$rest=$State.rest
  if($Effect.kind -ceq 'json-string'){
    _Precision-Fields $p @('value')
    return [Management.Automation.LanguagePrimitives]::ConvertTo($p.value,[string],[Globalization.CultureInfo]::InvariantCulture)
  }
  $x=[int](_Read-OptValue -Rest $rest -Name '--x');$y=[int](_Read-OptValue -Rest $rest -Name '--y')
  $tm=_Read-OptValue -Rest $rest -Name '--target-match';if(-not $tm){$tm=_Read-OptValue -Rest $rest -Name '--match'};if(-not $tm){$tm=_Read-OptValue -Rest $rest -Name '--window'}
  $th=[int64](_Read-OptValue -Rest $rest -Name '--target-hwnd')
  if($Effect.kind -cin @('coord-map','hit-test','coord-profile')){
    $fields=@('x','y','target_hwnd','target_match');if($Effect.kind -eq 'coord-map'){$fields+=@('from','norm_x','norm_y','has_norm')};if($Effect.kind -eq 'coord-profile'){$fields+='has_point'}
    _Precision-Fields $p $fields
    _Precision-Require (($p.x -is [int]) -and ($p.y -is [int]) -and ($p.target_hwnd -is [int] -or $p.target_hwnd -is [long]) -and $p.target_match -is [string]) 'Invalid precision target types.'
    _Precision-Require ($p.x -eq $x -and $p.y -eq $y -and [int64]$p.target_hwnd -eq $th -and $p.target_match -ceq [string]$tm) 'Precision target changed.'
  }
  switch -CaseSensitive ($Effect.kind){
    'coord-map' {
      _Precision-Require ($State.operation -eq 'coord-anchor' -and $State.reads -eq 0 -and $p.from -ceq 'screen' -and $p.has_norm -is [bool] -and -not $p.has_norm -and $p.norm_x -eq 0 -and $p.norm_y -eq 0) 'Invalid coordinate-map read.'
      return _Build-CoordMap -From 'screen' -X $x -Y $y -NormX 0 -NormY 0 -HasNorm $false -TargetHwnd $th -TargetMatch $tm
    }
    'hit-test' {
      _Precision-Require ($State.operation -eq 'point-plan' -and $State.reads -eq 0) 'Invalid hit-test order.'
      $reply=_Native-HitTestPoint -X $x -Y $y -TargetHwnd $th -TargetMatch $tm;$State.precheck=$reply;return $reply
    }
    'coord-profile' {
      _Precision-Require ($State.operation -eq 'point-plan' -and $State.reads -eq 1 -and $p.has_point -is [bool] -and $p.has_point) 'Invalid coordinate-profile order.'
      $reply=_Build-CoordProfile -HasPoint $true -X $x -Y $y -TargetHwnd $th -TargetMatch $tm;$State.profile=$reply;return $reply
    }
    'history-lines' {
      _Precision-Fields $p @('path');_Precision-Require ($p.path -is [string] -and $p.path -ceq $State.history_file -and $State.operation -eq 'coord-anchor' -and $State.reads -eq 1 -and $rest -notcontains '--no-history') 'Invalid history read.'
      Write-Output -NoEnumerate ([object[]]@(_Precision-HistoryLines -Path $State.history_file));return
    }
    {$_ -cin @('hit-scan','point-plan-child','cache-read')} {
      $radiusRaw=_Read-OptValue -Rest $rest -Name '--radius';$stepRaw=_Read-OptValue -Rest $rest -Name '--step';$ttlRaw=_Read-OptValue -Rest $rest -Name '--cache-ttl'
      $radius=if($null -ne $radiusRaw -and "$radiusRaw" -ne ''){[int]$radiusRaw}else{6};$radius=[Math]::Min(64,[Math]::Max(0,$radius))
      $step=if($null -ne $stepRaw -and "$stepRaw" -ne ''){[int]$stepRaw}else{2};if($step -le 0){$step=2};$step=[Math]::Min(16,$step)
      $inset=[int](_Read-OptValue -Rest $rest -Name '--click-inset');if($inset -le 0){$inset=2}
      $ttl=if($null -ne $ttlRaw -and "$ttlRaw" -ne ''){[int]$ttlRaw}else{$State.cache_seconds};$ttl=[Math]::Max(0,$ttl);if($rest -contains '--no-cache'){$ttl=0}
      if($Effect.kind -ceq 'point-plan-child'){
        _Precision-Require ($State.operation -eq 'target-validate' -and $State.reads -eq 0) 'Invalid child planner order.'
        $argv=@('--x',"$x",'--y',"$y",'--radius',"$radius",'--step',"$step",'--click-inset',"$inset",'--cache-ttl',"$ttl")
        if($tm){$argv+=@('--target-match',$tm)};if($th -gt 0){$argv+=@('--target-hwnd',"$th")};if($rest -contains '--no-cache'){$argv+='--no-cache'}
        _Precision-Fields $p @('argv');_Precision-AssertArgv $p.argv $argv
        return _TargetValidate-InvokePointPlanJson -PointPlanArgs $argv
      }
      _Precision-Require ($State.operation -eq 'point-plan' -and $State.reads -in @(2,3) -and ((-not $tm -and $th -le 0) -or [bool]$State.precheck.matched)) 'Target guard forbids this read.'
      if($Effect.kind -ceq 'cache-read'){
        _Precision-Fields $p @('directory','key','max_age_seconds')
        _Precision-Require ($State.reads -eq 2 -and $p.directory -is [string] -and $p.directory -ceq $State.cache_dir -and $p.key -is [string] -and $p.max_age_seconds -is [int] -and $p.max_age_seconds -eq $ttl) 'Invalid cache read.'
        $key=_PointPlan-CacheKey -X $x -Y $y -Radius $radius -Step $step -ClickInset $inset -TargetHwnd $th -TargetMatch $tm -Precheck $State.precheck -CoordSignature ([string]$State.profile.coord_signature)
        _Precision-Require ($p.key -ceq $key) 'Cache key changed.'
        return _PointPlan-ReadCache -Key $key -MaxAgeSeconds $ttl
      }
      $argv=@('-Action','hit-scan','-X',"$x",'-Y',"$y",'-ClickInset',"$inset",'-ScanRadius',"$radius",'-ScanStep',"$step")
      if($tm){$argv+=@('-TargetMatch',$tm)};if($th -gt 0){$argv+=@('-TargetHwnd',"$th")}
      _Precision-Fields $p @('argv');_Precision-AssertArgv $p.argv $argv
      return Invoke-NativeHelper -ArgList $argv
    }
    default {_Precision-Require $false 'Unsupported precision read effect.'}
  }
}
function _Invoke-LegacyPrecisionSession {
  param([string]$Operation,[hashtable]$Arguments,[switch]$Storage)
  $planner=$Operation -in @('coord-anchor','point-plan','target-validate') -and -not $Storage
  $state=@{operation=$Operation;rest=@($Arguments.rest);cache_seconds=[int]$Arguments.cache_seconds;history_file=[string]$Arguments.history_file;history_max=[int]$Arguments.history_max;cache_dir=[string]$Arguments.cache_dir;reads=0;precheck=$null;profile=$null;planner=$planner}
  $startupArgs=$Arguments
  $schema=if($Storage){'cucp.precision-storage/v1'}else{'cucp.precision-session/v1'}
  $startup=@{schema=$schema;operation=$Operation;args=(_Precision-EncodeWire $startupArgs);culture=[Globalization.CultureInfo]::CurrentCulture.Name}
  $startupJson=ConvertTo-Json -InputObject $startup -Depth 100 -Compress
  _Precision-Require ($startupJson.Length -le 4194304) 'Precision startup exceeds its bound.'
  $process=_Precision-StartProcess -Storage:$Storage;$writer=$null
  try{
    $stderr=$process.StandardError.ReadToEndAsync()
    $writer=New-Object IO.StreamWriter -ArgumentList @($process.StandardInput.BaseStream,(New-Object Text.UTF8Encoding($false,$true)));$writer.AutoFlush=$true
    $writer.WriteLine($startupJson);$id=1;$prepared=$null;$rendered=$null;$successJson=$null;$failureJson=$null;$serialized=$null
    while($true){
      $message=_Precision-ReadMessage $process.StandardOutput $id;$id++
      if($message.target -ceq 'error'){throw [string]$message.value.error}
      if($message.target -ceq 'read'){
        $reply=$null;$errorText=$null
        try{$reply=_Precision-ReadEffect $message.value $state}catch{if($_.Exception.Data.Contains("precision_protocol")){throw};$errorText=$_.Exception.Message}
        if($message.value.kind -cne 'json-string'){$state.reads++}
        _Precision-Reply $writer $message.id $reply $errorText;continue
      }
      if($message.target -cin @('complete','prepare')){
        $prepared=$message.value
        _Precision-Fields $prepared @('state','payload','exit','brief','json_depth','queries','effects')
        _Precision-Require ($prepared.state -ceq 'complete' -and (-not $planner -or $prepared.payload.schema -ceq "cucp.$Operation/v1") -and $prepared.exit -in @(0,1,2) -and $prepared.json_depth -in @(2,4,8,12,14,18,32,64,100) -and $prepared.effects -is [array] -and $prepared.effects.Count -le 1) 'Invalid precision completion.'
        $rendered=if(-not $planner){$null}elseif($null -ne $prepared.brief){[string]$prepared.brief}else{$prepared.payload|ConvertTo-Json -Depth ([int]$prepared.json_depth)}
        if($message.target -ceq 'complete'){_Precision-Require ($prepared.effects.Count -eq 0) 'Uncommitted precision effect.';break}
        _Precision-Require ($planner -and $prepared.effects.Count -eq 1) 'Missing precision terminal effect.'
        $Rest=$Arguments.rest
        $effect=$prepared.effects[0]
        if($effect.kind -ceq 'history-append'){
          _Precision-Require ($Operation -eq 'coord-anchor' -and ($Rest -contains '--record-history' -or $Rest -contains '--learn-history') -and $Rest -notcontains '--no-history' -and $effect.args.path -ceq $state.history_file -and $effect.args.max -eq $state.history_max -and $effect.bind -ceq 'reuse_history.recorded') 'Invalid terminal history effect.'
          $serialized=$effect.args.record|ConvertTo-Json -Compress -Depth 10
          $prepared.payload.reuse_history.recorded=$true;$successJson=$prepared.payload|ConvertTo-Json -Depth ([int]$prepared.json_depth)
          $prepared.payload.reuse_history.recorded=$false;$failureJson=$prepared.payload|ConvertTo-Json -Depth ([int]$prepared.json_depth)
        }elseif($effect.kind -ceq 'cache-write'){
          _Precision-Require ($Operation -eq 'point-plan' -and $effect.args.directory -ceq $state.cache_dir -and $effect.args.key -ceq $prepared.payload.cache_key -and $effect.bind -ceq 'payload' -and $prepared.payload.cache_ttl_seconds -gt 0) 'Invalid terminal cache effect.'
          $serialized=$prepared.payload|ConvertTo-Json -Depth 14
        }else{throw 'Unknown precision terminal effect.'}
        _Precision-Reply $writer $message.id @{serialized=$serialized} $null;continue
      }
      if($message.target -ceq 'commit-ready'){
        _Precision-Require ($null -ne $prepared -and $null -ne $serialized) 'Unexpected precision commit request.'
        _Precision-Fields $message.value @('receipt')
        $hash=[Security.Cryptography.SHA256]::Create();try{$expected=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($serialized)))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
        _Precision-Require ($message.value.receipt -is [string] -and $message.value.receipt -ceq $expected) 'Precision commit receipt differs from rendered bytes.'
        _Precision-Reply $writer $message.id @{receipt=$expected} $null;continue
      }
      if($message.target -ceq 'committed'){
        _Precision-Require ($null -ne $prepared) 'Unexpected precision commit outcome.';_Precision-Fields $message.value @('recorded')
        if($prepared.effects[0].kind -ceq 'history-append'){
          _Precision-Require ($message.value.recorded -is [bool]) 'Missing history append outcome.'
          $prepared.payload.reuse_history.recorded=$message.value.recorded
          if($null -eq $prepared.brief){$rendered=if($message.value.recorded){$successJson}else{$failureJson}}
        }else{_Precision-Require ($null -eq $message.value.recorded) 'Unexpected cache append outcome.'}
        break
      }
      throw 'Unknown precision session message.'
    }
    $writer.Close();$process.WaitForExit()
    _Precision-Require ($process.ExitCode -eq [int]$prepared.exit) 'Precision session failed; no terminal write is retried.'
    return [pscustomobject]@{state=$prepared;console=$rendered}
  }finally{if($writer){$writer.Dispose()};try{if(-not $process.HasExited){$process.Kill()}}catch{};$process.Dispose()}
}
function _Invoke-LegacyPrecision {
  param([ValidateSet('coord-anchor','point-plan','target-validate')][string]$Operation,[string[]]$Rest)
  $arguments=@{rest=@($Rest);cache_seconds=[int]$CacheSeconds;brief=[bool]$Brief;elapsed_ms=0;now=(Get-Date).ToString('o');history_file=[string]$Script:AnchorHistoryFile;history_max=[int]$Script:AnchorHistoryMax;cache_dir=[string]$Script:CacheDir}
  $completed=_Invoke-LegacyPrecisionSession -Operation $Operation -Arguments $arguments
  [Console]::Out.WriteLine($completed.console)
  return [int]$completed.state.exit
}
function _Invoke-LegacyPrecisionValue {
  param([string]$Operation,[hashtable]$Arguments,[switch]$Storage)
  $completed=_Invoke-LegacyPrecisionSession -Operation $Operation -Arguments $Arguments -Storage:$Storage
  Write-Output -NoEnumerate $completed.state.payload
}
function Invoke-MacroCoordAnchor {param([string[]]$Rest) _Invoke-LegacyPrecision -Operation 'coord-anchor' -Rest $Rest}
function Invoke-MacroPointPlan {param([string[]]$Rest) _Invoke-LegacyPrecision -Operation 'point-plan' -Rest $Rest}
function Invoke-MacroTargetValidate {param([string[]]$Rest) _Invoke-LegacyPrecision -Operation 'target-validate' -Rest $Rest}
function _Precision-HistoryLines {param([string]$Path) $result=_Invoke-LegacyPrecisionValue -Storage -Operation 'history-lines' -Arguments @{history_file=$Path};return @($result)}
function _AnchorHistory-Read {param([int]$Last=500) $result=_Invoke-LegacyPrecisionValue -Storage -Operation 'history-file-read' -Arguments @{history_file=[string]$Script:AnchorHistoryFile;last=$Last};return @($result)}
function _AnchorHistory-NormDistance {param($A,$B) _Invoke-LegacyPrecisionValue -Operation 'history-distance' -Arguments @{a=$A;b=$B}}
function _AnchorHistory-Append {
  param($Record)
  if(-not $Record){return $false}
  try{$line=$Record|ConvertTo-Json -Compress -Depth 10;return [bool](_Invoke-LegacyPrecisionValue -Storage -Operation 'history-append' -Arguments @{history_file=[string]$Script:AnchorHistoryFile;maximum=[int]$Script:AnchorHistoryMax;serialized=$line})}catch{return $false}
}
function _AnchorHistory-Score {param($Record,[double]$Tolerance=0.012) _Invoke-LegacyPrecisionValue -Storage -Operation 'history-file-score' -Arguments @{history_file=[string]$Script:AnchorHistoryFile;record=$Record;tolerance=$Tolerance}}
function _PointPlan-CacheKey {
  param([int]$X,[int]$Y,[int]$Radius,[int]$Step,[int]$ClickInset,[int]$TargetHwnd,[string]$TargetMatch,$Precheck,[string]$CoordSignature)
  _Invoke-LegacyPrecisionValue -Operation 'cache-key' -Arguments @{x=$X;y=$Y;radius=$Radius;step=$Step;click_inset=$ClickInset;target_hwnd=$TargetHwnd;target_match=$TargetMatch;precheck=$Precheck;coord_signature=$CoordSignature}
}
function _PointPlan-CachePath {param([string]$Key) _Invoke-LegacyPrecisionValue -Storage -Operation 'cache-path' -Arguments @{cache_dir=[string]$Script:CacheDir;key=$Key}}
function _PointPlan-ReadCache {param([string]$Key,[int]$MaxAgeSeconds) if(-not $Key -or $MaxAgeSeconds -le 0){return $null};_Invoke-LegacyPrecisionValue -Storage -Operation 'cache-read' -Arguments @{cache_dir=[string]$Script:CacheDir;key=$Key;max_age_seconds=$MaxAgeSeconds}}
function _PointPlan-WriteCache {param([string]$Key,$Payload) if(-not $Key -or -not $Payload){return};try{$text=$Payload|ConvertTo-Json -Depth 14;$null=_Invoke-LegacyPrecisionValue -Storage -Operation 'cache-write' -Arguments @{cache_dir=[string]$Script:CacheDir;key=$Key;serialized=$text}}catch{}}
function _TargetValidate-ConfidenceRank {param([string]$Confidence) _Invoke-LegacyPrecisionValue -Operation 'confidence-rank' -Arguments @{value=$Confidence}}
function _TargetValidate-SizeClass {param($Rect,[int]$Area) _Invoke-LegacyPrecisionValue -Operation 'size-class' -Arguments @{rect=$Rect;area=$Area}}
function _TargetValidate-PointEdgeDistance {param($Point,$Rect) _Invoke-LegacyPrecisionValue -Operation 'edge-distance' -Arguments @{point=$Point;rect=$Rect}}
function _TargetValidate-InvokePointPlanJson {
  param([string[]]$PointPlanArgs)
  $writer=New-Object IO.StringWriter;$previous=[Console]::Out;$exitCode=1
  try{
    [Console]::SetOut($writer)
    try{$exitCode=Invoke-MacroPointPlan -Rest (@($PointPlanArgs)+@('--json-only'))}
    catch{$exitCode=if($_.Exception.Message -match 'AllowLiveControl|Live (desktop )?control|Live click|requires -AllowLiveControl|Coordinate-based act|requires --after|Label not found|affordance_id not found'){3}else{1}}
  }finally{[Console]::SetOut($previous)}
  $raw=$writer.ToString().Replace("`r`n","`n");$writer.Dispose();if($raw.EndsWith("`n")){$raw=$raw.Substring(0,$raw.Length-1)}
  _Invoke-LegacyPrecisionValue -Operation 'child-plan-envelope' -Arguments @{raw_lines=@($raw -split "`n");exit_code=[int]$exitCode}
}
