"""Coordinate risk scenarios and actual fixed Windows acquisition, without input."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_coordinates import Coordinates
from pcucp_cli.native_session import NativeSession


class CoordinateRiskTests(unittest.TestCase):
    def snapshot(self, point_device='left', target_device='left', scale=1):
        monitor = lambda name: dict(device=name, primary=name == 'left', rect=dict(x=0, y=0, width=500, height=500),
            work_rect=dict(x=0, y=0, width=500, height=480), dpi=dict(x=96, y=96, scale_x=scale, scale_y=scale))
        return dict(virtual_screen=dict(x=-500, y=0, width=1000, height=500, right=500, bottom=500,
            monitor_count=2, same_display_format=True), monitors=[monitor('left'), monitor('right')],
            point_monitor=monitor(point_device), target_monitor=monitor(target_device), target_window_dpi=dict(dpi=96, scale=1))

    def coordinates(self, snapshot, *, matched=True):
        window = dict(hwnd=42, title='Owned Editor', process='editor', visible=True, minimized=False, foreground=False,
            rect=dict(x=100, y=100, width=200, height=100), **{'class': 'Owned'})
        def read(operation, args):
            if operation == 'windows': return [window]
            if operation == 'coordinate-snapshot': return snapshot
            values = dict(zip(args[::2], args[1::2]))
            return dict(status='ok' if matched else 'partial', root_hwnd=42, root_title=window['title'], process_name='editor',
                process_id=1, root_class='Owned', matched=matched, x=int(values['--x']), y=int(values['--y']))
        return Coordinates(read)

    def test_multi_monitor_dpi_and_target_edge_risks_preserve_warning_order(self):
        result = self.coordinates(self.snapshot(scale=1.5)).profile(has_point=True, x=100, y=101, target_hwnd=42)
        self.assertEqual(result['coordinate_risk'], 'medium')
        self.assertEqual(result['warnings'], ['point_near_target_window_edge', 'non_100_percent_dpi_scale', 'multi_monitor_coordinates'])
        self.assertEqual(result['point_window_relative']['norm_x'], 0)
        self.assertEqual(result['edge_distance_to_target']['min'], 0)
        self.assertTrue(result['point_inside_target_window'])

    def test_mismatched_target_and_monitor_are_high_risk_without_clamping(self):
        result = self.coordinates(self.snapshot(point_device='right'), matched=False).profile(
            has_point=True, x=300, y=200, target_hwnd=42)
        self.assertEqual(result['coordinate_risk'], 'high')
        self.assertEqual(result['warnings'], ['point_outside_target_window', 'multi_monitor_coordinates',
            'point_monitor_differs_from_target_window_monitor', 'win32_hit_test_target_mismatch'])
        self.assertEqual(result['point_window_relative']['norm_x'], 1)
        self.assertFalse(result['point_inside_target_window'])
        self.assertIn('target=42', result['coord_signature'])


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_DIAGNOSTIC_PROVIDER_NATIVE'), 'Explicit Windows fixed coordinate reads')
class ActualCoordinateReadTests(unittest.TestCase):
    def test_snapshot_and_outside_screen_profile_use_actual_wrapper_interop(self):
        with NativeSession() as native:
            def read(operation, args):
                code, payload, error = native('legacy-diagnostic-read', ['--operation', operation, *args])
                self.assertEqual(code, 0, error)
                return payload['data']['value']
            coordinates = Coordinates(read)
            result = coordinates.profile(has_point=True, x=-100000, y=-100000, target_match='CUCP unique absent coordinate target')
            self.assertEqual(result['schema'], 'cucp.coord-profile/v1')
            self.assertEqual(result['coordinate_risk'], 'high')
            self.assertFalse(result['point_inside_virtual_screen'])
            self.assertIsNone(result['target_window'])
            self.assertEqual(result['hit_test']['source'], 'wrapper_win32_fast')
            self.assertTrue(result['monitors'])
            self.assertGreater(result['virtual_screen']['width'], 0)


if __name__ == '__main__':
    unittest.main()
