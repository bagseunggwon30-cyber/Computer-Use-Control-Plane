"""Owned read-only coordinate runtime shared by production and the staged owner."""
import math
import time

from .legacy_coordinates import Coordinates
from .legacy_host_protocol import LegacyHostError, exact, require
from .native_session import NativeSession
from .legacy_native_kernel import compatibility
from .legacy_cdp_contract import ps_string

OPERATIONS = frozenset(('coord-profile', 'coord-map', 'hit-test-batch'))

READS = frozenset(('ensure-win32', 'windows', 'hit-test-point', 'coordinate-snapshot', 'coordinate-target'))


class CoordinateRuntime:
    def __init__(self, *, timeout_s=15, culture='en-US', modern=False, parent_deadline=math.inf, cancelled=None):
        require(type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0 and
                type(modern) is bool and type(culture) is str, 'Invalid coordinate startup.')
        self.deadline = min(parent_deadline, time.monotonic() + timeout_s)
        self.cancelled = cancelled
        self.native = NativeSession(allow_live_control=False)
        self.coordinates = Coordinates(self.read, culture=culture, remaining=self.remaining, cancelled=cancelled, modern=modern)

    def remaining(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'Coordinate owner cancelled; no retry attempted.')
        result = self.deadline - time.monotonic()
        require(result > 0, 'Coordinate deadline expired; no retry attempted.')
        return result

    def close(self):
        self.native.close()

    def read(self, operation, argv):
        require(operation in READS, 'Unknown coordinate acquisition.')
        code, payload, error = self.native('legacy-diagnostic-read', ['--operation', operation, *argv], timeout_s=self.remaining())
        self.remaining()
        require(code == 0 and type(payload) is dict and type(payload.get('data')) is dict and
                'value' in payload['data'], error or 'Coordinate acquisition failed.')
        return payload['data']['value']

    def value(self, action, args):
        require(action in ('profile', 'map', 'hit', 'batch'), 'Unknown coordinate operation.')
        if action == 'batch':
            exact(args, ('points', 'maximum', 'target_hwnd', 'target_match'))
            require(type(args['points']) is list and all(type(p) is str for p in args['points']) and
                    type(args['maximum']) is int and -(2**31) <= args['maximum'] < 2**31 and
                    type(args['target_hwnd']) is int and -(2**31) <= args['target_hwnd'] < 2**31 and
                    (args['target_match'] is None or type(args['target_match']) is str), 'Invalid batch values.')
            started = time.monotonic()
            plan = compatibility('coord-batch-points', dict(points=args['points'], maximum=args['maximum']),
                                 culture=self.coordinates.culture, timeout_s=self.remaining(), cancelled=self.cancelled)
            require(plan.get('schema') == 'cucp.coord-batch-points/v1', 'Invalid point parse plan.')
            results = []
            if plan['valid']:
                require(self.read('ensure-win32', []), 'Win32 load failed')
                for point in plan['valid']:
                    hit = self.coordinates.hit(point['x'], point['y'], args['target_hwnd'], args['target_match'] or '')
                    results.append({**hit, 'index': point['index']})
            errors = plan['errors']
            matched = sum(bool(row['matched']) for row in results)
            partial = sum(row['status'].lower() != 'ok' for row in results)
            safe = bool(results) and not errors and not partial
            return dict(schema='cucp.hit-test-batch/v1', status='ok' if safe else 'partial', source='wrapper_win32_fast',
                        uia_skipped=True, target_hwnd=args['target_hwnd'], target_match=args['target_match'],
                        point_count=len(args['points']), result_count=len(results), matched_count=matched, partial_count=partial,
                        error_count=len(errors), safe_to_act=safe, elapsed_ms=round((time.monotonic()-started)*1000),
                        results=results, errors=errors)
        fields = ('x', 'y', 'target_hwnd', 'target_match')
        exact(args, (*fields, 'has_point') if action == 'profile' else
              (*fields, 'source', 'norm_x', 'norm_y', 'has_norm') if action == 'map' else fields)
        require(type(args['target_hwnd']) is int and -(2**63) <= args['target_hwnd'] < 2**63 and
                type(args['target_match']) is str, 'Invalid coordinate target.')
        if action in ('profile', 'hit'):
            require(all(type(args[k]) is int and -(2**31) <= args[k] < 2**31 for k in ('x', 'y')),
                    'Coordinate point must be Int32.')
            if action == 'hit':
                require(-(2**31) <= args['target_hwnd'] < 2**31, 'Hit target must be Int32.')
            else:
                require(type(args['has_point']) is bool, 'Coordinate point flag must be boolean.')
        else:
            require(type(args['source']) is str and type(args['has_norm']) is bool and
                    all(type(args[k]) in (int, float) and math.isfinite(args[k]) for k in ('x', 'y', 'norm_x', 'norm_y')),
                    'Invalid coordinate mapping values.')
        try:
            available = self.read('ensure-win32', [])
        except (OSError, LegacyHostError):
            self.remaining()
            available = False
        if not available:
            if action == 'hit':
                raise LegacyHostError('Win32 load failed')
            return dict(schema=f'cucp.coord-{action}/v1', status='partial', reason='win32_load_failed', elapsed_ms=0)
        return getattr(self.coordinates, action)(**args)

    def run(self, name, rest, *, brief=False):
        require(name in OPERATIONS and type(rest) is list and all(type(p) is str for p in rest) and
                type(brief) is bool, 'Invalid coordinate macro.')
        prepared = compatibility('coord-macro-prepare', dict(name=name, rest=rest), culture=self.coordinates.culture,
                                 timeout_s=self.remaining(), cancelled=self.cancelled)
        value = self.value(prepared['action'], prepared['args'])
        rendered = brief and not prepared['json_only']
        if name == 'coord-profile':
            virtual = value.get('virtual_screen') or {}
            line = f"{value['status']} coord-profile risk={ps_string(value.get('coordinate_risk'))} monitors={ps_string(virtual.get('monitor_count'))} warnings={len(value['warnings']) if 'warnings' in value else 1} elapsed_ms={value['elapsed_ms']}"
        elif name == 'coord-map':
            point = value.get('screen_point')
            screen = f"{point['x']},{point['y']}" if point else 'none'
            line = f"{value['status']} coord-map from={prepared['display_from']} screen={screen} inside={ps_string(value.get('inside_window'))} warnings={len(value['warnings']) if 'warnings' in value else 1} elapsed_ms={value['elapsed_ms']}"
        else:
            line = f"{value['status']} hit-test-batch points={value['point_count']} matched={value['matched_count']} partial={value['partial_count']} errors={value['error_count']} elapsed_ms={value['elapsed_ms']}"
        return dict(payload=value, exit=0 if value['status'] == 'ok' else 2, json_depth=10 if name == 'hit-test-batch' else 12,
                    brief=line if rendered else None, emit_json=not rendered)


def handle(request, *, timeout_s=15, culture='en-US', modern=False):
    require(type(request) is dict, 'Coordinate request must be an object.')
    if request.get('action') == 'macro':
        exact(request, ('action', 'name', 'rest', 'brief'))
    else:
        exact(request, ('action', 'args'))
        require(type(request['action']) is str and type(request['args']) is dict, 'Invalid coordinate request.')
    runtime = CoordinateRuntime(timeout_s=timeout_s, culture=culture, modern=modern)
    try:
        if request['action'] == 'macro':
            return runtime.run(request['name'], request['rest'], brief=request['brief'])
        return dict(value=runtime.value(request['action'], request['args']))
    finally:
        runtime.close()
