"""Closed owned effects for the retained interaction coordinators."""
import json
import math
import re
import time
import uuid
from .legacy_diagnostic_provider import timestamp
from .legacy_host_protocol import Authority, exact, require

ALLOWED = {
    'find-label': {'Clock', 'Timestamp', 'Win32Windows', 'Appshot'},
    'icon-find': {'Clock', 'Timestamp', 'UIAffordances'},
    'click-label': {'Clock', 'Timestamp', 'UIAffordances', 'Appshot', 'Notice', 'Vision', 'Cucp', 'TrajectoryAppend', 'PipelineOutput'},
    'icon-click': {'Clock', 'Timestamp', 'UIAffordances', 'Appshot', 'ObservationId', 'Cucp'},
    'safe-type': {'Native'}, 'ocr-click': {'Native', 'TrajectoryAppend', 'Console'},
    'click-point': {'Clock', 'Timestamp', 'HitTestPoint', 'PointCacheRead', 'PointCacheWrite', 'CoordProfile',
        'AnchorScore', 'AnchorAppend', 'Native', 'TrajectoryAppend', 'Console'},
    'precision-validate': {'Clock', 'Native', 'Sleep'},
}
NATIVE = {
    'windows': (set(), set()), 'focus': ({'WindowHwnd'}, {'WindowHwnd'}),
    'click': ({'X', 'Y', 'Button', 'TargetMatch', 'TargetHwnd', 'ClickRefine', 'ClickInset'}, {'X', 'Y'}),
    'type': ({'Text', 'TargetHwnd'}, {'Text', 'TargetHwnd'}), 'shortcut': ({'Keys', 'TargetHwnd'}, {'Keys', 'TargetHwnd'}),
    'ocr-find-text': ({'OcrText', 'OcrMatch', 'OcrMaxCandidates', 'OcrLanguage', 'Match', 'ScreenshotX', 'ScreenshotY', 'ScreenshotW', 'ScreenshotH'},
        {'OcrText', 'OcrMatch', 'OcrMaxCandidates'}),
    'hit-scan': ({'X', 'Y', 'ClickInset', 'ScanRadius', 'ScanStep', 'TargetMatch', 'TargetHwnd'}, {'X', 'Y', 'ScanRadius', 'ScanStep'}),
}
NATIVE_OPERATIONS = {'safe-type': {'windows', 'focus', 'click', 'type', 'shortcut'}, 'ocr-click': {'ocr-find-text', 'click'},
    'click-point': {'hit-scan', 'click'}, 'precision-validate': {'hit-scan'}}
LIVE_NATIVE = {'focus', 'click', 'type', 'shortcut'}
RECORD_FIELDS = ('ts', 'anchor_id', 'anchor_type', 'target_match', 'target_hwnd_current', 'process', 'class', 'title',
    'source_point', 'screen_point', 'normalized_window_point', 'visible_normalized_point', 'safe_to_reuse', 'coordinate_risk', 'coord_signature', 'window_rect')


def pairs(argv, start, allowed, required):
    require((len(argv) - start) % 2 == 0, 'Interaction argument arity changed.')
    result = {}
    for key, value in zip(argv[start::2], argv[start + 1::2]):
        require(key in allowed and key not in result, 'Unknown or duplicate interaction argument.')
        result[key] = value
    require(required <= set(result), 'Missing required interaction argument.')
    return result


class InteractionProvider:
    def __init__(self, *, operation, rest, authority=Authority(), culture='en-US', brief=False, cache_seconds=2,
                 vision_available=False, double=False, right_click=False, ports=None, parent_deadline=float('inf')):
        require(operation in ALLOWED and type(rest) is list and all(type(word) is str for word in rest), 'Invalid interaction startup.')
        self.operation, self.rest, self.authority = operation, list(rest), authority
        self.culture, self.brief, self.cache_seconds, self.vision_available = culture, brief, cache_seconds, vision_available
        self.double, self.right_click, self.parent_deadline = double, right_click, parent_deadline
        self.ports = dict(ports or {})
        require(not (set(self.ports) - set().union(*ALLOWED.values())) and all(callable(port) for port in self.ports.values()), 'Unknown interaction port.')
        self.deadline, self.cancelled = float('inf'), None
        self.observations, self.screenshots, self.cache_keys, self.records = set(), set(), set(), set()
        self.clocks, self.console, self.pipeline = {}, [], []

    def startup(self):
        return dict(schema='cucp.interaction-start/v1', operation=self.operation, rest=self.rest, brief=self.brief,
            cache_seconds=self.cache_seconds, vision_available=self.vision_available, culture=self.culture,
            double=self.double, right_click=self.right_click)

    def bind_session(self, deadline, cancelled):
        self.deadline, self.cancelled = deadline, cancelled

    def remaining(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'Interaction owner cancelled; action not retried.')
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'Interaction deadline expired; action not retried.')
        return remaining

    def validate_startup(self, family, startup, authority):
        require(family == 'interaction' and startup == self.startup() and authority == self.authority, 'Interaction startup or authority changed.')

    @staticmethod
    def record(record):
        exact(record, RECORD_FIELDS)
        require(type(record['anchor_id']) is str and re.fullmatch(r'[a-f0-9]{32}', record['anchor_id']) and
            record['anchor_type'] == 'click_point_live_route' and type(record['target_hwnd_current']) is int and
            type(record['safe_to_reuse']) is bool and (record['target_match'] is None or type(record['target_match']) is str),
            'Invalid interaction anchor identity.')
        for key in ('ts', 'process', 'class', 'title', 'coordinate_risk', 'coord_signature'):
            require(type(record[key]) is str, 'Invalid anchor text.')
        for key in ('source_point', 'screen_point', 'normalized_window_point', 'visible_normalized_point'):
            exact(record[key], ('x', 'y'))
            types = (int, float) if 'normalized' in key else (int,)
            require(all(type(value) in types and (type(value) is not float or math.isfinite(value)) for value in record[key].values()), 'Invalid anchor point.')

    def validate(self, effect):
        kind, name, argv, data = effect.kind, effect.name, effect.argv, effect.data
        require(kind in ALLOWED[self.operation], 'Effect is outside the selected interaction operation.')
        self.authority.restrict(effect.live, effect.confirm_sensitive)
        require(not effect.quiet and not effect.brief and not effect.confirm_sensitive, 'Unexpected interaction effect options.')
        require(kind in {'Native', 'Cucp'} or not effect.live and not argv, 'Unexpected interaction argv/input capability.')
        require(kind in {'Notice', 'ObservationId', 'TrajectoryAppend', 'Clock', 'Timestamp', 'Console'} or name == '', 'Unexpected interaction effect name.')
        if kind == 'Native':
            require(name == '' and data is None and len(argv) >= 2 and argv[0] == '-Action' and
                argv[1] in NATIVE_OPERATIONS.get(self.operation, set()), 'Invalid native interaction acquisition.')
            action = argv[1]
            require(effect.live == (action in LIVE_NATIVE), 'Interaction native/live classification changed.')
            allowed, required = NATIVE[action]
            values = pairs(argv, 2, {'-' + key for key in allowed}, {'-' + key for key in required})
            if action == 'shortcut':
                require(values['-Keys'] in {'enter', 'ctrl+enter'}, 'Unexpected submit shortcut.')
            if action == 'ocr-find-text':
                require(values['-OcrMaxCandidates'] == '8' and len(set(values) & {'-ScreenshotX', '-ScreenshotY', '-ScreenshotW', '-ScreenshotH'}) in {0, 4},
                    'Interaction OCR region/candidate count changed.')
        elif kind == 'Cucp':
            require(name == '' and data is None and effect.live and len(argv) >= 2 and argv[0] == 'act' and argv[1] in {'click', 'right-click'}, 'Invalid interaction CLI action.')
            values = pairs(argv, 2, {'--x', '--y', '--after', '--target-window'}, {'--x', '--y', '--after'})
            require(values['--after'] in self.observations, 'Action observation was not acquired by this interaction.')
        elif kind == 'Appshot':
            exact(data, ('match', 'semantic', 'no_cache'))
            require(type(data['match']) is str and data['semantic'] is True and type(data['no_cache']) is bool, 'Invalid interaction appshot.')
        elif kind == 'Win32Windows':
            exact(data, ('match',)); require(type(data['match']) is str, 'Invalid interaction window query.')
        elif kind == 'UIAffordances':
            exact(data, ('focused_window', 'max_elements'))
            require(type(data['focused_window']) is str and type(data['max_elements']) is int and data['max_elements'] == 800, 'Invalid UIA acquisition bounds.')
        elif kind == 'Vision':
            exact(data, ('screenshot_path', 'description'))
            require(type(data['description']) is str and data['screenshot_path'] in self.screenshots, 'Vision input was not acquired by this interaction.')
        elif kind in {'HitTestPoint', 'CoordProfile'}:
            exact(data, ('x', 'y', 'target_hwnd', 'target_match') + (('has_point',) if kind == 'CoordProfile' else ()))
            require(all(type(data[key]) is int for key in ('x', 'y', 'target_hwnd')) and type(data['target_match']) is str and
                (kind != 'CoordProfile' or data['has_point'] is True), 'Invalid interaction coordinate acquisition.')
        elif kind in {'PointCacheRead', 'PointCacheWrite'}:
            exact(data, ('key', 'max_age_seconds') if kind == 'PointCacheRead' else ('key', 'payload'))
            require(type(data['key']) is str and re.fullmatch(r'[a-f0-9]{32}', data['key']), 'Invalid interaction cache key.')
            if kind == 'PointCacheRead':
                require(type(data['max_age_seconds']) is int and data['max_age_seconds'] > 0, 'Invalid point cache age.')
            else:
                require(data['key'] in self.cache_keys, 'Cache write lacks an acquired key.')
                payload = data['payload']
                exact(payload, ('schema', 'status', 'mode', 'source', 'x', 'y', 'radius', 'step', 'click_inset', 'target_hwnd', 'target_match',
                    'from_cache', 'cache_ttl_seconds', 'cache_key', 'confidence', 'safe_to_act', 'mouse_moved', 'reason', 'precheck', 'best',
                    'recommended_point', 'recommended_command', 'checks', 'scan'))
                require(payload['schema'] == 'cucp.point-plan/v1' and payload['status'] == 'ok' and payload['mode'] == 'coordinate_click' and
                    payload['cache_key'] == data['key'] and payload['source'] == 'click_point_micro_refine' and payload['safe_to_act'] is True and
                    payload['from_cache'] is False and payload['mouse_moved'] is True and payload['reason'] == '' and
                    payload['recommended_command'] is None and type(payload['confidence']) is str and type(payload['checks']) is list and
                    len(payload['checks']) == 2 and (payload['target_match'] is None or type(payload['target_match']) is str), 'Invalid micro-refine cache evidence.')
                require(all(type(payload[key]) is int for key in ('x', 'y', 'radius', 'step', 'click_inset', 'target_hwnd', 'cache_ttl_seconds')),
                    'Invalid numeric micro-refine cache field.')
        elif kind in {'AnchorScore', 'AnchorAppend'}:
            exact(data, ('record',)); self.record(data['record'])
            if kind == 'AnchorAppend':
                require(json.dumps(data['record'], sort_keys=True, allow_nan=False) in self.records, 'Anchor append has no matching scored record.')
        elif kind == 'Notice':
            require(name in {'WARN', 'ERROR'} and type(data) is str, 'Invalid interaction notice.')
        elif kind == 'PipelineOutput':
            require(type(data) is str, 'Invalid interaction pipeline output.')
        elif kind == 'ObservationId':
            require(name == 'icon-click' and data is None, 'Invalid observation identifier request.')
        elif kind == 'TrajectoryAppend':
            require(name == 'click' and type(data) is dict and (data.get('source') in {'icon_find_fallback', 'vision_fallback', 'ocr_click', 'native_click_point'} or
                set(data) == {'label', 'window', 'role', 'x', 'y', 'observation_id', 'exit', 'double', 'right'}), 'Invalid interaction trajectory source.')
        elif kind == 'Clock':
            require(name in {'start', 'stop', 'elapsed'} and type(data) is str and data in {'find-label', 'icon-find', 'click-point-precheck', 'precision-validate'}, 'Invalid interaction clock.')
        elif kind == 'Timestamp':
            require(name == 'o' and data is None, 'Invalid interaction timestamp.')
        elif kind == 'Sleep':
            require(name == '' and type(data) is int and data == 30, 'Invalid precision validation delay.')
        elif kind == 'Console':
            require(name == 'write' and type(data) is str, 'Invalid interaction raw output.')

    def dispatch(self, effect):
        self.remaining()
        kind, name, data = effect.kind, effect.name, effect.data
        if kind == 'Clock':
            now = time.monotonic()
            if name == 'start': self.clocks[data] = (now, None); return 0
            require(data in self.clocks, 'Interaction clock has not started.')
            start, stopped = self.clocks[data]
            if name == 'stop': stopped = stopped or now; self.clocks[data] = (start, stopped)
            return round(((stopped or now) - start) * 1000)
        if kind == 'Timestamp': return timestamp()
        if kind == 'Console': self.console.append(data); return None
        if kind == 'PipelineOutput': self.pipeline.append(data); return None
        if kind == 'ObservationId':
            value = 'icon-click-' + uuid.uuid4().hex[:12]; self.observations.add(value); return value
        if kind == 'Sleep':
            self.cancelled.wait(data / 1000); self.remaining(); return None
        require(kind in self.ports, 'Required preserved interaction port is unavailable: ' + kind)
        value = self.ports[kind](effect, self)
        if kind == 'Appshot' and value:
            self.observations.add(str(value['ObservationId'])); self.screenshots.add(str(value['ScreenshotPath']))
        if kind == 'PointCacheRead': self.cache_keys.add(data['key'])
        if kind == 'AnchorScore': self.records.add(json.dumps(data['record'], sort_keys=True, allow_nan=False))
        return value

    def validate_completion(self, result):
        require(result['payload'] is None or type(result['payload']) is dict, 'Invalid interaction completion payload.')
