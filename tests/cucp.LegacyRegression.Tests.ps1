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
  It "does not pass a timing SLO with zero successful samples" {
    Mock Invoke-NativeHelper { return @{ExitCode=5; Json=@{status="ok"}} }
    $r = Invoke-CapturedLegacy { Invoke-MacroBenchmark -Rest @("--iters", "2") }
    $r.Json.slo_pass_count | Should -Be 0
    foreach ($row in $r.Json.results) {
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
    foreach ($row in $r.Json.results) {
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
