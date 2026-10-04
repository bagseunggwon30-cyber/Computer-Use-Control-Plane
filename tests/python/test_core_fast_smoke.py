"""The 18 core smoke checks, using Python source launchers and published C#.

No build, fallback, input, or elevation occurs in these tests. Missing native
prerequisites skip local checks and fail when CI explicitly requires them.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'pcucp-next/python'
LAUNCHER = SOURCE / 'run_source.py'


class SmokeBase(unittest.TestCase):
    def setUp(self):
        self.owned = tempfile.TemporaryDirectory(prefix='CUCP core smoke 한글 ')
        self.addCleanup(self.owned.cleanup)
        self.folder = Path(self.owned.name)
        self.env = dict(os.environ, PYTHONPATH=str(SOURCE), PYTHONIOENCODING='utf-8',
                        TEMP=str(self.folder), TMP=str(self.folder))

    def run_cli(self, *arguments, launcher=False, env=None):
        command = [sys.executable, '-X', 'utf8'] + ([str(LAUNCHER)] if launcher else ['-m', 'pcucp_cli'])
        result = subprocess.run(command + list(arguments), cwd=ROOT, env=env or self.env,
                                capture_output=True, timeout=45)
        return result.returncode, json.loads(result.stdout.decode('utf-8-sig'))

    def assert_uia(self, code, payload):
        self.assertIn(payload['status'], ('ok', 'partial'))
        if payload['status'] == 'ok':
            self.assertEqual(code, 0)
            self.assertEqual(payload['errors'], [])
        else:
            self.assertNotEqual(code, 0)
            self.assertTrue(payload['errors'])
        self.assertEqual(payload['schema'], 'pcucp.uia-tree/v1')
        self.assertEqual(payload['kind'], 'uia-tree')
        self.assertEqual(payload['route']['primary'], 'dotnet-native-host')
        self.assertIn('count', payload['data'])
        if payload['data']['nodes']:
            self.assertIn('patterns', payload['data']['nodes'][0])


class CoreSourceSmokeTests(SmokeBase):
    def test_multi_runtime_layout(self):
        paths = ['python/run_source.py', *('python/pcucp_cli/' + name + '.py' for name in
                 ('__main__', 'cli', 'find_label', 'native_host', 'ocr', 'planner', 'task_plan')),
                 'dotnet/PcuCp.NativeHost/PcuCp.NativeHost.csproj', 'dotnet/PcuCp.NativeHost/Program.cs',
                 'schemas/command.schema.json', 'schemas/observation.schema.json', 'config/runtime-profile.json']
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((ROOT / 'pcucp-next' / path).is_file())

    def test_legacy_compatibility_path(self):
        self.assertTrue((ROOT / 'scripts/cucp.ps1').is_file())

    def test_language_roles_and_component_paths(self):
        code, payload = self.run_cli('version', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.version/v1')
        self.assertEqual(payload['status'], 'ok')
        for language, role in (('powershell', 'legacy'), ('python', 'session'), ('dotnet', 'Windows')):
            self.assertIn(role, payload['language_roles'][language])
        for component in ('python_cli', 'native_host_project', 'legacy_wrapper'):
            self.assertTrue(payload['components'][component])

    def test_read_only_plan(self):
        code, payload = self.run_cli('plan', '--command', 'windows', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.plan/v1')
        self.assertEqual(payload['command'], 'windows')
        self.assertFalse(payload['safety']['live_control_required'])
        self.assertEqual(payload['route']['primary'], 'dotnet-native-host')
        self.assertEqual(payload['route']['fallback'], 'none')

    def test_missing_native_host_errors_without_fallback(self):
        env = dict(self.env, CUCP_NATIVE_HOST=str(self.folder / 'missing.exe'))
        code, payload = self.run_cli('windows', '--json', env=env)
        self.assertNotEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.native/v1')
        self.assertEqual(payload['status'], 'error')
        self.assertEqual(payload['errors'][0]['code'], 'native_transport_error')
        self.assertIsNone(payload['route']['fallback'])

    def test_task_plan_gates_live_actions(self):
        code, payload = self.run_cli('task-plan', '--type-text', 'hello', '--shortcut', 'ctrl+s', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.task-plan/v1')
        self.assertEqual(payload['route']['primary'], 'python-router')
        self.assertTrue(payload['safety']['live_control_required'])
        self.assertFalse(payload['safety']['default_allow_live_control'])
        self.assertEqual(len(payload['steps']), 2)

    def test_source_launcher_version(self):
        code, payload = self.run_cli('version', '--json', launcher=True)
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.version/v1')

    def test_parseable_schemas_and_config(self):
        for name in ('schemas/command.schema.json', 'schemas/observation.schema.json', 'config/runtime-profile.json'):
            self.assertTrue(json.loads((ROOT / 'pcucp-next' / name).read_text(encoding='utf-8')))

    def test_native_project_framework_and_no_external_packages(self):
        text = (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/PcuCp.NativeHost.csproj').read_text(encoding='utf-8')
        self.assertIn('<TargetFramework>net8.0-windows10.0.19041.0</TargetFramework>', text)
        self.assertNotIn('<PackageReference', text)


class CoreNativeSmokeTests(SmokeBase):
    def setUp(self):
        super().setUp()
        self.host = Path(os.environ.get('CUCP_NATIVE_HOST') or ROOT / 'pcucp-next/bin/native/PcuCp.NativeHost.exe')
        available = (os.name == 'nt' and self.host.is_absolute() and self.host.is_file() and
                     (self.host.suffix.lower() == '.exe' or self.host.suffix.lower() == '.dll' and shutil.which('dotnet')))
        if not available:
            if os.environ.get('CUCP_REQUIRE_CORE_SMOKE') == '1':
                self.fail('Required published Windows native host is unavailable.')
            self.skipTest('Published Windows native host is unavailable; no build attempted.')
        self.env['CUCP_NATIVE_HOST'] = str(self.host)

    def fixture(self):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            if os.environ.get('CUCP_REQUIRE_CORE_SMOKE') == '1':
                self.fail('Pillow is required for the owned OCR fixture.')
            self.skipTest('Pillow is unavailable for the owned OCR fixture.')
        path = self.folder / 'Send Message 한글.png'
        image = Image.new('RGB', (520, 140), 'white')
        font = ImageFont.truetype(str(Path(os.environ['SystemRoot']) / 'Fonts/segoeuib.ttf'), 40)
        ImageDraw.Draw(image).text((24, 36), 'Send Message', fill='black', font=font)
        image.save(path)
        return path

    def windows(self, launcher=False):
        code, payload = self.run_cli('windows', '--json', launcher=launcher)
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.observation/v1')
        self.assertEqual(payload['kind'], 'windows')
        self.assertEqual(payload['route']['primary'], 'dotnet-native-host')
        self.assertIn('count', payload['data'])

    def ocr(self, launcher=False):
        code, payload = self.run_cli('ocr-image', '--path', str(self.fixture()), '--json', launcher=launcher)
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.ocr-image/v1')
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['kind'], 'ocr-image')
        self.assertEqual(payload['route']['primary'], 'dotnet-native-host')
        self.assertRegex(payload['text'], 'Send|Message')

    def test_windows(self):
        self.windows()

    def test_uia_tree(self):
        self.assert_uia(*self.run_cli('uia-tree', '--max-depth', '1', '--json'))

    def test_find_label(self):
        label = '__pcucp_unlikely_label__'
        code, payload = self.run_cli('find-label', '--label', label, '--json')
        self.assertEqual(payload['schema'], 'pcucp.find-label/v1')
        self.assertIn(payload['status'], ('not_found', 'partial'))
        if payload['status'] == 'partial':
            self.assertEqual(code, 3)
            self.assertTrue(payload['errors'])
            self.assertTrue(any(p['status'] == 'partial' for p in payload['providers']))
            self.assertFalse(any(p['status'] == 'error' for p in payload['providers']))
        else:
            self.assertEqual(code, 2)
        self.assertEqual(payload['candidates'], [])
        self.assertEqual(payload['query']['label'], label)
        self.assertEqual(payload['route']['primary'], 'python-router')
        for route in ('dotnet-native-host/windows', 'dotnet-native-host/uia-tree'):
            self.assertIn(route, payload['route']['observations'])
        self.assertIn('uia_node_count', payload)

    def test_ocr_image(self):
        self.ocr()

    def test_ocr_find_text(self):
        code, payload = self.run_cli('ocr-find-text', '--path', str(self.fixture()), '--text', 'Send', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(payload['schema'], 'pcucp.ocr-find-text/v1')
        self.assertEqual(payload['kind'], 'ocr-find-text')
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['route']['primary'], 'python-router')
        self.assertEqual(payload['route']['observation'], 'dotnet-native-host/ocr-image')
        self.assertIn('Send', payload['top']['text'])
        self.assertGreaterEqual(payload['top']['score'], 60)

    def test_source_launcher_windows(self):
        self.windows(launcher=True)

    def test_source_launcher_uia(self):
        self.assert_uia(*self.run_cli('uia-tree', '--max-depth', '1', '--json', launcher=True))

    def test_source_launcher_ocr(self):
        self.ocr(launcher=True)

    def test_published_native_version_without_build(self):
        command = ([shutil.which('dotnet'), str(self.host)] if self.host.suffix.lower() == '.dll' else [str(self.host)])
        result = subprocess.run(command + ['version'], env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.decode('utf-8-sig'))
        self.assertEqual(payload['schema'], 'pcucp.native/v1')
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['kind'], 'version')
        self.assertEqual(payload['data']['component'], 'PcuCp.NativeHost')


if __name__ == '__main__':
    unittest.main()
