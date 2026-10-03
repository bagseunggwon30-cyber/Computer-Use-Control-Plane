import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from helper_process_evidence import run_evidence, require_success


class HelperProcessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_python(self, code, **kwargs):
        return run_evidence([sys.executable, '-c', code], directory=self.temp.name, label='owned', **kwargs)

    def test_success_failure_and_both_raw_streams(self):
        result = self.run_python("import os; os.write(1,b'out\\xff'); os.write(2,b'err\\xfe'); raise SystemExit(7)")
        require_success(result, expected_exit=7)
        self.assertEqual(result['stdout'], b'out\xff')
        self.assertEqual(result['stderr'], b'err\xfe')
        self.assertTrue(Path(result['evidence_path']).is_file())

    def test_timeout_retains_available_prefixes(self):
        result = self.run_python("import os,time; os.write(1,b'before'); os.write(2,b'error'); time.sleep(10)", timeout=.1)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['stdout'], b'before')
        self.assertEqual(result['stderr'], b'error')
        with self.assertRaises(AssertionError):
            require_success(result, expected_exit=result['exit_code'])

    def test_overflow_keeps_bounded_prefix_not_tail(self):
        result = self.run_python("import os; os.write(1,b'prefix'+b'x'*50000)", limit=100)
        self.assertEqual(len(result['stdout']), 100)
        self.assertTrue(result['stdout'].startswith(b'prefix'))
        self.assertTrue(result['truncated']['stdout'])
        with self.assertRaises(AssertionError):
            require_success(result)

    def test_launch_error_cannot_be_expected_rejection(self):
        result = run_evidence([str(Path(self.temp.name) / 'missing')], directory=self.temp.name, label='missing')
        self.assertIsNotNone(result['launch_error'])
        with self.assertRaises(AssertionError):
            require_success(result, expected_exit=None)

    def test_descendant_holding_pipe_keeps_prefix_and_deadline(self):
        started = time.monotonic()
        # The owned descendant exits itself; no PID lookup or broad tree kill.
        result = self.run_python("import subprocess,sys,os; os.write(1,b'parent'); subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])", timeout=1)
        self.assertLess(time.monotonic() - started, 1.7)
        self.assertEqual(result['stdout'], b'parent')
        self.assertTrue(result['drain_incomplete'])
        self.assertFalse(result['timed_out'])
        with self.assertRaises(AssertionError):
            require_success(result)
