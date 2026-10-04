"""Execution acquisition gates and actual Windows coordinator integration."""
import json
import os
from pathlib import Path
import sys
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_execution_provider import ExecutionProvider
from pcucp_cli.legacy_execution_runtime import ExecutionRuntime
from pcucp_cli.legacy_host_protocol import Authority, Effect, LegacyHostError
from pcucp_cli.legacy_history import SmartClickHistory
from pcucp_cli.legacy_native_desktop import DesktopSession
from pcucp_cli.legacy_planning_runtime import PlanningRuntime


def effect(kind, name='', argv=(), data=None, live=False, confirm=False):
    return Effect(kind, name, tuple(argv), data, live, False, False, confirm)


class EffectBoundaryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP execution 한글 ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.provider = ExecutionProvider(operation='watch', rest=[], authority=Authority(), cache_directory=self.root)

    def test_native_argv_and_capture_paths_cannot_expand_the_owned_surface(self):
        descriptors = [effect('Native', argv=['-Action', 'type', '-Text', 'x']),
            effect('Native', argv=['-Action', 'focused', '-AllowLiveControl', 'true']),
            effect('Native', argv=['-Action', 'uia-find', '-Label', 'x', '-Label', 'y']),
            effect('Native', argv=['-Action', 'screenshot', '-OutPath', str(self.root / 'unowned.png')]),
            effect('RemoveFile', data=str(self.root / 'unowned.png')),
            effect('SendEscape', live=True, confirm=True), effect('Diagnostic', name='ReadText', data={}),
            effect('Clock', name='elapsed', data={'scope': 'total'})]
        for descriptor in descriptors:
            with self.subTest(descriptor=descriptor), self.assertRaises(LegacyHostError):
                self.provider.validate(descriptor)

    def test_capture_ownership_is_acquired_before_use_and_cleanup(self):
        descriptor = effect('CachePath', name='smartclick-before', data='123456-789')
        self.provider.validate(descriptor)
        path = self.provider.dispatch(descriptor)
        Path(path).write_bytes(b'owned')
        for descriptor in (effect('FileExists', data=path), effect('RemoveFile', data=path)):
            self.provider.validate(descriptor)
            self.provider.dispatch(descriptor)
        self.assertFalse(Path(path).exists())

    def test_sleep_stops_when_an_ancestor_cancels(self):
        cancelled = threading.Event()
        self.provider.bind_session(time.monotonic() + 5, cancelled)
        timer = threading.Timer(.05, cancelled.set)
        timer.start(); self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(LegacyHostError):
            self.provider.dispatch(effect('Sleep', data=1000))
        self.assertLess(time.monotonic() - started, .5)

    def test_history_ties_case_matching_malformed_lines_and_rotation(self):
        history = SmartClickHistory(self.root, maximum=5)
        history.append('Save', 'Editor', 'UIA', True, 1)
        history.append('save', 'editor', 'OCR', True, 2)
        history.append('save', 'editor', 'uia', False, 3)
        self.assertEqual(history.pick('SAVE', 'EDITOR'), 'OCR')
        with history.path.open('ab') as stream:
            stream.write(b'invalid\n')
        self.assertEqual(history.stats()['total'], 3)
        history.append('save', 'editor', 'uia', True, 4)
        self.assertEqual(history.pick('save', 'editor'), 'uia')
        for number in range(6):
            history.append('x' * 200000, 'editor', 'UIA', True, number)
        self.assertEqual(history.stats()['total'], 4)


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_LEGACY_SYNTAX_EXE') and os.environ.get('CUCP_LEGACY_DESKTOP_EXE') and
    os.environ.get('CUCP_NATIVE_HOST'), 'Explicit actual Windows execution backends')
class ActualExecutionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP actual execution 한글 ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.children = []

    def child(self, descriptor, provider):
        self.children.append(descriptor)
        argv = list(descriptor.argv)
        if argv[:2] == ['macro', 'native-windows']:
            result = DesktopSession(authority=Authority(), timeout_s=provider.remaining(), cancelled=provider.cancelled).run(
                ['-Action', 'windows', '-Match', 'CUCP unique absent workflow target'])
            return dict(exit=result['ExitCode'], raw=result['Raw'], json=result['Json'])
        if argv[:2] == ['macro', 'workflow-run']:
            result = self.runtime(authority=provider.authority.restrict(descriptor.live, descriptor.confirm_sensitive),
                parent_deadline=provider.deadline, parent_cancelled=provider.cancelled).run('workflow-run', argv[2:])
            return dict(exit=result['exit'], raw=json.dumps(result['payload']), json=result['payload'])
        self.assertIn(argv[1], {'task-plan', 'form-plan', 'smart-plan'})
        runtime = PlanningRuntime(culture='en-US', parent_deadline=provider.deadline, cancelled=provider.cancelled,
            child=lambda command, owner: self.child(effect('Child', argv=command), owner), audit_directory=self.root / 'audit')
        result = runtime.run(argv[1], argv[2:])
        return dict(exit=result['exit'], raw=json.dumps(result['payload']), json=result['payload'])

    def runtime(self, **kwargs):
        return ExecutionRuntime(audit_directory=self.root / 'audit', cache_directory=self.root / 'cache', child=self.child, **kwargs)

    def test_all_seven_original_coordinators_run_through_python_ports(self):
        cases = [
            ('workflow-run', ['--dry-run', '--step', 'macro windows'], Authority(), 0),
            ('task-run', ['--dry-run', '--type-text', 'ordinary'], Authority(), 0),
            ('form-run', ['--dry-run', '--field', 'Absent=ordinary', '--match', 'CUCP unique absent form target'], Authority(), 3),
            ('watch', ['--max-cycles', '1'], Authority(), 0),
            ('recovery-plan', ['--match', 'CUCP unique absent recovery target'], Authority(), 0),
            ('recovery-run', ['--dry-run', '--match', 'CUCP unique absent recovery target'], Authority(), 0),
            ('smart-click', ['--label', 'CUCP absent label', '--match', 'CUCP unique absent smart target', '--no-history'], Authority(True), 2),
        ]
        for operation, rest, authority, expected in cases:
            with self.subTest(operation=operation):
                result = self.runtime(authority=authority).run(operation, rest, brief=operation == 'smart-click')
                self.assertEqual(result['exit'], expected, result['payload'])
                if operation == 'smart-click':
                    self.assertIsNone(result['payload'])
                    self.assertFalse(result['emit_json'])
                else:
                    self.assertEqual(result['payload']['schema'], 'cucp.' + operation + '/v1')

    def test_real_read_only_workflow_child_and_audit_keep_authority(self):
        result = self.runtime().run('workflow-run', ['--step', 'macro native-windows', '--include-plan'])
        self.assertEqual(result['exit'], 0, result['payload'])
        self.assertEqual(result['payload']['executed_count'], 1)
        self.assertTrue(self.children and not self.children[0].live and not self.children[0].confirm_sensitive)
        record = json.loads((self.root / 'audit/trajectory.ndjson').read_text(encoding='utf-8-sig'))
        self.assertEqual(record['kind'], 'workflow-run')

    def test_live_workflow_without_startup_permission_never_dispatches_child(self):
        with self.assertRaises(LegacyHostError):
            self.runtime().run('workflow-run', ['--step', 'macro type-native --text ordinary'])
        self.assertEqual(self.children, [])

    def test_parent_cancellation_ends_watch_without_waiting_for_next_cycle(self):
        cancelled = threading.Event()
        timer = threading.Timer(.1, cancelled.set)
        timer.start(); self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(LegacyHostError):
            self.runtime(parent_cancelled=cancelled).run('watch', ['--max-cycles', '100', '--interval-ms', '1000'])
        self.assertLess(time.monotonic() - started, 1.5)

    def test_read_only_task_preset_keeps_generated_workflow_without_launching_app(self):
        runtime = PlanningRuntime(audit_directory=self.root / 'audit',
            child=lambda command, owner: self.child(effect('Child', argv=command), owner))
        result = runtime.run('task-preset', ['--kind', 'document', '--text', '한글😀'])
        self.assertEqual(result['exit'], 0)
        self.assertEqual(result['payload']['task_plan']['live_step_count'], 2)
        self.assertEqual(result['payload']['task_plan']['recommended_command'][:2], ['macro', 'workflow-run'])
        self.assertTrue(all(not child.live for child in self.children))

    def test_cancellation_closes_owned_cdp_wire_and_never_starts_native_fallback(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen(8); listener.settimeout(.05)
        stop, cancelled, received = threading.Event(), threading.Event(), threading.Event()
        connections, times = [], []
        def server():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                    connections.append(connection)
                    connection.settimeout(.1)
                    try:
                        request = connection.recv(4096)
                        if request.startswith(b'GET '):
                            # Cancel only after an actual owned HTTP request.
                            times.append(time.monotonic()); received.set(); cancelled.set()
                    except socket.timeout:
                        pass
                    # Deliberately provide no HTTP response bytes.
                except socket.timeout:
                    continue
                except OSError:
                    return
        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        def cleanup():
            stop.set(); listener.close(); thread.join(.5)
            for connection in connections:
                connection.close()
        self.addCleanup(cleanup)
        def forbidden_native(argv, provider):
            self.fail('Cancelled CDP read must not start a native fallback: ' + repr(argv))
        runtime = PlanningRuntime(audit_directory=self.root / 'audit', cancelled=cancelled)
        # CDP is an allowed fixed read. Guard against later UIA/OCR fallback.
        original = runtime._native
        runtime._native = lambda argv: original(argv) if argv[1].startswith('cdp-') else forbidden_native(argv, runtime)
        with self.assertRaises(LegacyHostError):
            runtime.run('smart-plan', ['--label', 'owned', '--cdp-port', str(listener.getsockname()[1])])
        self.assertTrue(received.is_set(), 'Must reach the owned HTTP read, not cancel during a cold kernel startup.')
        self.assertLess(time.monotonic() - times[0], 1.2)


if __name__ == '__main__':
    unittest.main()
