"""Deterministic fixture lifecycle tests: no browser, network, or live input."""
from contextlib import ExitStack
import errno
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import ANY, Mock, call, patch

import test_cdp_browser as fixture


class BrowserFixtureCleanupTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.TemporaryDirectory(prefix='cucp-cleanup-test-')
        self.addCleanup(self.parent.cleanup)
        self.root = Path(self.parent.name) / 'owned'
        self.profile = self.root / 'profile' / 'Default'
        self.profile.mkdir(parents=True)
        self.process = Mock()
        self.process.poll.return_value = 0

    def error(self, code=errno.ENOTEMPTY, filename=None):
        return OSError(code, os.strerror(code), str(filename or self.profile))

    def fail_removal(self, error):
        def remove(_root, *, onerror):
            onerror(os.rmdir, error.filename, (type(error), error, error.__traceback__))
        return remove

    def test_success_removes_owned_directory_without_sleep(self):
        with patch.object(fixture.time, 'sleep') as sleep:
            fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertFalse(self.root.exists())
        self.process.poll.assert_called_once_with()
        sleep.assert_not_called()

    def test_transient_late_profile_entry_retries_real_rmtree(self):
        # Add a file after rmtree scanned Default but before its rmdir. This
        # deterministically produces the CI errno without a browser or thread.
        rmdir = os.rmdir
        injected = False

        def late_entry(path, *args, **kwargs):
            nonlocal injected
            if Path(path).name == 'Default' and not injected:
                (self.profile / 'late-write').write_text('owned fixture')
                injected = True
            return rmdir(path, *args, **kwargs)

        with patch.object(fixture.os, 'rmdir', side_effect=late_entry), \
                patch.object(fixture.time, 'sleep') as sleep:
            fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertTrue(injected)
        self.assertFalse(self.root.exists())
        sleep.assert_called_once()
        self.assertLessEqual(sleep.call_args.args[0], .05)

    def test_persistent_enotempty_is_bounded_and_propagates(self):
        error = self.error()
        with patch.object(fixture.shutil, 'rmtree', side_effect=self.fail_removal(error)) as remove, \
                patch.object(fixture.time, 'monotonic', return_value=0), \
                patch.object(fixture.time, 'sleep') as sleep:
            with self.assertRaises(OSError) as raised:
                fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertIs(raised.exception, error)
        self.assertEqual(remove.call_count, 20)
        self.assertEqual(sleep.call_count, 19)
        self.assertTrue(self.root.exists())

    def test_basename_error_uses_qualified_callback_path(self):
        error = OSError(errno.ENOTEMPTY, 'profile changed', 'Default')
        remove = shutil.rmtree
        attempts = 0

        def basename_failure(root, *, onerror):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                onerror(os.rmdir, str(self.profile), (type(error), error, None))
            else:
                remove(root, onerror=onerror)

        with patch.object(fixture.shutil, 'rmtree', side_effect=basename_failure), \
                patch.object(fixture.time, 'sleep') as sleep:
            fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertEqual(attempts, 2)
        self.assertEqual(error.filename, 'Default')
        sleep.assert_called_once()
        self.assertFalse(self.root.exists())

    def test_profile_filename_without_qualified_callback_never_retries(self):
        error = self.error()
        with patch.object(fixture.shutil, 'rmtree', side_effect=error) as remove, \
                patch.object(fixture.time, 'sleep') as sleep:
            with self.assertRaises(OSError) as raised:
                fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertIs(raised.exception, error)
        remove.assert_called_once_with(self.root, onerror=ANY)
        sleep.assert_not_called()

    def test_cleanup_deadline_propagates_before_retry(self):
        error = self.error()
        with patch.object(fixture.shutil, 'rmtree', side_effect=self.fail_removal(error)) as remove, \
                patch.object(fixture.time, 'monotonic', side_effect=[0, 1]), \
                patch.object(fixture.time, 'sleep') as sleep:
            with self.assertRaises(OSError) as raised:
                fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertIs(raised.exception, error)
        remove.assert_called_once_with(self.root, onerror=ANY)
        sleep.assert_not_called()

    def test_unrelated_errors_and_paths_never_retry(self):
        for error in (self.error(errno.EACCES), self.error(errno.EBUSY),
                      OSError(errno.ENOTEMPTY, 'no filename'),
                      self.error(filename=self.root),
                      self.error(filename=self.root / 'profile-other' / 'Default'),
                      self.error(filename=self.root / 'profile' / '..' / 'other'),
                      self.error(filename=Path(self.parent.name) / 'unrelated' / 'profile')):
            with self.subTest(error=error), \
                    patch.object(fixture.shutil, 'rmtree', side_effect=self.fail_removal(error)) as remove, \
                    patch.object(fixture.time, 'sleep') as sleep:
                with self.assertRaises(OSError) as raised:
                    fixture._cleanup_owned_browser_directory(self.root, self.process)
                self.assertIs(raised.exception, error)
                remove.assert_called_once_with(self.root, onerror=ANY)
                sleep.assert_not_called()

    def test_expired_deadline_after_sleep_prevents_another_removal(self):
        error = self.error()
        with patch.object(fixture.shutil, 'rmtree', side_effect=self.fail_removal(error)) as remove, \
                patch.object(fixture.time, 'monotonic', side_effect=[0, .98, 1]), \
                patch.object(fixture.time, 'sleep') as sleep:
            with self.assertRaises(OSError) as raised:
                fixture._cleanup_owned_browser_directory(self.root, self.process)
        self.assertIs(raised.exception, error)
        remove.assert_called_once_with(self.root, onerror=ANY)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], .02)

    def test_running_child_preserves_directory_without_deletion(self):
        self.process.poll.return_value = None
        with patch.object(fixture.shutil, 'rmtree') as remove, \
                patch.object(fixture.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'still running'):
                fixture._cleanup_owned_browser_directory(self.root, self.process)
        remove.assert_not_called()
        sleep.assert_not_called()
        self.assertTrue(self.root.exists())

    def test_partial_setup_without_child_cleans_directory(self):
        fixture._cleanup_owned_browser_directory(self.root, None)
        self.assertFalse(self.root.exists())

    def test_partial_setup_without_child_never_retries(self):
        error = self.error()
        with patch.object(fixture.shutil, 'rmtree', side_effect=self.fail_removal(error)) as remove, \
                patch.object(fixture.time, 'sleep') as sleep:
            with self.assertRaises(OSError) as raised:
                fixture._cleanup_owned_browser_directory(self.root, None)
        self.assertIs(raised.exception, error)
        remove.assert_called_once_with(self.root, onerror=ANY)
        sleep.assert_not_called()

    def test_exit_stack_reaps_exact_child_before_directory_cleanup(self):
        events = []
        self.process.poll.side_effect = lambda: None if 'wait' not in events else 0
        self.process.terminate.side_effect = lambda: events.append('terminate')
        self.process.wait.side_effect = lambda timeout: events.append('wait')
        remove = shutil.rmtree

        def checked_remove(root, **kwargs):
            events.append('remove')
            self.assertEqual(events, ['adapter-close', 'terminate', 'wait', 'remove'])
            remove(root, **kwargs)

        with patch.object(fixture.shutil, 'rmtree', side_effect=checked_remove):
            with ExitStack() as resources:
                resources.callback(fixture._cleanup_owned_browser_directory, self.root, self.process)
                resources.callback(fixture._stop_owned_browser, self.process)
                resources.callback(events.append, 'adapter-close')
        self.process.wait.assert_called_once_with(timeout=5)
        self.process.kill.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_stop_timeout_remains_observable_and_preserves_directory(self):
        self.process.poll.return_value = None
        error = subprocess.TimeoutExpired('owned fixture', 5)
        self.process.wait.side_effect = error
        with patch.object(fixture.shutil, 'rmtree') as remove:
            with self.assertRaisesRegex(RuntimeError, 'still running') as raised:
                with ExitStack() as resources:
                    resources.push(lambda _type, error, _tb:
                                   fixture._cleanup_owned_browser_directory(self.root, self.process, error))
                    resources.callback(fixture._stop_owned_browser, self.process)
        self.assertIs(raised.exception.__cause__, error)
        self.process.terminate.assert_called_once_with()
        self.process.kill.assert_called_once_with()
        self.assertEqual(self.process.wait.call_args_list, [call(timeout=5), call(timeout=5)])
        remove.assert_not_called()
        self.assertTrue(self.root.exists())

    def test_stop_kill_fallback_waits_for_exact_child(self):
        self.process.poll.return_value = None
        self.process.wait.side_effect = [subprocess.TimeoutExpired('owned fixture', 5), 0]
        fixture._stop_owned_browser(self.process)
        self.process.terminate.assert_called_once_with()
        self.process.kill.assert_called_once_with()
        self.assertEqual(self.process.wait.call_args_list, [call(timeout=5), call(timeout=5)])

    def test_stop_already_reaped_child_does_not_signal(self):
        fixture._stop_owned_browser(self.process)
        self.process.terminate.assert_not_called()
        self.process.kill.assert_not_called()
        self.process.wait.assert_not_called()


if __name__ == '__main__':
    unittest.main()
