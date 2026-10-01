# Source installer compatibility entrypoint. Python 3.10+ is required.
# The default remains the legacy PowerShell backend; core/portable are explicit.
[CmdletBinding()]
param(
    [string]$BinDir,
    [switch]$NoPathShim,
    [switch]$Quiet,
    [ValidateSet('legacy','core','portable')][string]$Backend = 'legacy',
    [string]$PortableRoot,
    [string]$PythonExe
)
$ErrorActionPreference = 'Stop'
$python = $null
$names = if ($PythonExe) { @($PythonExe) } else { @('python.exe','python','py.exe') }
foreach ($name in $names) {
    $python = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
    if ($python) { break }
}
if (-not $python) { [Console]::Error.WriteLine('Python 3.10+ is required for source installation. Portable bundles can run without this installer.'); exit 2 }
$prefix = @()
if ([IO.Path]::GetFileName($python.Source) -ieq 'py.exe') { $prefix += '-3' }
$prefix += @('-X','utf8')
& $python.Source @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 2)'
if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine('Python 3.10+ is required.'); exit 2 }
$arguments = @((Join-Path $PSScriptRoot 'pcucp-next/packaging/install_runtime.py'),'--root',$PSScriptRoot,'--backend',$Backend,'--apply')
if ($BinDir) { $arguments += @('--bin-dir',$BinDir) }
if ($NoPathShim) { $arguments += '--no-path-shim' }
if ($Quiet) { $arguments += '--quiet' }
if ($PortableRoot) { $arguments += @('--portable-root',$PortableRoot) }
& $python.Source @prefix @arguments
exit $LASTEXITCODE
