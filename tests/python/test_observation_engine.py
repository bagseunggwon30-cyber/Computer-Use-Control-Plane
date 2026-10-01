"""OCR/fusion/diff wiring against deterministic captured fixtures, never real OCR."""
import base64
import copy
import unittest
import test_engine
from test_engine import envelope, screenshot_data
from test_observation_processing import png, word


class ObservationEngineTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    request = test_engine.EngineTests.request
    observe = test_engine.EngineTests.observe
    assert_error_code = test_engine.EngineTests.assert_error_code

    def ocr_observe(self, *, ui=False):
        data = screenshot_data()
        data['ocr'] = {'words': [word('저장', 20, 30, 40, 20)],
                       'lines': [{'text': '저장', 'words': [word('저장', 20, 30, 40, 20)]}],
                       'coordinate_space': 'image_pixels', 'text': '저장', 'engine_language': 'ko'}
        self.native.queue('ocr-window', envelope('ocr-window', data=data))
        if ui:
            node = {'name': '저장', 'automation_id': 'save', 'control_type': 'Button', 'process_id': 42,
                    'patterns': ['Invoke'], 'element_ref': 'A'*48, 'bounding_rectangle': {'x': -1890, 'y': -150, 'width': 120, 'height': 60}, 'children': []}
            self.native.queue('uia-tree', envelope('uia-tree', data={'nodes': [node]}))
        result = self.request('ocr-window', {'hwnd': '0x20', 'include_ui': ui, 'language': 'ko'})
        self.assertEqual(result['status'], 'ok', result)
        return result['data']['observation_id']

    def test_window_ocr_issues_new_token_and_passes_language(self):
        old = self.observe()
        token = self.ocr_observe()
        self.assertNotEqual(old, token)
        call = next(c for c in self.native.calls if c[0] == 'ocr-window')
        self.assertIn('--language', call[1])
        self.assertIn('ko', call[1])
        result = self.request('ocr-find', {'observation_id': token, 'text': '저장', 'match': 'exact'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['top']['coordinate_space'], 'image_pixels')
        self.assertFalse(result['data']['automatic_action'])
        self.assert_error_code(self.request('ocr-find', {'observation_id': old, 'text': '저장'}), 'stale_observation')

    def test_fusion_keeps_image_and_negative_screen_coordinates_distinct(self):
        token = self.ocr_observe(ui=True)
        result = self.request('ocr-uia-fuse', {'observation_id': token, 'text': '저장', 'match': 'exact'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['coordinate_space'], 'physical_screen_pixels')
        point = result['data']['top']['point']
        self.assertEqual(point['image_x'], 40)
        self.assertEqual(point['screen_x'], -1840)
        self.assertFalse(result['data']['actionable'])
        self.assertFalse(result['data']['automatic_action'])
        self.assertNotIn('click', [c[0] for c in self.native.calls])

    def test_ocr_and_uia_presence_are_required(self):
        token = self.observe()
        self.assert_error_code(self.request('ocr-find', {'observation_id': token, 'text': 'x'}), 'ocr_observation_required')
        token = self.ocr_observe()
        self.assert_error_code(self.request('ocr-uia-fuse', {'observation_id': token, 'text': 'x'}), 'ui_observation_required')

    def test_ocr_error_does_not_issue_a_new_action_token(self):
        self.observe()
        self.native.queue('ocr-window', envelope('ocr-window', status='error', errors=[{'code': 'ocr_language_unavailable', 'message': 'missing'}]))
        result = self.request('ocr-window', {'hwnd': '0x20', 'language': 'ko'})
        self.assert_error_code(result, 'ocr_language_unavailable')
        self.assertIsNone(self.session.observation)

    def test_snapshot_memory_is_bounded_and_diff_keeps_pixels_separate_from_success(self):
        tokens = []
        for pixel in (b'\x00\x00\x00\xff', b'\xff\x00\x00\xff', b'\x00\xff\x00\xff'):
            data = screenshot_data()
            data['image']['data'] = base64.b64encode(png(width=1, height=1, pixels=pixel)).decode()
            self.native.queue('screenshot', envelope('screenshot', data=data))
            tokens.append(self.observe())
        self.assertEqual(len(self.session.snapshots), 2)
        self.assert_error_code(self.request('screenshot-diff', {'before_id': tokens[0], 'after_id': tokens[2]}), 'snapshot_unavailable')
        result = self.request('screenshot-diff', {'before_id': tokens[1], 'after_id': tokens[2]})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['changed_pixels'], 1)
        self.assertEqual(result['data']['verification'], 'pixels_changed_not_task_success')
        self.assertEqual(self.session.observation.id, tokens[2])

    def test_different_target_geometry_and_all_masked_diff_fail_closed(self):
        tokens = []
        for _ in range(2):
            data = screenshot_data()
            data['image']['data'] = base64.b64encode(png()).decode()
            self.native.queue('screenshot', envelope('screenshot', data=data))
            tokens.append(self.observe())
        args = {'before_id': tokens[0], 'after_id': tokens[1]}
        result = self.request('screenshot-diff', {**args, 'ignore_regions': [{'x': 0, 'y': 0, 'width': 2, 'height': 2}]})
        self.assertEqual(result['status'], 'partial', result)
        self.assert_error_code(result, 'incomplete_comparison')
        self.session.snapshots[-1]['geometry']['x'] += 1
        self.assert_error_code(self.request('screenshot-diff', args), 'incompatible_snapshots')

    def test_malformed_ocr_results_and_old_ocr_expiry(self):
        data = screenshot_data()
        data['ocr'] = {'words': [], 'lines': [], 'coordinate_space': 'screen_pixels'}
        self.native.queue('ocr-window', envelope('ocr-window', data=data))
        self.assert_error_code(self.request('ocr-window', {'hwnd': '0x20'}), 'invalid_observation')
        token = self.ocr_observe()
        self.now += 61
        self.assert_error_code(self.request('ocr-find', {'observation_id': token, 'text': 'x'}), 'stale_observation')
