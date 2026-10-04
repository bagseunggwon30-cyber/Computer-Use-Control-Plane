"""Executable host adapters and CLI plans, without native desktop effects."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pcucp_cli.engine import ComputerSession
from pcucp_cli.server import _serve_frames
from pcucp_cli.mcp_server import McpServer
from pcucp_cli.schema_export import request_schema
from test_engine import NativeFake, envelope

ROOT = Path(__file__).resolve().parents[2]


class WorkflowTransportTests(unittest.TestCase):
    def test_jsonl_and_mcp_execute_same_compiled_form(self):
        for host in ('jsonl', 'mcp'):
            with self.subTest(host=host):
                native = NativeFake()
                node = {'name': '제목', 'automation_id': 'title', 'control_type': 'Edit', 'process_id': 42,
                        'element_ref': 'A'*48, 'children': []}
                native.queue('uia-tree', envelope('uia-tree', data={'nodes': [node]}))
                session = ComputerSession(allow_live_control=True, native=native)
                args = {'hwnd': '0x20', 'fields': [{'selector': {'automation_id': 'title'}, 'text': '한글 😀'}]}
                sink = io.StringIO()
                if host == 'jsonl':
                    request = {'schema': 'cucp.request/v1', 'id': 'form', 'command': 'form-run', 'args': args}
                    _serve_frames(io.BytesIO((json.dumps(request)+'\n').encode()), sink, session)
                    response = json.loads(sink.getvalue())
                else:
                    server = McpServer(session, sink)
                    server.receive({'jsonrpc': '2.0', 'id': 'init', 'method': 'initialize', 'params': {
                        'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'generic', 'version': '1'}}})
                    server.receive({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                    server.receive({'jsonrpc': '2.0', 'id': 'form', 'method': 'tools/call', 'params': {
                        'name': 'cucp_form_run', 'arguments': args}})
                    server.worker.join(2)
                    result = json.loads(sink.getvalue().splitlines()[-1])['result']
                    response = json.loads(result['content'][0]['text'])
                    self.assertEqual(sum(c['type'] == 'image' for c in result['content']), 1)
                self.assertEqual(response['status'], 'ok', response)
                self.assertEqual(response['data']['executed_count'], 3)
                self.assertEqual([c[0] for c in native.calls].count('uia-set-value'), 1)

    def test_cli_plan_and_dry_run_need_no_native_or_powershell(self):
        with tempfile.TemporaryDirectory(prefix='CUCP 한글 ') as temp:
            path = Path(temp)/'plan.json'
            path.write_text(json.dumps({'steps': [{'command': 'type', 'args': {'observation_id': 'unused', 'text': '한글'}}]}), encoding='utf-8')
            env = {**os.environ, 'PYTHONPATH': str(ROOT/'pcucp-next/python'), 'CUCP_NATIVE_HOST': str(Path(temp)/'absent.exe')}
            for args in (['workflow-plan'], ['workflow-run', '--dry-run']):
                result = subprocess.run([sys.executable, '-m', 'pcucp_cli', *args, '--file', str(path), '--json'],
                                        capture_output=True, text=True, env=env, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'ok')
            result = subprocess.run([sys.executable, '-m', 'pcucp_cli', 'workflow-run', '--file', str(path), '--json'],
                                    capture_output=True, text=True, env=env, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['errors'][0]['code'], 'live_control_required')

    def test_exported_schema_is_exactly_current_tool_contract(self):
        stored = json.loads((ROOT/'pcucp-next/schemas/request.schema.json').read_text())
        self.assertEqual(stored, request_schema())
