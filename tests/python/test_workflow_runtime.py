"""Real Python planning/execution with injected native boundary; not desktop QA."""
import copy
import json
import unittest
from pcucp_cli.engine import ComputerSession
from pcucp_cli.workflows import WorkflowError, build_plan, form_plan, Recorder, condition_matches
from pcucp_cli.validation import validate, ValidationError
from pcucp_cli.mcp_server import SCHEMAS, tool_list, tool_result
import test_engine
from test_engine import envelope
import test_uia_actions


class WorkflowTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    request = test_engine.EngineTests.request
    observe = test_engine.EngineTests.observe
    assert_error_code = test_engine.EngineTests.assert_error_code
    ui_observe = test_uia_actions.UiaActionsTests.ui_observe
    node = staticmethod(test_uia_actions.UiaActionsTests.node)

    def workflow(self, steps, **options):
        return self.request('workflow-run', {'workflow': {'steps': steps, **options}})

    def test_plan_does_not_call_native_or_enable_live(self):
        workflow = {'steps': [{'command': 'type', 'args': {'observation_id': 'token', 'text': '한글'}}]}
        result = self.request('workflow-plan', {'workflow': workflow})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['plan']['live_step_count'], 1)
        self.assertEqual(self.native.calls, [])

    def test_readonly_preflight_stops_even_initial_read(self):
        self.session.allow_live_control = False
        result = self.workflow([{'command': 'windows', 'args': {}},
                                {'command': 'type', 'args': {'observation_id': 'latest', 'text': 'x'}}])
        self.assert_error_code(result, 'live_control_required')
        self.assertEqual(self.native.calls, [])

    def test_dryrun_permits_readonly_planning_of_mutation(self):
        self.session.allow_live_control = False
        result = self.request('workflow-run', {'dry_run': True, 'workflow': {'steps': [
            {'command': 'type', 'args': {'observation_id': 'x', 'text': 'x'}}]}})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['executed_count'], 0)
        self.assertEqual(self.native.calls, [])

    def test_schema_preflight_rejects_late_unknown_fields_before_input(self):
        result = self.workflow([{'command': 'focus', 'args': {'hwnd': '0x20', 'pid': 42}},
                               {'command': 'windows', 'args': {'allow_live_control': True}}])
        self.assert_error_code(result, 'invalid_argument')
        self.assertEqual(self.native.calls, [])

    def test_reference_workflow_observe_find_mutate_and_image(self):
        self.native.queue('uia-tree', envelope('uia-tree', data={'nodes': [self.node('A'*48)]}))
        result = self.workflow([
            {'id': 'o', 'command': 'observe', 'args': {'hwnd': '0x20', 'include_ui': True}},
            {'id': 'f', 'command': 'uia-find', 'args': {'observation_id': {'$ref': '/o/observation_id'}, 'name': '저장'},
             'assert': {'path': '/count', 'equals': 1}},
            {'command': 'uia-set-value', 'args': {'observation_id': {'$ref': '/o/observation_id'},
                                                 'element_ref': {'$ref': '/f/matches/0/element_ref'}, 'text': '안녕 😀'}},
        ])
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['executed_count'], 3)
        self.assertEqual(len([x for x in self.native.calls if x[0] == 'uia-set-value']), 1)
        self.assertEqual(len([x for x in tool_result(result)['content'] if x['type'] == 'image']), 1)

    def test_ambiguity_assertion_stops_before_any_mutation(self):
        self.native.queue('uia-tree', envelope('uia-tree', data={'nodes': [self.node('A'*48), self.node('B'*48)]}))
        result = self.request('form-run', {'hwnd': '0x20', 'fields': [{'selector': {'name': '저장'}, 'text': 'secret'}]})
        self.assert_error_code(result, 'assertion_failed')
        self.assertEqual(result['data']['steps'][2]['status'], 'skipped')
        self.assertNotIn('uia-set-value', [c[0] for c in self.native.calls])
        self.assertIsNone(self.session.observation)
        self.assertNotIn('observation_id', result['data'])

    def test_form_reobserves_and_supports_empty_values_without_implicit_submit(self):
        for ref in ('A'*48, 'B'*48):
            self.native.queue('uia-tree', envelope('uia-tree', data={'nodes': [self.node(ref)]}))
        result = self.request('form-run', {'hwnd': '0x20', 'fields': [
            {'selector': {'automation_id': 'save'}, 'text': ''},
            {'selector': {'name': '저장'}, 'text': '한국어 😀'},
        ]})
        self.assertEqual(result['status'], 'ok', result)
        calls = [c[0] for c in self.native.calls]
        self.assertEqual(calls.count('uia-tree'), 2)
        self.assertEqual(calls.count('uia-set-value'), 2)
        self.assertNotIn('uia-invoke', calls)

    def test_form_submit_is_explicit_and_observed_again(self):
        for ref in ('A'*48, 'B'*48):
            self.native.queue('uia-tree', envelope('uia-tree', data={'nodes': [self.node(ref)]}))
        result = self.request('form-run', {'hwnd': '0x20', 'fields': [{'selector': {'name': '저장'}, 'text': 'x'}], 'submit': {'name': '저장'}})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual([c[0] for c in self.native.calls].count('uia-invoke'), 1)

    def test_failed_mutation_never_retried_and_stops(self):
        token = self.observe()
        self.native.queue('type', (124, None, 'timeout'))
        result = self.workflow([{'command': 'type', 'args': {'observation_id': token, 'text': 'x'}},
                               {'command': 'windows', 'args': {}}], read_retries=3)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['data']['may_have_acted'])
        self.assertEqual(result['data']['steps'][1]['status'], 'skipped')
        self.assertEqual([c[0] for c in self.native.calls].count('type'), 1)
        self.assertIsNone(self.session.observation)

    def test_read_retry_is_explicit_and_bounded(self):
        self.session.sleep = lambda seconds: setattr(self, 'now', self.now + seconds)
        self.native.queue('windows', (1, None, 'temporarily unavailable'))
        result = self.workflow([{'command': 'windows', 'args': {}}], read_retries=1)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['steps'][0]['attempts'], 2)

    def test_partial_read_never_retried(self):
        self.native.queue('windows', envelope('windows', status='partial'))
        result = self.workflow([{'command': 'windows', 'args': {}}], read_retries=3)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(len(self.native.calls), 1)

    def test_cancel_during_settle_stops_next_operation(self):
        def pause(seconds):
            self.now += seconds
            self.session.cancel()
        self.session.sleep = pause
        result = self.workflow([{'command': 'windows', 'args': {}}, {'command': 'windows', 'args': {}}], settle_ms=100)
        self.assert_error_code(result, 'session_cancelled')
        self.assertEqual(result['data']['steps'][1]['status'], 'skipped')
        self.assertEqual(len(self.native.calls), 1)

    def test_cycles_forwardrefs_and_nested_dispatch_blocked(self):
        for command in ('workflow-run', 'batch', 'form-run', 'watch', 'record-start', 'legacy', 'session'):
            with self.subTest(command=command):
                result = self.workflow([{'command': command, 'args': {}}])
                self.assertEqual(result['status'], 'error')
        result = self.workflow([{'id': 'a', 'command': 'observe', 'args': {'hwnd': {'$ref': '/a/target/hwnd'}}}])
        self.assert_error_code(result, 'invalid_reference')
        self.assertEqual(self.native.calls, [])

    def test_duplicate_ids_bad_limits_and_injection_are_data(self):
        for spec in ({'steps': []}, {'steps': [{'command': 'windows', 'args': {}}]*65},
                     {'steps': [{'id': 'a', 'command': 'windows', 'args': {}}]*2},
                     {'steps': [{'command': 'windows', 'args': {}}], 'read_retries': True}):
            with self.assertRaises(WorkflowError):
                build_plan(spec)
        result = self.workflow([{'command': 'uia-find', 'args': {'observation_id': '$(calc)', 'name': '; calc'}}])
        self.assert_error_code(result, 'stale_observation')

    def test_watch_cannot_wrap_mutation(self):
        result = self.request('watch', {'command': 'type', 'args': {'observation_id': 'x', 'text': 'x'}})
        self.assert_error_code(result, 'invalid_argument')
        self.assertEqual(self.native.calls, [])

    def test_watch_until_and_changes(self):
        self.session.sleep = lambda seconds: setattr(self, 'now', self.now + seconds)
        self.native.queue('windows', envelope('windows', data={'count': 0}), envelope('windows', data={'count': 1}))
        result = self.request('watch', {'command': 'windows', 'args': {}, 'until': {'path': '/count', 'equals': 1}})
        self.assertEqual(result['status'], 'ok', result)
        self.assertTrue(result['data']['until_matched'])
        self.assertEqual(len(result['data']['cycles']), 2)
        self.assertTrue(result['data']['cycles'][1]['changed'])

    def test_watch_unmet_is_partial_not_success(self):
        result = self.request('watch', {'command': 'windows', 'args': {}, 'max_cycles': 1, 'until': {'path': '/count', 'equals': 9}})
        self.assertEqual(result['status'], 'partial')
        self.assert_error_code(result, 'condition_not_met')

    def test_recording_never_contains_text_request_ids_or_image(self):
        self.request('record-start')
        token = self.observe()
        self.request('type', {'observation_id': token, 'text': 'secret-value'}, rid='secret-request-id')
        result = self.request('record-stop')
        raw = json.dumps(result)
        self.assertNotIn('secret-value', raw)
        self.assertNotIn('secret-request-id', raw)
        self.assertNotIn('iVBOR', raw)
        self.assertFalse(result['data']['replayable'])
        self.assertFalse(result['data']['active'])

    def test_recorder_limit_and_double_start(self):
        r = Recorder()
        r.start()
        with self.assertRaises(WorkflowError): r.start()
        for i in range(1005): r.append({'command': 'windows', 'status': 'ok'})
        self.assertEqual(len(r.entries), 1000)
        self.assertEqual(r.dropped, 5)

    def test_condition_json_types_and_escaped_pointers(self):
        self.assertFalse(condition_matches({'value': True}, {'path': '/value', 'equals': 1}))
        self.assertTrue(condition_matches({'a/b': {'x~y': 1}}, {'path': '/a~1b/x~0y', 'equals': 1}))
        self.assertTrue(condition_matches({}, {'path': '/missing', 'exists': False}))

    def test_validation_and_capabilities_use_same_tool_set(self):
        caps = self.request('capabilities')['data']['commands']
        self.assertEqual({x['name'] for x in caps}, set(SCHEMAS))
        for name in ('workflow-run', 'form-run', 'uia-toggle', 'uia-select', 'uia-expand-collapse', 'uia-scroll'):
            tool = next(t for t in tool_list() if t['name'] == 'cucp_'+name.replace('-', '_'))
            self.assertFalse(tool['annotations']['readOnlyHint'])
        with self.assertRaises(ValidationError): validate({'x': True}, {'type': 'object', 'properties': {'x': {'type': 'integer'}}})

    def test_new_patterns_use_current_reference_and_validate_options(self):
        for command, extra, expected in (
            ('uia-toggle', {}, []), ('uia-select', {'selection_mode': 'add'}, ['--selection-mode', 'add']),
            ('uia-expand-collapse', {'state': 'collapsed'}, ['--state', 'collapsed']),
            ('uia-scroll', {'vertical': 'large-increment'}, ['--vertical', 'large-increment']),
        ):
            token = self.ui_observe([self.node('A'*48)])
            result = self.request(command, {'observation_id': token, 'element_ref': 'A'*48, **extra})
            self.assertEqual(result['status'], 'ok', result)
            call = next(c for c in reversed(self.native.calls) if c[0] == command)
            for value in expected: self.assertIn(value, call[1])
        token = self.ui_observe([self.node('A'*48)])
        count = len(self.native.calls)
        self.assert_error_code(self.request('uia-scroll', {'observation_id': token, 'element_ref': 'A'*48}), 'invalid_argument')
        self.assertEqual(len(self.native.calls), count)

    def test_recovery_never_dispatches_and_profile_is_observation_bound(self):
        result = self.request('recovery-plan', {'failed_reason': 'dialog'})
        self.assertEqual(self.native.calls, [])
        self.assertFalse(result['data']['automatic_dismissal'])
        token = self.ui_observe([self.node('A'*48)])
        result = self.request('app-profile', {'observation_id': token})
        self.assertEqual(result['data']['element_count'], 1)
        self.assertFalse(result['data']['model_provider_required'])

    def test_nested_json_conditions_keep_boolean_distinct_from_integer(self):
        for actual, expected in (({'v': True}, {'v': 1}), ([True], [1]), ({'v': [False]}, {'v': [0]})):
            self.assertFalse(condition_matches({'value': actual}, {'path': '/value', 'equals': expected}))
        self.assertTrue(condition_matches({'value': {'v': [True]}}, {'path': '/value', 'equals': {'v': [True]}}))

    def test_settle_deadline_preserves_applied_operation_status(self):
        self.session.sleep = lambda seconds: setattr(self, 'now', self.now + seconds)
        token = self.observe()
        result = self.workflow([{'command': 'type', 'args': {'observation_id': token, 'text': 'x'}}], timeout_ms=100, settle_ms=200)
        self.assertEqual(result['status'], 'partial', result)
        self.assertTrue(result['data']['may_have_acted'])
        step = result['data']['steps'][0]
        self.assertEqual(step['operation_status'], 'ok')
        self.assertEqual(step['completion_phase'], 'settle')
        self.assertTrue(step['may_have_acted'])
        self.assertFalse(result['data']['automatic_mutation_retry'])

    def test_watch_validates_leaf_schema_before_any_native_call(self):
        result = self.request('watch', {'command': 'windows', 'args': {'unexpected': True}})
        self.assert_error_code(result, 'invalid_argument')
        self.assertEqual(self.native.calls, [])

    def test_task_launch_wait_is_bound_to_launched_pid(self):
        self.native.queue('app-launch', envelope('app-launch', data={'pid': 42}))
        self.native.queue('windows', envelope('windows', data={'windows': [
            {'hwnd': '0x21', 'process_id': 99, 'title': 'Editor'},
            {'hwnd': '0x20', 'process_id': 42, 'title': 'Editor'}]}))
        result = self.request('task-run', {'launch': {'path': 'C:\\Apps\\Editor.exe'},
            'wait': {'title': 'Editor'}, 'text': 'hello'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['executed_count'], 4)
        self.assertEqual([c[0] for c in self.native.calls].count('app-launch'), 1)
        self.assertEqual([c[0] for c in self.native.calls].count('type'), 1)

    def test_task_build_cannot_override_launch_pid_or_create_nested_actions(self):
        result = self.request('task-build', {'launch': {'path': 'C:\\Apps\\Editor.exe'},
            'wait': {'title': 'Editor', 'pid': 99}})
        self.assert_error_code(result, 'invalid_plan')
        self.assertEqual(self.native.calls, [])

    def test_task_build_returns_reviewable_plan_without_dispatch(self):
        result = self.request('task-build', {'target': {'hwnd': '0x20', 'pid': 42},
            'fields': [{'selector': {'automation_id': 'title'}, 'text': '안녕하세요'}],
            'keys': ['CTRL+S']})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['plan']['live_step_count'], 2)
        self.assertEqual(self.native.calls, [])
