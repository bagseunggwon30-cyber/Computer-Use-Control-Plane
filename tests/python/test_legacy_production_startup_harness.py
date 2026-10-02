"""Portable fixture-shape checks, not a Windows main-entry execution claim."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import legacy_production_startup as harness


class ProductionStartupHarnessTests(unittest.TestCase):
    def test_exact_closed_operation_sets_exclude_retained_measurement_routes(self):
        self.assertEqual(set(harness.FAMILIES['interaction']['operations']), {
            'find-label', 'click-point', 'click-label', 'safe-type', 'icon-find',
            'icon-click', 'ocr-click', 'precision-validate'})
        self.assertEqual(set(harness.FAMILIES['diagnostics']['operations']), {
            'perf', 'diagnose-lag', 'health-quick', 'health-detail', 'log-tail', 'self-test', 'release-notes'})
        for family in harness.FAMILIES:
            for operation in harness.FAMILIES[family]['operations']:
                case = harness.fixture_case(family, operation)
                self.assertEqual(json.loads(json.dumps(case)), case)
                self.assertEqual(case['rest'], harness.LITERAL_REST)
                self.assertNotIn(operation, ('benchmark', 'audit-summary'))

    def test_typed_bootstrap_is_visible_and_does_not_ast_install_public_delegates(self):
        bootstrap = (harness.FIXTURES / 'legacy-family-production-startup.ps1').read_text(encoding='utf-8-sig')
        probe = (harness.FIXTURES / 'legacy-family-production-probe.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('-CucpArgs $argv', bootstrap)
        self.assertIn('-AllowLiveControl:$false', bootstrap)
        self.assertNotIn('Set-PSBreakpoint', bootstrap)
        self.assertIn('Startup function preimage changed:', bootstrap)
        self.assertIn('Copied production source hash changed', bootstrap)
        self.assertIn('[Environment]::Exit(97)', bootstrap)
        self.assertNotIn('function Invoke-Macro', probe)
        self.assertNotIn('[scriptblock]::Create', bootstrap)
        self.assertIn('Replace-StartupDefinition $path $module.entry', bootstrap)

    def test_subprocess_uses_fixed_bootstrap_and_owned_provider_roots(self):
        case = harness.fixture_case('interaction', 'safe-type')
        observed = {}

        def capture(argv, *, cwd, env, capture_output, timeout):
            root = Path(cwd)
            self.assertTrue((root / '.startup-fixture-owner').is_file())
            observed['case'] = json.loads((root / 'case.json').read_text(encoding='utf-8-sig'))
            sources = observed['case'].pop('sources')
            self.assertEqual(set(sources), set(harness.SOURCES))
            self.assertTrue(all(len(value) == 64 for value in sources.values()))
            self.assertEqual(observed['case'], case)
            self.assertFalse(any(value in argv for value in case['rest']))
            self.assertEqual(env['TEMP'], str(root / 'temp'))
            self.assertEqual(env['TMP'], env['TEMP'])
            self.assertEqual(env['PATH'], str(root / 'empty-bin'))
            self.assertFalse(Path(env['CUCP_NATIVE_HOST']).exists())
            self.assertEqual(timeout, 45)
            self.assertTrue(capture_output)
            return harness.subprocess.CompletedProcess(argv, 37, b'', b'')

        with patch.object(harness.subprocess, 'run', side_effect=capture):
            process, records, root = harness.run_startup('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe', case)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(records, [])
        self.assertFalse(Path(root).exists())
