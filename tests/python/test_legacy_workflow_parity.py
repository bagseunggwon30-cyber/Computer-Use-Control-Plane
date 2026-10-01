"""Pure workflow migration evidence; never execute a planned command.

The ordinary corpus checks literal-token and policy parity. A separate broad
syntax probe identifies unresolved PSParser compatibility. Strict qualification
is opt-in with CUCP_REQUIRE_WORKFLOW_PARSER_PARITY=1 and is required before any
legacy parser retirement. A green ordinary suite is NOT full parser parity.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = "bf895d3120dd5e145f360cb1c41e1d79a061d048"
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyWorkflow.ContractTests"
KERNEL = ROOT / "pcucp-next/dotnet/PcuCp.NativeHost/LegacyWorkflowKernel.cs"
LITERAL_PARSER = KERNEL.with_name("LegacyWorkflowLiteralParser.cs")


def original_source():
    return subprocess.check_output(["git", "show", f"{BASELINE_TREE}:scripts/cucp.ps1"], cwd=ROOT).decode("utf-8-sig")


def original_allowlists():
    source = original_source()
    source = source[source.index("function _Build-WorkflowPlan {"):source.index("function Invoke-MacroWorkflowPlan {")]
    result = {}
    for name in ("readOnlyMacros", "liveMacros", "blockedMacros"):
        match = re.search(r"\$" + name + r"\s*=\s*@\((.*?)\)", source, re.S)
        if match is None:
            raise ValueError(f"Missing pinned workflow allowlist: {name}")
        result[name] = re.findall(r'"([^"\r\n]*)"', match[1])
    return result


def supported_cases():
    steps = [
        "", " ", "\t\r\n", "''", '""', "macro", "windows", "macro windows", "MACRO WINDOWS", "macro session",
        "macro windows --match Notepad", "macro click-point --x -100 --y 0", "macro windows # comment",
        "macro windows; macro registry", "macro windows | anything", "macro windows > filename",
        "macro windows $env:PATH", "macro windows -Name value", 'macro type-native --text "unterminated',
        "macro type-native --text '한글 it''s'", 'macro type-native --text "a`nb"',
        'macro type-native --text "a""b"', "macro type-native --text foo` bar",
        "macro type-native --text '$env:PATH'", 'macro type-native --text pre"middle"post',
        'macro type-native --text "" --next value', "macro windows `\n --json-only",
        "macro windows\nmacro screenshot", 'macro type-native --text "C:\\Program Files\\한글"',
        "macro type-native --text ‘한글’", "macro type-native --text “한글”",
        'macro type-native --text "`a`b`f`n`r`t`v`0`e`u{41}"',
    ]
    fixtures = [{"kind": "parse", "step": step} for step in steps]
    rest_cases = [[], ["--step"], ["--step", ""], ["ignored", "--STEP", "macro", "windows", "--step", ""],
                  ["--name", "demo", "--step", "macro windows", "--step", "macro type-native --text 'hello'"],
                  ["--step", "macro windows", "--name", "name inside step"], ["--name", "--step", "macro windows"],
                  ["--name", "first", "--name", "second", "--step", "macro windows"],
                  ["--step", "macro", "--step", "macro windows"], ["--step", "", "--step", "macro windows"]]
    for rest in rest_cases:
        fixtures.extend(({"kind": "specs", "rest": rest}, {"kind": "plan", "rest": rest}))
    names = original_allowlists()
    for name in names["readOnlyMacros"] + names["liveMacros"] + names["blockedMacros"] + ["unknown", "task-run", "WINDOWS", "REGISTRY"]:
        fixtures.append({"kind": "plan", "rest": ["--step", f"macro {name}"]})
    for action in ("info", "helper-status", "autostart-status", "INFO", "start", "stop", "restart", "autostart-enable", "--json-only"):
        fixtures.append({"kind": "plan", "rest": ["--step", f"macro session {action}"]})
    for name in ("windows", "type-native", "registry", "process", "app-close", "notify", "cdp-eval"):
        for text in ("password", "delete account", "Send", "--force", "ordinary", "결제"):
            fixtures.append({"kind": "plan", "rest": ["--step", f"macro {name} --text '{text}'"]})
    return fixtures


def syntax_probe_cases():
    # This intentionally includes constructs which a whitespace/quote splitter
    # cannot classify faithfully. They must never be silently accepted as argv.
    return [{"kind": "parse", "step": value} for value in [
        "'windows'", "'macro' windows", '"macro" windows', "1 2", "-1", "+1", "process", "if", "return 1",
        "macro windows --", "macro windows --% --anything $env:PATH", "macro windows --% | more",
        'macro type-native --text "hello $name"', 'macro type-native --text "$(anything)"',
        'macro type-native --text "${name}"', 'macro type-native --text "$"', 'macro type-native --text "`$name"',
        "macro type-native --text a$b", "macro type-native --text '$()'", "macro type-native --text user@example.com",
        "macro type-native --text a#b", "macro type-native --text # comment", "macro type-native --text --not-a-param",
        "macro type-native --text -literal", "macro type-native --text -123", 'macro type-native --text -"literal"',
        "macro type-native --text foo`\nbar", "macro type-native --text foo`\r\nbar", "macro type-native --text tail`",
        "macro windows (anything)", "macro windows (", "macro windows )", "macro windows { anything }", "macro windows {",
        "macro windows @('a','b')", "macro windows @{x=1}", "macro windows [string]", "macro windows a,b",
        "macro windows <# comment #>", "macro windows <# unterminated", "macro windows && more", "macro windows || more",
        "& macro windows", ". macro windows", "macro windows 2>&1", "macro windows *>file", "macro windows < file",
        "macro type-native --text @'\nhello\n'@", 'macro type-native --text @"\nhello\n"@',
        "macro type-native --text a\u00a0b", "macro type-native --text a\u2003b", "macro type-native --text a\x00b",
        "macro type-native --text ‘a’", "macro type-native --text “a”", "macro type-native --text \"a'b\"",
    ]]


def normalized(value):
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        # Native diagnostics need not reproduce localized PowerShell wording.
        return {key: normalized(item) for key, item in value.items() if key not in {"message", "detail"}}
    return value


class WorkflowFixtureTests(unittest.TestCase):
    def test_allowlists_exactly_match_immutable_source(self):
        before = original_allowlists()
        source = KERNEL.read_text(encoding="utf-8")
        for old, new in (("readOnlyMacros", "ReadOnlyMacros"), ("liveMacros", "LiveMacros")):
            match = re.search(new + r" = new\(Comparer\)\s*\{(.*?)\};", source, re.S)
            self.assertIsNotNone(match)
            self.assertEqual(re.findall(r'"([^"\r\n]*)"', match[1]), before[old])
        self.assertEqual(before["blockedMacros"], ["workflow-plan", "workflow-run"])

    def test_corpus_covers_policy_and_unqualified_syntax(self):
        self.assertGreater(len(supported_cases()), 170)
        self.assertGreater(len(syntax_probe_cases()), 50)
        self.assertTrue(any("@'" in fixture["step"] for fixture in syntax_probe_cases()))

    def test_no_powershell_runtime_or_command_execution_dependency(self):
        source = KERNEL.read_text(encoding="utf-8") + LITERAL_PARSER.read_text(encoding="utf-8")
        for forbidden in ("Process.Start", "ProcessStartInfo", "System.Management.Automation", "DllImport", "Invoke-Expression"):
            self.assertNotIn(forbidden, source)

    def test_plan_assembly_has_no_candidate_lexer_dependency(self):
        kernel = KERNEL.read_text(encoding="utf-8")
        self.assertIn("PlanFromParsed(JsonElement args)", kernel)
        self.assertNotIn("ParseStep(", kernel)
        self.assertNotIn("Plan(string[] rest)", kernel)
        self.assertIn("ParseStep(string step)", LITERAL_PARSER.read_text(encoding="utf-8"))


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell 5.1 differential qualification")
class WorkflowWindowsParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotnet = shutil.which("dotnet")
        cls.powershell = shutil.which("powershell.exe")
        if not cls.dotnet or not cls.powershell:
            raise RuntimeError("SDK and Windows PowerShell 5.1 are required for workflow qualification")
        result = subprocess.run([cls.dotnet, "build", str(PROJECT), "-c", "Release"], cwd=ROOT, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        cls.runner = PROJECT / "bin/Release/net8.0/PcuCp.LegacyWorkflow.ContractTests.dll"

    def differential(self, cases, *, parsed_feed=False):
        with tempfile.TemporaryDirectory(prefix="CUCP workflow 한글 ") as temp:
            root = Path(temp)
            source, inputs, runner = root / "original.ps1", root / "cases.json", root / "runner.ps1"
            source.write_text(original_source(), encoding="utf-8-sig")
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8-sig")
            runner.write_text(r'''
param([string]$SourcePath, [string]$InputPath)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected PS 5.1' }
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source did not parse' }
foreach ($name in @('_Read-OptValue','_Safety-Truncate','_Classify-SafetyFromText','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan')) {
  $function=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($function.Count -ne 1) { throw "Expected one exact baseline function: $name" }
  . ([scriptblock]::Create($function[0].Extent.Text))
}
$results=New-Object Collections.ArrayList
foreach ($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  try {
    if ($case.kind -eq 'plan-from-parsed-input') {
      $parsed=New-Object Collections.ArrayList
      foreach ($spec in @(_Read-WorkflowStepSpecs -Rest $case.rest)) {
        [void]$parsed.Add((_Parse-WorkflowStepTokens -Step "$spec"))
      }
      try { $plan=_Build-WorkflowPlan -Rest $case.rest }
      catch { $plan=@{threw=$true;error='invalid_arguments'} }
      $value=@{input=@{rest=@($case.rest);parsed_steps=@($parsed)};expected=$plan}
    }
    elseif ($case.kind -eq 'parse') { $value=_Parse-WorkflowStepTokens -Step $case.step }
    elseif ($case.kind -eq 'specs') { $value=@{specs=@(_Read-WorkflowStepSpecs -Rest $case.rest)} }
    else { $value=_Build-WorkflowPlan -Rest $case.rest }
  } catch { $value=@{threw=$true;error='invalid_arguments'} }
  [void]$results.Add($value)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding="utf-8-sig")
            # The runner imports only these pure definitions. It never calls the
            # script entry point, workflow-run, or anything in a planned argv.
            before = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(runner),
                                     "-SourcePath", str(source), "-InputPath", str(inputs)], capture_output=True, timeout=60)
            self.assertEqual(before.returncode, 0, before.stderr.decode(errors="replace"))
            expected = json.loads(before.stdout.decode("utf-8-sig"))
            actual_inputs = cases
            if parsed_feed:
                actual_inputs = [{"kind": "plan-from-parsed", **value["input"]} for value in expected]
                expected = [value["expected"] for value in expected]
            after = subprocess.run([self.dotnet, str(self.runner), "--fixtures"], input=json.dumps(actual_inputs, ensure_ascii=True).encode(),
                                    capture_output=True, timeout=30)
            self.assertEqual(after.returncode, 0, after.stderr.decode(errors="replace"))
            actual = json.loads(after.stdout.decode("utf-8-sig"))
            self.assertEqual(len(expected), len(cases))
            self.assertEqual(len(actual), len(cases))
            if parsed_feed and os.environ.get("CUCP_NATIVE_TEST_HOST"):
                self.check_native_parsed_dispatch(actual_inputs, expected)
                # The actual retained PS entry point must preserve the same full
                # plans, including parser diagnostics, through native stdin.
                bridge_runner = root / "bridge.ps1"
                bridge_runner.write_text(runner.read_text(encoding="utf-8-sig").replace(
                    "@('_Read-OptValue','_Safety-Truncate','_Classify-SafetyFromText','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan')",
                    "@('_Invoke-LegacyCompatibility','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan')"), encoding="utf-8-sig")
                bridged = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File", str(bridge_runner),
                    "-SourcePath", str(ROOT / "scripts/cucp.ps1"), "-InputPath", str(inputs)],
                    env={**os.environ, "CUCP_NATIVE_HOST": os.environ["CUCP_NATIVE_TEST_HOST"]}, capture_output=True, timeout=180)
                self.assertEqual(bridged.returncode, 0, bridged.stderr.decode(errors="replace"))
                self.assertEqual([value["expected"] for value in json.loads(bridged.stdout.decode("utf-8-sig"))], expected)
            return list(zip(cases, expected, actual))

    def check_native_parsed_dispatch(self, fixtures, expected):
        """Additional real-dispatch evidence; never replace the 254-case pure proof."""
        host = Path(os.environ["CUCP_NATIVE_TEST_HOST"]).resolve()
        self.assertTrue(host.is_file(), f"Configured native test host missing: {host}")
        command = [self.dotnet, str(host)] if host.suffix.lower() == ".dll" else [str(host)]
        selectors = {
            "valid_readonly": lambda f, p: p.get("safe_to_run") and p.get("live_step_count") == 0,
            "sensitive": lambda f, p: p.get("safe_to_run") and p.get("requires_sensitive_confirmation"),
            "recursive_block": lambda f, p: any(e.get("code") == "recursive_workflow_blocked" for e in p.get("errors", [])),
            "parse_error": lambda f, p: any(e.get("code") == "parse_error" for e in p.get("errors", [])),
            "variable_literal": lambda f, p: any('"hello $name"' in value for value in f["rest"]),
            "here_string": lambda f, p: any("@'\nhello\n'@" in value for value in f["rest"]),
            "unicode": lambda f, p: any("한글" in value for value in f["rest"]),
            "nul_literal": lambda f, p: any("\x00" in value for value in f["rest"]),
        }
        checked = []
        for label, select in selectors.items():
            matches = [(fixture, plan) for fixture, plan in zip(fixtures, expected) if select(fixture, plan)]
            self.assertTrue(matches, f"Missing native dispatch fixture category: {label}")
            fixture, plan = matches[0]
            body = {"schema": "cucp.legacy-compat/v1", "operation": "workflow-plan-from-parsed",
                    "args": {key: fixture[key] for key in ("rest", "parsed_steps")}}
            with self.subTest(native_dispatch=label):
                result = subprocess.run([*command, "legacy-compat"], input=json.dumps(body, ensure_ascii=True).encode(),
                                        capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
                envelope = json.loads(result.stdout.decode("utf-8-sig"))
                self.assertEqual(envelope["status"], "ok", envelope)
                self.assertEqual(envelope["data"], plan)
                checked.append(label)
        print("Verified real native parsed-plan dispatch: " + ", ".join(checked))

    def test_actual_psparser_results_preserve_complete_original_plans(self):
        # This proof bypasses the unqualified C# lexer entirely. Both ordinary
        # literals and every broad syntax probe use actual PSParser results.
        cases = [{"kind": "plan-from-parsed-input",
                  "rest": ["--step", fixture["step"]] if fixture["kind"] == "parse" else fixture["rest"]}
                 for fixture in supported_cases() + syntax_probe_cases()]
        for fixture, expected, actual in self.differential(cases, parsed_feed=True):
            with self.subTest(fixture=fixture):
                # Unlike candidate lexer comparisons, original diagnostic text
                # is supplied as data and must be preserved exactly as well.
                self.assertEqual(actual, expected)

    def test_supported_literal_and_policy_cases_match(self):
        for fixture, expected, actual in self.differential(supported_cases()):
            with self.subTest(fixture=fixture):
                self.assertEqual(normalized(actual), normalized(expected))

    def test_broad_parser_probe_never_relaxes_rejected_constructs(self):
        gaps = []
        for fixture, expected, actual in self.differential(syntax_probe_cases()):
            with self.subTest(fixture=fixture):
                if actual.get("ok"):
                    self.assertTrue(expected.get("ok"), "Candidate accepted a sequence rejected by PSParser")
                    self.assertEqual(actual["tokens"], expected["tokens"], "Candidate reinterpreted accepted tokens")
                if normalized(expected) != normalized(actual):
                    gaps.append({"step": fixture["step"], "before": normalized(expected), "after": normalized(actual)})
        if gaps:
            print("WORKFLOW PARSER NOT QUALIFIED: " + json.dumps(gaps, ensure_ascii=True))
        if os.environ.get("CUCP_REQUIRE_WORKFLOW_PARSER_PARITY") == "1":
            self.assertEqual(gaps, [], "Do not retire the original PSParser while compatibility gaps remain")


if __name__ == "__main__":
    unittest.main()
