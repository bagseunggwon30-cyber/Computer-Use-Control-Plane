import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from helper_process_evidence import run_evidence, require_success


class HelperProcessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_python(self, code, **kwargs):
        return run_evidence([sys.executable, '-c', code], directory=self.temp.name, label='owned', **kwargs)

    def test_creation_flags_are_recorded_and_privilege_expansion_is_refused(self):
        result = self.run_python('print("ordinary")')
        self.assertEqual(result['creationflags'], 0)
        for flags in (True, -1, 0x01000000, 0x00000004):
            with self.subTest(flags=flags):
                with self.assertRaises(ValueError): self.run_python('raise RuntimeError("must not launch")', creationflags=flags)

    def test_invalid_labels_refuse_before_process_launch_on_every_platform(self):
        from helper_process_evidence import validate_evidence_label
        invalid=(None,1,'','*','test_autostart*.py','../escape','a/b','a\\b','a:b','a?b',
                 'a<b','a>b','a|b','a"b','a\n','a\0','trailing.','name.py','한글','x'*121)
        with patch('helper_process_evidence.subprocess.Popen') as launch:
            for label in invalid:
                with self.subTest(label=label):
                    with self.assertRaises(ValueError):
                        run_evidence([sys.executable,'-c','raise RuntimeError("must not launch")'],
                            directory=self.temp.name,label=label)
            launch.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])
        for label in ('a','helper-autostart-tests','record_123','x'*120):
            self.assertEqual(validate_evidence_label(label),label)

    def test_valid_repeated_label_keeps_separate_complete_raw_evidence(self):
        first=self.run_python('print("first")');second=self.run_python('print("second")')
        require_success(first);require_success(second)
        self.assertNotEqual(first['evidence_path'],second['evidence_path'])
        for result,expected in ((first,b'first'),(second,b'second')):
            path=Path(result['evidence_path'])
            self.assertEqual(path.with_suffix('.stdout.bin').read_bytes().strip(),expected)
            self.assertEqual(path.with_suffix('.stderr.bin').read_bytes(),b'')
            self.assertEqual(json.loads(path.read_text())['exit_code'],0)

    def test_staged_gate_preserves_discovery_pattern_but_never_uses_it_as_label(self):
        import importlib.util
        import io
        from contextlib import redirect_stdout
        from helper_process_evidence import validate_evidence_label
        root=Path(__file__).resolve().parents[2]
        spec=importlib.util.spec_from_file_location('owned_staged_gate',root/'pcucp-next/packaging/qualify_staged_legacy_helper.py')
        gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
        calls=[]
        def capture(argv,**kwargs):
            validate_evidence_label(kwargs['label']);calls.append((argv,kwargs))
            return dict(stdout=b'',stderr=b'',evidence_path='inert-fixture',exit_code=0,running=False,
                launch_error=None,timed_out=False,kill_error=None,drain_incomplete=False,stdin_error=None,
                read_errors={},truncated={'stdout':False,'stderr':False})
        with patch.object(gate,'run_evidence',side_effect=capture),redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(['--autostart','--log-dir',self.temp.name]),0)
        self.assertEqual(len(calls),5)
        labels=[kwargs['label'] for _,kwargs in calls]
        self.assertEqual(len(set(labels)),len(labels))
        self.assertEqual(calls[0][0][-3:-1],['-p','test_helper_process_evidence.py'])
        self.assertEqual(calls[-1][0][-3:-1],['-p','test_legacy_helper_autostart*.py'])
        self.assertEqual(labels[-1],'helper-autostart-tests')
        self.assertTrue(all(kwargs['timeout']==300 and kwargs['limit']==2*1024*1024 for _,kwargs in calls))

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
