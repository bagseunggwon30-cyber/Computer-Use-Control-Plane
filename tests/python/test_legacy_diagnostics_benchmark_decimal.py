"""Typed Decimal Int32 conversion, with separate full-operation Windows pairing."""
import json
from pathlib import Path
import sys
import unittest

from test_legacy_diagnostics_parity import reply, run_candidate
from test_legacy_diagnostics_benchmark_functional import (
    BASELINE_PATH, acquire_routes, compare_failure, original_contract, pure_contract, strict_equal,
)


def vectors():
    # These are source-derived expectations for IConvertible Decimal rounding,
    # including both accepted Int32 edges. Exponent and string controls retain
    # their existing Double conversion, rather than inheriting Decimal precision.
    decimal = [('-0.5000000000000000000000000001', -1), ('0.5', 0),
        ('0.5000000000000000000000000001', 1), ('1.4999999999999999999999999999', 1),
        ('1.5', 2), ('2.5', 2), ('-1.5', -2), ('-2.5', -2),
        ('2147483647.4999999999999999999', 2147483647), ('2147483647.5', None),
        ('-2147483648.5', -2147483648), ('-2147483648.5000000000000000001', None)]
    controls = [('0.5000000000000000000000000001', 0), ('1.4999999999999999999999999999', 2),
                ('2147483647.4999999999999999999', None)]
    return ([('decimal/' + raw, raw, expected) for raw, expected in decimal] +
            [('double/' + raw, raw + 'e0', expected) for raw, expected in controls] +
            [('string/' + raw, json.dumps(raw), expected) for raw, expected in controls])


def number_cases():
    fixtures, expectations = [], {}
    for identity, raw, converted in vectors():
        for field in ('p50_ms', 'p95_ms'):
            other = 'p95_ms' if field == 'p50_ms' else 'p50_ms'
            baseline = '{"results":[{"name":"windows","' + field + '":' + raw + ',"' + other + '":100}]}'
            for brief in (False, True):
                case_id = f'typed-number/{identity}/{field}/brief-{brief}'
                fixtures.append(dict(case_id=case_id, operation='benchmark', culture='en-US', brief=brief,
                    rest=['--iters', '1', '--baseline', BASELINE_PATH], replies=[reply()] * 4 + [True, baseline]))
                value = json.loads(raw)
                divisor = float(value) if field == 'p50_ms' else 100
                expectations[case_id] = dict(converted=converted, b50=converted if field == 'p50_ms' else 100, divisor=divisor)
    return fixtures, expectations


def assert_numeric_result(test, fixture, observed, expected):
    test.assertEqual(observed['state'], 'complete')
    test.assertEqual(observed['exit'], 0)
    test.assertEqual(observed['consumed'], 6)
    payload = observed['payload']
    test.assertEqual(payload['schema'], 'cucp.benchmark/v1')
    test.assertEqual(payload['status'], 'ok')
    comparison = payload['baseline_compare']
    if expected['converted'] is None:
        test.assertEqual(set(comparison), {'baseline_path', 'error', 'detail'})
        test.assertEqual(comparison['error'], 'baseline_load_failed')
        return
    test.assertNotIn('error', comparison)
    baseline = expected['b50']
    delta = 37 - baseline
    verdict = 'improved' if delta <= -10 else 'regressed' if delta >= 30 else 'neutral'
    percentage = round(delta / expected['divisor'] * 100, 1) if baseline > 0 else 0
    test.assertEqual(comparison, dict(baseline_path=BASELINE_PATH, compared_targets=1,
        improved_count=int(verdict == 'improved'), regressed_count=int(verdict == 'regressed'),
        rows=[dict(name='windows', baseline_p50_ms=baseline, current_p50_ms=37, delta_ms=delta,
                   delta_pct=percentage, verdict=verdict)]))


class BenchmarkDecimalPortableTests(unittest.TestCase):
    def test_typed_decimal_midpoints_boundaries_and_controls(self):
        fixtures, expected = number_cases()
        self.assertEqual(len(vectors()), 18)
        self.assertEqual(len(fixtures), 72)
        self.assertEqual(len({f['case_id'] for f in fixtures}), 72)
        for fixture, observed in zip(fixtures, run_candidate(fixtures)):
            with self.subTest(case=fixture['case_id']):
                assert_numeric_result(self, fixture, observed, expected[fixture['case_id']])
                self.assertEqual([effect['kind'] for effect in observed['effects']],
                    ['Clock', 'Native', 'Clock'] * 4 + ['FileExists', 'ReadText'])


@unittest.skipUnless(sys.platform == 'win32', 'Windows original/pure/actual typed benchmark conversion qualification')
class BenchmarkDecimalWindowsTests(unittest.TestCase):
    def test_typed_numeric_conversion_preserves_full_benchmark_contract(self):
        fixtures, expected = number_cases()
        capture, pure, records = acquire_routes(self, fixtures, 'benchmark-decimal-functional', case_source=Path(__file__))
        for fixture, p, o, a in zip(fixtures, pure, records['original'], records['candidate']):
            with self.subTest(case=fixture['case_id']), capture.comparison(fixture['case_id'], 'benchmark-typed-numeric'):
                assumption = expected[fixture['case_id']]
                # Require the captured Windows original to validate the inferred
                # outcomes before claiming that any numeric repair is qualified.
                for observed in (p, original_contract(o), original_contract(a)):
                    assert_numeric_result(self, fixture, observed, assumption)
                if assumption['converted'] is None:
                    compare_failure(self, fixture, o, p, a)
                else:
                    self.assertTrue(strict_equal(a, o), 'Successful numeric cases require exact actual-adapter records')
                    self.assertTrue(strict_equal(pure_contract(p), original_contract(o)))
                    self.assertEqual(p['brief'], o['console'].removesuffix('\r\n') if fixture.get('brief') else None)
                    self.assertEqual(p['json_depth'], 10)
                    self.assertIs(p['emit_json'], not fixture['brief'])
                    self.assertEqual(p['hashtable_paths'], [])
        capture.complete()


if __name__ == '__main__':
    unittest.main()
