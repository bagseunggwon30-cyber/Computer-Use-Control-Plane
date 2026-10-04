param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)

# No loaders, facades or desktop actions are imported. Only the exact published
# dispatch/health bodies and two harmless local parameter-binding controls run.
function Hash-Text([string]$Text) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
function Limit-Text([string]$Text) { return $Text.Substring(0,[Math]::Min(2048,$Text.Length)) }
function Type-Name($Value) { if($null -eq $Value){return $null};return $Value.GetType().FullName }
function Convert-Case($Value) {
  if($null -eq $Value){return $null}
  if($Value -is [array]){$a=New-Object Collections.ArrayList;foreach($v in $Value){[void]$a.Add((Convert-Case $v))};return ,$a.ToArray()}
  if($Value -is [Management.Automation.PSCustomObject]){$r=@{};foreach($p in $Value.PSObject.Properties){$r[$p.Name]=Convert-Case $p.Value};return $r}
  return $Value
}
function Invoke-AutomaticArgsProbe {
  param([hashtable]$Args)
  $script:Entered++
  return @{received_type=(Type-Name $Args);bound_type=(Type-Name $PSBoundParameters['Args']);count=$Args.Count}
}
function Invoke-NamedParameterProbe {
  param([hashtable]$RequestData)
  $script:Entered++
  return @{received_type=(Type-Name $RequestData);bound_type=(Type-Name $PSBoundParameters['RequestData']);count=$RequestData.Count;received=$RequestData}
}

$pin=[IO.File]::ReadAllText($Manifest,[Text.Encoding]::UTF8)|ConvertFrom-Json
$entry=@($pin.files|Where-Object{$_.path -eq 'scripts/cucp-helper-server.ps1'})[0]
$sourceText=[IO.File]::ReadAllText($Source,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
if((Hash-Text $sourceText) -cne $entry.normalized_sha256){throw 'Published server source hash mismatch'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Published server source AST parse failed'}
$verified=New-Object Collections.ArrayList
foreach($name in @('_Action-Health','_Dispatch')){
  $records=@($entry.functions|Where-Object{$_.name -ceq $name})
  $nodes=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
  if($records.Count -ne 1 -or $nodes.Count -ne 1){throw "Expected exact function: $name"}
  $record=$records[0];$node=$nodes[0]
  if($node.Extent.StartOffset -ne $record.start_utf16 -or $node.Extent.EndOffset -ne $record.end_utf16 -or (Hash-Text $node.Extent.Text) -cne $record.sha256){throw "Published AST extent changed: $name"}
  [void]$verified.Add(@{name=$name;sha256=$record.sha256})
  . ([scriptblock]::Create($node.Extent.Text))
}

$PipeName='binding-probe';$Script:_StartedAt=[DateTime]::UtcNow;$Script:_RequestCount=0;$Script:_Win32Loaded=$false
$observations=New-Object Collections.ArrayList
foreach($inputCase in @(
  @{name='direct-empty';value=@{}},
  @{name='direct-values';value=@{Label='Save';Flag=$false}},
  @{name='converted-empty';value=(Convert-Case ('{}'|ConvertFrom-Json))},
  @{name='converted-values';value=(Convert-Case ('{"Label":"Save","Flag":false}'|ConvertFrom-Json))},
  @{name='converted-nested';value=(Convert-Case ('{"Nested":{"Empty":{},"Values":[{"Label":"Save"},[],null,false]}}'|ConvertFrom-Json))}
)){
  foreach($target in @('synthetic-automatic','synthetic-named','original-health','original-dispatch-health','original-dispatch-shutdown','original-dispatch-unsupported')){
    $script:Entered=0;$Script:_RequestCount=0;$value=$null;$failure=$null
    try {
      switch($target){
        'synthetic-automatic' {$value=Invoke-AutomaticArgsProbe -Args $inputCase.value}
        'synthetic-named' {$value=Invoke-NamedParameterProbe -RequestData $inputCase.value}
        'original-health' {$value=_Action-Health -Args $inputCase.value}
        'original-dispatch-health' {$value=_Dispatch -Action health -Args $inputCase.value}
        'original-dispatch-shutdown' {$value=_Dispatch -Action shutdown -Args $inputCase.value}
        'original-dispatch-unsupported' {$value=_Dispatch -Action binding-probe-unsupported -Args $inputCase.value}
      }
    } catch {
      $failure=@{
        record_type=$_.GetType().FullName
        exception_type=$_.Exception.GetType().FullName
        inner_exception_type=(Type-Name $_.Exception.InnerException)
        fully_qualified_error_id=$_.FullyQualifiedErrorId
        message=(Limit-Text $_.Exception.Message)
        category=[string]$_.CategoryInfo.Category
        target_type=(Type-Name $_.TargetObject)
        invocation=@{command=$_.InvocationInfo.MyCommand.Name;line=(Limit-Text $_.InvocationInfo.Line);position=(Limit-Text $_.InvocationInfo.PositionMessage);script_line=$_.InvocationInfo.ScriptLineNumber;offset=$_.InvocationInfo.OffsetInLine}
        script_stack_trace=(Limit-Text $_.ScriptStackTrace)
      }
    }
    [void]$observations.Add(@{input=$inputCase.name;input_type=(Type-Name $inputCase.value);input_value=$inputCase.value;target=$target;body_entered=$script:Entered;request_count=$Script:_RequestCount;result=$value;error=$failure})
  }
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{schema='cucp.helper-binding-probe/v1';powershell_version=$PSVersionTable.PSVersion.ToString();source_sha256=$entry.normalized_sha256;functions=@($verified);observations=@($observations)} -Depth 12 -Compress))
