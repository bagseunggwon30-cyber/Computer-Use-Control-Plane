# Production wrapper path under an isolated TEMP root; no desktop launch authority.
param(
  [Parameter(Mandatory=$true)][string]$Wrapper,
  [Parameter(Mandatory=$true)][ValidateSet('start','status','stop','version')][string]$Operation
)
$ErrorActionPreference='Stop'
if ($env:CUCP_STAGED_COMPILED_HELPER -cne '1' -or $env:CUCP_STAGED_HELPER_READONLY_DESKTOP) {
  throw 'Owned staged fixture requires explicit staged mode and denied desktop launch authority.'
}
switch ($Operation) {
  'start' { & $Wrapper -Quiet -CucpArgs @('macro','session','start-helper','--idle-timeout-ms','10000') }
  'status' { & $Wrapper -Quiet -CucpArgs @('macro','session','helper-status') }
  'stop' { & $Wrapper -Quiet -CucpArgs @('macro','session','stop-helper','--force') }
  'version' { & $Wrapper -Quiet -CucpArgs @('macro','version') }
}
