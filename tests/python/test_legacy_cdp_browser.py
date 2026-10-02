"""Opt-in legacy rendered DOM tests, only in an owned sandboxed fresh Chrome profile."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'pcucp-next/python'))
from pcucp_cli.legacy_cdp import LegacyCdpAdapter
from pcucp_cli.cdp import CdpAdapter
import test_cdp_browser as fixtures


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
