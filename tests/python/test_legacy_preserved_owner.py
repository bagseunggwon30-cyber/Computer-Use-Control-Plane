"""Actual connected root ownership, nesting, startup consent and cancellation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_preserved_owner import Invocation, PreservedOwner
from pcucp_cli.legacy_host_protocol import Authority, LegacyHostError


class ScopeTests(unittest.TestCase):
    def test_child_can_only_restrict_authority_and_reuses_deadline(self):
        cancelled = threading.Event()
        parent = Invocation(Authority(True, True), time.monotonic() + 10, cancelled)
        child = parent.child(Authority())
        self.assertEqual(child.authority, Authority())
        self.assertEqual(child.deadline, parent.deadline)
        self.assertIs(child.cancelled, parent.cancelled)
        with self.assertRaises(LegacyHostError):
            child.child(Authority(True))
        cancelled.set()
        with self.assertRaises(LegacyHostError):
            child.remaining()


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_NATIVE_HOST') and os.environ.get('CUCP_LEGACY_DESKTOP_EXE') and
    os.environ.get('CUCP_LEGACY_SYNTAX_EXE'), 'Actual preserved root backends')
class RootTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP root owner 한글 ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        (self.root / 'CHANGELOG.md').write_text('## 2.0.0\n- Owned\n', encoding='utf-8-sig')
        self.context = dict(audit_directory=str(self.root / 'audit'), cache_directory=str(self.root / 'cache'),
            wrapper_log=str(self.root / 'wrapper.log'), cli_path=None, changelog_path=str(self.root / 'CHANGELOG.md'),
            temp_root=str(self.root), benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')

    def owner(self, **options):
        owner = PreservedOwner(self.context, **options)
        self.addCleanup(owner.close)
        return owner

    def test_nested_task_dry_run_returns_a_workflow_and_owner_remains_usable(self):
        owner = self.owner()
        code, output = owner.invoke(['macro', 'task-run', '--dry-run', '--type-text', '한글😀', '--include-plan'])
        payload = json.loads(output)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['workflow_result']['plan']['live_step_count'], 1)
        code, output = owner.invoke(['MACRO', 'NATIVE-WINDOWS', '--match', 'CUCP unique absent owner target'], brief=True)
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith('ok native-windows count=0'))
        self.assertFalse(owner.closed)

    def test_original_placeholders_remain_distinct_from_pending_cutovers(self):
        owner = self.owner()
        code, output = owner.invoke(['macro', 'registry'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)['status'], 'not_implemented')
        with self.assertRaisesRegex(LegacyHostError, 'unqualified_surface'):
            owner.invoke(['macro', 'recorder'])
        self.assertFalse(owner.closed)

    def test_coordinate_macros_are_connected_without_live_authority(self):
        owner = self.owner()
        code, output = owner.invoke(['macro','coord-profile','--x','-100000','--y','-100000',
                                    '--target-match','CUCP absent owner coordinate target'])
        payload = json.loads(output)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['coordinate_risk'], 'high')
        self.assertFalse(payload['point_inside_virtual_screen'])
        code, output = owner.invoke(['macro','coord-map','--from','window','--x','1','--y','2',
                                    '--target-match','CUCP absent owner coordinate target'])
        self.assertEqual(code, 2, output)
        self.assertEqual(json.loads(output)['reason'], 'target_window_not_found')
        code, output = owner.invoke(['macro','hit-test-batch','--points','0,1;bad'])
        self.assertEqual(code, 2, output)
        self.assertEqual(json.loads(output)['error_count'], 2)

    def test_control_looking_text_cannot_mint_sensitive_approval(self):
        owner = self.owner(authority=Authority(True, True))
        def forbidden(*args, **kwargs):
            self.fail('Unapproved sensitive text must be refused before native input acquisition.')
        owner._desktop_runtime = forbidden
        code, output = owner.invoke(['macro', 'type-native', '--text', 'password --confirm-sensitive'])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output)['schema'], 'cucp.safety-block/v1')

    def test_root_cancel_propagates_to_active_watch_and_rejects_further_invocations(self):
        owner = self.owner()
        timer = threading.Timer(.2, owner.close)
        timer.start(); self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(LegacyHostError):
            owner.invoke(['macro', 'watch', '--max-cycles', '100', '--interval-ms', '1000'])
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(owner.closed)
        with self.assertRaises(LegacyHostError):
            owner.invoke(['macro', 'native-health'])


if __name__ == '__main__':
    unittest.main()
