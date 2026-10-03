"""Routing policy contracts for core commands and explicitly isolated legacy routes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next' / 'python'))
from pcucp_cli.planner import plan_command
from pcucp_cli.registry import COMMANDS, capabilities


class PlannerTests(unittest.TestCase):
    def test_unknown_commands_fail_closed(self):
        result = plan_command('some-new-command', ['--arg', 'value'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['route']['primary'], 'blocked')
        self.assertEqual(result['route']['fallback'], 'none')
        self.assertTrue(result['safety']['live_control_required'])
        self.assertIn('unknown_command', result['errors'])

    def test_launch_close_and_js_evaluation_are_mutations(self):
        for command in ('app-launch', 'app-close', 'cdp-eval', 'cdp-click', 'uia-set-value', 'focus'):
            with self.subTest(command=command):
                result = plan_command(command)
                self.assertEqual(result['status'], 'ok')
                self.assertTrue(result['safety']['live_control_required'])
                self.assertFalse(result['safety']['default_allow_live_control'])
                self.assertEqual(COMMANDS[command].effect, 'write')

    def test_observations_do_not_require_live_control(self):
        for command in ('windows', 'uia-tree', 'observe', 'screenshot', 'privileges'):
            with self.subTest(command=command):
                result = plan_command(command)
                self.assertEqual(result['status'], 'ok')
                self.assertFalse(result['safety']['live_control_required'])
                self.assertEqual(result['route']['fallback'], 'none')

    def test_retired_legacy_names_fail_closed_without_fallback(self):
        for command in ('safe-type', 'vision-click', 'clipboard', 'goal'):
            result = plan_command(command)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['route']['primary'], 'blocked')
            self.assertEqual(result['route']['fallback'], 'none')
            self.assertNotIn(command, {item['name'] for item in capabilities()})

    def test_migrated_cdp_requires_explicit_optional_adapter_and_live_eval(self):
        result = plan_command('cdp-eval')
        self.assertEqual(result['route']['primary'], 'python-cdp-adapter')
        self.assertTrue(result['safety']['live_control_required'])
        self.assertTrue(COMMANDS['cdp-eval'].available_in_engine)

    def test_normalization_does_not_bypass_mutation_classification(self):
        result = plan_command(' APP_LAUNCH ')
        self.assertEqual(result['command'], 'app-launch')
        self.assertTrue(result['safety']['live_control_required'])

    def test_batch_plan_is_conservative_until_steps_known(self):
        result = plan_command('batch')
        self.assertTrue(result['safety']['live_control_required'])
        self.assertFalse(result['safety']['default_allow_live_control'])


if __name__ == '__main__':
    unittest.main()
