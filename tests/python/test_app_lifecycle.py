"""Process policy with injected native transport; never launches applications."""
import base64
import json
import unittest
import test_engine
from pcucp_cli.engine import ComputerSession

class AppLifecycleTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    request = test_engine.EngineTests.request
    observe = test_engine.EngineTests.observe
    click = test_engine.EngineTests.click
    assert_error_code = test_engine.EngineTests.assert_error_code

    def test_launch_close_blocked_readonly(self):
        readonly = ComputerSession(native=self.native)
        for command in ('app-close', 'app-launch'):
            result = self.request(command, {}, session=readonly)
            self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.native.calls, [])

    def test_launch_preserves_argument_vector_and_consumes_observation(self):
        self.observe()
        values = ['hello world', '& calc.exe', 'a"b', '한국어', '']
        result = self.request('app-launch', {'path': 'C:\\Apps\\test.exe', 'arguments': values})
        self.assertEqual(result['status'], 'ok')
        cmd, args, _ = self.native.calls[-1]
        self.assertEqual(cmd, 'app-launch')
        self.assertEqual(json.loads(base64.b64decode(args[args.index('--args-b64')+1])), values)
        self.assertIsNone(self.session.observation)
        self.assertFalse(result['data']['automatic_retry'])

    def test_launch_rejects_scripts_names_and_unknown_fields(self):
        for path in ('notepad.exe', 'C:\\x.cmd', 'https://example.com/x.exe', '/bin/x.exe', 'C:\\x.exe\x00'):
            self.assert_error_code(self.request('app-launch', {'path': path}), 'invalid_argument')
        self.assert_error_code(self.request('app-launch', {'path': 'C:\\x.exe', 'force': True}), 'invalid_argument')
        self.assertEqual(self.native.calls, [])

    def test_close_consumes_token_passes_exact_target_and_does_not_capture_dead_window(self):
        token = self.observe()
        before = len(self.native.calls)
        result = self.request('app-close', {'observation_id': token})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(self.native.calls), before+1)
        _, args, _ = self.native.calls[-1]
        self.assertIn('--expected-x', args)
        self.assertEqual(args[args.index('--pid')+1], '42')
        self.assertIsNone(self.session.observation)
        self.assert_error_code(self.request('app-close', {'observation_id': token}), 'stale_observation')

    def test_cancelled_session_never_dispatches(self):
        token = self.observe()
        before = len(self.native.calls)
        self.session.cancel()
        self.assert_error_code(self.click(token), 'session_cancelled')
        self.assertEqual(len(self.native.calls), before)

if __name__ == '__main__': unittest.main()
