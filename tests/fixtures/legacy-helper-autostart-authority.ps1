param([Parameter(Mandatory=$true)][string]$SourceRoot,
      [Parameter(Mandatory=$true)][string]$OwnedRoot)
$ErrorActionPreference='Stop'
# A disposable fixture layout only. The real Startup/LocalApplicationData lookup
# is replaced before the production adapter or extracted delegate is invoked.
$marker=Join-Path $OwnedRoot '.autostart-authority-fixture'
if ((Get-Content -LiteralPath $marker -Raw) -cne 'owned-temporary-autostart-authority/v1') { throw 'Missing owned fixture marker' }
$SourceRoot=[IO.Path]::GetFullPath($SourceRoot)
$OwnedRoot=[IO.Path]::GetFullPath($OwnedRoot)
$Script:AuditDir=Join-Path $OwnedRoot 'audit'
$Script:OwnedStartup=Join-Path $OwnedRoot 'startup'
$Script:OwnedMetadata=Join-Path $OwnedRoot 'state'
$scripts=Join-Path $OwnedRoot 'scripts'; $python=Join-Path $OwnedRoot 'pcucp-next/python'
foreach($dir in @($scripts,$python,$Script:AuditDir,$Script:OwnedStartup,$Script:OwnedMetadata)) {
  [void](New-Item -ItemType Directory -Path $dir)
}
$adapter=Join-Path $scripts 'cucp-staged-helper-adapter.ps1'
Copy-Item -LiteralPath (Join-Path $SourceRoot 'scripts/cucp-staged-helper-adapter.ps1') -Destination $adapter
Copy-Item -LiteralPath (Join-Path $SourceRoot 'tests/fixtures/legacy-helper-autostart-bridge-capture.py') -Destination (Join-Path $python 'legacy_helper_bridge.py')
$tokens=$null; $parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $SourceRoot 'scripts/cucp.ps1'),[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Install-HelperAutostart','Uninstall-HelperAutostart','Get-HelperAutostartStatus')) {
  $nodes=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($nodes.Count -ne 1) { throw 'Unexpected autostart function inventory' }
  . ([scriptblock]::Create($nodes[0].Extent.Text))
}
$env:CUCP_STAGED_COMPILED_HELPER='1'; $env:CUCP_STAGED_HELPER_READONLY_DESKTOP=$null
$results=@()
foreach ($initial in @($false,$true)) {
  $AllowLiveControl=$initial
  . $adapter
  function _Get-AutostartShimPath { return (Join-Path $Script:OwnedStartup 'cucp-helper-autostart.cmd') }
  function _Get-StagedAutostartMetadataDirectory { return $Script:OwnedMetadata }
  # Changing the public variable later cannot alter captured bootstrap authority.
  $AllowLiveControl=-not $initial
  $install=Install-HelperAutostart -IdleTimeoutMs 12345
  $status=Get-HelperAutostartStatus
  $uninstall=Uninstall-HelperAutostart
  foreach ($reply in @($install,$status,$uninstall)) {
    if ($reply.allow_change -ne $initial -or $reply.desktop -ne $false -or
        $reply.startup_directory -cne $Script:OwnedStartup -or
        $reply.metadata_directory -cne $Script:OwnedMetadata) { throw 'Authority or fixed fixture path changed' }
  }
  if ($install.operation -cne 'autostart-install' -or $install.arguments.idle_timeout_ms -ne 12345 -or
      $status.operation -cne 'autostart-status' -or $uninstall.operation -cne 'autostart-uninstall') { throw 'Delegate command changed' }
  $results+=@{captured=$initial; install=$install; status=$status; uninstall=$uninstall}
}
if (@(Get-ChildItem -LiteralPath $Script:OwnedStartup).Count -or @(Get-ChildItem -LiteralPath $Script:OwnedMetadata).Count) {
  throw 'Inert capture fixture unexpectedly wrote registration data'
}
@{status='ok'; results=$results} | ConvertTo-Json -Depth 12 -Compress
