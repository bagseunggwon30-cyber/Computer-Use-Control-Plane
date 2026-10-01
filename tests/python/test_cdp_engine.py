"""Host-neutral engine/browser adapter integration against local mock sockets only."""
import io
import json
import unittest
from unittest.mock import patch
from pcucp_cli.engine import ComputerSession
from pcucp_cli.mcp_server import McpServer
from pcucp_cli.server import _serve_frames
from pcucp_cli.cdp import CdpError
from test_engine import NativeFake
from test_cdp import server


class CdpEngineTests(unittest.TestCase):
    def call(self, session, command, args=None):
        self.sequence = getattr(self, 'sequence', 0) + 1
        return session.handle({'schema':'cucp.request/v1','id':str(self.sequence),'command':command,'args':args or {}})

    def test_adapter_disabled_without_explicit_startup_configuration(self):
        session = ComputerSession()
        response = self.call(session, 'cdp-detect')
        self.assertEqual(response['status'], 'blocked')
        self.assertEqual(response['errors'][0]['code'], 'cdp_not_configured')
        self.assertFalse(self.call(session, 'capabilities')['data']['cdp']['configured'])

    def test_readonly_gate_and_request_endpoint_rejected_before_network(self):
        with server() as (state, endpoint):
            session = ComputerSession(cdp_endpoint=endpoint)
            self.addCleanup(session.cancel)
            self.assertEqual(state.paths, [])
            response = self.call(session, 'cdp-eval', {'snapshot_id':'bad','expression':'document.body.remove()'})
            self.assertEqual(response['errors'][0]['code'], 'live_control_required')
            response = self.call(session, 'cdp-detect', {'endpoint':endpoint})
            self.assertEqual(response['errors'][0]['code'], 'invalid_argument')
            self.assertEqual(state.paths, [])

    def test_browser_mutation_invalidates_prior_native_observation(self):
        with server() as (state, endpoint):
            session = ComputerSession(cdp_endpoint=endpoint, allow_live_control=True, native=NativeFake())
            self.addCleanup(session.cancel)
            token = self.call(session, 'observe', {'hwnd':'0x20'})['data']['observation_id']
            browser = self.call(session, 'cdp-observe', {'target_id':'page-0'})['data']
            button = next(n for n in browser['nodes'] if n['tag_name']=='button')
            response = self.call(session, 'cdp-click', {'snapshot_id':browser['snapshot_id'], 'element_ref':button['element_ref']})
            self.assertEqual(response['status'], 'ok', response)
            self.assertEqual(response['data']['verification'], 'protocol_dispatch_not_task_success')
            stale = self.call(session, 'click', {'observation_id':token,'x':1,'y':1})
            self.assertEqual(stale['errors'][0]['code'],'stale_observation')

    def test_native_mutation_invalidates_browser_snapshot(self):
        with server() as (state, endpoint):
            session = ComputerSession(cdp_endpoint=endpoint, allow_live_control=True, native=NativeFake())
            self.addCleanup(session.cancel)
            browser = self.call(session, 'cdp-observe', {'target_id':'page-0'})['data']
            self.assertEqual(self.call(session, 'focus', {'hwnd':'0x20','pid':42})['status'],'ok')
            stale = self.call(session, 'cdp-query', {'snapshot_id':browser['snapshot_id'],'selector':'#save'})
            self.assertEqual(stale['errors'][0]['code'],'stale_snapshot')

    def test_uncertain_browser_mutation_is_partial_and_never_retried(self):
        with server() as (state, endpoint):
            session = ComputerSession(cdp_endpoint=endpoint, allow_live_control=True)
            self.addCleanup(session.cancel)
            browser = self.call(session, 'cdp-observe', {'target_id':'page-0'})['data']
            button = next(n for n in browser['nodes'] if n['tag_name']=='button')
            state.drop_method='Runtime.callFunctionOn'
            response = self.call(session,'cdp-click',{'snapshot_id':browser['snapshot_id'],'element_ref':button['element_ref']})
            self.assertEqual(response['status'],'partial',response)
            self.assertTrue(response['data']['may_have_acted'])
            self.assertFalse(response['data']['automatic_retry'])
            self.assertEqual(sum(r['method']=='Runtime.callFunctionOn' for r in state.requests),1)

    def test_declarative_browser_workflow_uses_snapshot_references(self):
        with server() as (state, endpoint):
            session = ComputerSession(cdp_endpoint=endpoint, allow_live_control=True)
            self.addCleanup(session.cancel)
            response = self.call(session,'workflow-run',{'workflow':{'steps':[
                {'id':'obs','command':'cdp-observe','args':{'target_id':'page-0'}},
                {'id':'find','command':'cdp-query','args':{'snapshot_id':{'$ref':'/obs/snapshot_id'},'selector':'#save'},'assert':{'path':'/candidate_count','equals':1}},
                {'command':'cdp-click','args':{'snapshot_id':{'$ref':'/obs/snapshot_id'},'element_ref':{'$ref':'/find/candidates/0/element_ref'}}},
            ]}})
            self.assertEqual(response['status'],'ok',response)
            self.assertEqual(response['data']['executed_count'],3)
            self.assertTrue(response['data']['may_have_acted'])

    def test_same_browser_read_over_mcp_and_jsonl(self):
        for host in ('mcp','jsonl'):
            with self.subTest(host=host), server() as (state, endpoint):
                session=ComputerSession(cdp_endpoint=endpoint)
                self.addCleanup(session.cancel)
                sink=io.StringIO()
                if host=='jsonl':
                    wire=json.dumps({'schema':'cucp.request/v1','id':'browser','command':'cdp-detect','args':{}})+'\n'
                    _serve_frames(io.BytesIO(wire.encode()),sink,session)
                    response=json.loads(sink.getvalue())
                else:
                    mcp=McpServer(session,sink)
                    mcp.receive({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'fixture','version':'1'}}})
                    mcp.receive({'jsonrpc':'2.0','method':'notifications/initialized'})
                    mcp.receive({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'cucp_cdp_detect'}})
                    mcp.worker.join(2)
                    response=json.loads(json.loads(sink.getvalue().splitlines()[-1])['result']['content'][0]['text'])
                self.assertEqual(response['status'],'ok',response)
                self.assertEqual(response['data']['targets'][0]['id'],'page-0')
                self.assertEqual(state.requests,[])

    def test_session_cancel_is_terminal_for_optional_browser_adapter(self):
        with server() as (state, endpoint):
            session=ComputerSession(cdp_endpoint=endpoint)
            session.cancel()
            response=self.call(session,'cdp-detect')
            self.assertEqual(response['errors'][0]['code'],'session_cancelled')
            self.assertEqual(state.paths,[])
