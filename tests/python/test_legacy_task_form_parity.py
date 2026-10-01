"""Candidate task/form assembly against pinned original Windows PowerShell 5.1.

Only selected pure definitions run. Nested acquisition functions are replaced at
their AST extents with ordered captured replies. Generated commands never run.
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
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyTaskForm.ContractTests"
KERNEL = ROOT / "pcucp-next/dotnet/PcuCp.LegacyTaskForm/LegacyTaskFormKernel.cs"


def original_source():
    return subprocess.check_output(["git", "show", f"{BASELINE_TREE}:scripts/cucp.ps1"], cwd=ROOT).decode("utf-8-sig")


def plan_cases():
    result = []

    def add(kind, rest, **kw):
        result.append({"kind": kind, "rest": rest, "elapsed_ms": 37, **kw})

    task_inputs = [[], ["--app"], ["--app", ""], ["--app", "app"], ["--wait-title", "title"],
                   ["--verify-label", "done"], ["--field", "Name=x"], ["--send-label", "Send"],
                   ["--click-label", ""], ["--type-text", ""], ["--text", "fallback"],
                   ["--shortcut", ""], ["--shortcut", " "], ["--pre-shortcut", ""],
                   ["--app", "", "--open-app", "alias", "--wait-title", "", "--verify-window", "alias"],
                   ["--type-text", "", "--text", "ignored", "--type-text", "second", "--clear-first"],
                   ["--type-text", "a", "--type-text", "b", "--match", "window", "--clear-first", "--press-enter"],
                   ["--keys", "F1", "--shortcut", "F2", "--keys", "F3", "--shortcut", "F4"],
                   ["--app", "first", "--app", "last", "--name", ""],
                   ["--app", "--wait-title", "title"], ["--TYPE-TEXT", "한글", "--ENTER"]]
    form_inputs = [[], ["--field"], ["--send-label", ""], ["--field", ""], ["--field", "bad"],
                   ["--field", "=x"], ["--field", " =x"], ["--field", " A ="], ["--field", "A=b=c"],
                   ["--field", "A=x", "--send-label", "Send"], ["--field", "bad", "--field", "Name=value", "--field", " =x", "--field", "Age=1", "--send-label", "Send"],
                   ["--field", "A=x", "--field", "A=y"], ["--send-label", "--field", "A=x"],
                   ["--FIELD", "Name=x", "--SEND-LABEL", "Send"]]
    for rest in task_inputs:
        add("task", rest)
    for rest in form_inputs:
        add("form", rest)
    for rest in (["--type-text", None, "--text", "fallback"], [None, "--type-text", ""],
                 ["--type-text", None, "--type-text", "second", "--clear-first"],
                 ["--field", None], ["--click-label", None], ["--shortcut", None],
                 ["--app", None, "--open-app", "fallback"]):
        add("task", rest)
    for rest in (["--field", None], ["--field", None, "--field", "Name=x", "--send-label", "Send"],
                 [None, "--field", "A=x"], ["--send-label", None, "--field", "A=x"]):
        add("form", rest)
    forwarding = ["--match", "window", "--window", "ignored", "--allow-cdp", "--no-cdp", "--cdp-page-match", "page", "--cdp-port", "9223", "--clear-first", "--include-ocr", "--point-plan", "--precision-radius", "4", "--precision-step", "2", "--cache-ttl", "3"]
    run_options = ["--name", "name", "--settle-ms", "0", "--observe-after-step", "--verify-after-step", "--observe-match", "", "--verify-match", "v", "--verify-label-after-step", "", "--verify-after-label", "after", "--verify-label-window", "vw", "--verify-label-timeout-ms", "1", "--verify-label-interval-ms", "2", "--retry-failed-step", "3", "--retry-delay-ms", "4", "--retry-live-steps"]
    for options in (forwarding, run_options, ["--match", "", "--window", "fallback"],
                    ["--point-cache-ttl", "", "--cache-ttl", "fallback"], ["--point-cache-ttl", "first", "--cache-ttl", "last"],
                    ["--precision-points", "--point-plan", "--allow-cdp", "--allow-cdp"],
                    ["--settle-ms", "", "--observe-match", "", "--verify-label-window", "", "--retry-delay-ms", ""],
                    ["--observe-after-step"], ["--verify-after-step"], ["--app-args", "quoted args"]):
        add("task", ["--app", "app", "--wait-title", "title", "--pre-shortcut", "ctrl+a", "--type-text", "x", "--type-text", "", "--field", "Name=x", "--click-label", "one", "--click-label", "two", "--shortcut", "ctrl+s", "--keys", "F4", "--verify-label", "done", *options])
        add("form", ["--field", "A=x", "--field", "B=", "--send-label", "Send", *options])
    for text in ("", " ", "'", '"', "a'b", "$name; $(call)", "`n", "line1\nline2", "line1\r\nline2", "한글😀", "C:\\Program Files\\file.txt", "a\x00b", "a\u00a0b", "a\u2003b", "--step", "tail\n", "-AllowLiveControl", "-CucpArgs", "-Brief", "--"):
        add("task", ["--type-text", text, "--name", text, "--click-label", text])
        add("form", ["--field", "Label=" + text, "--send-label", text])
    for culture in ("en-US", "ko-KR", "tr-TR", ""):
        for number in ("", " ", "\t", "\r\n", "\u00a0", "0", "-1", "+1", "  2  ", "1.5", "2.5", "-1.5", "1e2", "1,000", "1,5", "0x10", "0xffffffff", "0x100000000", "-0x1", "1kb", "NaN", "Infinity", "2147483647", "2147483648", "-2147483648", "-2147483649", "2147483647.4", "2147483647.5", "2147483648.0", "-2147483648.6", "1e400", "bad", "--verify-label"):
            add("task", ["--wait-title", "title", "--wait-timeout-ms", number, "--verify-label", "done", "--verify-timeout-ms", number], culture=culture)
        for rest in (["--wait-timeout-ms", "bad"], ["--verify-timeout-ms", "bad"], ["--app", "app", "--verify-timeout-ms", "bad"]):
            add("task", rest, culture=culture)
    plans = [None, {}, {"safe_to_act": False}, {"safe_to_act": True}, {"SAFE_TO_ACT": True}, {"safe_to_act": "false"}, {"safe_to_act": ""}, {"safe_to_act": 0}, {"safe_to_act": []}, {"safe_to_act": [False]}, {"safe_to_act": [False, False]}, {"safe_to_act": {}},
             {"safe_to_act": False, "unsafe_steps": [{"index": 3}], "errors": [{"code": "embedded"}], "recommended_command": ["macro", "click", "--x", "1", "--y", "2"], "best_route": "unsafe"}]
    for plan in plans:
        reply = {"exit": 9, "raw": "captured\n한글", "json": plan}
        add("form", ["--field", "A=x", "--field", "bad", "--send-label", "Send"], replies=[reply, reply])
        add("task", ["--field", "A=x", "--click-label", "one", "--click-label", "two"], replies=[reply, reply, reply])
    commands = [None, [], [None], [""], "singleton", "", ["macro", "windows"], [["macro", "windows"]], [[[]]],
                ["macro", [None, "", "a b"]], [["macro", [["a", "b"], ["c"]]]], ["macro", True, False, 0, -1, 1.5],
                ["macro", [["a", None, "b"], []]], ["macro", "a'b", "한글😀", "line\nnext"],
                [[], []], [None, None], ["single"], [1], [False], [[None]], [[], "x"], [["a"], ["b"]]]
    for command in commands:
        reply = {"exit": 5, "raw": "unused", "json": {"safe_to_act": True, "best_route": "captured", "recommended_command": command}}
        add("form", ["--send-label", "Send"], replies=[reply])
        add("task", ["--click-label", "Click"], replies=[reply])
        form_reply = {"exit": 7, "raw": "unused", "json": {"safe_to_act": True, "command_plan": [{"label": "Name", "route": "captured", "command": command}]}}
        add("task", ["--field", "Name=x"], replies=[form_reply])
    for route in ([], [None], ["route"], [[]], [["route"]], ["first", "second"]):
        reply = {"exit": 7, "raw": "unused", "json": {"safe_to_act": True, "best_route": route, "recommended_command": ["macro", "windows"]}}
        add("form", ["--send-label", "Send"], replies=[reply])
    for plan in (None, {}, {"safe_to_run": False}, {"safe_to_run": True, "step_count": "2.5", "live_step_count": "1e1", "sensitive_step_count": None, "requires_sensitive_confirmation": "false"}, {"safe_to_run": [False, False], "step_count": 1, "errors": ["kept"], "safety": {"risk": "high"}}):
        add("task", ["--type-text", "x"], workflow_result=plan)
    for kind, rest in (("task", ["--field", "A=x", "--click-label", "one", "--click-label", "two"]), ("form", ["--field", "A=x", "--field", "B=y", "--send-label", "Send"])):
        for index in range(3):
            add(kind, rest, throws_at=index)
        for safe in (True, False):
            for json_only in (True, False):
                reply = {"exit": 2, "raw": "diagnostic", "json": {"safe_to_act": safe, "command_plan": [], "recommended_command": ["macro", "windows"]}}
                add(kind, rest + (["--json-only"] if json_only else []), replies=[reply] * 3, brief=True)
    return result


class TaskFormFixtureTests(unittest.TestCase):
    def test_broad_and_bounded_corpus(self):
        self.assertGreater(len(plan_cases()), 300)
        self.assertTrue(any(case.get("throws_at") == 2 for case in plan_cases()))
        self.assertTrue(any(isinstance(token, str) and "\x00" in token for case in plan_cases() for token in case["rest"]))

    def test_kernel_is_pure_and_excluded_from_native_wildcard(self):
        source = KERNEL.read_text(encoding="utf-8")
        for forbidden in ("Process.Start", "ProcessStartInfo", "System.Management.Automation", "DllImport", "File.Read", "HttpClient"):
            self.assertNotIn(forbidden, source)
        self.assertNotEqual(KERNEL.parent.name, "PcuCp.NativeHost")

    def test_pinned_original_boundaries(self):
        source = original_source()
        task = source[source.index("function Invoke-MacroTaskPlan {"):source.index("function Invoke-MacroTaskRun {")]
        form = source[source.index("function Invoke-MacroFormPlan {"):source.index("function Invoke-MacroFormRun {")]
        self.assertEqual(task.count("& powershell"), 1)
        self.assertEqual(form.count("& powershell"), 1)
        self.assertEqual(task.count("_Build-WorkflowPlan -Rest $wfArgs"), 1)
        self.assertEqual(task.count("_InvokeTaskChildJson -ChildArgs"), 2)
        self.assertEqual(form.count("_InvokeChildSmartPlanJson -PlanArgs"), 2)


@unittest.skipUnless(sys.platform == "win32", "Requires original Windows PowerShell 5.1 behavior")
class TaskFormWindowsParityTests(unittest.TestCase):
    maxDiff = None
    @classmethod
    def setUpClass(cls):
        cls.dotnet = shutil.which("dotnet")
        cls.powershell = shutil.which("powershell.exe")
        if not cls.dotnet or not cls.powershell:
            raise RuntimeError("SDK and Windows PowerShell 5.1 required")
        result = subprocess.run([cls.dotnet, "build", str(PROJECT), "-c", "Release"], cwd=ROOT, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        cls.runner = PROJECT / "bin/Release/net8.0/PcuCp.LegacyTaskForm.ContractTests.dll"

    def test_original_queries_assembly_payload_and_console(self):
        cases = plan_cases()
        with tempfile.TemporaryDirectory(prefix="CUCP task form 한글 ") as temp:
            folder = Path(temp)
            source, inputs, runner = folder / "original.ps1", folder / "cases.json", folder / "runner.ps1"
            source.write_text(original_source(), encoding="utf-8-sig")
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8-sig")
            runner.write_text(PS_RUNNER, encoding="utf-8-sig")
            before = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(runner), "-SourcePath", str(source), "-InputPath", str(inputs)], capture_output=True, timeout=180)
            self.assertEqual(before.returncode, 0, before.stderr.decode(errors="replace"))
            baseline = json.loads(before.stdout.decode("utf-8-sig"))
            self.assertEqual(len(baseline), len(cases))
            for case, original in zip(cases, baseline):
                if None in case["rest"]:
                    self.assertEqual(original["bound_rest"], ["" if item is None else item for item in case["rest"]], case)
                    self.assertTrue(all(isinstance(item, str) for query in original["queries"] for item in query["argv"]), case)
            print("TASK_FORM_NULL_REST_BINDING_OBSERVATIONS: " + json.dumps([
                {"kind": case["kind"], "input_rest": case["rest"], "bound_rest": original["bound_rest"], "queries": original["queries"]}
                for case, original in zip(cases, baseline) if None in case["rest"]
            ], ensure_ascii=True))
            fixtures, expected, origins, completed = [], [], [], []
            for index, (case, original) in enumerate(zip(cases, baseline)):
                # Use exactly what the original [string[]] parameter binder
                # supplied. Both null preservation and normalization remain
                # visible in bound_rest for the separate adapter comparison.
                prepare = {"operation": "prepare-" + case["kind"], "args": {"rest": original["bound_rest"]}}
                if "throws_at" in case:
                    self.assertTrue(original["threw"], case)
                    self.assertEqual(original["message"], "captured acquisition failure", case)
                    self.assertEqual(len(original["queries"]), case["throws_at"] + 1, case)
                    # A callback failure is never represented as a successful captured reply.
                    continue
                fixtures.append(prepare); origins.append(case)
                if original.get("threw"):
                    expected.append({key: original[key] for key in ("threw", "error", "message")})
                    continue
                expected.append({"schema": "cucp." + case["kind"] + "-plan-preparation/v1", "queries": original["queries"]})
                if None in case["rest"]:
                    fixtures.append({"operation": "prepare-" + case["kind"], "args": {"rest": case["rest"]}})
                    origins.append(case); expected.append(expected[-1])
                args = {"rest": original["bound_rest"], "captured_query_results": original["captured"]}
                if case["kind"] == "task":
                    fixtures.append({"operation": "assemble-task", "args": args}); origins.append(case); expected.append(original["assembly"])
                complete_args = {**args, "elapsed_ms": case["elapsed_ms"]}
                if case["kind"] == "task":
                    complete_args["captured_workflow_plan"] = original["workflow_plan"]
                fixtures.append({"operation": "complete-" + case["kind"], "args": complete_args}); origins.append(case); expected.append(original["payload"])
                completed.append((index, len(fixtures) - 1))
            after = subprocess.run([self.dotnet, str(self.runner), "--fixtures"], input=json.dumps(fixtures, ensure_ascii=True).encode(), capture_output=True, timeout=120)
            self.assertEqual(after.returncode, 0, after.stderr.decode(errors="replace"))
            actual = json.loads(after.stdout.decode("utf-8-sig"))
            self.assertEqual(len(actual), len(expected))
            for case, fixture, old, new in zip(origins, fixtures, expected, actual):
                with self.subTest(case=case, operation=fixture["operation"]):
                    self.assertEqual(new, old)
            # Render candidate payloads through PS5.1's unchanged presentation
            # boundary, including exact JSON serialization depth/order/newline.
            successful = [(i, j) for i, j in completed if not actual[j].get("threw")]
            rendered = [{"case": cases[i], "payload": actual[j]} for i, j in successful]
            render_inputs, render_script = folder / "render.json", folder / "render.ps1"
            render_inputs.write_text(json.dumps(rendered, ensure_ascii=True), encoding="utf-8-sig")
            render_script.write_text(PS_RENDER, encoding="utf-8-sig")
            rendered_output = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(render_script), "-InputPath", str(render_inputs)], capture_output=True, timeout=120)
            self.assertEqual(rendered_output.returncode, 0, rendered_output.stderr.decode(errors="replace"))
            rendered_results = json.loads(rendered_output.stdout.decode("utf-8-sig"))
            self.assertEqual(len(rendered_results), len(rendered))
            for (index, _), console in zip(successful, rendered_results):
                with self.subTest(console_case=cases[index]):
                    self.assertEqual(console["output"], baseline[index]["output"])
                    self.assertEqual(console["return_code"], baseline[index]["return_code"])
            print(f"Compared {len(fixtures)} task/form preparation, assembly and payload results from {len(cases)} original cases; exact console and exit assertions determine success")
            if os.environ.get("CUCP_TASK_FORM_TEST_HOST"):
                bridged = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(runner), "-SourcePath", str(source), "-InputPath", str(inputs), "-AdapterPath", str(ROOT / "scripts/cucp.ps1")], env={**os.environ, "CUCP_NATIVE_HOST": os.environ["CUCP_TASK_FORM_TEST_HOST"]}, capture_output=True, timeout=300)
                self.assertEqual(bridged.returncode, 0, bridged.stderr.decode(errors="replace"))
                adapter_results = json.loads(bridged.stdout.decode("utf-8-sig"))
                self.assertEqual(len(adapter_results), len(baseline))
                for case, old, new in zip(cases, baseline, adapter_results):
                    with self.subTest(adapter=case):
                        # Internal assembly is independently qualified above;
                        # adapters may no longer expose those original locals.
                        self.assertEqual({k: v for k, v in new.items() if k != "assembly"}, {k: v for k, v in old.items() if k != "assembly"})


PS_RUNNER = r'''
param([string]$SourcePath,[string]$InputPath,[string]$AdapterPath)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected Windows PowerShell 5.1' }
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source parse failure' }
function Import-Definition {
  param($Tree,[string]$Name)
  $found=@($Tree.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $Name},$true))
  if ($found.Count -ne 1) { throw "Expected one function: $Name" }
  $text=$found[0].Extent.Text
  if ($Name -in @('Invoke-MacroTaskPlan','Invoke-MacroFormPlan')) {
    $queryName=if ($Name -eq 'Invoke-MacroTaskPlan') {'_InvokeTaskChildJson'} else {'_InvokeChildSmartPlanJson'}
    $query=@($found[0].FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $queryName},$true))
    if ($query.Count -ne 1) { throw 'Expected exactly one nested acquisition function' }
    $replacement=if ($Name -eq 'Invoke-MacroTaskPlan') {
      'function _InvokeTaskChildJson { param([string[]]$ChildArgs) return (Capture-PlanReply -Argv $ChildArgs) }'
    } else {
      'function _InvokeChildSmartPlanJson { param([string[]]$PlanArgs) return (Capture-PlanReply -Argv (@("-Quiet","macro","smart-plan") + @($PlanArgs) + @("--json-only"))) }'
    }
    $offset=$query[0].Extent.StartOffset-$found[0].Extent.StartOffset
    $text=$text.Remove($offset,$query[0].Extent.Text.Length).Insert($offset,$replacement)
    if ($text.Contains('& powershell')) { throw 'Child invocation survived acquisition interception' }
    $text=$text.Replace('[Console]::Out.WriteLine(', 'Write-TaskFormConsole (')
    $text=$text.Replace('param([string[]]$Rest)', 'param([string[]]$Rest); $script:BoundRest=@($Rest)')
  }
  return $text
}
foreach ($name in @('_Read-OptValue','_Read-AllOptValues','_Read-Switch','_TaskPlan-QuoteToken','_TaskPlan-StepString','_TaskPlan-UnwrapCommand','_Safety-Truncate','_Classify-SafetyFromText','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan','Invoke-MacroTaskPlan','Invoke-MacroFormPlan')) {
  . ([scriptblock]::Create((Import-Definition -Tree $ast -Name $name)))
}
$script:OriginalWorkflow=(Get-Command _Build-WorkflowPlan).ScriptBlock
if ($AdapterPath) {
  $current=[Management.Automation.Language.Parser]::ParseFile($AdapterPath,[ref]$tokens,[ref]$errors)
  if ($errors.Count) { throw 'Current adapter parse failure' }
  foreach ($name in @('_Invoke-LegacyCompatibility','Invoke-MacroTaskPlan','Invoke-MacroFormPlan')) {
    . ([scriptblock]::Create((Import-Definition -Tree $current -Name $name)))
  }
}
function Capture-PlanReply {
  param([string[]]$Argv)
  $kind=if ($Argv[2] -eq 'form-plan') {'form_plan'} else {'smart_plan'}
  [void]$script:Queries.Add([pscustomobject]@{kind=$kind;argv=@($Argv)})
  $index=$script:Queries.Count-1
  if ($script:Case.PSObject.Properties.Name -contains 'throws_at' -and [int]$script:Case.throws_at -eq $index) { throw 'captured acquisition failure' }
  if ($script:Case.PSObject.Properties.Name -contains 'replies') { $reply=$script:Case.replies[$index] }
  elseif ($kind -eq 'form_plan') { $reply=[pscustomobject]@{exit=0;raw='unused';json=[pscustomobject]@{safe_to_act=$true;command_plan=@([pscustomobject]@{label='Name';route='captured';command=@('macro','windows')})}} }
  else { $reply=[pscustomobject]@{exit=0;raw='unused';json=[pscustomobject]@{safe_to_act=$true;best_route='captured';recommended_command=@('macro','windows')}} }
  [void]$script:Captured.Add([pscustomobject]@{kind=$kind;argv=@($Argv);exit=[int]$reply.exit;raw=[string]$reply.raw;json=$reply.json})
  return $reply
}
function _Build-WorkflowPlan {
  param([string[]]$Rest)
  $result=if ($script:Case.PSObject.Properties.Name -contains 'workflow_result') { $script:Case.workflow_result } else { & $script:OriginalWorkflow -Rest $Rest }
  $script:WorkflowPlan=$result
  return $result
}
function Write-TaskFormConsole {
  param([string]$Line)
  $script:Payload=$payload
  $script:Payload.elapsed_ms=[int]$script:Case.elapsed_ms
  if ($script:Case.kind -eq 'task') {
    $script:Assembly=[pscustomobject]@{schema='cucp.task-plan-assembly/v1';workflow_required=($workflowSteps.Count -gt 0);workflow_rest=@($wfArgs);items=@($items);errors=@($errors);form_plan=$formPlan}
  }
  if ($Brief -and -not (_Read-Switch -Rest $script:Case.rest -Name '--json-only')) {
    $script:Output=[regex]::Replace($Line,'elapsed_ms=\d+',('elapsed_ms='+$script:Case.elapsed_ms))+[Environment]::NewLine
  } else {
    $depth=if ($script:Case.kind -eq 'task') {18} else {16}
    $script:Output=($script:Payload | ConvertTo-Json -Depth $depth)+[Environment]::NewLine
  }
}
$results=New-Object Collections.ArrayList
$savedCulture=[Threading.Thread]::CurrentThread.CurrentCulture
foreach ($script:Case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  $script:Queries=New-Object Collections.ArrayList; $script:Captured=New-Object Collections.ArrayList
  $script:Payload=$null; $script:WorkflowPlan=$null; $script:Assembly=$null; $script:Output=$null; $script:BoundRest=@()
  $Brief=[bool]$script:Case.brief
  [Threading.Thread]::CurrentThread.CurrentCulture=if ($script:Case.PSObject.Properties.Name -contains 'culture') { [Globalization.CultureInfo]::GetCultureInfo([string]$script:Case.culture) } else {$savedCulture}
  try {
    $exit=if ($script:Case.kind -eq 'task') { Invoke-MacroTaskPlan -Rest $script:Case.rest } else { Invoke-MacroFormPlan -Rest $script:Case.rest }
    $value=[pscustomobject]@{bound_rest=@($script:BoundRest);queries=@($script:Queries);captured=@($script:Captured);workflow_plan=$script:WorkflowPlan;assembly=$script:Assembly;payload=$script:Payload;output=$script:Output;return_code=[int]$exit}
  } catch { $value=[pscustomobject]@{threw=$true;error='invalid_arguments';message=$_.Exception.Message;bound_rest=@($script:BoundRest);queries=@($script:Queries)} }
  [void]$results.Add($value)
}
[Threading.Thread]::CurrentThread.CurrentCulture=$savedCulture
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 64 -Compress))
'''


PS_RENDER = r'''
param([string]$InputPath)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$results=New-Object Collections.ArrayList
foreach ($renderCase in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  $payload=$renderCase.payload; $case=$renderCase.case
  $brief=[bool]$case.brief -and -not ($case.rest -contains '--json-only')
  if ($brief -and $case.kind -eq 'task') { $line="$($payload.status) task-plan steps=$($payload.step_count) live=$($payload.live_step_count) errors=$($payload.errors.Count) elapsed_ms=$($payload.elapsed_ms)" }
  elseif ($brief -and $payload.safe_to_act) { $line="ok form-plan steps=$($payload.step_count) safe=$($payload.safe_step_count) match='$($payload.match)' elapsed_ms=$($payload.elapsed_ms)" }
  elseif ($brief) { $line="partial form-plan steps=$($payload.step_count) safe=$($payload.safe_step_count) errors=$($payload.errors.Count) match='$($payload.match)' elapsed_ms=$($payload.elapsed_ms)" }
  else { $depth=if ($case.kind -eq 'task') {18} else {16}; $line=$payload | ConvertTo-Json -Depth $depth }
  $exit=if ($payload.status -eq 'ok') {0} else {2}
  [void]$results.Add([pscustomobject]@{output=$line+[Environment]::NewLine;return_code=$exit})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 8 -Compress))
'''


if __name__ == "__main__":
    unittest.main()
