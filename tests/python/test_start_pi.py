"""Launch only owned argv recorders. Elevation is a seam, never a real UAC request."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'pcucp-next/packaging/start_pi.py'
spec = importlib.util.spec_from_file_location('start_pi', SOURCE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class PiLauncherTests(unittest.TestCase):
    def test_fixed_executable_argv_and_environment(self):
        env = launcher.session_environment(Path('/fixture root'), '/python', Path('/native'), {'sentinel': 'kept'})
        self.assertEqual(launcher.pi_command('/pi.exe', '/한글 extension.ts', env), ['/pi.exe', '--extension', '/한글 extension.ts'])
        self.assertEqual(env['sentinel'], 'kept')
        self.assertEqual(env['CUCP_ROOT'], str(Path('/fixture root')))
        self.assertNotIn('CUCP_ALLOW_LIVE_CONTROL', env)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows npm shim decoding')
    def test_actual_cmd_unicode_metacharacter_paths_exit_and_argv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / '한글 space %CUCP_TEST_EXPANSION% ! & clone'
            root.mkdir()
            pi = root / 'pi.cmd'
            recorder = root / 'recorder.py'
            extension = root / 'extension.ts'
            extension.write_text('owned test')
            recorder.write_text('import json,os,sys; print(json.dumps(dict(args=sys.argv[1:],root=os.environ["CUCP_ROOT"],native=os.environ["CUCP_NATIVE_HOST"]),ensure_ascii=True)); sys.exit(37)', encoding='utf-8')
            pi.write_bytes(b'@echo off\r\nsetlocal DisableDelayedExpansion\r\n"%CUCP_TEST_PYTHON%" "%CUCP_TEST_RECORDER%" %*\r\n')
            env = launcher.session_environment(root, sys.executable, root / 'native.exe')
            env.update(CUCP_TEST_PYTHON=sys.executable, CUCP_TEST_RECORDER=str(recorder), CUCP_TEST_EXPANSION='MUST_NOT_EXPAND')
            result = subprocess.run(launcher.pi_command(pi, extension, env), env=env, shell=False,
                capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 37, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['args'], ['--extension', str(extension)])
            self.assertEqual(value['root'], str(root))
            self.assertEqual(value['native'], str(root / 'native.exe'))

    def test_rejects_paths_that_can_break_the_fixed_cmd_boundary(self):
        for path in ('a"b.cmd', 'a\nb.cmd', 'a\0b.cmd'):
            with self.assertRaises(ValueError): launcher.pi_command(path, 'extension.ts', {})
