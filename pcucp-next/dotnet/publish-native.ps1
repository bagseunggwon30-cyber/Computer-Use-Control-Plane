# Compatibility shim only. Build orchestration lives in Python.
[CmdletBinding()]
param(
    [ValidateSet('win-x64', 'win-arm64')][string]$Runtime = 'win-x64',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../bin/native'),
    [string]$PythonExe = 'python'
)
& $PythonExe (Join-Path $PSScriptRoot '../packaging/publish_native.py') --runtime $Runtime --output $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Native publish failed with exit code $LASTEXITCODE" }
