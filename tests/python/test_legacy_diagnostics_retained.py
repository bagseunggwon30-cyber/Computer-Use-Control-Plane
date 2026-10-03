"""Captured-only qualification of the two retained diagnostic candidates.

This is an additional gate, independent of the production-selection manifest.
The existing nine-operation original/production gates and all their assertions
remain intact. No case here authorizes provider, desktop, account or model use.
"""
import copy
import hashlib
import json
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_legacy_diagnostics_parity import (
    ACCEPTED_TREE, BODY_HASHES, FILE_OPERATIONS, PROJECT, ROOT, cases, decode_wire,
    reply, run_candidate,
)
from test_legacy_diagnostics_adapters import (
    ADAPTER, BRIDGE, RETAINED_DIAGNOSTICS, UNCERTAIN_MESSAGE,
    actual_adapter_arguments, captured_failures, changes_owned_state, diagnostic_uses_session,
)

from legacy_diagnostic_evidence import CAPTURE_ENV, DiagnosticEvidence, file_identity
from legacy_diagnostic_json_neighbors import cases as json_neighbor_cases
from legacy_diagnostic_number_neighbors import cases as number_neighbor_cases

# Historical corpus membership must never depend on future production cutovers.
QUALIFICATION_DIAGNOSTICS = frozenset({'benchmark', 'audit-summary'})
EXPECTED_CANDIDATE_PARTITION = dict(exact=660, owned_failure=8, terminal_failure=0)
EXPECTED_PRODUCTION_PARTITION = dict(exact=660, owned_failure=8, terminal_failure=0)
EXPECTED_AUDIT_PRODUCTION_CASES = 258
EXPECTED_BENCHMARK_PRODUCTION_CASES = 410
EXPECTED_BENCHMARK_OWNED_FAILURE_IDS = frozenset({
    "existing/24", "existing/25", "existing/26", "existing/27",
    "existing/55", "existing/56", "existing/57", "existing/58",
})


def adversarial_json_cases():
    """Raw file text crosses existing captured ReadText/ReadLines seams only.

    IDs describe inputs, not presumed PowerShell outcomes. Source-derived repair
    expectations below are separate from the mandatory Windows differential.
    """
    result = []

    def benchmark(identity, raw, **extra):
        result.append(dict(case_id='baseline/' + identity, operation='benchmark',
            rest=['--iters', '1', '--baseline', r'C:\fixture\baseline.json'],
            replies=[reply()] * 4 + [True, raw], **extra))

    def audit(identity, lines, **extra):
        result.append(dict(case_id='audit/' + identity, operation='audit-summary',
            rest=[], replies=[True, [dict(full_name=r'C:\fixture\audit\trajectory-inert.ndjson',
                last_write_time='2026-10-02T00:00:00Z')], lines], **extra))

    def baseline(value, field='p50_ms'):
        other = 'p95_ms' if field == 'p50_ms' else 'p50_ms'
        return '{"results":[{"name":"windows","' + field + '":' + value + ',"' + other + '":100}]}'

    for literal in ('NaN', 'Infinity', '-Infinity', 'nan', 'infinity', '+Infinity', '1e999', '-1e999'):
        benchmark('number/' + literal, baseline(literal))
        audit('number/' + literal, ['{"macro":' + literal + ',"ts":' + literal + ',"exit_code":' + literal + '}'])
    for field in ('p50_ms', 'p95_ms'):
        for literal in (r'"\/Date(0)\/"', r'"\/Date(-1000)\/"', r'"\/Date(0+0900)\/"', '"/Date(0)/"', '"01/01/1970 00:00:00"'):
            benchmark('date/' + field + '/' + literal, baseline(literal, field))
    benchmark('date/ko-KR', baseline(r'"\/Date(0)\/"'), culture='ko-KR')
    audit('date/nested', [r'{"ts":"\/Date(0)\/","macro":["date","\/Date(-1000)\/"],"exit_code":"\/Date(0)\/"}'])
    audit('date/overflow', [r'{"ts":"\/Date(9223372036854775807)\/","macro":"overflow"}'])
    # Retain discovered object-interpolation gaps as exact Windows probes, not
    # as portable expectations or an allowlist of accepted mismatches.
    audit('object/empty', ['{"macro":{},"action":"fallback","reason":{},"ts":{}}'])
    audit('object/nested', ['{"macro":{"nested":{"value":1},"items":[1,2]},"exit_code":{}}'])

    for name in ('', 'PSObject', 'PSBase', 'PSAdapted', 'PSExtended', 'PSTypeNames',
                 'psobject', 'ToString', 'Count', 'Length', '__proto__', 'constructor'):
        key = json.dumps(name)
        benchmark('property/' + name, '{' + key + ':1,"results":[{"name":"windows","p50_ms":100,"p95_ms":100}]}')
        audit('property/' + name, ['{' + key + ':1,"macro":"property"}', '{"macro":"after"}'])
    for identity, raw in (
        ('nested-empty', '{"ignored":{"":1},"results":[]}'),
        ('empty-before-child-collision', '{"":{"x":1,"X":2},"results":[]}'),
        ('type-names-before-child-empty', '{"PSTypeNames":{"":1},"results":[]}'),
        ('reserved-after-child-empty', '{"PSObject":{"":1},"results":[]}'),
        ('overwritten-empty', '{"ignored":{"":1},"ignored":null,"results":[]}'),
        ('overwritten-reserved', '{"ignored":{"PSObject":1},"ignored":null,"results":[]}'),
        ('overwritten-type-names', '{"ignored":{"PSTypeNames":1},"ignored":null,"results":[]}'),
        ('case-collision', '{"x":1,"X":2,"results":[]}'),
        ('case-collision-before-empty', '{"x":1,"X":2,"":3,"results":[]}'),
        ('empty-before-case-collision', '{"":3,"x":1,"X":2,"results":[]}'),
        ('exact-duplicate', '{"results":[{"name":"windows","p50_ms":1}],"results":[{"name":"windows","p50_ms":100,"p95_ms":100}]}'),
        ('type-null', '{"__type":null,"results":[]}'),
        ('type-object', '{"__type":{},"results":[]}'),
        ('type-array', '{"__type":[],"results":[]}'),
        ('type-null-collision', '{"__type":null,"__Type":"kept","results":[]}'),
        ('type-removed-before-collision', '{"__type":"inert","__Type":"kept","results":[]}'),
        ('type-overwritten-null', '{"__type":"inert","__type":null,"__Type":"kept","results":[]}'),
        ('type-overwritten-nonnull', '{"__type":null,"__type":"inert","__Type":"kept","results":[]}'),
        ('scalar-row', '{"results":{"name":"windows","p50_ms":100,"p95_ms":100}}'),
        ('array-root', '[{"results":[{"name":"windows","p50_ms":100,"p95_ms":100}]}]'),
        ('missing-p95', '{"results":[{"name":"windows","p50_ms":100}]}'),
        ('null-p50', '{"results":[{"name":"windows","p50_ms":null,"p95_ms":100}]}'),
        ('unreached-date', r'{"results":[{"name":"unmatched","p50_ms":"\/Date(0)\/","p95_ms":100}]}'),
        ('unreached-nonfinite', '{"results":[{"name":"windows","p50_ms":null,"p95_ms":NaN}]}'),
        ('null-root', 'null'),
        ('empty-text', ''),
    ):
        benchmark(identity, raw)
        audit(identity, [raw, '{"macro":"after"}'])
    # Int32 rounding/overflow, text vs numeric, and unsupported containers are
    # qualification probes too; adding a case never changes the expected oracle.
    for value in ('2147483648', '-2147483649', '2147483647.49', '"1.5"', 'true',
                  '[100]', '[]', '{}', '{"value":1}', '{"items":[1,2]}', '"bad"'):
        benchmark('cast/' + value, baseline(value))
    # Keep raw rendering and Brief/JSON-only behavior visible for every new input.
    originals = copy.deepcopy(result)
    for fixture in originals:
        fixture['case_id'] += '/brief-json-only'
        fixture['brief'] = True
        fixture['rest'].append('--json-only')
        result.append(fixture)
    return result


def subtraction_boundary_cases():
    # Append after the original 302 cases. Negative captured clocks deliberately
    # exercise the full signed arithmetic domain; they are not live timings.
    low, high = -(2**31), 2**31 - 1
    vectors = [
        ('current-37-baseline-min', 37, low, low),
        ('current-37-baseline-max', 37, high, high),
        ('zero-baseline-min', 0, low, low),
        ('zero-baseline-max', 0, high, high),
        ('exact-min', low, 0, 0),
        ('exact-max', high, 0, 0),
        ('below-min', low, 1, 1),
        ('above-max', high, -1, -1),
        ('inside-min', low, -1, -1),
        ('inside-max', high, 1, 1),
        ('widest-positive', high, low, low),
        ('widest-negative', low, high, high),
        ('p95-min', 37, 100, low),
        ('p95-max', 37, 100, high),
        ('p95-invalid-after-wide-p50', 37, low, 'bad'),
    ]
    result = []
    for name, current, p50, p95 in vectors:
        for brief in (False, True):
            result.append(dict(case_id='subtraction/' + name + ('/brief-json-only' if brief else ''),
                operation='benchmark', rest=['--iters', '1', '--baseline', r'C:\fixture\baseline.json'] + (['--json-only'] if brief else []),
                brief=brief, clocks=[current, 37, 37, 37], replies=[reply()] * 4 + [True,
                    json.dumps(dict(results=[dict(name='windows', p50_ms=p50, p95_ms=p95)]))]))
    return result


def retained_candidate_cases():
    retained = [copy.deepcopy(f) for f in cases() if f['operation'] in QUALIFICATION_DIAGNOSTICS]
    for index, fixture in enumerate(retained):
        fixture['case_id'] = 'existing/' + str(index)
    return retained + adversarial_json_cases() + subtraction_boundary_cases() + json_neighbor_cases() + number_neighbor_cases()


def retained_candidate_adapter_arguments(pinned_source):
    # Deliberately never add -ProductionEntry or consult the manifest. That path
    # would run original retained functions and could falsely qualify candidates.
    return ['-Source', str(pinned_source), '-AdapterSource', str(ADAPTER),
            '-BridgeSource', str(BRIDGE)]


def assert_actual_candidate(test, fixture, before, after):
    old_effects = decode_wire(before['effects'])
    new_effects = decode_wire(after['effects'])
    failures = captured_failures(fixture, old_effects)
    uncertain = next((f for f in failures if changes_owned_state(f['effect']) and
                      f['effect']['kind'] != 'AssertAuthorized'), None)
    if uncertain is not None:
        test.assertEqual(new_effects, old_effects[:uncertain['trace_index'] + 1])
        test.assertEqual(after['consumed'], uncertain['reply_index'] + 1)
        test.assertEqual(after['state'], 'error')
        test.assertEqual(after['error'], UNCERTAIN_MESSAGE)
        test.assertEqual(after['console'], '')
        return 'owned_failure'
    if before['state'] == 'error' and any(changes_owned_state(e) for e in old_effects):
        test.assertEqual(new_effects, old_effects)
        test.assertEqual(after['consumed'], before['consumed'])
        test.assertEqual(after['state'], 'error')
        test.assertEqual(after['error'], 'mutation_may_have_occurred=true; automatic_retry=false; ' + before['error'])
        test.assertEqual(after['console'], before['console'])
        return 'terminal_failure'
    test.assertEqual(after, before)
    return 'exact'


class RetainedDiagnosticPortableTests(unittest.TestCase):
    def test_both_reports_use_exact_delegates_and_keep_historical_originals(self):
        self.assertEqual(RETAINED_DIAGNOSTICS, set())
        source = BRIDGE.read_text(encoding='utf-8-sig')
        benchmark = "function Invoke-MacroBenchmark {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'benchmark' -Rest $Rest}"
        self.assertEqual(re.findall(r'^function Invoke-MacroBenchmark[^\n]*', source, re.M), [benchmark])
        self.assertEqual((len(benchmark.encode()), hashlib.sha256(benchmark.encode()).hexdigest()),
            (128, 'a19c0690237a12e02824080770153baa48957612af8a90fa5f2aeefd5354fb63'))
        audit = "function Invoke-MacroAuditSummary {param([string[]]$Rest) return _Invoke-LegacyDiagnosticFamily -Operation 'audit-summary' -Rest $Rest}"
        self.assertEqual(re.findall(r'^function Invoke-MacroAuditSummary[^\n]*', source, re.M), [audit])
        self.assertEqual((len(audit.encode()), hashlib.sha256(audit.encode()).hexdigest()),
            (135, '752661100756660ec332af82e4c3f440300c80199c6b222d67f206fc66ffe79c'))
        self.assertIn('"audit-summary" { return Invoke-MacroAuditSummary -Rest $rest }', source)
        pinned_original = subprocess.check_output(['git', 'show', f'{ACCEPTED_TREE}:scripts/cucp.ps1'], cwd=ROOT).decode('utf-8-sig')
        for name in ('Benchmark', 'AuditSummary'):
            start = re.search(r'^function Invoke-Macro' + name + r' \{', pinned_original, re.M).start()
            body = pinned_original[start:pinned_original.index('\n}', start) + 2].encode()
            self.assertEqual((len(body), hashlib.sha256(body).hexdigest()), BODY_HASHES[name])
        self.assertTrue(diagnostic_uses_session('audit-summary', 'production'))
        self.assertTrue(diagnostic_uses_session('benchmark', 'production'))
        pinned = Path('inert-pinned-original.ps1')
        arguments = retained_candidate_adapter_arguments(pinned)
        self.assertEqual(arguments, actual_adapter_arguments(pinned, 'draft'))
        self.assertNotIn('-ProductionEntry', arguments)
        self.assertNotEqual(arguments, actual_adapter_arguments(pinned, 'production'))

    def test_adversarial_corpus_is_closed_and_preserves_all_66_retained_cases(self):
        fixtures = retained_candidate_cases()
        existing = [f for f in cases() if f['operation'] in QUALIFICATION_DIAGNOSTICS]
        self.assertEqual(len(existing), 66)
        self.assertEqual(QUALIFICATION_DIAGNOSTICS, frozenset({'benchmark', 'audit-summary'}))
        self.assertEqual(hashlib.sha256(json.dumps(fixtures[:66], ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            '6ed498a1ad4ac56717a728f5482c86e1c6be1a0312f11ac7298182d70fc2b83a')
        self.assertEqual(len(adversarial_json_cases()), 236)
        self.assertEqual(len(subtraction_boundary_cases()), 30)
        self.assertEqual(len(json_neighbor_cases()), 140)
        self.assertEqual(len(number_neighbor_cases()), 196)
        self.assertEqual(len(fixtures), 668)
        self.assertEqual(hashlib.sha256(json.dumps(fixtures[:668], ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            '0990ff64fee42212576c81225e63b664f01ffe383f31b9b8816969099c4ee461')
        self.assertEqual(hashlib.sha256(json.dumps(fixtures[:472], ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            '3ed6f4f492813a682179b5f6231aa57a805f8196aba19e93561b7ff17969b166')
        self.assertEqual(hashlib.sha256(json.dumps(fixtures[:332], ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            '355d50fa883eb909813b939f9d26725338ef4145ab471ad22c3af2cd5e310630')
        # Pin every value and case ID from the previous candidate batch, not
        # merely its case count. New probes append without altering that corpus.
        self.assertEqual(hashlib.sha256(json.dumps(fixtures[:302], ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            '6a3949f67bf355818b6a61b53910eca6affe1768993d7727767aa3060a20b561')
        self.assertEqual([{k: v for k, v in f.items() if k != 'case_id'} for f in fixtures[:66]], existing)
        self.assertEqual(len({f['case_id'] for f in fixtures}), len(fixtures))
        self.assertEqual({f['operation'] for f in fixtures}, QUALIFICATION_DIAGNOSTICS)
        self.assertEqual(json.loads(json.dumps(fixtures)), fixtures)
        observations = run_candidate(fixtures)
        self.assertEqual(len(observations), len(fixtures))
        for fixture, observed in zip(fixtures, observations):
            with self.subTest(case=fixture['case_id']):
                self.assertNotIn('Fixture exhausted', observed.get('error', ''))
                if fixture['case_id'].startswith('existing/'):
                    continue
                self.assertEqual(observed['state'], 'complete', observed)
                self.assertEqual(observed['consumed'], len(fixture['replies']))
                self.assertTrue(all(effect['kind'] in {'Clock', 'Native', 'FileExists', 'ReadText', 'ListFiles', 'ReadLines'} for effect in observed['effects']))

    def test_source_derived_finite_double_aggregation_and_type_controls(self):
        selected = [f for f in number_neighbor_cases() if f['case_id'] in {
            'number/audit/scalar/1e16', 'number/audit/scalar/-0e0',
            'number/audit/scalar/123456789012344.5e0',
            'number/audit/key-collision', 'number/audit/string-control',
            'number/audit/decimal-control',
            'number/baseline/object/de-DE/1.2345678901234567e0'}]
        expected_maps = {
            'number/audit/scalar/1e16': {'1E+16': 1},
            'number/audit/scalar/-0e0': {'0': 1},
            'number/audit/scalar/123456789012344.5e0': {'123456789012345': 1},
            'number/audit/key-collision': {'1.23456789012346': 2},
            'number/audit/string-control': {'1e16': 1},
            'number/audit/decimal-control': {'1.2345678901234567': 1},
        }
        self.assertEqual(len(selected), 7)
        for fixture, observed in zip(selected, run_candidate(selected)):
            with self.subTest(case=fixture['case_id']):
                self.assertEqual(observed['state'], 'complete')
                if fixture['operation'] == 'audit-summary':
                    self.assertEqual(observed['payload']['by_macro'], expected_maps[fixture['case_id']])
                else:
                    self.assertIn('@{value=1,23456789012346}', observed['payload']['baseline_compare']['detail'])

    def test_finite_display_mathematical_model_against_independent_decimal_rounding(self):
        # This validates the bounded arithmetic model independently, not PS5.1
        # parsing or historical CRT behavior. Only the Windows oracle can do that.
        import decimal
        import math
        import random
        import struct
        rng = random.Random(0xC0C0)
        values = [0.0, -0.0, float.fromhex('0x0.0000000000001p-1022'),
                  float.fromhex('0x1.fffffffffffffp+1023')]
        while len(values) < 256:
            value = struct.unpack('>d', rng.getrandbits(64).to_bytes(8, 'big'))[0]
            if math.isfinite(value):
                values.append(value)
        fixtures = []
        expected = []
        for value in values:
            token = format(value, '.17e')  # Force the diagnostic Double path.
            fixtures.append(dict(operation='audit-summary', rest=[], replies=[True,
                [dict(full_name='inert', last_write_time='2026-10-02T00:00:00Z')],
                ['{"macro":' + token + '}']]))
            with decimal.localcontext() as context:
                context.prec = 15
                context.rounding = decimal.ROUND_HALF_UP
                rounded = +decimal.Decimal.from_float(abs(value))
                exponent = rounded.adjusted()
                if rounded == 0:
                    text = '0'
                elif -4 <= exponent < 15:
                    text = format(rounded.normalize(), 'f')
                else:
                    coefficient, power = format(rounded.normalize(), 'E').split('E')
                    text = coefficient + 'E' + ('-' if int(power) < 0 else '+') + str(abs(int(power))).zfill(2)
                expected.append(('-' if value < 0 else '') + text)
        for value, text, observed in zip(values, expected, run_candidate(fixtures)):
            with self.subTest(binary=value.hex()):
                self.assertEqual(observed['state'], 'complete')
                self.assertEqual(observed['payload']['by_macro'], {text: 1})

    def test_source_derived_typed_scalar_repairs_do_not_coerce_json_strings(self):
        fixtures = adversarial_json_cases()
        selected = [f for f in fixtures if not f.get('brief') and
            (f['case_id'].startswith('baseline/date/') or f['case_id'] in {
                'baseline/number/NaN', 'baseline/number/Infinity', 'baseline/number/-Infinity',
                'audit/number/NaN', 'audit/number/Infinity', 'audit/number/-Infinity',
                'audit/number/nan', 'audit/number/1e999'})]
        for fixture, observed in zip(selected, run_candidate(selected)):
            with self.subTest(case=fixture['case_id']):
                payload = observed['payload']
                if fixture['operation'] == 'benchmark':
                    detail = payload['baseline_compare']['detail']
                    if '\\/Date(' in fixture['replies'][-1]:
                        self.assertIn("Invalid cast from 'DateTime' to 'Int32'.", detail)
                    elif '/date/' in fixture['case_id']:
                        self.assertIn('Input string was not in a correct format.', detail)
                    else:
                        self.assertIn('Value was either too large or too small for an Int32.', detail)
                elif fixture['case_id'] in {'audit/number/nan', 'audit/number/1e999'}:
                    self.assertEqual(payload['event_count'], 0)
                else:
                    value = fixture['case_id'].rsplit('/', 1)[-1]
                    self.assertEqual(payload['event_count'], 1)
                    self.assertEqual(payload['by_macro'], {value: 1})
                    self.assertEqual(payload['earliest_ts'], value)

    def test_source_derived_property_validation_order_and_overwrite(self):
        empty = ('Cannot process argument because the value of argument "name" is not valid. '
                 'Change the value of the "name" argument and run the operation again.')
        duplicate = ("Cannot convert the JSON string because a dictionary that was converted "
                     "from the string contains the duplicated keys 'pstypenames' and 'PSTypeNames'.")
        expected = {
            'property/': empty,
            'property/PSObject': 'The member name "PSObject" is reserved.',
            'property/psobject': 'The member name "psobject" is reserved.',
            'property/PSTypeNames': duplicate,
            'empty-before-child-collision': empty,
            'type-names-before-child-empty': duplicate,
            'reserved-after-child-empty': empty,
            'overwritten-empty': None,
            'overwritten-reserved': None,
            'overwritten-type-names': None,
            'type-removed-before-collision': None,
            'type-overwritten-nonnull': None,
            'unreached-date': None,
            'unreached-nonfinite': None,
        }
        fixtures = [f for f in adversarial_json_cases() if not f.get('brief') and
                    f['case_id'].removeprefix('baseline/') in expected and f['operation'] == 'benchmark']
        self.assertEqual(len(fixtures), len(expected))
        for fixture, observed in zip(fixtures, run_candidate(fixtures)):
            identity = fixture['case_id'].removeprefix('baseline/')
            with self.subTest(case=identity):
                comparison = observed['payload']['baseline_compare']
                if expected[identity] is None:
                    self.assertNotIn('error', comparison)
                else:
                    self.assertEqual(comparison['detail'], expected[identity])

    def test_source_derived_container_cast_errors_do_not_unwrap_singletons(self):
        expected = {
            'baseline/cast/[100]': 'Cannot convert the "System.Object[]" value of type "System.Object[]" to type "System.Int32".',
            'baseline/cast/[]': 'Cannot convert the "System.Object[]" value of type "System.Object[]" to type "System.Int32".',
        }
        fixtures = [f for f in adversarial_json_cases() if f['case_id'] in expected]
        self.assertEqual(len(fixtures), len(expected))
        for fixture, observed in zip(fixtures, run_candidate(fixtures)):
            with self.subTest(case=fixture['case_id']):
                self.assertEqual(observed['payload']['baseline_compare']['detail'], expected[fixture['case_id']])

    def test_source_derived_subtraction_promotion_and_p95_evaluation(self):
        fixtures = subtraction_boundary_cases()
        observations = run_candidate(fixtures)
        self.assertEqual(len(observations), len(fixtures))
        for fixture, observed in zip(fixtures, observations):
            with self.subTest(case=fixture['case_id']):
                self.assertEqual(observed['state'], 'complete')
                self.assertEqual(observed['consumed'], 6)
                comparison = observed['payload']['baseline_compare']
                baseline = json.loads(fixture['replies'][-1])['results'][0]
                if baseline['p95_ms'] == 'bad':
                    self.assertEqual(comparison['error'], 'baseline_load_failed')
                    self.assertEqual(comparison['detail'], 'Cannot convert value "bad" to type "System.Int32". Error: "Input string was not in a correct format."')
                    continue
                self.assertNotIn('error', comparison)
                self.assertEqual(comparison['compared_targets'], 1)
                delta = fixture['clocks'][0] - baseline['p50_ms']
                verdict = 'improved' if delta <= -10 else 'regressed' if delta >= 30 else 'neutral'
                self.assertEqual(comparison['rows'], [dict(name='windows', baseline_p50_ms=baseline['p50_ms'],
                    current_p50_ms=fixture['clocks'][0], delta_ms=delta,
                    delta_pct=round(delta / baseline['p50_ms'] * 100, 1) if baseline['p50_ms'] > 0 else 0,
                    verdict=verdict)])
                self.assertEqual(comparison['improved_count'], int(verdict == 'improved'))
                self.assertEqual(comparison['regressed_count'], int(verdict == 'regressed'))


@unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell 5.1 retained candidate qualification')
class RetainedDiagnosticWindowsTests(unittest.TestCase):
    maxDiff = 2500

    def test_pinned_original_production_entry_pure_candidate_and_actual_candidate(self):
        fixtures = retained_candidate_cases()
        planned = ['git-head', 'git-status', 'pinned-source', 'dotnet-info', 'pure-build', 'pure']
        planned += [name + '-' + group for group in ('file', 'runtime') for name in ('original', 'production', 'candidate')]
        capture = DiagnosticEvidence(os.environ.get(CAPTURE_ENV) or
            ROOT / '.migration-logs/diagnostics/retained-diagnostics', fixtures, planned)
        self.addCleanup(capture.finish)
        with capture.comparison('acquisition', 'all-routes'):
            host = os.environ.get('CUCP_DIAGNOSTICS_TEST_HOST')
            powershell = shutil.which('powershell.exe')
            dotnet = os.environ.get('DOTNET') or shutil.which('dotnet')
            capture.provenance(accepted_tree=ACCEPTED_TREE,
                powershell_requirement='5.1; checked independently by both unchanged oracle scripts',
                executables={name: file_identity(path) for name, path in (
                    ('powershell', powershell), ('dotnet', dotnet), ('native_host', host))},
                source_files={str(path.relative_to(ROOT)): file_identity(path) for path in (
                    BRIDGE, ADAPTER, Path(__file__), ROOT / 'tests/python/legacy_diagnostic_evidence.py',
                    ROOT / 'tests/python/legacy_diagnostic_json_neighbors.py',
                    ROOT / 'tests/python/legacy_diagnostic_number_neighbors.py',
                    ROOT / 'tests/python/test_legacy_diagnostics_parity.py',
                    ROOT / 'tests/python/test_legacy_diagnostics_adapters.py',
                    ROOT / 'tests/fixtures/legacy-diagnostics-file-oracle.ps1',
                    ROOT / 'tests/fixtures/legacy-diagnostics-runtime-oracle.ps1',
                    ROOT / 'tests/fixtures/legacy-diagnostics-adapter-guards.ps1',
                    *sorted(PROJECT.glob('*.cs')), PROJECT / 'PcuCp.LegacyDiagnostics.ContractTests.csproj',
                    PROJECT.parent / 'PcuCp.NativeHost/LegacyDiagnosticCulture.cs',
                    PROJECT.parent / 'PcuCp.LegacyTaskForm/LegacyTaskFormKernel.cs',
                    *sorted((PROJECT.parent / 'PcuCp.LegacyDiagnostics').glob('*.cs')))},
                fixture_cultures=sorted({f.get('culture', 'en-US') for f in fixtures}))
            with capture.comparison('setup', 'host-configuration'):
                self.assertTrue(host, 'Retained candidate qualification requires CUCP_DIAGNOSTICS_TEST_HOST')
                self.assertTrue(Path(host).is_file(), 'Matching diagnostic NativeHost does not exist')
            for name, arguments in (('git-head', ['rev-parse', 'HEAD']), ('git-status', ['status', '--porcelain'])):
                process = capture.run(name, ['git'] + arguments, cwd=ROOT, timeout=30)
                capture.success(self, name, process)
                capture.provenance(**{name.replace('-', '_'): process.stdout.decode('utf-8', errors='replace').strip()})
            process = capture.run('dotnet-info', [dotnet, '--info'], cwd=ROOT, timeout=30)
            capture.success(self, 'dotnet-info', process)
            process = capture.run('pure-build', [dotnet, 'build', str(PROJECT), '-c', 'Release'], cwd=ROOT, timeout=180)
            capture.success(self, 'pure-build', process)
            dll = PROJECT / 'bin/Release/net8.0/PcuCp.LegacyDiagnostics.ContractTests.dll'
            capture.provenance(pure_assembly=file_identity(dll),
                pure_runtime_config=file_identity(dll.with_suffix('.runtimeconfig.json')))
            process = capture.run('pure', [dotnet, str(dll), '--fixtures'],
                case_ids=[f['case_id'] for f in fixtures], input=json.dumps(fixtures).encode(), cwd=ROOT, timeout=120)
            pure = capture.rows(self, 'pure', process, len(fixtures))
            records = {name: [None] * len(fixtures) for name in ('original', 'production', 'candidate')}
            with tempfile.TemporaryDirectory(prefix='CUCP retained diagnostics 한국어 ') as temporary:
                temp = Path(temporary)
                source = temp / 'original.ps1'
                process = capture.run('pinned-source', ['git', 'show', f'{ACCEPTED_TREE}:scripts/cucp.ps1'], cwd=ROOT, timeout=30)
                capture.success(self, 'pinned-source', process)
                source.write_bytes(process.stdout)
                capture.provenance(pinned_source=file_identity(source))
                for file_group in (True, False):
                    selected = [(i, f) for i, f in enumerate(fixtures) if (f['operation'] in FILE_OPERATIONS) == file_group]
                    inputs = temp / 'cases.json'
                    inputs.write_text(json.dumps([f for _, f in selected]), encoding='utf-8-sig')
                    runner = ROOT / ('tests/fixtures/legacy-diagnostics-file-oracle.ps1' if file_group else 'tests/fixtures/legacy-diagnostics-runtime-oracle.ps1')
                    command = [powershell, '-NoProfile', '-NonInteractive', '-File', str(runner), '-InputPath', str(inputs)]
                    routes = {
                        'original': ['-Source', str(source)],
                        'production': actual_adapter_arguments(source, 'production'),
                        'candidate': retained_candidate_adapter_arguments(source),
                    }
                    for name, arguments in routes.items():
                        route = name + ('-file' if file_group else '-runtime')
                        process = capture.run(route, command + arguments,
                            case_ids=[f['case_id'] for _, f in selected],
                            metadata=dict(case_indices=[i for i, _ in selected], input=file_identity(inputs), oracle=file_identity(runner)),
                            timeout=900, env={**os.environ, 'CUCP_NATIVE_HOST': str(Path(host).resolve()), 'CUCP_EXECUTION_DIAGNOSTICS': '1'})
                        observations = capture.rows(self, route, process, len(selected))
                        for (index, _), observed in zip(selected, observations):
                            records[name][index] = observed
        partition = dict(exact=0, owned_failure=0, terminal_failure=0)
        production_partition = dict(exact=0, owned_failure=0, terminal_failure=0)
        audit_production_cases = benchmark_production_cases = 0
        candidate_owned_ids, production_owned_ids = set(), set()
        for index, fixture in enumerate(fixtures):
            original = records['original'][index]
            with self.subTest(case=fixture['case_id'], route='production-entry'), capture.comparison(fixture['case_id'], 'production-entry'):
                if diagnostic_uses_session(fixture['operation'], 'production'):
                    category = assert_actual_candidate(self, fixture, original, records['production'][index])
                    production_partition[category] += 1
                    if category == 'owned_failure': production_owned_ids.add(fixture['case_id'])
                else:
                    self.assertEqual(records['production'][index], original)
                    production_partition['exact'] += 1
            if fixture['operation'] == 'audit-summary':
                audit_production_cases += 1
            else:
                benchmark_production_cases += 1
            if fixture['operation'] in QUALIFICATION_DIAGNOSTICS:
                with self.subTest(case=fixture['case_id'], route='production-v-candidate'), capture.comparison(fixture['case_id'], 'production-v-candidate'):
                    self.assertEqual(records['production'][index], records['candidate'][index])
            with self.subTest(case=fixture['case_id'], route='pure-candidate'), capture.comparison(fixture['case_id'], 'pure-candidate'):
                actual = pure[index]
                self.assertEqual(actual['state'], original['state'])
                self.assertEqual(actual['effects'], decode_wire(original['effects']))
                self.assertEqual(actual['consumed'], original['consumed'])
                if actual['state'] == 'error':
                    self.assertEqual(actual['error'], original['error'])
                else:
                    self.assertEqual(actual['exit'], original['exit'])
                    if original['payload'] is not None:
                        self.assertEqual(actual['payload'], decode_wire(original['payload']))
            with self.subTest(case=fixture['case_id'], route='actual-candidate'), capture.comparison(fixture['case_id'], 'actual-candidate'):
                category = assert_actual_candidate(self, fixture, original, records['candidate'][index])
                partition[category] += 1
                if category == 'owned_failure': candidate_owned_ids.add(fixture['case_id'])
        with capture.comparison('final', 'partition-counts'):
            self.assertEqual(sum(partition.values()), len(fixtures))
            self.assertEqual(partition, EXPECTED_CANDIDATE_PARTITION)
            self.assertEqual(production_partition, EXPECTED_PRODUCTION_PARTITION)
            self.assertEqual(audit_production_cases, EXPECTED_AUDIT_PRODUCTION_CASES)
            self.assertEqual(benchmark_production_cases, EXPECTED_BENCHMARK_PRODUCTION_CASES)
            self.assertEqual(candidate_owned_ids, EXPECTED_BENCHMARK_OWNED_FAILURE_IDS)
            self.assertEqual(production_owned_ids, EXPECTED_BENCHMARK_OWNED_FAILURE_IDS)
        capture.complete()
        print(f"Compared {len(fixtures)} retained diagnostic cases through original/production-entry/pure-candidate/actual-candidate routes: {partition}; production: {production_partition}; audit production/direct exact pairs: {audit_production_cases}; benchmark production/direct exact pairs: {benchmark_production_cases}", flush=True)


if __name__ == '__main__':
    unittest.main()
