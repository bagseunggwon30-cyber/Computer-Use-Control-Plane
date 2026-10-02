param([string]$SourcePath, [string]$InputPath, [string]$SourceHash, [string]$BaselineTree)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected Windows PowerShell 5.1' }
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if ((Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw 'Pinned source hash mismatch' }
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
$cases=@(Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)
if ($cases.Count -lt 1 -or $cases.Count -gt 128) { throw 'Case count exceeds the bounded capture' }
$results=New-Object Collections.ArrayList
foreach ($case in $cases) {
  $step=[string]$case.step
  if ($step.Length -gt 65536) { throw 'Case text exceeds the bounded capture' }
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
  [void]$results.Add(@{id=[string]$case.id; step=$step; parsed=$parsed; plan=$plan;
    parse_errors=@($diagnostics); first_unsupported_token_type=$firstUnsupported})
}
$provenance=@{evidence='observed-windows-powershell-5.1-raw-diagnostics'; baseline_tree=$BaselineTree;
  source_sha256=$SourceHash; helper_sha256=$helperHashes; powershell_version=$PSVersionTable.PSVersion.ToString();
  powershell_edition=[string]$PSVersionTable.PSEdition; culture=[Globalization.CultureInfo]::CurrentCulture.Name;
  ui_culture=[Globalization.CultureInfo]::CurrentUICulture.Name; ps_culture=[string]$PSCulture; ps_ui_culture=[string]$PSUICulture;
  clr_version=[string]$PSVersionTable.CLRVersion; os_version=[Environment]::OSVersion.VersionString;
  captured_at_utc=[DateTime]::UtcNow.ToString('o'); oracle='PSParser.Tokenize plus unchanged pinned private workflow functions';
  input_sha256=(Get-FileHash -LiteralPath $InputPath -Algorithm SHA256).Hash.ToLowerInvariant()}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{schema='cucp.workflow-raw-diagnostics/v1';provenance=$provenance;cases=@($results)} -Depth 40 -Compress))
