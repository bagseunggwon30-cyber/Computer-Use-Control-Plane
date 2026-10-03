"""Real production entry -> real module loader -> captured final family entry.

This is startup wiring coverage, separate from kernel/transport parity. Nothing
rewrites the actual public delegates or enables live authority.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures'
SOURCES = ('scripts/cucp.ps1', 'scripts/cucp-legacy-interaction-adapter.ps1',
           'scripts/cucp-legacy-diagnostic-adapter.ps1', 'scripts/cucp-legacy-cdp-adapter.ps1')
FAMILIES = {
    'interaction': {
        'entry': '_Invoke-LegacyInteractionFamily',
        'operations': {
            'find-label': 'FindLabel', 'click-point': 'ClickPoint', 'click-label': 'ClickLabel',
            'safe-type': 'SafeType', 'icon-find': 'IconFind', 'icon-click': 'IconClick',
            'ocr-click': 'OcrClick', 'precision-validate': 'PrecisionValidate',
        },
        'failure_operations': ('find-label',),
    },
    'diagnostics': {
        'entry': '_Invoke-LegacyDiagnosticFamily',
        'operations': {
            'perf': 'Perf', 'diagnose-lag': 'DiagnoseLag', 'health-quick': 'HealthQuick',
            'health-detail': 'HealthDetail', 'log-tail': 'LogTail', 'self-test': 'SelfTest',
            'release-notes': 'ReleaseNotes', 'audit-summary': 'AuditSummary', 'benchmark': 'Benchmark',
        },
        # Retain controls and prove both report routes fail closed during startup.
        'failure_operations': ('perf', 'audit-summary', 'benchmark'),
    },
}
# Values intentionally resemble outer switches and consent flags. They travel
# in a JSON file, then through the main script's named string[] CucpArgs binding.
LITERAL_REST = ['--text', '-AllowLiveControl', '--label', '--confirm-sensitive',
                '--match', '-Brief', '--x', '-20', '--y', '0', '--payload',
                '한글 + ^ % {value}\n"quotes" $(not-a-command)']


def fixture_case(family, operation, exit_code=37):
    spec = FAMILIES[family]
    return dict(family=family, macro=operation, operation=operation,
                wrapper='Invoke-Macro' + spec['operations'][operation], entry=spec['entry'],
                rest=list(LITERAL_REST), exit_code=exit_code)


def run_startup(powershell, case, mode='normal'):
    with tempfile.TemporaryDirectory(prefix='cucp-production-startup-') as temporary:
        root = Path(temporary).resolve()
        shutil.copytree(ROOT / 'scripts', root / 'scripts')
        (root / '.startup-fixture-owner').write_text('owned startup fixture\n', encoding='utf-8')
        for name in ('temp', 'empty-bin', 'profile', 'appdata', 'localappdata'):
            (root / name).mkdir()
        inputs = root / 'case.json'
        request = dict(case, sources={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCES})
        inputs.write_text(json.dumps(request, ensure_ascii=True), encoding='utf-8-sig')
        # Keep standard Windows/PowerShell runtime variables, but remove inherited
        # CUCP provider settings and isolate all ordinary writable/discovery roots.
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith('CUCP_') and key.upper() not in {
                   'PATH', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PSMODULEPATH'}}
        env.update(TEMP=str(root / 'temp'), TMP=str(root / 'temp'), PATH=str(root / 'empty-bin'),
                   USERPROFILE=str(root / 'profile'), APPDATA=str(root / 'appdata'),
                   LOCALAPPDATA=str(root / 'localappdata'),
                   PSModulePath=str(Path(powershell).resolve().parent / 'Modules'),
                   CUCP_NATIVE_HOST=str(root / 'no-native-host.exe'),
                   CUCP_LEGACY_CDP_HOST=str(root / 'no-cdp-host.exe'))
        command = [str(powershell), '-NoProfile', '-NonInteractive', '-File',
                   str(FIXTURES / 'legacy-family-production-startup.ps1'),
                   '-Root', str(root), '-CasePath', str(inputs), '-Mode', mode]
        process = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=45)
        record = root / 'record.jsonl'
        records = [json.loads(line) for line in record.read_text(encoding='utf-8-sig').splitlines()] if record.exists() else []
        return process, records, str(root)


class ProductionStartupChecks:
    """Mixin: only concrete family TestCase classes are discovered by unittest."""
    family = None

    @classmethod
    def setUpClass(cls):
        enabled = json.loads((ROOT / '.github/migration-adapters.json').read_text())['test_adapters']
        if cls.family not in enabled:
            raise unittest.SkipTest('Production startup qualification applies after this family is promoted')
        if sys.platform != 'win32':
            raise unittest.SkipTest('Real main-script startup requires Windows PowerShell 5.1')
        cls.powershell = shutil.which('powershell.exe')
        if not cls.powershell:
            raise AssertionError('Promoted production startup gate requires Windows PowerShell 5.1')

    def test_actual_main_entry_maps_all_promoted_operations_and_literal_argv(self):
        for operation in FAMILIES[self.family]['operations']:
            for exit_code in (0, 37):
                case = fixture_case(self.family, operation, exit_code)
                with self.subTest(operation=operation, exit_code=exit_code):
                    process, records, root = run_startup(self.powershell, case)
                    self.assertEqual(process.returncode, exit_code, process.stderr.decode(errors='replace'))
                    self.assertEqual(len(records), 1, process.stdout.decode(errors='replace') + process.stderr.decode(errors='replace'))
                    record = records[0]
                    self.assertEqual(record['family'], self.family)
                    self.assertEqual(record['operation'], operation)
                    self.assertEqual(record['rest'], case['rest'])
                    self.assertEqual(record['calls'], 1)
                    self.assertEqual(record['loads'], dict(interaction=1, diagnostics=1))
                    self.assertIs(record['allow_live'], False)
                    self.assertIs(record['brief'], False)
                    self.assertEqual(record['cache_seconds'], 0)
                    self.assertIs(record['double'], False)
                    self.assertIs(record['right_click'], False)
                    expected_path = str(Path(root) / 'scripts/cucp.ps1') if self.family == 'interaction' else ''
                    self.assertEqual(record['script_path'], expected_path)
                    audit = Path(root) / 'temp/computer-use-control-plane'
                    self.assertEqual(record['audit_dir'], str(audit))
                    self.assertEqual(record['cache_dir'], str(audit / 'wrapper-cache'))

    def test_missing_support_file_never_reaches_family(self):
        for operation in FAMILIES[self.family]['failure_operations']:
            with self.subTest(operation=operation):
                case = fixture_case(self.family, operation)
                process, records, _ = run_startup(self.powershell, case, 'missing-support')
                self.assertNotEqual(process.returncode, 0)
                self.assertNotEqual(process.returncode, 37)
                self.assertEqual(records, [])

    def test_duplicate_production_support_load_fails(self):
        for operation in FAMILIES[self.family]['failure_operations']:
            with self.subTest(operation=operation):
                case = fixture_case(self.family, operation)
                process, records, _ = run_startup(self.powershell, case, 'duplicate-load')
                self.assertNotEqual(process.returncode, 0)
                self.assertNotEqual(process.returncode, 37)
                self.assertEqual(records, [])
                self.assertIn('Duplicate production support load', process.stderr.decode(errors='replace'))

    def test_native_leaf_is_stopped_before_its_body(self):
        for operation in FAMILIES[self.family]['failure_operations']:
            with self.subTest(operation=operation):
                case = fixture_case(self.family, operation)
                process, records, _ = run_startup(self.powershell, case, 'blocked-provider')
                self.assertEqual(process.returncode, 97, process.stderr.decode(errors='replace'))
                self.assertIn('startup_provider_guard', process.stderr.decode(errors='replace'))
                self.assertEqual(records, [])
