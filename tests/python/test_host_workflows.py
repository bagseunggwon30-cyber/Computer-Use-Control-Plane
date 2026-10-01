"""Same workflow through actual JSONL/MCP adapters with injected native fixture.

No model/client SDK is required. This proves adapter mapping, not external-host
compatibility or real Windows provider behavior.
"""
import io
import json
import unittest
from pcucp_cli.engine import ComputerSession
from pcucp_cli.server import _serve_frames
from pcucp_cli.mcp_server import McpServer
from test_engine import NativeFake, envelope

class HostWorkflowTests(unittest.TestCase):
    def test_common_observe_find_set_value_flow(self):
        for host in ('jsonl', 'mcp'):
            with self.subTest(host=host):
                native = NativeFake()
                node = {'name': '입력', 'automation_id': 'input', 'control_type': 'Edit',
                        'process_id': 42, 'element_ref': 'A'*48, 'children': []}
                native.queue('uia-tree', envelope('uia-tree', data={'nodes': [node]}))
                session = ComputerSession(allow_live_control=True, native=native)
                sink = io.StringIO()
                server = McpServer(session, sink)
                if host == 'mcp':
                    server.receive({'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'generic-test', 'version': '1'}}})
                    server.receive({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                sequence = 0
                def call(command, args):
                    nonlocal sequence
                    sequence += 1
                    if host == 'jsonl':
                        req = {'schema': 'cucp.request/v1', 'id': str(sequence), 'command': command, 'args': args}
                        _serve_frames(io.BytesIO((json.dumps(req)+'\n').encode()), sink, session)
                        return json.loads(sink.getvalue().splitlines()[-1])
                    server.receive({'jsonrpc': '2.0', 'id': sequence, 'method': 'tools/call', 'params': {
                        'name': 'cucp_'+command.replace('-', '_'), 'arguments': args}})
                    server.worker.join(2)
                    result = json.loads(sink.getvalue().splitlines()[-1])['result']
                    return json.loads(result['content'][0]['text'])
                observed = call('observe', {'hwnd': '0x20'})
                self.assertEqual(observed['status'], 'ok')
                token = observed['data']['observation_id']
                found = call('uia-find', {'observation_id': token, 'automation_id': 'input'})
                self.assertEqual(found['data']['count'], 1)
                result = call('uia-set-value', {'observation_id': token, 'element_ref': found['data']['matches'][0]['element_ref'], 'text': '한글 😀'})
                self.assertEqual(result['status'], 'ok', result)
                self.assertEqual(result['data']['verification'], 'observed_not_asserted')
                stale = call('uia-invoke', {'observation_id': token, 'element_ref': 'A'*48})
                self.assertEqual(stale['status'], 'blocked')
                self.assertEqual(len([c for c in native.calls if c[0] == 'uia-set-value']), 1)
                self.assertNotIn('uia-invoke', [c[0] for c in native.calls])
