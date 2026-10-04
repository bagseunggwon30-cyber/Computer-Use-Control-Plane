"""Legacy CDP family: captured protocol replies, immutable authority, wrapper contracts."""
import base64
import copy
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next/python'))
from pcucp_cli.legacy_cdp import LegacyCdpAdapter, _expression
from pcucp_cli.legacy_cdp_contract import (ACTIONS, LIVE_ACTIONS, LegacyCdpResult, dom_bridge_plan,
    find_page, prepare_macro, score_pages, utf16_length)
from pcucp_cli.legacy_cdp_macro import macro_output, port_closed_output, execute_macro, LegacyCdpPortCache
from pcucp_cli.cdp import CdpError
from test_cdp import server


def smart_value():
    return dict(ok=True, action='click', query='Save', matched_text='Save', score=147, match_score=100,
        tag_name='BUTTON', role='', rect=dict(x=10,y=20,width=80,height=25), candidate_count=2,
        text_length=0, sent_enter=False, plan_only=True,
        selector_candidates=[dict(kind='css_id',selector='#save',score=98,reason='stable_id')],
        locator_candidates=[dict(kind='playwright_role',locator="page.getByRole('button', { name: \"Save\" })",score=100,reason='button_name')],
        candidate_summaries=[dict(score=147, match_score=100,matched_text='Save',tag_name='BUTTON',role='',rect=dict(x=10,y=20,width=80,height=25),selector_candidates=[],locator_candidates=[])])


def response_for(value):
    return {'result': {'result': {'type': 'object' if isinstance(value, (dict,list)) else 'string', 'value': value}}}


def capture(state, responses):
    responses = iter(responses)
    def respond(request):
        state.requests.append(request)
        return next(responses)
    state.respond = respond


class PureContractTests(unittest.TestCase):
    def test_ranking_and_selection_are_legacy_not_modern_first_target(self):
        pages = [dict(id='worker',title='Save',url='https://site.test',type='worker'),
                 dict(id='b',title='B',url='app:home',type='page'),
                 dict(id='a',title='A',url='file:a',type='page'),
                 dict(id='dev',title='DevTools',url='devtools://tools',type='page')]
        detected = dict(available=True,pages=pages)
        self.assertEqual([(p['id'],p['score']) for p in score_pages(detected)], [('a',65),('b',65),('dev',-23),('worker',-40)])
        selected, evidence = find_page(detected,'Save')
        self.assertEqual(selected['id'],'worker')
        self.assertEqual(evidence['selected']['reasons'], ['exact_page_match','type_worker','has_title','document_url'])
        selected, evidence = find_page(detected,'missing')
        self.assertIsNone(selected)
        self.assertIsNone(evidence['selected'])
        self.assertEqual(evidence['candidates'][0]['id'],'a')
        with self.assertRaises(ValueError): score_pages(dict(pages={'value':pages,'Count':4}))

    def test_framework_equal_title_swaps_and_first_eight(self):
        detected = dict(available=True,pages=[dict(id=str(i),title='Same',url='https://x',type='page') for i in range(12)])
        selected, evidence = find_page(detected)
        self.assertEqual(selected['id'],'8')
        self.assertEqual([p['id'] for p in evidence['candidates']],list(map(str,[8,7,6,11,10,9,2,1])))
        # This is intentionally distinct from stable DOM candidate ranking.
        pages=[dict(id=str(i),title='same',url='https://x',type='page') for i in range(2)]
        self.assertEqual([p['id'] for p in score_pages(dict(pages=pages))],['1','0'])

    def test_dom_bridge_helper_and_wrapper_difference(self):
        helper = dom_bridge_plan('type', '이름', 1234, "O'Brien", 'a\n😀', True, True)
        wrapper = dom_bridge_plan('type', '이름', 1234, "O'Brien", 'a\n😀', True, True, helper=False)
        self.assertEqual(helper['live_command'], ['macro','cdp-smart-type','--label','이름','--text','a\n😀','--clear-first','--press-enter','--port','1234','--page-match',"O'Brien"])
        self.assertEqual(helper['read_only_command'],['macro','cdp-smart-type-find','--label','이름','--port','1234','--page-match',"O'Brien"])
        helper.pop('locator_hints')
        self.assertEqual(helper,wrapper)

    def test_macro_option_precedence_case_and_port_fallbacks(self):
        result = prepare_macro('cdp-smart-type',['--LABEL','First','--label','Second','--text','😀','--CLEAR-FIRST','--PORT','-1'],allow_live_control=True)
        self.assertEqual(result.port,9222)
        self.assertEqual(result.args,dict(page_match='',needle='First',text='😀',clear=True,enter=False))
        self.assertEqual(prepare_macro('cdp-deep-find',['--text','x','--port','bad']).port,9222)
        self.assertEqual(prepare_macro('cdp-prosemirror-insert',['--selector','#x','--text','a','--port','0'],allow_live_control=True).port,0)
        with self.assertRaises(ValueError): prepare_macro('cdp-detect',['--port','bad'])
        with self.assertRaises(PermissionError): prepare_macro('cdp-eval',['--expr','1'])

    def test_exact_brief_quirks_and_trajectory(self):
        macro = prepare_macro('cdp-type',['--selector','#x','--text','😀'],allow_live_control=True)
        result = LegacyCdpResult(dict(status='ok',tag_name='INPUT',is_content_editable=False,is_input=True,
            current_value_length=2,sent_enter=False,page_title='Page',page_id='p'),0)
        output = macro_output(macro,result)
        self.assertEqual(output.brief_line,"ok cdp-type selector='#x' tag=INPUT ce=False input=True value_len=2 sent_enter=False page='Page'")
        self.assertEqual(output.trajectory['kind'],'click')
        self.assertEqual(output.trajectory['payload']['text_length'],2)
        self.assertEqual(port_closed_output(macro).trajectory['kind'],'type')
        macro = prepare_macro('cdp-deep-find',['--text','x'])
        output = macro_output(macro,LegacyCdpResult(dict(status='error',reason='no_result'),1))
        self.assertEqual(output.brief_line,"ok cdp-deep-find text='x' found=0 shadow_roots=0 iframes=0")
        self.assertEqual(output.exit_code,2)
        self.assertEqual(output.json_depth,10)
        with self.assertRaises(ValueError): output.render()


class LegacyTransportTests(unittest.TestCase):
    def test_endpoint_and_live_authority_are_immutable(self):
        with patch('socket.socket',side_effect=AssertionError('constructor must not connect')):
            for endpoint in ('http://localhost:9222','http://127.1:9222','http://[::ffff:127.0.0.1]:9222','http://127.0.0.1:2/x','https://127.0.0.1:2'):
                with self.subTest(endpoint=endpoint), self.assertRaises(CdpError): LegacyCdpAdapter(endpoint)
            adapter = LegacyCdpAdapter('http://[::1]:22')
            with self.assertRaises(AttributeError): adapter.allow_live_control=True
            for action in LIVE_ACTIONS:
                self.assertEqual(adapter.execute(action).payload['reason'],'live_control_required')
            with self.assertRaises(ValueError): adapter.execute('cdp-detect',{'allow_live_control':True})

    def test_detect_exact_envelope_and_no_websocket(self):
        with server() as (state,endpoint):
            result=LegacyCdpAdapter(endpoint).execute('cdp-detect')
            expected=dict(status='ok',port=state.port,page_count=1,pages=[dict(id='page-0',title='Fixture',url='https://example.test/',type='page',ws_url=f'ws://127.0.0.1:{state.port}/devtools/page/page-0')],browser='Mock/1',protocol_version='1.3',user_agent='',action='cdp-detect')
            payload=copy.deepcopy(result.payload);self.assertIsInstance(payload.pop('elapsed_ms'),int)
            self.assertEqual(payload,expected)
            self.assertEqual(result.exit_code,0)
            self.assertEqual(state.paths,['/json/version','/json/list'])
            self.assertEqual(state.requests,[])

    def test_redirect_and_websocket_escape_never_follow(self):
        with server() as (state,endpoint):
            state.http_mode='redirect'
            result=LegacyCdpAdapter(endpoint).execute('cdp-detect')
            self.assertEqual(result.payload['reason'],'cdp_port_closed')
            self.assertEqual(state.paths,['/json/version'])
            state.http_mode='';state.paths.clear()
            state.external_ws='ws://127.0.0.1:1/devtools/page/page-0'
            result=LegacyCdpAdapter(endpoint).execute('cdp-smart-find',{'needle':'Save'})
            self.assertEqual(result.payload['reason'],'endpoint_escape')
            self.assertEqual(state.requests,[])

    def test_fragmented_correlated_read_preserves_masking_and_ping(self):
        with server() as (state,endpoint):
            state.ws_mode='fragmented'
            capture(state,[response_for(smart_value())])
            result=LegacyCdpAdapter(endpoint).execute('cdp-smart-find',{'needle':'Save'})
            self.assertEqual(result.payload['status'],'ok')
            self.assertTrue(state.pong.wait(1))
            self.assertTrue(all(masked for _op,masked,_length in state.client_frames))

    def test_read_smart_exact_captured_reply_and_side_effect_flags(self):
        with server() as (state,endpoint):
            value=smart_value();capture(state,[response_for(value)])
            result=LegacyCdpAdapter(endpoint).execute('cdp-smart-find',{'needle':'Save'})
            self.assertEqual(result.exit_code,0)
            for key in ('matched_text','score','match_score','tag_name','role','rect','candidate_count','selector_candidates','locator_candidates','candidate_summaries'):
                self.assertEqual(result.payload[key],value[key])
            self.assertTrue(result.payload['plan_only'])
            self.assertEqual(len(state.requests),1)
            request=state.requests[0]
            self.assertTrue(request['params']['throwOnSideEffect'])
            self.assertFalse(request['params']['awaitPromise'])
            self.assertIn('const planOnly = true;',request['params']['expression'])
            self.assertNotIn('if (!planOnly)',request['params']['expression'])
            self.assertNotIn('el.click()',request['params']['expression'])

    def test_getter_and_protocol_guard_failure_never_escalate(self):
        replies=[{'result':{'exceptionDetails':{'text':'Uncaught','exception':{'description':'EvalError: Possible side-effect in debug-evaluate'}}}},
                 {'error':{'code':-32602,'message':'throwOnSideEffect unsupported'}}]
        for reply in replies:
            with self.subTest(reply=reply),server() as (state,endpoint):
                capture(state,[reply])
                result=LegacyCdpAdapter(endpoint,allow_live_control=True).execute('cdp-smart-type-find',{'needle':'Name'})
                self.assertEqual(result.exit_code,2)
                self.assertFalse(result.payload['automatic_fallback'])
                self.assertNotIn('mutation_may_have_occurred',result.payload)
                self.assertEqual(len(state.requests),1)
                self.assertTrue(state.requests[0]['params']['throwOnSideEffect'])

    def test_eval_b64_protocol_errors_and_exceptions(self):
        with server() as (state,endpoint):
            adapter=LegacyCdpAdapter(endpoint,allow_live_control=True)
            capture(state,[response_for('😀'),{'error':{'code':-1,'message':'bad'}},
                {'result':{'exceptionDetails':{'text':'Oops','exception':{'description':'detail'}}}}])
            expression='"😀"'
            result=adapter.execute('cdp-eval',{'expression_b64':base64.b64encode(expression.encode()).decode()})
            self.assertEqual(result.payload['expression'],expression)
            self.assertEqual(result.payload['result_value'],'😀')
            self.assertTrue(state.requests[0]['params']['awaitPromise'])
            result=adapter.execute('cdp-eval',{'expression':'1'})
            self.assertEqual((result.payload['reason'],result.exit_code),('cdp_evaluate_error',1))
            result=adapter.execute('cdp-eval',{'expression':'throw 1'})
            self.assertEqual((result.payload['reason'],result.exit_code),('javascript_exception',2))

    def test_quote_safe_type_preserves_cr_removal_and_utf16_length(self):
        with server() as (state,endpoint):
            capture(state,[response_for(dict(ok=True,tag_name='INPUT',is_input=True,is_content_editable=False,current_value_length=7,sent_enter=True))])
            text='\r😀"\\\n';selector='[id="x\\y"]'
            result=LegacyCdpAdapter(endpoint,allow_live_control=True).execute('cdp-type',dict(selector=selector,text=text,clear=True,enter=True))
            self.assertEqual(result.payload['text_length'],utf16_length(text))
            expression=state.requests[0]['params']['expression']
            wire_args=json.loads(expression.rsplit(')(',1)[1][:-1])
            self.assertEqual(wire_args,dict(selector=selector,text=text.replace('\r',''),clear=True,enter=True))
            self.assertNotIn('throwOnSideEffect',state.requests[0]['params'])

    def test_deep_correct_envelope_and_actual_arrays(self):
        value=dict(traversal=dict(hops=4,shadow_roots_seen=1,iframes_seen=2,iframes_blocked=1,total_nodes=19),found_count=1,top_matches=[dict(tag='button',score=100,matched_text='Save',rect=None)])
        with server() as (state,endpoint):
            capture(state,[response_for(value)])
            result=LegacyCdpAdapter(endpoint).execute('cdp-deep-find',{'needle':'Save'})
            self.assertEqual(result.exit_code,0)
            self.assertEqual(result.payload['top_matches'],value['top_matches'])
            self.assertEqual(result.payload['traversal'],value['traversal'])
            self.assertTrue(state.requests[0]['params']['throwOnSideEffect'])
        obj={'value':[1,2],'Count':2}
        with server() as (state,endpoint):
            capture(state,[response_for({**value,'top_matches':obj})])
            result=LegacyCdpAdapter(endpoint).execute('cdp-deep-find',{'needle':'Save'})
            self.assertEqual(result.payload['top_matches'],[obj])

    def test_success_arrays_and_failure_pipeline_collection_remain_distinct(self):
        for source, success, failure in ((None,[None],None),([],[],None),([{'score':1}],[{'score':1}],{'score':1}),
                                         ([{'score':1},{'score':2}],[{'score':1},{'score':2}],[{'score':1},{'score':2}]),
                                         ({'value':[1],'Count':1},[{'value':[1],'Count':1}],{'value':[1],'Count':1})):
            with self.subTest(source=source),server() as (state,endpoint):
                adapter=LegacyCdpAdapter(endpoint)
                value=smart_value();value['candidate_summaries']=source
                capture(state,[response_for(value),response_for(dict(ok=False,reason='no_text_match',candidate_summaries=source))])
                self.assertEqual(adapter.execute('cdp-smart-find',{'needle':'Save'}).payload['candidate_summaries'],success)
                self.assertEqual(adapter.execute('cdp-smart-find',{'needle':'Save'}).payload['candidate_summaries'],failure)

    def test_lost_live_reply_is_uncertain_and_never_retried(self):
        with server() as (state,endpoint):
            state.drop_method='Runtime.evaluate'
            result=LegacyCdpAdapter(endpoint,allow_live_control=True).execute('cdp-click',{'selector':'#save'})
            self.assertTrue(result.payload['mutation_may_have_occurred'])
            self.assertEqual(len(state.requests),1)

    def test_prosemirror_focus_and_verification(self):
        with server() as (state,endpoint):
            capture(state,[{'result':{}},{'result':{}},{'error':{'code':-32601,'message':'Input.enable unsupported'}},
                response_for(dict(ok=True,value='seed')),{'result':{}},response_for('seed안녕😀')])
            result=LegacyCdpAdapter(endpoint,allow_live_control=True).execute('cdp-prosemirror-insert',{'selector':'.ProseMirror','text':'안녕😀'})
            self.assertEqual(result.exit_code,0)
            self.assertTrue(result.payload['changed'])
            self.assertEqual(result.payload['after_length'],8)
            self.assertEqual([r['method'] for r in state.requests],['DOM.enable','Runtime.enable','Input.enable','Runtime.evaluate','Input.insertText','Runtime.evaluate'])
            self.assertEqual(state.requests[4]['params'],{'text':'안녕😀'})

    def test_prosemirror_failed_focus_never_inserts(self):
        with server() as (state,endpoint):
            capture(state,[{'result':{}},{'result':{}},{'result':{}},response_for({'ok':False})])
            result=LegacyCdpAdapter(endpoint,allow_live_control=True).execute('cdp-prosemirror-insert',{'selector':'#x','text':'text'})
            self.assertEqual(result.payload['reason'],'editor_focus_not_verified')
            self.assertNotIn('Input.insertText',[r['method'] for r in state.requests])

    def test_close_cancels_blocked_read_and_prevents_later_input(self):
        with server() as (state,endpoint):
            adapter=LegacyCdpAdapter(endpoint,allow_live_control=True)
            def respond(request):
                state.requests.append(request)
                if request['method']=='Runtime.evaluate':
                    state.blocked.set();state.release.wait(2)
                    return response_for(dict(ok=True,value='seed'))
                return {'result':{}}
            state.respond=respond
            results=[]
            thread=threading.Thread(target=lambda:results.append(adapter.execute('cdp-prosemirror-insert',{'selector':'#x','text':'t'})))
            thread.start();self.assertTrue(state.blocked.wait(1));adapter.close();state.release.set();thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertNotIn('Input.insertText',[r['method'] for r in state.requests])
            self.assertTrue(results[0].payload['mutation_may_have_occurred'])


if __name__=='__main__': unittest.main()
