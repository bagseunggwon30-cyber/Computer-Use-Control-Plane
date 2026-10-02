"""Actual PS5.1 interaction hooks -> shared transport -> compiled native host.

All native/model/storage dependencies are the existing oracle's inert captures.
CUCP_INTERACTION_TEST_HOST explicitly selects this qualification and fails closed
if its compiled host or required Windows PowerShell interpreter is unavailable.
"""
import copy
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_legacy_interaction_parity import (
    ACCEPTED_TREE, BASELINE_TREE, OPERATIONS, ORACLE, ROOT, boundary_cases,
    captured_failure_effects, cases, decode_wire, first_difference, run_oracle,
)

RUNNER = ROOT / 'tests/fixtures/legacy-interaction-adapter-oracle.ps1'
ADAPTER = ROOT / 'scripts/cucp-legacy-interaction-adapter.ps1'
SHARED = ROOT / 'scripts/cucp.ps1'
OWNED_STATE_EFFECTS = {'Native', 'Appshot', 'Vision', 'PointCacheWrite', 'AnchorAppend',
                       'TrajectoryAppend', 'Notice', 'Cucp'}


def adapter_public_source(root=ROOT):
    """The checked manifest explicitly chooses draft or promoted delegates."""
    data=json.loads((root/'.github/migration-adapters.json').read_text(encoding='utf-8'))
    known={'execution','precision','cdp','interaction','diagnostics','file-images'}
    if not isinstance(data,dict) or set(data)!={'test_adapters'}:
        raise ValueError('Expected the exact migration adapter manifest schema.')
    families=data['test_adapters']
    if not isinstance(families,list) or any(type(v) is not str or v not in known for v in families) or len(families)!=len(set(families)):
        raise ValueError('Adapter families must be unique known names.')
    return root/('scripts/cucp.ps1' if 'interaction' in families else 'scripts/cucp-legacy-interaction-adapter.ps1')


def powershell(*, required=False, portable=False):
    configured = os.environ.get('CUCP_INTERACTION_POWERSHELL')
    executable = configured or shutil.which('pwsh' if portable else 'powershell.exe')
    if executable and (Path(executable).is_file() or shutil.which(executable)):
        return str(executable)
    message = 'Windows PowerShell 5.1 is required for interaction adapter qualification'
    if required:
        raise AssertionError(message)
    raise unittest.SkipTest(message)


def configured_native_host():
    value = os.environ.get('CUCP_INTERACTION_TEST_HOST')
    if not value:
        raise unittest.SkipTest('Set CUCP_INTERACTION_TEST_HOST to qualify the actual interaction adapter')
    host = Path(value)
    if not host.is_file():
        raise AssertionError(f'Configured interaction native host missing: {host}')
    if host.suffix.lower() not in ('.exe', '.dll'):
        raise AssertionError('CUCP_INTERACTION_TEST_HOST must select a compiled executable or DLL')
    return host.resolve()


def run_adapter(fixtures, *, descriptors=False, startup_clone=False, portable=False):
    host = None if descriptors or startup_clone else configured_native_host()
    # Explicit opt-in must never become a skip because another prerequisite is
    # missing. Portable descriptor checks are supplemental, not PS5.1 parity.
    ps = powershell(required=host is not None or bool(os.environ.get('CUCP_INTERACTION_TEST_HOST')),
                    portable=portable)
    with tempfile.TemporaryDirectory(prefix='CUCP actual interaction 한글 ') as folder:
        root = Path(folder)
        accepted = root / 'accepted.ps1'
        baseline = root / 'original.ps1'
        inputs = root / 'cases.json'
        accepted.write_bytes(subprocess.check_output(
            ['git', 'show', f'{ACCEPTED_TREE}:scripts/cucp.ps1'], cwd=ROOT))
        baseline.write_bytes(subprocess.check_output(
            ['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT))
        inputs.write_text(json.dumps(fixtures, ensure_ascii=True), encoding='utf-8-sig')
        command = [ps, '-NoProfile', '-NonInteractive', '-File', str(RUNNER),
                   '-Source', str(accepted), '-BaselineSource', str(baseline),
                   '-SharedSource', str(SHARED), '-AdapterSource', str(ADAPTER),
                   '-PublicSource', str(adapter_public_source()),
                   '-DiagnosticSource', str(ROOT/'scripts/cucp-legacy-diagnostic-adapter.ps1'),
                   '-OracleSource', str(ORACLE), '-InputPath', str(inputs)]
        if descriptors:
            command.append('-ValidateDescriptors')
        if startup_clone:
            command.append('-ValidateStartupClone')
        if portable:
            command.append('-AllowPortableHost')
        env = dict(os.environ)
        if host is not None:
            env['CUCP_INTERACTION_TEST_HOST'] = str(host)
            env['CUCP_NATIVE_HOST'] = str(host)
        result = subprocess.run(command, env=env, capture_output=True, timeout=900)
        if result.returncode:
            raise AssertionError(result.stdout.decode('utf-8-sig', errors='replace') + '\n' +
                                 result.stderr.decode('utf-8-sig', errors='replace'))
        return json.loads(result.stdout.decode('utf-8-sig'))


def effect(kind='Native', *, name='', argv=(), data=None, live=False, **changes):
    result = dict(kind=kind, name=name, argv=list(argv), data=data, live=live,
                  quiet=False, brief=False, confirm_sensitive=False)
    result.update(changes)
    return result


def descriptor_cases():
    """Decoded adversarial descriptors; every row must fail before any leaf."""
    click = effect(argv=['-Action', 'click', '-X', '1', '-Y', '2'], live=True)
    rows = []

    def add(label, value=None, *, operation='click-point', live=True, sensitive=False, receipts=None):
        rows.append(dict(case=label, operation=operation, effect=copy.deepcopy(value or click),
                         live=live, sensitive=sensitive, receipts=receipts))

    add('live-ceiling', live=False)
    add('live-classification', dict(click, live=False))
    add('forged-read-live', effect(argv=['-Action', 'windows'], live=True), operation='safe-type')
    add('unknown-kind', dict(click, kind='Process'))
    add('case-forged-kind', dict(click, kind='native'))
    add('unknown-action', dict(click, argv=['-Action', 'start-process']))
    add('case-forged-action', dict(click, argv=['-Action', 'CLICK', '-X', '1', '-Y', '2']))
    add('missing-action', dict(click, argv=[]))
    add('reordered-action', dict(click, argv=['-X', '1', '-Action', 'click', '-Y', '2']))
    add('bad-arity', dict(click, argv=['-Action', 'click', '-X', '1', '-Y']))
    add('duplicate-option', dict(click, argv=click['argv'] + ['-X', '3']))
    add('case-duplicate-option', dict(click, argv=click['argv'] + ['-x', '3']))
    add('unknown-option', dict(click, argv=click['argv'] + ['-AllowLiveControl', 'true']))
    add('missing-required-option', dict(click, argv=['-Action', 'click', '-X', '1']))
    add('non-string-argv', dict(click, argv=['-Action', 'click', '-X', 1, '-Y', '2']))
    add('scalar-argv', dict(click, argv='-Action click'))
    add('native-data', dict(click, data={'path': 'unexpected'}))
    add('native-name', dict(click, name='anything'))
    for field, value in [('live', 'true'), ('quiet', True), ('brief', True),
                         ('confirm_sensitive', True)]:
        add('forged-' + field, dict(click, **{field: value}))
    add('sensitive-option-even-with-ceiling', dict(click, confirm_sensitive=True), sensitive=True)
    extra = dict(click, process='unauthorized')
    add('extra-descriptor-field', extra)
    missing = dict(click)
    del missing['name']
    add('missing-descriptor-field', missing)
    for operation in ('find-label', 'icon-find', 'precision-validate'):
        add('readonly-native-mutation-' + operation, operation=operation)
        add('readonly-cucp-mutation-' + operation,
            effect('Cucp', argv=['act', 'click', '--x', '1', '--y', '2', '--after', '0'], live=True),
            operation=operation)
    add('unknown-operation', operation='unknown')
    add('cross-operation-type', effect(argv=['-Action', 'type', '-Text', 'x', '-TargetHwnd', '42'], live=True))
    add('cucp-unknown-verb', effect('Cucp', argv=['act', 'type'], live=True), operation='click-label')
    add('cucp-bad-arity', effect('Cucp', argv=['act', 'click', '--x'], live=True), operation='click-label')
    add('cucp-duplicate-option', effect('Cucp', argv=['act', 'click', '--x', '1', '--y', '2', '--after', '0', '--x', '3'], live=True), operation='click-label')
    add('cucp-forged-live', effect('Cucp', argv=['act', 'click', '--x', '1', '--y', '2', '--after', '0']), operation='click-label')
    add('arbitrary-shortcut', effect(argv=['-Action', 'shortcut', '-Keys', 'alt+f4', '-TargetHwnd', '42'], live=True), operation='safe-type')
    add('ocr-incomplete-region', effect(argv=['-Action', 'ocr-find-text', '-OcrText', 'Save', '-OcrMatch', 'contains', '-OcrMaxCandidates', '8', '-ScreenshotX', '1']), operation='ocr-click')
    add('ocr-expanded-candidates', effect(argv=['-Action', 'ocr-find-text', '-OcrText', 'Save', '-OcrMatch', 'contains', '-OcrMaxCandidates', '1000']), operation='ocr-click')
    invalid_data = [
        ('Appshot', 'find-label', {'match': '', 'semantic': 'true', 'no_cache': False}),
        ('Appshot', 'find-label', {'match': '', 'semantic': False, 'no_cache': False}),
        ('Win32Windows', 'find-label', {'match': 42}),
        ('UIAffordances', 'icon-find', {'focused_window': '', 'max_elements': 999}),
        ('Vision', 'click-label', {'screenshot_path': [], 'description': 'Save'}),
        ('HitTestPoint', 'click-point', {'x': '1', 'y': 2, 'target_hwnd': 42, 'target_match': ''}),
        ('PointCacheRead', 'click-point', {'key': '../escape', 'max_age_seconds': 5}),
        ('PointCacheRead', 'click-point', {'key': 'a' * 32, 'max_age_seconds': 0}),
        ('PointCacheWrite', 'click-point', {'key': 'a' * 32, 'payload': {'schema': 'forged'}}),
        ('CoordProfile', 'click-point', {'has_point': False, 'x': 1, 'y': 2, 'target_hwnd': 42, 'target_match': ''}),
        ('AnchorScore', 'click-point', {'record': {'anchor_id': '../escape'}}),
        ('AnchorAppend', 'click-point', {'record': None}),
        ('PipelineOutput', 'click-label', {'value': ['preserve'], 'Count': 1}),
        ('Sleep', 'precision-validate', 30000),
    ]
    for index, (kind, operation, data) in enumerate(invalid_data):
        add('invalid-data-' + str(index), effect(kind, data=data), operation=operation)
    add('unknown-clock', effect('Clock', name='elapsed', data='foreign'), operation='find-label')
    add('invalid-console-name', effect('Console', name='write-line', data='raw'))
    add('invalid-console-type', effect('Console', name='write', data=False))
    add('invalid-observation-id', effect('ObservationId', name='arbitrary'), operation='icon-click')
    add('invalid-timestamp', effect('Timestamp', name='HHmmss-fff'), operation='find-label')
    add('invalid-notice', effect('Notice', name='EXEC', data='forged'), operation='click-label')
    add('invalid-trajectory', effect('TrajectoryAppend', name='click', data={'source': 'arbitrary'}))
    owned = dict(observations=['owned-observation'], screenshots=['C:\\fixture\\owned.png'],
                 cache_keys=['a' * 32], anchor_records=[])
    for receipts in (None, owned):
        suffix = '-empty' if receipts is None else '-mismatched'
        add('forged-observation' + suffix,
            effect('Cucp', argv=['act', 'click', '--x', '1', '--y', '2', '--after', 'forged-observation'], live=True),
            operation='click-label', receipts=receipts)
        add('forged-screenshot' + suffix,
            effect('Vision', data=dict(screenshot_path='C:\\fixture\\foreign.png', description='Save')),
            operation='click-label', receipts=receipts)
        payload = dict(schema='cucp.point-plan/v1', status='ok', mode='coordinate_click',
                       source='click_point_micro_refine', x=1, y=2, radius=3, step=1,
                       click_inset=1, target_hwnd=42, target_match='Editor', from_cache=False,
                       cache_ttl_seconds=5, cache_key='b' * 32, confidence='high', safe_to_act=True,
                       mouse_moved=True, reason='', precheck=None, best=None,
                       recommended_point=None, recommended_command=None, checks=[True, True], scan=None)
        add('forged-cache-key' + suffix,
            effect('PointCacheWrite', data=dict(key='b' * 32, payload=payload)), receipts=receipts)
    record = dict(ts='2026-10-02T00:00:00.0000000Z', anchor_id='a' * 32,
                  anchor_type='click_point_live_route', target_match='Editor', target_hwnd_current=42,
                  process='fixture', title='Editor', source_point=dict(x=1, y=2), screen_point=dict(x=1, y=2),
                  normalized_window_point=dict(x=.1, y=.2), visible_normalized_point=dict(x=.1, y=.2),
                  safe_to_reuse=True, coordinate_risk='low', coord_signature='geometry-one',
                  window_rect=dict(x=0, y=0, width=100, height=100), **{'class': 'Window'})
    add('unscored-anchor-record', effect('AnchorAppend', data=dict(record=record)))
    owned['anchor_records'] = [dict(record, anchor_id='b' * 32)]
    add('mismatched-scored-anchor-record', effect('AnchorAppend', data=dict(record=record)), receipts=owned)
    # Exercise both the already-decoded family hook and the real common validator
    # that decodes once before selecting that same family hook.
    return [dict(row, shared=shared) for shared in (False, True) for row in rows]


def reached_uncertain_failure(fixture, effects):
    return next((failure for failure in captured_failure_effects(fixture, effects)
                 if failure['effect']['kind'] in OWNED_STATE_EFFECTS or
                 any(item['live'] for item in effects[:failure['trace_index'] + 1])), None)


def terminal_state_uncertainty(result, effects):
    """Apply only after ruling out an earlier reached callback boundary."""
    return result['state'] == 'error' and any(
        item['live'] or item['kind'] in OWNED_STATE_EFFECTS for item in effects)


def unbrief_key(fixture):
    return json.dumps({key: value for key, value in fixture.items() if key not in ('brief', 'case')},
                      sort_keys=True)


def decoded_result(result):
    """Wire property-list order is not object identity; console stays byte-exact."""
    decoded = dict(result)
    decoded['effects'] = decode_wire(result['effects'])
    if result.get('payload') is not None:
        decoded['payload'] = decode_wire(result['payload'])
    return decoded


@lru_cache(maxsize=1)
def ordinary_results():
    fixtures = cases()
    # Resolve explicit host/interpreter before calling the optional old oracle.
    configured_native_host()
    powershell(required=True)
    return fixtures, run_oracle(fixtures), run_adapter(fixtures)


class InteractionAdapterHarnessTests(unittest.TestCase):
    def test_manifest_explicitly_selects_public_delegate_source(self):
        with tempfile.TemporaryDirectory(prefix='CUCP interaction manifest ') as folder:
            root=Path(folder);(root/'.github').mkdir();manifest=root/'.github/migration-adapters.json'
            for families,expected in ((['execution'],'scripts/cucp-legacy-interaction-adapter.ps1'),
                                      (['execution','interaction'],'scripts/cucp.ps1')):
                manifest.write_text(json.dumps({'test_adapters':families}),encoding='utf-8')
                self.assertEqual(adapter_public_source(root),root/expected)
            for malformed in ({}, {'test_adapters':'interaction'}, {'test_adapters':['interaction','interaction']},
                              {'test_adapters':['unknown']}, {'test_adapters':[],'fallback':True}):
                manifest.write_text(json.dumps(malformed),encoding='utf-8')
                with self.assertRaises(ValueError):adapter_public_source(root)

    def test_shared_corpus_stays_exactly_870_plus_12(self):
        self.assertEqual(len(cases()), 870)
        self.assertEqual(len(boundary_cases()), 12)
        self.assertEqual({row['operation'] for row in cases()}, OPERATIONS)

    def test_explicit_missing_host_fails_instead_of_skipping(self):
        with mock.patch.dict(os.environ, {'CUCP_INTERACTION_TEST_HOST': str(ROOT / 'missing-native-host.exe')}):
            with self.assertRaisesRegex(AssertionError, 'native host missing'):
                configured_native_host()

    def test_explicit_missing_powershell_fails_instead_of_skipping(self):
        with mock.patch.dict(os.environ, {'CUCP_INTERACTION_POWERSHELL': str(ROOT / 'missing-powershell.exe')}):
            with self.assertRaisesRegex(AssertionError, 'Windows PowerShell 5.1'):
                powershell(required=True)

    def test_no_copied_transport_or_oracle_native_stubs(self):
        source = RUNNER.read_text(encoding='utf-8')
        for definition in ('function Capture-Effect', 'function Invoke-NativeHelper',
                           'function _Invoke-LegacyExecutionHost', 'function _Execution-WriteChunks'):
            self.assertNotIn(definition, source)
        self.assertIn('legacy-interaction-oracle.ps1', source)
        self.assertIn('CUCP_INTERACTION_TEST_HOST', source)
        self.assertIn('PipelineOutput', source)
        self.assertIn('final integer', source)

    def test_failure_partition_uses_reached_effects_and_owned_state(self):
        fixture = dict(replies=[None, {'throw': 'lost'}, {'throw': 'unreached'}])
        effects = [effect('UIAffordances'), effect('Appshot')]
        failure = reached_uncertain_failure(fixture, effects)
        self.assertEqual((failure['trace_index'], failure['reply_index']), (1, 1))
        self.assertIsNone(reached_uncertain_failure(fixture, [effect('UIAffordances')]))
        self.assertIsNone(reached_uncertain_failure(fixture, [effect('UIAffordances'), effect('Win32Windows')]))
        self.assertIsNone(reached_uncertain_failure(fixture, [effect('Appshot'), effect('UIAffordances')]))
        self.assertIsNotNone(reached_uncertain_failure(fixture, [effect(live=True), effect('UIAffordances')]))
        # Even read-only native actions use the retained helper's redirected
        # cache files/log/lock lifecycle. Only the currently failed native call
        # is uncertain; a later genuine read failure does not inherit live input.
        native_read = effect(argv=['-Action', 'windows'], live=False)
        failure = reached_uncertain_failure(fixture, [effect('UIAffordances'), native_read])
        self.assertEqual((failure['trace_index'], failure['reply_index']), (1, 1))
        self.assertFalse(failure['effect']['live'])
        self.assertIsNone(reached_uncertain_failure(fixture, [native_read, effect('UIAffordances')]))

    def test_terminal_error_partition_only_changes_error_prefix(self):
        self.assertTrue(terminal_state_uncertainty(dict(state='error'), [effect('Appshot')]))
        self.assertTrue(terminal_state_uncertainty(dict(state='error'), [effect(argv=['-Action', 'windows'], live=False)]))
        self.assertTrue(terminal_state_uncertainty(dict(state='error'), [effect(live=True)]))
        self.assertFalse(terminal_state_uncertainty(dict(state='complete'), [effect('Appshot')]))
        self.assertFalse(terminal_state_uncertainty(dict(state='error'), [effect('UIAffordances')]))
        self.assertFalse(terminal_state_uncertainty(dict(state='error'), []))


class InteractionDecodedDescriptorTests(unittest.TestCase):
    def test_selected_public_delegates_preserve_their_source_script_path(self):
        fixtures=[dict(case=operation,family='interaction',public=name,rest=['--label','literal 한글'])
                  for operation,name in (
                    ('find-label','Invoke-MacroFindLabel'),('click-point','Invoke-MacroClickPoint'),
                    ('click-label','Invoke-MacroClickLabel'),('safe-type','Invoke-MacroSafeType'),
                    ('icon-find','Invoke-MacroIconFind'),('icon-click','Invoke-MacroIconClick'),
                    ('ocr-click','Invoke-MacroOcrClick'),('precision-validate','Invoke-MacroPrecisionValidate'))]
        results=run_adapter(fixtures,startup_clone=True)
        self.assertEqual(len(results),8)
        expected=adapter_public_source().resolve()
        for fixture,result in zip(fixtures,results):
            with self.subTest(public=fixture['public']):
                self.assertEqual(result['host_calls'],1)
                self.assertEqual(result['entry'],'legacy-interaction-session')
                self.assertEqual(result['operation'],fixture['case'])
                self.assertEqual(Path(result['script_path']).resolve(),expected)
                self.assertEqual(result['caller_after'],result['caller_before'])
                self.assertEqual(result['startup_after'],result['startup_before'])
                self.assertEqual(result['exit'],7)

    def test_wrapper_host_state_rest_cannot_mutate_caller_or_startup(self):
        self.assert_wrapper_host_state_clone(portable=False)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell 7')
    def test_powershell7_wrapper_host_state_rest_cannot_mutate_caller_or_startup(self):
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell, 'PowerShell 7 is required for argv ownership qualification')
        with mock.patch.dict(os.environ, {'CUCP_INTERACTION_POWERSHELL': shell}):
            self.assert_wrapper_host_state_clone(portable=True)

    def assert_wrapper_host_state_clone(self, *, portable):
        fixtures=[dict(case=name,rest=rest,family=family) for family in ('interaction','execution','diagnostics') for name,rest in (
            ('null-argv',None),('empty-argv',[]),('null-element',[None]),
            ('empty-element',['']),('singleton',['--label']),
            ('literal-tokens',['--label','한글','--text','-AllowLiveControl','']))]
        results=run_adapter(fixtures,startup_clone=True,portable=portable)
        self.assertEqual(len(results),len(fixtures))
        for fixture,result in zip(fixtures,results):
            with self.subTest(case=fixture['case'],family=fixture['family']):
                self.assertEqual(result['case'],fixture['case'])
                self.assertEqual(result['family'],fixture['family'])
                self.assertEqual(result['host_calls'],1)
                self.assertEqual(result['compatibility_calls'],0)
                self.assertIs(result['live'],False)
                self.assertIs(result['sensitive'],False)
                entry_family='diagnostic' if fixture['family']=='diagnostics' else fixture['family']
                self.assertEqual(result['entry'],f'legacy-{entry_family}-session')
                self.assertEqual(result['exit'],7)
                self.assertEqual(result['state_type'],result['expected_state_type'])
                self.assertIs(result['aliases_caller'],False)
                for snapshot in ('raw_before', 'raw_after', 'caller_before', 'caller_after',
                                 'state_before', 'state_after', 'startup_before', 'startup_after',
                                 'expected_state', 'expected_startup'):
                    self.assertIsInstance(result[snapshot], str, snapshot)
                self.assertEqual(json.loads(result['raw_before']),fixture['rest'])
                self.assertEqual(result['raw_after'],result['raw_before'])
                self.assertEqual(result['caller_after'],result['caller_before'])
                self.assertEqual(result['startup_before'],result['expected_startup'])
                self.assertEqual(result['startup_after'],result['startup_before'])
                self.assertEqual(result['state_before'],result['expected_state'])
                state_before=json.loads(result['state_before'])
                if state_before is None:
                    self.assertIsNone(result['state_type'])
                    self.assertIsNone(json.loads(result['state_after']))
                else:
                    self.assertIsInstance(state_before,list)
                    self.assertTrue(result['state_type'].endswith('[]'))
                    self.assertEqual(json.loads(result['state_after']),[f'host-mutated-{i}' for i in range(len(state_before))])

    def test_forged_descriptors_fail_before_any_captured_leaf(self):
        fixtures = descriptor_cases()
        results = run_adapter(fixtures, descriptors=True,
                              portable=os.environ.get('CUCP_INTERACTION_PORTABLE_DESCRIPTORS') == '1')
        self.assertEqual(len(results), len(fixtures))
        for fixture, result in zip(fixtures, results):
            with self.subTest(case=fixture['case'], shared=fixture['shared']):
                self.assertTrue(result['error'], 'Forged effect passed closed descriptor validation')
                self.assertEqual(decode_wire(result['effects']), [], 'A captured leaf ran before rejection')
                self.assertEqual(result['consumed'], 0)

    def test_valid_native_controls_reach_captured_leaf_and_literal_tokens_stay_data(self):
        fixtures = [dict(operation='safe-type', live=True, sensitive=False, shared=shared,
                         effect=effect(argv=['-Action', 'type', '-Text', token, '-TargetHwnd', '42'], live=True))
                    for shared in (False, True)
                    for token in ('-AllowLiveControl', '--confirm-sensitive', '-Action', '한글 + ^ % {text}\nline')]
        results = run_adapter(fixtures, descriptors=True,
                              portable=os.environ.get('CUCP_INTERACTION_PORTABLE_DESCRIPTORS') == '1')
        self.assertEqual(len(results), len(fixtures))
        for fixture, result in zip(fixtures, results):
            with self.subTest(shared=fixture['shared'], argv=fixture['effect']['argv']):
                self.assertIsNone(result['error'])
                self.assertEqual(decode_wire(result['effects']), [fixture['effect']])
                self.assertEqual(result['consumed'], 1)


class InteractionActualAdapterTests(unittest.TestCase):
    maxDiff = 1800

    def test_all_ordinary_source_comparisons_with_explicit_uncertainty_partition(self):
        fixtures, before, after = ordinary_results()
        self.assertEqual(len(before), 870)
        self.assertEqual(len(after), 870)
        unbrief = {unbrief_key(f): r for f, r in zip(fixtures, after) if not f.get('brief')}
        exact = uncertain = terminal = exact_failures = 0
        terminal_examples = []
        for index, (fixture, old, new) in enumerate(zip(fixtures, before, after)):
            with self.subTest(index=index, case=fixture['case'], operation=fixture['operation']):
                self.assertNotIn('Fixture exhausted', old.get('error', ''))
                effects = decode_wire(old['effects'])
                failure = reached_uncertain_failure(fixture, effects)
                if failure is None:
                    if terminal_state_uncertainty(old, effects):
                        terminal += 1
                        if len(terminal_examples) < 6:
                            terminal_examples.append(fixture['case'])
                        expected = dict(old, error='mutation_may_have_occurred=true; automatic_retry=false; ' + old['error'])
                        self.assertIsNone(first_difference(decoded_result(new), decoded_result(expected)))
                        continue
                    exact += 1
                    exact_failures += bool(captured_failure_effects(fixture, effects))
                    self.assertIsNone(first_difference(decoded_result(new), decoded_result(old)))
                    continue
                uncertain += 1
                boundary = failure['trace_index'] + 1
                self.assertIsNone(first_difference(decode_wire(new['effects']), effects[:boundary]))
                self.assertEqual(new['consumed'], failure['reply_index'] + 1)
                self.assertEqual(new['pipeline'], [e['data'] for e in effects[:boundary] if e['kind'] == 'PipelineOutput'])
                console_prefix = ''.join(e['data'] for e in effects[:boundary] if e['kind'] == 'Console')
                self.assertTrue(new['console'].startswith(console_prefix))
                # No later input, storage write, acquisition, sleep or trace is
                # permitted. Every reached prefix remains compared exactly.
                if failure['effect']['live']:
                    self.assertEqual(new['state'], 'complete')
                    self.assertEqual(new['exit'], 2)
                    report = unbrief[unbrief_key(fixture)] if fixture.get('brief') else new
                    self.assertIsNotNone(report['payload'])
                    payload = decode_wire(report['payload'])
                    self.assertEqual(payload['status'], 'partial')
                    self.assertIs(payload['mutation_may_have_occurred'], True)
                    self.assertIs(payload['automatic_retry'], False)
                    self.assertEqual(payload['effect'], {key: failure['effect'][key] for key in ('kind', 'name', 'argv')})
                    self.assertEqual(payload['result']['detail'], failure['message'])
                    if fixture.get('brief'):
                        self.assertTrue(new['console'][len(console_prefix):].startswith('partial '), new['console'])
                else:
                    self.assertEqual(new['state'], 'error')
                    self.assertEqual(new['error'], 'mutation_may_have_occurred=true; automatic_retry=false; ' + failure['message'])
                    self.assertEqual(new['console'], console_prefix)
        self.assertEqual(exact + uncertain + terminal, 870)
        self.assertGreater(exact_failures, 0)
        self.assertGreater(uncertain, 0)
        self.assertGreater(terminal, 0)
        print(f'Interaction actual adapter: {exact} exact rows, {uncertain} reached callback uncertainty rows, '
              f'{terminal} exact terminal-error prefixes; all 870 compared; terminal examples={terminal_examples}')

    def test_all_12_explicit_live_and_postdispatch_readback_boundaries(self):
        fixtures = boundary_cases()
        results = run_adapter(fixtures)
        self.assertEqual(len(results), 12)
        for fixture, result in zip(fixtures, results):
            with self.subTest(case=fixture['case'], boundary=fixture['boundary']):
                self.assertEqual(result['consumed'], fixture['expected_consumed'])
                effects = decode_wire(result['effects'])
                self.assertFalse(any(e['kind'] == 'TrajectoryAppend' for e in effects))
                if fixture['boundary'] == 'live':
                    self.assertTrue(effects[-1]['live'])
                    self.assertEqual(result['state'], 'complete')
                    self.assertEqual(result['exit'], 2)
                    payload = decode_wire(result['payload'])
                    self.assertIs(payload['mutation_may_have_occurred'], True)
                    self.assertIs(payload['automatic_retry'], False)
                else:
                    self.assertEqual(effects[-1]['kind'], 'AnchorAppend')
                    self.assertEqual(result['state'], 'error')
                    self.assertEqual(result['error'], 'mutation_may_have_occurred=true; automatic_retry=false; post-click history result lost')


if __name__ == '__main__':
    unittest.main()
