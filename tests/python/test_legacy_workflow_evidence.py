"""Regression evidence must survive the negative assertions it explains."""
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import test_legacy_workflow_parity as workflow
import test_legacy_workflow_boundaries as boundary


class WorkflowFailureEvidenceTests(unittest.TestCase):
    def test_false_acceptance_and_reinterpretation_keep_both_sides(self):
        cases = [
            {"id": "rejected", "step": "inert rejected text", "candidate": {"ok": True, "error": "", "tokens": ["changed"]}},
            {"id": "reinterpreted", "step": "inert accepted text", "candidate": {"ok": True, "error": "", "tokens": ["changed"]}},
        ]
        expected = [{"ok": False, "error": "parse_error", "tokens": []},
                    {"ok": True, "error": "", "tokens": ["original"]}]
        methods = [
            (workflow.WorkflowWindowsParityTests.test_broad_parser_probe_never_relaxes_rejected_constructs,
             "WORKFLOW PARSER NOT QUALIFIED: "),
            (workflow.WorkflowWindowsParityTests.test_inferred_literal_edges_never_relax_ps51_rejections,
             "WORKFLOW INFERRED LITERAL EDGES NOT QUALIFIED: "),
            (boundary.WorkflowBoundaryWindowsParityTests.test_inferred_boundaries_never_relax_ps51_rejections,
             "WORKFLOW BOUNDARY EDGES NOT QUALIFIED: "),
        ]
        for method, prefix in methods:
            with self.subTest(method=method.__name__):
                class Probe(unittest.TestCase):
                    def differential(self, inputs):
                        return [(fixture, before, case["candidate"]) for fixture, before, case in zip(inputs, expected, cases)]

                    def runTest(self):
                        method(self)

                output, result = io.StringIO(), unittest.TestResult()
                with patch.object(workflow, "syntax_probe_cases", return_value=cases), \
                     patch.object(workflow, "inferred_literal_fixtures", return_value={"cases": cases}), \
                     patch.object(boundary, "boundary_fixture", return_value={"inferred": cases}), \
                     patch.dict(os.environ, {"CUCP_REQUIRE_WORKFLOW_PARSER_PARITY": "0"}), \
                     contextlib.redirect_stdout(output):
                    Probe().run(result)
                self.assertEqual(len(result.failures), 2)
                self.assertEqual(result.errors, [])
                line = next(line for line in output.getvalue().splitlines() if line.startswith(prefix))
                rows = json.loads(line[len(prefix):])
                self.assertEqual([row["before"] for row in rows], expected)
                self.assertEqual([row["after"] for row in rows], [case["candidate"] for case in cases])


if __name__ == "__main__":
    unittest.main()
