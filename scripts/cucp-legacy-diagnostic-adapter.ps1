# Diagnostic acquisition adapter. Shared _Execution-* functions own
# framing, process lifetime, immutable authority and mutation uncertainty.
# Main routes eight public delegates here; benchmark retains its original body.
function _Diagnostic-Require($Condition,[string]$Message) { _Execution-Require $Condition $Message }
function _Diagnostic-Fields($Value,[string[]]$Names) { _Execution-Fields $Value $Names }
function _Diagnostic-ArgvEquals($Actual,[string[]]$Expected) {
  if($Actual.Count -ne $Expected.Count){return $false}
  for($i=0;$i -lt $Expected.Count;$i++){if($Actual[$i] -isnot [string] -or $Actual[$i] -cne $Expected[$i]){return $false}}
  return $true
}
function _Diagnostic-Value([string[]]$Rest,[string]$Name) {
  for($i=0;$i+1 -lt $Rest.Count;$i++){if($Rest[$i] -eq $Name){return $Rest[$i+1]}}
  return $null
}
function _Diagnostic-IntOption($State,[string]$Name,[int]$Default) {
  $value=[int](_Diagnostic-Value $State.rest $Name)
  if($value -le 0){$value=$Default};return $value
}
function _Diagnostic-NewState {
  param([string]$Operation,[string[]]$Rest,$Context)
  _Diagnostic-Require ($Operation -cin @('perf','diagnose-lag','health-quick','health-detail','log-tail','benchmark','self-test','audit-summary','release-notes')) 'Unknown diagnostic operation.'
  _Diagnostic-Fields $Context @('audit_directory','cache_directory','wrapper_log','cli_path','changelog_path','temp_root','benchmark_schema','release_schema')
  foreach($key in @('audit_directory','cache_directory','wrapper_log','changelog_path','temp_root','benchmark_schema','release_schema')) {
    _Diagnostic-Require ($Context.$key -is [string]) 'Invalid diagnostic context field.'
  }
  _Diagnostic-Require ($null -eq $Context.cli_path -or $Context.cli_path -is [string]) 'Invalid diagnostic CLI context.'
  # Fresh scalar copies separate original invocation data from mutable replies.
  $owned=[pscustomobject][ordered]@{}
  foreach($key in @('audit_directory','cache_directory','wrapper_log','cli_path','changelog_path','temp_root','benchmark_schema','release_schema')) {
    $owned|Add-Member NoteProperty $key $Context.$key
  }
  $restCopy=@($Rest);if($null -ne $restCopy){$restCopy=$restCopy.Clone()}
  return @{family='diagnostics';operation=$Operation;rest=$restCopy;context=$owned;
    live=$false;sensitive=$false;paths=@{};clocks=@{};writer=$null;live_effect_seen=$false;
    diagnostic_counts=@{};diagnostic_audit_files=@{};diagnostic_cache_path=$null;diagnostic_changelog=$null;
    diagnostic_process_lists=(New-Object Collections.ArrayList);diagnostic_process_rows=(New-Object Collections.ArrayList);diagnostic_metric_order=@();diagnostic_metric_cursor=0}
}
function _Diagnostic-Limit($State,[string]$Key,[int]$Limit) {
  $count=0;if($State.diagnostic_counts.ContainsKey($Key)){$count=[int]$State.diagnostic_counts[$Key]}
  _Diagnostic-Require ($count -lt $Limit) ('Diagnostic effect exceeded invocation count: '+$Key)
  $State.diagnostic_counts[$Key]=$count+1
}
function _Diagnostic-ValidateEffect($Effect,$State) {
  # Common validator has already checked the outer fields, Boolean ceilings and
  # inert string argv, and decoded the tagged value exactly once.
  _Diagnostic-Require ($State.family -ceq 'diagnostics' -and $Effect.kind -ceq 'Diagnostic' -and
    -not $Effect.live -and -not $Effect.quiet -and -not $Effect.brief -and -not $Effect.confirm_sensitive) 'Invalid diagnostic effect authority.'
  _Diagnostic-Fields $Effect.data @('name','value')
  _Diagnostic-Require ($Effect.data.name -is [string]) 'Invalid diagnostic suboperation.'
  $kind=$Effect.name;$name=$Effect.data.name;$value=$Effect.data.value;$a=@($Effect.argv)
  $c=$State.context;$op=$State.operation;$rest=$State.rest
  $kinds=@('Clock','Timestamp','FileExists','ListFiles','FileStat','ReadLines','ReadText','TailBytes','ResolvePath','NodeVersion','Cli','Native','Macro','AuditProbe','EnsureWin32','EnsureUia','HelperUp','FindCodex','Processes','ProcessMetrics','ProcessorCount','Windows','Sleep','ClearAppshotCache','AssertAuthorized','Appshot','CacheKey','Uia','Notice')
  _Diagnostic-Require ($kind -cin $kinds) 'Unknown diagnostic effect kind.'
  if($kind -cnotin @('Clock','Timestamp','Macro','AuditProbe','ClearAppshotCache','Notice')){_Diagnostic-Require ($name -ceq '') 'Unexpected diagnostic suboperation.'}
  if($kind -cnotin @('Cli','Native','Macro','AssertAuthorized')){_Diagnostic-Require ($a.Count -eq 0) 'Unexpected diagnostic argv.'}
  switch -CaseSensitive ($kind) {
    'Clock' {
      $scope=switch($op){'perf'{'perf-sample'};'benchmark'{'benchmark-sample'};'health-quick'{'health-quick'};'diagnose-lag'{'diagnose-lag'};'log-tail'{'log-tail'};default{''}}
      _Diagnostic-Require ($name -cin @('start','stop','elapsed') -and $scope -ne '' -and $value -is [string] -and $value -ceq $scope -and ($name -cne 'elapsed' -or $op -ceq 'log-tail')) 'Invalid diagnostic clock.'
    }
    'Timestamp' {_Diagnostic-Require ($name -ceq 'o' -and $null -eq $value -and $op -cin @('perf','health-quick','health-detail','diagnose-lag','log-tail','audit-summary')) 'Invalid diagnostic timestamp.'}
    'NodeVersion' {_Diagnostic-Require ($op -cin @('health-quick','health-detail') -and $null -eq $value) 'Invalid node probe.';_Diagnostic-Limit $State 'node' 1}
    'Cli' {
      _Diagnostic-Require ($null -eq $value) 'Invalid CLI payload.';$allowed=$false;$limit=1
      if($op -ceq 'self-test'){$allowed=(_Diagnostic-ArgvEquals $a @('version')) -or (_Diagnostic-ArgvEquals $a @('tools')) -or (_Diagnostic-ArgvEquals $a @('observe','windows'))}
      elseif($op -ceq 'health-detail'){$allowed=_Diagnostic-ArgvEquals $a @('version')}
      elseif($op -ceq 'perf'){
        $limit=_Diagnostic-IntOption $State '--iters' 3
        $allowed=(_Diagnostic-ArgvEquals $a @('version')) -or (_Diagnostic-ArgvEquals $a @('release'))
        if($rest -notcontains '--quick'){
          $allowed=$allowed -or (_Diagnostic-ArgvEquals $a @('health')) -or (_Diagnostic-ArgvEquals $a @('observe','context')) -or (_Diagnostic-ArgvEquals $a @('observe','screenshot')) -or (_Diagnostic-ArgvEquals $a @('observe','appshot','--match','unlikely-perf-target-window'))
        }
        if($rest -contains '--include-live-ish' -and (_Diagnostic-ArgvEquals $a @('observe','appshot'))){$allowed=$true;$limit=[Math]::Min([int]::MaxValue,[long]$limit*2)}
      }
      _Diagnostic-Require $allowed 'CLI argv is outside diagnostic invocation.'
      _Diagnostic-Limit $State ('cli:'+($a -join '|')) $limit
    }
    'Native' {
      _Diagnostic-Require ($op -ceq 'benchmark' -and $null -eq $value -and $a.Count -eq 2 -and $a[0] -ceq '-Action' -and $a[1] -cin @('windows','health','focused','modal-detect')) 'Native action is outside benchmark.'
      $iters=3;$raw=_Diagnostic-Value $rest '--iters';if($raw){try{$iters=[int]$raw}catch{$iters=3}};$iters=[Math]::Min(10,[Math]::Max(1,$iters))
      _Diagnostic-Limit $State ('native:'+ $a[1]) $iters
    }
    'Macro' {
      _Diagnostic-Require ($op -ceq 'perf' -and $null -eq $value) 'Invalid diagnostic macro operation.'
      $allowed=$false
      if($name -cin @('metrics','health-quick')){$allowed=$a.Count -eq 0}
      elseif($name -ceq 'windows'){$allowed=$a.Count -eq 0 -or (_Diagnostic-ArgvEquals $a @('--match','unlikely-perf-target-window')) -or ($rest -notcontains '--quick' -and (_Diagnostic-ArgvEquals $a @('--rich')))}
      elseif($name -ceq 'find-label'){
        $base=@('--label','__cucp_unlikely_label__','--match','unlikely-perf-target-window')
        $allowed=(_Diagnostic-ArgvEquals $a ($base+@('--fast'))) -or ($rest -notcontains '--quick' -and (_Diagnostic-ArgvEquals $a $base))
      }
      _Diagnostic-Require $allowed 'Macro argv is outside diagnostic invocation.'
      _Diagnostic-Limit $State ('macro:'+$name+':'+($a -join '|')) (_Diagnostic-IntOption $State '--iters' 3)
    }
    'FileExists' {
      _Diagnostic-Require ($value -is [string]) 'Invalid diagnostic file path.';$allowed=@()
      switch($op){
        'health-quick'{$allowed=@($c.cli_path,$c.cache_directory,$c.audit_directory,$c.wrapper_log)}
        'health-detail'{$allowed=@($c.cli_path)}
        'diagnose-lag'{$allowed=@($c.temp_root,$c.cache_directory,$c.wrapper_log)}
        'audit-summary'{$allowed=@($c.audit_directory)}
        'log-tail'{$path=_Diagnostic-Value $rest '--path';if(-not $path){$path=$c.wrapper_log};$allowed=@($path)}
        'benchmark'{$path=_Diagnostic-Value $rest '--baseline';if($path){$allowed=@($path)}}
        'self-test'{if($State.diagnostic_cache_path){$allowed=@($State.diagnostic_cache_path)}}
      }
      _Diagnostic-Require ($value -cin $allowed) 'Diagnostic file probe changed its requested path.'
    }
    'FileStat' {_Diagnostic-Require ($op -cin @('health-quick','diagnose-lag') -and $value -is [string] -and $value -ceq $c.wrapper_log) 'Invalid diagnostic stat.'}
    'ListFiles' {
      _Diagnostic-Fields $value @('path','recurse','filter','file')
      _Diagnostic-Require ($value.path -is [string] -and $value.recurse -is [bool] -and $value.file -is [bool] -and ($null -eq $value.filter -or $value.filter -is [string])) 'Invalid diagnostic listing types.'
      $allowed=$false
      if($op -ceq 'audit-summary'){$allowed=$value.path -ceq $c.audit_directory -and $value.recurse -and -not $value.file -and $value.filter -ceq 'trajectory*.ndjson'}
      elseif($op -ceq 'health-quick'){$allowed=$null -eq $value.filter -and $value.file -and (($value.path -ceq $c.cache_directory -and -not $value.recurse) -or ($value.path -ceq $c.audit_directory -and $value.recurse))}
      elseif($op -ceq 'diagnose-lag'){$allowed=$null -eq $value.filter -and $value.file -and (($value.path -ceq $c.cache_directory -and -not $value.recurse) -or ($value.path -ceq $c.temp_root -and $value.recurse))}
      _Diagnostic-Require $allowed 'Listing is outside diagnostic invocation.'
      _Diagnostic-Limit $State ('list:'+$value.path) 1
    }
    'ReadLines' {
      _Diagnostic-Require ($value -is [string] -and (($op -ceq 'audit-summary' -and $State.diagnostic_audit_files.ContainsKey($value)) -or ($op -ceq 'release-notes' -and $null -ne $State.diagnostic_changelog -and $value -ceq $State.diagnostic_changelog))) 'Diagnostic line read lacks matching acquisition.'
    }
    'ReadText' {_Diagnostic-Require ($op -ceq 'benchmark' -and $value -is [string] -and $value -ceq (_Diagnostic-Value $rest '--baseline')) 'Baseline read changed its requested path.'}
    'ResolvePath' {_Diagnostic-Require ($op -ceq 'release-notes' -and $value -is [string] -and $value -ceq $c.changelog_path) 'Changelog resolution changed its configured path.';_Diagnostic-Limit $State 'resolve' 1}
    'TailBytes' {
      _Diagnostic-Fields $value @('path','max_bytes');_Diagnostic-Require ($value.path -is [string] -and ($value.max_bytes -is [int] -or $value.max_bytes -is [long]) -and $value.max_bytes -gt 0 -and $value.max_bytes -le [int]::MaxValue) 'Invalid diagnostic tail types.'
      $path=$c.wrapper_log;$maximum=65536
      if($op -ceq 'log-tail'){$path=_Diagnostic-Value $rest '--path';if(-not $path){$path=$c.wrapper_log};$maximum=_Diagnostic-IntOption $State '--max-bytes' 262144}
      _Diagnostic-Require ($op -cin @('log-tail','health-quick','diagnose-lag') -and $value.path -ceq $path -and $value.max_bytes -eq $maximum) 'Tail window differs from requested diagnostic.'
      _Diagnostic-Limit $State 'tail' 1
    }
    'AuditProbe' {
      $prefix=if($op -ceq 'health-quick'){'.health-quick-probe-'}else{'.health-probe-'}
      _Diagnostic-Require ($op -cin @('health-quick','health-detail') -and $name -ceq $prefix -and $value -is [string] -and $value -ceq $c.audit_directory) 'Audit probe is outside immutable owned directory.'
      _Diagnostic-Limit $State 'audit-probe' 1
    }
    'ClearAppshotCache' {
      _Diagnostic-Require ($op -ceq 'perf' -and $rest -contains '--include-live-ish' -and $name -ceq 'appshot-*.json' -and $value -is [string] -and $value -ceq $c.cache_directory) 'Cache clear exceeds immutable invocation scope.'
      _Diagnostic-Limit $State 'cache-clear' 1
    }
    {$_ -cin @('EnsureWin32','EnsureUia','HelperUp','FindCodex')} {
      $expected=if($kind -ceq 'EnsureWin32'){'health-quick'}else{'health-detail'}
      _Diagnostic-Require ($op -ceq $expected -and $null -eq $value) 'Provider check is outside diagnostic operation.'
      _Diagnostic-Limit $State $kind 1
    }
    'Processes' {
      _Diagnostic-Require ($op -ceq 'diagnose-lag' -and $null -eq $value -and ($State.diagnostic_process_lists.Count -eq 0 -or $State.diagnostic_counts['sleep'] -eq 1)) 'Invalid process snapshot.'
      _Diagnostic-Limit $State 'processes' 2
    }
    'ProcessMetrics' {
      _Diagnostic-Fields $value @('current_ordinal','previous_ordinal')
      _Diagnostic-Require ($op -ceq 'diagnose-lag' -and $State.diagnostic_process_lists.Count -eq 2 -and $State.diagnostic_counts['processor-count'] -eq 1 -and ($value.current_ordinal -is [int] -or $value.current_ordinal -is [long]) -and $value.current_ordinal -ge [int]::MinValue -and $value.current_ordinal -le [int]::MaxValue -and ($null -eq $value.previous_ordinal -or (($value.previous_ordinal -is [int] -or $value.previous_ordinal -is [long]) -and $value.previous_ordinal -ge [int]::MinValue -and $value.previous_ordinal -le [int]::MaxValue))) 'Invalid retained process ordinal types.'
      $cursor=[int]$State.diagnostic_metric_cursor
      _Diagnostic-Require ($cursor -lt $State.diagnostic_metric_order.Count -and $value.current_ordinal -eq $State.diagnostic_metric_order[$cursor]) 'Process metrics changed original grouped order.'
      $current=$State.diagnostic_process_rows[1][$value.current_ordinal];$expected=$null
      for($i=0;$i -lt $State.diagnostic_process_rows[0].Count;$i++){if($State.diagnostic_process_rows[0][$i].id -eq $current.id){$expected=$i}}
      _Diagnostic-Require (($null -eq $expected -and $null -eq $value.previous_ordinal) -or ($null -ne $expected -and $null -ne $value.previous_ordinal -and $value.previous_ordinal -eq $expected)) 'Process metrics changed previous retained object.'
      $State.diagnostic_metric_cursor=$cursor+1
    }
    'ProcessorCount' {_Diagnostic-Require ($op -ceq 'diagnose-lag' -and $null -eq $value -and $State.diagnostic_process_lists.Count -eq 2) 'Invalid processor-count query.';_Diagnostic-Limit $State 'processor-count' 1}
    'Windows' {_Diagnostic-Require ($op -ceq 'diagnose-lag' -and $null -eq $value) 'Invalid foreground query.';_Diagnostic-Limit $State 'windows' 1}
    'Sleep' {
      $sample=[Math]::Min(8000,(_Diagnostic-IntOption $State '--sample-ms' 3000))
      _Diagnostic-Require ($op -ceq 'diagnose-lag' -and ($value -is [int] -or $value -is [long]) -and $value -ge [int]::MinValue -and $value -le [int]::MaxValue -and $value -eq $sample -and $State.diagnostic_process_lists.Count -eq 1) 'Diagnostic sampling delay changed.';_Diagnostic-Limit $State 'sleep' 1
    }
    'AssertAuthorized' {
      $allowed=(_Diagnostic-ArgvEquals $a @('act','click','--x','0','--y','0','--after','fake')) -or (_Diagnostic-ArgvEquals $a @('act','click','--x','100','--y','100'))
      _Diagnostic-Require ($op -ceq 'self-test' -and $null -eq $value -and $allowed) 'Self-test authorization check changed.'
      _Diagnostic-Limit $State ('gate:'+($a -join '|')) 1
    }
    'Appshot' {
      _Diagnostic-Fields $value @('match','semantic','no_cache','cache_max_seconds')
      _Diagnostic-Require ($op -ceq 'self-test' -and $value.match -is [string] -and $value.semantic -is [bool] -and $value.no_cache -is [bool]) 'Invalid self-test appshot types.'
      $cold=$value.match -ceq 'selftest-cache' -and -not $value.semantic -and $value.no_cache -and $null -eq $value.cache_max_seconds
      $warm=$value.match -ceq 'selftest-cache' -and -not $value.semantic -and -not $value.no_cache -and ($value.cache_max_seconds -is [int] -or $value.cache_max_seconds -is [long]) -and $value.cache_max_seconds -eq 600
      $full=$rest -contains '--deep' -and $value.match -ceq '' -and $value.semantic -and $value.no_cache -and $null -eq $value.cache_max_seconds
      _Diagnostic-Require ($cold -or $warm -or $full) 'Appshot exceeds fixed self-test scope.'
      _Diagnostic-Limit $State ('appshot:'+$cold+':'+$warm+':'+$full) 1
    }
    'CacheKey' {_Diagnostic-Require ($op -ceq 'self-test' -and $value -is [string] -and $value -ceq 'selftest-cache') 'Invalid self-test cache key.';_Diagnostic-Limit $State 'cache-key' 1}
    'Uia' {
      _Diagnostic-Fields $value @('focused_window','max_elements')
      _Diagnostic-Require ($op -ceq 'self-test' -and $rest -contains '--deep' -and $value.focused_window -is [string] -and $value.focused_window -ceq '' -and ($value.max_elements -is [int] -or $value.max_elements -is [long]) -and $value.max_elements -eq 50) 'UIA check exceeds fixed self-test scope.'
      _Diagnostic-Limit $State 'uia' 1
    }
    'Notice' {
      $expected='self-test 시작 (deep='+[bool]($rest -contains '--deep')+', strict='+[bool]($rest -contains '--strict')+')'
      _Diagnostic-Require ($op -ceq 'self-test' -and $name -ceq 'INFO' -and $value -is [string] -and $value -ceq $expected) 'Invalid self-test notice.';_Diagnostic-Limit $State 'notice' 1
    }
  }
}
function _Diagnostic-Clock($State,[string]$Name,[string]$Scope) {
  if($Name -ceq 'start'){$State.clocks[$Scope]=[Diagnostics.Stopwatch]::StartNew();return 0}
  _Diagnostic-Require ($State.clocks.ContainsKey($Scope)) 'Diagnostic clock was not started.'
  if($Name -ceq 'stop'){$State.clocks[$Scope].Stop()}
  if($Scope -ceq 'benchmark-sample'){return [int]$State.clocks[$Scope].ElapsedMilliseconds}
  return [int]$State.clocks[$Scope].Elapsed.TotalMilliseconds
}
function _Diagnostic-NodeVersion {
  $output=& node --version 2>&1
  return [pscustomobject]@{exit=$LASTEXITCODE;output=$(if($null -eq $output){$null}else{"$output"})}
}
function _Diagnostic-TailBytes([string]$Path,[int]$Maximum) {
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
  try {
    $total=[long]$stream.Length;$start=[long][Math]::Max(0,$total-$Maximum)
    [void]$stream.Seek($start,[IO.SeekOrigin]::Begin)
    $length=[int][Math]::Min($total-$start,[long]$Maximum)
    $buffer=New-Object byte[] $length;$read=$stream.Read($buffer,0,$length)
    return [pscustomobject]@{total_bytes=$total;tail_bytes=$length;text=[Text.Encoding]::UTF8.GetString($buffer,0,$read)}
  } finally {$stream.Dispose()}
}
function _Diagnostic-AssertOwnedRoot([string]$Path) {
  _Diagnostic-Require ([IO.Path]::IsPathRooted($Path)) 'Diagnostic owned directory must be absolute.'
  $full=[IO.Path]::GetFullPath($Path);$current=$full
  while($current){
    if(Test-Path -LiteralPath $current){
      $item=Get-Item -LiteralPath $current -Force -ErrorAction Stop
      _Diagnostic-Require (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Diagnostic owned directory traverses a reparse point.'
    }
    $parent=[IO.Path]::GetDirectoryName($current)
    if($parent -eq $current){break};$current=$parent
  }
  if(Test-Path -LiteralPath $full){$full=[IO.Path]::GetFullPath((Get-Item -LiteralPath $full -Force -ErrorAction Stop).FullName)}
  return $full
}
function _Diagnostic-PathEquals([string]$Left,[string]$Right) {
  return [string]::Equals([IO.Path]::GetFullPath($Left).TrimEnd([char[]]@('\','/')),[IO.Path]::GetFullPath($Right).TrimEnd([char[]]@('\','/')),[StringComparison]::OrdinalIgnoreCase)
}
function _Diagnostic-AuditProbe([string]$Directory,[string]$Prefix) {
  $full=_Diagnostic-AssertOwnedRoot $Directory
  if(-not (Test-Path -LiteralPath $full)){New-Item -ItemType Directory -Path $full -Force | Out-Null}
  $path=Join-Path $full ($Prefix+[guid]::NewGuid().ToString())
  _Diagnostic-Require (_Diagnostic-PathEquals ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($path))) $full) 'Probe escaped its owned directory.'
  Set-Content -LiteralPath $path -Value 'ok' -Encoding UTF8
  Remove-Item -LiteralPath $path -Force
}
function _Diagnostic-ClearAppshotCache([string]$Directory) {
  $full=_Diagnostic-AssertOwnedRoot $Directory
  foreach($item in @(Get-ChildItem -LiteralPath $full -Filter 'appshot-*.json' -ErrorAction SilentlyContinue)) {
    # An appshot cache entry is a regular file. Directory/reparse entries are not
    # cache artifacts and never acquire deletion authority from their filename.
    if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){continue}
    $path=[IO.Path]::GetFullPath($item.FullName)
    _Diagnostic-Require (_Diagnostic-PathEquals ([IO.Path]::GetDirectoryName($path)) $full) 'Cache entry escaped its owned directory.'
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
  }
}
function _Diagnostic-CapturedMacro([string]$Name,[string[]]$Argv) {
  $previous=[Console]::Out;$writer=New-Object IO.StringWriter
  try {
    [Console]::SetOut($writer)
    switch -CaseSensitive ($Name) {
      'metrics' {$result=Invoke-MacroMetrics -Rest $Argv}
      'health-quick' {$result=Invoke-MacroHealthQuick -Rest $Argv}
      'windows' {$result=Invoke-MacroWindows -Rest $Argv}
      'find-label' {$result=Invoke-MacroFindLabel -Rest $Argv}
      default {throw 'Unsupported diagnostic macro.'}
    }
    return ,$result
  } finally {[Console]::SetOut($previous);$writer.Dispose()}
}
function _Diagnostic-Dispatch($Effect,$State) {
  $kind=$Effect.name;$name=$Effect.data.name;$value=$Effect.data.value;$a=[string[]]$Effect.argv;$c=$State.context
  switch -CaseSensitive ($kind) {
    'Clock' {return _Diagnostic-Clock $State $name $value}
    'Timestamp' {return (Get-Date).ToString('o')}
    'NodeVersion' {return ,(_Diagnostic-NodeVersion)}
    'Cli' {$r=Invoke-Cucp -ArgList $a -CaptureJson;return [pscustomobject]@{exit=$r.ExitCode;json=$r.Json}}
    'Native' {$r=Invoke-NativeHelper -ArgList $a;return [pscustomobject]@{exit=$r.ExitCode;json=$r.Json}}
    'Macro' {return ,(_Diagnostic-CapturedMacro $name $a)}
    'FileExists' {return Test-Path -LiteralPath ([string]$value)}
    'FileStat' {return [pscustomobject]@{length=[long](Get-Item -LiteralPath ([string]$value)).Length}}
    'ListFiles' {
      $parameters=@{LiteralPath=[string]$value.path;ErrorAction='SilentlyContinue'}
      if($value.recurse){$parameters.Recurse=$true};if($value.file){$parameters.File=$true};if($null -ne $value.filter){$parameters.Filter=[string]$value.filter}
      $items=@(Get-ChildItem @parameters);$rows=New-Object Collections.ArrayList
      foreach($item in $items){
        [void]$rows.Add([pscustomobject]@{full_name=[string]$item.FullName;length=$item.Length;last_write_time=$item.LastWriteTime.ToString('o')})
        if($State.operation -ceq 'audit-summary'){$State.diagnostic_audit_files[[string]$item.FullName]=$true}
      }
      return ,([object[]]$rows.ToArray())
    }
    'ReadLines' {
      if($State.operation -ceq 'audit-summary'){$lines=@(Get-Content -LiteralPath ([string]$value) -Encoding UTF8 -ErrorAction SilentlyContinue)}
      else{$lines=@(Get-Content -LiteralPath ([string]$value))}
      return ,([object[]]$lines)
    }
    'ReadText' {return (@(Get-Content -LiteralPath ([string]$value) -Raw) -join '')}
    'ResolvePath' {
      $resolved=Resolve-Path -LiteralPath ([string]$value) -ErrorAction SilentlyContinue
      if($resolved){$State.diagnostic_changelog=[string]$resolved.Path;return [string]$resolved.Path};return $null
    }
    'TailBytes' {return ,(_Diagnostic-TailBytes ([string]$value.path) ([int]$value.max_bytes))}
    'AuditProbe' {_Diagnostic-AuditProbe ([string]$value) $name;return}
    'ClearAppshotCache' {_Diagnostic-ClearAppshotCache ([string]$value);return}
    'EnsureWin32' {return _Ensure-Win32Loaded}
    'EnsureUia' {return _Ensure-UIALoaded}
    'HelperUp' {return _Helper-IsUp}
    'FindCodex' {return _Find-CodexCli}
    'Processes' {return ,(_Diagnostic-Processes $State)}
    'ProcessMetrics' {return ,(_Diagnostic-ProcessMetrics $State ([int]$value.current_ordinal) $value.previous_ordinal)}
    'ProcessorCount' {return _Diagnostic-ProcessorCount}
    'Windows' {return ,([object[]]@(_Enumerate-Win32Windows -Match $null))}
    'Sleep' {Start-Sleep -Milliseconds ([int]$value);return}
    'AssertAuthorized' {
      # Original self-test catches every assertion exception as a completed
      # blocked policy result. No actuation is requested by this fixed check.
      try {Assert-Authorized -ArgList $a;return $false}catch{return $true}
    }
    'Appshot' {
      $parameters=@{Match=[string]$value.match;Semantic=[bool]$value.semantic;NoCache=[bool]$value.no_cache}
      if($null -ne $value.cache_max_seconds){$parameters.CacheMaxSeconds=[int]$value.cache_max_seconds}
      return ,(Invoke-Appshot @parameters)
    }
    'CacheKey' {
      $key=Get-CacheKey -Match ([string]$value)
      _Diagnostic-Require ($key -is [string] -and $key -match '^[A-Za-z0-9_-]+$') 'Cache-key provider returned a path-bearing key.'
      $State.diagnostic_cache_path=Join-Path $c.cache_directory ('appshot-'+$key+'.json')
      return $key
    }
    'Uia' {return ,(_Get-UIAffordances -FocusedWindow '' -MaxElements 50)}
    'Notice' {Write-Notice -Level $name -Message ([string]$value);return}
    default {throw 'Unknown diagnostic acquisition.'}
  }
}
function _Diagnostic-PreparePayload($Payload,$State) {
  # The family operation is captured before launch. Terminal model annotations
  # cannot turn arbitrary objects into Hashtables or choose their paths.
  if($State.operation -ceq 'audit-summary'){
    _Diagnostic-Require ($null -ne $Payload -and $Payload.schema -ceq 'cucp.audit-summary/v1') 'Invalid audit-summary completion.'
    foreach($name in @('by_macro','by_exit_code')){
      $object=$Payload.$name;_Diagnostic-Require ($null -ne $object -and $object -isnot [array] -and $object -isnot [string] -and $object -isnot [ValueType]) 'Invalid audit counter map.'
      # Audit initializes each new counter, then assigns its incremented value.
      # Hashtable may expand even on that second assignment; preserve its raw order.
      $map=@{};foreach($property in $object.PSObject.Properties){$map[$property.Name]=0;$map[$property.Name]=$property.Value};$Payload.$name=$map
    }
  } elseif($State.operation -ceq 'diagnose-lag'){
    _Diagnostic-Require ($null -ne $Payload -and $Payload.schema -ceq 'cucp.diagnose-lag/v1' -and $Payload.processes -is [array]) 'Invalid diagnose-lag completion.'
    foreach($process in $Payload.processes){
      $object=$process.priority_classes;_Diagnostic-Require ($null -ne $object -and $object -isnot [array] -and $object -isnot [string] -and $object -isnot [ValueType]) 'Invalid priority counter map.'
      $map=@{};foreach($property in $object.PSObject.Properties){$map[$property.Name]=$property.Value};$process.priority_classes=$map
    }
  }
  return ,$Payload
}
function _Diagnostic-GetContext {
  return [pscustomobject][ordered]@{
    audit_directory=[string]$Script:AuditDir;cache_directory=[string]$Script:CacheDir;wrapper_log=[string]$Script:WrapperLog;
    cli_path=$Script:CliPath;changelog_path=(Join-Path $PSScriptRoot '..\CHANGELOG.md');
    temp_root=(Join-Path $env:TEMP 'computer-use-control-plane');benchmark_schema=[string]$Script:CucpV14Schema.Benchmark;release_schema=[string]$Script:CucpV14Schema.ReleaseNotes
  }
}
function _Diagnostic-ProcessorCount {return [Environment]::ProcessorCount}
function _Invoke-LegacyDiagnosticFamily {
  param([ValidateSet('perf','diagnose-lag','health-quick','health-detail','log-tail','benchmark','self-test','audit-summary','release-notes')][string]$Operation,[string[]]$Rest)
  $context=_Diagnostic-GetContext
  $state=_Diagnostic-NewState -Operation $Operation -Rest $Rest -Context $context
  $startup=[ordered]@{schema='cucp.diagnostic-start/v1';operation=$Operation;rest=[string[]]@($Rest);brief=[bool]$Brief;
    cache_seconds=[int]$CacheSeconds;vision_available=[bool]$Script:CliPath;culture=[Globalization.CultureInfo]::CurrentCulture.Name;context=$state.context}
  try {return _Invoke-LegacyExecutionHost -EntryPoint 'legacy-diagnostic-session' -Startup $startup -State $state}
  finally {_Diagnostic-DisposeProcesses $state}
}
function _Diagnostic-Processes($State) {
  $snapshot=[object[]]@(Get-Process -ErrorAction SilentlyContinue)
  [void]$State.diagnostic_process_lists.Add($snapshot)
  $rows=[object[]]@(foreach($process in $snapshot){[pscustomobject]@{id=$process.Id;name=$process.ProcessName}})
  [void]$State.diagnostic_process_rows.Add($rows)
  if($State.diagnostic_process_rows.Count -eq 2){
    $order=New-Object Collections.ArrayList
    foreach($group in @(@{names=@('codex')},@{names=@('electron','Code','Cursor','Windsurf')},@{names=@('node')},@{names=@('powershell','pwsh')},@{names=@('chrome','msedge','brave','whale')},@{names=@('cucp-helper','windows-mcp-helper')})){
      for($index=0;$index -lt $rows.Count;$index++){if($rows[$index].name -in $group.names){[void]$order.Add($index)}}
    }
    $State.diagnostic_metric_order=[object[]]$order.ToArray()
  }
  return ,$rows
}
function _Diagnostic-ProcessMetrics($State,[int]$CurrentOrdinal,$PreviousOrdinal) {
  $process=$State.diagnostic_process_lists[1][$CurrentOrdinal]
  $previous=$null;if($null -ne $PreviousOrdinal){$previous=$State.diagnostic_process_lists[0][[int]$PreviousOrdinal]}
  $metrics=[ordered]@{}
  # Preserve original native getter ordering and independent caught failures.
  try {$metrics.private_bytes=[long]$process.PrivateMemorySize64} catch {}
  try {$metrics.started_at=$process.StartTime.ToString('o')} catch {}
  try {
    if($null -ne $previous){
      $currentCpu=$process.TotalProcessorTime.TotalMilliseconds
      $previousCpu=$previous.TotalProcessorTime.TotalMilliseconds
      $metrics.current_cpu_ms=$currentCpu;$metrics.previous_cpu_ms=$previousCpu
    }
  } catch {}
  try {$metrics.priority=[string]$process.PriorityClass} catch {}
  return [pscustomobject]$metrics
}
function _Diagnostic-DisposeProcesses($State) {
  foreach($snapshot in $State.diagnostic_process_lists){foreach($process in $snapshot){if($process -is [Diagnostics.Process]){try{$process.Dispose()}catch{}}}}
  $State.diagnostic_process_lists.Clear()
}
