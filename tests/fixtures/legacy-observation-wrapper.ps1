param([Parameter(Mandatory=$true)][string]$WrapperPath,[Parameter(Mandatory=$true)][string]$ArgumentsPath)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Actual wrapper qualification requires Windows PowerShell 5.1.'}
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
$OutputEncoding=$utf8
$argv=@([IO.File]::ReadAllText($ArgumentsPath) | ConvertFrom-Json)
& $WrapperPath -Quiet -CacheSeconds 0 -CucpArgs $argv
exit $LASTEXITCODE
