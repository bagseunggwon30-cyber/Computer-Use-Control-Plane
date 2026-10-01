"""Pure task-preset recipe/result qualification against the immutable PS 5.1 source.

Only pure definitions are imported. The original nested task query is replaced
at its AST extent by a captured-result stub. Workflow planning is pure and runs
against the original parser/classifier. No generated command is ever executed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = "bf895d3120dd5e145f360cb1c41e1d79a061d048"
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyTaskPreset.ContractTests"
KERNEL = ROOT / "pcucp-next/dotnet/PcuCp.LegacyTaskPreset/LegacyTaskPresetKernel.cs"


def original_source():
    return subprocess.check_output(["git", "show", f"{BASELINE_TREE}:scripts/cucp.ps1"], cwd=ROOT).decode("utf-8-sig")


def rest_cases():
    examples = {
        "document": ["--text", "hello"], "mail": ["--body", "hello"], "form-submit": ["--field", "Name=value"],
        "form": ["--submit"], "file-upload": ["--path", "C:\\test.txt"], "upload": ["--file", "C:\\test.txt"],
        "file-download": [], "download": [], "settings": [], "app-settings": [],
    }
    result = [[], ["--kind"], ["--kind", ""], ["--kind", "unknown"], ["--kind", " document "],
              ["--kind", "document"], ["--kind", "mail"], ["--kind", "form"], ["--kind", "upload"],
              ["--kind", "settings", "--field", "bad"], ["--kind", "settings", "--field", "=x"],
              ["--kind", "settings", "--field", " =x"], ["--kind", "settings", "--field", ""],
              ["--kind", "document", "--text", "", "--body", "fallback"],
              ["--kind", "document", "--text", "first", "--text", "second"],
              ["--kind", "document", "--text", "--save"],
              ["--kind", "", "--preset", "", "--type", "settings"],
              ["--kind", "document", "--text", "x", "--shortcut", "", "--shortcut", "ctrl+x"],
              ["--kind", "mail", "--send"], ["--kind", "mail", "--send-label", "Submit"],
              ["--kind", "mail", "--to", "a", "--subject", "b", "--body", "c", "--to-label", "Receiver", "--subject-label", "Title", "--body-label", "Content"],
              ["--kind", "form", "--field", "", "--field", "Name=x", "--submit"],
              ["--kind", "upload", "--path", "", "--file", "fallback"],
              ["--kind", "settings", "--field", "Name=", "--field", " A =b=c", "--click-label", "", "--save", "--apply"],
              ["--kind", "settings", "--field", "one=a", "--field", "invalid", "--field", "three=c"]]
    forwarding = ["--name", "n", "--settle-ms", "0", "--observe-match", "o", "--verify-match", "v",
                  "--verify-label-after-step", "after", "--verify-label-window", "win", "--verify-label-timeout-ms", "0",
                  "--verify-label-interval-ms", "1", "--retry-failed-step", "2", "--retry-delay-ms", "3",
                  "--precision-radius", "4", "--precision-step", "5", "--point-cache-ttl", "6",
                  "--observe-after-step", "--verify-after-step", "--retry-live-steps", "--enter", "--press-enter"]
    for kind, base in examples.items():
        for key in ("--kind", "--preset", "--type", "--KIND"):
            result.append([key, kind.upper() if key == "--KIND" else kind, *base])
        for options in (
            forwarding, ["--match", "A 'quoted' window", "--app", "custom", "--wait-title", "title"],
            ["--no-cdp", "--allow-cdp", "--precision-points", "--include-ocr", "--point-plan", "--clear-first"],
            ["--verify-label", "Done", "--verify-timeout-ms", "42"],
            ["--save", "--replace", "--shortcut", "ctrl+z", "--shortcut", "ctrl+x"],
            ["--send-label", "Send", "--submit-label", "Submit", "--save-label", "Save", "--apply-label", "Apply"],
            ["--label", "fallback", "--upload-label", "Upload 2", "--download-label", "Download 2", "--dialog-title", "Pick", "--dialog-timeout-ms", "9"],
            ["--cdp-page-match", "example", "--cdp-port", "9223", "--name", "", "--json-only"],
            ["--settings-label", "Preferences", "--field", "한글=a=b", "--click-label", "second", "--click-label", "third"],
            ["--name", "--step", "--field", "x=--step"],
        ):
            result.append(["--kind", kind, *base, *options])
    for value in ("", " ", "'", '"', "a'b", "$name; $(call)", "`n", "line1\nline2", "line1\r\nline2",
                  "한글😀", "C:\\Program Files\\file.txt", "a\x00b", "a\u00a0b", "a\u2003b", "--step", "tail\n", "-AllowLiveControl", "-CucpArgs"):
        result.extend([
            ["--kind", "document", "--text", value], ["--kind", "upload", "--path", value],
            ["--kind", "form", "--field", "Label=" + value], ["--kind", "settings", "--field", "Label=" + value],
        ])
    return result


def preset_cases():
    cases = []
    for rest in rest_cases():
        cases.append({"operation": "preset", "args": {"rest": rest, "elapsed_ms": 37},
                      "task_result": {"exit": 0, "raw": "unused", "json": {"schema": "captured", "safe_to_run": True, "errors": []}}})
    for plan in (None, {}, {"safe_to_run": False}, {"safe_to_run": True, "requires_sensitive_confirmation": True},
                 {"safe_to_run": False, "errors": [{"code": "first"}, {"code": "second"}], "safety": {"level": "critical"}},
                 {"SAFE_TO_RUN": True}, {"safe_to_run": "false"}, {"safe_to_run": ""}, {"safe_to_run": 0},
                 {"safe_to_run": []}, {"safe_to_run": [False]}, {"safe_to_run": [False, False]}):
        for kind, extra in (("document", ["--text", "x"]), ("mail", ["--send"]), ("settings", []), ("form", ["--submit"])):
            cases.append({"operation": "preset", "args": {"rest": ["--kind", kind, *extra], "elapsed_ms": 0},
                          "task_result": {"exit": 2, "raw": "error\n한글", "json": plan}, "workflow_result": plan})
    return cases


def helper_cases():
    values = [None, "", "abc", "a b", "C:\\tmp\\file", "a'b", "'", '"', "$env:PATH", "a; b", "한글", "x\n", "\n", "x\x00y"]
    cases = [{"operation": "quote", "args": {"value": value}} for value in values]
    commands = [None, [], [None], [""], ["macro", "windows"], ["macro", ["a", "b"]], [["a", "b"]],
                [[[]]], ["macro", [None, "", "a b"]], ["macro", [["a", "b"], ["c"]]],
                ["macro", [["a", None, "b"], []]], ["macro", True, False, 0, -1, 1.5], "singleton", ""]
    return cases + [{"operation": "helpers", "args": {"command": command}} for command in commands]


class PresetFixtureTests(unittest.TestCase):
    def test_broad_fixture_coverage(self):
        self.assertGreater(len(preset_cases()), 250)
        self.assertGreater(len(helper_cases()), 25)
        self.assertTrue(any("\x00" in token for rest in rest_cases() for token in rest))

    def test_kernel_has_no_query_execution_dependency(self):
        text = KERNEL.read_text(encoding="utf-8")
        for forbidden in ("Process.Start", "ProcessStartInfo", "System.Management.Automation", "DllImport", "File.Read", "HttpClient"):
            self.assertNotIn(forbidden, text)
        self.assertNotEqual(KERNEL.parent.name, "PcuCp.NativeHost")

    def test_pinned_original_has_expected_query_boundaries(self):
        source = original_source()
        body = source[source.index("function Invoke-MacroTaskPreset {"):source.index("function Invoke-MacroTaskPlan {")]
        self.assertEqual(body.count("$planResult = _PresetInvokeJson"), 1)
        self.assertEqual(body.count("_Build-WorkflowPlan -Rest $workflowPlanRest"), 1)
        self.assertEqual(body.count("& powershell"), 1)


@unittest.skipUnless(sys.platform == "win32", "Requires original Windows PowerShell 5.1 behavior")
class PresetWindowsParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotnet = shutil.which("dotnet")
        cls.powershell = shutil.which("powershell.exe")
        if not cls.dotnet or not cls.powershell:
            raise RuntimeError("SDK and Windows PowerShell 5.1 required")
        result = subprocess.run([cls.dotnet, "build", str(PROJECT), "-c", "Release"], cwd=ROOT, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        cls.runner = PROJECT / "bin/Release/net8.0/PcuCp.LegacyTaskPreset.ContractTests.dll"

    def differential(self, cases):
        with tempfile.TemporaryDirectory(prefix="CUCP preset 한글 ") as temp:
            folder = Path(temp)
            source, inputs, runner = folder / "original.ps1", folder / "cases.json", folder / "runner.ps1"
            source.write_text(original_source(), encoding="utf-8-sig")
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8-sig")
            runner.write_text(PS_RUNNER, encoding="utf-8-sig")
            before = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(runner),
                                     "-SourcePath", str(source), "-InputPath", str(inputs)], capture_output=True, timeout=120)
            self.assertEqual(before.returncode, 0, before.stderr.decode(errors="replace"))
            baseline = json.loads(before.stdout.decode("utf-8-sig"))
            fixtures, expected = [], []
            for case, result in zip(cases, baseline):
                if case.get("brief"):
                    continue  # Console formatting is checked against the actual adapter below.
                if case["operation"] != "preset":
                    fixtures.append(case); expected.append(result); continue
                fixtures.append({"operation": "prepare", "args": {"rest": case["args"]["rest"]}})
                expected.append(result if result.get("threw") else result["prepared"])
                if not result.get("threw"):
                    fixtures.append({"operation": "complete", "args": {**case["args"], "captured_query_result": result["captured"]}})
                    expected.append(result["payload"])
            self.assertEqual(len(baseline), len(cases))
            after = subprocess.run([self.dotnet, str(self.runner), "--fixtures"], input=json.dumps(fixtures, ensure_ascii=True).encode(),
                                   capture_output=True, timeout=60)
            self.assertEqual(after.returncode, 0, after.stderr.decode(errors="replace"))
            actual = json.loads(after.stdout.decode("utf-8-sig"))
            self.assertEqual(len(actual), len(expected))
            for case, old, new in zip(fixtures, expected, actual):
                with self.subTest(fixture=case):
                    self.assertEqual(new, old)
            print(f"Verified {len(fixtures)} exact task-preset/helper comparisons from {len(cases)} original cases")
            if os.environ.get("CUCP_NATIVE_TEST_HOST") and any(case["operation"] == "preset" for case in cases):
                # Use the entire current function and current native stdin bridge.
                # Only the original child planning-query acquisition is stubbed.
                bridged = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(runner),
                    "-SourcePath", str(ROOT / "scripts/cucp.ps1"), "-InputPath", str(inputs), "-Adapter"],
                    env={**os.environ, "CUCP_NATIVE_HOST": os.environ["CUCP_NATIVE_TEST_HOST"]},
                    capture_output=True, timeout=240)
                self.assertEqual(bridged.returncode, 0, bridged.stderr.decode(errors="replace"))
                actual_adapter = json.loads(bridged.stdout.decode("utf-8-sig"))
                self.assertEqual(len(actual_adapter), len(baseline))
                for case, old, new in zip(cases, baseline, actual_adapter):
                    with self.subTest(actual_adapter=case):
                        self.assertEqual(new, old)
                print(f"Verified {len(cases)} complete actual PowerShell task-preset adapter results, queries, and exit codes")

    def test_child_script_parameter_binding_characterization(self):
        # This target contains only the original parameter block/delimiter logic
        # and a JSON echo. It cannot query windows, dispatch macros, or act.
        values = ["plain", "-AllowLiveControl", "-AllowLive", "-CucpArgs", "-Quiet", "-Brief", "-CacheSeconds", "-InvokeTimeoutMs", "--out", "--"]
        with tempfile.TemporaryDirectory(prefix="CUCP binding 한글 ") as temp:
            folder = Path(temp)
            source, target, inputs, runner = (folder / name for name in ("original.ps1", "echo.ps1", "values.json", "binding.ps1"))
            original = original_source()
            source.write_text(original, encoding="utf-8-sig")
            header = original[:original.index("# ============================================================================")]
            target.write_text(header + r'''
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
[Console]::Out.WriteLine((@{live=[bool]$AllowLiveControl;quiet=[bool]$Quiet;brief=[bool]$Brief;args=@($CucpArgs)} | ConvertTo-Json -Depth 10 -Compress))
''', encoding="utf-8-sig")
            inputs.write_text(json.dumps(values), encoding="utf-8-sig")
            runner.write_text(BINDING_RUNNER, encoding="utf-8-sig")
            result = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(runner),
                "-SourcePath", str(source), "-CurrentPath", str(ROOT / "scripts/cucp.ps1"), "-TargetPath", str(target), "-InputPath", str(inputs)], capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            observations = json.loads(result.stdout.decode("utf-8-sig"))
            print("SCRIPT_BINDING_OBSERVATIONS: " + json.dumps(observations, ensure_ascii=True))
            self.assertEqual(len(observations), 2 * len(values))
            legacy = {item["value"]: item["result"] for item in observations if item["mode"] == "legacy"}
            self.assertTrue(legacy["-AllowLiveControl"]["json"]["live"], "The suspected original binding seam did not reproduce")
            for item in observations:
                if item["mode"] != "delimited":
                    continue
                with self.subTest(binding=item["value"]):
                    self.assertNotIn("threw", item["result"], item)
                    self.assertEqual(item["result"]["exit"], 0, item)
                    echo = item["result"]["json"]
                    self.assertFalse(echo["live"], item)
                    self.assertFalse(echo["brief"], item)
                    self.assertTrue(echo["quiet"], item)
                    self.assertEqual(echo["args"], ["macro", "task-plan", "--type-text", item["value"], "--json-only"])
            print("Original native -File binding reproduced live=True for data '-AllowLiveControl'; fixed -Quiet -- preserved all 10 control-like values with live=False")

    def test_original_recipe_and_complete_payload_parity(self):
        self.differential(preset_cases())

    def test_original_quoting_and_one_level_argv_helpers(self):
        self.differential(helper_cases())

    @unittest.skipUnless(os.environ.get("CUCP_NATIVE_TEST_HOST"), "Actual adapter requires the built native host")
    def test_original_brief_and_json_only_formatting(self):
        cases = []
        for rest in (["--kind", "document", "--text", "hello"], ["--kind", "mail", "--send"],
                     ["--kind", "settings"], ["--kind", "form", "--submit"]):
            for safe in (True, False):
                for json_only in (False, True):
                    cases.append({"operation": "preset", "brief": True,
                        "args": {"rest": rest + (["--json-only"] if json_only else []), "elapsed_ms": 37},
                        "task_result": {"exit": 2, "raw": "preserved", "json": {"safe_to_run": safe}},
                        "workflow_result": {"safe_to_run": safe}})
        self.differential(cases)


PS_RUNNER = r'''
param([string]$SourcePath, [string]$InputPath, [switch]$Adapter)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected Windows PowerShell 5.1' }
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$Brief=$false
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source parse failure' }
$names=@('_Read-OptValue','_Read-AllOptValues','_Read-Switch','_TaskPlan-QuoteToken','_TaskPlan-StepString','_TaskPlan-UnwrapCommand','_Safety-Truncate','_Classify-SafetyFromText','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan','Invoke-MacroTaskPreset')
if ($Adapter) { $names=@('_Invoke-LegacyCompatibility')+$names }
foreach ($name in $names) {
  $found=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($found.Count -ne 1) { throw "Expected one baseline function: $name" }
  $text=$found[0].Extent.Text
  if ($name -eq 'Invoke-MacroTaskPreset') {
    $query=@($found[0].FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq '_PresetInvokeJson'},$true))
    if ($query.Count -ne 1) { throw 'Expected exactly one nested child query' }
    $start=$query[0].Extent.StartOffset-$found[0].Extent.StartOffset
    $text=$text.Remove($start,$query[0].Extent.Text.Length).Insert($start,'function _PresetInvokeJson { param([string[]]$ChildArgs) $script:Query=@{kind="task_plan";argv=@($ChildArgs);rest=$null}; return $script:Case.task_result }')
    if ($text.Contains('& powershell')) { throw 'External query was not fully stubbed' }
  }
  . ([scriptblock]::Create($text))
}
$script:OriginalWorkflow=(Get-Command _Build-WorkflowPlan).ScriptBlock
function _Build-WorkflowPlan {
  param([string[]]$Rest)
  $script:Query=@{kind='workflow_plan';argv=$null;rest=@($Rest)}
  $script:RecipeSteps=if ($Adapter) { @($preset.workflow_steps) } else { @($workflowSteps) }
  $plan=if ($script:Case.PSObject.Properties.Name -contains 'workflow_result') { $script:Case.workflow_result } else { & $script:OriginalWorkflow -Rest $Rest }
  $script:WorkflowPlan=$plan
  return $plan
}
$results=New-Object Collections.ArrayList
foreach ($script:Case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  try {
    if ($script:Case.operation -eq 'quote') { $value=@{value=(_TaskPlan-QuoteToken -Value $script:Case.args.value)} }
    elseif ($script:Case.operation -eq 'helpers') {
      $value=@{step=(_TaskPlan-StepString -Command $script:Case.args.command);unwrapped=@(_TaskPlan-UnwrapCommand -Command $script:Case.args.command)}
    }
    else {
      $Brief=[bool]$script:Case.brief
      $script:Query=$null; $script:WorkflowPlan=$null; $script:RecipeSteps=@()
      $writer=New-Object IO.StringWriter
      $saved=[Console]::Out
      try { [Console]::SetOut($writer); $exit=Invoke-MacroTaskPreset -Rest $script:Case.args.rest }
      finally { [Console]::SetOut($saved) }
      if ($Brief -and -not (_Read-Switch -Rest $script:Case.args.rest -Name '--json-only')) {
        $output=$writer.ToString()
        if ($script:Query.kind -eq 'task_plan') { $output=[regex]::Replace($output,'elapsed_ms=\d+',('elapsed_ms='+$script:Case.args.elapsed_ms)) }
        [void]$results.Add(@{output=$output;return_code=[int]$exit;query=$script:Query})
        continue
      }
      $payload=$writer.ToString() | ConvertFrom-Json
      $mode=if ($payload.PSObject.Properties.Name -contains 'mode') { $payload.mode } else { 'task' }
      if ($mode -eq 'task') { $payload.elapsed_ms=[int]$script:Case.args.elapsed_ms }
      $captured=if ($mode -eq 'task') { $script:Case.task_result } else { @{workflow_plan=$script:WorkflowPlan} }
      $prepared=@{schema='cucp.task-preset-preparation/v1';kind=$payload.kind;mode=$mode;queries=@($script:Query);notes=@($payload.notes);extra_commands=@();workflow_steps=@()}
      if ($mode -eq 'workflow') {
        $prepared.extra_commands=@($payload.extra_commands)
        $prepared.workflow_steps=@($script:RecipeSteps)
      }
      $value=@{prepared=$prepared;payload=$payload;captured=$captured;return_code=[int]$exit}
    }
  } catch { $value=@{threw=$true;error='invalid_arguments';message=$_.Exception.Message} }
  [void]$results.Add($value)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 64 -Compress))
'''


BINDING_RUNNER = r'''
param([string]$SourcePath, [string]$CurrentPath, [string]$TargetPath, [string]$InputPath)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected Windows PowerShell 5.1' }
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
$preset=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-MacroTaskPreset'},$true))
$query=@($preset[0].FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq '_PresetInvokeJson'},$true))
if ($errors.Count -or $preset.Count -ne 1 -or $query.Count -ne 1) { throw 'Expected exact original query definition' }
$script:FixtureTargetPath=$TargetPath
$text=$query[0].Extent.Text.Replace('$PSCommandPath','$script:FixtureTargetPath')
$current=[Management.Automation.Language.Parser]::ParseFile($CurrentPath,[ref]$tokens,[ref]$errors)
$currentPreset=@($current.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-MacroTaskPreset'},$true))
$currentQuery=@($currentPreset[0].FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq '_PresetInvokeJson'},$true))
if ($errors.Count -or $currentPreset.Count -ne 1 -or $currentQuery.Count -ne 1) { throw 'Expected exact current query definition' }
$delimited=$currentQuery[0].Extent.Text.Replace('$PSCommandPath','$script:FixtureTargetPath')
if (-not $delimited.Contains("-Quiet '--' @macroArgs")) { throw 'Actual adapter is missing the fixed authority delimiter' }
$results=New-Object Collections.ArrayList
foreach ($mode in @('legacy','delimited')) {
  $definition=if ($mode -eq 'legacy') { $text } else { $delimited }
  . ([scriptblock]::Create($definition))
  foreach ($value in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
    try { $result=_PresetInvokeJson -ChildArgs @('-Quiet','macro','task-plan','--type-text',"$value",'--json-only') }
    catch { $result=@{threw=$true;message=$_.Exception.Message} }
    [void]$results.Add(@{mode=$mode;value=$value;result=$result})
  }
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 20 -Compress))
'''


if __name__ == "__main__":
    unittest.main()
