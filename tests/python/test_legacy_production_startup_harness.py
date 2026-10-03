"""Portable fixture-shape checks, not a Windows main-entry execution claim."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import legacy_production_startup as harness


class ProductionStartupHarnessTests(unittest.TestCase):
    def test_exact_closed_operation_sets_include_audit_and_exclude_retained_benchmark(self):
        self.assertEqual(set(harness.FAMILIES['interaction']['operations']), {
            'find-label', 'click-point', 'click-label', 'safe-type', 'icon-find',
            'icon-click', 'ocr-click', 'precision-validate'})
        self.assertEqual(set(harness.FAMILIES['diagnostics']['operations']), {
            'perf', 'diagnose-lag', 'health-quick', 'health-detail', 'log-tail', 'self-test',
            'release-notes', 'audit-summary'})
        for family in harness.FAMILIES:
            for operation in harness.FAMILIES[family]['operations']:
                case = harness.fixture_case(family, operation)
                self.assertEqual(json.loads(json.dumps(case)), case)
                self.assertEqual(case['rest'], harness.LITERAL_REST)
                self.assertNotEqual(operation, 'benchmark')
        audit = harness.fixture_case('diagnostics', 'audit-summary')
        self.assertEqual(audit['wrapper'], 'Invoke-MacroAuditSummary')
        self.assertEqual(audit['entry'], '_Invoke-LegacyDiagnosticFamily')

    def test_failure_controls_keep_original_routes_and_explicitly_exercise_audit(self):
        class Checks(harness.ProductionStartupChecks, unittest.TestCase):
            powershell = 'unused-powershell.exe'

        controls = {
            'missing-support': ('test_missing_support_file_never_reaches_family', 1, b''),
            'duplicate-load': ('test_duplicate_production_support_load_fails', 1,
                               b'Duplicate production support load'),
            'blocked-provider': ('test_native_leaf_is_stopped_before_its_body', 97,
                                 b'startup_provider_guard:Invoke-NativeHelper'),
        }
        for family, operations in (('interaction', ('find-label',)),
                                   ('diagnostics', ('perf', 'audit-summary'))):
            self.assertEqual(harness.FAMILIES[family]['failure_operations'], operations)
            for mode, (method, exit_code, stderr) in controls.items():
                with self.subTest(family=family, mode=mode):
                    check = Checks(method)
                    check.family = family
                    process = harness.subprocess.CompletedProcess([], exit_code, b'', stderr)
                    with patch.object(harness, 'run_startup', return_value=(process, [], 'unused-root')) as run:
                        getattr(check, method)()
                    self.assertEqual(run.call_count, len(operations))
                    self.assertEqual([call.args for call in run.call_args_list], [
                        (check.powershell, harness.fixture_case(family, operation), mode)
                        for operation in operations])

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
