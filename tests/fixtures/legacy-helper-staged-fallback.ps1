# Execute the actual wrapper functions with a failing bridge and inert child.
param([Parameter(Mandatory=$true)][string]$Wrapper,[Parameter(Mandatory=$true)][string]$Work)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Wrapper,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Production wrapper parse failed' }
$names=@('_Read-LockSafely','_Is-StaleLock','_Try-Delete-Lock','_Read-HelperServerVersion','Invoke-NativeHelper','ConvertTo-ProcessArgumentString')
foreach ($name in $names) {
  $found=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
  if ($found.Count -ne 1) { throw ('Missing unique production function: '+$name) }
  . ([scriptblock]::Create($found[0].Extent.Text))
}
function _Invoke-StagedHelper { throw 'Injected unavailable staged bridge' }
function Write-WrapperLog { param([string]$Message) }
$Script:StagedCompiledHelper=$true
$Script:NativeHelperPath=Join-Path $PSScriptRoot 'legacy-helper-staged-child.ps1'
$Script:CacheDir=$Work;$Script:CacheSeconds=2;$Script:InvokeTimeoutMs=10000
$Script:HelperServerSupported=@('health')
$env:CUCP_FORCE_CHILD=$null;$env:CUCP_HOT_CACHE_DISABLE=$null
$Script:HotCache=@{'health|'=@{expires_ticks=[DateTime]::UtcNow.AddMinutes(1).Ticks;exit_code=0;json=@{fixture='hot-cache'};raw='{"fixture":"hot-cache"}'}}
$cached=Invoke-NativeHelper -ArgList @('-Action','health')
if ($cached.Route -cne 'hot-cache' -or $cached.Json.fixture -cne 'hot-cache') { throw 'Broken bridge did not preserve hot cache' }
$Script:HotCache=@{}
$child=Invoke-NativeHelper -ArgList @('-Action','health')
if ($child.Route -cne 'child' -or $child.ExitCode -ne 0 -or $child.Json.fixture -cne 'one-shot-read') { throw 'Broken bridge did not preserve one-shot read fallback' }
$version=_Read-HelperServerVersion
if ($version.error -cne 'helper_compiled_runtime_unavailable' -or $null -ne $version.version) { throw 'Broken bridge lost recoverable version metadata' }
_Try-Delete-Lock -ExpectedLock $null
[Console]::Out.WriteLine('{"status":"ok","checks":4,"desktop_acquired":false}')
