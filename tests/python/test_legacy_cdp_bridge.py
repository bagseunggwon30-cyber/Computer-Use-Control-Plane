"""Actual Python process boundary and pure host-phase validation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
PYTHON_ROOT=ROOT/'pcucp-next/python'
sys.path.insert(0,str(PYTHON_ROOT))
from pcucp_cli.legacy_cdp_bridge import handle, MAX_FRAME, SCHEMA
from pcucp_cli.legacy_cdp_contract import prepare_macro
from pcucp_cli.legacy_cdp_macro import port_closed_output
from test_cdp import server
from test_legacy_cdp import capture,response_for,smart_value


class LegacyCdpBridgeTests(unittest.TestCase):
    def invoke(self,operation,request,*flags,raw=None):
        return subprocess.run([sys.executable,'-E','-B','-m','pcucp_cli.legacy_cdp_bridge','--operation',operation,*flags],
            cwd=PYTHON_ROOT,input=(raw if raw is not None else json.dumps(request,ensure_ascii=True)+'\n'),
            text=True,encoding='utf-8',capture_output=True,timeout=15)

    def test_prepare_complete_no_network_and_raw_passthrough(self):
        request=dict(action='cdp-click',argv=['--selector',"#x'\n$(Get-Process)",'--port','9222'])
        with patch('socket.socket',side_effect=AssertionError('pure phase must not connect')):
            prepared=handle('macro-prepare',request,allow_live_control=True)
            self.assertEqual(prepared['native_argv'],['-Action','cdp-click','-CdpSelector',"#x'\n$(Get-Process)",'-CdpPort','9222'])
            reply=dict(ExitCode=1,Json=None,Raw='verbatim helper text\r\n')
            completed=handle('macro-complete',{**request,'port_open':True,'reply':reply},allow_live_control=True)
            self.assertEqual(completed['raw'],'verbatim helper text\r\n')
            self.assertTrue(completed['raw_passthrough'])
            self.assertEqual(completed['brief_line'],"partial cdp-click selector='#x'\n$(Get-Process)' reason=helper_failed")
            self.assertEqual(completed['exit_code'],1)

    def test_closed_native_parser_consumes_authority_looking_values_as_data(self):
        for value in ('-AllowLiveControl','-CdpStartup','-CdpAllowLiveControl','-Action','--allow-live-control'):
            with self.subTest(value=value):
                result=handle('native-prepare',{'argv':['-Action','cdp-eval','-CdpExpr',value,'-CdpPageMatch',value,'-CdpPort','9222']})
                self.assertEqual(result,dict(action='cdp-eval',args=dict(expression=value,page_match=value),port=9222))
        for flag in ('-AllowLiveControl','-CdpStartup','-CdpAllowLiveControl'):
            with self.subTest(flag=flag),self.assertRaises(ValueError):
                handle('native-prepare',{'argv':['-Action','cdp-eval','-CdpExpr','1',flag,'true']})

    def test_macro_complete_revalidates_authority_not_caller_continuation(self):
        frame=dict(action='cdp-eval',argv=['--expr','1'],port_open=False,reply=None)
        with self.assertRaises(PermissionError):handle('macro-complete',frame)
        for field in ('allow_live_control','endpoint','operation'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                handle('macro-prepare',dict(action='cdp-detect',argv=[],**{field:True}))
        with self.assertRaises(ValueError):handle('macro-complete',{**frame,'port_open':'false'},allow_live_control=True)

    def test_helper_missing_json_and_raw_remain_distinct(self):
        for action,argv,code,line in (
            ('cdp-deep-find',['--text','x'],2,"ok cdp-deep-find text='x' found=0 shadow_roots=0 iframes=0"),
            ('cdp-prosemirror-insert',['--selector','.ProseMirror','--text','x'],1,'partial cdp-prosemirror-insert reason=unknown')):
            result=handle('macro-complete',dict(action=action,argv=argv,port_open=True,reply=dict(ExitCode=124,Json=None,Raw=None)),allow_live_control=True)
            self.assertEqual(result['exit_code'],code)
            self.assertEqual(result['brief_line'],line)
            self.assertEqual(result['payload']['reason'],'helper_failed')
            self.assertFalse(result['raw_passthrough'])

    def test_actual_process_native_detect_and_live_gate(self):
        with server() as (state,endpoint):
            p=self.invoke('native',dict(action='cdp-detect',args={}), '--endpoint',endpoint)
            self.assertEqual(p.returncode,0,p.stderr)
            result=json.loads(p.stdout)
            self.assertEqual(result['schema'],SCHEMA)
            self.assertEqual(result['data']['payload']['page_count'],1)
            self.assertEqual(result['data']['exit_code'],0)
            state.paths.clear()
            p=self.invoke('native',dict(action='cdp-eval',args={'expression':'1'}),'--endpoint',endpoint)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(p.stdout)['data']['exit_code'],3)
            self.assertEqual(state.paths,[])

    def test_actual_process_guarded_read_and_live_expression_data(self):
        with server() as (state,endpoint):
            capture(state,[response_for(smart_value()),response_for('owned')])
            p=self.invoke('native',dict(action='cdp-smart-find',args={'needle':"Save'\n);malicious()//"}),'--endpoint',endpoint)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertTrue(state.requests[0]['params']['throwOnSideEffect'])
            p=self.invoke('native',dict(action='cdp-eval',args={'expression':"'$(not-a-shell)'"}),'--endpoint',endpoint,'--allow-live-control')
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(state.requests[1]['params']['expression'],"'$(not-a-shell)'")

    def test_actual_process_limits_malformed_frame_and_permission_messages(self):
        for raw in ('{"action":"cdp-detect","args":{},"allow_live_control":true}\n','{"action":"a","action":"b","args":{}}\n','x'*(MAX_FRAME+1)):
            with self.subTest(length=len(raw)):
                p=self.invoke('native',None,'--endpoint','http://127.0.0.1:1',raw=raw)
                self.assertEqual(p.returncode,1)
                self.assertEqual(json.loads(p.stdout)['status'],'error')
                self.assertNotIn('Traceback',p.stderr)
        p=self.invoke('macro-prepare',dict(action='cdp-eval',argv=['--expr','1']))
        self.assertEqual(json.loads(p.stdout)['error']['message'],'macro cdp-eval requires -AllowLiveControl')

    def test_framework_utf8_preamble_is_transport_only(self):
        frame=json.dumps(dict(action='cdp-detect',argv=['--page-match','한글😀']))+'\n'
        p=self.invoke('macro-prepare',None,raw='\ufeff'+frame)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['data']['native_argv'],['-Action','cdp-detect','-CdpPort','9222'])
        for raw in ('\ufeff\ufeff'+frame,' \ufeff'+frame,'\ufeff{"action":"cdp-detect","action":"cdp-eval","argv":[]}\n'):
            with self.subTest(raw=raw):
                p=self.invoke('macro-prepare',None,raw=raw)
                self.assertEqual(p.returncode,1)


if __name__=='__main__':unittest.main()
