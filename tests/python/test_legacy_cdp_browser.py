"""Opt-in legacy rendered DOM tests, only in an owned sandboxed fresh Chrome profile."""
import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'pcucp-next/python'))
from pcucp_cli.legacy_cdp import LegacyCdpAdapter, _expression
from pcucp_cli.cdp import CdpAdapter
import test_cdp_browser as fixtures
from test_legacy_cdp_assets import css_identifier_source, css_identifier_cases


@unittest.skipUnless(os.environ.get('CUCP_LEGACY_CDP_BROWSER_TEST')=='1',
    'Set CUCP_LEGACY_CDP_BROWSER_TEST=1 for owned sandboxed legacy Chrome fixtures')
class LegacyCdpBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.CdpBrowserTests.setUpClass.__func__(cls)

    setUp = fixtures.CdpBrowserTests.setUp

    def adapter(self,live=False):
        adapter=LegacyCdpAdapter(self.endpoint,allow_live_control=live)
        self.resources.callback(adapter.close)
        return adapter

    def evaluate(self,expression):
        result=self.adapter(True).execute('cdp-eval',{'expression':expression,'page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        return result.payload['result_value']

    def test_guarded_primitive_diagnostics(self):
        # Fixed source against this owned fixture only. Every probe remains
        # guarded and bounded; failures never trigger unrestricted evaluation.
        self.evaluate("""(()=>{const host=document.createElement('div');host.id='probe-host';document.body.append(host);
          host.attachShadow({mode:'open'}).innerHTML='<button>Probe</button>';
          const frame=document.createElement('iframe');frame.id='probe-frame';document.body.append(frame);return true})()""")
        primitives={
            'get_element_by_id':"!!document.getElementById('save')",
            'literal_object':'({ok:true})',
            'nfkc':"'Ｓａｖｅ'.normalize('NFKC').toLowerCase()",
            'unicode_regex':"'Save!'.replace(/[^\\p{L}\\p{N}\\s]+/gu,' ')",
            'local_array':'(()=>{const a=[];a.push(2,1);a.sort((x,y)=>x-y);return a.map(x=>x+1)})()',
            'local_set':'(()=>{const a=new Set();a.add(1);return a.has(1)})()',
            'query_all':"document.querySelectorAll('button').length",
            'query_array_from':"Array.from(document.querySelectorAll('button')).length",
            'connected':"document.querySelector('#save').isConnected",
            'rect':"document.querySelector('#save').getBoundingClientRect().width",
            'style_object':"!!window.getComputedStyle(document.querySelector('#save'))",
            'style_display':"window.getComputedStyle(document.querySelector('#save')).display",
            'style_visibility':"window.getComputedStyle(document.querySelector('#save')).visibility",
            'style_opacity':"window.getComputedStyle(document.querySelector('#save')).opacity",
            'tag':"document.querySelector('#save').tagName",
            'attribute':"document.querySelector('#save').getAttribute('aria-label')",
            'inner_text':"document.querySelector('#save').innerText",
            'text_content':"document.querySelector('#save').textContent",
            'parent_element':"document.querySelector('#save').parentElement.tagName",
            'child_nodes':"document.querySelector('#save').childNodes.length",
            'text_node_type':"document.querySelector('#save').childNodes[0].nodeType",
            'text_node_value':"document.querySelector('#save').childNodes[0].nodeValue",
            'source_descendant_query':"!!document.body.querySelector('script,style,noscript,template')",
            'labels':"document.querySelector('#message').labels.length",
            'label_array_from':"Array.from(document.querySelector('#message').labels).length",
            'control':"document.querySelector('label').control.id",
            'disabled':"document.querySelector('#save').disabled",
            'onclick':"document.querySelector('#save').onclick===null",
            'content_editable':"document.querySelector('#prosemirror').isContentEditable",
            'value':"document.querySelector('#message').value",
            'placeholder':"document.querySelector('#message').placeholder",
            'title':"document.querySelector('#message').title",
            'shadow_root':"document.querySelector('#save').shadowRoot===null",
            'shadow_query':"document.querySelector('#probe-host').shadowRoot.querySelectorAll('*').length",
            'content_document':"document.querySelector('#probe-frame').contentDocument.querySelectorAll('*').length",
            'css_escape':"CSS.escape('save')",
            'json_stringify':"JSON.stringify('Save')",
            'complete_smart_click':_expression('smart_read',dict(action='click',needle='Save')),
            'complete_smart_type':_expression('smart_read',dict(action='type',needle='Write a note')),
            'complete_deep':_expression('deep_read',dict(needle='Save')),
        }
        adapter=self.adapter()
        page=dict(id=self.target_id,type='page',ws_url=self.endpoint.replace('http:','ws:')+'/devtools/page/'+self.target_id)
        report={}
        for name,expression in primitives.items():
            response=adapter._transport.call(page,'Runtime.evaluate',dict(expression=expression,returnByValue=True,
                throwOnSideEffect=True,awaitPromise=False,timeout=250),time.monotonic()+1,audited_read=True)
            error=response.get('error') or response.get('result',{}).get('exceptionDetails')
            report[name]='ok' if error is None else json.dumps(error,ensure_ascii=True)[:260]
        print('LEGACY_CDP_GUARDED_PRIMITIVES '+json.dumps(report,sort_keys=True),flush=True)

    def install_privacy_fixture(self):
        # Everything here is created within this test's owned fresh profile.
        self.evaluate("""(()=>{
          const panel=document.createElement('section');panel.id='privacy-panel';
          const password=document.createElement('input');password.type='password';password.id='privacy-password';
          password.setAttribute('value','CANARY-PASSWORD-ATTRIBUTE');password.value='CANARY-PASSWORD-CURRENT';panel.append(password);
          const hidden=document.createElement('input');hidden.type='hidden';hidden.value='CANARY-HIDDEN-CURRENT';panel.append(hidden);
          const field=document.createElement('input');field.id='privacy-public-field';field.value='CANARY-PUBLIC-FIELD-CURRENT';
          field.setAttribute('value','CANARY-PUBLIC-FIELD-ATTRIBUTE');
          const label=document.createElement('label');label.htmlFor=field.id;label.textContent='Public label';panel.append(label,field);
          const caption=document.createElement('input');caption.type='button';caption.value='Public caption';panel.append(caption);
          const publicButton=document.createElement('button');publicButton.textContent='Public Save';panel.append(publicButton);
          for(const tag of ['script','style','noscript','template']){
            const container=document.createElement('button');container.style.width='120px';container.style.height='25px';
            const source=document.createElement(tag);if(tag==='script')source.type='application/json';
            const text='CANARY-'+tag.toUpperCase()+'-SOURCE';source.textContent=tag==='style'?'/* '+text+' */':text;
            container.append(source);panel.append(container);
            if(tag==='template'){
              const inert=document.createElement('button');inert.textContent='CANARY-TEMPLATE-CONTENT';source.content.append(inert);
              source.appendChild(document.createTextNode('CANARY-TEMPLATE-ORDINARY-CHILD'));
            }
          }
          const visibleSource=document.createElement('script');visibleSource.type='application/json';
          visibleSource.style.display='inline';visibleSource.textContent='CANARY-RENDERED-SCRIPT';publicButton.append(visibleSource);
          const host=document.createElement('div');panel.append(host);const shadow=host.attachShadow({mode:'open'});
          const shadowSecret=document.createElement('input');shadowSecret.type='password';shadowSecret.value='CANARY-SHADOW-PASSWORD';shadow.append(shadowSecret);
          document.body.append(panel);return true;
        })()""")

    def test_private_values_and_source_subtrees_absent_from_guarded_reads(self):
        self.install_privacy_fixture()
        adapter=self.adapter()
        for action in ('cdp-smart-find','cdp-smart-type-find','cdp-deep-find'):
            with self.subTest(action=action):
                result=adapter.execute(action,{'needle':'canary','page_match':self.fixture_url})
                self.assertEqual(result.payload['status'],'ok' if action=='cdp-deep-find' else 'partial',result.payload)
                self.assertNotIn('CANARY-',json.dumps(result.payload))
                if action=='cdp-deep-find':self.assertEqual(result.payload['found_count'],0)
                else:
                    self.assertEqual(result.payload['reason'],'no_text_match')
                    self.assertEqual(result.payload['candidate_count'],0)
        for action,needle in (('cdp-smart-find','Public caption'),('cdp-smart-find','Public Save'),
                              ('cdp-smart-type-find','Public label')):
            with self.subTest(action=action,needle=needle):
                result=adapter.execute(action,{'needle':needle,'page_match':self.fixture_url})
                self.assertEqual(result.payload['status'],'ok',result.payload)
                self.assertEqual(result.payload['matched_text'],needle)
                self.assertNotIn('CANARY-',json.dumps(result.payload))

    def test_private_values_absent_from_live_briefs_and_trajectories(self):
        from pcucp_cli.legacy_cdp_contract import prepare_macro
        from pcucp_cli.legacy_cdp_macro import macro_output
        self.install_privacy_fixture()
        adapter=self.adapter(True)
        for action in ('cdp-smart-click','cdp-smart-type'):
            for needle in ('canary','Public Save' if action=='cdp-smart-click' else 'Public label'):
                with self.subTest(action=action,needle=needle):
                    args={'needle':needle,'page_match':self.fixture_url}
                    argv=['--text' if action=='cdp-smart-click' else '--label',needle]
                    if action=='cdp-smart-type':args.update(text='owned',clear=True);argv+=['--text','owned','--clear-first']
                    result=adapter.execute(action,args)
                    self.assertEqual(result.payload['status'],'partial' if needle=='canary' else 'ok',result.payload)
                    output=macro_output(prepare_macro(action,argv,allow_live_control=True),result)
                    self.assertNotIn('CANARY-',json.dumps(dict(payload=output.payload,brief=output.brief_line,trajectory=output.trajectory)))

    def test_guarded_filter_never_reads_private_value_or_aggregate_getters(self):
        self.install_privacy_fixture()
        self.evaluate("""(()=>{window.privacyGetterReads=0;
          for(const [element,property] of [[document.querySelector('#privacy-password'),'value'],
               [document.querySelector('#privacy-panel'),'textContent'],[document.querySelector('#privacy-panel'),'innerText']]){
            Object.defineProperty(element,property,{get(){window.privacyGetterReads++;return 'CANARY-GETTER';}});
          }return true})()""")
        for action in ('cdp-smart-find','cdp-smart-type-find','cdp-deep-find'):
            result=self.adapter().execute(action,{'needle':'canary','page_match':self.fixture_url})
            self.assertEqual(result.payload['status'],'ok' if action=='cdp-deep-find' else 'partial',result.payload)
            if action!='cdp-deep-find':self.assertEqual(result.payload['reason'],'no_text_match')
            self.assertNotIn('CANARY-',json.dumps(result.payload))
        self.assertEqual(self.evaluate('window.privacyGetterReads'),0)

    def test_textarea_values_are_private_while_labels_and_typing_work(self):
        from pcucp_cli.legacy_cdp_contract import prepare_macro
        from pcucp_cli.legacy_cdp_macro import macro_output
        self.evaluate("""(()=>{
          const panel=document.createElement('section');panel.id='textarea-panel';
          const label=document.createElement('label');label.htmlFor='privacy-notes';label.textContent='Public note label';
          const area=document.createElement('textarea');area.id='privacy-notes';
          area.textContent='CANARY-TEXTAREA-DEFAULT';area.value='CANARY-TEXTAREA-CURRENT';panel.append(label,area);
          const wrapped=document.createElement('label');wrapped.append('Wrapped note label');
          const nested=document.createElement('textarea');nested.id='wrapped-notes';nested.textContent='CANARY-WRAPPED-DEFAULT';
          nested.value='CANARY-WRAPPED-CURRENT';wrapped.append(nested);panel.append(wrapped);
          const ancestor=document.createElement('div');ancestor.setAttribute('role','button');
          ancestor.style.width='120px';ancestor.style.height='25px';
          const hidden=document.createElement('textarea');hidden.style.display='none';
          hidden.textContent='CANARY-HIDDEN-TEXTAREA-DEFAULT';hidden.value='CANARY-HIDDEN-TEXTAREA-CURRENT';
          ancestor.append(hidden);panel.append(ancestor);document.body.append(panel);return true;
        })()""")
        reader=self.adapter()
        for action in ('cdp-smart-find','cdp-smart-type-find','cdp-deep-find'):
            result=reader.execute(action,{'needle':'canary','page_match':self.fixture_url})
            self.assertEqual(result.payload['status'],'ok' if action=='cdp-deep-find' else 'partial',result.payload)
            self.assertEqual(result.payload.get('found_count',result.payload.get('candidate_count')),0)
            self.assertNotIn('CANARY-',json.dumps(result.payload))
        for label,selector in (('Public note label','#privacy-notes'),('Wrapped note label','#wrapped-notes')):
            result=reader.execute('cdp-smart-type-find',{'needle':label,'page_match':self.fixture_url})
            self.assertEqual(result.payload['status'],'ok',result.payload)
            self.assertEqual(result.payload['tag_name'],'TEXTAREA')
            self.assertEqual(result.payload['matched_text'],label)
            self.assertEqual(result.payload['selector_candidates'][0]['selector'],selector)
            self.assertNotIn('CANARY-',json.dumps(result.payload))
        result=self.adapter(True).execute('cdp-smart-type',{'needle':'Public note label','text':'owned replacement',
                                                          'clear':True,'page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        output=macro_output(prepare_macro('cdp-smart-type',['--label','Public note label','--text','owned replacement',
                                                         '--clear-first'],allow_live_control=True),result)
        self.assertNotIn('CANARY-',json.dumps(dict(payload=output.payload,brief=output.brief_line,trajectory=output.trajectory)))
        self.assertTrue(self.evaluate("document.querySelector('#privacy-notes').value==='owned replacement' && document.querySelector('#privacy-notes').defaultValue==='CANARY-TEXTAREA-DEFAULT'"))
        # The remaining default remains private after current-value replacement;
        # guarded reads must avoid every alias, including ancestor aggregates.
        self.evaluate("""(()=>{window.textareaGetterReads=0;
          for(const property of ['value','defaultValue','innerText','textContent'])
            Object.defineProperty(document.querySelector('#privacy-notes'),property,{get(){window.textareaGetterReads++;return 'CANARY-ALIAS';}});
          for(const property of ['innerText','textContent'])
            Object.defineProperty(document.querySelector('#textarea-panel'),property,{get(){window.textareaGetterReads++;return 'CANARY-ANCESTOR';}});
          return true})()""")
        for action in ('cdp-smart-find','cdp-smart-type-find','cdp-deep-find'):
            result=reader.execute(action,{'needle':'canary','page_match':self.fixture_url})
            self.assertEqual(result.payload['status'],'ok' if action=='cdp-deep-find' else 'partial',result.payload)
            self.assertNotIn('CANARY-',json.dumps(result.payload))
        self.assertEqual(self.evaluate('window.textareaGetterReads'),0)

    def test_css_identifier_matches_native_fixture_oracle(self):
        values=[value for value,_ in css_identifier_cases()]
        # Explicit live authority belongs only to this owned fixture oracle.
        # Production smart-read never invokes native CSS.escape or removes its
        # mandatory side-effect guard after rejection.
        expression='('+css_identifier_source()+')'
        result=self.evaluate('('+json.dumps(values,ensure_ascii=True)+').map(value=>({actual:'+expression+
            '(value),expected:CSS.escape(value)}))')
        self.assertEqual(len(result),len(values))
        for value,row in zip(values,result):
            with self.subTest(value=repr(value)):
                self.assertEqual(row['actual'],row['expected'])

    def test_rendered_smart_find_and_label_match_with_guard(self):
        adapter=self.adapter()
        result=adapter.execute('cdp-smart-find',{'needle':'Save','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        self.assertEqual(result.payload['score'],147)
        self.assertEqual(result.payload['match_score'],100)
        self.assertEqual(result.payload['candidate_count'],2)
        self.assertEqual(result.payload['selector_candidates'][0]['selector'],'#save')
        self.assertEqual(result.payload['tag_name'],'BUTTON')
        self.assertTrue(result.payload['plan_only'])
        self.assertGreater(result.payload['rect']['width'],0)
        result=adapter.execute('cdp-smart-type-find',{'needle':'Write a note','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        self.assertEqual(result.payload['tag_name'],'INPUT')
        self.assertEqual(result.payload['score'],152)
        self.assertEqual(result.payload['selector_candidates'][0]['selector'],'#message')
        self.assertEqual(self.evaluate("document.getElementById('click-count').textContent"),'0')

    def test_shadow_and_same_origin_iframe_deep_read(self):
        self.evaluate("""(()=>{const host=document.createElement('div');host.id='host';document.body.append(host);
          const root=host.attachShadow({mode:'open'});const button=document.createElement('button');button.textContent='Shadow Save';button.id='shadow-save';root.append(button);
          const frame=document.createElement('iframe');document.body.append(frame);
          const button2=frame.contentDocument.createElement('button');button2.textContent='Frame Save';frame.contentDocument.body.append(button2);return true})()""")
        result=self.adapter().execute('cdp-smart-find',{'needle':'Shadow Save','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        self.assertEqual(result.payload['selector_candidates'][0]['selector'],'#shadow-save')
        deep=self.adapter().execute('cdp-deep-find',{'needle':'Frame Save','page_match':self.fixture_url})
        self.assertEqual(deep.payload['status'],'ok',deep.payload)
        self.assertEqual(deep.payload['traversal']['shadow_roots_seen'],1)
        self.assertEqual(deep.payload['traversal']['iframes_seen'],1)
        self.assertEqual(deep.payload['traversal']['iframes_blocked'],0)
        self.assertTrue(any(m['matched_text']=='Frame Save' for m in deep.payload['top_matches']))

    def test_read_getter_and_proxy_cannot_mutate_or_escalate(self):
        self.evaluate("""(()=>{window.fixtureGetterCount=0;Object.defineProperty(document.getElementById('message'),'labels',{
            get(){window.fixtureGetterCount++;return []}});return true})()""")
        result=self.adapter(True).execute('cdp-smart-type-find',{'needle':'Message','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'partial',result.payload)
        self.assertEqual(result.payload['reason'],'javascript_exception')
        self.assertFalse(result.payload['automatic_fallback'])
        self.assertEqual(self.evaluate('window.fixtureGetterCount'),0)
        self.evaluate("""(()=>{window.fixtureProxyCount=0;window.getComputedStyle=new Proxy(window.getComputedStyle,{
          apply(target,receiver,args){window.fixtureProxyCount++;return Reflect.apply(target,receiver,args)}});return true})()""")
        result=self.adapter(True).execute('cdp-smart-find',{'needle':'Save','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'partial',result.payload)
        self.assertEqual(self.evaluate('window.fixtureProxyCount'),0)

    def test_live_click_and_unicode_type_preserve_legacy_events(self):
        adapter=self.adapter(True)
        result=adapter.execute('cdp-click',{'selector':'#save','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        self.assertEqual(self.evaluate("document.getElementById('click-count').textContent"),'1')
        text='안녕😀 "quote" \\ newline\n'
        result=adapter.execute('cdp-smart-type',{'needle':'Message','text':text,'clear':True,'page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        self.assertEqual(self.evaluate("document.getElementById('message').value"),text.replace('\n',''))
        self.assertEqual(self.evaluate("document.getElementById('input-count').textContent"),'1')
        self.assertEqual(self.evaluate("document.getElementById('change-count').textContent"),'1')

    def test_prosemirror_trusted_input_and_wrong_element_block(self):
        adapter=self.adapter(True)
        result=adapter.execute('cdp-prosemirror-insert',{'selector':'#prosemirror','text':'안녕😀','page_match':self.fixture_url})
        self.assertEqual(result.payload['status'],'ok',result.payload)
        self.assertTrue(result.payload['changed'])
        self.assertIn('안녕😀',self.evaluate("document.getElementById('prosemirror').textContent"))
        self.assertEqual(self.evaluate("document.getElementById('prosemirror-trusted').textContent"),'true')
        result=adapter.execute('cdp-prosemirror-insert',{'selector':'#message','text':'wrong','page_match':self.fixture_url})
        self.assertEqual(result.payload['reason'],'editor_focus_not_verified')
        self.assertEqual(self.evaluate("document.getElementById('message').value"),'')


if __name__=='__main__': unittest.main()
