"""Pi process/argv fixtures. These tests never request UAC or control a desktop."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('start_pi', ROOT / 'pcucp-next/packaging/start_pi.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class PiLauncherTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP 한글 space & ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in ('pcucp-next/bin/native/PcuCp.NativeHost.exe', 'integrations/pi/src/index.ts'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def npm_fixture(self, entry='dist/cli.js'):
        shim = self.root / 'pi.cmd'
        shim.write_text('INVALID SHELL CODE; must not execute', encoding='utf-8')
        shim.chmod(0o755)  # POSIX lookup fixture; the shell content is never run.
        package = self.root / 'node_modules/@earendil-works/pi-coding-agent'
        package.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({'bin': {'pi': entry}}), encoding='utf-8')
        js = package / 'dist/cli.js'
        js.parent.mkdir()
        js.write_text('console.log(JSON.stringify({args:process.argv.slice(2),root:process.env.CUCP_ROOT,python:process.env.CUCP_PYTHON,native:process.env.CUCP_NATIVE_HOST,bundle:process.env.CUCP_EXECUTABLE}));process.exit(37);', encoding='utf-8')
        return shim

    def test_preparation_selects_core_and_never_enables_live_control(self):
        with patch.dict(os.environ, CUCP_EXECUTABLE='stale-CUCP.exe'):
            command, env = launcher.prepare(self.root, sys.executable, sys.executable)
        self.assertEqual(command, [str(Path(sys.executable).resolve()), '--extension', str(self.root / 'integrations/pi/src/index.ts')])
        self.assertNotIn('--allow-live-control', command)
        self.assertNotIn('CUCP_EXECUTABLE', env)
        self.assertEqual(env['CUCP_ROOT'], str(self.root))

    def test_missing_native_fails_before_any_process(self):
        (self.root / 'pcucp-next/bin/native/PcuCp.NativeHost.exe').unlink()
        with patch.object(launcher.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Publish'):
                launcher.prepare(self.root, sys.executable, sys.executable)
        run.assert_not_called()

    def test_unknown_shell_wrapper_and_package_escape_are_rejected(self):
        shim = self.npm_fixture('../outside.js')
        (shim.parent / 'node_modules/@earendil-works/outside.js').write_text('fixture', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inside'):
            launcher.pi_command(shim, node_exe=sys.executable)
        with self.assertRaisesRegex(ValueError, 'shell wrapper'):
            launcher.executable(shim)

    def test_elevation_is_explicit_and_preserves_startup_argv(self):
        args = ['--elevated', '--python-exe', sys.executable, '--pi-executable', sys.executable]
        with patch.object(launcher, 'prepare', return_value=(['fixture.exe'], {})), patch.object(sys, 'platform', 'win32'), \
             patch.object(launcher, 'is_admin', return_value=False), patch.object(launcher, 'elevate', return_value=37) as elevate, \
             patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.main(args), 37)
        self.assertEqual(elevate.call_args.args[0][2:], args)
        run.assert_not_called()

    def test_default_and_already_elevated_launch_do_not_request_uac(self):
        for admin in (False, True):
            args = ['--python-exe', sys.executable, '--pi-executable', sys.executable]
            if admin:
                args.append('--elevated')
            with patch.object(launcher, 'prepare', return_value=(['fixture.exe'], {})), patch.object(sys, 'platform', 'win32'), \
                 patch.object(launcher, 'is_admin', return_value=admin), patch.object(launcher, 'elevate') as elevate, \
                 patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 37)) as run:
                self.assertEqual(launcher.main(args), 37)
            elevate.assert_not_called()
            self.assertIs(run.call_args.kwargs['shell'], False)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the actual harmless JS process fixture')
    def test_real_npm_entry_avoids_shell_preserves_unicode_paths_and_exit(self):
        shim = self.npm_fixture()
        command, env = launcher.prepare(self.root, sys.executable, shim)
        result = subprocess.run(command, env=env, capture_output=True, encoding='utf-8', timeout=10, shell=False)
        self.assertEqual(result.returncode, 37, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['args'], ['--extension', str(self.root / 'integrations/pi/src/index.ts')])
        self.assertEqual(data['root'], str(self.root))
        self.assertEqual(data['python'], str(Path(sys.executable).resolve()))
        self.assertNotIn('bundle', data)


if __name__ == '__main__':
    unittest.main()
