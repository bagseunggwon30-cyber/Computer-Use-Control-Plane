param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Manifest,[Parameter(Mandatory=$true)][string]$CasePath,[string]$Stubs,[switch]$TestWrongBinding,[ValidateSet('none','duplicate','changed')][string]$TestTypeExtentFault='none',[switch]$CorrectedIntent,[ValidateSet('none','duplicate','changed','wrongname')][string]$TestArgsExtentFault='none',[switch]$FunctionalIntent,[ValidateSet('none','duplicate','changed','wrongname')][string]$TestFunctionalExtentFault='none',[ValidateSet('async-type','score-sort')][string]$TestFunctionalExtentTarget='async-type')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($FunctionalIntent -and -not $CorrectedIntent){throw 'Functional-intent mode requires explicit corrected-intent mode'}
if($TestFunctionalExtentFault -ne 'none' -and -not $FunctionalIntent){throw 'Functional extent faults require explicit functional-intent mode'}
function Hash-Text([string]$Text) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}
if(-not $Stubs){throw 'An inert acquisition facade is required'}
$pin=[IO.File]::ReadAllText($Manifest,[Text.Encoding]::UTF8)|ConvertFrom-Json
$entry=@($pin.files|Where-Object{$_.path -eq 'scripts/cucp-helper-server.ps1'})[0]
$sourceText=[IO.File]::ReadAllText($Source,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
if((Hash-Text $sourceText) -cne $entry.normalized_sha256){throw 'Published server source hash mismatch'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Published server source AST parse failed'}
$verified=New-Object Collections.ArrayList
foreach($record in $entry.functions) {
  $matches=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $record.name},$true))
  if($matches.Count -ne 1){throw "Expected exact function: $($record.name)"}
  $node=$matches[0]
  if($node.Extent.StartOffset -ne $record.start_utf16 -or $node.Extent.EndOffset -ne $record.end_utf16 -or (Hash-Text $node.Extent.Text) -cne $record.sha256){throw "Published AST extent changed: $($record.name)"}
  [void]$verified.Add(@{record=$record;node=$node})
}

# Source and original function hashes above remain unchanged. This explicit
# acquisition seam alters ONLY type-name AST extents in the listed functions:
# TypeExpressionAst / TypeConstraintAst and a bare first New-Object argument.
# Every other UTF-16 code unit is copied from the verified original. In
# particular, action branches, arguments, strings and query order are retained.
# Native loader definitions and their assembly-qualified WinRT literals are
# outside this seam. They are verified above but never imported or executed.
$loaderNames=@('_Ensure-Win32Loaded','_Server-Ensure-OCR','_Server-Ensure-UIA')
$importNames=@('_Log','_Action-Windows','_Action-Health','_Action-Focused','_Action-ModalDetect','_Action-OcrScreenFast','_Action-UiaFindFast','_Dispatch')
$fixturePrefix='CucpFixture.'
$typeCounts=[ordered]@{
  'HelperWin32'=18
  'HelperWin32+RECT'=2
  'System.Windows.Automation.AutomationElement'=4
  'System.Windows.Automation.OrCondition'=1
  'System.Windows.Automation.PropertyCondition'=2
  'System.Windows.Automation.ControlType'=2
  'System.Windows.Automation.TreeScope'=4
  'System.Windows.Automation.WindowPattern'=1
  'System.Windows.Forms.Screen'=1
  'System.Windows.Forms.SystemInformation'=1
  'Windows.Media.Ocr.OcrEngine'=1
  'System.Drawing.Bitmap'=1
  'System.Drawing.Graphics'=1
  'System.Drawing.Size'=1
  'System.Drawing.Imaging.ImageFormat'=1
  'WindowsRuntimeSystemExtensions'=1
  'Windows.Storage.StorageFile'=2
  'Windows.Storage.FileAccessMode'=1
  'Windows.Storage.Streams.IRandomAccessStream'=1
  'Windows.Graphics.Imaging.BitmapDecoder'=2
  'Windows.Graphics.Imaging.SoftwareBitmap'=1
  'Windows.Media.Ocr.OcrResult'=1
  'System.Windows.Automation.Condition'=2
}
if($TestArgsExtentFault -ne 'none' -and -not $CorrectedIntent){throw 'Args extent faults require explicit corrected-intent mode'}
# This separately labelled, opt-in seam fixes only the published automatic
# $Args collision. Absolute UTF-16 offsets describe the ORIGINAL pinned AST;
# they are not search/replace patterns. The default retains the original defect.
$argsPlan=[ordered]@{
  '_Action-Windows'=@{parameter=@(3847);variable=@(3968,3979,3997)}
  '_Action-Health'=@{parameter=@(6046)}
  '_Action-Focused'=@{parameter=@(6402)}
  '_Action-ModalDetect'=@{parameter=@(7336)}
  '_Action-OcrScreenFast'=@{parameter=@(13109);variable=@(13704,13720,13753,13769,13802,13818,13853,13869)}
  '_Action-UiaFindFast'=@{parameter=@(16595);variable=@(16812,16830,16876,16894)}
  '_Dispatch'=@{parameter=@(20016);variable=@(20124,20185,20247,20313,20381,20447);'command-parameter'=@(20118,20179,20241,20307,20375,20441)}
}
# This third, separately labelled tier is an intentional functional correction,
# not original parity. Its closed census permits exactly two uppercase $T
# variable sites and two complete score-sort command extents. The lowercase $t
# task references, acquisition, action branches and every other byte are copied.
$functionalPlan=@(
  @{function='_Action-ModalDetect';owner_function='_Action-ModalDetect';kind='score-sort-command';ast_kind='CommandAst';start_utf16=10048;end_utf16=10087;original='Sort-Object -Property score -Descending';replacement='_Oracle-StableScore'},
  @{function='_Action-OcrScreenFast';owner_function='_AsyncWait';kind='parameter';ast_kind='VariableExpressionAst';start_utf16=14987;end_utf16=14989;original='$T';replacement='$ResultType'},
  @{function='_Action-OcrScreenFast';owner_function='_AsyncWait';kind='variable';ast_kind='VariableExpressionAst';start_utf16=15028;end_utf16=15030;original='$T';replacement='$ResultType'},
  @{function='_Action-UiaFindFast';owner_function='_Action-UiaFindFast';kind='score-sort-command';ast_kind='CommandAst';start_utf16=19022;end_utf16=19061;original='Sort-Object -Property score -Descending';replacement='_Oracle-StableScore'}
)
$functionalSites=New-Object Collections.ArrayList;$functionalFunctions=New-Object Collections.ArrayList;$functionalFaultInjected=$false
$argsSites=New-Object Collections.ArrayList;$correctedFunctions=New-Object Collections.ArrayList;$argsFaultInjected=$false
$seen=@{};$functions=New-Object Collections.ArrayList;$sites=New-Object Collections.ArrayList;$faultInjected=$false
foreach($item in $verified){
  $record=$item.record;$node=$item.node
  if($record.parent_function -or $loaderNames -ccontains $record.name){continue}
  if($importNames -cnotcontains $record.name){throw "Unplanned oracle function: $($record.name)"}
  $edits=New-Object Collections.ArrayList
  foreach($part in @($node.FindAll({param($n) $n -is [Management.Automation.Language.TypeExpressionAst] -or $n -is [Management.Automation.Language.TypeConstraintAst] -or $n -is [Management.Automation.Language.StringConstantExpressionAst]},$true))){
    $extent=$null;$name=$null;$kind=$null
    if($part -is [Management.Automation.Language.TypeExpressionAst] -or $part -is [Management.Automation.Language.TypeConstraintAst]){
      $extent=$part.TypeName.Extent;$name=$part.TypeName.FullName;$kind='type'
    }elseif($part.Parent -is [Management.Automation.Language.CommandAst] -and $part.Parent.GetCommandName() -ceq 'New-Object' -and $part.Parent.CommandElements.Count -gt 1 -and $part.Parent.CommandElements[1] -eq $part){
      if($part.StringConstantType -ne [Management.Automation.Language.StringConstantType]::BareWord){throw 'Unplanned quoted New-Object type'}
      $extent=$part.Extent;$name=$part.Value;$kind='new-object'
    }
    if(-not $name){continue}
    if(-not $typeCounts.Contains($name)){
      if($name -cmatch '^(HelperWin32|Windows\.|WindowsRuntime|System\.Windows\.|System\.Drawing\.|CucpFixture\.)'){throw "Unplanned acquisition type: $name"}
      continue
    }
    if($extent.Text -cne $name){throw "Nonliteral oracle type extent: $name"}
    $start=$extent.StartOffset-$node.Extent.StartOffset;$end=$extent.EndOffset-$node.Extent.StartOffset
    if($start -lt 0 -or $end -gt $node.Extent.Text.Length -or $end -le $start){throw 'Oracle type extent is out of bounds'}
    [void]$edits.Add(@{start=$start;end=$end;name=$name})
    [void]$sites.Add(@{function=$record.name;kind=$kind;start_utf16=$extent.StartOffset;end_utf16=$extent.EndOffset;original=$name;replacement=$fixturePrefix+$name})
    $seen[$name]=1+[int]$seen[$name]
  }
  # Negative qualification changes only the in-memory edit plan. Neither fault
  # can reach compilation/import: the original overlap/text guard must refuse.
  if($TestTypeExtentFault -ne 'none' -and -not $faultInjected -and $edits.Count){
    $first=$edits[0]
    if($TestTypeExtentFault -eq 'duplicate'){[void]$edits.Add(@{start=$first.start;end=$first.end;name=$first.name})}
    else{$first.name='FixtureChangedType'}
    $faultInjected=$true
  }
  $body=$node.Extent.Text;$previous=$body.Length;$applied=0
  # Windows PowerShell 5.1 does not sort hashtable keys by -Property start.
  # A calculated numeric dictionary lookup works there as well as on PS6+.
  foreach($edit in @($edits|Sort-Object -Property {[int]$_['start']} -Descending)){
    $overlap=$edit.end -gt $previous
    $actual=$body.Substring($edit.start,$edit.end-$edit.start)
    if($overlap -or $actual -cne $edit.name){
      # Bounded, non-executable per-site evidence precedes the refusal. No body
      # or request data is emitted; the prefix is at most 128 UTF-16 code units.
      $diagnostic=@{schema='cucp.oracle-type-extent-refusal/v1';function=$record.name;reason=$(if($overlap){'overlap_or_order'}else{'text_mismatch'});start_utf16=$node.Extent.StartOffset+$edit.start;end_utf16=$node.Extent.StartOffset+$edit.end;previous_start_utf16=$node.Extent.StartOffset+$previous;expected_type=$edit.name;actual_prefix=$actual.Substring(0,[Math]::Min(128,$actual.Length));applied=$applied;planned=$edits.Count}
      [Console]::Error.WriteLine((ConvertTo-Json -InputObject $diagnostic -Depth 4 -Compress))
      throw 'Overlapping or changed oracle type extent'
    }
    $body=$body.Substring(0,$edit.start)+$fixturePrefix+$edit.name+$body.Substring($edit.end)
    $previous=$edit.start;$applied++
  }
  # A second AST parse proves the mechanically produced body is still a single
  # definition with the same name; only this pinned function becomes executable.
  $rewriteTokens=$null;$rewriteErrors=$null
  $rewriteAst=[Management.Automation.Language.Parser]::ParseInput($body,[ref]$rewriteTokens,[ref]$rewriteErrors)
  if($rewriteErrors.Count -or $rewriteAst.EndBlock.Statements.Count -ne 1 -or $rewriteAst.EndBlock.Statements[0] -isnot [Management.Automation.Language.FunctionDefinitionAst] -or $rewriteAst.EndBlock.Statements[0].Name -cne $record.name){throw 'Invalid substituted oracle function'}
  $typeOnlyHash=Hash-Text $body
  if($CorrectedIntent){
    $renames=New-Object Collections.ArrayList;$observed=@{}
    foreach($part in @($node.FindAll({param($n) $n -is [Management.Automation.Language.VariableExpressionAst] -or $n -is [Management.Automation.Language.CommandParameterAst]},$true))){
      $kind=$null;$original=$null;$replacement=$null
      if($part -is [Management.Automation.Language.VariableExpressionAst] -and $part.VariablePath.UserPath -ieq 'Args'){
        if($part.VariablePath.UserPath -cne 'Args' -or $part.Splatted){throw 'Unplanned Args variable spelling'}
        $kind='variable';if($part.Parent -is [Management.Automation.Language.ParameterAst] -and $part.Parent.Name -eq $part){$kind='parameter'}
        $original='$Args';$replacement='$RequestData'
      }elseif($part -is [Management.Automation.Language.CommandParameterAst] -and $part.ParameterName -ieq 'Args'){
        if($part.ParameterName -cne 'Args' -or $part.Argument -or $record.name -cne '_Dispatch' -or $argsPlan.Keys -cnotcontains $part.Parent.GetCommandName() -or $part.Parent.GetCommandName() -ceq '_Dispatch'){throw 'Unplanned Args command parameter'}
        $kind='command-parameter';$original='-Args';$replacement='-RequestData'
      }
      if(-not $kind){continue}
      $owner=$part.Parent
      while($owner -and $owner -isnot [Management.Automation.Language.FunctionDefinitionAst]){$owner=$owner.Parent}
      $extent=$part.Extent
      if($owner -ne $node -or -not $argsPlan.Contains($record.name) -or -not $argsPlan[$record.name].ContainsKey($kind) -or $argsPlan[$record.name][$kind] -cnotcontains $extent.StartOffset -or $extent.EndOffset -ne ($extent.StartOffset+5) -or $extent.Text -cne $original){throw 'Unplanned Args AST extent'}
      $key=$kind+':'+$extent.StartOffset
      if($observed.ContainsKey($key)){throw 'Duplicate Args AST extent'}
      $observed[$key]=$true
      [void]$renames.Add(@{start=$extent.StartOffset-$node.Extent.StartOffset;end=$extent.EndOffset-$node.Extent.StartOffset;original=$original;replacement=$replacement;kind=$kind})
      [void]$argsSites.Add(@{function=$record.name;kind=$kind;start_utf16=$extent.StartOffset;end_utf16=$extent.EndOffset;original=$original;replacement=$replacement})
    }
    if($argsPlan.Contains($record.name)){
      foreach($kind in $argsPlan[$record.name].Keys){foreach($start in $argsPlan[$record.name][$kind]){if(-not $observed.ContainsKey($kind+':'+$start)){throw 'Missing planned Args AST extent'}}}
    }elseif($renames.Count){throw 'Args correction escaped closed functions'}
    if($TestArgsExtentFault -ne 'none' -and -not $argsFaultInjected -and $renames.Count){
      $first=$renames[0]
      if($TestArgsExtentFault -eq 'duplicate'){[void]$renames.Add(@{start=$first.start;end=$first.end;original=$first.original;replacement=$first.replacement;kind=$first.kind})}
      elseif($TestArgsExtentFault -eq 'changed'){$first.original='$Else'}
      else{$first.replacement='$Unplanned'}
      $argsFaultInjected=$true
    }
    # Rebuild from original bytes using the union of verified disjoint edits.
    # The type-only body/hash above remains independent evidence in both modes.
    $combined=New-Object Collections.ArrayList
    foreach($edit in $edits){[void]$combined.Add(@{start=$edit.start;end=$edit.end;original=$edit.name;replacement=$fixturePrefix+$edit.name;kind='type'})}
    foreach($edit in $renames){[void]$combined.Add($edit)}
    $body=$node.Extent.Text;$previous=$body.Length;$applied=0
    foreach($edit in @($combined|Sort-Object -Property {[int]$_['start']} -Descending)){
      if($edit.start -lt 0 -or $edit.end -gt $node.Extent.Text.Length -or $edit.end -le $edit.start){throw 'Corrected-intent extent is out of bounds'}
      $actual=$body.Substring($edit.start,$edit.end-$edit.start)
      $reason=$null
      if($edit.end -gt $previous){$reason='overlap_or_order'}
      elseif($actual -cne $edit.original){$reason='text_mismatch'}
      elseif($edit.kind -ne 'type' -and (($edit.original -cne '$Args' -or $edit.replacement -cne '$RequestData') -and ($edit.original -cne '-Args' -or $edit.replacement -cne '-RequestData'))){$reason='wrong_replacement_name'}
      if($reason){
        $diagnostic=@{schema='cucp.oracle-args-extent-refusal/v1';function=$record.name;reason=$reason;start_utf16=$node.Extent.StartOffset+$edit.start;end_utf16=$node.Extent.StartOffset+$edit.end;applied=$applied;planned=$combined.Count;actual_prefix=$actual.Substring(0,[Math]::Min(128,$actual.Length))}
        [Console]::Error.WriteLine((ConvertTo-Json -InputObject $diagnostic -Depth 4 -Compress))
        throw 'Unsafe corrected-intent Args extent'
      }
      $body=$body.Substring(0,$edit.start)+$edit.replacement+$body.Substring($edit.end)
      $previous=$edit.start;$applied++
    }
    $correctedTokens=$null;$correctedErrors=$null
    $correctedAst=[Management.Automation.Language.Parser]::ParseInput($body,[ref]$correctedTokens,[ref]$correctedErrors)
    if($correctedErrors.Count -or $correctedAst.EndBlock.Statements.Count -ne 1 -or $correctedAst.EndBlock.Statements[0] -isnot [Management.Automation.Language.FunctionDefinitionAst] -or $correctedAst.EndBlock.Statements[0].Name -cne $record.name){throw 'Invalid corrected-intent oracle function'}
    [void]$correctedFunctions.Add(@{name=$record.name;original_sha256=$record.sha256;type_only_sha256=$typeOnlyHash;corrected_sha256=(Hash-Text $body)})
  }
  if($FunctionalIntent){
    $argsOnlyHash=Hash-Text $body
    $functionalEdits=New-Object Collections.ArrayList;$functionalObserved=@{}
    foreach($part in @($node.FindAll({param($n) $n -is [Management.Automation.Language.VariableExpressionAst] -or $n -is [Management.Automation.Language.CommandAst]},$true))){
      $kind=$null
      if($part -is [Management.Automation.Language.VariableExpressionAst] -and $part.VariablePath.UserPath -ceq 'T'){
        if($part.Splatted){throw 'Unplanned functional type variable spelling'}
        $kind='variable'
        if($part.Parent -is [Management.Automation.Language.ParameterAst] -and $part.Parent.Name -eq $part){$kind='parameter'}
        elseif($part.Parent -isnot [Management.Automation.Language.InvokeMemberExpressionAst] -or $part.Parent.Member.Value -cne 'MakeGenericMethod' -or $part.Parent.Arguments.Count -ne 1 -or $part.Parent.Arguments[0] -ne $part -or $part.Parent.Expression.VariablePath.UserPath -cne 'asTask'){throw 'Unplanned functional type variable use'}
      }elseif($part -is [Management.Automation.Language.CommandAst] -and $part.GetCommandName() -ieq 'Sort-Object'){
        $kind='score-sort-command'
      }
      if(-not $kind){continue}
      $extent=$part.Extent;$owner=$part.Parent
      while($owner -and $owner -isnot [Management.Automation.Language.FunctionDefinitionAst]){$owner=$owner.Parent}
      $planned=@($functionalPlan|Where-Object{$_.function -ceq $record.name -and $_.start_utf16 -eq $extent.StartOffset})
      if($planned.Count -ne 1){throw 'Unplanned functional AST extent'}
      $plan=$planned[0]
      if(-not $owner -or $owner.Name -cne $plan.owner_function -or $kind -cne $plan.kind -or $part.GetType().Name -cne $plan.ast_kind -or $extent.EndOffset -ne $plan.end_utf16 -or $extent.Text -cne $plan.original){throw 'Unplanned functional AST extent'}
      if($kind -eq 'score-sort-command'){
        if($owner -ne $node -or $part.GetCommandName() -cne 'Sort-Object' -or $part.CommandElements.Count -ne 4){throw 'Unplanned functional score sort owner'}
      }else{
        $nested=@($verified|Where-Object{$_.record.name -ceq '_AsyncWait' -and $_.record.parent_function -ceq $record.name})
        $outer=$owner.Parent
        while($outer -and $outer -isnot [Management.Automation.Language.FunctionDefinitionAst]){$outer=$outer.Parent}
        if($nested.Count -ne 1 -or $owner -ne $nested[0].node -or $outer -ne $node){throw 'Unplanned functional type variable owner'}
      }
      $key=$kind+':'+$extent.StartOffset
      if($functionalObserved.ContainsKey($key)){throw 'Duplicate functional AST extent'}
      $functionalObserved[$key]=$true
      [void]$functionalEdits.Add(@{start=$extent.StartOffset-$node.Extent.StartOffset;end=$extent.EndOffset-$node.Extent.StartOffset;original=$plan.original;replacement=$plan.replacement;kind=$kind;owner_function=$owner.Name})
      [void]$functionalSites.Add(@{function=$record.name;owner_function=$owner.Name;kind=$kind;ast_kind=$part.GetType().Name;start_utf16=$extent.StartOffset;end_utf16=$extent.EndOffset;original=$plan.original;replacement=$plan.replacement})
    }
    foreach($plan in @($functionalPlan|Where-Object{$_.function -ceq $record.name})){
      if(-not $functionalObserved.ContainsKey($plan.kind+':'+$plan.start_utf16)){throw 'Missing planned functional AST extent'}
    }
    if($TestFunctionalExtentFault -ne 'none' -and -not $functionalFaultInjected){
      $targets=@($functionalEdits|Where-Object{($TestFunctionalExtentTarget -eq 'score-sort' -and $_.kind -eq 'score-sort-command') -or ($TestFunctionalExtentTarget -eq 'async-type' -and $_.kind -eq 'parameter')})
      if($targets.Count){
        $first=$targets[0]
        if($TestFunctionalExtentFault -eq 'duplicate'){[void]$functionalEdits.Add(@{start=$first.start;end=$first.end;original=$first.original;replacement=$first.replacement;kind=$first.kind;owner_function=$first.owner_function})}
        elseif($TestFunctionalExtentFault -eq 'changed'){$first.original='Changed functional extent'}
        else{$first.replacement='UnplannedFunctionalReplacement'}
        $functionalFaultInjected=$true
      }
    }
    # Reconstruct from the original function again. Keeping the Args-only hash
    # above means the existing corrected-intent seam never describes this tier.
    $functionalCombined=New-Object Collections.ArrayList
    foreach($edit in $combined){[void]$functionalCombined.Add($edit)}
    foreach($edit in $functionalEdits){[void]$functionalCombined.Add($edit)}
    $body=$node.Extent.Text;$previous=$body.Length;$applied=0
    foreach($edit in @($functionalCombined|Sort-Object -Property {[int]$_['start']} -Descending)){
      if($edit.start -lt 0 -or $edit.end -gt $node.Extent.Text.Length -or $edit.end -le $edit.start){throw 'Functional-intent extent is out of bounds'}
      $actual=$body.Substring($edit.start,$edit.end-$edit.start);$reason=$null
      if($edit.end -gt $previous){$reason='overlap_or_order'}
      elseif($actual -cne $edit.original){$reason='text_mismatch'}
      elseif($edit.ContainsKey('owner_function')){
        $allowed=@($functionalPlan|Where-Object{$_.function -ceq $record.name -and $_.start_utf16 -eq ($node.Extent.StartOffset+$edit.start) -and $_.end_utf16 -eq ($node.Extent.StartOffset+$edit.end) -and $_.kind -ceq $edit.kind -and $_.owner_function -ceq $edit.owner_function -and $_.original -ceq $edit.original -and $_.replacement -ceq $edit.replacement})
        if($allowed.Count -ne 1){$reason='wrong_replacement_name'}
      }
      if($reason){
        $diagnostic=@{schema='cucp.oracle-functional-extent-refusal/v1';function=$record.name;owner_function=$edit.owner_function;kind=$edit.kind;reason=$reason;start_utf16=$node.Extent.StartOffset+$edit.start;end_utf16=$node.Extent.StartOffset+$edit.end;applied=$applied;planned=$functionalCombined.Count;actual_prefix=$actual.Substring(0,[Math]::Min(128,$actual.Length))}
        [Console]::Error.WriteLine((ConvertTo-Json -InputObject $diagnostic -Depth 4 -Compress))
        throw 'Unsafe functional-intent extent'
      }
      $body=$body.Substring(0,$edit.start)+$edit.replacement+$body.Substring($edit.end)
      $previous=$edit.start;$applied++
    }
    $functionalTokens=$null;$functionalErrors=$null
    $functionalAst=[Management.Automation.Language.Parser]::ParseInput($body,[ref]$functionalTokens,[ref]$functionalErrors)
    if($functionalErrors.Count -or $functionalAst.EndBlock.Statements.Count -ne 1 -or $functionalAst.EndBlock.Statements[0] -isnot [Management.Automation.Language.FunctionDefinitionAst] -or $functionalAst.EndBlock.Statements[0].Name -cne $record.name){throw 'Invalid functional-intent oracle function'}
    [void]$functionalFunctions.Add(@{name=$record.name;original_sha256=$record.sha256;type_only_sha256=$typeOnlyHash;args_only_sha256=$argsOnlyHash;functional_sha256=(Hash-Text $body)})
  }
  [void]$functions.Add(@{name=$record.name;original_sha256=$record.sha256;substituted_sha256=$typeOnlyHash;body=$body})
}
if($functions.Count -ne $importNames.Count -or $sites.Count -ne 52){throw 'Oracle substitution scope changed'}
foreach($name in $typeCounts.Keys){if($seen[$name] -ne $typeCounts[$name]){throw "Oracle type substitution count changed: $name"}}
if($CorrectedIntent -and ($argsPlan.Count -ne 7 -or $argsSites.Count -ne 34 -or $correctedFunctions.Count -ne 8 -or @($argsSites|Where-Object{$_.kind -eq 'parameter'}).Count -ne 7 -or @($argsSites|Where-Object{$_.kind -eq 'variable'}).Count -ne 21 -or @($argsSites|Where-Object{$_.kind -eq 'command-parameter'}).Count -ne 6)){throw 'Corrected-intent Args substitution scope changed'}
if($FunctionalIntent -and ($functionalPlan.Count -ne 4 -or $functionalSites.Count -ne 4 -or $functionalFunctions.Count -ne 8 -or @($functionalSites|Where-Object{$_.kind -eq 'parameter'}).Count -ne 1 -or @($functionalSites|Where-Object{$_.kind -eq 'variable'}).Count -ne 1 -or @($functionalSites|Where-Object{$_.kind -eq 'score-sort-command'}).Count -ne 2)){throw 'Functional-intent substitution scope changed'}
if($TestFunctionalExtentFault -ne 'none' -and -not $functionalFaultInjected){throw 'Functional extent fault target was not reached'}
$stableSortHelper=$null
if($FunctionalIntent){
  # Hash the literal counted helper definition before any facade compilation or
  # action import. It cannot be supplied by the manifest, request, or caller.
  $driverText=[IO.File]::ReadAllText($PSCommandPath,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
  $driverTokens=$null;$driverErrors=$null
  $driverAst=[Management.Automation.Language.Parser]::ParseInput($driverText,[ref]$driverTokens,[ref]$driverErrors)
  $helpers=@($driverAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq '_Oracle-StableScore'},$true))
  if($driverErrors.Count -or $helpers.Count -ne 1 -or (Hash-Text $helpers[0].Extent.Text) -cne '12d58b4e481506dd32dfc9b980132d80f1f2274db995bbfaf9a8c09f62757a27'){throw 'Stable score helper definition changed'}
  $stableSortHelper=@{name='_Oracle-StableScore';sha256=(Hash-Text $helpers[0].Extent.Text);source_path='tests/fixtures/legacy-helper/oracle.ps1'}
}

# The fixture is pinned before compilation. Unique namespace names never ask
# the runtime to resolve native Windows/WinRT types. The assembly guard is
# fail-closed for EVERY substituted type, including enums and nested RECT.
$facadeText=[IO.File]::ReadAllText($Stubs,[Text.Encoding]::UTF8).TrimStart([char]0xfeff).Replace("`r`n","`n")
$facadeHash=Hash-Text $facadeText
if($facadeHash -cne '0c19cfcd11a7d5f0c21f9433400a1e365361ae74d3662595b719b28301656148'){throw 'Inert oracle facade hash mismatch'}
$emitted=@(Microsoft.PowerShell.Utility\Add-Type -TypeDefinition $facadeText -ReferencedAssemblies @('System.dll','System.Core.dll','System.Web.Extensions.dll') -PassThru -ErrorAction Stop)
$anchors=@($emitted|Where-Object{$_.FullName -ceq 'CucpFixture.HelperFixture'})
if($anchors.Count -ne 1){throw 'Missing unique oracle fixture assembly'}
$fixtureAssembly=$anchors[0].Assembly
$resolved=New-Object Collections.ArrayList
foreach($typeName in $typeCounts.Keys){
  $resolvedName=$fixturePrefix+$typeName
  $type=$resolvedName -as [type]
  # Negative qualification can only force a harmless, wrong-assembly type.
  # The unchanged guard below must refuse it before importing any action.
  if($TestWrongBinding){$type=[string]}
  $expected=$fixtureAssembly.GetType($resolvedName,$false,$false)
  if(-not $type -or -not $expected -or $type.Assembly -ne $fixtureAssembly -or -not [object]::ReferenceEquals($type,$expected)){throw "Unsafe oracle type resolution: $resolvedName"}
  [void]$resolved.Add($type.FullName)
}
$seam=@{schema='cucp.oracle-type-seam/v1';source_sha256=$entry.normalized_sha256;facade_sha256=$facadeHash;type_substitutions=@($sites);guarded_types=@($resolved);functions=@($functions|ForEach-Object{@{name=$_.name;original_sha256=$_.original_sha256;substituted_sha256=$_.substituted_sha256}})}
$argsSeam=$null
if($CorrectedIntent){$argsSeam=@{schema='cucp.oracle-corrected-intent-seam/v1';qualification='corrected-intent-only';source_sha256=$entry.normalized_sha256;args_substitutions=@($argsSites);functions=@($correctedFunctions)}}
$functionalSeam=$null
if($FunctionalIntent){
  $functionalSeam=@{schema='cucp.oracle-functional-intent-seam/v1';qualification='functional-intent-only';source_sha256=$entry.normalized_sha256;functional_substitutions=@($functionalSites);stable_sort_helper=$stableSortHelper;functions=@($functionalFunctions)}
  # Insertion moves only strictly lower numeric scores. Equal scores therefore
  # retain acquisition order. WriteObject(false) emits each original record by
  # reference, without decorating, mutating, or enumerating its dictionary.
  function _Oracle-StableScore {
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline=$true)][object]$Record)
    begin { $orderedRecords=New-Object Collections.ArrayList }
    process {
      $position=$orderedRecords.Count
      while($position -gt 0 -and [double]($orderedRecords[$position-1]['score']) -lt [double]($Record['score'])){ $position-- }
      [void]$orderedRecords.Insert($position,$Record)
    }
    end { foreach($item in $orderedRecords){ $PSCmdlet.WriteObject($item,$false) } }
  }
}
foreach($function in $functions){. ([scriptblock]::Create($function.body))}
$c=[IO.File]::ReadAllText($CasePath,[Text.Encoding]::UTF8)|ConvertFrom-Json
if($c.culture){[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$c.culture);[Threading.Thread]::CurrentThread.CurrentUICulture=[Threading.Thread]::CurrentThread.CurrentCulture}
function Convert-Case($Value) {
  if($null -eq $Value){return $null}
  if($Value -is [array]){$a=New-Object Collections.ArrayList;foreach($v in $Value){[void]$a.Add((Convert-Case $v))};return ,$a.ToArray()}
  if($Value -is [Management.Automation.PSCustomObject]){$r=@{};foreach($p in $Value.PSObject.Properties){$r[$p.Name]=Convert-Case $p.Value};return $r}
  return $Value
}
$PipeName='fixture';$Script:_StartedAt=[DateTime]::UtcNow;$Script:_RequestCount=0;$Script:_Win32Loaded=$false;$Script:_UIALoaded=$false;$Script:_OCREngine=$null;$Script:_OCRError=$null
# These acquisition seams are deliberate fixtures. No top-level server loop,
# process launch, lock mutation, input, screen capture, or real UIA is executed.
$script:effects=New-Object Collections.ArrayList
function Add-Type { param($AssemblyName,$LiteralPath,$TypeDefinition) if($TypeDefinition -or $LiteralPath){throw 'unplanned Add-Type'};if($AssemblyName -eq 'UIAutomationClient' -and $Stubs){[CucpFixture.HelperFixture]::Trace('uia.loadModal',@())};if($AssemblyName -eq 'System.Drawing' -and $Stubs){[CucpFixture.HelperFixture]::Trace('ocr.loadDrawing',@())} }
function _Ensure-Win32Loaded { if($Script:_Win32Loaded){return $true};if($Stubs){[CucpFixture.HelperFixture]::Trace('win32.ensure',@())};[void]$script:effects.Add('ensure_win32');if($c.win32){$Script:_Win32Loaded=$true;return $true};return $false }
function _Server-Ensure-UIA { if($Script:_UIALoaded){return $true};if($Stubs){[CucpFixture.HelperFixture]::Trace('uia.load',@())};[void]$script:effects.Add('ensure_uia');if($c.uia){$Script:_UIALoaded=$true;return $true};return $false }
function _Server-Ensure-OCR {
  if($Script:_OCREngine){return $true}
  if($Stubs){[CucpFixture.HelperFixture]::Trace('ocr.initialize',@())}
  [void]$script:effects.Add('ensure_ocr')
  if($c.ocr){[CucpFixture.HelperFixture]::Trace('ocr.createProfile',@());$Script:_OCREngine=New-Object CucpFixture.Windows.Media.Ocr.OcrEngine;return $true}
  $Script:_OCRError='owned fixture init failure';return $false
}
function Remove-Item { param($LiteralPath,[switch]$Force) if($Stubs){[CucpFixture.HelperFixture]::Trace('ocr.removeTemp',@([string]$LiteralPath))} }

[CucpFixture.HelperFixture]::Initialize(($c|ConvertTo-Json -Depth 50 -Compress))
$results=New-Object Collections.ArrayList
foreach($r in $c.requests){
  $value=$null;$errorValue=$null
  try {
    if($CorrectedIntent){$value=_Dispatch -Action ([string]$r.action) -RequestData (Convert-Case $r.args)}
    else{$value=_Dispatch -Action ([string]$r.action) -Args (Convert-Case $r.args)}
  }catch{$errorValue=$_.Exception.Message}
  # Real time/PID are not deterministically replaceable in the exact function.
  if($value -and $value.schema -eq 'cucp.health/v1'){$value.pid=123;$value.uptime_s=0}
  $exitValue=0;if($errorValue -or $value.status -eq 'error'){$exitValue=1}elseif($value.status -eq 'partial'){$exitValue=2}elseif($value.status -eq 'fallback_required'){$exitValue=99};[void]$results.Add(@{id=$r.id;exit_code=$exitValue;result=$value;error=$errorValue})
}
# Keep the collection as an array even at cardinality zero or one. An untyped
# assignment from an if/pipeline loses the empty collection's JSON shape on PS5.
[object[]]$trace=@([CucpFixture.HelperFixture]::Effects.ToArray())
$output=@{oracle_mode=$(if($FunctionalIntent){'functional-intent'}elseif($CorrectedIntent){'corrected-intent'}else{'exact-original'});responses=@($results);effects=@($script:effects);calls=$trace;request_count=$Script:_RequestCount;oracle_seam=$seam;args_seam=$argsSeam}
if($FunctionalIntent){$output.functional_seam=$functionalSeam}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $output -Depth 50 -Compress))
