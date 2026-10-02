# Integration candidate. Requires the independently tested
# cucp.execution-sensitive-ceiling/v1 child entry contract before any child runs.
# This is a new effect adapter, never the read-only planning-query transport.
function _Invoke-LegacyExecutionChild {
  param([string]$ScriptPath, $Effect, [bool]$LiveCeiling, [bool]$SensitiveCeiling,
        [switch]$SensitiveCeilingContractVerified)
  if (-not $SensitiveCeilingContractVerified) { throw 'Execution child sensitive-ceiling contract has not been qualified.' }
  $childTokens=$null;$childErrors=$null
  $childAst=[Management.Automation.Language.Parser]::ParseFile($ScriptPath,[ref]$childTokens,[ref]$childErrors)
  $childReader=@($childAst.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Read-Switch'},$true))
  if ($childErrors.Count -gt 0 -or $childReader.Count -ne 1 -or -not $childReader[0].Extent.Text.Contains('cucp.execution-sensitive-ceiling/v1')) { throw 'Execution child does not support cucp.execution-sensitive-ceiling/v1.' }
  if ($Effect.kind -ne 'Child' -or $Effect.argv -isnot [array] -or
      @($Effect.argv | Where-Object { $_ -isnot [string] }).Count -gt 0 -or
      $Effect.live -isnot [bool] -or $Effect.quiet -isnot [bool] -or
      $Effect.brief -isnot [bool] -or $Effect.confirm_sensitive -isnot [bool]) { throw 'Invalid typed execution child descriptor.' }
  if ($Effect.live -and -not $LiveCeiling) { throw 'Execution descriptor exceeds live startup authority.' }
  if ($Effect.confirm_sensitive -and -not $SensitiveCeiling) { throw 'Execution descriptor exceeds sensitive startup authority.' }
  $bootstrap = @'
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$utf8=New-Object Text.UTF8Encoding($false,$true)
[Console]::OutputEncoding=$utf8
$reader=New-Object IO.StreamReader -ArgumentList @([Console]::OpenStandardInput(),$utf8,$true)
try {$text=$reader.ReadToEnd()} finally {$reader.Dispose()}
$r=$text | ConvertFrom-Json
$expected=@('schema','script_path','argv','live','quiet','brief','sensitive_ceiling')
if(@($r.PSObject.Properties).Count -ne $expected.Count -or @($r.PSObject.Properties | Where-Object {$_.Name -notin $expected}).Count -gt 0 -or
   $r.schema -ne 'cucp.execution-child/v1' -or $r.script_path -isnot [string] -or $r.argv -isnot [array] -or
   @($r.argv | Where-Object {$_ -isnot [string]}).Count -gt 0 -or $r.live -isnot [bool] -or
   $r.quiet -isnot [bool] -or $r.brief -isnot [bool] -or $r.sensitive_ceiling -isnot [bool]) {throw 'Invalid execution child request.'}
Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value ([bool]$r.sensitive_ceiling)
$global:LASTEXITCODE=0
& ([string]$r.script_path) -AllowLiveControl:([bool]$r.live) -Quiet:([bool]$r.quiet) -Brief:([bool]$r.brief) -CucpArgs ([string[]]$r.argv)
exit [int]$LASTEXITCODE
'@
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $request=[ordered]@{schema='cucp.execution-child/v1';script_path=$ScriptPath;argv=@($Effect.argv);
    live=[bool]$Effect.live;quiet=[bool]$Effect.quiet;brief=[bool]$Effect.brief;sensitive_ceiling=($SensitiveCeiling -and [bool]$Effect.confirm_sensitive)}
  $bytes=$utf8.GetBytes((ConvertTo-Json -InputObject $request -Depth 8 -Compress))
  $psi=New-Object Diagnostics.ProcessStartInfo
  $psi.FileName=(Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
  $psi.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -InputFormat Text -OutputFormat Text -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
  $psi.UseShellExecute=$false;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$psi;$started=$false
  try {
    $started=$process.Start();$stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
    $process.StandardInput.BaseStream.Write($bytes,0,$bytes.Length);$process.StandardInput.Close();$process.WaitForExit()
    $out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
    if($Effect.name -ceq 'direct'){[Console]::Out.Write($out);if($err){[Console]::Error.Write($err)}}
    $raw=(($out+$err) -replace "`r`n","`n") -replace "`n$",''
    $json=$null;try {$json=$raw|ConvertFrom-Json -ErrorAction Stop} catch {}
    return [pscustomobject]@{exit=[int]$process.ExitCode;raw=$raw;json=$json}
  } finally {if($started){try {if(-not $process.HasExited){$process.Kill()}} catch {}};$process.Dispose()}
}

function _Execution-EncodeWire($Value) {
  if($null -eq $Value){return @{kind='scalar';value=$null}}
  if($Value -is [string] -or $Value -is [ValueType]){return @{kind='scalar';value=$Value}}
  if($Value -is [System.Collections.IDictionary]){return @{kind='object';properties=@(foreach($key in $Value.Keys){@{name=[string]$key;value=(_Execution-EncodeWire $Value[$key])}})}}
  if($Value -is [System.Collections.IEnumerable]){return @{kind='array';items=@(foreach($item in $Value){_Execution-EncodeWire $item})}}
  return @{kind='object';properties=@(foreach($p in $Value.PSObject.Properties){@{name=$p.Name;value=(_Execution-EncodeWire $p.Value)}})}
}
function _Execution-Require($Condition,[string]$Message) {
  if (-not $Condition) { throw (New-Object InvalidOperationException -ArgumentList $Message) }
}
function _Execution-Fields($Value,[string[]]$Names) {
  _Execution-Require ($null -ne $Value -and $Value -isnot [array] -and $Value -isnot [string] -and $Value -isnot [ValueType]) 'Expected an execution protocol object.'
  $properties=@($Value.PSObject.Properties)
  _Execution-Require ($properties.Count -eq $Names.Count -and @($properties | Where-Object {$_.Name -cnotin $Names}).Count -eq 0) 'Unexpected execution protocol fields.'
}
function _Execution-DecodeWire($Wire) {
  _Execution-Require ($null -ne $Wire -and $Wire.kind -is [string]) 'Missing execution wire tag.'
  switch -CaseSensitive ($Wire.kind) {
    'scalar' {
      _Execution-Fields $Wire @('kind','value')
      _Execution-Require ($null -eq $Wire.value -or $Wire.value -is [string] -or $Wire.value -is [ValueType]) 'Invalid scalar wire value.'
      Write-Output -NoEnumerate $Wire.value;return
    }
    'array' {
      _Execution-Fields $Wire @('kind','items');_Execution-Require ($Wire.items -is [array]) 'Wire array items must be an array.'
      $items=New-Object Collections.ArrayList
      foreach($item in $Wire.items){[void]$items.Add((_Execution-DecodeWire $item))}
      Write-Output -NoEnumerate ([object[]]$items.ToArray());return
    }
    'object' {
      _Execution-Fields $Wire @('kind','properties');_Execution-Require ($Wire.properties -is [array]) 'Wire object properties must be an array.'
      $object=[ordered]@{}
      foreach($property in $Wire.properties){
        _Execution-Fields $property @('name','value');_Execution-Require ($property.name -is [string] -and -not $object.Contains($property.name)) 'Invalid or duplicate wire property.'
        $object[$property.name]=_Execution-DecodeWire $property.value
      }
      Write-Output -NoEnumerate ([pscustomobject]$object);return
    }
    default {throw 'Unknown execution wire kind.'}
  }
}
function _Execution-WriteChunks($Writer,[long]$Id,[string]$Target,$Value) {
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
function _Execution-WriteDiagnostic($State,$Process,$Stderr,[string]$ErrorText) {
  # Qualification-only opt-in. Never modify the protocol or replace its error.
  try {
    if($env:CUCP_EXECUTION_DIAGNOSTICS -cne '1' -or $State.diagnostic_phase -ceq 'host-error'){return}
    $counter=Get-Variable -Name ExecutionDiagnosticCount -Scope Script -ErrorAction SilentlyContinue
    $count=if($null -eq $counter){0}else{[int]$counter.Value}
    if($count -ge 4){return};$script:ExecutionDiagnosticCount=$count+1
    $line=[string]$State.diagnostic_frame;$prefix=$line.Substring(0,[Math]::Min(256,$line.Length))
    $points=@(foreach($character in $line.Substring(0,[Math]::Min(16,$line.Length)).ToCharArray()){'U+{0:X4}' -f [int]$character})
    $exited=$null;$code=$null;$err=''
    if($null -ne $Process){$exited=$Process.HasExited;if($exited){$code=$Process.ExitCode}}
    if($null -ne $Stderr -and $Stderr.IsCompleted){$err=[string]$Stderr.GetAwaiter().GetResult()}
    $record=[ordered]@{phase=[string]$State.diagnostic_phase;expected_id=$State.diagnostic_expected_id;
      frame_characters=$line.Length;prefix_codepoints=$points;frame_prefix=$prefix;
      host_exited=$exited;host_exit=$code;stderr_prefix=$err.Substring(0,[Math]::Min(1024,$err.Length));
      error=$ErrorText.Substring(0,[Math]::Min(512,$ErrorText.Length))}
    [Console]::Error.WriteLine('[execution-protocol] '+(ConvertTo-Json -InputObject $record -Depth 5 -Compress))
  } catch {} # Diagnostic collection cannot mask the original failure.
}
function _Execution-ValidateEffect($Effect,$State) {
  _Execution-Fields $Effect @('kind','name','argv','data','live','quiet','brief','confirm_sensitive')
  _Execution-Require ($Effect.kind -is [string] -and $Effect.name -is [string] -and $Effect.argv -is [array] -and
    @($Effect.argv | Where-Object {$_ -isnot [string]}).Count -eq 0 -and $Effect.live -is [bool] -and
    $Effect.quiet -is [bool] -and $Effect.brief -is [bool] -and $Effect.confirm_sensitive -is [bool]) 'Malformed execution effect descriptor.'
  _Execution-Require (-not $Effect.live -or $State.live) 'Effect exceeds immutable live startup authority.'
  _Execution-Require (-not $Effect.confirm_sensitive -or $State.sensitive) 'Effect exceeds immutable sensitive startup authority.'
  $Effect.data=_Execution-DecodeWire $Effect.data
  $a=@($Effect.argv);$d=$Effect.data;$n=$Effect.name;$kind=$Effect.kind
  _Execution-Require ($kind -cin @('WorkflowPlan','Child','Native','LocalMacro','CdpPort','HistoryRead','HistoryAppend','TrajectoryAppend','Sleep','Clock','Timestamp','CachePath','FileExists','RemoveFile','SendEscape','Console')) 'Unknown execution effect.'
  if($kind -ne 'Child'){_Execution-Require (-not $Effect.quiet -and -not $Effect.brief) 'Non-child effect changed child options.'}
  if($kind -notin @('Child','SendEscape')){_Execution-Require (-not $Effect.confirm_sensitive) 'Unexpected sensitive effect option.'}
  if($kind -notin @('Child','Native','LocalMacro','SendEscape')){_Execution-Require (-not $Effect.live) 'Unexpected live effect option.'}
  switch -CaseSensitive ($kind) {
    'WorkflowPlan' {_Execution-Require ($n -eq '' -and $null -eq $d) 'Invalid workflow acquisition descriptor.'}
    'Child' {_Execution-Require ($n -cin @('','direct') -and $null -eq $d) 'Invalid child execution descriptor.'}
    'Native' {
      _Execution-Require ($n -eq '' -and $null -eq $d -and $a.Count -ge 2 -and ($a.Count%2) -eq 0 -and $a[0] -ceq '-Action') 'Invalid native execution descriptor.'
      $action=$a[1];$live=$action -cin @('uia-invoke','uia-click','click','ocr-uia-invoke','cdp-smart-click')
      _Execution-Require ($Effect.live -eq $live) 'Native action/live classification mismatch.'
      $fields=switch -CaseSensitive ($action) {
        'focused' {@()};'modal-detect' {@('-Match')}
        'uia-find' {@('-Label','-Match','-Role')};'uia-invoke' {@('-Label','-Match','-Role')};'uia-click' {@('-Label','-Match','-Role')}
        'cdp-smart-click' {@('-CdpText','-CdpPort','-CdpPageMatch')}
        'ocr-uia-invoke' {@('-OcrText','-OcrMatch','-OcrMaxCandidates','-Match','-OcrLanguage')}
        'ocr-find-text' {@('-OcrText','-OcrMatch','-OcrMaxCandidates','-Match','-OcrLanguage')}
        'click' {@('-X','-Y','-Button','-ClickRefine','-TargetMatch')}
        'screenshot' {@('-OutPath','-ScreenshotX','-ScreenshotY','-ScreenshotW','-ScreenshotH')}
        'screenshot-diff' {@('-DiffBefore','-DiffAfter','-DiffThreshold')}
        default {throw 'Native action is outside execution coordination.'}
      }
      $seen=@{}
      for($i=2;$i -lt $a.Count;$i+=2){_Execution-Require ($a[$i] -cin $fields -and -not $seen.ContainsKey($a[$i])) 'Invalid or duplicate native effect argument.';$seen[$a[$i]]=$a[$i+1]}
      if($action -eq 'screenshot'){_Execution-Require ($State.paths.ContainsKey($seen['-OutPath'])) 'Screenshot destination is not owned by this execution.'}
      if($action -eq 'screenshot-diff'){_Execution-Require ($State.paths.ContainsKey($seen['-DiffBefore']) -and $State.paths.ContainsKey($seen['-DiffAfter'])) 'Screenshot diff paths are not owned by this execution.'}
    }
    'LocalMacro' {_Execution-Require ($n -cin @('click-point','icon-find') -and $null -eq $d -and $Effect.live -eq ($n -eq 'click-point')) 'Invalid local execution macro.'}
    'CdpPort' {_Execution-Require ($n -eq '' -and $null -eq $d -and $a.Count -eq 2 -and $a[1] -ceq '120' -and $a[0] -match '^\d+$') 'Invalid CDP port query.'}
    'HistoryRead' {_Execution-Require ($n -eq '' -and $null -eq $d -and $a.Count -eq 3 -and $a[2] -ceq '5') 'Invalid history query.'}
    'HistoryAppend' {
      _Execution-Require ($n -eq '' -and $a.Count -eq 3) 'Invalid history append descriptor.'
      _Execution-Fields $d @('success','elapsed_ms');_Execution-Require ($d.success -is [bool] -and $d.elapsed_ms -is [int]) 'Invalid history append payload.'
    }
    'TrajectoryAppend' {
      _Execution-Require ($n -cin @('workflow-run','task-run','form-run') -and $a.Count -eq 0) 'Invalid trajectory append kind.'
      if($n -eq 'task-run'){_Execution-Fields $d @('status','dry_run','workflow_exit','elapsed_ms')}
      else {_Execution-Fields $d @('status','executed_count','failed_count','total_steps','elapsed_ms')}
    }
    'Sleep' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [int] -and $d -ge 0) 'Invalid execution sleep.'}
    'Clock' {_Execution-Require ($n -cin @('start','stop','elapsed') -and $a.Count -eq 0 -and $d -is [string] -and $d -cin @('total','step','attempt','run')) 'Invalid execution clock.'}
    'Timestamp' {_Execution-Require ($n -cin @('o','HHmmss-fff') -and $a.Count -eq 0 -and $null -eq $d) 'Invalid execution timestamp.'}
    'CachePath' {_Execution-Require ($n -cin @('smartclick-before','smartclick-after','smartclick-retry-before','smartclick-retry-after') -and $a.Count -eq 0 -and $d -is [string] -and $d -match '^\d{6}-\d{3}$') 'Invalid execution capture path.'}
    'FileExists' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [string] -and $State.paths.ContainsKey($d)) 'Execution file probe is outside owned captures.'}
    'RemoveFile' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [string] -and $State.paths.ContainsKey($d)) 'Execution cleanup is outside owned captures.'}
    'SendEscape' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $null -eq $d -and $Effect.live -and $Effect.confirm_sensitive) 'Escape input requires both explicit startup gates.'}
    'Console' {_Execution-Require ($n -eq '' -and $a.Count -eq 0 -and $d -is [string]) 'Invalid execution console output.'}
  }
}
function _Execution-Dispatch($Effect,$State) {
  $a=[string[]]$Effect.argv;$d=$Effect.data;$n=$Effect.name
  switch -CaseSensitive ($Effect.kind) {
    'WorkflowPlan' {Write-Output -NoEnumerate (_Build-WorkflowPlan -Rest $a);return}
    'Child' {Write-Output -NoEnumerate (_Invoke-LegacyExecutionChild -ScriptPath $State.script_path -Effect $Effect -LiveCeiling $State.live -SensitiveCeiling $State.sensitive -SensitiveCeilingContractVerified);return}
    'Native' {Write-Output -NoEnumerate (Invoke-NativeHelper -ArgList $a);return}
    'LocalMacro' {
      $previous=[Console]::Out;$writer=New-Object IO.StringWriter
      try {
        [Console]::SetOut($writer)
        if($n -eq 'click-point'){$exit=Invoke-MacroClickPoint -Rest $a}else{Invoke-MacroIconFind -Rest $a | Out-Null;$exit=0}
      } finally {[Console]::SetOut($previous)}
      $raw=$writer.ToString();$writer.Dispose();$json=$null
      try {$json=$raw|ConvertFrom-Json -ErrorAction Stop} catch {}
      return [pscustomobject]@{exit=[int]$exit;raw=$raw;json=$json}
    }
    'CdpPort' {return Test-CdpPortQuick -Port ([int]$a[0]) -TimeoutMs ([int]$a[1])}
    'HistoryRead' {Write-Output -NoEnumerate (_History-PickBestStrategy -Label $a[0] -Match $a[1] -LookbackN ([int]$a[2]));return}
    'HistoryAppend' {_History-Append -Label $a[0] -Match $a[1] -Strategy $a[2] -Success ([bool]$d.success) -ElapsedMs ([int]$d.elapsed_ms);return}
    'TrajectoryAppend' {$payload=@{};foreach($p in $d.PSObject.Properties){$payload[$p.Name]=$p.Value};_Trajectory-Append -Kind $n -Payload $payload;return}
    'Sleep' {Start-Sleep -Milliseconds ([int]$d);return}
    'Clock' {
      if($n -eq 'start'){$State.clocks[$d]=[Diagnostics.Stopwatch]::StartNew();return 0}
      if(-not $State.clocks.ContainsKey($d)){throw 'Execution clock has not been started.'}
      if($n -eq 'stop'){$State.clocks[$d].Stop()}
      return [int]$State.clocks[$d].Elapsed.TotalMilliseconds
    }
    'Timestamp' {return (Get-Date).ToString($n)}
    'CachePath' {$path=Join-Path $State.cache_dir ($n+'-'+$d+'.png');$State.paths[$path]=$true;return $path}
    'FileExists' {return Test-Path -LiteralPath ([string]$d)}
    'RemoveFile' {Remove-Item -LiteralPath ([string]$d) -Force -ErrorAction SilentlyContinue;return}
    'SendEscape' {Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop;[System.Windows.Forms.SendKeys]::SendWait('{ESC}');return}
    'Console' {[Console]::Out.WriteLine([string]$d);return}
    default {throw 'Unknown execution effect.'}
  }
}
function _Invoke-LegacyExecutionEffectLoop {
  param([Diagnostics.Process]$HostProcess,[hashtable]$State)
  $utf8=New-Object Text.UTF8Encoding($false,$true);$sequence=0L
  while($true) {
    $buffer=New-Object IO.MemoryStream;$target=$null;$id=$null
    try {
      while($true) {
        $State.diagnostic_phase='read-frame';$State.diagnostic_expected_id=$sequence+1;$State.diagnostic_frame=$null
        $line=$HostProcess.StandardOutput.ReadLine();if($null -eq $line){if($State.live_effect_seen){throw 'mutation_may_have_occurred=true; automatic_retry=false; execution session disconnected.'};throw 'Execution session disconnected; automatic_retry=false.'}
        $State.diagnostic_frame=$line;$State.diagnostic_phase='parse-frame'
        $frame=$line|ConvertFrom-Json -ErrorAction Stop
        $State.diagnostic_phase='validate-frame'
        if($frame.kind -ceq 'part'){_Execution-Fields $frame @('kind','target','id','data')}
        elseif($frame.kind -ceq 'end'){_Execution-Fields $frame @('kind','target','id')}
        else {throw 'Unknown execution frame kind.'}
        _Execution-Require ($frame.target -cin @('effect','complete','error') -and ($frame.id -is [int] -or $frame.id -is [long]) -and $frame.id -eq ($sequence+1)) 'Invalid execution frame sequence.'
        if($null -eq $id){$id=[long]$frame.id;$target=[string]$frame.target}
        _Execution-Require ($frame.id -eq $id -and $frame.target -ceq $target) 'Execution frame target changed.'
        if($frame.kind -ceq 'end'){break}
        _Execution-Require ($frame.data -is [string]) 'Execution chunk data must be a base64 string.'
        $part=[Convert]::FromBase64String($frame.data);_Execution-Require ($part.Length -le 49152) 'Execution chunk exceeds 48 KiB.';$buffer.Write($part,0,$part.Length)
      }
      $State.diagnostic_phase='parse-message'
      $message=$utf8.GetString($buffer.ToArray())|ConvertFrom-Json -ErrorAction Stop
    } finally {$buffer.Dispose()}
    $sequence=$id
    if($target -ceq 'error'){
      $State.diagnostic_phase='host-error'
      _Execution-Fields $message @('message','mutation_may_have_occurred','automatic_retry')
      _Execution-Require ($message.message -is [string] -and $message.mutation_may_have_occurred -is [bool] -and $message.automatic_retry -is [bool] -and -not $message.automatic_retry) 'Invalid execution error envelope.'
      if($message.mutation_may_have_occurred){throw ('mutation_may_have_occurred=true; automatic_retry=false; '+$message.message)}
      throw $message.message
    }
    if($target -ceq 'complete') {
      $State.diagnostic_phase='validate-completion'
      _Execution-Fields $message @('payload','exit','json_depth','brief','emit_json')
      _Execution-Require ($message.exit -is [int] -and $message.exit -ge 0 -and $message.exit -le 3 -and $message.json_depth -is [int] -and
        $message.json_depth -ge 0 -and $message.json_depth -le 100 -and $message.emit_json -is [bool] -and ($null -eq $message.brief -or $message.brief -is [string])) 'Invalid execution completion envelope.'
      $payload=_Execution-DecodeWire $message.payload
      if($message.emit_json){[Console]::Out.WriteLine((ConvertTo-Json -InputObject $payload -Depth ([int]$message.json_depth)))}
      elseif($null -ne $message.brief){[Console]::Out.WriteLine([string]$message.brief)}
      return [int]$message.exit
    }
    # Protocol/authority failures must terminate, never become fallback replies.
    $State.diagnostic_phase='validate-effect'
    _Execution-ValidateEffect $message $State
    $State.diagnostic_phase='dispatch-effect'
    if($message.live){$State.live_effect_seen=$true}
    try {$value=_Execution-Dispatch $message $State;$reply=@{state='ok';value=(_Execution-EncodeWire $value)}}
    catch {$reply=@{state='error';message=$_.Exception.Message;mutation_may_have_occurred=[bool]$message.live}}
    _Execution-WriteChunks -Writer $State.writer -Id $id -Target '' -Value $reply
  }
}

function _Invoke-LegacyExecutionFamily {
  param([ValidateSet('workflow-run','task-run','form-run','smart-click','watch','recovery-plan','recovery-run')][string]$Operation,[string[]]$Rest,[string]$ScriptPath)
  # Capture immutable invocation context before any plan/acquisition effect.
  $liveCeiling=[bool]$AllowLiveControl
  $sensitiveCeiling=[bool](_Read-StandaloneConfirmation -Rest $Rest)
  $inherited=Get-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -ErrorAction SilentlyContinue
  if($null -ne $inherited -and ($inherited.Value -isnot [bool] -or -not $inherited.Value -or
      -not ($inherited.Options -band [Management.Automation.ScopedItemOptions]::Constant))){$sensitiveCeiling=$false}
  $native=$env:CUCP_NATIVE_HOST
  if(-not $native){$native=Join-Path $PSScriptRoot '..\pcucp-next\bin\native\PcuCp.NativeHost.exe'}
  $native=[IO.Path]::GetFullPath($native)
  if(-not (Test-Path -LiteralPath $native -PathType Leaf)){throw 'Matching execution runtime missing. Publish the native runtime or set CUCP_NATIVE_HOST to its executable/DLL.'}
  $psi=New-Object Diagnostics.ProcessStartInfo
  switch ([IO.Path]::GetExtension($native).ToLowerInvariant()) {
    '.dll' {
      if($native.Contains('"') -or $native.Contains("`r") -or $native.Contains("`n")){throw 'Invalid execution runtime DLL path.'}
      $psi.FileName=(Get-Command dotnet.exe -CommandType Application -ErrorAction Stop).Source
      $psi.Arguments='"'+$native+'" legacy-execution-session'
    }
    '.exe' {$psi.FileName=$native;$psi.Arguments='legacy-execution-session'}
    default {throw 'Execution runtime must be an executable or DLL, never a shell script.'}
  }
  if($liveCeiling){$psi.Arguments+=' --allow-live-control'}
  if($sensitiveCeiling){$psi.Arguments+=' --confirm-sensitive'}
  $utf8=New-Object Text.UTF8Encoding($false,$true)
  $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
  $psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
  $startup=[ordered]@{schema='cucp.execution-start/v1';operation=$Operation;rest=@($Rest);brief=[bool]$Brief;
    cache_seconds=[int]$CacheSeconds;vision_available=[bool]$Script:CliPath;culture=[Globalization.CultureInfo]::CurrentCulture.Name}
  $state=@{live=$liveCeiling;sensitive=$sensitiveCeiling;script_path=$ScriptPath;cache_dir=$Script:CacheDir;paths=@{};clocks=@{};writer=$null;live_effect_seen=$false}
  $process=New-Object Diagnostics.Process;$process.StartInfo=$psi;$started=$false;$writer=$null;$stderr=$null
  try {
    $started=$process.Start();if(-not $started){throw 'Execution runtime did not start.'}
    $stderr=$process.StandardError.ReadToEndAsync()
    # Own no-BOM writer; .NET Framework's default redirected writer is not used.
    $writer=New-Object IO.StreamWriter -ArgumentList @($process.StandardInput.BaseStream,$utf8,4096,$true)
    $state.writer=$writer
    _Execution-WriteChunks -Writer $writer -Id 0 -Target '' -Value $startup
    $exit=_Invoke-LegacyExecutionEffectLoop -HostProcess $process -State $state
    $writer.Flush();$writer.Dispose();$writer=$null;$process.StandardInput.Close()
    if(-not $process.WaitForExit(10000)){throw 'Execution runtime did not exit after its final report; no action was retried.'}
    $err=$stderr.GetAwaiter().GetResult()
    if($process.ExitCode -ne $exit){throw ('Execution runtime exit did not match its final report. '+$err)}
    return [int]$exit
  } catch {
    _Execution-WriteDiagnostic -State $state -Process $process -Stderr $stderr -ErrorText $_.Exception.Message
    if($state.live_effect_seen -and $_.Exception.Message -notlike 'mutation_may_have_occurred=true;*'){
      throw ('mutation_may_have_occurred=true; automatic_retry=false; '+$_.Exception.Message)
    }
    throw
  } finally {
    if($null -ne $writer){try {$writer.Dispose()}catch {}}
    if($started){try {if(-not $process.HasExited){$process.Kill();[void]$process.WaitForExit(5000)}}catch {}}
    $process.Dispose()
  }
}
function Invoke-MacroWorkflowRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'workflow-run' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroTaskRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'task-run' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroFormRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'form-run' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroSmartClick {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'smart-click' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroWatch {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'watch' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroRecoveryPlan {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'recovery-plan' -Rest $Rest -ScriptPath $PSCommandPath}
function Invoke-MacroRecoveryRun {param([string[]]$Rest) return _Invoke-LegacyExecutionFamily -Operation 'recovery-run' -Rest $Rest -ScriptPath $PSCommandPath}
