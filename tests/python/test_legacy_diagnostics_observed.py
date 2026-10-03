"""Use only observed assertion fragments; missing raw arrays stay missing."""
import json
import sys
import unittest

from test_legacy_diagnostics_parity import ROOT, run_candidate
from test_legacy_diagnostics_retained import retained_candidate_cases

OBSERVATIONS = ROOT / 'tests/fixtures/legacy-diagnostics-observed-37090071710.json'


class DiagnosticObservedFragmentTests(unittest.TestCase):
    def test_observed_error_payload_fragments_without_claiming_full_original_arrays(self):
        expected = json.loads(OBSERVATIONS.read_text(encoding='utf-8'))
        self.assertTrue(expected['provenance']['complete_logs_available'])
        self.assertFalse(expected['provenance']['raw_route_arrays_available'])
        ids = set(expected['baseline_error_details']) | set(expected['audit_payload_fragments']) | {expected['boolean_baseline_row']['case_id']}
        fixtures = [f for f in retained_candidate_cases() if f['case_id'] in ids]
        self.assertEqual(len(fixtures), len(ids))
        for fixture, observed in zip(fixtures, run_candidate(fixtures)):
            identity = fixture['case_id']
            with self.subTest(case=identity):
                self.assertEqual(observed['state'], 'complete')
                payload = observed['payload']
                if identity in expected['baseline_error_details']:
                    self.assertEqual(payload['baseline_compare']['detail'], expected['baseline_error_details'][identity])
                elif identity in expected['audit_payload_fragments']:
                    for field, value in expected['audit_payload_fragments'][identity].items():
                        self.assertEqual(payload[field], value)
                else:
                    self.assertEqual(payload['baseline_compare']['rows'], [expected['boolean_baseline_row']['expected_row']])
                    self.assertEqual(payload['baseline_compare']['regressed_count'], 1)

    @unittest.skipUnless(sys.platform == 'win32', 'Observed date fragment requires actual Windows NLS metadata')
    def test_observed_korean_date_fragment_uses_windows_locale_metadata(self):
        expected = json.loads(OBSERVATIONS.read_text(encoding='utf-8'))['korean_date_fragment']
        fixture = next(f for f in retained_candidate_cases() if f['case_id'] == expected['case_id'])
        observed = run_candidate([fixture])[0]
        self.assertIn(expected['expected_fragment'], observed['payload']['baseline_compare']['detail'])


if __name__ == '__main__':
    unittest.main()
