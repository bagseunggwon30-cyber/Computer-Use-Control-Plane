"""Behavioral engine contracts using an injected native host, never desktop input."""
from collections import defaultdict, deque
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next' / 'python'))
from pcucp_cli.engine import ComputerSession


def envelope(command, *, status='ok', data=None, errors=None):
    return 0, {'schema': 'pcucp.native/v1', 'kind': command, 'status': status,
               'data': data if data is not None else {}, 'errors': errors or []}, ''


def screenshot_data():
    return {
        'image': {'mime_type': 'image/png', 'data': 'iVBORw0KGgo=', 'width': 960, 'height': 540},
        'target': {'hwnd': '0x20', 'pid': 42},
        'geometry': {'x': -1920, 'y': -200, 'width': 1920, 'height': 1080,
                     'image_width': 960, 'image_height': 540},
        'window_geometry': {'x': -1920, 'y': -200, 'width': 1920, 'height': 1080},
    }


class NativeFake:
    def __init__(self):
        self.calls = []
        self.responses = defaultdict(deque)

    def queue(self, command, *responses):
        self.responses[command].extend(responses)

    def __call__(self, command, args, **kwargs):
        self.calls.append((command, list(args), dict(kwargs)))
        if self.responses[command]:
            response = self.responses[command].popleft()
            if isinstance(response, BaseException):
                raise response
            return copy.deepcopy(response)
        if command == 'screenshot':
            return envelope(command, data=screenshot_data())
        if command == 'uia-tree':
            return envelope(command, data={'nodes': [], 'count': 0})
        if command == 'windows':
            return envelope(command, data={'windows': [{'hwnd': '0x20', 'process_id': 42}], 'count': 1})
        return envelope(command, data={'dispatched': True})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.native = NativeFake()
        self.now = 100.0
        self.session = ComputerSession(allow_live_control=True, native=self.native,
                                       clock=lambda: self.now, observation_ttl_s=60)
        self.sequence = 0

    def request(self, command, args=None, *, session=None, rid=None):
        self.sequence += 1
        return (session or self.session).handle({
            'schema': 'cucp.request/v1', 'id': rid or f'request-{self.sequence}',
            'command': command, 'args': args or {},
        })

    def observe(self):
        response = self.request('screenshot', {'hwnd': '0x20', 'pid': 42})
        self.assertEqual(response['status'], 'ok', response)
        return response['data']['observation_id']

    def click(self, token, **kwargs):
        return self.request('click', {'observation_id': token, 'x': 25, 'y': 30}, **kwargs)

    def assert_error_code(self, result, code):
        self.assertIn(code, [error['code'] for error in result['errors']], result)

    def test_read_only_mutation_blocked_before_native(self):
        session = ComputerSession(native=self.native)
        result = self.request('focus', {'hwnd': '0x20', 'pid': 42}, session=session)
        self.assertEqual(result['status'], 'blocked')
        self.assert_error_code(result, 'live_control_required')
        self.assertEqual(self.native.calls, [])

    def test_read_only_batch_preflight_prevents_all_effects(self):
        session = ComputerSession(native=self.native)
        result = self.request('batch', {'actions': [
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
            {'command': 'click', 'args': {'observation_id': 'latest', 'x': 1, 'y': 1}},
        ]}, session=session)
        self.assertEqual(result['status'], 'blocked')
        self.assert_error_code(result, 'live_control_required')
        self.assertEqual(self.native.calls, [])

    def test_read_only_batch_observations_work(self):
        session = ComputerSession(native=self.native)
        result = self.request('batch', {'actions': [
            {'command': 'windows', 'args': {}},
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
        ]}, session=session)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual([call[0] for call in self.native.calls], ['windows', 'screenshot'])

    def test_request_cannot_enable_live_control(self):
        session = ComputerSession(native=self.native)
        result = self.request('focus', {'hwnd': '0x20', 'pid': 42, 'allow_live_control': True}, session=session)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.native.calls, [])

    def test_expired_observation_blocks_without_input(self):
        token = self.observe()
        self.now += 61
        before = len(self.native.calls)
        result = self.click(token)
        self.assertEqual(result['status'], 'blocked')
        self.assert_error_code(result, 'stale_observation')
        self.assertEqual(len(self.native.calls), before)

    def test_observation_consumed_and_replaced_after_action(self):
        token = self.observe()
        first = self.click(token)
        self.assertEqual(first['status'], 'ok', first)
        self.assertNotEqual(token, first['data']['observation_id'])
        before = len(self.native.calls)
        second = self.click(token)
        self.assertEqual(second['status'], 'blocked')
        self.assertEqual(len(self.native.calls), before)

    def test_wrong_target_observation_never_issues_token(self):
        data = screenshot_data()
        data['target']['hwnd'] = '0x21'
        self.native.queue('screenshot', envelope('screenshot', data=data))
        result = self.request('screenshot', {'hwnd': '0x20', 'pid': 42})
        self.assert_error_code(result, 'target_mismatch')
        self.assertIsNone(self.session.observation)

    def test_wrong_pid_observation_never_issues_token(self):
        data = screenshot_data()
        data['target']['pid'] = 43
        self.native.queue('screenshot', envelope('screenshot', data=data))
        result = self.request('screenshot', {'hwnd': '0x20', 'pid': 42})
        self.assert_error_code(result, 'target_mismatch')
        self.assertIsNone(self.session.observation)

    def test_scaled_coordinates_preserve_negative_monitor_origin(self):
        token = self.observe()
        response = self.click(token)
        self.assertEqual(response['status'], 'ok', response)
        args = next(call[1] for call in self.native.calls if call[0] == 'click')
        options = dict(zip(args[0:-1:2], args[1:-1:2]))
        self.assertEqual(options['--x'], '-1870')
        self.assertEqual(options['--y'], '-140')
        self.assertEqual(options['--expected-x'], '-1920')
        self.assertEqual(options['--expected-y'], '-200')
        self.assertEqual(options['--hwnd'], '0x20')
        self.assertEqual(options['--pid'], '42')
        self.assertEqual(args[-1], '--allow-live-control')

    def test_image_boundary_is_exclusive(self):
        token = self.observe()
        before = len(self.native.calls)
        result = self.request('click', {'observation_id': token, 'x': 960, 'y': 0})
        self.assert_error_code(result, 'invalid_argument')
        self.assertEqual(len(self.native.calls), before)

    def test_duplicate_action_request_never_replays(self):
        token = self.observe()
        self.assertEqual(self.click(token, rid='stable-action-id')['status'], 'ok')
        before = len(self.native.calls)
        duplicate = self.click(token, rid='stable-action-id')
        self.assert_error_code(duplicate, 'duplicate_request')
        self.assertEqual(len(self.native.calls), before)
        self.assertEqual(sum(call[0] == 'click' for call in self.native.calls), 1)

    def test_failed_input_is_not_retried_and_consumes_token(self):
        token = self.observe()
        self.native.queue('click', (5, {'schema': 'pcucp.native/v1', 'kind': 'click', 'status': 'error',
            'data': {'sent': 1}, 'errors': [{'code': 'partial_input', 'message': 'one input event sent'}]}, ''))
        result = self.click(token)
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result['data']['may_have_acted'])
        self.assertFalse(result['data']['automatic_retry'])
        self.assertEqual([call[0] for call in self.native.calls], ['screenshot', 'click'])
        self.assertEqual(self.click(token)['status'], 'blocked')
        self.assertEqual(sum(call[0] == 'click' for call in self.native.calls), 1)

    def test_postaction_capture_failure_reports_partial(self):
        token = self.observe()
        self.native.queue('screenshot', (1, None, 'capture unavailable'))
        result = self.click(token)
        self.assertEqual(result['status'], 'partial', result)
        self.assertTrue(result['data']['action']['dispatched'])
        self.assertTrue(result['data']['may_have_acted'])
        self.assertNotIn('observation_id', result['data'])
        self.assertIsNone(self.session.observation)

    def test_action_transport_exception_preserves_uncertainty(self):
        token = self.observe()
        self.native.queue('click', RuntimeError('transport vanished'))
        result = self.click(token)
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result['data'].get('may_have_acted'), result)
        self.assertFalse(result['data'].get('automatic_retry', True), result)
        self.assertIsNone(self.session.observation)

    def test_postaction_transport_exception_is_partial(self):
        token = self.observe()
        self.native.queue('screenshot', RuntimeError('capture transport vanished'))
        result = self.click(token)
        self.assertEqual(result['status'], 'partial', result)
        self.assertTrue(result['data']['may_have_acted'])
        self.assertTrue(result['data']['action']['dispatched'])

    def test_latest_alias_rejected_outside_batch(self):
        self.observe()
        before = len(self.native.calls)
        result = self.click('latest')
        self.assertEqual(result['status'], 'blocked', result)
        self.assertEqual(len(self.native.calls), before)

    def test_latest_alias_requires_prior_batch_step(self):
        self.observe()
        before = len(self.native.calls)
        result = self.request('batch', {'actions': [
            {'command': 'click', 'args': {'observation_id': 'latest', 'x': 1, 'y': 1}},
        ]})
        self.assertNotEqual(result['status'], 'ok', result)
        self.assertEqual(len(self.native.calls), before)

    def test_batch_latest_uses_each_new_observation(self):
        result = self.request('batch', {'actions': [
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
            {'command': 'click', 'args': {'observation_id': 'latest', 'x': 1, 'y': 1}},
            {'command': 'key', 'args': {'observation_id': 'latest', 'keys': 'ENTER'}},
        ]})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual([call[0] for call in self.native.calls],
                         ['screenshot', 'click', 'screenshot', 'key', 'screenshot'])
        self.assertTrue(result['data']['observation_id'])

    def test_batch_stops_and_reports_skipped_steps(self):
        self.native.queue('click', (1, None, 'focus changed'))
        result = self.request('batch', {'actions': [
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
            {'command': 'click', 'args': {'observation_id': 'latest', 'x': 1, 'y': 1}},
            {'command': 'type', 'args': {'observation_id': 'latest', 'text': 'must not send'}},
        ]})
        self.assertEqual(result['status'], 'error', result)
        self.assertEqual([step['status'] for step in result['data']['steps']], ['ok', 'error', 'skipped'])
        self.assertTrue(result['data']['steps'][1]['data']['may_have_acted'])
        self.assertNotIn('observation_id', result['data'])
        self.assertIsNone(self.session.observation)
        self.assertEqual([call[0] for call in self.native.calls], ['screenshot', 'click'])

    def test_batch_native_exception_preserves_prior_results_and_skips(self):
        self.native.queue('click', RuntimeError('native crashed'))
        result = self.request('batch', {'actions': [
            {'command': 'screenshot', 'args': {'hwnd': '0x20'}},
            {'command': 'click', 'args': {'observation_id': 'latest', 'x': 1, 'y': 1}},
            {'command': 'key', 'args': {'observation_id': 'latest', 'keys': 'ENTER'}},
        ]})
        self.assertEqual(result['status'], 'error', result)
        self.assertEqual([step['status'] for step in result['data'].get('steps', [])], ['ok', 'error', 'skipped'], result)
        self.assertTrue(result['data']['steps'][1]['data']['may_have_acted'])
        self.assertEqual([call[0] for call in self.native.calls], ['screenshot', 'click'])

    def test_malformed_native_envelopes_are_protocol_errors(self):
        malformed = [[], 'text', {'status': []}, {'status': 'ok', 'data': []},
                     {'status': 'ok', 'data': None}, {'status': 'unexpected', 'data': {}}]
        for payload in malformed:
            with self.subTest(payload=payload):
                self.native.queue('windows', (0, payload, ''))
                result = self.request('windows')
                self.assertEqual(result['status'], 'error', result)
                self.assertIsInstance(result['data'], dict)
                self.assertTrue(result['errors'], result)
                self.assertNotIn('internal_error', [e['code'] for e in result['errors']], result)

    def test_explicit_focus_gets_checked_target_and_fresh_observation(self):
        result = self.request('focus', {'hwnd': '32', 'pid': 42})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(self.native.calls[0][1], ['--hwnd', '0x20', '--pid', '42', '--allow-live-control'])
        self.assertEqual([call[0] for call in self.native.calls], ['focus', 'screenshot'])
        self.assertTrue(result['data']['observation_id'])

    def test_double_click_uses_one_native_action_then_observes(self):
        token = self.observe()
        result = self.request('click', {'observation_id': token, 'x': 25, 'y': 30, 'count': 2})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual([c[0] for c in self.native.calls], ['screenshot', 'click', 'screenshot'])
        args = self.native.calls[1][1]
        self.assertEqual(args[args.index('--count') + 1], '2')
        self.assertNotEqual(token, result['data']['observation_id'])

    def test_invalid_click_count_sends_no_input(self):
        token = self.observe()
        for count in (0, 3, True, 1.5, '2'):
            result = self.request('click', {'observation_id': token, 'x': 0, 'y': 0, 'count': count})
            self.assert_error_code(result, 'invalid_argument')
        self.assertEqual([c[0] for c in self.native.calls], ['screenshot'])

    def test_wait_window_is_read_only_and_waits_for_title_and_pid(self):
        def sleep(seconds):
            self.now += seconds
        self.session.sleep = sleep
        self.session.allow_live_control = False
        self.native.queue('windows', envelope('windows', data={'windows': []}),
            envelope('windows', data={'windows': [{'hwnd': '0x20', 'process_id': 42, 'title': '메모장 - TEST'}]}))
        result = self.request('wait-window', {'title': 'test', 'pid': 42, 'timeout_ms': 500})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['attempts'], 2)
        self.assertEqual(result['data']['windows'][0]['hwnd'], '0x20')
        self.assertEqual([c[0] for c in self.native.calls], ['windows', 'windows'])
        self.assertIsNone(self.session.observation)

    def test_wait_window_timeout_is_bounded_and_does_not_focus(self):
        self.session.sleep = lambda seconds: setattr(self, 'now', self.now + seconds)
        result = self.request('wait-window', {'title': 'absent', 'timeout_ms': 500})
        self.assert_error_code(result, 'window_wait_timeout')
        self.assertEqual(self.now, 100.5)
        self.assertEqual(len(self.native.calls), 2)
        self.assertLessEqual(self.native.calls[-1][2]['timeout_s'], 0.25)

    def test_wait_window_ambiguity_and_native_failure_stop(self):
        self.native.queue('windows', envelope('windows', data={'windows': [
            {'hwnd': '0x20', 'process_id': 42, 'title': 'Test'},
            {'hwnd': '0x21', 'process_id': 43, 'title': 'Test'}]}))
        result = self.request('wait-window', {'title': 'Test'})
        self.assert_error_code(result, 'ambiguous_target')
        self.assertEqual(len(result['data']['windows']), 2)
        self.native.queue('windows', (1, None, 'native died'))
        result = self.request('wait-window', {'title': 'Test'})
        self.assert_error_code(result, 'native_unavailable')
        self.assertEqual(len(self.native.calls), 2)

    def test_invalid_wait_arguments_never_enumerate(self):
        for args in ({'title': ''}, {'title': ' '}, {'title': 'x', 'timeout_ms': 0},
                     {'title': 'x', 'timeout_ms': 10001}, {'title': 'x', 'poll_ms': 0}, {'title': 'x', 'pid': True}):
            self.assert_error_code(self.request('wait-window', args), 'invalid_argument')
        self.assertEqual(self.native.calls, [])


if __name__ == '__main__':
    unittest.main()
