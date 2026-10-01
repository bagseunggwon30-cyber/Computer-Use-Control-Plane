"""Cross-platform guard wiring tests; Win32 handle inheritance needs Windows QA."""
import unittest
from unittest.mock import MagicMock, patch
from pcucp_cli import native_host
from pcucp_cli.worker_lifetime import guarded_launch

class WorkerLifetimeTests(unittest.TestCase):
    def test_windows_cancel_uses_owned_process_only(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(native_host.os, 'name', 'nt'), patch.object(native_host.subprocess, 'run') as run:
            native_host._terminate_process_tree(process)
        process.kill.assert_called_once_with()
        run.assert_not_called()

    def test_exited_windows_worker_is_not_killed_by_reused_pid(self):
        process = MagicMock()
        process.poll.return_value = 0
        with patch.object(native_host.os, 'name', 'nt'), patch.object(native_host.subprocess, 'run') as run:
            native_host._terminate_process_tree(process)
        process.kill.assert_not_called()
        run.assert_not_called()

    def test_posix_launch_keeps_isolated_group(self):
        with patch('pcucp_cli.worker_lifetime.os.name', 'posix'):
            with guarded_launch(['host', 'serve']) as (command, kwargs):
                self.assertEqual(command, ['host', 'serve'])
                self.assertEqual(kwargs, {'start_new_session': True})

    def test_windows_guard_uses_only_sync_inherited_handle_and_closes_local_copy(self):
        import ctypes
        kernel = MagicMock()
        kernel.OpenProcess.return_value = 123
        startup = MagicMock()
        with patch('pcucp_cli.worker_lifetime.os.name', 'nt'), \
             patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch('pcucp_cli.worker_lifetime.subprocess.STARTUPINFO', return_value=startup, create=True), \
             patch('pcucp_cli.worker_lifetime.subprocess.CREATE_NEW_PROCESS_GROUP', 512, create=True):
            with guarded_launch(['worker', 'serve']) as (command, kwargs):
                self.assertEqual(command[-2:], ['--parent-handle', '123'])
                self.assertEqual(startup.lpAttributeList, {'handle_list': [123]})
                self.assertTrue(kwargs['close_fds'])
                self.assertEqual(kernel.OpenProcess.call_args.args[:2], (0x00100000, True))
                kernel.CloseHandle.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(123)

    def test_windows_guard_failure_is_not_unguarded_fallback(self):
        import ctypes
        kernel = MagicMock()
        kernel.OpenProcess.return_value = 0
        with patch('pcucp_cli.worker_lifetime.os.name', 'nt'), \
             patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(ctypes, 'get_last_error', return_value=5, create=True):
            with self.assertRaises(OSError):
                with guarded_launch(['worker']):
                    self.fail('Guard failure allowed worker launch')
