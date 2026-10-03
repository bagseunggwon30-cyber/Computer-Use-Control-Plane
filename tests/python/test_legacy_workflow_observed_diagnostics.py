"""Immutable raw PS5 diagnostic evidence and bounded comment/context repairs."""
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import unittest

import test_legacy_workflow_parity as workflow
import test_legacy_workflow_diagnostics as diagnostics

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST = FIXTURES / "legacy-workflow-diagnostic-repair-37082726512.json"
RAW = FIXTURES / "legacy-workflow-ps51-raw-diagnostics-37082726512.json"
RAW_SHA256 = "6c5602b3839565d43b34bcd1111c09f063b8d86d2e08f6c8082fd04b7976b97c"
TARGETS = {"inferred_opaque_nested_comment", "inferred_later_semicolon_keyword", "inferred_later_group_keyword"}


def evidence():
    return json.loads(MANIFEST.read_text(encoding="utf-8")), json.loads(RAW.read_bytes())


class WorkflowObservedDiagnosticTests(unittest.TestCase):
    def test_original_raw_capture_and_provenance_are_immutable(self):
        manifest, raw = evidence()
        self.assertEqual(hashlib.sha256(RAW.read_bytes()).hexdigest(), RAW_SHA256)
        raw_git_path = RAW.relative_to(workflow.ROOT).as_posix()
        indexed = subprocess.check_output(["git", "show", ":" + raw_git_path], cwd=workflow.ROOT)
        self.assertEqual(hashlib.sha256(indexed).hexdigest(), RAW_SHA256)
        self.assertEqual(subprocess.check_output(["git", "check-attr", "text", "--", raw_git_path], cwd=workflow.ROOT, text=True).strip(), raw_git_path + ": text: unset")
        self.assertIn("tests/fixtures/legacy-workflow-ps51-raw-diagnostics-37082726512.json -text whitespace=cr-at-eol", (workflow.ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines())
        provenance = manifest["provenance"]
        self.assertEqual(provenance["raw_capture_sha256"], RAW_SHA256)
        self.assertEqual(provenance["artifact_zip_sha256"], "38bc0f865489c573fea0c3b664fd8378fab4417108cf8db3b0fe8c74ab491a77")
        self.assertEqual(provenance["run_id"], "37082726512")
        self.assertEqual(provenance["tested_commit"], "9f6a2038e21bc90c0dcb9a3dcce7053af1bbb60c")
        self.assertEqual(provenance["baseline_tree"], workflow.BASELINE_TREE)
        self.assertEqual(raw["provenance"]["candidate_commit"], provenance["tested_commit"])
        self.assertEqual(raw["provenance"]["powershell_version"], "5.1.26100.33438")
        self.assertEqual(raw["provenance"]["culture"], "en-US")
        self.assertEqual(raw["provenance"]["ui_culture"], "en-US")
        self.assertTrue(raw["comparison_completed"])
        self.assertEqual(len(raw["cases"]), 101)
        self.assertEqual(len({case["id"] for case in raw["cases"]}), 101)

    def test_exact_and_normalized_debt_are_separate_overlapping_counts(self):
        manifest, raw = evidence()
        exact, normalized = [], []
        for case in raw["cases"]:
            before = {key: case[key] for key in ("parsed", "plan")}
            after = case["candidate"]
            if before != after:
                exact.append(case["id"])
            if workflow.normalized(before) != workflow.normalized(after):
                normalized.append(case["id"])
        self.assertEqual(exact, raw["exact_diagnostic_gap_ids"])
        self.assertEqual(len(exact), 84)
        self.assertEqual(len(normalized), 11)
        self.assertEqual(len(set(exact) - set(normalized)), 73)
        for name, count in (("historical_exact_gap_count", 84), ("historical_normalized_gap_count", 11), ("historical_text_only_gap_count", 73)):
            self.assertEqual(manifest["provenance"][name], count)

    def test_three_predictions_use_actual_observed_basis_without_changing_oracle(self):
        manifest, raw = evidence()
        self.assertEqual(set(manifest["target_ids"]), TARGETS)
        predictions = {case["id"]: case for case in json.loads((FIXTURES / "legacy-workflow-diagnostic-candidate.json").read_text(encoding="utf-8"))["cases"]}
        originals = {case["id"]: case for case in raw["cases"]}
        for case_id in TARGETS:
            predicted, observed = predictions[case_id], originals[case_id]
            self.assertEqual(predicted["step"], observed["step"])
            self.assertEqual(predicted["candidate_error"], observed["parsed"]["error"])
            self.assertEqual(predicted["candidate_basis"], {"evidence": "observed-windows-powershell-5.1-raw-diagnostics", "run_id": "37082726512", "observation_id": case_id, "raw_capture_sha256": RAW_SHA256})
            self.assertFalse(observed["parsed"]["ok"])
        self.assertEqual(originals["inferred_opaque_nested_comment"]["parsed"]["detail"], "Unexpected token ')' in expression or statement.")
        self.assertEqual(originals["inferred_later_semicolon_keyword"]["first_unsupported_token_type"], "StatementSeparator")
        self.assertEqual(originals["inferred_later_group_keyword"]["first_unsupported_token_type"], "GroupStart")

    def test_future_raw_capture_appends_neighbors_without_rewriting_original_cases(self):
        manifest, raw = evidence()
        live = diagnostics.diagnostic_cases()
        self.assertEqual(len(live), 124)
        self.assertEqual(live[:101], [{key: case[key] for key in ("id", "step")} for case in raw["cases"]])
        self.assertEqual(live[101:], [{key: case[key] for key in ("id", "step")} for case in manifest["inferred_neighbors"]])

    def test_adversarial_neighbors_stay_inferred_rejections(self):
        manifest, raw = evidence()
        neighbors = manifest["inferred_neighbors"]
        self.assertEqual(len(neighbors), 23)
        self.assertEqual(len({case["id"] for case in neighbors}), 23)
        self.assertFalse({case["step"] for case in neighbors} & {case["step"] for case in raw["cases"]})
        for case in neighbors:
            self.assertEqual(case["evidence"], "inferred-unqualified")
            self.assertEqual(case["candidate"]["ok"], False)
            self.assertEqual(case["candidate"]["tokens"], [])
            self.assertIn(case["candidate"]["error"], {"parse_error", "unsupported_token"})
            self.assertLessEqual(len(case["step"]), 65536)


@unittest.skipUnless(sys.platform == "win32", "Fresh Windows PowerShell 5.1 diagnostic context qualification")
class WorkflowDiagnosticSemanticsWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.WorkflowWindowsParityTests.setUpClass.__func__(cls)

    differential = workflow.WorkflowWindowsParityTests.differential

    def test_three_recorded_error_codes_and_tokens_match(self):
        manifest, raw = evidence()
        cases = [case for case in raw["cases"] if case["id"] in manifest["target_ids"]]
        inputs = [{"kind": "parse", "step": case["step"]} for case in cases]
        for case, (_, original, actual) in zip(cases, self.differential(inputs)):
            with self.subTest(case=case["id"]):
                self.assertEqual(workflow.normalized(original), workflow.normalized(case["parsed"]))
                self.assertEqual(workflow.normalized(actual), workflow.normalized(original))
                self.assertFalse(actual["ok"])

    def test_inferred_neighbors_preserve_ps51_rejection_classification(self):
        manifest, _ = evidence()
        cases = manifest["inferred_neighbors"]
        inputs = [{"kind": "parse", "step": case["step"]} for case in cases]
        for case, (_, original, actual) in zip(cases, self.differential(inputs)):
            with self.subTest(case=case["id"]):
                self.assertEqual(workflow.normalized(actual), case["candidate"])
                self.assertEqual(workflow.normalized(actual), workflow.normalized(original))
                self.assertFalse(actual["ok"])


if __name__ == "__main__":
    unittest.main()
