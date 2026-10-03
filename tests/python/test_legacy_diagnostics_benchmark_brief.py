"""Observed Windows Brief absence is evidence, never a replacement payload."""
import copy
import hashlib
import json
import unittest

from test_legacy_diagnostics_parity import ROOT
from test_legacy_diagnostics_benchmark_functional import (
    compare_calendar_case, compare_production_entry, original_contract, raw_exact_summary,
)
from test_legacy_diagnostics_benchmark_decimal import compare_number_case, number_cases

OBSERVED = ROOT / 'tests/fixtures/legacy-benchmark-brief-observed-37103413852.json'


class BenchmarkBriefObservedTests(unittest.TestCase):
    def setUp(self):
        self.observed = json.loads(OBSERVED.read_text(encoding='utf-8'))
        self.expected = number_cases()[1]

    def compare(self, pair, index):
        if pair['family'] == 'calendar':
            compare_calendar_case(self, pair['fixtures'], pair['pure'], pair, index)
        else:
            compare_number_case(self, pair['fixtures'], pair['pure'], pair, self.expected, index)

    def test_observed_windows_nonbrief_and_brief_pairs_preserve_public_absence(self):
        self.assertEqual(hashlib.sha256(OBSERVED.read_bytes()).hexdigest(),
                         '1acbac7ef7611061d20d47d2956208109fda9c453a76d6ea0f72c2c23305b335')
        self.assertEqual(self.observed['run_id'], 37103413852)
        self.assertEqual(len(self.observed['pairs']), 3)
        for pair in self.observed['pairs']:
            self.assertFalse(pair['fixtures'][0]['brief'])
            self.assertTrue(pair['fixtures'][1]['brief'])
            self.compare(pair, 0)
            self.compare(pair, 1)
            self.assertIsNone(original_contract(pair['original'][1])['payload'])
            summary = raw_exact_summary(pair['fixtures'], pair['pure'], pair)
            self.assertTrue(summary[0]['public_payload_observed'])
            self.assertFalse(summary[1]['public_payload_observed'])
            self.assertFalse(summary[1]['pure_kernel_contract_exact'])
            self.assertTrue(summary[1]['actual_adapter_record_exact'])

    def test_none_or_missing_payload_on_nonbrief_cannot_become_success(self):
        for original in self.observed['pairs']:
            for route in ('original', 'candidate', 'pure'):
                for remove in (False, True):
                    pair = copy.deepcopy(original)
                    if remove:
                        del pair[route][0]['payload']
                    else:
                        pair[route][0]['payload'] = None
                    with self.subTest(family=pair['family'], route=route, remove=remove), self.assertRaises(AssertionError):
                        self.compare(pair, 0)

    def test_terminal_failure_or_changed_effects_cannot_use_brief_absence(self):
        for original in self.observed['pairs']:
            for route in ('original', 'candidate', 'pure'):
                for mutation in ('terminal', 'extra_error', 'exit', 'effects', 'consumed'):
                    pair = copy.deepcopy(original)
                    record = pair[route][1]
                    if mutation == 'terminal':
                        record.update(state='error', payload=None, error='captured terminal failure')
                    elif mutation == 'extra_error':
                        record['error'] = 'unexpected error in a supposedly complete record'
                    elif mutation == 'exit':
                        record['exit'] = 1
                    elif mutation == 'effects':
                        record['effects'] = [] if route == 'pure' else dict(kind='array', items=[])
                    else:
                        record['consumed'] = 5
                    with self.subTest(family=pair['family'], route=route, mutation=mutation), self.assertRaises(AssertionError):
                        self.compare(pair, 1)
        terminal = dict(state='error', payload=None, error='preserved error', effects=None)
        self.assertEqual(original_contract(terminal), terminal)

    def test_brief_requires_its_same_input_nonbrief_data_witness(self):
        for original in self.observed['pairs']:
            for mutation in ('input', 'mode', 'pure_payload', 'control_payload', 'public_payload'):
                pair = copy.deepcopy(original)
                if mutation == 'input':
                    pair['fixtures'][0]['culture'] = 'different-culture'
                elif mutation == 'mode':
                    pair['fixtures'][0]['brief'] = True
                elif mutation == 'pure_payload':
                    pair['pure'][1]['payload'] = None
                elif mutation == 'control_payload':
                    pair['original'][0]['payload'] = None
                else:
                    pair['candidate'][1]['payload'] = copy.deepcopy(pair['candidate'][0]['payload'])
                with self.subTest(family=pair['family'], mutation=mutation), self.assertRaises(AssertionError):
                    self.compare(pair, 1)

    def test_brief_console_rendering_and_internal_numeric_data_remain_strict(self):
        for original in self.observed['pairs']:
            for mutation in ('console', 'emit_json', 'numeric', 'schema'):
                pair = copy.deepcopy(original)
                if mutation == 'console':
                    pair['candidate'][1]['console'] += 'unexpected output'
                elif mutation == 'emit_json':
                    pair['pure'][1]['emit_json'] = True
                elif mutation == 'numeric':
                    pair['pure'][1]['payload']['results'][0]['p50_ms'] = 38
                else:
                    pair['pure'][1]['payload']['schema'] = 'other-schema'
                with self.subTest(family=pair['family'], mutation=mutation), self.assertRaises(AssertionError):
                    self.compare(pair, 1)

    def test_production_entry_is_required_and_cannot_fall_back_to_another_record(self):
        pair = copy.deepcopy(self.observed['pairs'][0])
        with self.assertRaises(AssertionError):
            compare_production_entry(self, pair, 0)
        pair['production'] = copy.deepcopy(pair['candidate'])
        compare_production_entry(self, pair, 0)
        compare_production_entry(self, pair, 1)
        pair['production'][1]['console'] = 'wrong production output'
        with self.assertRaises(AssertionError):
            compare_production_entry(self, pair, 1)


if __name__ == '__main__':
    unittest.main()
