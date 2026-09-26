import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from pcucp_cli.server import MAX_REQUEST_BYTES, serve

class ServerTests(unittest.TestCase):
    def run_frames(self, data):
        sink = io.StringIO()
        code = serve(source=io.BytesIO(data), sink=sink)
        return code, [json.loads(line) for line in sink.getvalue().splitlines()]

    def test_bad_json_recovers_without_corrupting_stdout(self):
        request = {'schema':'cucp.request/v1','id':'1','command':'capabilities','args':{}}
        code, rows = self.run_frames(b'not-json\n' + json.dumps(request).encode() + b'\n')
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]['errors'][0]['code'], 'invalid_json')
        self.assertEqual(rows[1]['status'], 'ok')
        self.assertFalse(rows[1]['data']['allow_live_control'])

    def test_non_finite_json_rejected(self):
        _, rows = self.run_frames(b'{"args": NaN}\n')
        self.assertEqual(rows[0]['errors'][0]['code'], 'invalid_json')

    def test_oversize_frame_closes_session(self):
        code, rows = self.run_frames(b'x' * (MAX_REQUEST_BYTES + 1) + b'\n{}\n')
        self.assertEqual(code, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['errors'][0]['code'], 'request_too_large')

    def test_real_cli_jsonl_and_policy(self):
        requests = [dict(schema='cucp.request/v1', id=str(i), command=c, args=a) for i,c,a in [
            (1,'capabilities',{}), (2,'focus',{'hwnd':'0x1','pid':1}), (3,'arbitrary-shell',{})]]
        env = {**os.environ, 'PYTHONPATH':str(Path(__file__).resolve().parents[2] / 'pcucp-next/python')}
        result = subprocess.run([sys.executable,'-u','-m','pcucp_cli','serve'], input=''.join(json.dumps(r)+'\n' for r in requests),
                                text=True, capture_output=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['status'] for r in rows], ['ok','blocked','blocked'])
        self.assertEqual([r['id'] for r in rows], ['1','2','3'])

if __name__ == '__main__': unittest.main()
