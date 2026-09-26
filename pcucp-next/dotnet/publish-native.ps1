[CmdletBinding()]
param(
    [ValidateSet('win-x64', 'win-arm64')]
    [string]$Runtime = 'win-x64',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../bin/native')
)

$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'PcuCp.NativeHost/PcuCp.NativeHost.csproj'
# Published executable is used by Python; no SDK/build startup on each action.
& dotnet publish $project -c Release -r $Runtime --self-contained true -o $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Native publish failed with exit code $LASTEXITCODE" }
Write-Output "Published PcuCp.NativeHost.exe to $OutputDirectory"
