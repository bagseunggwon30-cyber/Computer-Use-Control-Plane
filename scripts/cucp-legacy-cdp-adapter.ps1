# Retained CDP host glue; business logic runs in Python.
# New bridge/delegation code only. Business logic lives in pcucp_cli.legacy_cdp*.
# Tests load exact functions with the PowerShell AST. No top-level execution.

# region cdp-process-bridge
function _Invoke-LegacyCdpBridge {
  param([ValidateSet('native','native-prepare','macro-prepare','macro-complete')][string]$Operation,
        [hashtable]$Request, [switch]$LiveAuthority, [int]$Port = 9222)
  $hostExe = $env:CUCP_LEGACY_CDP_HOST
  if ($hostExe) {
    $executable = [IO.Path]::GetFullPath($hostExe)
    $prefix = 'legacy-cdp-bridge'
    $directory = [IO.Path]::GetDirectoryName($executable)
  } else {
    $python = $env:CUCP_LEGACY_CDP_PYTHON
    if (-not $python) { $python = (Get-Command python.exe -CommandType Application -ErrorAction Stop).Source }
    $executable = [IO.Path]::GetFullPath($python)
    $prefix = '-E -B -m pcucp_cli.legacy_cdp_bridge'
    $directory = Join-Path $Script:LegacyCdpSourceRoot 'pcucp-next\python'
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'pcucp_cli\legacy_cdp_bridge.py') -PathType Leaf)) { throw 'Matching CDP module is missing; no fallback was attempted.' }
  }
  if ([IO.Path]::GetExtension($executable) -ne '.exe' -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'Matching CDP executable is missing; no fallback was attempted.' }
  $utf8 = New-Object Text.UTF8Encoding($false, $true)
  $bytes = $utf8.GetBytes(($Request | ConvertTo-Json -Depth 32 -Compress) + "`n")
  if ($bytes.Length -gt 1048576) { throw 'CDP bridge request exceeds 1 MiB; no retry was attempted.' }
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = $executable
  $psi.WorkingDirectory = $directory
  $psi.Arguments = $prefix + ' --operation ' + $Operation
  if ($Operation -eq 'native') {
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'CDP endpoint port is outside 1..65535.' }
    $psi.Arguments += ' --endpoint http://127.0.0.1:' + $Port + ' --timeout-s 8'
  }
  if ($LiveAuthority) { $psi.Arguments += ' --allow-live-control' }
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = $utf8
  $psi.StandardErrorEncoding = $utf8
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $psi
  $started = $false
  try {
    [void]$process.Start(); $started = $true
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $out = New-Object Text.StringBuilder
    $err = New-Object Text.StringBuilder
    $outBuffer = New-Object char[] 16384
    $errBuffer = New-Object char[] 16384
    $outRead = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length)
    $errRead = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length)
    $write = $process.StandardInput.BaseStream.WriteAsync($bytes, 0, $bytes.Length)
    $inputClosed = $false
    while (-not ($process.HasExited -and $null -eq $outRead -and $null -eq $errRead)) {
      $progressed = $false
      if ($watch.ElapsedMilliseconds -ge 15000) { throw 'CDP bridge timed out; no retry was attempted.' }
      if (-not $inputClosed -and $write.IsCompleted) {
        [void]$write.GetAwaiter().GetResult(); $process.StandardInput.Close(); $inputClosed = $true
        $progressed = $true
      }
      if ($null -ne $outRead -and $outRead.IsCompleted) {
        $progressed = $true
        $n = $outRead.GetAwaiter().GetResult()
        if ($out.Length + $n -gt 4194304) { throw 'CDP bridge stdout exceeds 4 MiB; no retry was attempted.' }
        if ($n -gt 0) { [void]$out.Append($outBuffer, 0, $n); $outRead = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length) }
        else { $outRead = $null }
      }
      if ($null -ne $errRead -and $errRead.IsCompleted) {
        $progressed = $true
        $n = $errRead.GetAwaiter().GetResult()
        if ($err.Length + $n -gt 65536) { throw 'CDP bridge stderr exceeds 64 KiB; no retry was attempted.' }
        if ($n -gt 0) { [void]$err.Append($errBuffer, 0, $n); $errRead = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length) }
        else { $errRead = $null }
      }
      if (-not $progressed) {
        if (-not $process.HasExited) { [void]$process.WaitForExit(1) }
        else { [Threading.Thread]::Sleep(1) }
      }
    }
    $response = $out.ToString() | ConvertFrom-Json -ErrorAction Stop
    if ($response.schema -ne 'cucp.legacy-cdp-bridge/v1') { throw 'Invalid CDP bridge schema; no retry was attempted.' }
    if ($process.ExitCode -ne 0 -or $response.status -ne 'ok') {
      if ($response.error.message -is [string]) { throw $response.error.message }
      throw 'CDP bridge failed; no retry was attempted.'
    }
    if ($null -eq $response.data) { throw 'Missing CDP bridge data; no retry was attempted.' }
    return $response.data
  } finally {
    if ($started -and -not $process.HasExited) {
      try { $process.Kill(); [void]$process.WaitForExit(1000) } catch { }
    }
    $process.Dispose()
  }
}
# endregion

# region cdp-macro-delegate
function _Invoke-LegacyCdpMacro {
  param([string]$ActionName, [string[]]$Rest)
  $argv = @()
  if ($null -ne $Rest) { $argv = @($Rest) }
  $request = @{action=$ActionName; argv=@($argv)}
  $state = _Invoke-LegacyCdpBridge -Operation 'macro-prepare' -Request $request -LiveAuthority:([bool]$AllowLiveControl)
  $opened = [bool](Test-CdpPortQuick -Port ([int]$state.port) -TimeoutMs 120)
  $reply = $null
  $mayHaveActed = $false
  try {
    if ($opened) {
      $mayHaveActed = [bool]$AllowLiveControl -and $ActionName -in @('cdp-eval','cdp-type','cdp-click','cdp-smart-click','cdp-smart-type','cdp-prosemirror-insert')
      $r = Invoke-NativeHelper -ArgList @($state.native_argv)
      $reply = @{ExitCode=[int]$r.ExitCode; Json=$r.Json; Raw=$r.Raw}
    }
    $request = @{action=$ActionName; argv=@($argv); port_open=$opened; reply=$reply}
    $state = _Invoke-LegacyCdpBridge -Operation 'macro-complete' -Request $request -LiveAuthority:([bool]$AllowLiveControl)
    if ($null -ne $state.trajectory) { _Trajectory-Append -Kind $state.trajectory.kind -Payload $state.trajectory.payload }
    if ($Brief) { [Console]::Out.WriteLine([string]$state.brief_line) }
    elseif ($state.raw_passthrough) { if ($state.raw) { [Console]::Out.Write([string]$state.raw) } }
    else { [Console]::Out.WriteLine(($state.payload | ConvertTo-Json -Depth ([int]$state.json_depth))) }
    return [int]$state.exit_code
  } catch {
    if (-not $mayHaveActed) { throw }
    # Fixed small JSON does not depend on the failed serializer or log sink.
    # ActionName was validated by macro-prepare before any live dispatch.
    $failure = '{"status":"partial","reason":"cdp_post_dispatch_reporting_failed","action":"' + $ActionName + '","mutation_may_have_occurred":true,"automatic_retry":false}'
    try { [Console]::Out.WriteLine($failure) }
    catch { try { [Console]::Error.WriteLine($failure) } catch { } }
    return 2
  }
}
function Invoke-MacroCdpDetect { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-detect' $Rest) }
function Invoke-MacroCdpEval { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-eval' $Rest) }
function Invoke-MacroCdpType { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-type' $Rest) }
function Invoke-MacroCdpClick { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-click' $Rest) }
function Invoke-MacroCdpSmartFind { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-smart-find' $Rest) }
function Invoke-MacroCdpSmartTypeFind { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-smart-type-find' $Rest) }
function Invoke-MacroCdpSmartClick { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-smart-click' $Rest) }
function Invoke-MacroCdpSmartType { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-smart-type' $Rest) }
function Invoke-MacroCdpDeepFind { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-deep-find' $Rest) }
function Invoke-MacroCdpProseMirrorInsert { param([string[]]$Rest) return (_Invoke-LegacyCdpMacro 'cdp-prosemirror-insert' $Rest) }
# endregion

# region cdp-native-intercept
function _Invoke-LegacyCdpNativeArgv {
  param([string[]]$ArgList, [switch]$LiveAuthority)
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $prepared = _Invoke-LegacyCdpBridge -Operation 'native-prepare' -Request @{argv=@($ArgList)}
  $mayHaveActed = [bool]$LiveAuthority -and $prepared.action -in @('cdp-eval','cdp-type','cdp-click','cdp-smart-click','cdp-smart-type','cdp-prosemirror-insert')
  try {
    $result = _Invoke-LegacyCdpBridge -Operation 'native' -Request @{action=$prepared.action;args=$prepared.args} -Port ([int]$prepared.port) -LiveAuthority:$LiveAuthority
  } catch {
    $result = @{exit_code=2;payload=[ordered]@{status='partial';reason='cdp_bridge_failed';detail=$_.Exception.Message;mutation_may_have_occurred=$mayHaveActed;action=$prepared.action;elapsed_ms=[int]$watch.ElapsedMilliseconds}}
  }
  $raw = ($result.payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine
  return [pscustomobject]@{ExitCode=[int]$result.exit_code;Json=$result.payload;Raw=$raw;Err='';ElapsedMs=[int]$watch.ElapsedMilliseconds;FromHotCache=$false;Route='python-cdp'}
}
# endregion

# region cdp-native-delegate
function _Invoke-LegacyCdpNative {
  param([string]$ActionName)
  $live = $false
  if ($null -ne $CdpStartup) {
    if ($CdpStartup -isnot [hashtable] -or $CdpStartup.PSBase.Count -ne 1 -or -not $CdpStartup.PSBase.ContainsKey('allow_live_control') -or $CdpStartup['allow_live_control'] -isnot [bool]) { throw 'Invalid typed CDP startup authority.' }
    $live = [bool]$CdpStartup['allow_live_control']
  }
  $arguments = @{page_match=[string]$CdpPageMatch}
  if ($ActionName -eq 'cdp-eval') { $arguments.expression=[string]$CdpExpr; $arguments.expression_b64=[string]$CdpExprB64 }
  if ($ActionName -in @('cdp-type','cdp-click','cdp-prosemirror-insert')) { $arguments.selector=[string]$CdpSelector }
  if ($ActionName -like 'cdp-smart-*' -or $ActionName -eq 'cdp-deep-find') { $arguments.needle=[string]$CdpText }
  if ($ActionName -in @('cdp-type','cdp-smart-type')) { $arguments.text=[string]$Text; $arguments.clear=[bool]$ClearFirst; $arguments.enter=[bool]$PressEnter }
  if ($ActionName -eq 'cdp-prosemirror-insert') { $arguments.text=[string]$CdpText }
  $mayHaveActed = $live -and $ActionName -in @('cdp-eval','cdp-type','cdp-click','cdp-smart-click','cdp-smart-type','cdp-prosemirror-insert')
  try {
    $result = _Invoke-LegacyCdpBridge -Operation 'native' -Request @{action=$ActionName;args=$arguments} -Port $CdpPort -LiveAuthority:$live
  } catch {
    $result = @{exit_code=2;payload=[ordered]@{status='partial';reason='cdp_bridge_failed';detail=$_.Exception.Message;mutation_may_have_occurred=$mayHaveActed}}
  }
  $payload = [ordered]@{}
  if ($result.payload -is [Collections.IDictionary]) { foreach ($key in $result.payload.Keys) { $payload[$key]=$result.payload[$key] } }
  else { foreach ($property in $result.payload.PSObject.Properties) { $payload[$property.Name]=$property.Value } }
  _Emit $payload ([int]$result.exit_code)
}
function _Action-CdpDetect { _Invoke-LegacyCdpNative 'cdp-detect' }
function _Action-CdpEval { _Invoke-LegacyCdpNative 'cdp-eval' }
function _Action-CdpType { _Invoke-LegacyCdpNative 'cdp-type' }
function _Action-CdpClick { _Invoke-LegacyCdpNative 'cdp-click' }
function _Action-CdpSmartFind { _Invoke-LegacyCdpNative 'cdp-smart-find' }
function _Action-CdpSmartTypeFind { _Invoke-LegacyCdpNative 'cdp-smart-type-find' }
function _Action-CdpSmartClick { _Invoke-LegacyCdpNative 'cdp-smart-click' }
function _Action-CdpSmartType { _Invoke-LegacyCdpNative 'cdp-smart-type' }
function _Action-CdpDeepFind { _Invoke-LegacyCdpNative 'cdp-deep-find' }
function _Action-CdpProseMirrorInsert { _Invoke-LegacyCdpNative 'cdp-prosemirror-insert' }
# endregion
