"""Exact published PS5 action bodies over inert acquisition namespace facades.

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
from test_legacy_helper_source import ROOT, FIXTURES, published_source

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


def captured_calls(case, trace):
    windows = {w['hwnd']: w for w in case.get('windows', [])}
    elements = {}
    def register(values):
        for element in values:
            elements[element['id']] = element
            register(element.get('subtree', []))
    register(case.get('uia_children', [])); register(case.get('uia_subtree', []))
    result = []
    for effect in trace:
        op, args = effect['op'], effect['args']
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
    def test_published_actions_inert_providers_and_exact_query_order(self):
        with tempfile.TemporaryDirectory(prefix='CUCP helper oracle 한글 ') as directory:
            root=Path(directory)
            logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root/'evidence'))
            source=root/'published.ps1';source.write_bytes(published_source('scripts/cucp-helper-server.ps1',logs))
            for case in cases():
                with self.subTest(case=case['id']):
                    path=root/'case.json';path.write_text(json.dumps(case,ensure_ascii=True),encoding='utf-8')
                    original=run_evidence([shutil.which('powershell.exe'),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(FIXTURES/'oracle.ps1'),
                       '-Source',str(source),'-Manifest',str(FIXTURES/'source-manifest.json'),'-CasePath',str(path),'-Stubs',str(FIXTURES/'OracleAcquisition.cs')],
                       directory=logs,label=case['id']+'-oracle',cwd=root,timeout=40,limit=2*1024*1024)
                    require_success(original)
                    before=json.loads(original['stdout'].decode('utf-8-sig'))
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
