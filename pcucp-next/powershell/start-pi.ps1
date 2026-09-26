[CmdletBinding()]
param(
    [switch]$Elevated,
    [string]$PythonExe = 'python',
    [string]$PiExecutable = 'pi'
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This launcher requires an interactive Windows desktop.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
try {
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} finally { $identity.Dispose() }

# Elevation is explicit, uses the normal UAC consent, and includes the entire Pi session.
if ($Elevated -and -not $isAdmin) {
    $launcherPath = $PSCommandPath.Replace("'", "''")
    $pythonLiteral = $PythonExe.Replace("'", "''")
    $piLiteral = $PiExecutable.Replace("'", "''")
    $workingLiteral = (Get-Location).Path.Replace("'", "''")
    $command = "Set-Location -LiteralPath '$workingLiteral'; & '$launcherPath' -PythonExe '$pythonLiteral' -PiExecutable '$piLiteral'; exit `$LASTEXITCODE"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $shell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $process = Start-Process -FilePath $shell -Verb RunAs -ArgumentList @('-NoProfile', '-EncodedCommand', $encoded) -Wait -PassThru
    exit $process.ExitCode
}
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$native = Join-Path $repoRoot 'pcucp-next/bin/native/PcuCp.NativeHost.exe'
if (-not (Test-Path -LiteralPath $native -PathType Leaf)) {
    throw "Build the native host first: & '$repoRoot\pcucp-next\dotnet\publish-native.ps1'"
}
$python = Get-Command $PythonExe -CommandType Application -ErrorAction Stop
$pi = Get-Command $PiExecutable -CommandType Application,ExternalScript -ErrorAction Stop
$env:CUCP_ROOT = $repoRoot
$env:CUCP_PYTHON = $python.Source
$env:CUCP_NATIVE_HOST = $native
if ($isAdmin) { Write-Host 'Pi and all loaded tools/extensions run as administrator. CUCP live control still starts off.' }
& $pi.Source --extension (Join-Path $repoRoot 'integrations/pi/src/index.ts')
exit $LASTEXITCODE
