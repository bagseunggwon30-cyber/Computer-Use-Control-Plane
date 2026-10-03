"""Original/Args-only defect evidence and explicit functional-intent contracts.

Provider results are synthesized only from case data, never candidate output.
The functional tier intentionally corrects the OCR type-variable collision and
numeric score sorting with stable acquisition-order ties. Full outputs, types,
and acquisition order face independent contracts and the candidate's exhaustible
provider. This is an intentional functional bug correction, never original parity.
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
from helper_process_evidence import run_evidence, require_success
from test_legacy_helper_source import (ROOT, FIXTURES, MANIFEST, published_source, expected_type_seam,
                                       expected_args_seam, expected_functional_seam)
from helper_binding_observation import classify_original_actions, classify_binding_probe
from helper_baseline_observation import save_classification
from helper_args_only_observation import classify_args_only_actions, args_only_case_ids, retained_args_only

HOST = os.environ.get('CUCP_LEGACY_HELPER_TEST_HOST', '')
ENABLED = sys.platform == 'win32' and HOST


def rect(x=0, y=0, w=100, h=100):
    return dict(x=x, y=y, w=w, h=h)


def node(id, name, **kwargs):
    return dict(dict(id=id, name=name, rect=rect()), **kwargs)


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
    # Distinct identity and geometry make a stable tie a selected-action contract,
    # not merely an unordered collection with equivalent scores.
    yield dict(id='modal-distinct-ties', win32=True, foreground=0, uia_children=[
        node('dialog-first', 'Dialog acquisition first', hwnd=5101, rect=rect(-90, 15, 150, 80), **{'class': '#32770'}),
        node('modal-first', 'Modal acquisition first', hwnd=5102, rect=rect(30, -25, 160, 90), is_modal=True),
        node('dialog-second', 'Dialog acquisition second', hwnd=5103, rect=rect(60, 35, 170, 100), **{'class': '#32770'}),
        node('modal-second', 'Modal acquisition second', hwnd=5104, rect=rect(90, 45, 180, 110), is_modal=True),
        node('small-first', 'Small acquisition first', hwnd=5105, rect=rect(120, 55, 190, 120)),
        node('small-second', 'Small acquisition second', hwnd=5106, rect=rect(150, 65, 200, 130)),
    ], requests=[dict(action='modal-detect', args={})])
    yield dict(id='uia-distinct-ties', win32=True, uia=True, uia_children=[
        node('first', 'Application acquisition first', hwnd=6001, subtree=[
            node('distinct-' + str(i), 'Save choice ' + str(i), hwnd=6100 + i,
                 rect=rect(-51 + i * 17, 21 - i * 3, 105 + i * 2, 73 + i * 2), control_type='button')
            for i in range(20)]),
        node('second', 'Application acquisition second', hwnd=6002,
             subtree=[node('forbidden-second', 'Save', hwnd=6200, rect=rect(800, 900, 20, 40))]),
    ], uia_subtree=[node('forbidden-root', 'Save', hwnd=6300, rect=rect(1000, 1100, 60, 80))],
        requests=[dict(action='uia-find-fast', args={'Label': 'Save', 'Match': 'Application'})])


def utf16_cut(text, maximum):
    return text.encode('utf-16-le')[:maximum * 2].decode('utf-16-le', errors='surrogatepass')


def same_json_types(left, right):
    """Fixture contracts distinguish booleans, integer fields and collections."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json_types(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json_types(a, b) for a, b in zip(left, right))
    return left == right


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


def functional_intent_contract(case, *, temp_paths=()):
    """Reviewed outputs and acquisition order for the closed fixture corpus.

    Expectations come from fixture data and declared action semantics, never
    candidate results or captured provider return sequences. Only generated OCR
    filenames are supplied by the oracle; their format/count is checked below.
    Every tied result retains its acquisition order, including selected identity
    and click point. No oracle or candidate order is used to form expectations.
    """
    responses, calls = [], []
    def call(op, *args):
        calls.append(dict(op=op, args=list(args)))
    def response(result):
        request = case['requests'][len(responses)]
        responses.append(dict(id=request.get('id'), exit_code={'error': 1, 'partial': 2, 'fallback_required': 99}.get(result['status'], 0),
                              result=result, error=None))
    def health(count, loaded):
        return dict(status='ok', schema='cucp.health/v1', helper_mode='persistent_server', pid=123,
                    pipe_name='fixture', uptime_s=0, request_count=count, win32_loaded=loaded)
    def failed(reason, **extra):
        return dict(status='error', reason=reason, **extra)
    def uia_candidate(element, score):
        bounds = element['rect']
        return dict(name=element['name'], score=score, rect=element['rect'],
                    click_point=dict(x=round(bounds['x'] + bounds['w'] / 2),
                                     y=round(bounds['y'] + bounds['h'] / 2)),
                    control_type=element.get('control_type', ''))
    def uia_result(elements, scores, match=None):
        candidates = [uia_candidate(element, score) for element, score in zip(elements, scores)]
        return dict(status='ok', schema='cucp.uia-find/v1', label='Save', match=match,
                    score=scores[0], best=candidates[0], candidates=candidates,
                    candidate_count=len(candidates), uia_warm=True)
    def uia_scan(elements):
        for element in elements:
            call('uia.name', element['id']); call('uia.rect', element['id']); call('uia.controlType', element['id'])
    identity = case['id']
    if identity == 'denied-six':
        call('win32.ensure'); response(failed('win32_unavailable'))
        response(health(2, False))
        call('win32.ensure'); response(failed('win32_unavailable'))
        call('uia.loadModal'); call('win32.ensure'); response(failed('win32_unavailable'))
        call('win32.ensure'); response(failed('win32_unavailable'))
        call('uia.load'); response(failed('uia_load_failed'))
        response(dict(status='ok', shutting_down=True))
        response(dict(status='fallback_required', reason='action_not_supported_in_server', action='UNKNOWN',
                      recommended_action='wrapper should fall back to child process for this action'))
    elif identity.startswith('windows-'):
        call('win32.ensure')
        foreground = dict(hwnd=126, title='İstanbul')
        for index in range(2):
            # The literal I fixture intentionally distinguishes Turkish casing.
            matches = [126] if index == 0 and case['culture'] != 'tr-TR' else []
            call('win32.enumerate')
            for window in case['windows']:
                handle = window['hwnd']; call('win32.visible', handle)
                if handle == 124: continue
                call('win32.titleLength', handle)
                if handle == 125: continue
                call('win32.title', handle, len(window['title'].encode('utf-16-le')) // 2 + 1)
                call('win32.class', handle, 256); call('win32.pid', handle)
                if handle in matches: call('win32.rect', handle)
            call('win32.foreground'); call('win32.titleLength', 126); call('win32.title', 126, 9)
            response(dict(status='ok', schema='cucp.observation/v1', kind='windows', sources=['win32_helper_server'],
                          foreground=foreground, windows=[{k: v for k, v in w.items() if k != 'visible'}
                                                        for w in case['windows'] if w['hwnd'] in matches], count=len(matches)))
        call('win32.foreground'); call('win32.title', 126, 512); call('win32.class', 126, 256)
        call('win32.pid', 126); call('win32.rect', 126)
        response(dict(status='ok', schema='cucp.focused/v1', **case['windows'][3]))
        response(health(4, True))
    elif identity.startswith('modal-'):
        call('uia.loadModal'); call('win32.ensure'); call('win32.foreground')
        foreground = None
        if case.get('foreground'):
            call('win32.title', 123, 512); call('win32.class', 123, 256)
            foreground = dict(hwnd=123, title='한글 😀 Save', **{'class': 'Dialog'})
        call('uia.root'); call('uia.children', 'root', 'window-or-pane')
        candidates = []
        for element in case['uia_children']:
            for op in ('name', 'class', 'rect', 'isModal', 'handle'): call('uia.' + op, element['id'])
            score, reason = {'modal': (120, 'uia_window_is_modal'), 'dialog': (80, 'dialog_class_name'),
                             'modal-first': (120, 'uia_window_is_modal'), 'modal-second': (120, 'uia_window_is_modal'),
                             'dialog-first': (80, 'dialog_class_name'), 'dialog-second': (80, 'dialog_class_name')}.get(element['id'], (20, 'small_window_size'))
            candidates.append(dict(hwnd=element.get('hwnd', 0), title=element['name'], score=score, reason=reason,
                                   is_modal=element.get('is_modal', False), **{'class': element.get('class', '')}))
        candidates.sort(key=lambda value: -value['score'])
        response(dict(status='ok', schema='cucp.modal-detect/v1', foreground=foreground,
                      modal_candidates=candidates, candidate_count=len(candidates),
                      recommended_action='wait' if identity == 'modal-large-ties' else 'dismiss_or_confirm'))
    elif identity in ('ocr-success-truthiness-cache', 'ocr-max-dimension', 'ocr-init-retry'):
        call('win32.ensure')
        if identity == 'ocr-init-retry':
            for _ in range(2):
                call('ocr.initialize'); response(failed('ocr_init_failed', detail='owned fixture init failure'))
        else:
            call('ocr.initialize'); call('ocr.createProfile')
            for index in range(len(case['requests'])):
                for op in ('loadDrawing', 'primaryScreenWidth', 'loadFormsAndVirtualWidth', 'maxDimension'): call('ocr.' + op)
                if identity == 'ocr-max-dimension':
                    response(failed('region_exceeds_max_image_dimension', max_dim=100)); continue
                region = rect(0, 0, 800, 600) if index == 0 else rect(0, -2, 800, 300)
                path = temp_paths[index]
                call('ocr.tempPath'); calls[-1]['value'] = path
                call('ocr.capture', region['x'], region['y'], region['w'], region['h'], path)
                call('ocr.prepareAsync'); call('ocr.loadFile', path); call('ocr.openRead', 'file')
                call('ocr.createDecoder', 'stream'); call('ocr.getBitmap', 'decoder'); call('ocr.recognize', 'engine', 'bitmap')
                call('ocr.removeTemp', path)
                response(dict(status='ok', schema='cucp.ocr-screen/v1', region=region, text='한글 OWNED 123',
                              line_count=1, lines=[dict(text='한글 OWNED 123', word_count=3)], engine_warm=True))
    elif identity in ('uia-en-US', 'uia-tr-TR', 'uia-ko-KR'):
        call('uia.load'); call('win32.ensure')
        call('uia.root'); call('uia.children', 'root', 'all'); call('uia.name', 'first'); call('uia.subtree', 'first')
        first = case['uia_children'][0]['subtree']; uia_scan(first)
        response(uia_result(first, [100, 80, 50], 'Application'))
        call('uia.root'); call('uia.children', 'root', 'all'); call('uia.name', 'first'); call('uia.name', 'second')
        call('uia.subtree', 'root'); uia_scan(case['uia_subtree'])
        response(uia_result(case['uia_subtree'], [50], 'missing'))
        response(failed('missing_label'))
        call('uia.root'); call('uia.subtree', 'root'); uia_scan(case['uia_subtree'])
        response(uia_result(case['uia_subtree'], [50]))
    elif identity == 'uia-caps-ties':
        call('uia.load'); call('win32.ensure'); call('uia.root'); call('uia.subtree', 'root')
        selected = case['uia_subtree'][:16]; uia_scan(selected); response(uia_result(selected, [80] * 16))
    elif identity == 'uia-distinct-ties':
        call('uia.load'); call('win32.ensure'); call('uia.root'); call('uia.children', 'root', 'all')
        call('uia.name', 'first'); call('uia.subtree', 'first')
        selected = case['uia_children'][0]['subtree'][:16]
        uia_scan(selected); response(uia_result(selected, [80] * 16, 'Application'))
    elif identity in ('uia-scan-cap', 'uia-no-match'):
        call('uia.load'); call('win32.ensure'); call('uia.root'); call('uia.subtree', 'root')
        for element in case['uia_subtree'][:800]: call('uia.name', element['id'])
        response(dict(status='partial', reason='no_match', label='Save' if identity == 'uia-scan-cap' else 'missing', match=None, candidate_count=0))
    elif identity == 'focused-partial':
        call('win32.ensure'); call('win32.foreground'); response(dict(status='partial', reason='no_foreground'))
    else:
        raise AssertionError('Functional-intent case needs an independent behavior contract: ' + identity)
    return dict(responses=responses, calls=calls, request_count=len(responses),
                effects=[{'win32.ensure': 'ensure_win32', 'uia.load': 'ensure_uia', 'ocr.initialize': 'ensure_ocr'}[c['op']]
                         for c in calls if c['op'] in ('win32.ensure', 'uia.load', 'ocr.initialize')])


def validate_functional_intent_behavior(case, before):
    validate_oracle_execution(case, before)
    if before.get('oracle_mode') != 'functional-intent':
        raise AssertionError('Positive action checks require explicit functional-intent mode')
    paths = [call.get('value') for call in before['calls'] if call.get('op') == 'ocr.tempPath']
    expected_count = 2 if case['id'] == 'ocr-success-truthiness-cache' else 0
    if (len(paths) != expected_count
            or any(not isinstance(path, str) or not re.fullmatch(r'.*[\\/]cucp-srv-ocr-[0-9a-f]{32}\.png', path) for path in paths)
            or len(set(paths)) != len(paths)):
        raise AssertionError('Functional-intent OCR temporary paths must have the exact generated shape and count')
    expected = functional_intent_contract(case, temp_paths=paths)
    observed = {key: copy.deepcopy(before.get(key)) for key in expected}
    if not same_json_types(observed, expected):
        raise AssertionError('Functional-intent outputs or action effect order violate the independent contract: ' + case['id']
                             + '\nexpected=' + repr(expected) + '\nobserved=' + repr(observed))


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
    def test_uia_best_rejects_numeric_type_changes_after_json_round_trip(self):
        case = next(case for case in cases() if case['id'] == 'uia-en-US')
        before = functional_intent_contract(case)
        before['oracle_mode'] = 'functional-intent'
        before = json.loads(json.dumps(before))
        result = before['responses'][0]['result']
        self.assertIsNot(result['best'], result['candidates'][0])
        validate_functional_intent_behavior(case, before)
        for path, value in [(('score',), 100.0), (('click_point', 'x'), 50.0)]:
            altered = copy.deepcopy(before)
            target = altered['responses'][0]['result']['best']
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(AssertionError):
                validate_functional_intent_behavior(case, altered)

    def test_functional_contract_rejects_tie_permutations_and_best_replacement(self):
        for identity in ('modal-large-ties', 'modal-distinct-ties', 'uia-caps-ties', 'uia-distinct-ties'):
            case = next(case for case in cases() if case['id'] == identity)
            before = json.loads(json.dumps(dict(functional_intent_contract(case), oracle_mode='functional-intent')))
            validate_functional_intent_behavior(case, before)
            key = 'modal_candidates' if identity.startswith('modal-') else 'candidates'
            with self.subTest(case=identity, change='tied-acquisition-order'):
                altered = copy.deepcopy(before)
                candidates = altered['responses'][0]['result'][key]
                self.assertEqual(candidates[0]['score'], candidates[1]['score'])
                candidates[0], candidates[1] = candidates[1], candidates[0]
                if key == 'candidates':
                    altered['responses'][0]['result']['best'] = copy.deepcopy(candidates[0])
                with self.assertRaises(AssertionError):
                    validate_functional_intent_behavior(case, altered)
            if key == 'candidates':
                with self.subTest(case=identity, change='supported-but-later-best'):
                    altered = copy.deepcopy(before)
                    altered['responses'][0]['result']['best'] = copy.deepcopy(altered['responses'][0]['result'][key][1])
                    with self.assertRaises(AssertionError):
                        validate_functional_intent_behavior(case, altered)

    def test_recorded_args_only_functional_defects_cannot_be_relabelled_as_qualified(self):
        corpus = {case['id']: case for case in cases()}
        for identity in ('ocr-success-truthiness-cache', 'uia-en-US', 'uia-tr-TR', 'uia-ko-KR',
                         'modal-large-ties', 'uia-caps-ties'):
            case = corpus[identity]
            baseline, _ = retained_args_only(case)
            baseline['oracle_mode'] = 'functional-intent'
            with self.subTest(case=identity), self.assertRaises(AssertionError):
                validate_functional_intent_behavior(case, baseline)

    def test_distinct_ties_preserve_selected_identity_geometry_and_first_root_child(self):
        corpus = {case['id']: case for case in cases()}
        modal = functional_intent_contract(corpus['modal-distinct-ties'])
        candidates = modal['responses'][0]['result']['modal_candidates']
        self.assertEqual([item['hwnd'] for item in candidates], [5102, 5104, 5101, 5103, 5105, 5106])
        self.assertEqual([item['score'] for item in candidates], [120, 120, 80, 80, 20, 20])
        self.assertEqual(candidates[0]['title'], 'Modal acquisition first')
        uia = functional_intent_contract(corpus['uia-distinct-ties'])
        selected = uia['responses'][0]['result']
        self.assertEqual([item['name'] for item in selected['candidates']], ['Save choice ' + str(i) for i in range(16)])
        self.assertEqual(selected['best']['name'], 'Save choice 0')
        self.assertEqual(selected['best']['rect'], rect(-51, 21, 105, 73))
        self.assertEqual(selected['best']['click_point'], dict(x=2, y=58))
        self.assertEqual(selected['best']['control_type'], 'button')
        self.assertEqual(selected['candidate_count'], 16)
        self.assertEqual([call['args'] for call in uia['calls'] if call['op'] == 'uia.subtree'], [['first']])
        self.assertEqual([call['args'][0] for call in uia['calls'] if call['op'] == 'uia.name'],
                         ['first'] + ['distinct-' + str(i) for i in range(16)])
        scan = functional_intent_contract(corpus['uia-scan-cap'])
        self.assertEqual([call['args'][0] for call in scan['calls'] if call['op'] == 'uia.name'],
                         ['n' + str(i) for i in range(800)])
        self.assertEqual(scan['responses'][0]['result']['candidate_count'], 0)

    def test_independent_contract_preserves_json_types(self):
        for value, changed in [(False, 0), (True, 1), (1, 1.0), ([], {}), (None, ''),
                               ({'x': [False]}, {'x': [0]})]:
            with self.subTest(value=value, changed=changed):
                self.assertFalse(same_json_types(value, changed))
                self.assertTrue(same_json_types(value, copy.deepcopy(value)))

    def test_independent_functional_contract_covers_every_case_and_rejects_canned_results(self):
        paths = [r'C:\Temp\cucp-srv-ocr-' + letter * 32 + '.png' for letter in ('a', 'b')]
        for case in cases():
            before = functional_intent_contract(case, temp_paths=paths)
            before['oracle_mode'] = 'functional-intent'
            with self.subTest(case=case['id']):
                validate_functional_intent_behavior(case, before)
                captured_calls(case, before['calls'])
                self.assertEqual(len(before['responses']), len(case['requests']))
                for field, value in [('calls', []), ('effects', []), ('oracle_mode', 'exact-original'),
                                     ('oracle_mode', 'corrected-intent')]:
                    if before[field] == value: continue
                    altered = copy.deepcopy(before); altered[field] = value
                    with self.assertRaises(AssertionError): validate_functional_intent_behavior(case, altered)
                altered = copy.deepcopy(before)
                altered['responses'][0]['result'] = dict(status='ok')
                with self.assertRaises(AssertionError): validate_functional_intent_behavior(case, altered)
                if len(before['calls']) > 1:
                    altered = copy.deepcopy(before)
                    different = next(index for index, call in enumerate(altered['calls']) if call != altered['calls'][0])
                    altered['calls'][0], altered['calls'][different] = altered['calls'][different], altered['calls'][0]
                    with self.assertRaises(AssertionError): validate_functional_intent_behavior(case, altered)
        with self.assertRaisesRegex(AssertionError, 'independent behavior contract'):
            functional_intent_contract(dict(id='new-unreviewed-case', requests=[]))

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
        historical = {'denied-six', 'ocr-success-truthiness-cache', 'ocr-max-dimension', 'ocr-init-retry',
                      'modal-large-ties', 'uia-caps-ties', 'uia-scan-cap', 'focused-partial', 'uia-no-match'}
        historical.update(action + '-' + culture for action in ('windows', 'modal', 'uia')
                          for culture in ('en-US', 'tr-TR', 'ko-KR'))
        self.assertEqual(len(historical), 18)
        self.assertEqual({case['id'] for case in values}, historical | {'modal-distinct-ties', 'uia-distinct-ties'})
        self.assertEqual(set(args_only_case_ids()), historical)
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
        The exact-original action run below remains independently classified.
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
            save_classification(classify_binding_probe(result, source=source), result['evidence_path'])
            source.write_bytes(source.read_bytes() + b'\n# changed binding-probe source\n')
            refused = run_evidence(command, directory=logs, label='original-dispatch-binding-source-refusal',
                                   cwd=root, timeout=20, limit=256 * 1024)
            require_success(refused, expected_exit=1)
            self.assertEqual(refused['stdout'], b'')
            self.assertIn('Published server source hash mismatch', refused['stderr'].decode('utf-8-sig'))

    def oracle(self, root, logs, label, *, source, stubs=None, wrong_binding=False, extent_fault=None,
               corrected_intent=False, args_extent_fault=None, functional_intent=False,
               functional_extent_fault=None, functional_extent_target=None, driver=None):
        command = [shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(driver or FIXTURES / 'oracle.ps1'), '-Source', str(source),
                   '-Manifest', str(FIXTURES / 'source-manifest.json'), '-CasePath', str(root / 'case.json')]
        if stubs is not False:
            command += ['-Stubs', str(stubs or FIXTURES / 'OracleAcquisition.cs')]
        if wrong_binding:
            command += ['-TestWrongBinding']
        if extent_fault is not None:
            command += ['-TestTypeExtentFault', extent_fault]
        if corrected_intent:
            command += ['-CorrectedIntent']
        if args_extent_fault is not None:
            command += ['-TestArgsExtentFault', args_extent_fault]
        if functional_intent:
            command += ['-FunctionalIntent']
        if functional_extent_fault is not None:
            command += ['-TestFunctionalExtentFault', functional_extent_fault]
        if functional_extent_target is not None:
            command += ['-TestFunctionalExtentTarget', functional_extent_target]
        return run_evidence(command, directory=logs, label=label, cwd=root, timeout=40, limit=2 * 1024 * 1024)

    def test_oracle_type_edit_order_and_refusals(self):
        with tempfile.TemporaryDirectory(prefix='CUCP extent oracle ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            raw = published_source('scripts/cucp-helper-server.ps1', logs)
            source = root / 'published.ps1'
            source.write_bytes(raw)
            (root / 'case.json').write_text(json.dumps(dict(requests=[])), encoding='utf-8')
            for mode, corrected, functional in [('exact-original', False, False),
                                                 ('corrected-intent', True, False),
                                                 ('functional-intent', True, True)]:
                with self.subTest(mode=mode):
                    label = 'oracle-type-edit' if not corrected else mode + '-type-edit'
                    success = self.oracle(root, logs, label + '-order', source=source,
                                          corrected_intent=corrected, functional_intent=functional)
                    require_success(success)
                    before = json.loads(success['stdout'].decode('utf-8-sig'))
                    seam = before['oracle_seam']
                    seam['guarded_types'].sort()
                    seam['type_substitutions'].sort(key=lambda s: s['start_utf16'])
                    self.assertEqual(seam, expected_type_seam(raw))
                    self.assertEqual(before['responses'], [])
                    self.assertEqual(before['calls'], [])
                    self.assertEqual(before['oracle_mode'], mode)
                    if corrected:
                        before['args_seam']['args_substitutions'].sort(key=lambda site: site['start_utf16'])
                        self.assertEqual(before['args_seam'], expected_args_seam(raw))
                    else:
                        self.assertIsNone(before['args_seam'])
                    if not functional:
                        self.assertNotIn('functional_seam', before)
                    self.assertEqual(success['stderr'], b'')
                    first = next(s for s in seam['type_substitutions'] if s['function'] == '_Action-Windows')
                    for fault, reason, planned, applied in [('duplicate', 'overlap_or_order', 12, 11),
                                                          ('changed', 'text_mismatch', 11, 10)]:
                        with self.subTest(fault=fault):
                            result = self.oracle(root, logs, label + '-' + fault, source=source, extent_fault=fault,
                                                 corrected_intent=corrected, functional_intent=functional)
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

    def test_corrected_intent_args_extents_and_faults_are_separately_evidenced(self):
        with tempfile.TemporaryDirectory(prefix='CUCP corrected intent extent ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            raw = published_source('scripts/cucp-helper-server.ps1', logs)
            source = root / 'published.ps1'; source.write_bytes(raw)
            (root / 'case.json').write_text(json.dumps(dict(requests=[])), encoding='utf-8')
            result = self.oracle(root, logs, 'corrected-intent-args-census', source=source, corrected_intent=True)
            require_success(result)
            self.assertEqual(result['stderr'], b'')
            observed = json.loads(result['stdout'].decode('utf-8-sig'))
            self.assertEqual(observed['oracle_mode'], 'corrected-intent')
            self.assertNotIn('functional_seam', observed)
            self.assertEqual(observed['responses'], [])
            self.assertEqual(observed['calls'], [])
            observed['oracle_seam']['guarded_types'].sort()
            observed['oracle_seam']['type_substitutions'].sort(key=lambda site: site['start_utf16'])
            self.assertEqual(observed['oracle_seam'], expected_type_seam(raw))
            observed['args_seam']['args_substitutions'].sort(key=lambda site: site['start_utf16'])
            self.assertEqual(observed['args_seam'], expected_args_seam(raw))
            first = expected_args_seam(raw)['args_substitutions'][0]
            for fault, reason in [('duplicate', 'overlap_or_order'), ('changed', 'text_mismatch'), ('wrongname', 'wrong_replacement_name')]:
                with self.subTest(fault=fault):
                    refused = self.oracle(root, logs, 'corrected-intent-args-' + fault, source=source,
                                          corrected_intent=True, args_extent_fault=fault)
                    require_success(refused, expected_exit=1)
                    self.assertEqual(refused['stdout'], b'')
                    lines = refused['stderr'].decode('utf-8-sig').splitlines()
                    diagnostic = json.loads(lines[0])
                    self.assertEqual(diagnostic['schema'], 'cucp.oracle-args-extent-refusal/v1')
                    self.assertEqual(diagnostic['reason'], reason)
                    self.assertEqual(diagnostic['function'], first['function'])
                    self.assertEqual(diagnostic['start_utf16'], first['start_utf16'])
                    self.assertEqual(diagnostic['end_utf16'], first['end_utf16'])
                    self.assertEqual(diagnostic['planned'], 16 if fault == 'duplicate' else 15)
                    self.assertEqual(diagnostic['applied'], 15 if fault == 'duplicate' else 14)
                    self.assertLessEqual(len(diagnostic['actual_prefix'].encode('utf-16-le')), 256)
                    self.assertIn('Unsafe corrected-intent Args extent', '\n'.join(lines[1:]))
            refused = self.oracle(root, logs, 'original-refuses-args-fault-switch', source=source, args_extent_fault='duplicate')
            require_success(refused, expected_exit=1)
            self.assertEqual(refused['stdout'], b'')
            self.assertIn('Args extent faults require explicit corrected-intent mode', refused['stderr'].decode('utf-8-sig'))

    def test_functional_intent_census_and_refusals_are_separately_evidenced(self):
        with tempfile.TemporaryDirectory(prefix='CUCP functional intent extent ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            raw = published_source('scripts/cucp-helper-server.ps1', logs)
            source = root / 'published.ps1'; source.write_bytes(raw)
            (root / 'case.json').write_text(json.dumps(dict(requests=[])), encoding='utf-8')
            types, args, functional = expected_type_seam(raw), expected_args_seam(raw), expected_functional_seam(raw)
            result = self.oracle(root, logs, 'functional-intent-census', source=source,
                                 corrected_intent=True, functional_intent=True)
            require_success(result)
            self.assertEqual(result['stderr'], b'')
            observed = json.loads(result['stdout'].decode('utf-8-sig'))
            self.assertEqual(set(observed), {'oracle_mode', 'oracle_seam', 'args_seam', 'functional_seam',
                                             'responses', 'calls', 'effects', 'request_count'})
            self.assertEqual(observed['oracle_mode'], 'functional-intent')
            self.assertEqual(observed['responses'], [])
            self.assertEqual(observed['calls'], [])
            self.assertEqual(observed['effects'], [])
            self.assertEqual(observed['request_count'], 0)
            observed['oracle_seam']['guarded_types'].sort()
            observed['oracle_seam']['type_substitutions'].sort(key=lambda site: site['start_utf16'])
            observed['args_seam']['args_substitutions'].sort(key=lambda site: site['start_utf16'])
            observed['functional_seam']['functional_substitutions'].sort(key=lambda site: site['start_utf16'])
            self.assertEqual(observed['oracle_seam'], types)
            self.assertEqual(observed['args_seam'], args)
            self.assertEqual(observed['functional_seam'], functional)
            self.assertEqual(len(functional['functional_substitutions']), 4)
            # Copy the counted driver and alter only one harmless whitespace
            # token. No new executable PowerShell body is manufactured here.
            driver_text = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
            helper_header = 'function _Oracle-StableScore {'
            self.assertEqual(driver_text.count(helper_header), 1)
            changed_driver = root / 'changed-helper-whitespace.ps1'
            changed_driver.write_text(driver_text.replace(helper_header, 'function _Oracle-StableScore  {', 1), encoding='utf-8')
            refused = self.oracle(root, logs, 'functional-intent-stable-helper-hash-refusal', source=source,
                                  corrected_intent=True, functional_intent=True, driver=changed_driver)
            require_success(refused, expected_exit=1)
            self.assertEqual(refused['stdout'], b'')
            self.assertIn('Stable score helper definition changed', refused['stderr'].decode('utf-8-sig'))
            for target, kind in [('async-type', 'parameter'), ('score-sort', 'score-sort-command')]:
                first = next(site for site in functional['functional_substitutions'] if site['kind'] == kind)
                combined = [site for site in types['type_substitutions'] + args['args_substitutions']
                            + functional['functional_substitutions'] if site['function'] == first['function']]
                applied_before_target = sum(site['start_utf16'] > first['start_utf16'] for site in combined)
                for fault, reason in [('duplicate', 'overlap_or_order'), ('changed', 'text_mismatch'),
                                      ('wrongname', 'wrong_replacement_name')]:
                    with self.subTest(target=target, fault=fault):
                        refused = self.oracle(root, logs, 'functional-intent-' + target + '-' + fault,
                                              source=source, corrected_intent=True, functional_intent=True,
                                              functional_extent_fault=fault, functional_extent_target=target)
                        require_success(refused, expected_exit=1)
                        self.assertEqual(refused['stdout'], b'')
                        lines = refused['stderr'].decode('utf-8-sig').splitlines()
                        diagnostic = json.loads(lines[0])
                        self.assertEqual(diagnostic['schema'], 'cucp.oracle-functional-extent-refusal/v1')
                        self.assertEqual(diagnostic['reason'], reason)
                        for key in ('function', 'owner_function', 'kind', 'start_utf16', 'end_utf16'):
                            self.assertEqual(diagnostic[key], first[key])
                        self.assertEqual(diagnostic['planned'], len(combined) + (fault == 'duplicate'))
                        self.assertEqual(diagnostic['applied'], applied_before_target + (fault == 'duplicate'))
                        self.assertLessEqual(len(diagnostic['actual_prefix'].encode('utf-16-le')), 256)
                        self.assertIn('Unsafe functional-intent extent', '\n'.join(lines[1:]))
            # Functional corrections do not relax the earlier Args edit guard.
            first_args = args['args_substitutions'][0]
            for fault, reason in [('duplicate', 'overlap_or_order'), ('changed', 'text_mismatch'),
                                  ('wrongname', 'wrong_replacement_name')]:
                with self.subTest(args_fault=fault):
                    refused = self.oracle(root, logs, 'functional-intent-args-' + fault, source=source,
                                          corrected_intent=True, functional_intent=True, args_extent_fault=fault)
                    require_success(refused, expected_exit=1)
                    self.assertEqual(refused['stdout'], b'')
                    lines = refused['stderr'].decode('utf-8-sig').splitlines()
                    diagnostic = json.loads(lines[0])
                    self.assertEqual(diagnostic['schema'], 'cucp.oracle-args-extent-refusal/v1')
                    self.assertEqual(diagnostic['reason'], reason)
                    for key in ('function', 'start_utf16', 'end_utf16'):
                        self.assertEqual(diagnostic[key], first_args[key])
                    self.assertEqual(diagnostic['planned'], 16 if fault == 'duplicate' else 15)
                    self.assertEqual(diagnostic['applied'], 15 if fault == 'duplicate' else 14)
                    self.assertLessEqual(len(diagnostic['actual_prefix'].encode('utf-16-le')), 256)
                    self.assertIn('Unsafe corrected-intent Args extent', '\n'.join(lines[1:]))
            refused = self.oracle(root, logs, 'functional-intent-requires-args-mode', source=source,
                                  functional_intent=True)
            require_success(refused, expected_exit=1)
            self.assertEqual(refused['stdout'], b'')
            self.assertIn('Functional-intent mode requires explicit corrected-intent mode', refused['stderr'].decode('utf-8-sig'))
            for corrected in (False, True):
                with self.subTest(functional_fault_without_mode=corrected):
                    refused = self.oracle(root, logs, 'functional-fault-requires-mode-' + str(corrected), source=source,
                                          corrected_intent=corrected, functional_extent_fault='duplicate')
                    require_success(refused, expected_exit=1)
                    self.assertEqual(refused['stdout'], b'')
                    self.assertIn('Functional extent faults require explicit functional-intent mode', refused['stderr'].decode('utf-8-sig'))

    def test_oracle_rejects_source_facade_and_type_binding_changes_before_dispatch(self):
        with tempfile.TemporaryDirectory(prefix='CUCP guarded oracle ') as directory:
            root = Path(directory)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            original_source = published_source('scripts/cucp-helper-server.ps1', logs)
            source = root / 'published.ps1'
            source.write_bytes(original_source)
            (root / 'case.json').write_text(json.dumps(dict(win32=True, ocr=True, requests=[dict(action='ocr-screen-fast', args={})])), encoding='utf-8')

            def expect_failure(label, message, **kwargs):
                for mode, corrected, functional in [('exact-original', False, False),
                                                     ('corrected-intent', True, False),
                                                     ('functional-intent', True, True)]:
                    result = self.oracle(root, logs, label + ('-' + mode if corrected else ''),
                                         source=source, corrected_intent=corrected, functional_intent=functional, **kwargs)
                    # Timeout, launch error, truncated output, etc. never count
                    # as a successful refusal. Raw evidence is already saved.
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

    def test_original_and_args_only_observations_then_functional_action_differential(self):
        with tempfile.TemporaryDirectory(prefix='CUCP helper oracle 한글 ') as directory:
            root=Path(directory)
            logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root/'evidence'))
            source=root/'published.ps1';source.write_bytes(published_source('scripts/cucp-helper-server.ps1',logs))
            expected_seam=expected_type_seam(source.read_bytes())
            expected_args=expected_args_seam(source.read_bytes())
            expected_functional=expected_functional_seam(source.read_bytes())
            for case in cases():
                with self.subTest(case=case['id']):
                    path=root/'case.json';path.write_text(json.dumps(case,ensure_ascii=True),encoding='utf-8')
                    with self.subTest(phase='original-binding-baseline'):
                        original=self.oracle(root,logs,case['id']+'-oracle',source=source)
                        require_success(original)
                        # This independently classified failure is retained;
                        # it never becomes successful original action parity.
                        save_classification(classify_original_actions(original, case=case, source=source), original['evidence_path'])
                    if case['id'] in args_only_case_ids():
                        with self.subTest(phase='args-only-baseline'):
                            args_only=self.oracle(root,logs,case['id']+'-corrected-intent-oracle',source=source,corrected_intent=True)
                            require_success(args_only)
                            self.assertEqual(args_only['stderr'], b'')
                            observed=json.loads(args_only['stdout'].decode('utf-8-sig'))
                            observed['oracle_seam']['guarded_types'].sort()
                            observed['oracle_seam']['type_substitutions'].sort(key=lambda site:site['start_utf16'])
                            self.assertEqual(observed['oracle_seam'],expected_seam)
                            observed['args_seam']['args_substitutions'].sort(key=lambda site:site['start_utf16'])
                            self.assertEqual(observed['args_seam'],expected_args)
                            self.assertNotIn('functional_seam', observed)
                            # Recorded behavior and narrowly classified ordering
                            # changes stay unqualified; infrastructure failures fail.
                            save_classification(classify_args_only_actions(args_only,case=case,source=source),args_only['evidence_path'])
                    with self.subTest(phase='functional-intent'):
                        functional=self.oracle(root,logs,case['id']+'-functional-intent-oracle',source=source,
                                               corrected_intent=True,functional_intent=True)
                        require_success(functional)
                        self.assertEqual(functional['stderr'], b'')
                        before=json.loads(functional['stdout'].decode('utf-8-sig'))
                        before['oracle_seam']['guarded_types'].sort()
                        before['oracle_seam']['type_substitutions'].sort(key=lambda site:site['start_utf16'])
                        self.assertEqual(before['oracle_seam'],expected_seam)
                        before['args_seam']['args_substitutions'].sort(key=lambda site:site['start_utf16'])
                        self.assertEqual(before['args_seam'],expected_args)
                        before['functional_seam']['functional_substitutions'].sort(key=lambda site:site['start_utf16'])
                        self.assertEqual(before['functional_seam'],expected_functional)
                        validate_functional_intent_behavior(case,before)
                        calls=captured_calls(case,before['calls'])
                        fixture=dict(pid=123,pipe_name='fixture',culture=case.get('culture','en-US'),clock=['2020-01-01T00:00:00Z']*(sum(r['action'].lower()=='health' for r in case['requests'])+1),calls=calls,requests=case['requests'])
                        path.write_text(json.dumps(fixture,ensure_ascii=True),encoding='utf-8')
                        candidate=run_evidence([HOST,'fixture','--input-file',str(path)],directory=logs,label=case['id']+'-functional-intent-candidate',cwd=root,timeout=20,limit=2*1024*1024)
                        require_success(candidate)
                        self.assertEqual(candidate['stderr'], b'')
                        after=json.loads(candidate['stdout'].decode('utf-8-sig'))
                        self.assertEqual(before['responses'],after['responses'])
                        self.assertTrue(same_json_types(before['responses'],after['responses']), 'Functional-intent response JSON types differ')
                        self.assertEqual(after['consumed'],len(calls))
                        expected_calls=[dict(op=x['op'],args=x['args']) for x in before['calls']]
                        self.assertTrue(same_json_types(expected_calls,after['calls']), 'Functional-intent acquisition order, arguments, or types differ')
                        expected_after=dict(responses=before['responses'], calls=expected_calls,
                                            consumed=len(calls), clock_consumed=len(fixture['clock']),
                                            state=dict(request_count=len(case['requests']),
                                                       win32_loaded=case.get('win32',False),
                                                       uia_loaded=case.get('uia',False),
                                                       ocr_warm=case.get('ocr',False),
                                                       started_at='2020-01-01T00:00:00.0000000Z'))
                        self.assertTrue(same_json_types(expected_after,after),
                                        'Functional-intent full candidate outputs, state, or JSON types differ')
                        # Exhaustible provider refuses missing, extra, reordered,
                        # or differently-parameterized calls before result parsing.
