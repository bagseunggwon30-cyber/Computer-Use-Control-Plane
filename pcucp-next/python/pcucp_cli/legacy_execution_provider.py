"""Closed Python effect acquisition for all seven retained execution coordinators.

The existing C# coordinator owns policy and reporting. Python owns leaf calls,
inherited authority/deadlines, and the exact set of invocation capture paths.
Callbacks are trusted constructor ports, never names/functions from the wire.
"""
from __future__ import annotations
from datetime import datetime
import math
import re
import time
from .legacy_diagnostic_provider import owned_path, timestamp
from .legacy_host_protocol import Authority, exact, require
from .legacy_values import int32
from .legacy_workflow_plan import workflow_plan

OPERATIONS = frozenset(('workflow-run', 'task-run', 'form-run', 'smart-click', 'watch', 'recovery-plan', 'recovery-run'))
KINDS = frozenset('WorkflowPlan Child Native LocalMacro CdpPort HistoryRead HistoryAppend TrajectoryAppend Sleep '
    'Clock Timestamp CachePath FileExists RemoveFile SendEscape Console'.split())
PORTS = frozenset(('Child', 'Native', 'LocalMacro', 'CdpPort', 'HistoryRead', 'HistoryAppend', 'TrajectoryAppend', 'SendEscape'))
NATIVE_FIELDS = {
    'focused': (), 'modal-detect': ('Match',),
    'uia-find': ('Label', 'Match', 'Role'), 'uia-invoke': ('Label', 'Match', 'Role'), 'uia-click': ('Label', 'Match', 'Role'),
    'cdp-smart-click': ('CdpText', 'CdpPort', 'CdpPageMatch'),
    'ocr-uia-invoke': ('OcrText', 'OcrMatch', 'OcrMaxCandidates', 'Match', 'OcrLanguage'),
    'ocr-find-text': ('OcrText', 'OcrMatch', 'OcrMaxCandidates', 'Match', 'OcrLanguage'),
    'click': ('X', 'Y', 'Button', 'ClickRefine', 'TargetMatch'),
    'screenshot': ('OutPath', 'ScreenshotX', 'ScreenshotY', 'ScreenshotW', 'ScreenshotH'),
    'screenshot-diff': ('DiffBefore', 'DiffAfter', 'DiffThreshold'),
}
LIVE_NATIVE = frozenset(('uia-invoke', 'uia-click', 'click', 'ocr-uia-invoke', 'cdp-smart-click'))


class ExecutionProvider:
    def __init__(self, *, operation, rest, authority, cache_directory, culture='en-US', brief=False,
                 cache_seconds=2, vision_available=False, ports=None, parent_deadline=math.inf, on_session=None):
        require(operation in OPERATIONS and type(authority) is Authority and type(rest) is list and
            all(type(value) is str for value in rest), 'Invalid execution owner startup.')
        self.operation, self.rest, self.authority = operation, list(rest), authority
        self.cache_directory = owned_path(str(cache_directory))
        self.culture, self.brief = culture, brief
        self.cache_seconds, self.vision_available = int32(cache_seconds), vision_available
        self.ports = dict(ports or {})
        require(not (set(self.ports) - PORTS) and all(callable(port) for port in self.ports.values()), 'Unknown execution port.')
        self.parent_deadline, self.on_session = parent_deadline, on_session
        self.deadline, self.cancelled = math.inf, None
        self.clocks, self.paths, self.console = {}, set(), []

    def startup(self):
        return dict(schema='cucp.execution-start/v1', operation=self.operation, rest=self.rest,
            brief=self.brief, cache_seconds=self.cache_seconds, vision_available=self.vision_available, culture=self.culture)

    def bind_session(self, deadline, cancelled):
        self.deadline, self.cancelled = deadline, cancelled
        if self.on_session:
            self.on_session(deadline, cancelled)

    def remaining(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'Execution owner cancelled; action not retried.')
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'Execution owner timed out; action not retried.')
        return remaining

    def validate_startup(self, family, startup, authority):
        require(family == 'execution' and startup == self.startup() and authority == self.authority,
            'Execution startup or immutable authority changed.')

    def validate(self, effect):
        kind, name, argv, data = effect.kind, effect.name, effect.argv, effect.data
        require(kind in KINDS, 'Effect is outside the original execution surface.')
        self.authority.restrict(effect.live, effect.confirm_sensitive)
        require(kind == 'Child' or not effect.quiet and not effect.brief, 'Non-child effect changed child output options.')
        require(kind in {'Child', 'SendEscape'} or not effect.confirm_sensitive, 'Unexpected sensitive execution option.')
        require(kind in {'Child', 'Native', 'LocalMacro', 'SendEscape'} or not effect.live, 'Unexpected live execution option.')
        if kind in {'WorkflowPlan', 'Child', 'Native', 'LocalMacro', 'CdpPort', 'HistoryRead'}:
            require(data is None, 'Unexpected execution acquisition payload.')
        if kind == 'WorkflowPlan':
            require(name == '', 'Invalid workflow acquisition descriptor.')
        elif kind == 'Child':
            require(name in {'', 'direct'}, 'Invalid child descriptor.')
        elif kind == 'Native':
            require(name == '' and len(argv) >= 2 and len(argv) % 2 == 0 and argv[0] == '-Action', 'Invalid native descriptor.')
            action, values = argv[1], {}
            require(action in NATIVE_FIELDS and effect.live == (action in LIVE_NATIVE), 'Native action/live classification mismatch.')
            for key, value in zip(argv[2::2], argv[3::2]):
                require(key in {'-' + field for field in NATIVE_FIELDS[action]} and key not in values, 'Invalid or duplicate native option.')
                values[key] = value
            if action == 'screenshot':
                require(values.get('-OutPath') in self.paths, 'Screenshot destination is not an invocation capture.')
            if action == 'screenshot-diff':
                require(values.get('-DiffBefore') in self.paths and values.get('-DiffAfter') in self.paths, 'Diff input is not an invocation capture.')
        elif kind == 'LocalMacro':
            require(name in {'click-point', 'icon-find'} and effect.live == (name == 'click-point'), 'Invalid local execution macro.')
        elif kind == 'CdpPort':
            require(name == '' and len(argv) == 2 and argv[1] == '120' and re.fullmatch(r'\d+', argv[0]), 'Invalid CDP port probe.')
        elif kind == 'HistoryRead':
            require(name == '' and len(argv) == 3 and argv[2] == '5', 'Invalid history query.')
        elif kind == 'HistoryAppend':
            require(name == '' and len(argv) == 3, 'Invalid history append descriptor.')
            exact(data, ('success', 'elapsed_ms'))
            require(type(data['success']) is bool and type(data['elapsed_ms']) is int and -(2**31) <= data['elapsed_ms'] < 2**31, 'Invalid history append payload.')
        elif kind == 'TrajectoryAppend':
            require(name in {'workflow-run', 'task-run', 'form-run'} and not argv, 'Invalid execution trajectory kind.')
            exact(data, ('status', 'dry_run', 'workflow_exit', 'elapsed_ms') if name == 'task-run' else
                  ('status', 'executed_count', 'failed_count', 'total_steps', 'elapsed_ms'))
        elif kind == 'Sleep':
            require(name == '' and not argv and type(data) is int and 0 <= data < 2**31, 'Invalid execution delay.')
        elif kind == 'Clock':
            require(name in {'start', 'stop', 'elapsed'} and not argv and type(data) is str and data in {'total', 'step', 'attempt', 'run'}, 'Invalid execution clock.')
        elif kind == 'Timestamp':
            require(name in {'o', 'HHmmss-fff'} and not argv and data is None, 'Invalid execution timestamp.')
        elif kind == 'CachePath':
            require(name in {'smartclick-before', 'smartclick-after', 'smartclick-retry-before', 'smartclick-retry-after'} and
                not argv and type(data) is str and re.fullmatch(r'\d{6}-\d{3}', data), 'Invalid execution capture name.')
        elif kind in {'FileExists', 'RemoveFile'}:
            require(name == '' and not argv and type(data) is str and data in self.paths, 'Execution capture is not owned by this invocation.')
        elif kind == 'SendEscape':
            require(name == '' and not argv and data is None and effect.live and effect.confirm_sensitive, 'Escape requires both explicit startup gates.')
        elif kind == 'Console':
            require(name == '' and not argv and type(data) is str, 'Invalid execution console output.')

    def dispatch(self, effect):
        self.remaining()
        kind, name, data = effect.kind, effect.name, effect.data
        if kind in PORTS:
            require(kind in self.ports, 'Required preserved execution port is unavailable: ' + kind)
            return self.ports[kind](effect, self)
        if kind == 'WorkflowPlan':
            return workflow_plan(list(effect.argv), culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled)
        if kind == 'Clock':
            now = time.monotonic()
            if name == 'start':
                self.clocks[data] = (now, None)
                return 0
            require(data in self.clocks, 'Execution clock has not started.')
            started, stopped = self.clocks[data]
            if name == 'stop':
                stopped = stopped or now
                self.clocks[data] = (started, stopped)
            return round(((stopped or now) - started) * 1000)
        if kind == 'Timestamp':
            return timestamp() if name == 'o' else datetime.now().strftime('%H%M%S-%f')[:-3]
        if kind == 'Sleep':
            end = time.monotonic() + data / 1000
            while time.monotonic() < end:
                remaining = self.remaining()
                delay = min(.025, remaining, max(0, end - time.monotonic()))
                if self.cancelled is not None:
                    self.cancelled.wait(delay)
                else:
                    time.sleep(delay)
            return None
        if kind == 'CachePath':
            self.cache_directory.mkdir(parents=True, exist_ok=True)
            path = str(owned_path(str(self.cache_directory / (name + '-' + data + '.png'))))
            self.paths.add(path)
            return path
        if kind == 'FileExists':
            return owned_path(data).exists()
        if kind == 'RemoveFile':
            try:
                owned_path(data).unlink(missing_ok=True)
            except OSError:
                pass
            return None
        if kind == 'Console':
            self.console.append(data)
            return None
        require(False, 'Unknown validated execution effect.')

    def validate_completion(self, result):
        # The retained smart-click command often reports only Console lines,
        # including an empty non-brief failure. Do not invent a JSON payload.
        require((type(result['payload']) is dict or self.operation == 'smart-click' and result['payload'] is None and
                 not result['emit_json']) and result['exit'] in (0, 1, 2, 3), 'Invalid execution completion.')
