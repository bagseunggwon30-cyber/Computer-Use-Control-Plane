"""Immutable PS5.1 observations and additional inert string-scanner contracts.

The checked-in observed rows are historical replay evidence. Nearby managed
contracts stay inferred until the existing Windows differential suite runs.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
OBSERVED = ROOT / "tests/fixtures/legacy-workflow-ps51-embedded-observed-37074340659.json"
INFERRED = ROOT / "tests/fixtures/legacy-workflow-literal-inferred.json"


class EmbeddedFixtureTests(unittest.TestCase):
    def test_observed_provenance_and_exact_case_mapping(self):
        document = json.loads(OBSERVED.read_text(encoding="utf-8"))
        provenance = document["provenance"]
        self.assertEqual(provenance["evidence"], "observed-windows-powershell-5.1")
        self.assertEqual(provenance["run_id"], "37074340659")
        self.assertEqual(provenance["tested_commit"], "48bb1651499d0857b4886b3f5cd8b2ed04d5e8a0")
        self.assertEqual(provenance["baseline_tree"], "bf895d3120dd5e145f360cb1c41e1d79a061d048")
        self.assertEqual(provenance["log_line"], 225)
        self.assertEqual(provenance["log_sha256"], "d7090be7d8bcb52fd4d2a2b156f862c40a5dc66a66a507374916ca009dabb53e")
        gaps = document["observed_gaps"]
        self.assertEqual(len(gaps), 100)
        self.assertEqual(sum(case["before"]["ok"] for case in gaps), 70)
        self.assertEqual(sum(case["before"]["error"] == "parse_error" for case in gaps), 30)
        self.assertEqual(len({case["id"] for case in gaps}), len(gaps))
        candidates = {case["id"]: case for case in json.loads(INFERRED.read_text(encoding="utf-8"))["cases"]}
        for case in gaps:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["after"], {"ok": False, "error": "unsupported_token", "tokens": []})
                self.assertNotEqual(case["before"], case["after"])
                self.assertEqual(case["step"], candidates[case["id"]]["step"])
                self.assertEqual(case["before"], candidates[case["id"]]["candidate"])

    def test_new_neighbors_remain_inferred_and_fail_closed(self):
        document = json.loads(INFERRED.read_text(encoding="utf-8"))
        self.assertEqual(document["evidence"], "inferred-unqualified")
        cases = [case for case in document["cases"] if case["id"].startswith("strings_batch_")]
        self.assertEqual(len(cases), 80)
        by_id = {case["id"]: case for case in cases}
        for context in ("quoted", "here"):
            for name in ("pipeline_remains_gap", "statement_remains_gap", "depth_limit", "large_number_remains_gap", "braced_escape_remains_gap"):
                self.assertEqual(by_id[f"strings_batch_{context}_{name}"]["candidate"],
                                 {"ok": False, "error": "unsupported_token", "tokens": []})
            for name in ("missing_nested_close", "arithmetic_missing_operand", "nested_keyword", "nested_bad_scope"):
                self.assertEqual(by_id[f"strings_batch_{context}_{name}"]["candidate"],
                                 {"ok": False, "error": "parse_error", "tokens": []})
            self.assertEqual(by_id[f"strings_batch_{context}_inner_escape_spelling"]["candidate"]["tokens"][-1],
                             '$("line`ntext")')
            self.assertEqual(by_id[f"strings_batch_{context}_escaped_invalid_subexpression"]["candidate"]["tokens"][-1],
                             "$(1 + )")

    def test_source_inferred_special_variable_and_escape_adversaries(self):
        document = json.loads(INFERRED.read_text(encoding="utf-8"))
        self.assertEqual(document["evidence"], "inferred-unqualified")
        cases = [case for case in document["cases"] if case["id"].startswith("strings_followup_")]
        self.assertEqual(len(cases), 44)
        self.assertEqual(sum(case["candidate"]["ok"] for case in cases), 16)
        observed_ids = {case["id"] for case in json.loads(OBSERVED.read_text(encoding="utf-8"))["observed_gaps"]}
        self.assertFalse(observed_ids & {case["id"] for case in cases})
        for case in cases:
            if not case["candidate"]["ok"]:
                self.assertEqual(case["candidate"], {"ok": False, "error": "unsupported_token", "tokens": []})
            elif case["id"].endswith("question_literal_suffix"):
                self.assertEqual(case["candidate"]["tokens"][-1], "$?foo")
            elif case["id"].endswith("scoped_literal_double_colon"):
                self.assertEqual(case["candidate"]["tokens"][-1], "$a:b::")

    def test_mode_sensitive_inner_quotes_remain_source_inferred(self):
        document = json.loads(INFERRED.read_text(encoding="utf-8"))
        self.assertEqual(document["evidence"], "inferred-unqualified")
        cases = [case for case in document["cases"] if case["id"].startswith("strings_quote_boundary_")]
        self.assertEqual(len(cases), 16)
        observed_ids = {case["id"] for case in json.loads(OBSERVED.read_text(encoding="utf-8"))["observed_gaps"]}
        self.assertFalse(observed_ids & {case["id"] for case in cases})
        for case in cases:
            self.assertEqual(case["candidate"], {"ok": False, "error": "unsupported_token", "tokens": []})

    def test_raw_quote_boundaries_cover_openers_and_all_backtick_parities(self):
        document = json.loads(INFERRED.read_text(encoding="utf-8"))
        self.assertEqual(document["evidence"], "inferred-unqualified")
        cases = {case["id"]: case for case in document["cases"] if case["id"].startswith("strings_raw_quote_boundary_")}
        self.assertEqual(len(cases), 46)
        self.assertEqual(sum(case["candidate"]["ok"] for case in cases.values()), 16)
        observed_ids = {case["id"] for case in json.loads(OBSERVED.read_text(encoding="utf-8"))["observed_gaps"]}
        self.assertFalse(observed_ids & set(cases))
        for context in ("quoted", "here"):
            for size in range(1, 9):
                candidate = cases[f"strings_raw_quote_boundary_{context}_backtick_run_{size}_before_quote"]["candidate"]
                self.assertEqual(candidate, {"ok": False, "error": "unsupported_token", "tokens": []})
            for size in (2, 4, 6, 8):
                candidate = cases[f"strings_raw_quote_boundary_{context}_backtick_run_{size}_before_text"]["candidate"]
                self.assertTrue(candidate["ok"])
            self.assertFalse(cases[f"strings_raw_quote_boundary_{context}_empty_inner_double_quote"]["candidate"]["ok"])
            self.assertTrue(cases[f"strings_raw_quote_boundary_{context}_empty_inner_single_quote"]["candidate"]["ok"])


if __name__ == "__main__":
    unittest.main()
