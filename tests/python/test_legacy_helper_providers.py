"""Portable tests of actual-provider verdicts; never instantiate desktop providers."""
import copy
import tempfile
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

from helper_provider_expectations import GROUPS, same, shape, validate_case, validate_group, validate_uia, validate_ocr
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('helper_provider_gate',ROOT/'pcucp-next/packaging/qualify_legacy_helper_providers.py')
GATE=importlib.util.module_from_spec(spec);spec.loader.exec_module(GATE)

def ready():
    return dict(pid=42,hwnd=123,title='Owned unique',window_class='WindowsForms10.Window.fixture',outer=dict(x=120,y=120,w=620,h=570),
                ocr=dict(x=140,y=560,width=560,height=70),run=dict(x=160,y=190,width=130,height=40),
                run_prefix=dict(x=160,y=360,width=200,height=35),run_contains=dict(x=380,y=360,width=200,height=35))

def row(name,result,calls=None):
    return dict(schema='cucp.helper-provider-case/v1',name=name,pid=99,action='focused',args=None,result=result,error=None,calls=calls or [],diagnostics=[],
                state=dict(request_count=1,win32_loaded=True,uia_loaded=False,ocr_warm=False))

def focused():
    r=ready();p=dict(status='ok',schema='cucp.focused/v1',hwnd=r['hwnd'],title=r['title'],**{'class':r['window_class']},pid=r['pid'],rect=r['outer'])
    return row('focused',p,[dict(operation='win32.foreground',arguments=[],source='actual-provider',result=r['hwnd'])])

def token(i):return dict(object_id=i,type='System.Windows.Automation.AutomationElement')

def uia():
    r=ready();calls=[dict(operation='uia.root',arguments=[],source='actual-provider',result=token(1)),dict(operation='uia.name',arguments=[token(2)],source='actual-provider',result=r['title'])]
    d=[]
    for i,key,text in [(3,'run_contains','prefix Run 한글'),(4,'run','Run 한글'),(5,'run_prefix','Run 한글 extra')]:
        rect=r[key];d.append(dict(element=token(i),name=text,control_type='button',pid=42,hwnd=i,rect=dict(x=rect['x'],y=rect['y'],w=rect['width'],h=rect['height'])))
    calls.append(dict(operation='uia.subtree',arguments=[token(2)],source='actual-provider',result=[x['element'] for x in d]))
    calls.extend(dict(operation='uia.name',arguments=[x['element']],source='actual-provider',result=x['name']) for x in d)
    expected=[]
    for i,score in [(1,100),(2,80),(0,50)]:
        a=d[i];z=a['rect'];expected.append(dict(name=a['name'],score=score,rect=z,click_point=dict(x=round(z['x']+z['w']/2),y=round(z['y']+z['h']/2)),control_type='button'))
    x=row('uia-run',dict(status='ok',schema='cucp.uia-find/v1',label='Run 한글',match=r['title'],score=100,best=expected[0],candidates=expected,candidate_count=3,uia_warm=True),calls)
    x['action']='uia-find-fast';x['args']=dict(Label='Run 한글',Match=r['title']);x['diagnostics']=d;x['state']['uia_loaded']=True
    return x

def ocr():
    r=ready()['ocr'];path='C:\\owned\\cucp-srv-ocr-'+'0'*32+'.png'
    calls=[dict(operation='ocr.tempPath',result=path),dict(operation='ocr.capture',arguments=[r['x'],r['y'],r['width'],r['height'],path],source='generated-owned-image',image_sha256='0'*64,image_bytes=1,image_artifact='owned.png'),
           dict(operation='ocr.loadFile',result=token(1)),dict(operation='ocr.openRead',arguments=[token(1)],result=token(2)),dict(operation='ocr.recognize',arguments=[token(3),token(4)],result=dict(text='HELLO 2468',lines=[dict(text='HELLO 2468',word_count=2)])),dict(operation='ocr.removeTemp',arguments=[path],result=None,remaining_file=False)]
    x=row('ocr-file-text',dict(status='ok',schema='cucp.ocr-screen/v1',region=dict(x=r['x'],y=r['y'],w=r['width'],h=r['height']),text='HELLO 2468',line_count=1,lines=[dict(text='HELLO 2468',word_count=2)],engine_warm=True),calls)
    x['state']['ocr_warm']=True;x['action']='ocr-screen-fast';x['args']=dict(X=r['x'],Y=r['y'],W=r['width'],H=r['height']);return x

class ProviderExpectationTests(unittest.TestCase):
    def test_exact_owned_focused_passes(self):validate_case(focused(),ready())
    def test_other_foreground_cannot_earn_owned_coverage(self):
        x=focused();x['result']['hwnd']=321
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_focused_partial_is_not_success(self):
        x=focused();x['result']=dict(status='partial',reason='no_foreground')
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_extra_fields_rejected(self):
        x=focused();x['result']['extra']=1
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_numeric_boolean_mismatch_rejected(self):
        with self.assertRaises(AssertionError):same(1,True)
    def test_shape_cannot_drop_identity(self):
        with self.assertRaises(AssertionError):shape(dict(title='Owned'),'hwnd title')
    def test_dispatch_exception_never_counts_as_expected_error(self):
        x=focused();x['error']=dict(type='Failure',detail='unavailable')
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_owned_uia_numeric_ranking(self):validate_case(uia(),ready())
    def test_uia_proxy_role_difference_not_normalized(self):
        x=uia();x['diagnostics'][0]['control_type']='pane'
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_uia_wrong_best_rejected(self):
        x=uia();x['result']['best']=x['result']['candidates'][-1]
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_uia_order_difference_not_normalized(self):
        x=uia();x['result']['candidates'].reverse()
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_uia_wrong_owned_geometry_rejected(self):
        x=uia();x['diagnostics'][0]['rect']['x']+=1
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_uia_malformed_subtree_identity_rejected(self):
        x=uia();x['calls'][2]['result'].reverse()
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_scan_bound_requires_owned_beyond_target(self):
        x=uia();x['name']='uia-scan-bound';x['args']['Label']='Beyond scan';x['result']=dict(status='partial',reason='no_match',label='Beyond scan',match=ready()['title'],candidate_count=0)
        with self.assertRaises(AssertionError):validate_uia(x,ready())
    def test_missing_label_error_precise(self):
        x=row('uia-missing',dict(status='error',reason='missing_label'));validate_uia(x,ready())
        x['result']['reason']='uia_load_failed'
        with self.assertRaises(AssertionError):validate_uia(x,ready())
    def test_missing_label_must_not_query_root(self):
        x=row('uia-missing',dict(status='error',reason='missing_label'),[dict(operation='uia.root')])
        with self.assertRaises(AssertionError):validate_uia(x,ready())
    def test_exact_generated_ocr_success(self):validate_case(ocr(),ready())
    def test_partial_ocr_is_unqualified(self):
        x=ocr();x['result']=dict(status='partial',reason='no_language')
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_blank_ocr_not_text_success(self):
        x=ocr();x['result']['text']=''
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_ocr_text_whitespace_is_not_normalized(self):
        x=ocr();x['result']['text']+='\r\n'
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_ocr_temporary_file_must_be_removed(self):
        x=ocr();x['calls'][-1]['remaining_file']=True
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_owned_capture_cannot_use_generated_substitute(self):
        x=ocr();x['name']='ocr-owned-text'
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_image_evidence_required(self):
        x=ocr();del x['calls'][1]['image_sha256']
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_init_error_never_counts_for_available_language(self):
        x=ocr();x['name']='ocr-no-language';x['state']['ocr_warm']=False;x['result']=dict(status='error',reason='ocr_init_failed',detail='no_ocr_language_available')
        with self.assertRaises(AssertionError):validate_ocr(x,ready())
    def test_empty_or_reordered_group_rejected(self):
        with self.assertRaises(AssertionError):validate_group('native',[],ready())

    def test_wrong_case_action_rejected(self):
        x=ocr();x['action']='wrong-action'
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_wrong_request_arguments_rejected(self):
        x=ocr();x['args']['X']=999
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def test_capture_coordinate_difference_rejected(self):
        x=ocr();x['calls'][1]['arguments'][0]=999
        with self.assertRaises(AssertionError):validate_case(x,ready())
    def retry_group(self):
        x=ocr();x['name']='ocr-init-retry';x['state']['request_count']=2
        for c in x['calls']: c.setdefault('source','actual-provider');c.setdefault('arguments',[])
        x['calls'][:0]=[dict(operation='ocr.initialize',source='actual-provider',arguments=[],result=None),dict(operation='ocr.createProfile',source='actual-provider',arguments=[],actual_result=token(3),result=token(3))]
        first=copy.deepcopy(x);first['name']='ocr-no-language';first['state'].update(request_count=1,ocr_warm=False)
        first['result']=dict(status='error',reason='ocr_init_failed',detail='no_ocr_language_available')
        first['calls']=[dict(operation='win32.ensure',source='actual-provider',arguments=[],result=None),dict(operation='ocr.initialize',source='actual-provider',arguments=[],result=None),dict(operation='ocr.createProfile',source='actual-provider-plus-explicit-profile-null-seam',arguments=[],actual_result=token(3),result=None),dict(operation='ocr.languages',source='actual-provider-plus-explicit-empty-languages-seam',arguments=[],actual_result=[token(5)],result=[])]
        return [first,x]
    def test_retry_seams_and_engine_identity_positive(self):self.assertEqual(validate_group('ocr-retry',self.retry_group(),ready()),[])
    def test_retry_cannot_omit_language_query(self):
        x=self.retry_group();x[0]['calls'].pop()
        with self.assertRaises(AssertionError):validate_group('ocr-retry',x,ready())
    def test_retry_cannot_hide_successful_first_engine(self):
        x=self.retry_group();x[0]['calls'][2]['result']=token(9)
        with self.assertRaises(AssertionError):validate_group('ocr-retry',x,ready())
    def test_cached_engine_cannot_change_at_recognition(self):
        x=self.retry_group();next(c for c in x[1]['calls'] if c['operation']=='ocr.recognize')['arguments'][0]=token(99)
        with self.assertRaises(AssertionError):validate_group('ocr-retry',x,ready())
    def test_initializer_failure_cannot_count_as_successful_retry(self):
        x=self.retry_group();x[0]['calls'][1]['error']='failed'
        with self.assertRaises(AssertionError):validate_group('ocr-retry',x,ready())

    def test_all_six_actions_have_required_cases(self):
        names=sum(GROUPS.values(),[])
        for name in ('windows-owned','health-cold','focused','modal','uia-run','ocr-owned-text'):self.assertIn(name,names)
        self.assertEqual(len(names),len(set(names)))
    def test_windows_flag_refuses_nonwindows(self):
        if sys.platform=='win32':self.skipTest('Non-Windows refusal control')
        with self.assertRaises(SystemExit) as error:GATE.main(['--windows'])
        self.assertEqual(error.exception.code,2)

class ProviderGateStructureTests(unittest.TestCase):
    def test_no_production_runtime_change_or_seam_registration(self):
        code=(ROOT/'tests/fixtures/legacy-helper-provider-probe/Program.cs').read_text()
        for token in ('SendInput','SetForegroundWindow','RegisterClientSide','Process.Start','powershell'):
            self.assertNotIn(token,code)
        self.assertIn('new WindowsLegacyHelperProvider()',code)
        self.assertIn('for (int row = y; row < y + height; row++) for (int col = x; col < x + width; col++)',code)
        self.assertIn('GetAncestor(WindowFromPoint(new Point(col, row)), 2) != hwnd',code)
    def test_actual_groups_continue_after_failure(self):
        code=(ROOT/'pcucp-next/packaging/qualify_legacy_helper_providers.py').read_text()
        self.assertIn("for group in list(GROUPS)+['uia-cold']:",code);self.assertIn('except Exception as error: failures.append(dict(group=group,error=str(error)))',code)
        self.assertIn("same(closed,dict(input_events=0,invoke_events=0,value_events=0))",code)
    def test_empty_discovery_fails(self):
        with self.assertRaises(AssertionError):GATE.require_regressions(dict(stderr=b'Ran 0 tests in 0.001s\n\nOK\n'),False)
    def test_unexpected_skip_fails(self):
        with self.assertRaises(AssertionError):GATE.require_regressions(dict(stderr=b"test_other (Suite.test_other) ... skipped 'missing'\nRan 43 tests in 0.001s\n"),False)
    def test_image_hash_matches_owned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'ocr-file-image-1.png';path.write_bytes(b'owned')
            call=dict(image_artifact=str(path),image_bytes=5,image_sha256=hashlib.sha256(b'owned').hexdigest())
            GATE.verify_images([dict(calls=[call])],root,'ocr-file')
            path.write_bytes(b'changed')
            with self.assertRaises(AssertionError):GATE.verify_images([dict(calls=[call])],root,'ocr-file')
    def test_image_other_group_or_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'ocr-owned-image-1.png';path.write_bytes(b'owned')
            call=dict(image_artifact=str(path),image_bytes=5,image_sha256=hashlib.sha256(b'owned').hexdigest())
            with self.assertRaises(AssertionError):GATE.verify_images([dict(calls=[call])],root,'ocr-file')
            with self.assertRaises(AssertionError):GATE.verify_images([dict(calls=[call,call])],root,'ocr-owned')
    def test_ci_permissions_and_limits_unchanged(self):
        code=(ROOT/'.github/workflows/legacy-helper-candidate.yml').read_text()
        self.assertIn('contents: read',code);self.assertNotIn('contents: write',code)
        self.assertIn('timeout-minutes: 40',code);self.assertIn("'tests/fixtures/legacy-observation-owned-window/**'",code)
    def test_fixture_helper_mode_is_explicit(self):
        code=(ROOT/'tests/fixtures/legacy-observation-owned-window/Program.cs').read_text()
        self.assertIn('args[2]!="helper-provider"',code);self.assertIn('if(helper)',code)

if __name__=='__main__':unittest.main()
