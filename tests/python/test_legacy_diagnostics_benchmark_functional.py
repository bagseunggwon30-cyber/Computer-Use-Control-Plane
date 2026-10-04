"""Bounded benchmark function checks beside the unchanged exact diagnostic gate.

Only a contained baseline_load_failed detail and its JSON Console token may
differ. Raw observations and exact comparison results are always retained.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

from legacy_diagnostic_evidence import CAPTURE_ENV, DiagnosticEvidence, file_identity
from test_legacy_diagnostics_adapters import ADAPTER, BRIDGE, actual_adapter_arguments
from test_legacy_diagnostics_parity import ACCEPTED_TREE, PROJECT, ROOT, decode_wire, reply, run_candidate

DETAIL_MARKER = '<benchmark runtime diagnostic prose>'
BASELINE_PATH = r'C:\fixture\baseline.json'


def calendar_cases():
    fixtures = []
    # The first day is a control: modern DateTime's default formatting already
    # gives it a special fallback. The next day actually reaches the range error.
    for day, milliseconds in ((1, -62135596800000), (2, -62135510400000)):
        for field in ('p50_ms', 'p95_ms'):
            for member in (False, True):
                raw = '"\\/Date(' + str(milliseconds) + ')\\/"'
                if member:
                    raw = '{"date":' + raw + '}'
                other = 'p95_ms' if field == 'p50_ms' else 'p50_ms'
                baseline = '{"results":[{"name":"windows","' + field + '":' + raw + ',"' + other + '":100}]}'
                for brief in (False, True):
                    fixtures.append(dict(case_id=f'calendar/day-{day}/{field}/member-{member}/brief-{brief}',
                        operation='benchmark', culture='fa-IR', brief=brief,
                        rest=['--iters', '1', '--baseline', BASELINE_PATH],
                        replies=[reply()] * 4 + [True, baseline]))
    return fixtures


def strict_equal(left, right):
    # Unlike Python == alone, this cannot let booleans impersonate numbers.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def failure_payload(payload):
    if not isinstance(payload, dict) or payload.get('schema') != 'cucp.benchmark/v1' or payload.get('status') != 'ok':
        raise AssertionError('Prose allowance requires the complete benchmark report')
    comparison = payload.get('baseline_compare')
    if not isinstance(comparison, dict) or set(comparison) != {'baseline_path', 'error', 'detail'}:
        raise AssertionError('Prose allowance requires exactly the failed baseline fields')
    if comparison['error'] != 'baseline_load_failed' or comparison['baseline_path'] != BASELINE_PATH:
        raise AssertionError('Stable baseline error/path changed')
    detail = comparison['detail']
    if not isinstance(detail, str) or not 8 <= len(detail) <= 4096 or '\0' in detail or not any(c.isalpha() for c in detail):
        raise AssertionError('Runtime diagnostic must remain useful bounded text')
    masked = copy.deepcopy(payload)
    masked['baseline_compare']['detail'] = DETAIL_MARKER
    return masked


def wire_property(value, name):
    if value.get('kind') != 'object':
        raise AssertionError('Expected tagged object')
    matches = [p['value'] for p in value['properties'] if p['name'] == name]
    if len(matches) != 1:
        raise AssertionError('Expected one tagged property: ' + name)
    return matches[0]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AssertionError('Duplicate Console JSON field')
        result[key] = value
    return result


def mask_record(record, fixture):
    require_complete_public_record(record, fixture)
    if fixture.get('brief'):
        raise AssertionError('Brief has no public payload and cannot use a detail prose allowance')
    payload = decode_wire(record['payload'])
    failure_payload(payload)
    masked = copy.deepcopy(record)
    detail = wire_property(wire_property(masked['payload'], 'baseline_compare'), 'detail')
    if detail.get('kind') != 'scalar' or not isinstance(detail.get('value'), str):
        raise AssertionError('Detail must remain one tagged string')
    detail['value'] = DETAIL_MARKER
    if not fixture.get('brief'):
        console = record['console']
        parsed = json.loads(console, object_pairs_hook=unique_object)
        if not strict_equal(parsed, payload):
            raise AssertionError('Console JSON differs from its captured payload')
        # Preserve every Console byte outside the one serialized detail value.
        matches = list(re.finditer(r'"detail"\s*:\s*("(?:[^"\\]|\\.)*")', console))
        if len(matches) != 1 or json.loads(matches[0][1]) != payload['baseline_compare']['detail']:
            raise AssertionError('Expected exactly one raw Console detail token')
        match = matches[0]
        masked['console'] = console[:match.start(1)] + json.dumps(DETAIL_MARKER) + console[match.end(1):]
    return masked


def pure_contract(record):
    return {key: record[key] for key in ('state', 'error', 'exit', 'payload', 'effects', 'consumed') if key in record}


def original_contract(record):
    result = pure_contract(record)
    for key in ('payload', 'effects'):
        # Preserve absent observations as None in the raw comparison. This is
        # not a success rule: each functional comparator validates the rendering
        # mode and completion before permitting a Brief-only absent payload.
        if key in result and result[key] is not None:
            result[key] = decode_wire(result[key])
    return result


def require_complete_public_record(record, fixture):
    if (fixture.get('operation') != 'benchmark' or
        set(record) != {'state', 'payload', 'exit', 'console', 'effects', 'consumed'} or
        record['state'] != 'complete' or type(record['exit']) is not int or record['exit'] != 0):
        raise AssertionError('Benchmark qualification requires an intact successful public record')
    if not isinstance(record['console'], str) or type(record['consumed']) is not int:
        raise AssertionError('Invalid public Console or reply count')
    if not isinstance(record['effects'], dict) or record['effects'].get('kind') != 'array':
        raise AssertionError('Public effects must remain a tagged array')
    if fixture.get('brief'):
        if record['payload'] is not None:
            raise AssertionError('Brief must preserve the observed absence of a public payload')
    elif not isinstance(record['payload'], dict) or record['payload'].get('kind') != 'object':
        raise AssertionError('Non-Brief must expose its complete tagged report')


def paired_nonbrief(test, fixtures, pure, records, index):
    fixture = fixtures[index]
    test.assertIs(fixture['brief'], True)
    test.assertGreater(index, 0)
    control = fixtures[index - 1]
    test.assertIs(control['brief'], False)
    test.assertTrue(strict_equal({k: v for k, v in fixture.items() if k not in ('case_id', 'brief')},
                                 {k: v for k, v in control.items() if k not in ('case_id', 'brief')}),
                    'Brief data evidence must come from the same input with only rendering changed')
    return control, pure[index - 1], records['original'][index - 1], records['candidate'][index - 1]


def compare_brief(test, fixture, original, pure, actual, control):
    control_fixture, control_pure, control_original, control_actual = control
    test.assertIs(fixture['brief'], True)
    test.assertIs(control_fixture['brief'], False)
    for record in (original, actual):
        require_complete_public_record(record, fixture)
    for record in (control_original, control_actual):
        require_complete_public_record(record, control_fixture)
    # Public Brief comparison remains exact, including payload=None. Do not
    # invent a public payload from the candidate or from the paired report.
    test.assertTrue(strict_equal(actual, original))
    test.assertEqual(original['consumed'], len(fixture['replies']))
    for key in ('state', 'exit', 'consumed', 'effects'):
        test.assertTrue(strict_equal(original[key], control_original[key]))
        test.assertTrue(strict_equal(actual[key], control_actual[key]))
        expected = decode_wire(original[key]) if key == 'effects' else original[key]
        test.assertTrue(strict_equal(pure[key], expected))
    test.assertTrue(strict_equal(pure_contract(pure), pure_contract(control_pure)))
    test.assertIsInstance(pure.get('payload'), dict)
    test.assertEqual(pure['json_depth'], 10)
    test.assertIs(pure['emit_json'], False)
    test.assertEqual(pure['hashtable_paths'], [])
    test.assertIsInstance(pure['brief'], str)
    test.assertEqual(pure['brief'] + '\r\n', original['console'])


def compare_failure(test, fixture, original, pure, actual):
    # The original's actual Windows outcome is asserted, never inferred from its
    # catch block or substituted with a handwritten expected error sentence.
    test.assertTrue(strict_equal(mask_record(actual, fixture), mask_record(original, fixture)))
    test.assertEqual(original['consumed'], len(fixture['replies']))
    left, right = pure_contract(pure), original_contract(original)
    test.assertEqual(left['state'], 'complete')
    test.assertIs(type(left['exit']), int)
    test.assertEqual(left['exit'], 0)
    left['payload'] = failure_payload(left.get('payload'))
    right['payload'] = failure_payload(right['payload'])
    test.assertTrue(strict_equal(left, right))
    test.assertEqual(pure['json_depth'], 10)
    test.assertIs(pure['emit_json'], not fixture.get('brief', False))
    test.assertEqual(pure['hashtable_paths'], [])
    test.assertEqual(pure['brief'], original['console'].removesuffix('\r\n') if fixture.get('brief') else None)


def compare_calendar_case(test, fixtures, pure, records, index):
    fixture, p, o, a = fixtures[index], pure[index], records['original'][index], records['candidate'][index]
    if fixture['brief']:
        control = paired_nonbrief(test, fixtures, pure, records, index)
        cf, cp, co, ca = control
        compare_failure(test, cf, co, cp, ca)
        compare_brief(test, fixture, o, p, a, control)
    else:
        compare_failure(test, fixture, o, p, a)


def raw_exact_summary(fixtures, pure, records):
    return [dict(case_id=fixture['case_id'], public_payload_observed=o.get('payload') is not None,
                 pure_kernel_contract_exact=strict_equal(pure_contract(p), original_contract(o)),
                 actual_adapter_record_exact=strict_equal(a, o))
            for fixture, p, o, a in zip(fixtures, pure, records['original'], records['candidate'])]


def compare_production_entry(test, records, index):
    test.assertIn('production', records, 'Fresh qualification must execute the current public entry')
    test.assertTrue(strict_equal(records['production'][index], records['candidate'][index]),
                    'Current production entry must match the independently invoked candidate exactly')


def acquire_routes(test, fixtures, label, *, case_source=None):
    capture = DiagnosticEvidence(Path(os.environ.get(CAPTURE_ENV) or
        ROOT / '.migration-logs/diagnostics/retained-diagnostics') / label, fixtures,
        ['git-head', 'git-status', 'dotnet-info', 'pure-build', 'pure', 'pinned-source', 'original', 'candidate', 'production'])
    test.addCleanup(capture.finish)
    with capture.comparison('acquisition', label):
        host = os.environ.get('CUCP_DIAGNOSTICS_TEST_HOST')
        dotnet = os.environ.get('DOTNET') or shutil.which('dotnet')
        powershell = shutil.which('powershell.exe')
        test.assertTrue(host and Path(host).is_file(), 'Matching diagnostic NativeHost is required')
        runner = ROOT / 'tests/fixtures/legacy-diagnostics-runtime-oracle.ps1'
        capture.provenance(accepted_tree=ACCEPTED_TREE, qualification_kind='benchmark-functional',
            allowance='Only benchmark baseline_compare.detail and its one serialized Console value; no existing exact assertion changed',
            executables={name: file_identity(path) for name, path in (('powershell', powershell), ('dotnet', dotnet), ('native_host', host))},
            source_files={str(path.relative_to(ROOT)): file_identity(path) for path in (
                BRIDGE, ADAPTER, runner, Path(__file__), case_source or Path(__file__), ROOT / 'tests/python/legacy_diagnostic_evidence.py',
                ROOT / 'tests/python/test_legacy_diagnostics_parity.py', ROOT / 'tests/python/test_legacy_diagnostics_adapters.py',
                *sorted(PROJECT.glob('*.cs')), PROJECT / 'PcuCp.LegacyDiagnostics.ContractTests.csproj',
                PROJECT.parent / 'PcuCp.NativeHost/LegacyDiagnosticCulture.cs',
                PROJECT.parent / 'PcuCp.LegacyTaskForm/LegacyTaskFormKernel.cs',
                *sorted((PROJECT.parent / 'PcuCp.LegacyDiagnostics').glob('*.cs')))})
        for name, argv in (('git-head', ['git', 'rev-parse', 'HEAD']), ('git-status', ['git', 'status', '--porcelain']),
                           ('dotnet-info', [dotnet, '--info']), ('pure-build', [dotnet, 'build', str(PROJECT), '-c', 'Release'])):
            process = capture.run(name, argv, cwd=ROOT, timeout=180)
            capture.success(test, name, process)
        dll = PROJECT / 'bin/Release/net8.0/PcuCp.LegacyDiagnostics.ContractTests.dll'
        capture.provenance(pure_assembly=file_identity(dll), pure_runtime_config=file_identity(dll.with_suffix('.runtimeconfig.json')))
        ids = [fixture['case_id'] for fixture in fixtures]
        process = capture.run('pure', [dotnet, str(dll), '--fixtures'], input=json.dumps(fixtures).encode(), case_ids=ids, cwd=ROOT, timeout=120)
        pure = capture.rows(test, 'pure', process, len(fixtures))
        with tempfile.TemporaryDirectory(prefix='cucp-benchmark-functional-') as temporary:
            source, inputs = Path(temporary) / 'original.ps1', Path(temporary) / 'cases.json'
            process = capture.run('pinned-source', ['git', 'show', f'{ACCEPTED_TREE}:scripts/cucp.ps1'], cwd=ROOT, timeout=30)
            capture.success(test, 'pinned-source', process)
            source.write_bytes(process.stdout)
            inputs.write_text(json.dumps(fixtures), encoding='utf-8-sig')
            command = [powershell, '-NoProfile', '-NonInteractive', '-File', str(runner), '-InputPath', str(inputs)]
            records = {}
            for name, args in (('original', ['-Source', str(source)]), ('candidate', actual_adapter_arguments(source, 'draft')),
                               ('production', actual_adapter_arguments(source, 'production'))):
                process = capture.run(name, command + args, case_ids=ids,
                    metadata=dict(pinned_source=file_identity(source), inputs=file_identity(inputs), oracle=file_identity(runner)),
                    cwd=ROOT, timeout=900, env={**os.environ, 'CUCP_NATIVE_HOST': str(Path(host).resolve()), 'CUCP_EXECUTION_DIAGNOSTICS': '1'})
                records[name] = capture.rows(test, name, process, len(fixtures))
    with capture.comparison('raw-exact-summary', label):
        exact = raw_exact_summary(fixtures, pure, records)
        for index, row in enumerate(exact):
            row['production_entry_record_exact'] = strict_equal(records['production'][index], records['candidate'][index])
        (capture.directory / 'raw-exact-summary.json').write_text(json.dumps(exact, indent=2) + '\n', encoding='utf-8')
    return capture, pure, records


class BenchmarkCalendarPortableTests(unittest.TestCase):
    def test_full_benchmark_contains_calendar_format_failure(self):
        fixtures = calendar_cases()
        self.assertEqual(len(fixtures), 16)
        self.assertEqual(len({f['case_id'] for f in fixtures}), 16)
        for fixture, observed in zip(fixtures, run_candidate(fixtures)):
            with self.subTest(case=fixture['case_id']):
                self.assertEqual(observed['state'], 'complete')
                self.assertEqual(observed['exit'], 0)
                self.assertEqual(observed['consumed'], 6)
                failure_payload(observed['payload'])
                self.assertEqual(observed['payload']['slo_pass_rate_pct'], 100)
                self.assertEqual(observed['payload']['recommendation'], 'all_within_slo')
                self.assertEqual([effect['kind'] for effect in observed['effects']],
                    ['Clock', 'Native', 'Clock'] * 4 + ['FileExists', 'ReadText'])

    def test_allowance_rejects_state_exit_numeric_path_error_and_other_string_changes(self):
        self.assertFalse(strict_equal(pure_contract(dict(state='error', error='first')),
                                      pure_contract(dict(state='error', error='second'))))
        def wire(value):
            if isinstance(value, dict):
                return dict(kind='object', properties=[dict(name=k, value=wire(v)) for k, v in value.items()])
            if isinstance(value, list):
                return dict(kind='array', items=[wire(v) for v in value])
            return dict(kind='scalar', value=value)
        payload = dict(schema='cucp.benchmark/v1', status='ok', count=1, label='kept',
            baseline_compare=dict(baseline_path=BASELINE_PATH, error='baseline_load_failed', detail='Original conversion diagnostic'))
        fixture = dict(operation='benchmark', brief=False)
        def record(value):
            return dict(state='complete', exit=0, consumed=6, effects=wire([]), payload=wire(value), console=json.dumps(value))
        original = record(payload)
        changed = copy.deepcopy(payload); changed['baseline_compare']['detail'] = 'Different calendar diagnostic'
        self.assertTrue(strict_equal(mask_record(original, fixture), mask_record(record(changed), fixture)))
        for key, value in (('count', 2), ('count', True), ('label', 'changed')):
            changed = copy.deepcopy(payload); changed[key] = value
            self.assertFalse(strict_equal(mask_record(original, fixture), mask_record(record(changed), fixture)))
        for key, value in (('error', 'other'), ('baseline_path', 'C:\\other'), ('detail', ''), ('detail', 'x' * 4097)):
            changed = copy.deepcopy(payload); changed['baseline_compare'][key] = value
            with self.assertRaises(AssertionError):
                mask_record(record(changed), fixture)
        for key, value in (('state', 'error'), ('exit', 1), ('exit', False)):
            changed = copy.deepcopy(original); changed[key] = value
            with self.assertRaises(AssertionError):
                mask_record(changed, fixture)
        for key, value in (('consumed', 5), ('effects', wire([dict(kind='Native', name='unexpected')]))):
            changed = copy.deepcopy(original); changed[key] = value
            self.assertFalse(strict_equal(mask_record(original, fixture), mask_record(changed, fixture)))
        with self.assertRaises(AssertionError):
            mask_record(original, dict(operation='audit-summary', brief=False))
        changed = copy.deepcopy(original); changed['console'] = '\n' + changed['console']
        self.assertFalse(strict_equal(mask_record(original, fixture), mask_record(changed, fixture)))
        brief_original = copy.deepcopy(original); brief_original['console'] = 'original brief\r\n'
        brief_changed = copy.deepcopy(brief_original); brief_changed['console'] = 'changed brief\r\n'
        with self.assertRaises(AssertionError):
            mask_record(brief_original, dict(operation='benchmark', brief=True))
        with self.assertRaises(AssertionError):
            mask_record(brief_changed, dict(operation='benchmark', brief=True))
        changed = copy.deepcopy(original); changed['console'] = changed['console'].replace('"count": 1', '"count": 2')
        with self.assertRaises(AssertionError):
            mask_record(changed, fixture)


@unittest.skipUnless(sys.platform == 'win32', 'Windows original/pure/actual benchmark functional qualification')
class BenchmarkCalendarWindowsTests(unittest.TestCase):
    def test_calendar_failures_preserve_full_benchmark_contract(self):
        fixtures = calendar_cases()
        capture, pure, records = acquire_routes(self, fixtures, 'benchmark-calendar-functional')
        for index, fixture in enumerate(fixtures):
            with self.subTest(case=fixture['case_id']), capture.comparison(fixture['case_id'], 'benchmark-functional'):
                compare_production_entry(self, records, index)
                compare_calendar_case(self, fixtures, pure, records, index)
        capture.complete()


if __name__ == '__main__':
    unittest.main()
