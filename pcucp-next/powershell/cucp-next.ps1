[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$nextRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $nextRoot
$pythonRoot = Join-Path $nextRoot "python"
$legacyWrapper = Join-Path $repoRoot "scripts\cucp.ps1"

function Find-PcuCpPython {
  foreach ($name in @("python.exe", "python", "py.exe")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
  }
  return $null
}

$python = Find-PcuCpPython
if ($python) {
  $oldPythonPath = $env:PYTHONPATH
  try {
    if ($oldPythonPath) { $env:PYTHONPATH = "$pythonRoot;$oldPythonPath" }
    else { $env:PYTHONPATH = $pythonRoot }
    & $python -m pcucp_cli @RemainingArgs
    exit $LASTEXITCODE
  } finally {
    $env:PYTHONPATH = $oldPythonPath
  }
}

if (Test-Path -LiteralPath $legacyWrapper) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $legacyWrapper @RemainingArgs
  exit $LASTEXITCODE
}

Write-Error "Neither Python nor the legacy CUCP wrapper is available."
exit 2
