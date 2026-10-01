"""No network, desktop, real applications or model API calls."""
import io
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next/python'))
from pcucp_cli.engine import ComputerSession
from pcucp_cli.mcp_server import McpServer, tool_list, serve_mcp
from test_engine import NativeFake, screenshot_data

class McpTests(unittest.TestCase):
    def setUp(self):
        self.sink = io.StringIO()
        self.native = NativeFake()
        self.session = ComputerSession(native=self.native)
        self.closed = False
        self.server = McpServer(self.session, self.sink, lambda: setattr(self, 'closed', True))
        self.rid = 0

    def request(self, method, params=None, rid=None):
        self.rid += 1
        self.server.receive({'jsonrpc': '2.0', 'id': rid if rid is not None else self.rid, 'method': method, 'params': params or {}})
        if self.server.worker:
            self.server.worker.join(2)
        return json.loads(self.sink.getvalue().splitlines()[-1])

    def init(self):
        result = self.request('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
        self.server.receive({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return result

    def call(self, name, args=None, **kwargs):
        return self.request('tools/call', {'name': 'cucp_' + name, 'arguments': args or {}}, **kwargs)

    def test_lifecycle_and_tools(self):
        self.assertIn('error', self.request('tools/list'))
        self.assertEqual(self.init()['result']['protocolVersion'], '2025-11-25')
        listing = self.request('tools/list')['result']['tools']
        self.assertEqual(len(listing), 40)
        self.assertTrue(all(t['inputSchema']['additionalProperties'] is False for t in listing))
        self.assertNotIn('cucp_enable', [t['name'] for t in listing])
        self.assertIn('error', self.request('initialize'))

    def test_version_negotiation(self):
        result = self.request('initialize', {'protocolVersion': 'unknown', 'capabilities': {}, 'clientInfo': {}})
        self.assertEqual(result['result']['protocolVersion'], '2025-11-25')

    def test_readonly_never_forwards_write_or_permission_override(self):
        self.init()
        result = self.call('focus', {'hwnd': '0x20', 'pid': 42, 'allow_live_control': True})['result']
        self.assertTrue(result['isError'])
        self.assertIn('live_control_required', result['content'][0]['text'])
        self.assertEqual(self.native.calls, [])

    def test_image_is_native_mcp_content_and_metadata_kept(self):
        self.init()
        result = self.call('observe', {'hwnd': '0x20'})['result']
        self.assertFalse(result['isError'])
        self.assertEqual(result['content'][1], {'type': 'image', 'mimeType': 'image/png', 'data': screenshot_data()['image']['data']})
        metadata = json.loads(result['content'][0]['text'])
        self.assertEqual(metadata['data']['image']['width'], 960)
        self.assertNotIn('data', metadata['data']['image'])
        self.assertIn('observation_id', metadata['data'])

    def test_batch_returns_last_image_and_preserves_failure_state(self):
        self.init()
        result = self.call('batch', {'actions': [
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
        ]})['result']
        self.assertEqual([item['type'] for item in result['content']], ['text', 'image'])
        data = json.loads(result['content'][0]['text'])['data']
        self.assertEqual(data['image_from_step'], 1)
        self.assertNotIn('image', data['steps'][0]['data'])
        self.assertEqual(data['image']['width'], 960)

    def test_duplicate_request_and_unknown_tool(self):
        self.init()
        self.call('windows', rid='dedupe')
        before = len(self.native.calls)
        self.assertIn('error', self.call('windows', rid='dedupe'))
        self.assertEqual(len(self.native.calls), before)
        self.assertEqual(self.call('enable_live')['error']['code'], -32602)

    def test_integer_and_string_ids_distinct_and_long_id_works(self):
        self.init()
        self.assertFalse(self.call('capabilities', rid=100)['result']['isError'])
        self.assertFalse(self.call('capabilities', rid='100')['result']['isError'])
        self.assertFalse(self.call('capabilities', rid='x'*128)['result']['isError'])

    def test_cancellation_terminal_no_reply_and_no_input_replay(self):
        entered, release = threading.Event(), threading.Event()
        def native(*args, **kwargs):
            entered.set()
            release.wait(2)
            return self.native(*args, **kwargs)
        self.session.native = native
        self.server.close_native = release.set
        self.init()
        self.server.receive({'jsonrpc': '2.0', 'id': 'pending', 'method': 'tools/call', 'params': {'name': 'cucp_windows'}})
        self.assertTrue(entered.wait(1))
        count = len(self.sink.getvalue().splitlines())
        self.server.receive({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 'pending'}})
        self.server.worker.join(2)
        self.assertEqual(len(self.sink.getvalue().splitlines()), count)
        self.assertTrue(self.session.cancelled.is_set())
        self.assertTrue(self.call('windows')['result']['isError'])
        self.assertEqual(len(self.native.calls), 1)

    def test_unknown_cancel_ignored_and_notification_never_replied(self):
        self.init()
        before = self.sink.getvalue()
        for params in ({'requestId': 'absent'}, {'requestId': []}, []):
            self.server.receive({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': params})
        self.assertEqual(before, self.sink.getvalue())
        self.assertFalse(self.session.cancelled.is_set())

    def test_close_invalidates_session(self):
        self.server.close()
        self.assertTrue(self.closed)
        self.assertTrue(self.session.cancelled.is_set())

    def test_oversize_and_invalid_frames(self):
        sink = io.StringIO()
        self.assertEqual(serve_mcp(source=io.BytesIO(b'{' + b'x'*262144), sink=sink), 2)
        self.assertEqual(json.loads(sink.getvalue())['error']['code'], -32600)
        sink = io.StringIO()
        self.assertEqual(serve_mcp(source=io.BytesIO(b'NaN\n[]\n'), sink=sink), 0)
        self.assertEqual([json.loads(v)['error']['code'] for v in sink.getvalue().splitlines()], [-32700, -32600])


class McpProcessTests(unittest.TestCase):
    def start(self, code=None):
        import os
        import queue
        self.queue = queue.Queue()
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'pcucp-next/python'))
        argv = [sys.executable, '-u', '-c', code] if code else [sys.executable, '-u', '-m', 'pcucp_cli', 'mcp']
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding='utf-8', env=env)
        def reader():
            for line in self.process.stdout:
                self.queue.put(json.loads(line))
        threading.Thread(target=reader, daemon=True).start()
        self.addCleanup(self.cleanup)
        self.send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
        self.assertEqual(self.queue.get(timeout=3)['id'], 1)
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})

    def cleanup(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed: stream.close()

    def send(self, request):
        self.process.stdin.write(json.dumps(request)+'\n')
        self.process.stdin.flush()

    def test_real_cli_protocol_and_read_only_default(self):
        self.start()
        self.send({'jsonrpc':'2.0','id':2,'method':'tools/list'})
        self.assertEqual(len(self.queue.get(timeout=3)['result']['tools']),40)
        self.send({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'cucp_capabilities'}})
        result=self.queue.get(timeout=3)
        self.assertFalse(json.loads(result['result']['content'][0]['text'])['data']['allow_live_control'])
        self.send({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'cucp_focus','arguments':{'hwnd':'0x20','pid':42}}})
        self.assertTrue(self.queue.get(timeout=3)['result']['isError'])
        self.process.stdin.close()
        self.assertEqual(self.process.wait(timeout=3),0)
        self.assertEqual(self.process.stderr.read(),'')

    def test_eof_cancels_pending_native_without_replay(self):
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as directory:
            log = str(Path(directory)/'requests.jsonl')
            fixture = str(Path(__file__).resolve().parents[1]/'fixtures/native_session_host.py')
            code = ('import sys; from pcucp_cli import native_host; '
                    f'native_host._native_argv=lambda:([sys.executable,{fixture!r},"hang",{log!r}],""); '
                    'from pcucp_cli.mcp_server import run_mcp; raise SystemExit(run_mcp())')
            self.start(code)
            self.send({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'cucp_windows'}})
            deadline=time.monotonic()+3
            while not Path(log).exists() and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(Path(log).exists())
            self.process.stdin.close()
            self.assertEqual(self.process.wait(timeout=3),0)
            self.assertEqual(len(Path(log).read_text().splitlines()),1)
            self.assertTrue(self.queue.empty())

if __name__ == '__main__': unittest.main()
