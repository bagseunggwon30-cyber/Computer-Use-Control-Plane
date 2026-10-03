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
        self.assertEqual(len(live), 128)
        self.assertEqual(live[:101], [{key: case[key] for key in ("id", "step")} for case in raw["cases"]])
        position = diagnostics.command_position_fixtures()
        prior = {case["id"]: case for case in manifest["inferred_neighbors"] + position["observed_positive_targets"]}
        self.assertEqual(live[101:124], [{key: prior[id][key] for key in ("id", "step")} for id in manifest["captured_neighbor_order"]])
        self.assertEqual(live[124:], [{key: case[key] for key in ("id", "step")} for case in position["inferred_live_neighbors"]])

    def test_adversarial_neighbors_stay_inferred_rejections(self):
        manifest, raw = evidence()
        neighbors = manifest["inferred_neighbors"]
        self.assertEqual(len(neighbors), 22)
        self.assertEqual(len({case["id"] for case in neighbors}), 22)
        self.assertFalse({case["step"] for case in neighbors} & {case["step"] for case in raw["cases"]})
        for case in neighbors:
            self.assertEqual(case["evidence"], "inferred-unqualified")
            self.assertEqual(case["candidate"]["ok"], False)
            self.assertEqual(case["candidate"]["tokens"], [])
            self.assertIn(case["candidate"]["error"], {"parse_error", "unsupported_token"})
            self.assertLessEqual(len(case["step"]), 65536)

    def test_observed_positive_row_is_separate_from_22_rejection_contracts(self):
        position = diagnostics.command_position_fixtures()
        provenance = position["provenance"]
        self.assertEqual(provenance["run_id"], "37084621275")
        self.assertEqual(provenance["tested_commit"], "fe3963929cebefd23b318f129a236d8ff7b5acb3")
        self.assertEqual(provenance["raw_capture_sha256"], "7e12bab3a28adf209bc1a7d1437260cc9b53af2e84a006d1be94639d8ddcade0")
        self.assertEqual(provenance["artifact_zip_sha256"], "351a8145d09804fd3dfd8a8ddc08f465ff7fdd3f9c985fb6611e8927df5e94a0")
        self.assertEqual([provenance[name] for name in ("historical_raw_case_count", "historical_exact_gap_count", "historical_normalized_gap_count", "historical_text_only_gap_count")], [124, 107, 9, 98])
        self.assertEqual(position["oracle_provenance"]["candidate_commit"], provenance["tested_commit"])
        self.assertEqual(len(position["observed_positive_targets"]), 1)
        row_hash = hashlib.sha256(json.dumps(position["observed_positive_targets"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(row_hash, "a674092da4b3662c85a4a4ac5997b72b752a0b10797f01123bb62d2f7f5f7f86")
        self.assertEqual(provenance["observed_positive_rows_sha256"], row_hash)
        positive = position["observed_positive_targets"][0]
        self.assertEqual(positive["id"], "diagnostic_context_named_block_after_newline")
        self.assertEqual(positive["step"], "macro windows\nprocess")
        self.assertEqual(positive["parsed"], {"ok": True, "error": "", "detail": "", "tokens": ["macro", "windows", "process"]})
        self.assertEqual(positive["parse_errors"], [])
        self.assertFalse(positive["candidate"]["parsed"]["ok"])
        self.assertTrue(positive["plan"]["safe_to_run"])
        manifest, _ = evidence()
        self.assertNotIn(positive["id"], {case["id"] for case in manifest["inferred_neighbors"]})
        self.assertEqual(len(position["inferred_live_neighbors"]), 4)
        self.assertEqual(len(position["inferred_managed_neighbors"]), 10)
        for case in position["inferred_live_neighbors"] + position["inferred_managed_neighbors"]:
            self.assertEqual(case["evidence"], "inferred-unqualified")


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

    def test_recorded_positive_command_position_and_four_live_neighbors(self):
        position = diagnostics.command_position_fixtures()
        cases = position["observed_positive_targets"] + position["inferred_live_neighbors"]
        inputs = [{"kind": "parse", "step": case["step"]} for case in cases]
        for case, (_, original, actual) in zip(cases, self.differential(inputs)):
            with self.subTest(case=case["id"]):
                expected = case["parsed"] if "parsed" in case else case["candidate"]
                self.assertEqual(workflow.normalized(actual), workflow.normalized(expected))
                self.assertEqual(workflow.normalized(actual), workflow.normalized(original))
                self.assertTrue(actual["ok"])

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
