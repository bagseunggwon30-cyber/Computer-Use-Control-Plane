"""Persistent Python startup against an owned C# service and lock directory."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_helper_runtime import StagedHelperRuntime
spec = importlib.util.spec_from_file_location('python_helper_server', ROOT / 'scripts/cucp-helper-server.py')
server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)


class HelperStartupTests(unittest.TestCase):
    def test_classic_options_keep_zero_idle_custom_pipe_and_debug(self):
        with patch.object(server,'validate_package'):
            argv, lock = server.command(Path('/owned'), pipe_name='owned-name', lock_file=Path('/owned/helper.pid'), idle_timeout_ms=0, debug_log=True)
        self.assertIn('serve-direct',argv); self.assertIn('--allow-readonly-desktop',argv); self.assertIn('--debug-log',argv)
        self.assertEqual(argv[argv.index('--idle-timeout-ms')+1],'0')
        for value in (-1,True,2147483648):
            with self.assertRaises(ValueError): server.command(Path('/owned'),idle_timeout_ms=value)


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_PYTHON_HELPER_PACKAGE'),'Explicit owned Windows helper package')
class ActualPythonHelperTests(unittest.TestCase):
    def test_python_start_windows_health_debug_and_acknowledged_shutdown(self):
        package = Path(os.environ['CUCP_PYTHON_HELPER_PACKAGE'])
        with tempfile.TemporaryDirectory(prefix='CUCP-helper-python-') as folder:
            root = Path(folder).resolve(); lock = root/'helper.pid'; stderr = root/'debug.log'
            runtime = StagedHelperRuntime(package,lock,desktop=True)
            with stderr.open('wb') as errors:
                process = subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'scripts/cucp-helper-server.py'),
                    '--package',str(package),'-LockFile',str(lock),'-IdleTimeoutMs','10000','-DebugLog'],
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline=time.monotonic()+5
                    while not runtime.client.state().usable and process.poll() is None and time.monotonic()<deadline: time.sleep(.025)
                    self.assertTrue(runtime.client.state().usable,stderr.read_bytes().decode('utf-8',errors='replace'))
                    windows=runtime.client.invoke('windows',{'Match':'CUCP-owned-absent-helper-window'})
                    self.assertEqual(windows['exit_code'],0)
                    self.assertEqual(windows['result']['count'],0)
                    health=runtime.client.invoke('health')
                    self.assertEqual(health['exit_code'],0)
                    self.assertEqual(health['result']['pipe_name'],'cucp-helper-'+str(health['result']['pid']))
                    self.assertEqual(runtime.client.stop()['reason'],'shutdown_requested')
                    self.assertEqual(process.wait(timeout=5),0)
                    self.assertFalse(lock.exists())
                finally:
                    if process.poll() is None:
                        try: runtime.client.stop()
                        finally:
                            process.terminate(); process.wait(timeout=5)
            debug=stderr.read_text(encoding='utf-8')
            self.assertIn('event=server.start',debug)
            self.assertIn('action=windows',debug)
            self.assertNotIn('CUCP-owned-absent-helper-window',debug)
