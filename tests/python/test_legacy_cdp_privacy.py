"""Intentional privacy divergences, separate from unchanged ordinary parity.

Only synthetic canaries, owned DOM objects and captured loopback CDP replies.
The pinned deep JS exposed data internally; its old PowerShell envelope defect
suppressed that result. The corrected public envelope must not disclose it.

Node 22.23.3's inspector rejects guarded NFKC/case conversion and Array.from,
while Node 24 and the owned Chrome gate accept the complete assets. This optional
Node harness checks fixed capabilities and both success/fail-closed outcomes;
it cannot replace the mandatory real-browser success/privacy qualification.
"""
import json
import shutil
import subprocess
import unittest

from test_legacy_cdp_assets import HARNESS, old_expression, BASELINE_TREE, ROOT
from test_legacy_cdp import capture, response_for
from test_cdp import server
from pcucp_cli.legacy_cdp import LegacyCdpAdapter, _expression
from pcucp_cli.legacy_cdp_contract import prepare_macro
from pcucp_cli.legacy_cdp_macro import macro_output

CANARY='CANARY-OWNED-NOT-A-REAL-SECRET'
ZERO=dict(x=0,y=0,width=0,height=0)


def source_container(tag, *, public=''):
    source=dict(tag=tag,innerText='',textContent=CANARY,children=[CANARY],rect=ZERO)
    return dict(tag='BUTTON',attrs={'id':'container'},innerText=public,
                textContent=public+CANARY,children=([public] if public else [])+[source])


def privacy_cases():
    password=dict(tag='INPUT',attrs={'type':'password','value':CANARY,'id':'private'},value=CANARY)
    cases=[]
    for asset,action in (('smart_read','click'),('smart_read','type'),('smart','click'),('smart','type')):
        cases.append(('password_attribute',asset,dict(action=action,needle='canary',text='owned'),[password]))
    cases.append(('weak_partial','smart_read',dict(action='click',needle='can-other'),[password]))
    cases.append(('full_result_alternate','smart_read',dict(action='click',needle='canary'),
                  [dict(tag='BUTTON',text='canary',attrs={'id':'public'}),password]))
    for action,public in (('click',dict(tag='BUTTON',text='canary',attrs={'id':'public'})),
                          ('type',dict(tag='INPUT',attrs={'aria-label':'canary','id':'public'}))):
        cases.append(('full_result_alternate','smart',dict(action=action,needle='canary',text='owned'),[public,password]))
    cases.append(('ordinary_field_value','smart_read',dict(action='type',needle='canary'),
                  [dict(tag='INPUT',attrs={'type':'text','value':CANARY},value=CANARY)]))
    cases.append(('visible_label_hidden_password','smart_read',dict(action='type',needle='canary'),
                  [dict(tag='LABEL',text='Account',control=1),
                   {**password,'style':{'display':'none'},'rect':ZERO}]))
    for kind in ('password','hidden','text'):
        cases.append(('current_'+kind,'deep_read',dict(needle='canary'),
                      [dict(tag='INPUT',attrs={'type':kind},value=CANARY,rect=ZERO if kind=='hidden' else None)]))
    cases.append(('hidden_button_caption','deep_read',dict(needle='canary'),
                  [dict(tag='INPUT',attrs={'type':'submit','value':CANARY},value=CANARY,rect=ZERO)]))
    for asset in ('smart_read','smart'):
        cases.append(('stale_button_attribute',asset,dict(action='click',needle='canary'),
                      [dict(tag='INPUT',attrs={'type':'button','value':CANARY},value='Public caption')]))
    for tag in ('SCRIPT','STYLE','NOSCRIPT','TEMPLATE'):
        for asset in ('smart_read','smart','deep_read'):
            cases.append(('source_'+tag,asset,dict(action='click',needle='canary'),[source_container(tag)]))
        # Even visible synthetic ordinary descendants of a source-only element
        # must never become candidates via their own text or attributes.
        nested=dict(tag=tag,innerText='',textContent=CANARY,rect=ZERO,
                    children=[dict(tag='BUTTON',text=CANARY,attrs={'aria-label':CANARY})])
        cases.append(('source_descendant_'+tag,'smart_read',dict(action='click',needle='canary'),[nested]))
    return cases


@unittest.skipUnless(shutil.which('node'),'Node owned DOM fixture evaluator')
class LegacyCdpPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=subprocess.check_output(['git','show',BASELINE_TREE+':scripts/cucp-native-helper.ps1'],cwd=ROOT).decode('utf-8-sig')

    def evaluate(self,cases):
        rows=[dict(original=old_expression(self.original,asset,args),ported=_expression(asset,args),fixture=fixture)
              for _,asset,args,fixture in cases]
        process=subprocess.run(['node','-e',HARNESS],input=json.dumps(rows),text=True,encoding='utf-8',
                               capture_output=True,timeout=20)
        self.assertEqual(process.returncode,0,process.stderr)
        return json.loads(process.stdout)

    def envelope(self,asset,args,value):
        action='cdp-deep-find' if asset=='deep_read' else ('cdp-smart-type' if args['action']=='type' else 'cdp-smart-click')
        if asset=='smart_read':action='cdp-smart-type-find' if args['action']=='type' else 'cdp-smart-find'
        live=asset=='smart'
        with server() as (state,endpoint):
            capture(state,[response_for(value)])
            adapter=LegacyCdpAdapter(endpoint,allow_live_control=live)
            try:
                request=dict(needle=args['needle'])
                if action=='cdp-smart-type':request['text']=args.get('text','owned')
                result=adapter.execute(action,request)
            finally:adapter.close()
            if not live:
                self.assertIs(state.requests[0]['params']['throwOnSideEffect'],True)
                self.assertIs(state.requests[0]['params']['awaitPromise'],False)
        options=['--label' if 'type' in action else '--text',args['needle']]
        if action=='cdp-smart-type':options+=['--text',args.get('text','owned')]
        macro=prepare_macro(action,options,allow_live_control=live)
        output=macro_output(macro,result)
        return dict(payload=output.payload,brief=output.brief_line,trajectory=output.trajectory)

    def test_original_exposure_and_corrected_public_outputs(self):
        cases=privacy_cases()
        results=self.evaluate(cases)
        self.assertEqual(len(results),len(cases))
        for (name,asset,args,_),row in zip(cases,results):
            with self.subTest(case=name,asset=asset,action=args.get('action')):
                old=row['original']['result'];new=row['ported']['result']
                self.assertIn(CANARY,json.dumps(old))
                old_public=self.envelope(asset,args,old)
                new_public=self.envelope(asset,args,new)
                self.assertIn(CANARY,json.dumps(old_public['payload']))
                self.assertNotIn(CANARY,json.dumps(new_public))
                if name=='weak_partial':
                    self.assertEqual(old_public['payload']['status'],'partial')
                    self.assertEqual(new_public['payload']['status'],'partial')
                if name=='full_result_alternate':
                    self.assertEqual(old_public['payload']['status'],'ok')
                    self.assertEqual(new_public['payload']['status'],'ok')
                    self.assertEqual(new_public['payload']['matched_text'],'canary')
                if asset=='smart':
                    if name=='full_result_alternate':
                        self.assertEqual(row['ported']['events'],row['original']['events'])
                    else:
                        self.assertIn(CANARY,old_public['brief'])
                        self.assertIn(CANARY,json.dumps(old_public['trajectory']))
                        self.assertEqual(row['ported']['events'],[])

    def test_visible_button_captions_and_ordinary_labels_remain_exact(self):
        cases=[]
        for kind in ('button','submit','reset'):
            fixture=[dict(tag='INPUT',attrs={'type':kind,'value':'Public caption'},value='Public caption')]
            for asset in ('smart_read','smart','deep_read'):
                cases.append((kind,asset,dict(action='click',needle='Public caption'),fixture))
        for tag in ('SCRIPT','STYLE','NOSCRIPT','TEMPLATE'):
            cases.append((tag,'smart_read',dict(action='click',needle='Public Save'),[source_container(tag,public='Public Save')]))
        segmented=dict(tag='BUTTON',innerText='First\nSecond',textContent='FirstSecond'+CANARY,
                       children=[dict(tag='DIV',text='First',children=['First']),
                                 dict(tag='DIV',text='Second',children=['Second']),
                                 source_container('SCRIPT')['children'][0]])
        cases.append(('rendered_lines','smart_read',dict(action='click',needle='First Second'),[segmented]))
        for case,row in zip(cases,self.evaluate(cases)):
            with self.subTest(case=case[:3]):
                self.assertEqual(row['original']['result'],row['ported']['result'])
                self.assertNotIn(CANARY,json.dumps(row['ported']['result']))

    def test_shared_privacy_boundary_is_identical_in_all_three_assets(self):
        # These are actual used JS functions, kept local to the audited assets.
        pieces=[]
        for asset in ('smart_read','smart','deep_read'):
            code=_expression(asset,{})
            pieces.append(code[code.index('  function sourceOnly('):code.index('  function textParts(')])
        self.assertEqual(pieces[0],pieces[1]);self.assertEqual(pieces[0],pieces[2])

    def test_visible_caption_uses_current_property_without_exposing_stale_attribute(self):
        cases=[('current_caption',asset,dict(action='click',needle='Public caption'),
                [dict(tag='INPUT',attrs={'type':'button','value':CANARY},value='Public caption')])
               for asset in ('smart_read','smart','deep_read')]
        for case,row in zip(cases,self.evaluate(cases)):
            with self.subTest(asset=case[1]):
                new=row['ported']['result']
                self.assertNotIn(CANARY,json.dumps(new))
                if case[1]=='deep_read':self.assertEqual(new['top_matches'][0]['matched_text'],'Public caption')
                else:
                    self.assertTrue(new['ok'])
                    self.assertEqual(new['matched_text'],'Public caption')

    def test_textarea_default_current_and_ancestor_aliases_are_not_public(self):
        default='CANARY-TEXTAREA-DEFAULT-OWNED'
        current='CURRENT-TEXTAREA-VALUE-OWNED'
        area=dict(tag='TEXTAREA',attrs={'id':'private-area'},innerText=default,
                  textContent=default,value=current,children=[default])
        cases=[]
        for asset,action in (('smart_read','click'),('smart_read','type'),('smart','click'),
                             ('smart','type'),('deep_read','click')):
            cases.append(('textarea_default',asset,dict(action=action,needle='canary',text='owned'),[area]))
        ancestor=dict(tag='DIV',attrs={'role':'button'},innerText='',textContent=default,
                      children=[{**area,'style':{'display':'none'},'rect':ZERO}])
        for asset in ('smart_read','deep_read'):
            cases.append(('current_only',asset,dict(action='click',needle='current'),
                          [{**area,'innerText':'','textContent':'','children':[]}]))
            cases.append(('ancestor_fallback',asset,dict(action='click',needle='canary'),[ancestor]))
            cases.append(('ancestor_visible',asset,dict(action='click',needle='canary'),
                          [{**ancestor,'innerText':'Public visible text','textContent':'Public visible text '+default}]))
        self.assertEqual(len(cases),11)
        for (name,asset,args,_),row in zip(cases,self.evaluate(cases)):
            with self.subTest(case=name,asset=asset,action=args['action']):
                if name not in ('current_only',) and not (name=='ancestor_visible' and asset=='smart_read'):
                    self.assertIn(default,json.dumps(row['original']['result']))
                new_public=self.envelope(asset,args,row['ported']['result'])
                self.assertNotIn(default,json.dumps(new_public))
                self.assertNotIn(current,json.dumps(new_public))
                if asset=='smart':
                    old_public=self.envelope(asset,args,row['original']['result'])
                    self.assertIn(default,old_public['brief'])
                    self.assertIn(default,json.dumps(old_public['trajectory']))
                    self.assertEqual(row['ported']['events'],[])

    def test_textarea_remains_a_labeled_type_target(self):
        area=dict(tag='TEXTAREA',attrs={'id':'notes'},innerText=CANARY,textContent=CANARY,
                  value=CANARY,children=[CANARY])
        fixture=[dict(tag='LABEL',text='Public note label',control=1),area]
        cases=[('labeled_area',asset,dict(action='type',needle='Public note label',text='owned',clear=True),fixture)
               for asset in ('smart_read','smart')]
        for case,row in zip(cases,self.evaluate(cases)):
            with self.subTest(asset=case[1]):
                self.assertEqual(row['original']['result'],row['ported']['result'])
                self.assertEqual(row['original']['events'],row['ported']['events'])
                self.assertEqual(row['ported']['result']['tag_name'],'TEXTAREA')
                self.assertEqual(row['ported']['result']['matched_text'],'Public note label')
                self.assertNotIn(CANARY,json.dumps(row['ported']['result']))
                if case[1]=='smart':self.assertEqual(row['ported']['values'][1]['value'],'owned')

    def test_inert_template_content_is_not_added_to_the_read_surface(self):
        cases=[('template_content',asset,dict(action='click',needle='canary'),
                [dict(tag='TEMPLATE',innerText='',textContent='',rect=ZERO)])
               for asset in ('smart_read','deep_read')]
        for case,row in zip(cases,self.evaluate(cases)):
            with self.subTest(asset=case[1]):
                self.assertEqual(row['original']['result'],row['ported']['result'])
                self.assertNotIn(CANARY,json.dumps(row['ported']['result']))

    def test_affected_ancestor_text_budget_fails_closed_without_source_fallback(self):
        source=source_container('SCRIPT')
        source['children']=['public ']*1201+source['children']
        cases=[('bounded_ancestor',asset,dict(action='click',needle='canary'),[source])
               for asset in ('smart_read','smart','deep_read')]
        for case,row in zip(cases,self.evaluate(cases)):
            with self.subTest(asset=case[1]):
                self.assertIn(CANARY,json.dumps(row['original']['result']))
                self.assertNotIn(CANARY,json.dumps(row['ported']['result']))
                self.assertEqual(row['ported']['events'],[])

    def test_exact_read_assets_rebuild_public_text_under_v8_side_effect_guard(self):
        # Owned plain DOM objects only; Chrome's binding qualification remains a
        # separate mandatory browser gate. Node inspectors differ in support for
        # guarded intrinsics: assert success OR the explicit fail-closed contract
        # from fixed prerequisite probes, never version-pin, skip, or retry live.
        # The production JS itself is not rewritten.
        setup=r'''
globalThis.window={getComputedStyle(){return {display:'block',visibility:'visible',opacity:'1'}}};
const source={tagName:'SCRIPT',nodeType:1,childNodes:[],textContent:'CANARY-SOURCE'};
const text={nodeType:3,nodeValue:'Public Save'};
const box={tagName:'BUTTON',nodeType:1,parentElement:null,isConnected:true,disabled:false,
  childNodes:[text,source],innerText:'Public Save',textContent:'Public SaveCANARY-SOURCE',labels:[],
  getAttribute(key){return key==='id'?'public':null},
  getBoundingClientRect(){return {x:1,y:2,left:1,top:2,width:50,height:20}},
  querySelector(){return source}};
source.parentElement=box;text.parentElement=box;
globalThis.document={querySelectorAll(selector){return selector==='iframe,frame'?[]:selector==='*'?[box,source]:[box]}};
'''
        program=r'''
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const session=new(require('node:inspector').Session)();session.connect();
function post(params){
  let row;session.post('Runtime.evaluate',params,(error,response)=>{row={error:error||null,response}});
  if(!row)throw Error('Inspector response was not delivered');return row;
}
function guarded(expression){return post({expression,throwOnSideEffect:true,awaitPromise:false,returnByValue:true,timeout:1000})}
const setup=post({expression:input.setup});
if(setup.error||setup.response.exceptionDetails)throw Error(JSON.stringify(setup));
const capabilities=input.probes.map(guarded);
const snapshot="JSON.stringify({box,source,text,sourceParentIsBox:source.parentElement===box,textParentIsBox:text.parentElement===box},(key,value)=>key==='parentElement'?undefined:value)";
const before=guarded(snapshot);
const rows=input.expressions.map(guarded);
const after=guarded(snapshot);
process.stdout.write(JSON.stringify({node:process.versions.node,v8:process.versions.v8,capabilities,rows,before,after}));
session.disconnect();
'''
        probes=[('normalize',"'Ｓａｖｅ'.normalize('NFKC')",'Save'),
                ('lower',"'Public Save'.toLowerCase()",'public save'),
                ('upper',"'script'.toUpperCase()",'SCRIPT'),
                ('array_from','Array.from([])',[])]
        expressions=[_expression('smart_read',dict(action='click',needle='Public Save')),
                     _expression('deep_read',dict(needle='Public Save'))]
        p=subprocess.run(['node','-e',program],input=json.dumps(dict(setup=setup,expressions=expressions,
                                                                 probes=[expression for _,expression,_ in probes])),
                         capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        report=json.loads(p.stdout)

        def rejection(row):
            self.assertIsNone(row['error'])
            response=row['response']
            self.assertEqual(response['exceptionDetails']['exception']['className'],'EvalError')
            self.assertIn('Possible side-effect in debug-evaluate',response['exceptionDetails']['exception']['description'])
            self.assertNotIn('value',response['result'])
            self.assertNotIn('CANARY-',json.dumps(response))

        unsupported=set()
        self.assertEqual(len(report['capabilities']),len(probes))
        for (name,_,expected),row in zip(probes,report['capabilities']):
            if 'exceptionDetails' in row['response']:
                rejection(row);unsupported.add(name)
            else:
                self.assertIsNone(row['error'])
                self.assertEqual(row['response']['result']['value'],expected)
        print('LEGACY_CDP_NODE_GUARD_CAPABILITIES '+json.dumps(dict(node=report['node'],v8=report['v8'],
              rejected=sorted(unsupported))),flush=True)
        for key in ('before','after'):
            self.assertIsNone(report[key]['error'])
            self.assertNotIn('exceptionDetails',report[key]['response'])
        self.assertEqual(report['before']['response']['result']['value'],report['after']['response']['result']['value'])
        rows=report['rows'];self.assertEqual(len(rows),2)
        dependencies=[{'normalize','lower','upper','array_from'},{'lower','upper'}]
        for index,(row,required) in enumerate(zip(rows,dependencies)):
            self.assertIsNone(row['error'])
            self.assertNotIn('CANARY-',json.dumps(row['response']))
            if not required.intersection(unsupported):
                self.assertNotIn('exceptionDetails',row['response'])
                value=row['response']['result']['value']
                self.assertEqual(value['matched_text'] if index==0 else value['top_matches'][0]['matched_text'],'Public Save')
                continue
            rejection(row)
            # Replay the real inspector rejection through the actual adapter.
            # A live-enabled process must still keep this read-only and must not
            # attempt another evaluation or escalate to any input operation.
            with server() as (state,endpoint):
                capture(state,[{'result':row['response']}])
                adapter=LegacyCdpAdapter(endpoint,allow_live_control=True)
                try:result=adapter.execute('cdp-smart-find' if index==0 else 'cdp-deep-find',{'needle':'Public Save'})
                finally:adapter.close()
                self.assertEqual(result.payload['status'],'partial')
                self.assertEqual(result.payload['reason'],'javascript_exception')
                self.assertIs(result.payload['automatic_fallback'],False)
                self.assertIs(result.payload['side_effect_guard'],True)
                self.assertIs(result.payload['read_only'],True)
                self.assertFalse(result.payload.get('mutation_may_have_occurred',False))
                self.assertNotIn('CANARY-',json.dumps(result.payload))
                self.assertEqual(len(state.requests),1)
                self.assertEqual(state.requests[0]['method'],'Runtime.evaluate')
                self.assertIs(state.requests[0]['params']['throwOnSideEffect'],True)
                self.assertIs(state.requests[0]['params']['awaitPromise'],False)


if __name__=='__main__':unittest.main()
