"""Pinned PS5 action bodies with an explicit, verified type-name-only seam.

Provider results are synthesized only from case data, never candidate output.
Query order comes from the original executed function and is checked by the
candidate's exhaustible provider. Owned transport is a separate suite.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from helper_process_evidence import run_evidence, require_success
from test_legacy_helper_source import ROOT, FIXTURES, MANIFEST, published_source, expected_type_seam

HOST = os.environ.get('CUCP_LEGACY_HELPER_TEST_HOST', '')
ENABLED = sys.platform == 'win32' and HOST


def rect(x=0, y=0, w=100, h=100):
    return dict(x=x, y=y, w=w, h=h)


def node(id, name, **kwargs):
    return dict(id=id, name=name, rect=rect(), **kwargs)


def cases():
    # Independent positive/negative branches for all six public actions; real
    # OCR screenshot/WinRT is intentionally not represented as qualified here.
    yield dict(id='denied-six', requests=[dict(action=a, args={}) for a in
               ['windows', 'health', 'focused', 'modal-detect', 'ocr-screen-fast', 'uia-find-fast', 'shutdown', 'UNKNOWN']])
    yield dict(id='ocr-success-truthiness-cache', win32=True, ocr=True,
               ocr_result={'text':'한글 OWNED 123','lines':[{'text':'한글 OWNED 123','word_count':3}]},
               requests=[dict(action='ocr-screen-fast',args={}),dict(action='ocr-screen-fast',args={'X':False,'Y':-2,'W':0,'H':300.5})])
    yield dict(id='ocr-max-dimension', win32=True, ocr=True, max_dimension=100,
               requests=[dict(action='ocr-screen-fast',args={'W':101,'H':1})])
    yield dict(id='ocr-init-retry', win32=True, requests=[dict(action='ocr-screen-fast', args={})] * 2)
    for culture in ('en-US', 'tr-TR', 'ko-KR'):
        windows = [dict(hwnd=123, title='한글 😀 Save', **{'class': 'Dialog'}, pid=17, rect=rect(-10, 20, 500, 300)),
                   dict(hwnd=124, title='istanbul', **{'class': 'hidden'}, pid=18, rect=rect(), visible=False),
                   dict(hwnd=125, title='', **{'class': 'empty'}, pid=19, rect=rect()),
                   dict(hwnd=126, title='İstanbul', **{'class': 'Frame'}, pid=20, rect=rect())]
        yield dict(id='windows-'+culture, culture=culture, win32=True, windows=windows, foreground=126,
                   requests=[dict(action='windows', args={'Match': 'I'}), dict(action='windows', args={'Match': '[a]'}),
                             dict(action='focused', args={}), dict(action='health', args={})])
        yield dict(id='modal-'+culture, culture=culture, win32=True, windows=windows, foreground=123,
                   uia_children=[node('first','small'), node('tie','small second'), node('modal','confirm',is_modal=True),
                                 node('dialog','dialog',**{'class':'#32770'})], requests=[dict(action='modal-detect', args={})])
        yield dict(id='uia-'+culture, culture=culture, win32=True, uia=True,
                   uia_children=[node('first','Application',subtree=[node('a','Save'),node('b','save as'),node('c','resave')]),
                                 node('second','Application',subtree=[node('forbidden','Save forbidden')])],
                   uia_subtree=[node('fallback','Root Save')], requests=[dict(action='uia-find-fast', args={'Label':'Save','Match':'Application'}),
                       dict(action='uia-find-fast', args={'Label':'Save','Match':'missing'}),
                       dict(action='uia-find-fast', args={'Label':False}), dict(action='uia-find-fast', args={'Label':['Save']})])
    yield dict(id='modal-large-ties', win32=True, foreground=0, uia_children=[node('m'+str(i),'small '+str(i)) for i in range(32)], requests=[dict(action='modal-detect',args={})])
    yield dict(id='uia-caps-ties', win32=True, uia=True,
               uia_subtree=[node('n'+str(i),'Save '+str(i)) for i in range(25)], requests=[dict(action='uia-find-fast', args={'Label':'Save'})])
    yield dict(id='uia-scan-cap', win32=True, uia=True,
               uia_subtree=[node('n'+str(i),'no') for i in range(800)] + [node('too-late','Save')],
               requests=[dict(action='uia-find-fast', args={'Label':'Save'})])
    yield dict(id='focused-partial', win32=True, foreground=0, requests=[dict(action='focused', args={})])
    yield dict(id='uia-no-match', win32=True, uia=True, uia_subtree=[node('zero','Save', **{})],
               requests=[dict(action='uia-find-fast', args={'Label':'missing'})])


def utf16_cut(text, maximum):
    return text.encode('utf-16-le')[:maximum * 2].decode('utf-16-le', errors='surrogatepass')


def validate_oracle_execution(case, before):
    """Reject absent dispatch/invalid JSON collections before candidate replay."""
    if not isinstance(before, dict) or not isinstance(before.get('calls'), list):
        raise AssertionError('Oracle calls must be a JSON array, including when empty')
    if not isinstance(before.get('responses'), list) or len(before['responses']) != len(case['requests']):
        raise AssertionError('Oracle response count must equal the fixture request count')
    count = before.get('request_count')
    if type(count) is not int or count != len(case['requests']):
        raise AssertionError('Original oracle did not dispatch every fixture request; inspect recorded oracle errors')
    for response in before['responses']:
        if not isinstance(response, dict) or set(response) != {'id', 'exit_code', 'result', 'error'}:
            raise AssertionError('Oracle response must preserve its complete result/error record')


def captured_calls(case, trace):
    if not isinstance(trace, list):
        raise AssertionError('Oracle calls must be a JSON array, including when empty')
    windows = {w['hwnd']: w for w in case.get('windows', [])}
    elements = {}
    def register(values):
        for element in values:
            elements[element['id']] = element
            register(element.get('subtree', []))
    register(case.get('uia_children', [])); register(case.get('uia_subtree', []))
    result = []
    for effect in trace:
        if (not isinstance(effect, dict) or not isinstance(effect.get('op'), str)
                or not effect['op'] or not isinstance(effect.get('args'), list)):
            raise AssertionError('Each captured operation requires a string op and JSON args array')
        op, args = effect['op'], effect['args']
        if set(effect) != ({'op', 'args', 'value'} if op == 'ocr.tempPath' else {'op', 'args'}):
            raise AssertionError('Unexpected captured operation fields: ' + op)
        arity = {
            'win32.ensure': 0, 'win32.enumerate': 0, 'win32.foreground': 0,
            'win32.visible': 1, 'win32.titleLength': 1, 'win32.title': 2,
            'win32.class': 2, 'win32.pid': 1, 'win32.rect': 1,
            'uia.load': 0, 'uia.loadModal': 0, 'uia.root': 0, 'uia.children': 2,
            'uia.subtree': 1, 'uia.name': 1, 'uia.class': 1, 'uia.isModal': 1,
            'uia.handle': 1, 'uia.controlType': 1, 'uia.rect': 1,
            'ocr.initialize': 0, 'ocr.createProfile': 0, 'ocr.loadDrawing': 0,
            'ocr.loadFormsAndVirtualWidth': 0, 'ocr.primaryScreenWidth': 0,
            'ocr.maxDimension': 0, 'ocr.tempPath': 0, 'ocr.capture': 5,
            'ocr.prepareAsync': 0, 'ocr.loadFile': 1, 'ocr.openRead': 1,
            'ocr.createDecoder': 1, 'ocr.getBitmap': 1, 'ocr.recognize': 2, 'ocr.removeTemp': 1,
        }
        if op not in arity:
            raise AssertionError('unplanned acquisition: ' + op)
        if len(args) != arity[op]:
            raise AssertionError('Unexpected captured argument count: ' + op)
        call = dict(op=op, args=args, result=None)
        if op == 'win32.ensure':
            if not case.get('win32'): call = dict(op=op, args=args, **{'throw':'owned win32 failure'})
        elif op == 'uia.load':
            if not case.get('uia'): call = dict(op=op, args=args, **{'throw':'owned uia failure'})
        elif op == 'uia.loadModal': pass
        elif op == 'ocr.initialize':
            if not case.get('ocr'): call = dict(op=op, args=args, **{'throw':'owned fixture init failure'})
        elif op == 'ocr.createProfile': call['result']='engine'
        elif op in ('ocr.loadDrawing','ocr.loadFormsAndVirtualWidth','ocr.capture','ocr.prepareAsync','ocr.removeTemp'): pass
        elif op == 'ocr.primaryScreenWidth': call['result']=1920
        elif op == 'ocr.maxDimension': call['result']=case.get('max_dimension',10000)
        elif op == 'ocr.tempPath': call['result']=effect['value']
        elif op in ('ocr.loadFile','ocr.openRead','ocr.createDecoder','ocr.getBitmap'):
            call['result']={'ocr.loadFile':'file','ocr.openRead':'stream','ocr.createDecoder':'decoder','ocr.getBitmap':'bitmap'}[op]
        elif op == 'ocr.recognize': call['result']=case['ocr_result']
        elif op == 'win32.enumerate': call['result'] = list(windows)
        elif op == 'win32.foreground': call['result'] = case.get('foreground', 0)
        elif op.startswith('win32.'):
            w = windows[args[0]]
            if op == 'win32.visible': call['result'] = w.get('visible', True)
            elif op == 'win32.titleLength': call['result'] = len(w.get('title','').encode('utf-16-le')) // 2
            elif op in ('win32.title', 'win32.class'): call['result'] = utf16_cut(w.get(op.split('.')[1], ''), args[1]-1)
            elif op == 'win32.pid': call['result'] = w.get('pid', 0)
            elif op == 'win32.rect':
                r=w['rect'];call['result']=dict(left=r['x'],top=r['y'],right=r['x']+r['w'],bottom=r['y']+r['h'])
            else: raise AssertionError('unknown captured Win32 operation '+op)
        elif op == 'uia.root': call['result'] = 'root'
        elif op == 'uia.children': call['result'] = [e['id'] for e in case.get('uia_children', [])]
        elif op == 'uia.subtree': call['result'] = [e['id'] for e in case.get('uia_subtree', [])] if args[0]=='root' else [e['id'] for e in elements[args[0]].get('subtree', [])]
        elif op.startswith('uia.'):
            e=elements[args[0]]
            if op == 'uia.rect':
                r=e['rect'];call['result']=dict(x=r['x'],y=r['y'],width=r['w'],height=r['h'])
            else:
                key={'uia.name':'name','uia.class':'class','uia.isModal':'is_modal','uia.handle':'hwnd','uia.controlType':'control_type'}[op]
                call['result']=e.get(key, False if key=='is_modal' else 0 if key=='hwnd' else '')
        else: raise AssertionError('unplanned acquisition: '+op)
        result.append(call)
    return result


class HelperParityCorpusTests(unittest.TestCase):
    def test_capture_replay_preserves_empty_single_and_ordered_calls(self):
        self.assertEqual(captured_calls({}, []), [])
        trace = [dict(op='uia.loadModal', args=[]), dict(op='uia.load', args=[]),
                 dict(op='win32.ensure', args=[]), dict(op='win32.foreground', args=[])]
        case = dict(win32=True, uia=True, foreground=17)
        original = copy.deepcopy(trace)
        replay = captured_calls(case, trace)
        self.assertEqual(trace, original)
        self.assertEqual([dict(op=c['op'], args=c['args']) for c in replay], original)
        self.assertEqual(replay[-1]['result'], 17)
        self.assertEqual(captured_calls({}, [dict(op='win32.ensure', args=[])]),
                         [dict(op='win32.ensure', args=[], **{'throw': 'owned win32 failure'})])

    def test_capture_replay_rejects_malformed_and_unplanned_trace(self):
        for invalid in ({}, None, '', 0, [None], [{}], [dict(op='uia.load')],
                        [dict(op=3, args=[])], [dict(op='uia.load', args={})],
                        [dict(op='uia.load', args=[None])], [dict(op='uia.load', args=[], result=None)],
                        [dict(op='unplanned', args=[])], [dict(op='ocr.tempPath', args=[])]):
            with self.subTest(trace=invalid), self.assertRaises(AssertionError):
                captured_calls({}, invalid)

    def test_oracle_replay_requires_complete_dispatch_and_response_counts(self):
        case = dict(requests=[dict(action='health', args={})])
        before = dict(calls=[], responses=[dict(id=None, exit_code=0, result={}, error=None)], request_count=1)
        validate_oracle_execution(case, before)
        for field, value in [('calls', {}), ('responses', {}), ('responses', []),
                             ('responses', [dict(result={})]), ('request_count', 0), ('request_count', True)]:
            broken = dict(before, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                validate_oracle_execution(case, broken)
        validate_oracle_execution(dict(requests=[]), dict(calls=[], responses=[], request_count=0))

    def test_explicit_corpus_has_all_six_actions_and_culture_caps(self):
        values=list(cases())
        actions={r['action'] for c in values for r in c['requests']}
        self.assertTrue({'windows','health','focused','modal-detect','ocr-screen-fast','uia-find-fast'}.issubset(actions))
        self.assertGreaterEqual(len(values), 14)
        self.assertEqual({c['culture'] for c in values if 'culture' in c},{'en-US','tr-TR','ko-KR'})
        if os.environ.get('CUCP_REQUIRE_HELPER_ORACLE'):
            self.assertTrue(ENABLED, 'Required Windows helper oracle was not enabled')
            self.assertTrue(shutil.which('powershell.exe'), 'Required Windows PowerShell 5.1 oracle is absent')


@unittest.skipUnless(ENABLED, 'Requires Windows net48 helper and published PS5 oracle')
class HelperActionsWindowsParityTests(unittest.TestCase):
    maxDiff=None

    def test_isolated_original_dispatch_binding_diagnostic(self):
        """Classify the binding defect without correcting published function text.

        This is a diagnostic baseline, not successful original action parity.
        The original action differential below still must pass independently.
        """
        with tempfile.TemporaryDirectory(prefix='CUCP binding probe ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            source = root / 'published.ps1'
            source.write_bytes(published_source('scripts/cucp-helper-server.ps1', logs))
            command = [shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                       '-File', str(FIXTURES / 'binding-probe.ps1'), '-Source', str(source),
                       '-Manifest', str(FIXTURES / 'source-manifest.json')]
            result = run_evidence(command,
                directory=logs, label='original-dispatch-binding-probe', cwd=root, timeout=20, limit=256 * 1024)
            require_success(result)
            self.assertEqual(result['stderr'], b'')
            evidence = json.loads(result['stdout'].decode('utf-8-sig'))
            self.assertEqual(evidence['schema'], 'cucp.helper-binding-probe/v1')
            self.assertTrue(evidence['powershell_version'].startswith('5.1.'))
            self.assertEqual(evidence['source_sha256'], MANIFEST['files'][0]['normalized_sha256'])
            self.assertEqual(evidence['functions'], [dict(name=f['name'], sha256=f['sha256'])
                for f in MANIFEST['files'][0]['functions'] if f['name'] in ('_Action-Health', '_Dispatch')])
            inputs = {
                'direct-empty': {}, 'direct-values': {'Label': 'Save', 'Flag': False},
                'converted-empty': {}, 'converted-values': {'Label': 'Save', 'Flag': False},
                'converted-nested': {'Nested': {'Empty': {}, 'Values': [{'Label': 'Save'}, [], None, False]}},
            }
            targets = {'synthetic-automatic', 'synthetic-named', 'original-health',
                       'original-dispatch-health', 'original-dispatch-shutdown', 'original-dispatch-unsupported'}
            observations = evidence['observations']
            self.assertEqual(len(observations), len(inputs) * len(targets))
            self.assertEqual({(o['input'], o['target']) for o in observations},
                             {(name, target) for name in inputs for target in targets})
            for observation in observations:
                with self.subTest(input=observation['input'], target=observation['target']):
                    self.assertEqual(observation['input_type'], 'System.Collections.Hashtable')
                    self.assertEqual(observation['input_value'], inputs[observation['input']])
                    self.assertEqual(observation['request_count'], 0)
                    if observation['target'] == 'synthetic-named':
                        self.assertIsNone(observation['error'])
                        self.assertEqual(observation['body_entered'], 1)
                        self.assertEqual(observation['result'], dict(received_type='System.Collections.Hashtable',
                            bound_type='System.Collections.Hashtable', count=len(inputs[observation['input']]),
                            received=inputs[observation['input']]))
                    else:
                        self.assertEqual(observation['body_entered'], 0)
                        self.assertIsNone(observation['result'])
                        error = observation['error']
                        self.assertEqual(error['record_type'], 'System.Management.Automation.ErrorRecord')
                        self.assertTrue(error['exception_type'])
                        self.assertTrue(error['fully_qualified_error_id'])
                        self.assertIn('System.Object[]', error['message'])
                        self.assertIn('System.Collections.Hashtable', error['message'])
                        self.assertIsInstance(error['invocation'], dict)
                        self.assertTrue(error['script_stack_trace'])
                        for text in (error['message'], error['invocation']['line'],
                                     error['invocation']['position'], error['script_stack_trace']):
                            self.assertLessEqual(len(text.encode('utf-16-le')), 4096)
            source.write_bytes(source.read_bytes() + b'\n# changed binding-probe source\n')
            refused = run_evidence(command, directory=logs, label='original-dispatch-binding-source-refusal',
                                   cwd=root, timeout=20, limit=256 * 1024)
            require_success(refused, expected_exit=1)
            self.assertEqual(refused['stdout'], b'')
            self.assertIn('Published server source hash mismatch', refused['stderr'].decode('utf-8-sig'))

    def oracle(self, root, logs, label, *, source, stubs=None, wrong_binding=False, extent_fault=None):
        command = [shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(FIXTURES / 'oracle.ps1'), '-Source', str(source),
                   '-Manifest', str(FIXTURES / 'source-manifest.json'), '-CasePath', str(root / 'case.json')]
        if stubs is not False:
            command += ['-Stubs', str(stubs or FIXTURES / 'OracleAcquisition.cs')]
        if wrong_binding:
            command += ['-TestWrongBinding']
        if extent_fault is not None:
            command += ['-TestTypeExtentFault', extent_fault]
        return run_evidence(command, directory=logs, label=label, cwd=root, timeout=40, limit=2 * 1024 * 1024)

    def test_oracle_type_edit_order_and_refusals(self):
        with tempfile.TemporaryDirectory(prefix='CUCP extent oracle ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            raw = published_source('scripts/cucp-helper-server.ps1', logs)
            source = root / 'published.ps1'
            source.write_bytes(raw)
            (root / 'case.json').write_text(json.dumps(dict(requests=[])), encoding='utf-8')
            success = self.oracle(root, logs, 'oracle-type-edit-order', source=source)
            require_success(success)
            before = json.loads(success['stdout'].decode('utf-8-sig'))
            seam = before['oracle_seam']
            seam['guarded_types'].sort()
            seam['type_substitutions'].sort(key=lambda s: s['start_utf16'])
            self.assertEqual(seam, expected_type_seam(raw))
            self.assertEqual(before['responses'], [])
            self.assertEqual(before['calls'], [])
            self.assertEqual(success['stderr'], b'')
            first = next(s for s in seam['type_substitutions'] if s['function'] == '_Action-Windows')
            for fault, reason, planned, applied in [('duplicate', 'overlap_or_order', 12, 11),
                                                     ('changed', 'text_mismatch', 11, 10)]:
                with self.subTest(fault=fault):
                    result = self.oracle(root, logs, 'oracle-type-edit-' + fault, source=source, extent_fault=fault)
                    require_success(result, expected_exit=1)
                    lines = result['stderr'].decode('utf-8-sig', errors='strict').splitlines()
                    diagnostic = json.loads(lines[0])
                    self.assertEqual(diagnostic['schema'], 'cucp.oracle-type-extent-refusal/v1')
                    self.assertEqual(diagnostic['function'], '_Action-Windows')
                    self.assertEqual(diagnostic['reason'], reason)
                    self.assertEqual(diagnostic['start_utf16'], first['start_utf16'])
                    self.assertEqual(diagnostic['end_utf16'], first['end_utf16'])
                    self.assertEqual(diagnostic['planned'], planned)
                    self.assertEqual(diagnostic['applied'], applied)
                    self.assertLessEqual(len(diagnostic['actual_prefix'].encode('utf-16-le')), 256)
                    self.assertIn('Overlapping or changed oracle type extent', '\n'.join(lines[1:]))
                    self.assertEqual(result['stdout'], b'')

    def test_oracle_rejects_source_facade_and_type_binding_changes_before_dispatch(self):
        with tempfile.TemporaryDirectory(prefix='CUCP guarded oracle ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            original_source = published_source('scripts/cucp-helper-server.ps1', logs)
            source = root / 'published.ps1'
            source.write_bytes(original_source)
            (root / 'case.json').write_text(json.dumps(dict(win32=True, ocr=True, requests=[dict(action='ocr-screen-fast', args={})])), encoding='utf-8')

            def expect_failure(label, message, **kwargs):
                result = self.oracle(root, logs, label, source=source, **kwargs)
                # Timeout, launch error, truncated output, etc. never count as a
                # successful refusal. All raw evidence already exists on disk.
                require_success(result, expected_exit=1)
                self.assertIn(message, result['stderr'].decode('utf-8-sig', errors='replace'))
                self.assertEqual(result['stdout'], b'')

            expect_failure('oracle-missing-facade', 'An inert acquisition facade is required', stubs=False)
            source.write_bytes(original_source.replace(b'[Windows.Storage.StorageFile]', b'[System.String]', 1))
            expect_failure('oracle-mutated-source', 'Published server source hash mismatch')
            source.write_bytes(original_source)
            facade = root / 'mutated-facade.cs'
            facade.write_text((FIXTURES / 'OracleAcquisition.cs').read_text(encoding='utf-8') + '\n// changed facade\n', encoding='utf-8')
            expect_failure('oracle-mutated-facade', 'Inert oracle facade hash mismatch', stubs=facade)
            # The counted driver contains this negative path; Python supplies
            # only a switch. No executable PowerShell string is manufactured.
            expect_failure('oracle-wrong-assembly-binding', 'Unsafe oracle type resolution: CucpFixture.HelperWin32', wrong_binding=True)

    def test_published_actions_inert_providers_and_exact_query_order(self):
        with tempfile.TemporaryDirectory(prefix='CUCP helper oracle 한글 ') as directory:
            root=Path(directory)
            logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root/'evidence'))
            source=root/'published.ps1';source.write_bytes(published_source('scripts/cucp-helper-server.ps1',logs))
            expected_seam=expected_type_seam(source.read_bytes())
            for case in cases():
                with self.subTest(case=case['id']):
                    path=root/'case.json';path.write_text(json.dumps(case,ensure_ascii=True),encoding='utf-8')
                    original=self.oracle(root,logs,case['id']+'-oracle',source=source)
                    require_success(original)
                    before=json.loads(original['stdout'].decode('utf-8-sig'))
                    seam=before['oracle_seam']
                    seam['guarded_types'].sort()
                    seam['type_substitutions'].sort(key=lambda s:s['start_utf16'])
                    self.assertEqual(seam,expected_seam)
                    validate_oracle_execution(case,before)
                    calls=captured_calls(case,before['calls'])
                    fixture=dict(pid=123,pipe_name='fixture',culture=case.get('culture','en-US'),clock=['2020-01-01T00:00:00Z']*(sum(r['action'].lower()=='health' for r in case['requests'])+1),calls=calls,requests=case['requests'])
                    path.write_text(json.dumps(fixture,ensure_ascii=True),encoding='utf-8')
                    candidate=run_evidence([HOST,'fixture','--input-file',str(path)],directory=logs,label=case['id']+'-candidate',cwd=root,timeout=20,limit=2*1024*1024)
                    require_success(candidate)
                    after=json.loads(candidate['stdout'].decode('utf-8-sig'))
                    self.assertEqual(before['responses'],after['responses'])
                    self.assertEqual(after['consumed'],len(calls))
                    self.assertEqual([dict(op=x['op'],args=x['args']) for x in before['calls']],after['calls'])
                    # The scripted provider refuses missing, extra, reordered, or
                    # differently-parameterized calls before any response is parsed.
