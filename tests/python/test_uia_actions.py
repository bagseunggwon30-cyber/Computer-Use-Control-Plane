"""Observation-bound UIA/input behavior with fake native adapter; not Windows GUI QA."""
import base64
import unittest
import test_engine
from test_engine import envelope
from pcucp_cli.mcp_server import tool_list


class UiaActionsTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    request = test_engine.EngineTests.request
    observe = test_engine.EngineTests.observe
    assert_error_code = test_engine.EngineTests.assert_error_code
    def ui_observe(self, nodes=None, status='ok'):
        if nodes is None:
            nodes = [self.node('A' * 48), self.node('B' * 48)]
        self.native.queue('uia-tree', envelope('uia-tree', status=status, data={'nodes': nodes}))
        result = self.request('observe', {'hwnd': '0x20', 'pid': 42, 'include_ui': True})
        self.assertIn(result['status'], ('ok', 'partial'))
        return result['data']['observation_id']

    @staticmethod
    def node(ref):
        return {'name': '저장', 'automation_id': 'save', 'control_type': 'Button',
                'element_ref': ref, 'process_id': 42, 'children': []}

    def test_find_preserves_ambiguity_without_acting(self):
        token = self.ui_observe()
        count = len(self.native.calls)
        result = self.request('uia-find', {'observation_id': token, 'name': '저장'})
        self.assertEqual(result['data']['count'], 2)
        self.assertTrue(result['data']['ambiguous'])
        self.assertEqual(len(self.native.calls), count)
        self.assertEqual(self.session.observation.id, token)

    def test_invoke_requires_both_current_observation_and_known_reference(self):
        token = self.ui_observe()
        bad = self.request('uia-invoke', {'observation_id': token, 'element_ref': 'C'*48})
        self.assert_error_code(bad, 'stale_element_reference')
        result = self.request('uia-invoke', {'observation_id': token, 'element_ref': 'A'*48})
        self.assertEqual(result['status'], 'ok', result)
        call = [c for c in self.native.calls if c[0] == 'uia-invoke'][0]
        self.assertIn('--pid', call[1]); self.assertIn('42', call[1])
        self.assertIn('--expected-x', call[1]); self.assertIn('--element-ref', call[1])
        stale = self.request('uia-invoke', {'observation_id': token, 'element_ref': 'B'*48})
        self.assert_error_code(stale, 'stale_observation')

    def test_set_value_supports_korean_emoji_and_empty_without_clipboard(self):
        for value in ('한글 😀', ''):
            token = self.ui_observe()
            result = self.request('uia-set-value', {'observation_id': token, 'element_ref': 'A'*48, 'text': value})
            self.assertEqual(result['status'], 'ok', result)
            call = [c for c in self.native.calls if c[0] == 'uia-set-value'][-1]
            encoded = call[1][call[1].index('--text-b64')+1]
            self.assertEqual(base64.b64decode(encoded).decode(), value)

    def test_partial_tree_never_issues_usable_refs(self):
        token = self.ui_observe(status='partial')
        result = self.request('uia-invoke', {'observation_id': token, 'element_ref': 'A'*48})
        self.assert_error_code(result, 'stale_element_reference')

    def test_native_failure_consumes_observation_and_never_retries(self):
        token = self.ui_observe()
        self.native.queue('uia-invoke', (124, None, 'timed out'))
        result = self.request('uia-invoke', {'observation_id': token, 'element_ref': 'A'*48})
        self.assertTrue(result['data']['may_have_acted'])
        self.assertFalse(result['data']['automatic_retry'])
        self.assertIsNone(self.session.observation)
        self.assertEqual(len([c for c in self.native.calls if c[0] == 'uia-invoke']), 1)

    def test_wrong_pid_duplicate_and_malformed_refs_rejected(self):
        for nodes in ([self.node('x')], [self.node('A'*48), self.node('A'*48)],
                      [{**self.node('A'*48), 'process_id': 43}]):
            self.native.queue('uia-tree', envelope('uia-tree', data={'nodes': nodes}))
            result = self.request('observe', {'hwnd': '0x20'})
            self.assert_error_code(result, 'invalid_observation')
            self.assertIsNone(self.session.observation)

    def test_drag_maps_both_points_from_negative_monitor(self):
        token = self.observe()
        result = self.request('drag', {'observation_id': token, 'x': 0, 'y': 0, 'to_x': 959, 'to_y': 539})
        self.assertEqual(result['status'], 'ok', result)
        args = [c[1] for c in self.native.calls if c[0] == 'drag'][0]
        self.assertEqual(args[args.index('--x')+1], '-1920')
        self.assertEqual(args[args.index('--to-x')+1], '-2')
        self.assertEqual(args[args.index('--to-y')+1], '878')

    def test_new_mutations_are_not_readonly_hints(self):
        listing = {t['name']: t for t in tool_list()}
        for name in ('uia_invoke', 'uia_set_value', 'drag'):
            self.assertFalse(listing['cucp_'+name]['annotations']['readOnlyHint'])
            readonly = type(self.session)(native=self.native)
            result = self.request(name.replace('_', '-'), {}, session=readonly)
            self.assert_error_code(result, 'live_control_required')

    def test_invalid_unicode_is_rejected_before_dispatch(self):
        for value in ('\ud800', '😀' * 2049, 'bad\x00value'):
            token = self.observe()
            count = len(self.native.calls)
            result = self.request('type', {'observation_id': token, 'text': value})
            self.assert_error_code(result, 'invalid_argument')
            self.assertEqual(len(self.native.calls), count)

    def test_read_find_expiry_and_batch_failure_stop(self):
        token = self.ui_observe()
        self.now += 61
        self.assert_error_code(self.request('uia-find', {'observation_id': token, 'name': '저장'}), 'stale_observation')
        token = self.ui_observe()
        self.native.queue('uia-invoke', (124, None, 'timed out'))
        result = self.request('batch', {'actions': [
            {'command': 'uia-invoke', 'args': {'observation_id': token, 'element_ref': 'A'*48}},
            {'command': 'click', 'args': {'observation_id': 'latest', 'x': 1, 'y': 1}},
        ]})
        self.assertEqual(result['data']['steps'][1]['status'], 'skipped')

    def test_standalone_tree_invalidates_actionable_references(self):
        token = self.ui_observe()
        self.request('uia-tree', {'hwnd': '0x20'})
        result = self.request('uia-invoke', {'observation_id': token, 'element_ref': 'A'*48})
        self.assert_error_code(result, 'stale_element_reference')
        self.assertNotIn('uia-invoke', [c[0] for c in self.native.calls])
