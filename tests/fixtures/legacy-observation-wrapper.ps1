param([Parameter(Mandatory=$true)][string]$WrapperPath,[Parameter(Mandatory=$true)][string]$ArgumentsPath)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Actual wrapper qualification requires Windows PowerShell 5.1.'}
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
$OutputEncoding=$utf8
$decoded=[IO.File]::ReadAllText($ArgumentsPath) | ConvertFrom-Json
$arguments=New-Object 'System.Collections.Generic.List[string]'
foreach($item in $decoded){
 if($item -isnot [string]){throw 'Wrapper fixture argv must contain only strings.'}
 $arguments.Add($item)
}
if($arguments.Count -lt 2 -or $arguments[0] -cne 'macro'){throw 'Wrapper fixture requires an explicit macro argv array.'}
& $WrapperPath -Quiet -CacheSeconds 0 -CucpArgs ([string[]]$arguments.ToArray())
exit $LASTEXITCODE
