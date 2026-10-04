"""Actual owned Node fixtures exercise forwarding, capture, timeout and cancellation."""
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import subprocess
import sys
import base64

from pcucp_cli.legacy_host_protocol import LegacyHostError
from pcucp_cli.legacy_node_runtime import NodeRuntime

@unittest.skipUnless(shutil.which('node'),'Actual Node executable')
class NodeRuntimeTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='CUCP Node 한글 ')
        self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.cli=self.root/'cli.mjs'
        self.cli.write_text("""
const args=process.argv.slice(2);
if(args[0]==='slow'){process.stdout.write('partial owned');setTimeout(()=>process.exit(0),10000);}
else if(args[0]==='bad'){process.stdout.write('not JSON');process.stderr.write('owned error');process.exitCode=2;}
else{process.stdout.write(JSON.stringify({status:'ok',args}));}
""",encoding='utf-8')
    def runtime(self,**kwargs):
        return NodeRuntime(cli_path=str(self.cli),cache_directory=str(self.root/'cache'),
                           wrapper_log=str(self.root/'wrapper.log'),**kwargs)
    def test_literal_argv_quotes_unicode_empty_values_and_capture_artifact(self):
        words=['owned','','한글😀','quoted " value','C:\\owned trailing\\','--allow-live-control']
        result=self.runtime().invoke(words,parse_reply=json.loads)
        self.assertEqual(result['ExitCode'],0);self.assertEqual(result['Json']['args'],words)
        self.assertEqual(Path(result['FilePath']).read_text(),result['Raw'])
        self.assertEqual(result['Err'],'')
    def test_missing_cli_invalid_json_and_nonzero_exit_remain_distinct(self):
        runtime=self.runtime();runtime.cli_path=None
        result=runtime.invoke([])
        self.assertEqual(result['ExitCode'],1);self.assertEqual(result['Json']['error_type'],'cli_missing')
        self.assertIsNone(result['FilePath'])
        result=self.runtime().invoke(['bad'],parse_reply=json.loads)
        self.assertEqual(result['ExitCode'],2);self.assertIsNone(result['Json'])
        self.assertEqual(result['Raw'],'not JSON');self.assertEqual(result['Err'],'owned error')
    def test_timeout_keeps_partial_stdout_and_never_replays(self):
        result=self.runtime(timeout_ms=350).invoke(['slow'],parse_reply=json.loads)
        self.assertEqual(result['ExitCode'],124);self.assertEqual(result['Raw'],'partial owned')
        self.assertEqual(result['Json']['error_type'],'invoke_timeout')
        self.assertEqual(len(list((self.root/'cache').glob('invoke-*.json'))),1)
    def test_cancellation_and_expired_parent_scope_stop_owned_worker(self):
        runtime=self.runtime();timer=threading.Timer(.1,runtime.close);timer.start();self.addCleanup(timer.cancel)
        with self.assertRaises(LegacyHostError):runtime.invoke(['slow'])
        self.assertIsNone(runtime._process)
        with self.assertRaises(LegacyHostError):runtime.invoke([])
        with self.assertRaises(LegacyHostError):
            self.runtime(parent_deadline=time.monotonic()-1).invoke(['owned'])
    def test_closing_child_does_not_cancel_parent_or_queue_a_second_invocation(self):
        parent=threading.Event();runtime=self.runtime(cancelled=parent)
        runtime.close();self.assertFalse(parent.is_set())
        runtime=self.runtime()
        self.assertTrue(runtime._serial.acquire(blocking=False))
        try:
            with self.assertRaises(LegacyHostError):runtime.invoke([])
        finally:runtime._serial.release()
    def test_fixed_entry_carries_text_as_base64_and_rejects_path_selection(self):
        entry=Path(__file__).resolve().parents[2]/'pcucp-next/python/legacy_node_capture.py'
        command=[sys.executable,str(entry),'--cli-path',str(self.cli),'--cache-directory',str(self.root/'cache'),
                 '--wrapper-log',str(self.root/'wrapper.log'),'--timeout-ms','30000']
        result=subprocess.run(command,input=json.dumps(dict(argv=['owned','한글😀'])).encode(),
                              capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        reply=json.loads(result.stdout)
        self.assertEqual(reply['schema'],'cucp.node-capture/v1')
        raw=base64.b64decode(reply['data']['RawBase64']).decode()
        self.assertEqual(json.loads(raw)['args'],['owned','한글😀'])
        result=subprocess.run(command,input=json.dumps(dict(argv=[],cli_path='other')).encode(),
                              capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
    def test_zero_infinite_timeout_and_logging_failure_preserve_capture(self):
        self.assertEqual(self.runtime(timeout_ms=0).invoke(['owned'])['ExitCode'],124)
        result=self.runtime(timeout_ms=-1,log=lambda message:(_ for _ in ()).throw(OSError('owned log failure'))).invoke(['owned'],parse_reply=json.loads)
        self.assertEqual(result['ExitCode'],0);self.assertEqual(result['Json']['status'],'ok')
        result=self.runtime(node=str(self.root/'absent-node.exe')).invoke(['owned'])
        self.assertEqual(result['ExitCode'],1);self.assertIsNone(result['Json'])

if __name__=='__main__':unittest.main()
