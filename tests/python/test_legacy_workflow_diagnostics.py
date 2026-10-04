"""Qualification-only diagnostic evidence. No fixture text is ever executed.

The existing normalized workflow comparisons deliberately omit detail/message.
This capture retains them, together with engine/culture/immutable-source identity.
No successful normalized comparison establishes exact diagnostic compatibility.
"""
import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_legacy_workflow_parity import BASELINE_TREE, ROOT, PROJECT, original_source, inferred_literal_fixtures, normalized

FIXTURES = ROOT / "tests/fixtures/legacy-workflow-diagnostic-candidate.json"
PREFLIGHT = PROJECT / "LegacyWorkflowParseErrorPreflight.cs"
CONTEXT_FIXTURES = ROOT / "tests/fixtures/legacy-workflow-diagnostic-repair-37082726512.json"
MAX_DIAGNOSTIC_CASES = 152
TOKEN_KIND_FIXTURES = ROOT / "tests/fixtures/legacy-workflow-token-kind-repair-37086299736.json"


def token_kind_fixtures():
    return json.loads(TOKEN_KIND_FIXTURES.read_text(encoding="utf-8"))


COMMAND_POSITION_FIXTURES = ROOT / "tests/fixtures/legacy-workflow-command-position-observed-37084621275.json"


def command_position_fixtures():
    return json.loads(COMMAND_POSITION_FIXTURES.read_text(encoding="utf-8"))


def validate_diagnostic_inputs(cases):
    """Validate one root array without coercing fields or flattening nested arrays."""
    if not isinstance(cases, list):
        raise ValueError("Diagnostic input root must be an array.")
    if not 1 <= len(cases) <= MAX_DIAGNOSTIC_CASES:
        raise ValueError("Case count exceeds the bounded capture")
    seen_ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Diagnostic input case must be an object.")
        if set(case) != {"id", "step"}:
            raise ValueError("Diagnostic input case fields must be exactly id and step.")
        if not isinstance(case["id"], str) or not case["id"]:
            raise ValueError("Diagnostic input id must be a nonempty string.")
        if not isinstance(case["step"], str):
            raise ValueError("Diagnostic input step must be a string.")
        # Match the Windows string bound in UTF-16 code units, not code points.
        if len(case["step"].encode("utf-16-le", errors="surrogatepass")) // 2 > 65536:
            raise ValueError("Case text exceeds the bounded capture")
        if case["id"] in seen_ids:
            raise ValueError("Duplicate diagnostic input id.")
        seen_ids.add(case["id"])
    return cases


def invalid_diagnostic_inputs():
    valid = {"id": "one", "step": "macro windows"}
    return [
        ("object_root", valid), ("null_root", None), ("string_root", "root"),
        ("empty", []), ("too_many", [{"id": str(i), "step": ""} for i in range(MAX_DIAGNOSTIC_CASES + 1)]),
        ("nested_array", [[valid]]), ("null_case", [None]), ("scalar_case", [3]),
        ("missing_id", [{"step": "macro windows"}]), ("missing_step", [{"id": "one"}]),
        ("extra_field", [{**valid, "extra": "not allowed"}]),
        ("wrong_case_field", [{"ID": "one", "step": "macro windows"}]),
        ("array_id", [{"id": ["one", "two"], "step": "macro windows"}]),
        ("empty_id", [{"id": "", "step": "macro windows"}]),
        ("array_step", [{"id": "one", "step": ["macro", "windows"]}]),
        ("boolean_step", [{"id": "one", "step": True}]),
        ("long_step", [{"id": "one", "step": "x" * 65537}]),
        ("duplicate_id", [valid, {"id": "one", "step": "macro screenshot"}]),
    ]


def diagnostic_cases():
    cases = [{"id": case["id"], "step": case["step"]}
             for case in json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]]
    # Preserve the original inferred/observed distinction in the input fixtures;
    # a newly captured raw oracle result gets its own provenance below.
    for case in inferred_literal_fixtures()["cases"]:
        if case["candidate"]["error"] == "parse_error" and case["id"].startswith("bounded_"):
            cases.append({"id": case["id"], "step": case["step"]})
    cases.extend([
        {"id": "diagnostic_empty", "step": ""},
        {"id": "diagnostic_first_unsupported_parameter", "step": "macro windows -Name value | other"},
        {"id": "diagnostic_first_unsupported_pipeline", "step": "macro windows | other -Name value"},
        {"id": "diagnostic_two_errors", "step": "macro windows -Name ( {"},
    ])
    context = json.loads(CONTEXT_FIXTURES.read_text(encoding="utf-8"))
    position = command_position_fixtures()
    prior_neighbors = {case["id"]: case for case in context["inferred_neighbors"] + position["observed_positive_targets"]}
    # Keep all existing 124 input rows in their captured order; append only four.
    cases.extend({"id": prior_neighbors[id]["id"], "step": prior_neighbors[id]["step"]}
                 for id in context["captured_neighbor_order"])
    cases.extend({"id": case["id"], "step": case["step"]} for case in position["inferred_live_neighbors"])
    cases.extend({"id": case["id"], "step": case["step"]} for case in token_kind_fixtures()["inferred_live_neighbors"])
    return validate_diagnostic_inputs(cases)


ORACLE_PATH = ROOT / "tests/fixtures/legacy-workflow-diagnostics-oracle.ps1"
ORACLE_RUNNER = ORACLE_PATH.read_text(encoding="utf-8-sig")



def retain_diagnostic_capture(capture, destination):
    encoded = json.dumps(capture, ensure_ascii=True, separators=(",", ":"))
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded + "\n", encoding="utf-8")
    print("WORKFLOW RAW DIAGNOSTIC CAPTURE: " + encoded)


class WorkflowDiagnosticFixtureTests(unittest.TestCase):
    def test_input_validation_preserves_one_or_many_without_coercion(self):
        one = [{"id": "one", "step": "macro windows"}]
        many = [{"id": "case", "step": "macro windows"}, {"id": "CASE", "step": ""}, {"id": "한글", "step": "macro windows\nmacro screenshot"}]
        for cases in (one, many):
            self.assertIs(validate_diagnostic_inputs(cases), cases)
            self.assertEqual(validate_diagnostic_inputs(json.loads(json.dumps(cases))), cases)
        self.assertEqual(len(diagnostic_cases()), MAX_DIAGNOSTIC_CASES)
        maximum = [{"id": str(i), "step": ""} for i in range(MAX_DIAGNOSTIC_CASES)]
        self.assertIs(validate_diagnostic_inputs(maximum), maximum)

    def test_input_validation_rejects_invalid_shapes_and_duplicate_ids(self):
        for name, cases in invalid_diagnostic_inputs():
            with self.subTest(case=name), self.assertRaises(ValueError):
                validate_diagnostic_inputs(cases)

    def test_ps5_root_array_is_assigned_directly_and_guarded_before_tokenization(self):
        materialize = "$cases=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($InputPath, [Text.Encoding]::UTF8))"
        self.assertIn(materialize, ORACLE_RUNNER)
        self.assertNotIn("$cases=@(", ORACLE_RUNNER)
        for guard in ("$cases -isnot [Array]", "$case -isnot [Management.Automation.PSCustomObject]", "$names -cnotcontains 'id'", "$names -cnotcontains 'step'", "$case.id -isnot [string]", "$case.step -isnot [string]", "$seenIds.Add($case.id)"):
            self.assertIn(guard, ORACLE_RUNNER)
            self.assertLess(ORACLE_RUNNER.index(guard), ORACLE_RUNNER.index("PSParser]::Tokenize($step"))
        self.assertIn("[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)", ORACLE_RUNNER)
        self.assertIn("$step=$case.step", ORACLE_RUNNER)
        self.assertNotIn("$step=[string]$case.step", ORACLE_RUNNER)

    def test_capture_is_bounded_and_evidence_labels_are_explicit(self):
        fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
        self.assertEqual(fixtures["provenance"]["baseline_tree"], BASELINE_TREE)
        observed = [case for case in fixtures["cases"] if case["evidence"] == "observed-windows-powershell-5.1"]
        self.assertEqual(len(observed), 9)
        for case in observed:
            self.assertEqual(case["observed"], {"ok": False, "error": "parse_error", "tokens": []})
            self.assertNotIn("detail", case["observed"])
        cases = diagnostic_cases()
        self.assertLessEqual(len(cases), MAX_DIAGNOSTIC_CASES)
        self.assertIn(f"$cases.Count -gt {MAX_DIAGNOSTIC_CASES}", ORACLE_RUNNER)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        unknown = [case for case in fixtures["cases"] if case.get("oracle_expectation") == "capture-only"]
        self.assertEqual(len(unknown), 6)
        for case in unknown:
            self.assertEqual(case["evidence"], "inferred-unqualified")
            self.assertIn("\0", case["step"])
            self.assertIn(case["candidate_error"], {"unsupported_token", "parse_error"})
            self.assertNotIn("observed", case)
        self.assertEqual(sum(case["candidate_error"] == "unsupported_token" for case in unknown), 5)
        self.assertEqual(sum(case["candidate_error"] == "parse_error" for case in unknown), 1)

    def test_leading_quoted_marker_neighbors_remain_inferred(self):
        fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
        neighbors = [case for case in fixtures if case["id"].startswith("inferred_marker_neighbor_")]
        self.assertEqual(len(neighbors), 7)
        self.assertEqual(sum(case["preflight_error"] == "parse_error" for case in neighbors), 4)
        self.assertEqual(sum(case["preflight_error"] == "" for case in neighbors), 3)
        for case in neighbors:
            self.assertEqual(case["evidence"], "inferred-unqualified")
            self.assertNotIn("observed", case)
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("if (IsSingle(step[start]) || IsDouble(step[start])) return false;", preflight)

    def test_quoted_marker_nul_acceptance_matches_recorded_oracle_exactly(self):
        boundary = json.loads(FIXTURES.with_name("legacy-workflow-boundary-candidate.json").read_text(encoding="utf-8"))
        observations = json.loads(FIXTURES.with_name("legacy-workflow-ps51-boundary-observed-37079778520.json").read_text(encoding="utf-8"))
        case_id = "stop_quoted_marker_adjacent_nul"
        candidate = next(case for case in boundary["inferred"] if case["id"] == case_id)
        observed = next(case for case in observations["observed_gaps"] if case["id"] == case_id)
        self.assertEqual(candidate["step"], observed["step"])
        self.assertEqual(candidate["candidate"], observed["before"])
        self.assertEqual(candidate["candidate_basis"], {"evidence": "observed-windows-powershell-5.1", "run_id": "37079778520", "observation_id": case_id})
        self.assertTrue(candidate["candidate"]["ok"])
        self.assertEqual(candidate["candidate"]["tokens"], ["macro", "windows", "--%", "\0raw"])

    def test_preflight_is_qualification_only_and_cannot_accept_tokens(self):
        source = PREFLIGHT.read_text(encoding="utf-8")
        for forbidden in ("Process.Start", "System.Management.Automation", "DllImport", "Invoke-Expression"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("new(true", source)
        self.assertIn('Reject("parse_error", detail)', source)
        native = (PROJECT.parent / "PcuCp.NativeHost/PcuCp.NativeHost.csproj").read_text(encoding="utf-8")
        self.assertNotIn("LegacyWorkflowParseErrorPreflight", native)
        self.assertIn('<Compile Remove="LegacyWorkflowLiteralParser.cs" />', native)

    def test_capture_cleanup_preserves_evidence_after_an_assertion_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "nested/capture.json"
            capture = {"comparison_completed": False, "cases": [{"id": "inert"}]}
            class FailedProbe(unittest.TestCase):
                def runTest(self):
                    self.addCleanup(retain_diagnostic_capture, capture, destination)
                    self.fail("intentional retention probe")
            result = unittest.TestResult()
            with contextlib.redirect_stdout(io.StringIO()):
                FailedProbe().run(result)
            self.assertEqual(len(result.failures), 1)
            self.assertEqual(result.errors, [])
            self.assertEqual(json.loads(destination.read_text()), capture)

    def test_file_hash_helper_uses_exact_bytes_without_module_commands(self):
        helper = ORACLE_RUNNER.split("function _Get-WorkflowDiagnosticFileSha256 {", 1)[1].split("\n}", 1)[0]
        self.assertIn("[byte[]]$fileBytes=[IO.File]::ReadAllBytes($Path)", helper)
        self.assertIn("$fileSha=[Security.Cryptography.SHA256]::Create()", helper)
        self.assertIn("$fileSha.ComputeHash($fileBytes)", helper)
        self.assertIn("([BitConverter]::ToString(", helper)
        self.assertIn(".Replace('-','').ToLowerInvariant()", helper)
        self.assertIn("finally { $fileSha.Dispose() }", helper)
        for forbidden in ("Get-FileHash", "Get-Content", "ReadAllText", "Text.Encoding", "Import-Module"):
            self.assertNotIn(forbidden, helper)
        self.assertNotIn("Get-FileHash", ORACLE_RUNNER)

    def test_both_file_hashes_keep_source_guard_and_provenance(self):
        source_check = "if ((_Get-WorkflowDiagnosticFileSha256 -Path $SourcePath) -ne $SourceHash) { throw 'Pinned source hash mismatch' }"
        self.assertIn(source_check, ORACLE_RUNNER)
        self.assertLess(ORACLE_RUNNER.index(source_check), ORACLE_RUNNER.index("::ParseFile($SourcePath"))
        self.assertIn("input_sha256=(_Get-WorkflowDiagnosticFileSha256 -Path $InputPath)", ORACLE_RUNNER)
        self.assertEqual(ORACLE_RUNNER.count("_Get-WorkflowDiagnosticFileSha256"), 3)
        self.assertIn("source_sha256=$SourceHash; helper_sha256=$helperHashes", ORACLE_RUNNER)

    def test_capture_imports_only_pinned_pure_definitions_and_does_not_run_input(self):
        self.assertIn("PSParser]::Tokenize($step", ORACLE_RUNNER)
        self.assertIn("source_sha256=$SourceHash", ORACLE_RUNNER)
        self.assertIn("ui_culture=", ORACLE_RUNNER)
        for forbidden in ("Invoke-Expression", "workflow-run", "::Create($step)", "& $step"):
            self.assertNotIn(forbidden, ORACLE_RUNNER)


@unittest.skipUnless(sys.platform == "win32", "Exact Windows PowerShell 5.1 diagnostic capture")
class WorkflowWindowsDiagnosticTests(unittest.TestCase):
    def test_oracle_materializes_cases_and_rejects_invalid_input_shapes(self):
        powershell = shutil.which("powershell.exe")
        self.assertTrue(powershell, "Windows PowerShell 5.1 is required")
        with tempfile.TemporaryDirectory(prefix="CUCP diagnostic array protocol ") as temp:
            root = Path(temp)
            source, inputs, runner = root / "original.ps1", root / "cases.json", root / "runner.ps1"
            source.write_text(original_source(), encoding="utf-8-sig")
            runner.write_bytes(ORACLE_PATH.read_bytes())
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            def invoke(payload):
                inputs.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8-sig")
                return subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(runner),
                                       "-SourcePath", str(source), "-InputPath", str(inputs),
                                       "-SourceHash", source_hash, "-BaselineTree", BASELINE_TREE],
                                      capture_output=True, timeout=60)
            for payload in ([{"id": "single", "step": "macro windows"}],
                            [{"id": "case", "step": "macro windows"}, {"id": "CASE", "step": ""},
                             {"id": "한글", "step": "macro windows\nmacro screenshot"}]):
                with self.subTest(case_count=len(payload)):
                    result = invoke(payload)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                    capture = json.loads(result.stdout.decode("utf-8-sig"))
                    self.assertEqual(len(capture["cases"]), len(payload))
                    self.assertEqual([{key: case[key] for key in ("id", "step")} for case in capture["cases"]], payload)
                    self.assertEqual(capture["provenance"]["source_sha256"], source_hash)
                    self.assertEqual(capture["provenance"]["input_sha256"], hashlib.sha256(inputs.read_bytes()).hexdigest())
                    self.assertEqual(capture["provenance"]["baseline_tree"], BASELINE_TREE)
                    self.assertTrue(capture["provenance"]["powershell_version"].startswith("5.1."))
            for name, payload in invalid_diagnostic_inputs():
                with self.subTest(invalid=name):
                    result = invoke(payload)
                    self.assertNotEqual(result.returncode, 0, "Invalid input was captured: " + name)
                    self.assertNotIn('"cucp.workflow-raw-diagnostics/v1"', result.stdout.decode(errors="replace"))
                    self.assertTrue(result.stderr, "Invalid input must explain the rejection")

    def test_raw_diagnostics_and_plan_messages_are_not_normalized(self):
        dotnet, powershell = shutil.which("dotnet"), shutil.which("powershell.exe")
        self.assertTrue(dotnet and powershell, "SDK and Windows PowerShell 5.1 are required")
        built = subprocess.run([dotnet, "build", str(PROJECT), "-c", "Release"], cwd=ROOT, capture_output=True, timeout=180)
        self.assertEqual(built.returncode, 0, built.stdout.decode(errors="replace") + built.stderr.decode(errors="replace"))
        cases = diagnostic_cases()
        with tempfile.TemporaryDirectory(prefix="CUCP raw workflow diagnostics ") as temp:
            root = Path(temp)
            source, inputs, runner = root / "original.ps1", root / "cases.json", root / "runner.ps1"
            source.write_text(original_source(), encoding="utf-8-sig")
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8-sig")
            self.assertLessEqual(inputs.stat().st_size, 1024 * 1024)
            runner.write_bytes(ORACLE_PATH.read_bytes())
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            before = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(runner),
                                     "-SourcePath", str(source), "-InputPath", str(inputs), "-SourceHash", source_hash,
                                     "-BaselineTree", BASELINE_TREE], capture_output=True, timeout=60)
            self.assertEqual(before.returncode, 0, before.stderr.decode(errors="replace"))
            self.assertLessEqual(len(before.stdout), 4 * 1024 * 1024)
            capture = json.loads(before.stdout.decode("utf-8-sig"))
            capture["comparison_completed"] = False
            self.addCleanup(retain_diagnostic_capture, capture, os.environ.get("CUCP_WORKFLOW_DIAGNOSTIC_CAPTURE"))
            self.assertEqual(capture["provenance"]["source_sha256"], source_hash)
            self.assertTrue(capture["provenance"]["powershell_version"].startswith("5.1."))
            self.assertEqual(capture["provenance"]["baseline_tree"], BASELINE_TREE)
            self.assertEqual(capture["provenance"]["input_sha256"], hashlib.sha256(inputs.read_bytes()).hexdigest())
            self.assertEqual(len(capture["provenance"]["helper_sha256"]), 6)
            for digest in capture["provenance"]["helper_sha256"].values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
            for field in ("culture", "ui_culture", "ps_culture", "ps_ui_culture", "captured_at_utc"):
                self.assertIsInstance(capture["provenance"][field], str)
            capture["provenance"]["candidate_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            capture["provenance"]["candidate_worktree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
            self.assertEqual(len(capture["cases"]), len(cases))
            fixture_inputs = []
            for case in cases:
                fixture_inputs.extend([{"kind": "parse", "step": case["step"]}, {"kind": "plan", "rest": ["--step", case["step"]]}])
            after = subprocess.run([dotnet, str(PROJECT / "bin/Release/net8.0/PcuCp.LegacyWorkflow.ContractTests.dll"), "--fixtures"],
                                   input=json.dumps(fixture_inputs, ensure_ascii=True).encode(), capture_output=True, timeout=30)
            self.assertEqual(after.returncode, 0, after.stderr.decode(errors="replace"))
            actual = json.loads(after.stdout.decode("utf-8-sig"))
            self.assertLessEqual(len(after.stdout), 4 * 1024 * 1024)
            self.assertEqual(len(actual), len(cases) * 2)
            gaps = []
            contracts = {case["id"]: case for case in json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]}
            for case in json.loads(CONTEXT_FIXTURES.read_text(encoding="utf-8"))["inferred_neighbors"]:
                contracts[case["id"]] = {**case, "candidate_error": case["candidate"]["error"]}
            position = command_position_fixtures()
            positives = {case["id"]: case for case in position["observed_positive_targets"]}
            live_neighbors = {case["id"]: case for case in position["inferred_live_neighbors"]}
            token_kinds = token_kind_fixtures()
            kind_raw = json.loads(TOKEN_KIND_FIXTURES.with_name(token_kinds["provenance"]["raw_capture_file"]).read_bytes())
            kind_targets = {case["id"]: case for case in kind_raw["cases"] if case["id"] in token_kinds["target_ids"]}
            kind_neighbors = {case["id"]: case for case in token_kinds["inferred_live_neighbors"]}
            normalized_gaps = []
            capture["exact_diagnostic_gap_ids"] = gaps
            capture["normalized_diagnostic_gap_ids"] = normalized_gaps
            for i, (requested, observed) in enumerate(zip(cases, capture["cases"])):
                original = observed["parsed"]
                candidate = {"parsed": actual[i * 2], "plan": actual[i * 2 + 1]}
                observed["candidate"] = candidate
                if candidate["parsed"] != original or candidate["plan"] != observed["plan"]:
                    gaps.append(observed["id"])
                if normalized(candidate) != normalized({"parsed": original, "plan": observed["plan"]}):
                    normalized_gaps.append(observed["id"])
                with self.subTest(case=requested["id"]):
                    self.assertEqual(observed["id"], requested["id"])
                    self.assertEqual(observed["step"], requested["step"])
                    original = observed["parsed"]
                    if observed["parse_errors"]:
                        self.assertEqual(original["error"], "parse_error")
                        self.assertEqual(original["detail"], "; ".join(error["message"] for error in observed["parse_errors"]))
                    elif observed["first_unsupported_token_type"]:
                        self.assertEqual(original["error"], "unsupported_token")
                        self.assertEqual(original["detail"], "unsupported token type '" + observed["first_unsupported_token_type"] + "'")
                    if target := kind_targets.get(requested["id"]):
                        self.assertEqual(original, target["parsed"], "Observed token-kind oracle changed")
                        self.assertEqual(observed["plan"], target["plan"], "Observed full diagnostic plan changed")
                        self.assertEqual(candidate, {key: target[key] for key in ("parsed", "plan")}, "Exact observed token-kind repair")
                    if neighbor := kind_neighbors.get(requested["id"]):
                        self.assertFalse(original["ok"], "Rejected diagnostic probe must stay rejected")
                        self.assertFalse(candidate["parsed"]["ok"], "Diagnostic repair cannot enable acceptance")
                        if neighbor["comparison"] == "exact":
                            self.assertEqual(original, neighbor["candidate"], "Inferred exact token-kind contract must match PS5.1")
                            self.assertEqual(candidate, {key: observed[key] for key in ("parsed", "plan")}, "Exact new parsed detail and full plan message")
                        else:
                            self.assertEqual({key: original[key] for key in ("ok", "error", "tokens")}, neighbor["candidate"], "Syntax guard must match PS5.1")
                            self.assertEqual({key: candidate["parsed"][key] for key in ("ok", "error", "tokens")}, neighbor["candidate"], "Syntax diagnostics retain precedence")
                    if positive := positives.get(requested["id"]):
                        self.assertEqual(original, positive["parsed"], "Observed positive oracle changed")
                        self.assertEqual(actual[i * 2], original, "Observed positive token contract")
                        self.assertEqual(actual[i * 2 + 1], positive["plan"], "Observed positive full plan contract")
                    if neighbor := live_neighbors.get(requested["id"]):
                        self.assertEqual(normalized(actual[i * 2]), neighbor["candidate"], "Inferred command-position contract")
                    if contract := contracts.get(requested["id"]):
                        if contract.get("oracle_expectation") == "capture-only":
                            # Unknown PS5 boundaries stay rejected by the
                            # candidate while their exact oracle is captured.
                            self.assertFalse(actual[i * 2]["ok"])
                            self.assertEqual(actual[i * 2]["error"], contract["candidate_error"])
                        elif contract["preflight_error"]:
                            self.assertEqual(original["error"], contract["preflight_error"], "Inferred syntax-error rule must match PS5.1: " + requested["id"])
                            self.assertEqual(actual[i * 2]["error"], original["error"], "Candidate must preserve parse-error precedence")
                        else:
                            self.assertNotEqual(original["error"], "parse_error", "Opaque/valid-syntax fixture changed: " + requested["id"])
                    if actual[i * 2].get("ok"):
                        self.assertTrue(original["ok"], "Candidate accepted a rejected sequence")
                        self.assertEqual(actual[i * 2]["tokens"], original["tokens"], "Candidate reinterpreted accepted tokens")
            capture["comparison_completed"] = True
            print(f"WORKFLOW DIAGNOSTIC GAP COUNTS: {len(gaps)} exact, {len(normalized_gaps)} normalized, {len(set(gaps) - set(normalized_gaps))} text-only; counts overlap and do not establish full grammar parity")
            # Cleanup retains the raw original/candidate capture even when a
            # non-relaxation or exact-diagnostic assertion fails.
            if gaps:
                print("WORKFLOW EXACT DIAGNOSTICS NOT QUALIFIED: " + json.dumps(gaps))
            if os.environ.get("CUCP_REQUIRE_WORKFLOW_PARSER_PARITY") == "1" or os.environ.get("CUCP_REQUIRE_WORKFLOW_DIAGNOSTIC_PARITY") == "1":
                self.assertEqual(gaps, [], "Exact raw detail/plan-message debt also blocks full parser retirement")


if __name__ == "__main__":
    unittest.main()
