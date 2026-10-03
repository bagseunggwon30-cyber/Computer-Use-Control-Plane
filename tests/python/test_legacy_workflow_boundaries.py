"""Inert candidate boundary contracts, replay, and fresh PS5 qualification hooks.

Historical replay is not a new Windows run. New neighboring cases are explicitly
inferred and every newly accepted result must match the retained PS5 oracle.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

import test_legacy_workflow_parity as workflow

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/legacy-workflow-boundary-candidate.json'
REPAIR_OBSERVATIONS = FIXTURE.with_name('legacy-workflow-ps51-boundary-observed-37079778520.json')


def boundary_fixture():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def repair_observations():
    return json.loads(REPAIR_OBSERVATIONS.read_text(encoding='utf-8'))


def matches_contract(actual, expected):
    return all(actual.get(key) == value for key, value in expected.items())


class WorkflowBoundaryFixtureTests(unittest.TestCase):
    def test_observed_boundary_evidence_retains_exact_provenance(self):
        root = boundary_fixture()
        provenance = root['observed_provenance']
        self.assertEqual(provenance['evidence'], 'observed-windows-powershell-5.1')
        self.assertEqual(provenance['run_id'], '37074340659')
        self.assertEqual(provenance['tested_commit'], '48bb1651499d0857b4886b3f5cd8b2ed04d5e8a0')
        self.assertEqual(provenance['baseline_tree'], workflow.BASELINE_TREE)
        self.assertEqual(provenance['log_sha256'], 'd7090be7d8bcb52fd4d2a2b156f862c40a5dc66a66a507374916ca009dabb53e')
        historical = {gap['step']: gap['before'] for gap in workflow.observed_literal_fixtures()['historical_gaps']}
        self.assertEqual(len(root['observed']), 10)
        for case in root['observed']:
            self.assertEqual(case['expected'], historical[case['step']])

    def test_new_neighbors_are_separate_and_never_claimed_observed(self):
        root = boundary_fixture()
        self.assertEqual(root['inferred_provenance']['evidence'], 'inferred-unqualified')
        cases = root['inferred']
        self.assertGreaterEqual(len(cases), 200)
        self.assertEqual(len(cases), len({case['id'] for case in cases}))
        for case in cases:
            self.assertLessEqual(len(case['step']), 65536)
            self.assertEqual(case['candidate']['ok'], bool(case['candidate']['tokens']))
            if case['candidate']['ok']:
                self.assertEqual(case['candidate']['error'], '')
        for prefix in ('signed_', 'stop_', 'unquoted_dollar_', 'adjacent_escape_', 'bracket_', 'whitespace_', 'nul_'):
            self.assertTrue(any(case['id'].startswith(prefix) for case in cases), prefix)

    def test_boundary_repair_preserves_all_original_rows(self):
        root = repair_observations()
        provenance = root['provenance']
        self.assertEqual(provenance['evidence'], 'observed-windows-powershell-5.1')
        self.assertEqual(provenance['run_id'], '37079778520')
        self.assertEqual(provenance['tested_commit'], '0e6e6748f475ee1526b82f3751f11da8ba42e64a')
        self.assertEqual(provenance['baseline_tree'], workflow.BASELINE_TREE)
        self.assertEqual(provenance['log_sha256'], '1c43ee04c706b02e83d7c4363c80a06c22fdb1f37945f0220ee1d5353da1a61c')
        self.assertEqual(provenance['log_line'], 271)
        rows = root['observed_gaps']
        self.assertEqual(len(rows), 33)
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(digest, '8b8b9a1eb3d6925fe0efa03d5ceb26df5b0e83a25b084d996e8924794e6b3e1f')
        self.assertEqual(provenance['rows_sha256'], digest)
        targets = set(root['repair_target_ids'])
        self.assertEqual(targets, {'stop_cooked_marker_64', 'stop_cooked_marker_65', 'nul_198', 'nul_199', 'nul_203'})
        predictions = {case['id']: case for case in boundary_fixture()['inferred']}
        for row in rows:
            self.assertEqual(set(row), {'id', 'step', 'before', 'after'})
            if row['id'] in targets:
                self.assertTrue(row['before']['ok'] and row['after']['ok'])
                self.assertEqual(predictions[row['id']]['candidate'], row['before'])
                self.assertEqual(predictions[row['id']]['candidate_basis']['run_id'], provenance['run_id'])

    def test_candidate_remains_excluded_from_native_host(self):
        project = workflow.KERNEL.with_name('PcuCp.NativeHost.csproj').read_text(encoding='utf-8')
        self.assertIn('<Compile Remove="LegacyWorkflowLiteralParser.cs" />', project)
        source = workflow.LITERAL_PARSER.read_text(encoding='utf-8')
        for forbidden in ('Process.Start', 'ProcessStartInfo', 'System.Management.Automation', 'Invoke-Expression'):
            self.assertNotIn(forbidden, source)


@unittest.skipUnless(sys.platform == 'win32', 'Fresh Windows PowerShell 5.1 boundary qualification')
class WorkflowBoundaryWindowsParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.WorkflowWindowsParityTests.setUpClass.__func__(cls)

    differential = workflow.WorkflowWindowsParityTests.differential

    def test_observed_boundaries_match_original_ps51(self):
        cases = boundary_fixture()['observed']
        inputs = [{'kind': 'parse', 'step': case['step']} for case in cases]
        for case, (fixture, expected, actual) in zip(cases, self.differential(inputs)):
            with self.subTest(case=case['id']):
                self.assertEqual(workflow.normalized(expected), case['expected'], 'Historical PS5 observation changed')
                self.assertEqual(workflow.normalized(actual), case['expected'])

    def test_boundary_repairs_replay_recorded_ps51_results(self):
        root = repair_observations()
        cases = root['observed_gaps']
        targets = set(root['repair_target_ids'])
        inputs = [{'kind': 'parse', 'step': case['step']} for case in cases]
        gaps = []
        for case, (fixture, expected, actual) in zip(cases, self.differential(inputs)):
            if workflow.normalized(expected) != workflow.normalized(actual):
                gaps.append({'id': case['id'], 'step': fixture['step'], 'before': workflow.normalized(expected), 'after': workflow.normalized(actual)})
            with self.subTest(case=case['id']):
                self.assertEqual(workflow.normalized(expected), case['before'], 'Recorded PS5 boundary observation changed')
                if actual.get('ok') or case['id'] in targets:
                    self.assertEqual(workflow.normalized(actual), workflow.normalized(expected), 'Observed boundary repair changed')
        if gaps:
            print('WORKFLOW OBSERVED BOUNDARY GAPS REMAIN: ' + json.dumps(gaps, ensure_ascii=True))
        if os.environ.get('CUCP_REQUIRE_WORKFLOW_PARSER_PARITY') == '1':
            self.assertEqual(gaps, [], 'Recorded boundary gaps also block PSParser retirement')

    def test_inferred_boundaries_never_relax_ps51_rejections(self):
        cases = boundary_fixture()['inferred']
        inputs = [{'kind': 'parse', 'step': case['step']} for case in cases]
        gaps = []
        for case, (fixture, expected, actual) in zip(cases, self.differential(inputs)):
            # Preserve rejected and reinterpreted rows even when their assertion fails.
            if workflow.normalized(expected) != workflow.normalized(actual):
                gaps.append({'id': case['id'], 'step': fixture['step'], 'before': workflow.normalized(expected), 'after': workflow.normalized(actual)})
            with self.subTest(case=case['id']):
                self.assertTrue(matches_contract(actual, case['candidate']), 'Managed boundary contract changed')
                if actual.get('ok'):
                    self.assertTrue(expected.get('ok'), 'Candidate relaxed a PS5 rejection')
                    self.assertEqual(actual['tokens'], expected['tokens'], 'Candidate reinterpreted PS5 tokens')
        if gaps:
            print('WORKFLOW BOUNDARY EDGES NOT QUALIFIED: ' + json.dumps(gaps, ensure_ascii=True))
        if os.environ.get('CUCP_REQUIRE_WORKFLOW_PARSER_PARITY') == '1':
            self.assertEqual(gaps, [], 'Boundary gaps also block PSParser retirement')


if __name__ == '__main__':
    unittest.main()
