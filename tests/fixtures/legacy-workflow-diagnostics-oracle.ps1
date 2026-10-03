param([string]$SourcePath, [string]$InputPath, [string]$SourceHash, [string]$BaselineTree)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected Windows PowerShell 5.1' }
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
# Hash the exact on-disk bytes without relying on module autoloading. The
# Python caller validates these hashes against hashlib.sha256 on the same files.
function _Get-WorkflowDiagnosticFileSha256 {
  param([string]$Path)
  [byte[]]$fileBytes=[IO.File]::ReadAllBytes($Path)
  $fileSha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($fileSha.ComputeHash($fileBytes))).Replace('-','').ToLowerInvariant() }
  finally { $fileSha.Dispose() }
}
if ((_Get-WorkflowDiagnosticFileSha256 -Path $SourcePath) -ne $SourceHash) { throw 'Pinned source hash mismatch' }
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source did not parse' }
$helperHashes=@{}
foreach ($name in @('_Read-OptValue','_Safety-Truncate','_Classify-SafetyFromText','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan')) {
  $function=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($function.Count -ne 1) { throw "Expected one exact baseline function: $name" }
  $bytes=[Text.Encoding]::UTF8.GetBytes($function[0].Extent.Text)
  $sha=[Security.Cryptography.SHA256]::Create()
  try { $helperHashes[$name]=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
  . ([scriptblock]::Create($function[0].Extent.Text))
}
# PS5 emits a JSON root array as one pipeline object. An outer @(...)
# therefore nests that array instead of materializing its individual cases.
# Assign the JSON result directly, then validate exactly one array level.
$cases=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($InputPath, [Text.Encoding]::UTF8))
if ($cases -isnot [Array]) { throw 'Diagnostic input root must be an array.' }
if ($cases.Count -lt 1 -or $cases.Count -gt 128) { throw 'Case count exceeds the bounded capture' }
$seenIds=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($case in $cases) {
  if ($case -isnot [Management.Automation.PSCustomObject]) { throw 'Diagnostic input case must be an object.' }
  $names=@($case.PSObject.Properties.Name)
  if ($names.Count -ne 2 -or $names -cnotcontains 'id' -or $names -cnotcontains 'step') {
    throw 'Diagnostic input case fields must be exactly id and step.'
  }
  if ($case.id -isnot [string] -or [string]::IsNullOrEmpty($case.id)) { throw 'Diagnostic input id must be a nonempty string.' }
  if ($case.step -isnot [string]) { throw 'Diagnostic input step must be a string.' }
  if ($case.step.Length -gt 65536) { throw 'Case text exceeds the bounded capture' }
  if (-not $seenIds.Add($case.id)) { throw 'Duplicate diagnostic input id.' }
}
$results=New-Object Collections.ArrayList
foreach ($case in $cases) {
  # Fields have already been checked as scalar strings; never join array values.
  $step=$case.step
  $parseErrors=$null
  $parsedTokens=[Management.Automation.PSParser]::Tokenize($step,[ref]$parseErrors)
  $diagnostics=New-Object Collections.ArrayList
  foreach ($diagnostic in @($parseErrors)) {
    if ($null -ne $diagnostic) {
      [void]$diagnostics.Add(@{message=$diagnostic.Message; token=@{type=[string]$diagnostic.Token.Type; content=$diagnostic.Token.Content;
        start=$diagnostic.Token.Start; length=$diagnostic.Token.Length; start_line=$diagnostic.Token.StartLine; start_column=$diagnostic.Token.StartColumn;
        end_line=$diagnostic.Token.EndLine; end_column=$diagnostic.Token.EndColumn}})
    }
  }
  $firstUnsupported=$null
  foreach ($token in @($parsedTokens)) {
    if ([string]$token.Type -notin @('Command','CommandArgument','String','Number','NewLine','LineContinuation')) {
      $firstUnsupported=[string]$token.Type; break
    }
  }
  $parsed=_Parse-WorkflowStepTokens -Step $step
  $plan=_Build-WorkflowPlan -Rest @('--step',$step)
  [void]$results.Add(@{id=$case.id; step=$step; parsed=$parsed; plan=$plan;
    parse_errors=@($diagnostics); first_unsupported_token_type=$firstUnsupported})
}
$provenance=@{evidence='observed-windows-powershell-5.1-raw-diagnostics'; baseline_tree=$BaselineTree;
  source_sha256=$SourceHash; helper_sha256=$helperHashes; powershell_version=$PSVersionTable.PSVersion.ToString();
  powershell_edition=[string]$PSVersionTable.PSEdition; culture=[Globalization.CultureInfo]::CurrentCulture.Name;
  ui_culture=[Globalization.CultureInfo]::CurrentUICulture.Name; ps_culture=[string]$PSCulture; ps_ui_culture=[string]$PSUICulture;
  clr_version=[string]$PSVersionTable.CLRVersion; os_version=[Environment]::OSVersion.VersionString;
  captured_at_utc=[DateTime]::UtcNow.ToString('o'); oracle='PSParser.Tokenize plus unchanged pinned private workflow functions';
  input_sha256=(_Get-WorkflowDiagnosticFileSha256 -Path $InputPath)}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{schema='cucp.workflow-raw-diagnostics/v1';provenance=$provenance;cases=@($results)} -Depth 40 -Compress))
