"""Wrapper coordinate acquisition and risk evidence, using fixed Win32 reads."""
import time
from .legacy_cdp_contract import _ps_equal, _invariant_lower, _framework_sort
from .legacy_native_kernel import compatibility
from .legacy_host_protocol import require
from .legacy_values import int32


def find_window(windows, match):
    if not match:
        return None
    needle = _invariant_lower(match)
    rows = [row for row in windows if row['visible'] and (needle in _invariant_lower(row['title'] or '') or
        needle in _invariant_lower(row['process'] or ''))]
    def rank(row):
        return (0 if _ps_equal(_invariant_lower(row['title'] or ''), needle) else
                1 if _ps_equal(_invariant_lower(row['process'] or ''), needle) else 2, 1 if row['minimized'] else 0)
    _framework_sort(rows, lambda a, b: (rank(a) > rank(b)) - (rank(a) < rank(b)))
    return rows[0] if rows else None


class Coordinates:
    def __init__(self, read, *, culture='en-US', remaining=lambda: 30, cancelled=None, modern=False):
        self.read, self.culture, self.remaining, self.cancelled, self.modern = read, culture, remaining, cancelled, modern

    def hit(self, x, y, target_hwnd=0, target_match=''):
        return self.read('hit-test-point', ['--x', str(x), '--y', str(y), '--target-hwnd', str(target_hwnd), '--target-match', target_match or ''])

    def _find(self, match):
        result = compatibility('coord-window', dict(windows=self.read('windows', []), match=match, modern=self.modern),
            culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled)
        require(result.get('schema') == 'cucp.coord-window/v1', 'Invalid coordinate window selection.')
        return result['window']

    def _precheck_window(self, hit, *, synthetic=True):
        if not hit or hit['root_hwnd'] <= 0:
            return None
        window = next((row for row in self.read('windows', []) if row['hwnd'] == hit['root_hwnd']), None)
        if window or not synthetic:
            return window
        return dict(
            hwnd=hit['root_hwnd'], title=hit['root_title'], process=hit['process_name'], pid=hit['process_id'],
            **{'class': hit['root_class']}, visible=True, minimized=False, foreground=False, rect=None)

    def profile(self, *, has_point=False, x=0, y=0, target_hwnd=0, target_match=''):
        started = time.monotonic()
        raw = self.read('coordinate-snapshot', ['--x', str(x), '--y', str(y), '--has-point', 'true' if has_point else 'false',
            '--target-hwnd', '0'])
        virtual, monitors = raw['virtual_screen'], raw['monitors']
        point_monitor = raw['point_monitor'] if has_point else None
        hit = None
        if has_point and -2147483648 <= target_hwnd <= 2147483647:
            try:
                hit = self.hit(x, y, target_hwnd, target_match)
            except (OSError, ValueError, RuntimeError):
                self.remaining()  # Cancellation/deadlines remain terminal.
        target = next((row for row in self.read('windows', []) if row['hwnd'] == target_hwnd), None) if target_hwnd > 0 else None
        if not target and target_match:
            target = self._find(target_match)
        if not target and hit:
            target = self._precheck_window(hit)
        target_monitor, window_dpi = None, None
        if target:
            try:
                extra = self.read('coordinate-target', ['--target-hwnd', str(target['hwnd'])])
                target_monitor, window_dpi = extra['target_monitor'], extra['target_window_dpi']
            except (OSError, ValueError, RuntimeError):
                self.remaining()
        inside = virtual['x'] <= x < virtual['right'] and virtual['y'] <= y < virtual['bottom'] if has_point else None
        rect = target['rect'] if target else None
        in_target, relative, edge = None, None, None
        if has_point and rect:
            right, bottom = rect['x'] + rect['width'], rect['y'] + rect['height']
            in_target = rect['x'] <= x < right and rect['y'] <= y < bottom
            relative = dict(x=x - rect['x'], y=y - rect['y'],
                norm_x=round((x - rect['x']) / rect['width'] * 1000000) / 1000000 if rect['width'] > 0 else None,
                norm_y=round((y - rect['y']) / rect['height'] * 1000000) / 1000000 if rect['height'] > 0 else None)
            edge = dict(left=x - rect['x'], top=y - rect['y'], right=right - x - 1, bottom=bottom - y - 1)
            edge['min'] = min(edge.values())
        warnings, risk = [], 'low'
        if has_point and not inside:
            risk = 'high'; warnings.append('point_outside_virtual_screen')
        if has_point and rect and not in_target:
            risk = 'high'; warnings.append('point_outside_target_window')
        if has_point and edge and 0 <= edge['min'] < 4 and risk != 'high':
            risk = 'medium'; warnings.append('point_near_target_window_edge')
        if target_monitor and (target_monitor['dpi']['scale_x'] != 1 or target_monitor['dpi']['scale_y'] != 1):
            if risk == 'low': risk = 'medium'
            warnings.append('non_100_percent_dpi_scale')
        if virtual['monitor_count'] > 1:
            if risk == 'low': risk = 'medium'
            warnings.append('multi_monitor_coordinates')
        if has_point and point_monitor and target_monitor and point_monitor['device'] and target_monitor['device'] and not _ps_equal(point_monitor['device'], target_monitor['device']):
            risk = 'high'; warnings.append('point_monitor_differs_from_target_window_monitor')
        if hit and (target_match or target_hwnd > 0) and not hit['matched']:
            risk = 'high'; warnings.append('win32_hit_test_target_mismatch')
        signature = [f"vs={virtual['x']},{virtual['y']},{virtual['width']},{virtual['height']}"]
        signature += [f"m={m['device']}:{m['rect']['x']},{m['rect']['y']},{m['rect']['width']},{m['rect']['height']}:{m['dpi']['x']}x{m['dpi']['y']}" for m in monitors]
        if target: signature.append('target=' + str(target['hwnd']))
        return dict(schema='cucp.coord-profile/v1', status='ok', point=dict(x=x, y=y) if has_point else None,
            has_point=has_point, coordinate_risk=risk, warnings=warnings, virtual_screen=virtual, monitors=monitors,
            point_inside_virtual_screen=inside, point_monitor=point_monitor, target_window={key: target[key] for key in
                ('hwnd', 'title', 'process', 'class', 'foreground', 'rect')} if target else None, target_monitor=target_monitor,
            target_window_dpi=window_dpi, point_inside_target_window=in_target, point_window_relative=relative,
            edge_distance_to_target=edge, hit_test=hit, coord_signature='|'.join(signature),
            elapsed_ms=round((time.monotonic() - started) * 1000), next_step=
            'Use point-plan for micro-refined click planning; if coordinate_risk is high, re-ground with app-profile or smart-plan before live control.' if has_point else
            'Use this profile to understand DPI/monitor layout before planning coordinate clicks.')

    def map(self, *, source='screen', x=0, y=0, norm_x=0, norm_y=0, has_norm=False, target_hwnd=0, target_match='', synthetic_fallback=True):
        started = time.monotonic()
        snapshot = self.read('coordinate-snapshot', [])
        window = next((row for row in self.read('windows', []) if row['hwnd'] == target_hwnd), None) if target_hwnd > 0 else None
        if not window and target_match:
            window = self._find(target_match)
        if not window and source.lower() == 'screen':
            try:
                hit = self.hit(int32(round(x)), int32(round(y)))
                window = self._precheck_window(hit, synthetic=synthetic_fallback)
            except (OSError, ValueError, RuntimeError):
                self.remaining()
        virtual = {key: item for key, item in snapshot['virtual_screen'].items() if key != 'same_display_format'}
        result = compatibility('coord-map', dict(**{'from': source or 'screen'}, x=x, y=y, norm_x=norm_x, norm_y=norm_y,
            has_norm=has_norm, target_hwnd=target_hwnd, target_match=target_match, virtual_screen=virtual, selected_window=window),
            culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled)
        require(result.get('schema') == 'cucp.coord-map/v1' and result.get('status') in {'ok', 'partial'}, 'Invalid coordinate mapping response.')
        if result['status'] == 'ok' and result.get('screen_point'):
            point = result['screen_point']
            profile = self.profile(has_point=True, x=point['x'], y=point['y'], target_hwnd=window['hwnd'] if window else 0)
            result['coordinate_profile'] = profile
            if profile['coordinate_risk'] == 'high':
                result['warnings'] += ['coordinate_profile_high_risk', *profile['warnings']]
        result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        return result
