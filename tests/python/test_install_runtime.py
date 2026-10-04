"""Installer file/argv fixtures only; no real install, model or elevation calls."""
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'pcucp-next/packaging/install_runtime.py'
spec = importlib.util.spec_from_file_location('install_runtime', SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "한글 space %bang! ' clone"
        self.bin = Path(self.temp.name) / '설치 bin'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'scripts/cucp.ps1').write_text('param()\n[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)\nConvertTo-Json -InputObject @($args) -Compress\nexit 37\n', encoding='utf-8-sig')
        (self.root / 'pcucp-next/python').mkdir(parents=True)
        (self.root / 'pcucp-next/python/run_source.py').write_text(
            'import json,sys; print(json.dumps(sys.argv[1:],ensure_ascii=True)); sys.exit(37)\n', encoding='utf-8')
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        (self.bundle / 'CUCP.exe').write_bytes(b'fixture, not executed')

    def plan(self, backend='legacy'):
        return installer.plan_install(self.root, self.bin, backend=backend, portable_root=self.bundle)

    def test_default_backend_is_legacy_not_silent_core_switch(self):
        p = self.plan()
        self.assertEqual(p['backend'], 'legacy')
        self.assertIn('scripts/cucp.ps1', p['health_argv'][5].replace('\\', '/'))
        self.assertIn('macro', p['health_argv'])
        self.assertTrue(p['contents']['cucp-launch.ps1'].startswith(b'\xef\xbb\xbf'))
        self.assertEqual(p['contents']['cucp.cmd'].decode('ascii').count('powershell.exe'), 1)
        self.assertIn("'' clone", p['contents']['cucp-launch.ps1'].decode('utf-8-sig'))

    def test_core_and_portable_do_not_depend_on_powershell(self):
        for backend in ('core', 'portable'):
            p = self.plan(backend)
            self.assertEqual(set(p['contents']), {'cucp.cmd'})
            self.assertNotIn('powershell', p['contents']['cucp.cmd'].decode('utf-8').lower())
            self.assertIn('DisableDelayedExpansion', p['contents']['cucp.cmd'].decode('utf-8'))
            self.assertIn('%%bang!', p['contents']['cucp.cmd'].decode('utf-8'))
            self.assertIn('chcp %_CUCP_CP%', p['contents']['cucp.cmd'].decode('utf-8'))
            self.assertEqual(p['system_changes'], [])

    def test_plan_does_not_write_and_backend_must_exist(self):
        self.plan()
        self.assertFalse(self.bin.exists())
        with self.assertRaises(ValueError):
            installer.plan_install(self.root, self.bin, backend='portable')
        with self.assertRaises(ValueError):
            installer.plan_install(self.root, self.bin, backend='unknown')
        (self.root / 'scripts/cucp.ps1').unlink()
        with self.assertRaises(ValueError): self.plan()

    def test_owned_install_reinstall_and_uninstall(self):
        for backend in ('legacy', 'core', 'portable'):
            p = self.plan(backend)
            installer.install(p)
            self.assertEqual(set(x.name for x in self.bin.iterdir()), set(installer.FILES[backend]) | {installer.MANIFEST})
            installer.install(p)
            manifest = installer.read_owned(self.bin)
            self.assertEqual(manifest['backend'], backend)
            sentinel = self.bin / 'user.txt'
            sentinel.write_text('untouched')
            installer.uninstall(self.bin)
            self.assertEqual(sentinel.read_text(), 'untouched')
            sentinel.unlink()

    def test_unmanaged_and_modified_files_are_preserved(self):
        self.bin.mkdir()
        cmd = self.bin / 'cucp.cmd'
        cmd.write_bytes(b'user launcher')
        with self.assertRaises(ValueError): installer.install(self.plan())
        self.assertEqual(cmd.read_bytes(), b'user launcher')
        cmd.unlink()
        installer.install(self.plan())
        cmd.write_bytes(b'edited by user')
        with self.assertRaises(ValueError): installer.uninstall(self.bin)
        with self.assertRaises(ValueError): installer.install(self.plan())
        self.assertEqual(cmd.read_bytes(), b'edited by user')

    def test_corrupt_manifest_rejected_without_file_deletion(self):
        installer.install(self.plan())
        manifest = self.bin / installer.MANIFEST
        for bad in ([], {'schema': installer.SCHEMA, 'backend': [], 'files': {}},
                    {'schema': installer.SCHEMA, 'backend': 'legacy', 'files': None}):
            manifest.write_text(json.dumps(bad))
            with self.assertRaises(ValueError): installer.uninstall(self.bin)
            self.assertTrue((self.bin / 'cucp.cmd').exists())

    def test_backend_change_requires_explicit_uninstall(self):
        installer.install(self.plan())
        with self.assertRaises(ValueError): installer.install(self.plan('core'))
        self.assertEqual(installer.read_owned(self.bin)['backend'], 'legacy')

    def test_publish_failure_restores_owned_files(self):
        p = self.plan()
        installer.install(p)
        before = {x.name: x.read_bytes() for x in self.bin.iterdir()}
        original = installer.os.replace
        count = 0
        def fail_once(source, destination):
            nonlocal count
            count += 1
            if count == 2: raise OSError('fixture write error')
            return original(source, destination)
        with patch.object(installer.os, 'replace', side_effect=fail_once):
            with self.assertRaises(OSError): installer.install(p)
        self.assertEqual({x.name: x.read_bytes() for x in self.bin.iterdir()}, before)

    def test_health_is_bounded_read_only_argv_and_nonfatal(self):
        def run(argv, **kwargs):
            self.assertEqual(kwargs['timeout'], 30)
            self.assertFalse(kwargs.get('shell', False))
            return subprocess.CompletedProcess(argv, 0, stdout='ok health', stderr='')
        self.assertTrue(installer.check_health(self.plan(), run=run)[0])
        def failed(*args, **kwargs): raise OSError('not installed')
        self.assertFalse(installer.check_health(self.plan(), run=failed)[0])

    def test_nonobject_doctor_json_is_nonfatal_warning(self):
        for output in ('[]', 'null', 'true', '"unexpected"', '42'):
            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr='')
            self.assertFalse(installer.check_health(self.plan('core'), run=run)[0])

    def test_cli_no_apply_never_installs_or_runs_health(self):
        with patch('sys.stdout'), patch.object(installer.sys, 'platform', 'win32'), patch.object(installer, 'install') as install, patch.object(installer, 'check_health') as health:
            result = installer.main(['--root', str(self.root), '--bin-dir', str(self.bin)])
        self.assertEqual(result, 0)
        install.assert_not_called(); health.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Requires real Windows cmd decoding and exit propagation')
    def test_windows_core_unicode_paths_argv_and_exit(self):
        installer.install(self.plan('core'))
        args = ['space value', '한글😀', 'a&b', '100%literal', '!bang!', '--allow-live-control']
        # Run only the disposable fixture Python entry, never the actual CUCP backend.
        # cmd.exe parses its /c tail itself. A Python argv list would apply CRT
        # backslash-quote escaping, which is not cmd escaping and breaks &/paths.
        command = '"' + str(self.bin / 'cucp.cmd') + '" ' + ' '.join(chr(34) + arg + chr(34) for arg in args)
        result = subprocess.run('"' + os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe') + '" /d /s /c "' + command + '"', capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(json.loads(result.stdout), args)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell legacy argument forwarding')
    def test_windows_legacy_unicode_paths_argv_and_exit(self):
        installer.install(self.plan())
        args = ['space value', '한글', '--allow-live-control']
        command = '"' + str(self.bin / 'cucp.cmd') + '" ' + ' '.join(chr(34) + arg + chr(34) for arg in args)
        result = subprocess.run('"' + os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe') + '" /d /s /c "' + command + '"', capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(json.loads(result.stdout), args)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires actual Python installer entrypoint')
    def test_windows_installer_compatibility_entrypoint_uses_exact_selected_backend(self):
        # Copy only the compatibility entrypoint, then substitute a harmless Python
        # argument recorder. Nothing runs the real installer or a CUCP backend.
        shutil.copy2(SOURCE.parents[2] / 'install.py', self.root / 'install.py')
        packaging = self.root / 'pcucp-next/packaging'
        packaging.mkdir(parents=True)
        (packaging / 'install_runtime.py').write_text(
            'import json,sys; print(json.dumps(sys.argv[1:],ensure_ascii=True)); sys.exit(37)\n', encoding='utf-8')
        for backend in (None, 'core', 'portable'):
            command = [sys.executable, '-X', 'utf8', str(self.root / 'install.py'),
                       '-PythonExe', sys.executable, '-BinDir', str(self.bin), '-NoPathShim', '-Quiet']
            if backend:
                command += ['-Backend', backend]
            if backend == 'portable':
                command += ['-PortableRoot', str(self.bundle)]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 37, result.stderr)
            forwarded = json.loads(result.stdout)
            self.assertEqual(forwarded[0], '--root')
            # PSScriptRoot expands RUNNER~1 TEMP aliases; verify filesystem identity.
            self.assertTrue(Path(forwarded[1]).samefile(self.root))
            self.assertIn('--apply', forwarded)
            self.assertIn('-NoPathShim', forwarded)
            self.assertIn('-Quiet', forwarded)
            self.assertEqual(forwarded[forwarded.index('-BinDir') + 1], str(self.bin))
            self.assertIn('-PythonExe', forwarded)
            self.assertEqual(forwarded[forwarded.index('-PythonExe') + 1], sys.executable)
            if backend: self.assertEqual(forwarded[forwarded.index('-Backend') + 1], backend)
            if backend == 'portable':
                self.assertEqual(forwarded[forwarded.index('-PortableRoot') + 1], str(self.bundle))
            self.assertFalse(self.bin.exists(), 'Shim fixture must not install anything')
