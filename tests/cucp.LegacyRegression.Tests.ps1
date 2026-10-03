BeforeAll {
# Pester 5.x unit regressions. No live Windows input or full script dispatch.
# Run: Invoke-Pester tests/cucp.LegacyRegression.Tests.ps1
$repoRoot = Split-Path -Parent $PSScriptRoot
$wrapperPath = Join-Path $repoRoot "scripts/cucp.ps1"
$helperPath = Join-Path $repoRoot "scripts/cucp-native-helper.ps1"
$tokens = $null
$parseErrors = $null
$wrapperAst = [System.Management.Automation.Language.Parser]::ParseFile($wrapperPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$helperAst = [System.Management.Automation.Language.Parser]::ParseFile($helperPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$cdpPath = Join-Path $repoRoot "scripts/cucp-legacy-cdp-adapter.ps1"
$cdpAst = [System.Management.Automation.Language.Parser]::ParseFile($cdpPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$Script:LegacyCdpSourceRoot = $repoRoot
# The CI gate supplies the matching compiled host for compatibility and family sessions.
if (-not $env:CUCP_NATIVE_HOST -or -not (Test-Path -LiteralPath $env:CUCP_NATIVE_HOST -PathType Leaf) -or
    [IO.Path]::GetExtension($env:CUCP_NATIVE_HOST) -notin @('.exe', '.dll')) {
  throw 'Set CUCP_NATIVE_HOST to the matching built NativeHost executable or DLL before running these regressions.'
}
$Script:Brief = $false
$Script:AllowLiveControl = $false
$Script:CacheSeconds = 0
$Script:CliPath = $null
$Script:AuditDir = Join-Path $TestDrive 'audit'
$Script:CacheDir = Join-Path $TestDrive 'cache'
$Script:WrapperLog = Join-Path $TestDrive 'wrapper.log'

function Get-LegacyFunctionText {
  param($Ast, [string]$Name)
  $found = @($Ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $Name
  }, $true))
  if ($found.Count -ne 1) { throw "Expected one definition of $Name; found $($found.Count)" }
  return $found[0].Extent.Text
}
foreach ($name in @("_Invoke-LegacyCompatibility", "_Read-OptValue", "_Read-Switch", "_Parse-WorkflowStepTokens", "_Read-WorkflowStepSpecs",
    "_Build-WorkflowPlan", "Invoke-MacroSafeType", "Invoke-MacroClickPoint",
    "Invoke-MacroBenchmark", "Invoke-MacroPrecisionValidate")) {
  . ([scriptblock]::Create((Get-LegacyFunctionText -Ast $wrapperAst -Name $name)))
}
foreach ($name in @("_Invoke-LegacyCdpBridge", "_Invoke-LegacyCdpMacro", "Invoke-MacroCdpEval")) {
  . ([scriptblock]::Create((Get-LegacyFunctionText -Ast $cdpAst -Name $name)))
}
# Load real transport and family support for both retained bodies and promoted
# delegates. Public macros above always come from the main production wrapper.
foreach ($name in @('_Read-StandaloneConfirmation', '_Execution-Require', '_Execution-Fields',
    '_Execution-EncodeWire', '_Execution-DecodeWire', '_Execution-WriteChunks', '_Execution-WriteDiagnostic',
    '_Execution-ValidateEffect', '_Execution-Dispatch', '_Execution-EffectMayChangeState',
    '_Invoke-LegacyExecutionEffectLoop', '_Invoke-LegacyExecutionHost')) {
  . ([scriptblock]::Create((Get-LegacyFunctionText -Ast $wrapperAst -Name $name)))
}
$familySupport = @(
  @{ Path = 'scripts/cucp-legacy-interaction-adapter.ps1'; Names = @(
    '_Interaction-Integer', '_Interaction-Number', '_Interaction-Text', '_Interaction-Point',
    '_Interaction-Arguments', '_Interaction-Record', '_Interaction-ValidateEffect', '_Interaction-Dispatch',
    '_Invoke-LegacyInteractionFamily') },
  @{ Path = 'scripts/cucp-legacy-diagnostic-adapter.ps1'; SourceFile = $true; Names = @(
    '_Diagnostic-Require', '_Diagnostic-Fields', '_Diagnostic-ArgvEquals', '_Diagnostic-Value',
    '_Diagnostic-IntOption', '_Diagnostic-NewState', '_Diagnostic-Limit', '_Diagnostic-ValidateEffect',
    '_Diagnostic-Clock', '_Diagnostic-NodeVersion', '_Diagnostic-TailBytes', '_Diagnostic-AssertOwnedRoot',
    '_Diagnostic-PathEquals', '_Diagnostic-AuditProbe', '_Diagnostic-ClearAppshotCache',
    '_Diagnostic-CapturedMacro', '_Diagnostic-Dispatch', '_Diagnostic-PreparePayload', '_Diagnostic-GetContext',
    '_Diagnostic-ProcessorCount', '_Invoke-LegacyDiagnosticFamily', '_Diagnostic-Processes',
    '_Diagnostic-ProcessMetrics', '_Diagnostic-DisposeProcesses') }
)
foreach ($support in $familySupport) {
  $supportPath = Join-Path $repoRoot $support.Path
  $supportAst = [System.Management.Automation.Language.Parser]::ParseFile($supportPath, [ref]$tokens, [ref]$parseErrors)
  if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
  foreach ($name in $support.Names) {
    $functionText = Get-LegacyFunctionText -Ast $supportAst -Name $name
    if (-not $support.SourceFile) { . ([scriptblock]::Create($functionText)) }
  }
  if ($support.SourceFile) {
    # Preserve the real file's PSScriptRoot used by _Diagnostic-GetContext.
    # Only the listed support definitions may execute; public macros stay above.
    $statements = @($supportAst.EndBlock.Statements)
    if ($supportAst.UsingStatements.Count -or $supportAst.ParamBlock -or
        $supportAst.BeginBlock -or $supportAst.ProcessBlock -or
        ($supportAst.PSObject.Properties['CleanBlock'] -and $supportAst.CleanBlock) -or
        $supportAst.DynamicParamBlock -or $supportAst.EndBlock.Traps.Count -or
        $statements.Count -ne $support.Names.Count -or @($statements | Where-Object {
          $_ -isnot [System.Management.Automation.Language.FunctionDefinitionAst] -or
          $_.Name -cnotin $support.Names
        }).Count) { throw 'File-backed support must contain only the selected function definitions.' }
    . $supportPath
  }
}
function Invoke-NativeHelper { param([string[]]$ArgList) throw "Live helper must be mocked" }
function _Classify-SafetyFromText { param($Text, $MacroName) return @{ requires_explicit_confirmation=$false } }
function _Trajectory-Append { param($Kind, $Payload) }
function Invoke-CapturedLegacy {
  param([scriptblock]$Body)
  $original = [Console]::Out
  $writer = New-Object System.IO.StringWriter
  try {
    [Console]::SetOut($writer)
    $code = & $Body
    $json = $writer.ToString() | ConvertFrom-Json
    return [pscustomobject]@{ ExitCode=$code; Json=$json }
  } finally { [Console]::SetOut($original); $writer.Dispose() }
}

# Exercise the production SendInput check with an injected native API stub.
$interopSource = Join-Path $repoRoot "pcucp-next/dotnet/PcuCp.LegacyInterop/CucpNative.cs"
$helperSource = Get-Content -LiteralPath $interopSource -Raw -Encoding UTF8
$checkedMethod = [regex]::Match($helperSource, '(?s)  private static void SendInputChecked\(INPUT\[\] inputs\) \{.*?\n  \}').Value
if (-not $checkedMethod) { throw "SendInputChecked implementation missing" }
if (-not ("CucpLegacyInputTestNative" -as [type])) {
  Add-Type -TypeDefinition (@'
using System;
using System.Runtime.InteropServices;
public static class CucpLegacyInputTestNative {
  public struct INPUT { public int value; }
  public static uint Inserted;
  public static uint SendInput(uint count, INPUT[] inputs, int size) { return Inserted; }
  public static void Check(uint inserted) { Inserted = inserted; SendInputChecked(new INPUT[2]); }
'@ + $checkedMethod + "`n}")
}
}

Describe "legacy command boundaries" {
  BeforeEach {
    $script:Brief = $false
    $script:AllowLiveControl = $false
    $script:CacheSeconds = 0
  }
  It "blocks arbitrary JavaScript before touching a CDP target" {
    Mock Invoke-NativeHelper { throw "Must not execute" }
    { Invoke-MacroCdpEval -Rest @("--expr", "document.body.remove()") } | Should -Throw "*requires -AllowLiveControl*"
    Assert-MockCalled Invoke-NativeHelper -Times 0 -Exactly
  }
  It "uses the first Python on PATH when duplicate applications are discoverable" {
    Mock Invoke-NativeHelper { throw "Must not execute" }
    $originalPath = $env:PATH
    $originalCdpHost = $env:CUCP_LEGACY_CDP_HOST
    $originalCdpPython = $env:CUCP_LEGACY_CDP_PYTHON
    try {
      $realPython = (Get-Command python.exe -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
      Test-Path -LiteralPath $realPython -PathType Leaf | Should -BeTrue
      $secondDirectory = Join-Path $TestDrive 'secondary-python'
      [void](New-Item -ItemType Directory -Path $secondDirectory)
      $inertPython = Join-Path $secondDirectory 'python.exe'
      [IO.File]::WriteAllBytes($inertPython, [byte[]]@())
      $env:PATH = ([IO.Path]::GetDirectoryName($realPython), $secondDirectory, $originalPath) -join [IO.Path]::PathSeparator
      $env:CUCP_LEGACY_CDP_HOST = $null
      $env:CUCP_LEGACY_CDP_PYTHON = $null
      $candidates = @(Get-Command python.exe -CommandType Application -ErrorAction Stop)
      $candidates.Count | Should -BeGreaterOrEqual 2
      $candidates[0].Source | Should -Be $realPython
      @($candidates.Source) | Should -Contain $inertPython
      { Invoke-MacroCdpEval -Rest @("--expr", "document.body.remove()") } | Should -Throw "*requires -AllowLiveControl*"
      Assert-MockCalled Invoke-NativeHelper -Times 0 -Exactly
    } finally {
      $env:PATH = $originalPath
      $env:CUCP_LEGACY_CDP_HOST = $originalCdpHost
      $env:CUCP_LEGACY_CDP_PYTHON = $originalCdpPython
    }
  }
  It "uses the same first-Application rule for the actual staged helper bridge" {
    $originalPath = $env:PATH
    $originalStaged = $env:CUCP_STAGED_COMPILED_HELPER
    $originalDesktop = $env:CUCP_STAGED_HELPER_READONLY_DESKTOP
    $originalSelected = $Script:StagedCompiledHelper
    $originalCeiling = $Script:StagedHelperDesktop
    $originalLock = $Script:HelperLockPath
    try {
      $realPython = (Get-Command python.exe -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
      $secondDirectory = Join-Path $TestDrive 'staged-secondary-python'
      [void](New-Item -ItemType Directory -Path $secondDirectory)
      $inertPython = Join-Path $secondDirectory 'python.exe'
      [IO.File]::WriteAllBytes($inertPython, [byte[]]@())
      $env:PATH = ([IO.Path]::GetDirectoryName($realPython), $secondDirectory, $originalPath) -join [IO.Path]::PathSeparator
      $candidates = @(Get-Command python.exe -CommandType Application -ErrorAction Stop)
      $candidates.Count | Should -BeGreaterOrEqual 2
      $candidates[0].Source | Should -Be $realPython
      @($candidates.Source) | Should -Contain $inertPython
      $env:CUCP_STAGED_COMPILED_HELPER = '1'
      $env:CUCP_STAGED_HELPER_READONLY_DESKTOP = $null
      . (Join-Path $repoRoot 'scripts/cucp-staged-helper-adapter.ps1')
      # Reach the actual Python bridge with a closed invalid operation. Package
      # availability may vary in this shared gate; either error is returned by
      # the launched bridge, never by Process.Start or a second executable.
      $message = $null
      try { $null = _Invoke-StagedHelper -Operation 'owned-invalid-operation' }
      catch { $message = $_.Exception.Message }
      $message | Should -BeLike 'Staged helper failed; no fallback or retry:*'
    } finally {
      $env:PATH = $originalPath
      $env:CUCP_STAGED_COMPILED_HELPER = $originalStaged
      $env:CUCP_STAGED_HELPER_READONLY_DESKTOP = $originalDesktop
      $Script:StagedCompiledHelper = $originalSelected
      $Script:StagedHelperDesktop = $originalCeiling
      $Script:HelperLockPath = $originalLock
    }
  }
  It "refuses an empty or nonscalar staged Python result before process construction" {
    $originalStaged = $env:CUCP_STAGED_COMPILED_HELPER
    $originalDesktop = $env:CUCP_STAGED_HELPER_READONLY_DESKTOP
    $originalSelected = $Script:StagedCompiledHelper
    $originalCeiling = $Script:StagedHelperDesktop
    $originalLock = $Script:HelperLockPath
    try {
      $env:CUCP_STAGED_COMPILED_HELPER = '1'; $env:CUCP_STAGED_HELPER_READONLY_DESKTOP = $null
      . (Join-Path $repoRoot 'scripts/cucp-staged-helper-adapter.ps1')
      Mock Get-Command { return $script:InjectedStagedCommands } -ParameterFilter { $Name -eq 'python.exe' }
      Mock New-Object { throw 'Must not construct a process' } -ParameterFilter { $TypeName -eq 'Diagnostics.Process' }
      $script:InjectedStagedCommands = @()
      { _Invoke-StagedHelper -Operation 'version' } | Should -Throw '*one Python application*'
      $script:InjectedStagedCommands = @([pscustomobject]@{Source='invalid.exe';CommandType='Application'})
      { _Invoke-StagedHelper -Operation 'version' } | Should -Throw '*invalid or missing*'
      $script:InjectedStagedCommands = @([pscustomobject]@{Source='first.exe'},[pscustomobject]@{Source='second.exe'})
      { _Invoke-StagedHelper -Operation 'version' } | Should -Throw '*one Python application*'
      Assert-MockCalled Get-Command -Times 3 -Exactly -ParameterFilter { $Name -eq 'python.exe' -and $TotalCount -eq 1 }
      Assert-MockCalled New-Object -Times 0 -Exactly -ParameterFilter { $TypeName -eq 'Diagnostics.Process' }
    } finally {
      $env:CUCP_STAGED_COMPILED_HELPER = $originalStaged; $env:CUCP_STAGED_HELPER_READONLY_DESKTOP = $originalDesktop
      $Script:StagedCompiledHelper = $originalSelected; $Script:StagedHelperDesktop = $originalCeiling; $Script:HelperLockPath = $originalLock
    }
  }
  It "refuses a disappeared first staged Python without discovering a replacement" {
    $originalStaged = $env:CUCP_STAGED_COMPILED_HELPER
    $originalDesktop = $env:CUCP_STAGED_HELPER_READONLY_DESKTOP
    $originalSelected = $Script:StagedCompiledHelper
    $originalCeiling = $Script:StagedHelperDesktop
    $originalLock = $Script:HelperLockPath
    try {
      $script:SelectedStagedPython = Get-Command python.exe -CommandType Application -TotalCount 1 -ErrorAction Stop
      $script:SelectedStagedSource = $script:SelectedStagedPython.Source
      $env:CUCP_STAGED_COMPILED_HELPER = '1'; $env:CUCP_STAGED_HELPER_READONLY_DESKTOP = $null
      . (Join-Path $repoRoot 'scripts/cucp-staged-helper-adapter.ps1')
      Mock Get-Command { return $script:SelectedStagedPython } -ParameterFilter { $Name -eq 'python.exe' }
      Mock Test-Path { return $false } -ParameterFilter { $LiteralPath -eq $script:SelectedStagedSource }
      Mock New-Object { throw 'Must not construct a process' } -ParameterFilter { $TypeName -eq 'Diagnostics.Process' }
      { _Invoke-StagedHelper -Operation 'version' } | Should -Throw '*invalid or missing*'
      Assert-MockCalled Get-Command -Times 1 -Exactly -ParameterFilter { $Name -eq 'python.exe' -and $TotalCount -eq 1 }
      Assert-MockCalled New-Object -Times 0 -Exactly -ParameterFilter { $TypeName -eq 'Diagnostics.Process' }
    } finally {
      $env:CUCP_STAGED_COMPILED_HELPER = $originalStaged; $env:CUCP_STAGED_HELPER_READONLY_DESKTOP = $originalDesktop
      $Script:StagedCompiledHelper = $originalSelected; $Script:StagedHelperDesktop = $originalCeiling; $Script:HelperLockPath = $originalLock
    }
  }
  It "classifies cdp-eval as a live workflow step" {
    $plan = _Build-WorkflowPlan -Rest @("--step", 'macro cdp-eval --expr 1+1')
    $plan.steps[0].allowed | Should -Be $true
    $plan.steps[0].live_required | Should -Be $true
    $plan.live_step_count | Should -Be 1
  }
  It "forwards zero and negative click coordinates unchanged" {
    $script:AllowLiveControl = $true
    Mock Invoke-NativeHelper {
      return @{ ExitCode=0; Json=[pscustomobject]@{status="ok"; x=-20; y=0} }
    }
    $r = Invoke-CapturedLegacy { Invoke-MacroClickPoint -Rest @("--x", "-20", "--y", "0") }
    $r.ExitCode | Should -Be 0
    Assert-MockCalled Invoke-NativeHelper -Times 1 -Exactly -ParameterFilter {
      $ArgList[1] -eq "click" -and (_Read-OptValue $ArgList "-X") -eq "-20" -and (_Read-OptValue $ArgList "-Y") -eq "0"
    }
  }
  It "rejects an omitted coordinate instead of silently using zero" {
    $script:AllowLiveControl = $true
    { Invoke-MacroClickPoint -Rest @("--x", "0") } | Should -Throw
  }
}

Describe "legacy guarded typing" {
  BeforeEach {
    $script:Brief = $false
    $script:AllowLiveControl = $true
    $script:Calls = New-Object System.Collections.ArrayList
    $script:Windows = @([pscustomobject]@{ hwnd=42; title="Note" })
    $script:TypeFails = $false
    $script:SendFails = $false
    Mock Invoke-NativeHelper {
      [void]$script:Calls.Add([pscustomobject]@{ Action=$ArgList[1]; Args=@($ArgList) })
      switch ($ArgList[1]) {
        "windows" { return @{ExitCode=0; Json=@{status="ok"; windows=$script:Windows}} }
        "focus" { return @{ExitCode=0; Json=@{status="ok"; verified=$true; target_hwnd=42}} }
        "type" {
          if ($script:TypeFails) { return @{ExitCode=1; Json=@{status="error"}} }
          return @{ExitCode=0; Json=@{status="ok"}}
        }
        "shortcut" {
          if ($script:SendFails) { return @{ExitCode=3; Json=@{status="blocked"}} }
          return @{ExitCode=0; Json=@{status="ok"}}
        }
        default { return @{ExitCode=0; Json=@{status="ok"}} }
      }
    }
  }
  It "types the requested text once with a pinned HWND and no probe or undo" {
    $r = Invoke-CapturedLegacy { Invoke-MacroSafeType -Rest @("--text", "hello", "--target-match", "Note", "--enter") }
    $r.ExitCode | Should -Be 0
    $typed = @($script:Calls | Where-Object {$_.Action -eq "type"})
    $typed.Count | Should -Be 1
    (_Read-OptValue $typed[0].Args "-Text") | Should -Be "hello"
    foreach ($call in @($script:Calls | Where-Object {$_.Action -in @("type", "shortcut")})) {
      (_Read-OptValue $call.Args "-TargetHwnd") | Should -Be "42"
    }
    @($script:Calls | Where-Object {$_.Args -contains "ctrl+z"}).Count | Should -Be 0
    $r.Json.application_result_verified | Should -Be $false
  }
  It "does not retry uncertain text insertion or send afterward" {
    $script:TypeFails = $true
    $r = Invoke-CapturedLegacy { Invoke-MacroSafeType -Rest @("--text", "hello", "--target-match", "Note", "--max-attempts", "3", "--enter") }
    $r.ExitCode | Should -Be 2
    @($script:Calls | Where-Object {$_.Action -eq "type"}).Count | Should -Be 1
    @($script:Calls | Where-Object {$_.Action -eq "shortcut"}).Count | Should -Be 0
  }
  It "reports failed send separately after successful text dispatch" {
    $script:SendFails = $true
    $r = Invoke-CapturedLegacy { Invoke-MacroSafeType -Rest @("--text", "hello", "--target-match", "Note", "--enter") }
    $r.ExitCode | Should -Be 2
    $r.Json.text_dispatched | Should -Be $true
    $r.Json.reason | Should -Be "send_blocked_or_failed"
  }
  It "rejects an ambiguous title before focus or input" {
    $script:Windows += [pscustomobject]@{hwnd=43; title="Note 2"}
    $r = Invoke-CapturedLegacy { Invoke-MacroSafeType -Rest @("--text", "hello", "--target-match", "Note") }
    $r.ExitCode | Should -Be 2
    $r.Json.reason | Should -Be "ambiguous_target"
    $script:Calls.Count | Should -Be 1
  }
}

Describe "legacy measurement evidence" {
  BeforeEach {
    $script:Brief = $false
    $script:CucpV14Schema = @{ Benchmark="cucp.benchmark/v1"; PrecisionValidate="cucp.precision-validate/v1" }
  }
  It "loads diagnostic context from the production support file" {
    $path = Join-Path $repoRoot 'scripts/cucp-legacy-diagnostic-adapter.ps1'
    (Get-Command _Diagnostic-GetContext).ScriptBlock.File | Should -Be $path
    $context = _Diagnostic-GetContext
    [IO.Path]::GetFullPath($context.changelog_path) | Should -Be (Join-Path $repoRoot 'CHANGELOG.md')
    $context.audit_directory | Should -Be $Script:AuditDir
    $context.benchmark_schema | Should -Be 'cucp.benchmark/v1'
  }
  It "does not pass a timing SLO with zero successful samples" {
    Mock Invoke-NativeHelper { return @{ExitCode=5; Json=@{status="ok"}} }
    $r = Invoke-CapturedLegacy { Invoke-MacroBenchmark -Rest @("--iters", "2") }
    $r.ExitCode | Should -Be 0
    $r.Json.schema | Should -Be 'cucp.benchmark/v1'
    @($r.Json.results).Count | Should -Be 4
    Assert-MockCalled Invoke-NativeHelper -Times 8 -Exactly
    $r.Json.slo_pass_count | Should -Be 0
    foreach ($row in $r.Json.results) {
      @($row.samples).Count | Should -Be 2
      $row.ok_count | Should -Be 0
      $row.slo_ok | Should -Be $false
      ($null -eq $row.p95_ms) | Should -Be $true
    }
  }
  It "uses nearest-rank p95, including the slowest of three successful observations" {
    $script:SampleIndex = 0
    Mock Invoke-NativeHelper {
      $script:SampleIndex++
      if (($script:SampleIndex % 3) -eq 0) { Start-Sleep -Milliseconds 25 }
      return @{ExitCode=0; Json=@{status="ok"}}
    }
    $r = Invoke-CapturedLegacy { Invoke-MacroBenchmark -Rest @("--iters", "3") }
    $r.ExitCode | Should -Be 0
    $r.Json.schema | Should -Be 'cucp.benchmark/v1'
    @($r.Json.results).Count | Should -Be 4
    Assert-MockCalled Invoke-NativeHelper -Times 12 -Exactly
    foreach ($row in $r.Json.results) {
      @($row.samples).Count | Should -Be 3
      $row.ok_count | Should -Be 3
      $row.p95_ms | Should -Be (($row.samples.ms | Measure-Object -Maximum).Maximum)
    }
  }
  It "does not call a single coordinate sample stable" {
    Mock Invoke-NativeHelper { return @{ExitCode=0; Json=@{status="ok"; recommended_point=@{x=0;y=0}; best=@{final_score=42}}} }
    $r = Invoke-CapturedLegacy { Invoke-MacroPrecisionValidate -Rest @("--x", "0", "--y", "0", "--samples", "1") }
    $r.ExitCode | Should -Be 2
    $r.Json.sample_count | Should -Be 1
    $r.Json.stable | Should -Be $false
    ($null -eq $r.Json.drift_max) | Should -Be $true
  }
  It "accepts actual hit-scan recommended_point fields at zero and negative coordinates" {
    Mock Invoke-NativeHelper { return @{ExitCode=0; Json=@{status="ok"; recommended_point=@{x=-30;y=0}; best=@{final_score=42}}} }
    $r = Invoke-CapturedLegacy { Invoke-MacroPrecisionValidate -Rest @("--x", "-30", "--y", "0", "--samples", "2") }
    $r.ExitCode | Should -Be 0
    $r.Json.sample_count | Should -Be 2
    $r.Json.stable | Should -Be $true
  }
}

Describe "legacy input delivery evidence" {
  It "rejects partial or zero native input delivery" {
    { [CucpLegacyInputTestNative]::Check(0) } | Should -Throw
    { [CucpLegacyInputTestNative]::Check(1) } | Should -Throw
  }
  It "accepts full native input delivery" {
    { [CucpLegacyInputTestNative]::Check(2) } | Should -Not -Throw
  }
}

Describe "legacy lifecycle boundary regressions" {
  BeforeAll {
    foreach ($name in @("Stop-HelperServer", "Invoke-MacroAppClose", "_Quote-NativeWindowsArgument")) {
      . ([scriptblock]::Create((Get-LegacyFunctionText -Ast $wrapperAst -Name $name)))
    }
    function _Read-LockSafely { return @{ pid=123; owner_user='test' } }
    function _Is-StaleLock { param($Lock) return $true }
    function _Try-Delete-Lock { }
    function Invoke-HelperPipe { param($Action, $ArgsHash, $TimeoutMs) throw 'Must be mocked' }
  }
  It "never kills a stale helper PID even with force" {
    Mock Stop-Process { throw 'Unrelated PID must not be killed' }
    Mock Invoke-HelperPipe { throw 'Stale pipe must not be contacted' }
    $result = Stop-HelperServer -Force
    $result.reason | Should -Be 'stale_lock_removed'
    Should -Invoke Stop-Process -Times 0
    Should -Invoke Invoke-HelperPipe -Times 0
  }
  It "does not promote graceful app close to kill" {
    $script:AllowLiveControl = $true
    $script:Brief = $true
    $fake = [pscustomobject]@{ MainWindowHandle=123; HasExited=$false; Killed=$false }
    $fake | Add-Member ScriptMethod CloseMainWindow { return $true }
    $fake | Add-Member ScriptMethod WaitForExit { param($Timeout) return $false }
    $fake | Add-Member ScriptMethod Kill { $this.Killed=$true }
    Mock Get-Process { return $fake }
    [void](Invoke-MacroAppClose -Rest @('--pid','123'))
    $fake.Killed | Should -BeFalse
  }
  It "rejects autostart changes from a read-only workflow" {
    $plan = _Build-WorkflowPlan -Rest @('--step','macro session install-autostart')
    $plan.steps[0].allowed | Should -BeFalse
    $plan.steps[0].live_required | Should -BeTrue
  }
  It "continues to allow read-only session diagnostics" {
    $plan = _Build-WorkflowPlan -Rest @('--step','macro session info')
    $plan.steps[0].allowed | Should -BeTrue
    $plan.steps[0].live_required | Should -BeFalse
  }
  It "quotes native argv without shell interpretation" {
    (_Quote-NativeWindowsArgument -Value '') | Should -Be '""'
    (_Quote-NativeWindowsArgument -Value 'a"b') | Should -Be '"a\"b"'
    (_Quote-NativeWindowsArgument -Value 'a\') | Should -Be '"a\\"'
    (_Quote-NativeWindowsArgument -Value 'x & calc.exe') | Should -Be '"x & calc.exe"'
  }
  It "removes cmd.exe from the optional vision launch path" {
    $text = Get-LegacyFunctionText -Ast $wrapperAst -Name '_Invoke-CodexVision'
    $text | Should -Not -Match '\$psi\.FileName\s*=\s*"cmd\.exe"'
    $text | Should -Match 'shell wrappers are disabled'
  }
}
