# Parsed as fixture data only. Definitions replace only the final family entry
# in a disposable copied support module; this file is never dot-sourced.
function _Invoke-LegacyInteractionFamily {
  param([string]$Operation,[string[]]$Rest,[string]$ScriptPath,[bool]$Double=$false,[bool]$RightClick=$false)
  if($global:CUCP_STARTUP_MODE -ceq 'blocked-provider'){Invoke-NativeHelper -ArgList @('-Action','windows');throw 'Provider guard failed'}
  return Write-StartupRecord -Family 'interaction' -Operation $Operation -Rest $Rest -ScriptPath $ScriptPath -Double $Double -RightClick $RightClick `
    -Live ([bool]$AllowLiveControl) -BriefValue ([bool]$Brief) -CacheValue ([int]$CacheSeconds) -AuditPath ([string]$Script:AuditDir) -CachePath ([string]$Script:CacheDir)
}
function _Invoke-LegacyDiagnosticFamily {
  param([string]$Operation,[string[]]$Rest)
  if($global:CUCP_STARTUP_MODE -ceq 'blocked-provider'){Invoke-NativeHelper -ArgList @('-Action','windows');throw 'Provider guard failed'}
  return Write-StartupRecord -Family 'diagnostics' -Operation $Operation -Rest $Rest `
    -Live ([bool]$AllowLiveControl) -BriefValue ([bool]$Brief) -CacheValue ([int]$CacheSeconds) -AuditPath ([string]$Script:AuditDir) -CachePath ([string]$Script:CacheDir)
}
