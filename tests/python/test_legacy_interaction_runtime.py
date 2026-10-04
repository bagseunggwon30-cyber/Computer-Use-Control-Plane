"""Interaction effect ownership and actual missing-target root paths."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from pcucp_cli.legacy_host_protocol import Authority, Effect, LegacyHostError
from pcucp_cli.legacy_interaction_provider import InteractionProvider
from pcucp_cli.legacy_preserved_owner import PreservedOwner


def effect(kind, *, argv=(), data=None, live=False):
    return Effect(kind, '', tuple(argv), data, live, False, False, False)


class OwnershipTests(unittest.TestCase):
    def test_unacquired_observation_and_native_scope_are_refused(self):
        provider = InteractionProvider(operation='icon-click', rest=[], authority=Authority(True))
        with self.assertRaises(LegacyHostError):
            provider.validate(effect('Cucp', argv=['act', 'click', '--x', '1', '--y', '1', '--after', 'unowned'], live=True))
        with self.assertRaises(LegacyHostError):
            provider.validate(effect('Native', argv=['-Action', 'type', '-Text', 'owned'], live=True))
        provider.observations.add('owned')
        provider.validate(effect('Cucp', argv=['act', 'click', '--x', '1', '--y', '1', '--after', 'owned'], live=True))

    def test_unqueried_cache_write_and_unscored_anchor_append_are_refused(self):
        provider = InteractionProvider(operation='click-point', rest=[], authority=Authority(True))
        with self.assertRaises(LegacyHostError):
            provider.validate(effect('PointCacheWrite', data=dict(key='a' * 32, payload={})))
        with self.assertRaises(LegacyHostError):
            provider.validate(effect('AnchorAppend', data=dict(record={})))
        with self.assertRaises(LegacyHostError):
            provider.validate(effect('Native', argv=['-Action', 'click', '-X', '1', '-Y', '1'], live=False))


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_NATIVE_HOST') and os.environ.get('CUCP_LEGACY_DESKTOP_EXE'),
    'Actual Windows interaction root')
class ActualInteractionTests(unittest.TestCase):
    def test_missing_targets_preserve_all_connected_interaction_reports_without_input(self):
        with tempfile.TemporaryDirectory(prefix='CUCP interaction root 한글 ') as folder:
            root = Path(folder).resolve()
            context = dict(audit_directory=str(root / 'audit'), cache_directory=str(root / 'cache'), wrapper_log=str(root / 'wrapper.log'),
                cli_path=None, changelog_path=str(root / 'CHANGELOG.md'), temp_root=str(root),
                benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')
            owner = PreservedOwner(context, authority=Authority(True))
            self.addCleanup(owner.close)
            original = owner._desktop_runtime
            def desktop(scope, **ports):
                runtime = original(scope, **ports)
                native = runtime.native
                def guarded(argv, authority, provider):
                    self.assertNotIn(argv[1], {'click', 'focus', 'type', 'shortcut'}, 'Negative target fixture must not dispatch input.')
                    return native(argv, authority, provider)
                runtime.native = guarded
                return runtime
            owner._desktop_runtime = desktop
            target = 'CUCP absent fixture 5e6cc951-aa24-4b49-8a41-1fe685949a12'
            # The retained affordance reader falls back to the desktop root
            # when a title is absent; icon-find may therefore find a candidate.
            cases = [('icon-find', ['--label', 'Absent', '--window', target], (0, 2)),
                ('click-point', ['--x', '1', '--y', '1', '--target-match', target], 3),
                ('safe-type', ['--text', 'owned', '--target-match', target], 2),
                ('ocr-click', ['--text', 'owned', '--target-match', target], 2),
                ('precision-validate', ['--x', '1', '--y', '1', '--target-match', target], 2)]
            for name, args, expected in cases:
                with self.subTest(name=name):
                    code, output = owner.invoke(['macro', name, *args], brief=True)
                    self.assertIn(code, expected if type(expected) is tuple else (expected,))
                    self.assertIn(name, output)


if __name__ == '__main__':
    unittest.main()
