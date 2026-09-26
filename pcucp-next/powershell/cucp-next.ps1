[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$nextRoot = Split-Path -Parent $PSScriptRoot
$pythonRoot = Join-Path $nextRoot "python"

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

Write-Error "Python 3.10 or later is required. No legacy fallback was executed."
exit 2
