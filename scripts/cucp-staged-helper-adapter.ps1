# Explicit unqualified cutover only. No defaults change and no PS-service fallback.
# Authority is copied once at wrapper startup, never read from pipe/JSON requests.
$Script:StagedCompiledHelper = $env:CUCP_STAGED_COMPILED_HELPER -ceq '1'
if ($env:CUCP_STAGED_COMPILED_HELPER -and -not $Script:StagedCompiledHelper) {
  throw 'CUCP_STAGED_COMPILED_HELPER accepts only 1 or an unset value.'
}
# Isolated staged lock prevents reusing the retained PowerShell service.
if ($Script:StagedCompiledHelper) { $Script:HelperLockPath = Join-Path $Script:AuditDir 'helper-staged.pid' }
# This is launch authority for this shared service, not a global wrapper policy.
$Script:StagedHelperDesktop = $env:CUCP_STAGED_HELPER_READONLY_DESKTOP -ceq '1'
if ($env:CUCP_STAGED_HELPER_READONLY_DESKTOP -and -not $Script:StagedHelperDesktop) {
  throw 'CUCP_STAGED_HELPER_READONLY_DESKTOP accepts only 1 or an unset value.'
}

function _Invoke-StagedHelper {
  param([string]$Operation, [hashtable]$Arguments = @{})
  if (-not $Script:StagedCompiledHelper) { throw 'Staged helper was not selected at startup.' }
  $bridge = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\pcucp-next\python\legacy_helper_bridge.py'))
  if (-not (Test-Path -LiteralPath $bridge -PathType Leaf)) { throw 'Staged helper bridge missing; no fallback.' }
  $python = Get-Command python.exe -CommandType Application -ErrorAction Stop
  foreach ($path in @($bridge, $Script:HelperLockPath)) {
    if ($path.Contains('"') -or $path.Contains("`r") -or $path.Contains("`n") -or $path.EndsWith('\')) {
      throw 'Invalid staged helper bootstrap path.'
    }
  }
  $utf8 = New-Object Text.UTF8Encoding($false, $true)
  $payload = @{operation=$Operation; arguments=$Arguments} | ConvertTo-Json -Depth 24 -Compress
  $bytes = $utf8.GetBytes($payload)
  if ($bytes.Length -gt 1048576) { throw 'Staged helper request exceeds 1 MiB.' }
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = $python.Source
  # -I excludes inherited PYTHONPATH/user site; script directory imports remain
  # unavailable under -I, so -E -s give source-mode imports with env isolation.
  $psi.Arguments = '-E -s "' + $bridge + '" --staged-unqualified --lock-file "' + $Script:HelperLockPath + '"'
  if ($Script:StagedHelperDesktop) { $psi.Arguments += ' --allow-readonly-desktop' }
  $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true
  $psi.RedirectStandardInput=$true; $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
  $psi.StandardOutputEncoding=$utf8; $psi.StandardErrorEncoding=$utf8
  $process = New-Object Diagnostics.Process
  $process.StartInfo=$psi
  $started=$false
  try {
    try { [void]$process.Start(); $started=$true }
    catch {
      $launchError = $_
      # Only resolution metadata on this failure path; no environment, argv,
      # request data, retries or alternate executable selection.
      try {
        $commands = @($python)
        $resolved = @(foreach ($command in @($commands | Select-Object -First 4)) {
          $pathText = [string]$command.Path; $sourceText = [string]$command.Source
          [pscustomobject]@{command_type=[string]$command.CommandType;
            path=$pathText.Substring(0,[Math]::Min(1024,$pathText.Length));
            source=$sourceText.Substring(0,[Math]::Min(1024,$sourceText.Length))}
        })
        $fileName = [string]$psi.FileName
        $launchMetadata = @{command_count=$commands.Count; commands=$resolved;
          file_name=$fileName.Substring(0,[Math]::Min(1024,$fileName.Length))} | ConvertTo-Json -Depth 4 -Compress
        Write-WrapperLog -Message ('STAGED HELPER LAUNCH RESOLUTION ' + $launchMetadata)
      } catch { }
      throw $launchError
    }
    $write=$process.StandardInput.BaseStream.WriteAsync($bytes,0,$bytes.Length)
    $inputClosed=$false
    $outBuffer=New-Object char[] 4096; $errBuffer=New-Object char[] 4096
    $outTask=$process.StandardOutput.ReadAsync($outBuffer,0,$outBuffer.Length)
    $errTask=$process.StandardError.ReadAsync($errBuffer,0,$errBuffer.Length)
    $out=New-Object Text.StringBuilder; $err=New-Object Text.StringBuilder
    $outDone=$false; $errDone=$false
    $budget=15000L
    if ($Operation -ceq 'invoke') { $budget=[Math]::Max($budget,([long]$Arguments.timeout_ms + 7000L)) }
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while (-not ($inputClosed -and $outDone -and $errDone -and $process.HasExited)) {
      if ($timer.ElapsedMilliseconds -gt $budget) { throw 'Staged helper timed out; operation not retried.' }
      if (-not $inputClosed -and $write.IsCompleted) {
        $write.GetAwaiter().GetResult(); $process.StandardInput.Close(); $inputClosed=$true
      }
      if (-not $outDone -and $outTask.IsCompleted) {
        $n=$outTask.GetAwaiter().GetResult()
        if ($n -eq 0) { $outDone=$true }
        else {
          if ($out.Length + $n -gt 2097152) { throw 'Staged helper output limit exceeded.' }
          [void]$out.Append($outBuffer,0,$n)
          $outTask=$process.StandardOutput.ReadAsync($outBuffer,0,$outBuffer.Length)
        }
      }
      if (-not $errDone -and $errTask.IsCompleted) {
        $n=$errTask.GetAwaiter().GetResult()
        if ($n -eq 0) { $errDone=$true }
        else {
          if ($err.Length + $n -gt 65536) { throw 'Staged helper error-output limit exceeded.' }
          [void]$err.Append($errBuffer,0,$n)
          $errTask=$process.StandardError.ReadAsync($errBuffer,0,$errBuffer.Length)
        }
      }
      Start-Sleep -Milliseconds 5
    }
    $response=$out.ToString() | ConvertFrom-Json -ErrorAction Stop
    if ($process.ExitCode -ne 0 -or $response.schema -cne 'cucp.staged-helper-bridge/v1' -or $response.status -cne 'ok') {
      throw ('Staged helper failed; no fallback or retry: ' + $response.reason)
    }
    return $response.data
  } finally {
    # Only the just-launched bridge handle is owned here. Its detached service
    # is intentionally not in a parent-death job and is never killed by PID.
    if ($started -and -not $process.HasExited) { try { $process.Kill() } catch { } }
    $process.Dispose()
  }
}
