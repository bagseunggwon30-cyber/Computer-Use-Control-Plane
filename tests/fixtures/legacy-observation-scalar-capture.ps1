# Inert Windows PowerShell 5.1 proof of Invoke-NativeHelper's scalar copy.
# Only owned temporary files are read/written. The wrapper is parsed, never
# loaded or invoked. Run under an external timeout: the regression being tested
# is a ConvertTo-Json hang. Decorated inputs are never recursively serialized.
param([Parameter(Mandatory=$true)][string]$WrapperPath)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1 -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
 throw 'Scalar capture qualification requires ordinary Windows PowerShell 5.1.'
}
$utf8=[Text.UTF8Encoding]::new($false,$true)
[Console]::OutputEncoding=$utf8
$OutputEncoding=$utf8

function Assert-ScalarEqual($Actual,$Expected,[string]$Label) {
 if (($null -eq $Actual) -ne ($null -eq $Expected)) { throw ($Label+': null/empty identity changed.') }
 if ($null -ne $Expected) {
  if ($Actual -isnot [string] -or $Expected -isnot [string]) { throw ($Label+': expected System.String.') }
  if (-not [string]::Equals($Actual,$Expected,[StringComparison]::Ordinal)) { throw ($Label+': UTF-16 code units changed.') }
 }
}

function Get-ScalarEvidence($Value) {
 # Do not evaluate property values: PSDrive/PSProvider lead to provider graphs.
 $names=@();$type='null';$length=$null;$units=$null
 if ($null -ne $Value) {
  if ($Value -isnot [string]) { throw 'Unexpected non-string capture.' }
  if ($Value.Length -gt 2048) { throw 'Fixture scalar exceeded its evidence bound.' }
  $type=$Value.PSObject.BaseObject.GetType().FullName
  $names=@(foreach ($property in $Value.PSObject.Properties) {
   if ($property.Name.Length -gt 128) { throw 'Fixture property name exceeded its evidence bound.' }
   [string]::new($property.Name.ToCharArray())
  })
  if ($names.Count -gt 32) { throw 'Fixture property count exceeded its evidence bound.' }
  $length=$Value.Length
  # Encoding.Unicode.GetBytes would replace an unpaired surrogate. Encode each
  # UTF-16 code unit explicitly so even NUL and lone surrogates remain exact.
  $bytes=New-Object byte[] ($length*2)
  for ($i=0;$i -lt $length;$i++) {
   $unit=[int][char]$Value[$i]
   $bytes[2*$i]=[byte]($unit -band 255)
   $bytes[2*$i+1]=[byte]($unit -shr 8)
  }
  $units=[Convert]::ToBase64String($bytes)
 }
 return [ordered]@{is_null=($null -eq $Value);type=$type;properties=$names;utf16_length=$length;utf16le_base64=$units}
}

function Test-ScalarCopy($Before,$After,$Expected,[string]$Label,[bool]$ExpectProvider) {
 Assert-ScalarEqual $Before $Expected ($Label+'.input')
 Assert-ScalarEqual $After $Expected ($Label+'.copy')
 $beforeEvidence=Get-ScalarEvidence $Before
 $afterEvidence=Get-ScalarEvidence $After
 if ($beforeEvidence.utf16le_base64 -cne $afterEvidence.utf16le_base64) { throw ($Label+': exact UTF-16 evidence changed.') }
 if ($ExpectProvider) {
  foreach ($name in @('PSDrive','PSProvider')) {
   if ($beforeEvidence.properties -cnotcontains $name) { throw ($Label+': real Get-Content input lacks '+$name+'.') }
  }
 }
 foreach ($name in @('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider','ReadCount')) {
  if ($afterEvidence.properties -ccontains $name) { throw ($Label+': copied scalar retained '+$name+'.') }
 }
 $freshReference=$null
 if ($null -ne $Before -and $Before.Length -gt 0) {
  $freshReference=-not [object]::ReferenceEquals($Before.PSObject.BaseObject,$After.PSObject.BaseObject)
  if (-not $freshReference) { throw ($Label+': nonempty copy reused the original string reference.') }
 }
 return [ordered]@{before=$beforeEvidence;after=$afterEvidence;fresh_reference=$freshReference;exact_utf16=$true;provider_expected=$ExpectProvider}
}

$wrapper=[IO.Path]::GetFullPath($WrapperPath)
$sourceBytes=[IO.File]::ReadAllBytes($wrapper)
$sha=[Security.Cryptography.SHA256]::Create()
try { $sourceHash=[BitConverter]::ToString($sha.ComputeHash($sourceBytes)).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose() }
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($wrapper,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Scalar capture wrapper has parse errors.' }
$functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-NativeHelper'},$true))
if ($functions.Count -ne 1) { throw 'Expected exactly one production Invoke-NativeHelper.' }
$native=$functions[0]
# ReadAllLines is intentional: source strings must not introduce the very ETS
# metadata this fixture is qualifying at the separate, actual Get-Content leaf.
$lines=[IO.File]::ReadAllLines($wrapper)
$rawStatement='if ($raw -is [string]) { $raw = [string]::new($raw.ToCharArray()) }'
$errStatement='if ($err -is [string]) { $err = [string]::new($err.ToCharArray()) }'
foreach ($statement in @($rawStatement,$errStatement)) {
 $matches=@(for ($i=$native.Extent.StartLineNumber-1;$i -lt $native.Extent.EndLineNumber;$i++) {
  if ($lines[$i].Trim() -ceq $statement) { $i }
 })
 if ($matches.Count -ne 1) { throw 'Expected each exact production scalar-copy statement once in Invoke-NativeHelper.' }
}
$starts=@(for ($i=$native.Extent.StartLineNumber-1;$i -lt $native.Extent.EndLineNumber;$i++) {
 if ($lines[$i].Trim() -ceq '$raw = ""') { $i }
})
if ($starts.Count -ne 1) { throw 'Expected one production raw initializer.' }
$statusBlocks=@($native.Body.FindAll({param($node)
 $node -is [Management.Automation.Language.IfStatementAst] -and $node.Extent.Text.StartsWith('if ($exitCode -eq 0 -and $json) {',[StringComparison]::Ordinal)
},$true))
if ($statusBlocks.Count -ne 1) { throw 'Expected one production JSON status correction.' }
$start=$starts[0];$end=$statusBlocks[0].Extent.EndLineNumber-1
if ($end -le $start -or $end-$start -gt 32) { throw 'Unexpected production capture block bounds.' }
$actual=@(for ($i=$start;$i -le $end;$i++) {
 $line=$lines[$i].Trim()
 if ($line -and -not $line.StartsWith('#',[StringComparison]::Ordinal)) { $line }
})
# Pin the whole reachable fragment before executing any extracted source. This
# rejects changed reads, reordered/missing copies, altered parsing or exit rules.
$expected=@(
 '$raw = ""',
 '$err = ""',
 'if (Test-Path -LiteralPath $stdoutFile) { $raw = Get-Content -LiteralPath $stdoutFile -Raw -Encoding UTF8 }',
 'if (Test-Path -LiteralPath $stderrFile) { $err = Get-Content -LiteralPath $stderrFile -Raw -Encoding UTF8 }',
 $rawStatement,
 $errStatement,
 '$json = $null',
 'if ($raw -and $raw.Trim().Length -gt 0) {',
 'try { $json = $raw | ConvertFrom-Json -ErrorAction Stop } catch { }',
 '}',
 'if ($exitCode -eq 0 -and $json) {',
 'switch ("$($json.status)") {',
 '"partial" { $exitCode = 2 }',
 '"error"   { $exitCode = 1 }',
 '}',
 '}'
)
if ($actual.Count -ne $expected.Count) { throw 'Production scalar capture fragment length mismatch.' }
for ($i=0;$i -lt $expected.Count;$i++) {
 if ($actual[$i] -cne $expected[$i]) { throw ('Production scalar capture source mismatch at fragment line '+($i+1)+'.') }
}
# These are production source lines, not the expected literals above. Splitting
# only allows bounded evidence to be collected before the two original copies.
$readBlock=[scriptblock]::Create(($actual[0..3] -join "`n"))
$copyBlock=[scriptblock]::Create(($actual[4..5] -join "`n"))
$parseBlock=[scriptblock]::Create(($actual[6..15] -join "`n"))

# Build non-ASCII text by UTF-16 code points so this fixture itself is ASCII and
# Windows PowerShell 5.1 cannot misread its source as an ANSI code page.
$korean=[string]::new([char[]]@([char]0xD55C,[char]0xAE00))
$rich=$korean+' '+[char]::ConvertFromUtf32(0x1F600)+' "quotes" C:\owned\path'+"`r`n"+'NUL='+[char]0+' tail'
$okJson=ConvertTo-Json -InputObject ([ordered]@{status='ok';text=$rich;count=7;enabled=$true;absent=$null}) -Compress
$cases=@(
 @{id='missing-both';mode='files';raw_exists=$false;err_exists=$false;raw=$null;err=$null;want_raw='';want_err='';initial_exit=0;want_exit=0;want_status=$null;want_json=$false},
 @{id='empty-both';mode='files';raw_exists=$true;err_exists=$true;raw='';err='';want_raw=$null;want_err=$null;initial_exit=0;want_exit=0;want_status=$null;want_json=$false},
 @{id='missing-stdout-rich-stderr';mode='files';raw_exists=$false;err_exists=$true;raw=$null;err=$rich;want_raw='';want_err=$rich;initial_exit=1;want_exit=1;want_status=$null;want_json=$false},
 @{id='empty-stdout-missing-stderr';mode='files';raw_exists=$true;err_exists=$false;raw='';err=$null;want_raw=$null;want_err='';initial_exit=0;want_exit=0;want_status=$null;want_json=$false},
 @{id='ok-json-rich-stderr';mode='files';raw_exists=$true;err_exists=$true;raw=("`r`n"+$okJson+"`r`n");err=$rich;want_raw=("`r`n"+$okJson+"`r`n");want_err=$rich;initial_exit=0;want_exit=0;want_status='ok';want_json=$true},
 @{id='partial-json';mode='files';raw_exists=$true;err_exists=$true;raw='{"status":"partial","items":[]}';err='';want_raw='{"status":"partial","items":[]}';want_err=$null;initial_exit=0;want_exit=2;want_status='partial';want_json=$true},
 @{id='error-json';mode='files';raw_exists=$true;err_exists=$true;raw='{"status":"error","message":"owned failure"}';err=$rich;want_raw='{"status":"error","message":"owned failure"}';want_err=$rich;initial_exit=0;want_exit=1;want_status='error';want_json=$true},
 @{id='nonzero-exit-preserved';mode='files';raw_exists=$true;err_exists=$true;raw='{"status":"partial"}';err=$rich;want_raw='{"status":"partial"}';want_err=$rich;initial_exit=17;want_exit=17;want_status='partial';want_json=$true},
 @{id='rich-raw-invalid-json';mode='files';raw_exists=$true;err_exists=$true;raw=$rich;err=$rich;want_raw=$rich;want_err=$rich;initial_exit=0;want_exit=0;want_status=$null;want_json=$false},
 @{id='whitespace-raw';mode='files';raw_exists=$true;err_exists=$false;raw=" `t`r`n";err=$null;want_raw=" `t`r`n";want_err='';initial_exit=0;want_exit=0;want_status=$null;want_json=$false},
 @{id='memory-null';mode='memory';raw=$null;err=$null;want_raw=$null;want_err=$null;initial_exit=0;want_exit=0;want_status=$null;want_json=$false},
 @{id='memory-empty';mode='memory';raw='';err='';want_raw='';want_err='';initial_exit=0;want_exit=0;want_status=$null;want_json=$false}
)
$loneHigh=[string]::new([char[]]@([char]0x41,[char]0xD800,[char]0x5A))
$loneLow=[string]::new([char[]]@([char]0x42,[char]0xDC00,[char]0x59))
$cases+=@{id='memory-lone-surrogates';mode='memory';raw=$loneHigh;err=$loneLow;want_raw=$loneHigh;want_err=$loneLow;initial_exit=9;want_exit=9;want_status=$null;want_json=$false}
$root=Join-Path ([IO.Path]::GetTempPath()) ('cucp-owned-scalar-'+[guid]::NewGuid().ToString('N'))
$rows=New-Object Collections.ArrayList
$nonStringRows=New-Object Collections.ArrayList
$decoratedFields=0;$serializedCaptures=0
try {
 [void][IO.Directory]::CreateDirectory($root)
 foreach ($case in $cases) {
  $stdoutFile=Join-Path $root ($case.id+'.stdout')
  $stderrFile=Join-Path $root ($case.id+'.stderr')
  if ($case.mode -ceq 'files') {
   if ($case.raw_exists) { [IO.File]::WriteAllText($stdoutFile,$case.raw,$utf8) }
   if ($case.err_exists) { [IO.File]::WriteAllText($stderrFile,$case.err,$utf8) }
   . $readBlock
  } else { $raw=$case.raw;$err=$case.err }
  $beforeRaw=$raw;$beforeErr=$err
  . $copyBlock
  $rawProvider=($case.mode -ceq 'files' -and $null -ne $case.want_raw -and $case.want_raw.Length -gt 0)
  $errProvider=($case.mode -ceq 'files' -and $null -ne $case.want_err -and $case.want_err.Length -gt 0)
  $rawEvidence=Test-ScalarCopy $beforeRaw $raw $case.want_raw ($case.id+'.raw') $rawProvider
  $errEvidence=Test-ScalarCopy $beforeErr $err $case.want_err ($case.id+'.err') $errProvider
  if ($rawProvider) { $decoratedFields++ };if ($errProvider) { $decoratedFields++ }
  $exitCode=[int]$case.initial_exit
  . $parseBlock
  $status=$null;if ($null -ne $json) { $status=$json.status }
  if ($exitCode -ne $case.want_exit -or ($null -ne $json) -ne $case.want_json -or $status -cne $case.want_status) { throw ($case.id+': production parse/status/exit semantics changed.') }
  if ($case.id -ceq 'ok-json-rich-stderr') {
   Assert-ScalarEqual $json.text $rich 'parsed JSON rich text'
   if ($json.count -ne 7 -or $json.enabled -ne $true -or $null -ne $json.absent) { throw 'Parsed JSON scalar fields changed.' }
  }
  $captureJson=$null;$jsonRoundTrip=$false
  if ($case.id -cne 'memory-lone-surrogates') {
   # Reproduce the final SmartPlan capture depth with copied scalars only.
   # No before-reference, provider property value or source object enters it.
   $capture=[pscustomobject]@{ExitCode=$exitCode;Json=$json;Raw=$raw;Err=$err;ElapsedMs=0;FromHotCache=$false;Route='child'}
   $payload=@{schema='cucp.legacy-compat/v1';operation='smart-plan-advance';args=@{captured_replies=@(@{result=$capture})};culture=[Globalization.CultureInfo]::CurrentCulture.Name}
   $captureJson=$payload | ConvertTo-Json -Depth 24 -Compress
   if ($captureJson.Length -gt 8192) { throw 'Copied capture JSON exceeded its evidence bound.' }
   $decoded=$captureJson | ConvertFrom-Json -ErrorAction Stop
   $roundTrip=$decoded.args.captured_replies[0].result
   Assert-ScalarEqual $roundTrip.Raw $raw ($case.id+'.json.raw')
   Assert-ScalarEqual $roundTrip.Err $err ($case.id+'.json.err')
   if ($roundTrip.ExitCode -ne $exitCode -or ($null -ne $roundTrip.Json) -ne $case.want_json) { throw ($case.id+': capture JSON semantics changed.') }
   if ($case.want_json -and $roundTrip.Json.status -cne $case.want_status) { throw ($case.id+': capture JSON status changed.') }
   $jsonRoundTrip=$true;$serializedCaptures++
  }
  # Lone surrogates are intentionally in-memory only. Their exact code units
  # are reported as base64; passing them through UTF-8 would be lossy/invalid.
  [void]$rows.Add([ordered]@{id=$case.id;mode=$case.mode;raw=$rawEvidence;err=$errEvidence;initial_exit=[int]$case.initial_exit;exit_code=$exitCode;json_present=($null -ne $json);json_status=$status;json_round_trip=$jsonRoundTrip;surrogate_memory_only=($case.id -ceq 'memory-lone-surrogates');copied_capture_json=$captureJson})
 }
 # Non-string values are outside Get-Content's normal scalar contract, but the
 # two guards must leave them untouched. Exercise only the exact copy fragment;
 # feeding arbitrary objects into the original string parser is not supported.
 $nonStrings=@(
  @{id='int-and-bool';raw=[int]17;err=$true;references=$false},
  @{id='long-and-double';raw=[long]9007199254740993;err=[double]2.5;references=$false},
  @{id='object-and-array';raw=[pscustomobject]@{marker='owned-scalar-fixture'};err=[object[]]@(1,$false);references=$true}
 )
 foreach ($case in $nonStrings) {
  $raw=$case.raw;$err=$case.err;$beforeRaw=$raw;$beforeErr=$err
  . $copyBlock
  $fields=[ordered]@{}
  foreach ($field in @(@{name='raw';before=$beforeRaw;after=$raw},@{name='err';before=$beforeErr;after=$err})) {
   $beforeType=$field.before.GetType().FullName;$afterType=$field.after.GetType().FullName
   if ($beforeType -cne $afterType -or $field.after -is [string]) { throw ($case.id+': non-string type was coerced.') }
   $sameReference=[object]::ReferenceEquals($field.before,$field.after)
   $value=$null
   if ($case.references) {
    if (-not $sameReference) { throw ($case.id+': non-string object reference changed.') }
   } else {
    if (-not [object]::Equals($field.before,$field.after)) { throw ($case.id+': non-string scalar value changed.') }
    $value=$field.after
   }
   # Arbitrary objects themselves never enter the output, only bounded type
   # names and identity evidence; numeric/boolean cases are ordinary scalars.
   $fields[$field.name]=[ordered]@{before_type=$beforeType;after_type=$afterType;same_reference=$sameReference;value_preserved=$true;scalar_value=$value}
  }
  [void]$nonStringRows.Add([ordered]@{id=$case.id;raw=$fields.raw;err=$fields.err})
 }
 if ($decoratedFields -eq 0 -or $serializedCaptures -ne 12 -or $rows.Count -ne 13) { throw 'Scalar capture qualification did not complete its expected coverage.' }
 $sha=[Security.Cryptography.SHA256]::Create()
 try { $afterHash=[BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($wrapper))).Replace('-','').ToLowerInvariant() }
 finally { $sha.Dispose() }
 if ($afterHash -cne $sourceHash) { throw 'Wrapper source changed during scalar qualification.' }
 $result=[ordered]@{schema='cucp.observation-scalar-capture/v1';status='ok';powershell=$PSVersionTable.PSVersion.ToString();wrapper_sha256=$sourceHash;source_unchanged=$true;source_statements=@($actual[4..5]);decorated_fields=$decoratedFields;serialized_captures=$serializedCaptures;cases=[object[]]$rows.ToArray();non_string_cases=[object[]]$nonStringRows.ToArray()}
 [Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Depth 12 -Compress))
} finally {
 if ([IO.Directory]::Exists($root)) { [IO.Directory]::Delete($root,$true) }
}
