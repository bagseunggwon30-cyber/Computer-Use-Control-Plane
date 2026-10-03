# Counted test-only driver. Loads only hash/AST-verified published definitions;
# every process and pipe acquisition is replaced with a closed fixture seam.
# Never dot-source or execute the original script top level.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Manifest,
      [Parameter(Mandatory=$true)][string]$Inputs,
      [Parameter(Mandatory=$true)][string]$Work)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo('en-US')
$manifestValue = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifestValue.published_tree -ne 'e36329b2a6b07539faacd070d661bc0e3819140d' -or
    $manifestValue.published_commit -ne '3e892ab02395bdc916a5814e39d4154efd1f6249') { throw 'Unpublished oracle pin' }
$pin = @($manifestValue.files | Where-Object { $_.path -eq 'scripts/cucp.ps1' })
if ($pin.Count -ne 1) { throw 'Expected one wrapper source pin' }
$pin = $pin[0]
$bytes = [IO.File]::ReadAllBytes($Source)
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $hash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
    if ($bytes.Length -ne $pin.raw_bytes -or $hash -ne $pin.raw_sha256) { throw 'Published wrapper bytes/hash mismatch' }
    $text = [Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF).Replace("`r`n", "`n")
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'Published source parse error' }
    foreach ($name in @('_Is-StaleLock', 'Get-HelperServerStatus', 'Start-HelperServer', 'Stop-HelperServer', 'Invoke-NativeHelper')) {
        $definitions = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true))
        $expected = @($pin.functions | Where-Object { $_.name -eq $name })
        if ($definitions.Count -ne 1 -or $expected.Count -ne 1) { throw "Expected one pinned definition: $name" }
        $definition = $definitions[0]; $expected = $expected[0]
        $bodyBytes = [Text.Encoding]::UTF8.GetBytes($definition.Extent.Text)
        $bodyHash = [BitConverter]::ToString($sha.ComputeHash($bodyBytes)).Replace('-', '').ToLowerInvariant()
        if ($definition.Extent.StartOffset -ne $expected.start_utf16 -or
            $definition.Extent.EndOffset -ne $expected.end_utf16 -or
            $bodyBytes.Length -ne $expected.utf8_bytes -or $bodyHash -ne $expected.sha256) { throw "Pinned AST extent mismatch: $name" }
        . ([scriptblock]::Create($definition.Extent.Text))
    }
} finally { $sha.Dispose() }

# All of these are inert acquisition seams, not substitutes for oracle bodies.
function Get-Date { return [datetime]::Parse('2026-01-02T12:00:00Z').ToUniversalTime().AddMilliseconds($Script:ClockMs) }
function Start-Sleep { param([int]$Milliseconds) $Script:ClockMs += $Milliseconds; $Script:SleepTicks++ }
function Get-Process { param([int]$Id, [string]$ErrorAction) if ($Script:Case.alive -ceq $false) { return $null }; return [pscustomobject]@{ Id = $Id } }
function _Read-LockSafely {
    if ($Script:Case.mode -eq 'start' -and $Script:Case.appear_tick -gt 0 -and $Script:SleepTicks -ge $Script:Case.appear_tick) { return $Script:Case.ready_lock }
    return $Script:FixtureLock
}
function _Try-Delete-Lock { $Script:DeleteCalls++ }
function Write-WrapperLog { param([string]$Message) }
function ConvertTo-ProcessArgumentString { param([string[]]$ArgList) return 'INERT-FIXTURE-ONLY' }
function Invoke-HelperPipe {
    param([string]$Action, [hashtable]$ArgsHash, [int]$TimeoutMs)
    if ($Action -notin @('windows', 'health', 'focused', 'modal-detect', 'ocr-screen-fast', 'uia-find-fast', 'shutdown')) { throw 'Unexpected fixture action' }
    $Script:PipeCalls++
    $Script:Forwarded = $ArgsHash
    if ($Script:Case.pipe_error) { throw 'fixture pipe failure' }
    return $Script:Case.response
}
function Start-Process {
    param([string]$FilePath, [string[]]$ArgumentList,
          [string]$RedirectStandardOutput, [string]$RedirectStandardError,
          [switch]$NoNewWindow, [switch]$PassThru, [string]$WindowStyle, [string]$ErrorAction)
    if ($Script:Case.mode -eq 'start') {
        if ($FilePath -ne 'powershell.exe' -or $ArgumentList -notcontains $Script:HelperServerScript) { throw 'Unexpected detached fixture launch' }
        $Script:LaunchCalls++
        $owned = [pscustomobject]@{ Id = 500 }
        $owned | Add-Member ScriptMethod Kill { $Script:OwnedKills++ }
        return $owned
    }
    if ($FilePath -ne 'powershell' -or ($ArgumentList.Count -ne 1 -or $ArgumentList[0] -ne 'INERT-FIXTURE-ONLY')) { throw 'Unexpected launch boundary' }
    foreach ($path in @($RedirectStandardOutput, $RedirectStandardError)) {
        if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($path)) -ne $Script:CacheDir) { throw 'Fixture path escaped owned work directory' }
    }
    $Script:ChildCalls++
    [IO.File]::WriteAllText($RedirectStandardOutput, [string]$Script:Case.child_raw, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText($RedirectStandardError, '', (New-Object Text.UTF8Encoding($false)))
    $process = [pscustomobject]@{ Id = 888; ExitCode = [int]$Script:Case.child_exit }
    $process | Add-Member ScriptMethod WaitForExit { param([int]$Timeout) return $true }
    $process | Add-Member ScriptMethod Refresh { }
    $process | Add-Member ScriptMethod Kill { throw 'No fixture process may be killed' }
    return $process
}

$Script:CacheDir = [IO.Path]::GetFullPath($Work)
$Script:HelperServerScript = Join-Path $Script:CacheDir 'inert-fixture-server.ps1'
[IO.File]::WriteAllText($Script:HelperServerScript, '# Inert fixture, never executed')
$Script:InvokeTimeoutMs = 30000
$Script:NativeHelperPath = 'INERT-NO-EXECUTABLE'
$Script:HelperServerSupported = @('windows', 'health', 'focused', 'modal-detect', 'ocr-screen-fast', 'uia-find-fast')
$output = New-Object Collections.ArrayList
foreach ($case in (Get-Content -LiteralPath $Inputs -Raw -Encoding UTF8 | ConvertFrom-Json)) {
    $Script:Case = $case
    $Script:FixtureLock = $case.lock
    $Script:ClockMs = 0; $Script:SleepTicks = 0; $Script:LaunchCalls = 0; $Script:OwnedKills = 0
    $Script:PipeCalls = 0; $Script:ChildCalls = 0; $Script:DeleteCalls = 0; $Script:Forwarded = $null
    $Script:HotCache = @{}; $Script:HotCacheStats = @{ hits = 0; misses = 0; evictions = 0 }
    if ($case.mode -eq 'lock') {
        [void]$output.Add([ordered]@{ stale = [bool](_Is-StaleLock -Lock $case.lock) })
    } elseif ($case.mode -eq 'status') {
        [void]$output.Add((Get-HelperServerStatus))
    } elseif ($case.mode -eq 'stop') {
        [void]$output.Add((Stop-HelperServer -Force:([bool]$case.force)))
    } elseif ($case.mode -eq 'start') {
        $started = Start-HelperServer -IdleTimeoutMs 1234
        [void]$output.Add([ordered]@{ result = $started; launches = $Script:LaunchCalls; owned_kills = $Script:OwnedKills })
    } elseif ($case.mode -eq 'route') {
        $Script:FixtureLock = [pscustomobject]@{ pid = 321; pipe_name = 'cucp-helper-321'; started_at = '2026-01-02T12:00:00Z'; helper_version = '2.0.0' }
        $env:CUCP_FORCE_CHILD = [string]$case.force_env
        $env:CUCP_HOT_CACHE_DISABLE = [string]$case.hot_disable
        $Script:CacheSeconds = [int]$case.cache_seconds
        $value = Invoke-NativeHelper -ArgList @($case.argv) -TimeoutMs 1000 -ForceChild:([bool]$case.force_child)
        [void]$output.Add([ordered]@{ route = $value.Route; exit_code = $value.ExitCode;
            pipe_calls = $Script:PipeCalls; child_calls = $Script:ChildCalls; forwarded = $Script:Forwarded })
    } else { throw 'Unknown fixture mode' }
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($output) -Depth 24 -Compress))
