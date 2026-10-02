param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$CasePath,
      [ValidateSet('normal','missing-support','duplicate-load','blocked-provider')][string]$Mode='normal')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
$Root=[IO.Path]::GetFullPath($Root)
if([IO.Path]::GetFileName($Root) -notlike 'cucp-production-startup-*' -or
   -not (Test-Path -LiteralPath (Join-Path $Root '.startup-fixture-owner') -PathType Leaf)){throw 'Missing disposable fixture ownership marker'}
$case=Get-Content -LiteralPath $CasePath -Raw -Encoding UTF8|ConvertFrom-Json
$main=Join-Path $Root 'scripts/cucp.ps1'
$global:CUCP_STARTUP_LOADS=@{interaction=0;diagnostics=0}
$global:CUCP_STARTUP_CALLS=0
$global:CUCP_STARTUP_CASE=$case
$global:CUCP_STARTUP_MODE=$Mode
$global:CUCP_STARTUP_RECORD=Join-Path $Root 'record.jsonl'
$tripwires=@('Invoke-NativeHelper','Invoke-Cucp','Invoke-Appshot','_Enumerate-Win32Windows','_Get-UIAffordances',
  '_Invoke-CodexVision','_Find-CodexCli','_Native-HitTestPoint','_Build-CoordProfile',
  '_PointPlan-ReadCache','_PointPlan-WriteCache','_AnchorHistory-Score','_AnchorHistory-Append','_Trajectory-Append',
  '_Invoke-LegacyCompatibility','_Invoke-LegacyExecutionHost','_Invoke-LegacyExecutionChild','_Execution-SendEscape',
  '_Ensure-Win32Loaded','_Ensure-UIALoaded','_Ensure-NativeDesktopTypes','_Native-FindWindow','_Native-FocusWindow',
  '_Native-SendShortcut','_Native-SetClipboard','_Native-ClickPoint','_Native-Screenshot')
$replaceNames=$tripwires+@('_Find-CliPath','Test-Tool','_Invoke-LegacyInteractionFamily','_Invoke-LegacyDiagnosticFamily')
function Read-StartupAst([string]$Path){
  $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e)
  if($e.Count){throw ('Startup source did not parse: '+$Path)};return $a
}
function Startup-Definition($Ast,[string]$Name){
  $f=@($Ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $Name},$true))
  if($f.Count -ne 1){throw ('Expected one startup definition: '+$Name)};return $f[0]
}
function Startup-Hash([byte[]]$Bytes){
  $hash=[Security.Cryptography.SHA256]::Create()
  try{return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
}
# Hash every original copied file against the Python parent's production-source
# snapshot, then retain the exact AST preimage hash for each function replacement.
$preimages=@{}
foreach($source in $case.sources.PSObject.Properties){
  $path=Join-Path $Root $source.Name
  if((Startup-Hash ([IO.File]::ReadAllBytes($path))) -cne $source.Value){throw 'Copied production source hash changed'}
  $ast=Read-StartupAst $path
  foreach($f in @($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true))){
    if($f.Name -cnotin $replaceNames){continue}
    $key=$path+'|'+$f.Name
    if($preimages.ContainsKey($key)){throw ('Duplicate production function: '+$f.Name)}
    $preimages[$key]=Startup-Hash ([Text.Encoding]::UTF8.GetBytes($f.Extent.Text))
  }
}
function Replace-StartupDefinition([string]$Path,[string]$Name,[string]$Replacement){
  $f=Startup-Definition (Read-StartupAst $Path) $Name;$text=[IO.File]::ReadAllText($Path)
  if(-not $preimages.ContainsKey($Path+'|'+$Name) -or
     (Startup-Hash ([Text.Encoding]::UTF8.GetBytes($f.Extent.Text))) -cne $preimages[$Path+'|'+$Name]){throw ('Startup function preimage changed: '+$Name)}
  [IO.File]::WriteAllText($Path,$text.Substring(0,$f.Extent.StartOffset)+$Replacement+$text.Substring($f.Extent.EndOffset),(New-Object Text.UTF8Encoding($true)))
}
function Write-StartupRecord {
  param([string]$Family,[string]$Operation,[string[]]$Rest,[string]$ScriptPath,[bool]$Double=$false,[bool]$RightClick=$false,
        [bool]$Live,[bool]$BriefValue,[int]$CacheValue,[string]$AuditPath,[string]$CachePath)
  if($global:CUCP_STARTUP_LOADS.interaction -ne 1 -or $global:CUCP_STARTUP_LOADS.diagnostics -ne 1){throw 'Missing or duplicate production support load'}
  $global:CUCP_STARTUP_CALLS++
  if($global:CUCP_STARTUP_CALLS -ne 1){throw 'Repeated family entry'}
  $record=@{family=$Family;operation=$Operation;rest=@($Rest);script_path=$ScriptPath;double=$Double;right_click=$RightClick;
    calls=$global:CUCP_STARTUP_CALLS;loads=$global:CUCP_STARTUP_LOADS;allow_live=$Live;brief=$BriefValue;
    cache_seconds=$CacheValue;audit_dir=$AuditPath;cache_dir=$CachePath}
  [IO.File]::AppendAllText($global:CUCP_STARTUP_RECORD,(ConvertTo-Json -InputObject $record -Depth 8 -Compress)+[Environment]::NewLine,(New-Object Text.UTF8Encoding($false)))
  return [int]$global:CUCP_STARTUP_CASE.exit_code
}
# Refuse retained bodies before executing anything. Actual public delegate text
# remains untouched, including its own $PSCommandPath argument expression.
$mainAst=Read-StartupAst $main
$entry=Startup-Definition $mainAst ([string]$case.wrapper)
$statements=@($entry.Body.EndBlock.Statements)
if($statements.Count -ne 1 -or $statements[0] -isnot [Management.Automation.Language.ReturnStatementAst]){throw 'Public entry is not a promoted delegate'}
$pipeline=$statements[0].Pipeline
if($pipeline -isnot [Management.Automation.Language.PipelineAst] -or $pipeline.PipelineElements.Count -ne 1 -or
   $pipeline.PipelineElements[0] -isnot [Management.Automation.Language.CommandAst] -or
   $pipeline.PipelineElements[0].GetCommandName() -cne [string]$case.entry){throw 'Public entry does not call its expected family'}
# These are provider-discovery seams only. There is no backend or executable in
# the copied tree, and the Python parent supplies an empty owned PATH directory.
Replace-StartupDefinition $main '_Find-CliPath' 'function _Find-CliPath {return $null}'
Replace-StartupDefinition $main 'Test-Tool' 'function Test-Tool {param([string]$Name) return $true}'
$probe=Read-StartupAst (Join-Path $PSScriptRoot 'legacy-family-production-probe.ps1')
$modules=@(
  @{family='interaction';file='cucp-legacy-interaction-adapter.ps1';entry='_Invoke-LegacyInteractionFamily'},
  @{family='diagnostics';file='cucp-legacy-diagnostic-adapter.ps1';entry='_Invoke-LegacyDiagnosticFamily'}
)
foreach($module in $modules){
  $path=Join-Path $Root ('scripts/'+$module.file);$ast=Read-StartupAst $path
  if(@($ast.EndBlock.Statements|Where-Object {$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]}).Count){throw 'Support module has executable top-level code'}
  Replace-StartupDefinition $path $module.entry (Startup-Definition $probe $module.entry).Extent.Text
  $prefix='$global:CUCP_STARTUP_LOADS.'+$module.family+'++; if($global:CUCP_STARTUP_LOADS.'+$module.family+' -ne 1){throw "Duplicate production support load"}'+[Environment]::NewLine
  [IO.File]::WriteAllText($path,$prefix+[IO.File]::ReadAllText($path),(New-Object Text.UTF8Encoding($true)))
}
$selected=$modules|Where-Object {$_.family -ceq $case.family}
if($Mode -ceq 'missing-support'){Remove-Item -LiteralPath (Join-Path $Root ('scripts/'+$selected.file))}
if($Mode -ceq 'duplicate-load'){
  $text=[IO.File]::ReadAllText($main)
  $loads=@((Read-StartupAst $main).FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and
    $n.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Dot -and $n.Extent.Text.Contains($selected.file)},$true))
  if($loads.Count -ne 1){throw 'Expected one production module loader for negative control'}
  $load=$loads[0].Extent
  [IO.File]::WriteAllText($main,$text.Substring(0,$load.EndOffset)+[Environment]::NewLine+$load.Text+$text.Substring($load.EndOffset),(New-Object Text.UTF8Encoding($true)))
}
# Hard tripwires replace acquisition leaves only in this disposable copy.
# No debugger is involved; Environment.Exit cannot be swallowed by legacy catches.
# Other gates qualify the unchanged provider/transport bodies in the real tree.
foreach($name in $tripwires){
  Replace-StartupDefinition $main $name ('function '+$name+' { [Console]::Error.WriteLine("startup_provider_guard:'+ $name+'"); [Environment]::Exit(97) }')
}
[string[]]$argv=@('macro',[string]$case.macro)+[string[]]@($case.rest)
& $main -AllowLiveControl:$false -Quiet -Brief:$false -CacheSeconds 0 -CucpArgs $argv
exit [int]$LASTEXITCODE
