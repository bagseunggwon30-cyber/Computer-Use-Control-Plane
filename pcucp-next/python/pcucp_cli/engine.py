"""Provider-neutral, serialized computer-use session. No model API or shell evaluation."""
from __future__ import annotations
import base64
import math
import secrets
import sys
import threading
import json
from pathlib import PureWindowsPath
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from .native_host import run_native, native_host_available
from .registry import COMMANDS, capabilities
from .workflows import WorkflowError
from .validation import ValidationError

MAX_BATCH = 12
KEYS = set('ENTER TAB ESC ESCAPE BACKSPACE DELETE SPACE LEFT RIGHT UP DOWN HOME END PAGEUP PAGEDOWN SHIFT+TAB ALT+F4'.split())
KEYS.update(f'F{i}' for i in range(1, 13))
KEYS.update(f'CTRL+{k}' for k in 'A C V X Z Y S F L HOME END'.split())

class EngineError(Exception):
    def __init__(self, code, message, status='error'):
        super().__init__(message)
        self.code, self.status = code, status

def errors_list(values):
    if not isinstance(values, list):
        values = [values]
    return [{'code': str(v.get('code', 'native_error')), 'message': str(v.get('message', v))}
            if isinstance(v, dict) else {'code': 'native_error', 'message': str(v)} for v in values]

def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise EngineError('invalid_argument', f'{name} must be integer [{low}, {high}]')
    return value

def input_text(value, *, allow_empty=False):
    if not isinstance(value, str) or '\x00' in value:
        raise EngineError('invalid_argument', 'text must be a Unicode string without NUL')
    try:
        units = len(value.encode('utf-16-le')) // 2
    except UnicodeError:
        raise EngineError('invalid_argument', 'text must not contain unpaired Unicode surrogates') from None
    if not (0 if allow_empty else 1) <= units <= 4096:
        raise EngineError('invalid_argument', 'text exceeds 4096 UTF-16 units or is empty')
    return value

def hwnd_value(value):
    try:
        if not isinstance(value, str) or len(value) > 18:
            raise ValueError()
        number = int(value, 16) if value.lower().startswith('0x') else int(value)
        if not 0 < number < 2**64:
            raise ValueError()
        return f'0x{number:X}'
    except ValueError:
        raise EngineError('invalid_argument', 'hwnd must be a positive handle returned by windows') from None

def fields(args, allowed, required=frozenset()):
    unknown, missing = set(args) - set(allowed), set(required) - set(args)
    if unknown or missing:
        raise EngineError('invalid_argument', f'unknown fields: {sorted(unknown)}; missing: {sorted(missing)}')

@dataclass
class Observation:
    id: str
    created: float
    target: dict
    geometry: dict
    window_geometry: dict
    elements: dict = field(default_factory=dict)
    ui_available: bool = False
    ocr: dict | None = None
    ui_nodes: list = field(default_factory=list)

class ComputerSession:
    """One owner per session. Host-side live permission cannot be changed by a request."""
    def __init__(self, *, allow_live_control=False, native: Callable=run_native,
                 clock: Callable=time.monotonic, sleep: Callable=time.sleep,
                 observation_ttl_s=60, native_transport="published executable per call"):
        self.native_transport = native_transport
        self.allow_live_control = bool(allow_live_control)
        self.native, self.clock, self.sleep, self.ttl = native, clock, sleep, observation_ttl_s
        self.observation = None
        self.snapshots = deque(maxlen=2)
        self.cancelled = threading.Event()
        self.seen, self.order = set(), deque()
        self.events = deque(maxlen=200)
        from .workflows import Recorder
        self.recorder = Recorder()

    def cancel(self):
        """Terminal cancellation; the host must create a new session and re-observe."""
        self.cancelled.set()

    def handle(self, request: Any) -> dict:
        started, rid, command = self.clock(), None, None
        try:
            if not isinstance(request, dict):
                raise EngineError('invalid_request', 'request must be object')
            rid, command = request.get('id'), request.get('command')
            if not isinstance(rid, str) or not 1 <= len(rid) <= 128:
                rid = None
                raise EngineError('invalid_request', 'id must be string with 1..128 characters')
            if not isinstance(command, str):
                command = None
                raise EngineError('invalid_request', 'command must be string')
            if set(request) - {'schema', 'id', 'command', 'args'} or request.get('schema') != 'cucp.request/v1':
                raise EngineError('invalid_request', 'expected cucp.request/v1: schema,id,command,args')
            if rid in self.seen:
                raise EngineError('duplicate_request', 'id already used; mutation is never replayed automatically')
            self.seen.add(rid)
            self.order.append(rid)
            if len(self.order) > 1024:
                self.seen.discard(self.order.popleft())
            args = request.get('args', {})
            if not isinstance(args, dict):
                raise EngineError('invalid_argument', 'args must be object')
            status, data, errors = self.execute(command, args, started + 60)
        except (EngineError, WorkflowError, ValidationError) as exc:
            status, data, errors = exc.status, {}, [{'code': exc.code, 'message': str(exc)}]
        except Exception as exc:
            self.observation = None
            status, data, errors = 'error', {}, [{'code': 'internal_error', 'message': f'{type(exc).__name__}: {exc}'}]
        duration = round((self.clock() - started) * 1000, 3)
        self.events.append({'id': rid, 'command': command, 'status': status, 'duration_ms': duration,
                            'error_codes': [e['code'] for e in errors]})
        self.recorder.append(self.events[-1])
        return {'schema': 'cucp.response/v1', 'id': rid, 'command': command,
                'status': status, 'data': data, 'errors': errors, 'duration_ms': duration}

    def call_native(self, command, args, deadline):
        if self.cancelled.is_set():
            raise EngineError("session_cancelled", "session cancelled; input may have occurred; never retry automatically", "blocked")
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise EngineError('deadline_exceeded', 'deadline reached; next action not started')
        code, payload, error = self.native(command, args, timeout_s=min(15, remaining))
        if payload is None:
            return 'error', {}, [{'code': 'native_unavailable', 'message': error or f'native exit {code}'}]
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
            return 'error', {}, [{'code': 'native_protocol_error', 'message': 'native response and data must be objects'}]
        status, errors = payload.get('status', 'error'), errors_list(payload.get('errors', []))
        if (code and status == 'ok') or status not in {'ok', 'partial', 'error', 'blocked'}:
            status = 'error'
        if status != 'ok' and not errors:
            errors = [{'code': 'native_failed', 'message': error or f'native exit {code}: {status}'}]
        return status, payload.get('data', {}), errors

    def execute(self, command, args, deadline, *, allow_latest=False):
        if self.cancelled.is_set():
            self.observation = None
            raise EngineError("session_cancelled", "restart session and observe again", "blocked")
        spec = COMMANDS.get(command)
        if spec is None or not spec.available_in_engine:
            raise EngineError('unknown_command', f'command not exposed by engine: {command}', 'blocked')
        if spec.effect == 'write' and not self.allow_live_control:
            raise EngineError('live_control_required', 'human operator must enable live control', 'blocked')
        from .mcp_server import SCHEMAS
        from .validation import validate
        validate(args, SCHEMAS[command])
        if command == 'capabilities':
            fields(args, [])
            return 'ok', {'commands': capabilities(), 'allow_live_control': self.allow_live_control,
                          'platform': 'windows', 'max_batch': MAX_BATCH, 'observation_ttl_s': self.ttl,
                          'runtime_platform': sys.platform, 'native_host_configured': native_host_available(),
                          'request_id_retention': 1024,
                          'coordinate_space': 'returned screenshot image pixels', 'keys': sorted(KEYS),
                          'automatic_retry': False, 'native_transport': self.native_transport,
                          'workflow': {'max_steps': 64, 'max_duration_ms': 60000, 'stop_on_error': True, 'mutation_retry': False, 'background_execution': False},
                          'observation_cache': {'snapshots': 2, 'storage': 'session_memory', 'automatic_persistence': False},
                          'recording': {'storage': 'session_memory', 'max_events': 1000, 'records_text': False, 'replayable': False},
                          'text_input': {'type': 'Unicode SendInput packets; not physical IME composition',
                                         'max_utf16_units': 4096, 'clipboard_used': False,
                                         'uia_set_value': 'writable non-password ValuePattern only'},
                          'drag': {'button': 'left', 'max_steps': 64, 'timed_dwell': False, 'cross_window': False}}, []
        if command in {'workflow-plan', 'workflow-run', 'task-build', 'task-run', 'form-plan', 'form-run', 'watch', 'record-start', 'record-stop', 'record-read', 'app-profile', 'recovery-plan'}:
            return self.workflow_command(command, args, deadline)
        if command == 'history':
            fields(args, [])
            return 'ok', {'events': list(self.events)}, []
        if command == 'windows':
            fields(args, [])
            return self.call_native(command, [], deadline)
        if command == 'wait-window':
            return self.wait_window(args, deadline)
        if command == 'privileges':
            fields(args, ['pid'])
            native_args = ['--pid', str(integer(args['pid'], 'pid', 1, 2**31-1))] if 'pid' in args else []
            return self.call_native(command, native_args, deadline)
        if command in {'ocr-find', 'ocr-uia-fuse', 'screenshot-diff'}:
            return self.process_observation(command, args, allow_latest=allow_latest)
        if command in {'observe', 'screenshot', 'ocr-window'}:
            fields(args, ['hwnd', 'pid', 'include_ui', 'max_width', 'max_height'] + (['language'] if command == 'ocr-window' else []), ['hwnd'])
            if 'include_ui' in args and not isinstance(args['include_ui'], bool):
                raise EngineError('invalid_argument', 'include_ui must be boolean')
            return self.observe(args, deadline, include_ui=args.get('include_ui', command == 'observe'),
                                capture_command='ocr-window' if command == 'ocr-window' else 'screenshot')
        if command == 'uia-tree':
            if self.observation is not None:
                self.observation.elements.clear()
                self.observation.ui_available = False
            fields(args, ['hwnd', 'max_depth', 'max_nodes'], ['hwnd'])
            return self.call_native(command, ['--hwnd', hwnd_value(args['hwnd']), '--max-depth',
                str(integer(args.get('max_depth', 2), 'max_depth', 0, 4)), '--max-nodes',
                str(integer(args.get('max_nodes', 300), 'max_nodes', 1, 1000))], deadline)
        if command == 'uia-find':
            return self.uia_find(args, allow_latest=allow_latest)
        if command in {'app-close', 'app-launch'}:
            return self.app_action(command, args, deadline, allow_latest=allow_latest)
        if command == 'batch':
            return self.batch(args, deadline)
        return self.action(command, args, deadline, allow_latest=allow_latest)

    def wait_window(self, args, deadline):
        fields(args, ['title', 'pid', 'timeout_ms', 'poll_ms'], ['title'])
        title = args['title']
        if not isinstance(title, str) or not 1 <= len(title) <= 256 or not title.strip() or '\x00' in title:
            raise EngineError('invalid_argument', 'title must contain 1..256 nonblank characters, no NUL')
        pid = integer(args['pid'], 'pid', 1, 2**31-1) if 'pid' in args else None
        timeout = integer(args.get('timeout_ms', 5000), 'timeout_ms', 100, 10000) / 1000
        poll = integer(args.get('poll_ms', 250), 'poll_ms', 100, 1000) / 1000
        end = min(deadline, self.clock() + timeout)
        self.observation = None
        attempts = 0
        while self.clock() < end:
            status, data, errors = self.call_native('windows', [], end)
            attempts += 1
            if status != 'ok':
                return status, {**data, 'attempts': attempts}, errors
            windows = data.get('windows')
            if not isinstance(windows, list) or any(not isinstance(w, dict) for w in windows):
                raise EngineError('native_protocol_error', 'windows response requires a list of objects')
            matches = [w for w in windows if title.casefold() in str(w.get('title', '')).casefold()
                       and (pid is None or w.get('process_id') == pid)]
            if matches:
                if len(matches) != 1:
                    return 'blocked', {'windows': matches, 'attempts': attempts}, [
                        {'code': 'ambiguous_target', 'message': 'Several windows match. Select an explicit hwnd or narrow title/pid.'}]
                return 'ok', {'windows': matches, 'attempts': attempts, 'next': 'observe the selected hwnd before input'}, []
            remaining = end - self.clock()
            if remaining > 0:
                self.sleep(min(poll, remaining))
        return 'error', {'windows': [], 'attempts': attempts}, [
            {'code': 'window_wait_timeout', 'message': 'No matching window appeared within the bounded wait.'}]

    def observe(self, args, deadline, *, include_ui=False, capture_command='screenshot'):
        self.observation = None
        hwnd = hwnd_value(args['hwnd'])
        native_args = ['--hwnd', hwnd, '--max-width', str(integer(args.get('max_width', 1600), 'max_width', 200, 2000)),
                       '--max-height', str(integer(args.get('max_height', 1000), 'max_height', 200, 2000))]
        if 'pid' in args:
            native_args += ['--pid', str(integer(args['pid'], 'pid', 1, 2**31-1))]
        if 'language' in args:
            language = args['language']
            if (not isinstance(language, str) or not 2 <= len(language) <= 64 or any(not part for part in language.split('-')) or
                any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in language)):
                raise EngineError('invalid_argument', 'language must be a bounded BCP-47 tag')
            native_args += ['--language', language]
        status, data, errors = self.call_native(capture_command, native_args, deadline)
        if status != 'ok':
            return status, data, errors
        image, target, geometry = data.get('image'), data.get('target'), data.get('geometry')
        if not all(isinstance(v, dict) for v in (image, target, geometry)):
            raise EngineError('invalid_observation', 'screenshot needs image,target,geometry')
        if hwnd_value(target.get('hwnd')) != hwnd or ('pid' in args and target.get('pid') != args['pid']):
            raise EngineError('target_mismatch', 'screenshot target differs from requested target')
        integer(target.get('pid'), 'target.pid', 1, 2**31-1)
        window_geometry = data.get('window_geometry', geometry)
        for mapping, names in ((geometry, ('x','y','width','height','image_width','image_height')),
                               (window_geometry, ('x','y','width','height'))):
            if not isinstance(mapping, dict):
                raise EngineError('invalid_observation', 'geometry must be object')
            for key in names:
                value = mapping.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (key not in {'x','y'} and value <= 0):
                    raise EngineError('invalid_observation', f'invalid geometry.{key}')
        if image.get('mime_type') != 'image/png' or not isinstance(image.get('data'), str) or not image['data']:
            raise EngineError('invalid_observation', 'expected nonempty PNG image')
        if image.get('width') != geometry['image_width'] or image.get('height') != geometry['image_height']:
            raise EngineError('invalid_observation', 'image dimensions differ from coordinate geometry')
        obs = Observation(secrets.token_urlsafe(18), self.clock(), dict(target), dict(geometry), dict(window_geometry))
        if capture_command == 'ocr-window':
            ocr = data.get('ocr')
            if not isinstance(ocr, dict) or not isinstance(ocr.get('words'), list) or not isinstance(ocr.get('lines'), list) or ocr.get('coordinate_space') != 'image_pixels':
                raise EngineError('invalid_observation', 'Window OCR requires bounded image-pixel words and lines')
            if len(ocr['words']) > 10000 or len(ocr['lines']) > 10000:
                raise EngineError('invalid_observation', 'Window OCR exceeds item limit')
            obs.ocr = ocr
        self.observation = obs
        self.snapshots.append({'observation_id': obs.id, 'image': dict(image), 'target': dict(target),
                               'geometry': dict(geometry), 'window_geometry': dict(window_geometry)})
        data = {**data, 'observation_id': obs.id, 'expires_in_ms': int(self.ttl * 1000)}
        if include_ui:
            ui_status, ui, ui_errors = self.call_native('uia-tree', ['--hwnd', hwnd, '--pid', str(target['pid']), '--max-depth', '2', '--max-nodes', '300'], deadline)
            data['ui'] = {'status': ui_status, 'data': ui, 'errors': ui_errors}
            if ui_status == 'ok':
                obs.ui_available = True
                obs.ui_nodes = ui.get('nodes', [])
                pending = list(ui.get('nodes', []))
                while pending:
                    node = pending.pop()
                    if not isinstance(node, dict):
                        self.observation = None
                        raise EngineError('invalid_observation', 'UIA node must be an object')
                    pending.extend(node.get('children', []))
                    ref = node.get('element_ref')
                    if ref is not None:
                        if (not isinstance(ref, str) or len(ref) != 48 or any(c not in '0123456789ABCDEF' for c in ref)
                            or ref in obs.elements or node.get('process_id') != target['pid']):
                            self.observation = None
                            raise EngineError('invalid_observation', 'Invalid or duplicate UIA element reference')
                        obs.elements[ref] = {k: v for k, v in node.items() if k != 'children'}
            else:
                status, errors = 'partial', errors + ui_errors
        return status, data, errors

    def action(self, command, args, deadline, *, allow_latest=False):
        if command == 'focus':
            fields(args, ['hwnd','pid'], ['hwnd','pid'])
            target = {'hwnd': hwnd_value(args['hwnd']), 'pid': integer(args['pid'], 'pid', 1, 2**31-1)}
            native_args = ['--hwnd', target['hwnd'], '--pid', str(target['pid'])]
        else:
            required = {'click': {'x','y'}, 'drag': {'x','y','to_x','to_y'}, 'type': {'text'}, 'key': {'keys'}, 'scroll': {'direction','amount'}, 'uia-invoke': {'element_ref'}, 'uia-set-value': {'element_ref','text'}, 'uia-toggle': {'element_ref'}, 'uia-select': {'element_ref'}, 'uia-expand-collapse': {'element_ref', 'state'}, 'uia-scroll': {'element_ref'}}[command]
            fields(args, required | {'observation_id'} | ({'button', 'count'} if command == 'click' else {'steps'} if command == 'drag' else {'selection_mode'} if command == 'uia-select' else {'horizontal', 'vertical'} if command == 'uia-scroll' else set()), required | {'observation_id'})
            obs = self.observation
            if not isinstance(args['observation_id'], str) or obs is None or (args['observation_id'] != obs.id and not (allow_latest and args['observation_id'] == 'latest')) or self.clock() - obs.created > self.ttl:
                raise EngineError('stale_observation', 'observe target again before acting', 'blocked')
            target = obs.target
            native_args = ['--hwnd', target['hwnd'], '--pid', str(target['pid'])]
            for field in ('x','y','width','height'):
                native_args += [f'--expected-{field}', str(round(obs.window_geometry[field]))]
            if command in {'uia-invoke', 'uia-set-value', 'uia-toggle', 'uia-select', 'uia-expand-collapse', 'uia-scroll'}:
                ref = args['element_ref']
                if not isinstance(ref, str) or ref not in obs.elements:
                    raise EngineError('stale_element_reference', 'Use an element_ref from this observation with include_ui=true', 'blocked')
                native_args += ['--element-ref', ref]
                if command == 'uia-select':
                    mode = args.get('selection_mode', 'replace')
                    if mode not in ('replace', 'add', 'remove'):
                        raise EngineError('invalid_argument', 'selection_mode must be replace, add or remove')
                    native_args += ['--selection-mode', mode]
                elif command == 'uia-expand-collapse':
                    if args['state'] not in ('expanded', 'collapsed'):
                        raise EngineError('invalid_argument', 'state must be expanded or collapsed')
                    native_args += ['--state', args['state']]
                elif command == 'uia-scroll':
                    choices = ('none', 'small-increment', 'large-increment', 'small-decrement', 'large-decrement')
                    h, v = args.get('horizontal', 'none'), args.get('vertical', 'none')
                    if h not in choices or v not in choices or (h == v == 'none'):
                        raise EngineError('invalid_argument', 'Specify supported nonzero UIA scroll amounts')
                    native_args += ['--horizontal', h, '--vertical', v]
                elif command == 'uia-set-value':
                    value = input_text(args['text'], allow_empty=True)
                    native_args += ['--text-b64', base64.b64encode(value.encode('utf-8')).decode('ascii')]
            elif command == 'drag':
                for field, dimension in [('x', 'image_width'), ('y', 'image_height'), ('to_x', 'image_width'), ('to_y', 'image_height')]:
                    value = integer(args[field], field, 0, int(obs.geometry[dimension])-1)
                    axis = 'x' if field.endswith('x') else 'y'
                    extent = 'width' if axis == 'x' else 'height'
                    physical = math.floor(obs.geometry[axis] + value * obs.geometry[extent] / obs.geometry[dimension])
                    native_args += ['--' + field.replace('_', '-'), str(physical)]
                native_args += ['--steps', str(integer(args.get('steps', 16), 'steps', 1, 64))]
            elif command == 'click':
                x = integer(args['x'], 'x', 0, int(obs.geometry['image_width'])-1)
                y = integer(args['y'], 'y', 0, int(obs.geometry['image_height'])-1)
                button = args.get('button', 'left')
                if not isinstance(button, str) or button not in {'left','right','middle'}:
                    raise EngineError('invalid_argument', 'button must be left,right,middle')
                px = math.floor(obs.geometry['x'] + x * obs.geometry['width'] / obs.geometry['image_width'])
                py = math.floor(obs.geometry['y'] + y * obs.geometry['height'] / obs.geometry['image_height'])
                native_args += ['--x', str(px), '--y', str(py), '--button', button]
                if 'count' in args:
                    native_args += ['--count', str(integer(args['count'], 'count', 1, 2))]
            elif command == 'type':
                value = input_text(args['text'])
                native_args += ['--text-b64', base64.b64encode(value.encode('utf-8')).decode('ascii')]
            elif command == 'key':
                key = args['keys']
                if not isinstance(key, str) or key.upper() not in KEYS:
                    raise EngineError('invalid_argument', 'unsupported key; see capabilities.keys')
                native_args += ['--key', key.upper()]
            else:
                direction = args['direction']
                if not isinstance(direction, str) or direction not in {'up','down','left','right'}:
                    raise EngineError('invalid_argument', 'invalid scroll direction')
                native_args += ['--direction', direction, '--amount', str(integer(args['amount'], 'amount', 1, 20))]
        self.observation = None
        try:
            status, action, errors = self.call_native(command, native_args + ['--allow-live-control'], deadline)
        except Exception as exc:
            return 'error', {'may_have_acted': True, 'automatic_retry': False}, [
                {'code': getattr(exc, 'code', 'native_error'), 'message': str(exc)}]
        if status != 'ok':
            return status, {'action': action, 'may_have_acted': True, 'automatic_retry': False}, errors
        try:
            observed, data, observation_errors = self.observe(target, deadline)
        except Exception as exc:
            self.observation = None
            observed, data, observation_errors = 'error', {}, [{'code': getattr(exc, 'code', 'observation_error'), 'message': str(exc)}]
        data = {**data, 'action': action, 'verification': 'observed_not_asserted', 'automatic_retry': False}
        if observed != 'ok':
            return 'partial', {**data, 'may_have_acted': True}, errors + observation_errors
        return 'ok', data, errors

    def uia_find(self, args, *, allow_latest=False):
        fields(args, ['observation_id', 'name', 'automation_id', 'control_type'], ['observation_id'])
        obs = self.observation
        if (not isinstance(args['observation_id'], str) or obs is None or
            (args['observation_id'] != obs.id and not (allow_latest and args['observation_id'] == 'latest')) or
            self.clock() - obs.created > self.ttl):
            raise EngineError('stale_observation', 'Observe with include_ui=true before finding elements', 'blocked')
        if not obs.ui_available:
            raise EngineError('ui_observation_required', 'Observe with include_ui=true; standalone uia-tree does not authorize element actions', 'blocked')
        filters = {k: v for k, v in args.items() if k != 'observation_id'}
        if not filters or any(not isinstance(v, str) or not 1 <= len(v) <= 256 or '\x00' in v for v in filters.values()):
            raise EngineError('invalid_argument', 'Supply at least one exact name, automation_id or control_type filter (1..256 characters)')
        matches = [node for node in obs.elements.values() if all(node.get(k) == v for k, v in filters.items())]
        return 'ok', {'matches': matches, 'count': len(matches), 'ambiguous': len(matches) > 1,
                      'observation_id': obs.id, 'matching': 'exact_case_sensitive',
                      'note': 'Choose an explicit element_ref; no implicit first-match action'}, []

    def app_action(self, command, args, deadline, *, allow_latest=False):
        if command == 'app-launch':
            fields(args, ['path', 'arguments'], ['path'])
            path, arguments = args['path'], args.get('arguments', [])
            if (not isinstance(path, str) or len(path) > 32767 or '\x00' in path or
                not PureWindowsPath(path).is_absolute() or PureWindowsPath(path).suffix.lower() != '.exe'):
                raise EngineError('invalid_argument', 'path must be an absolute Windows .exe path')
            if (not isinstance(arguments, list) or len(arguments) > 64 or
                any(not isinstance(v, str) or '\x00' in v or len(v) > 4096 for v in arguments)):
                raise EngineError('invalid_argument', 'arguments must be up to 64 strings, each at most 4096 characters without NUL')
            encoded = base64.b64encode(json.dumps(arguments, ensure_ascii=False).encode('utf-8')).decode('ascii')
            if len(encoded) > 48000:
                raise EngineError('invalid_argument', 'argument vector exceeds size limit')
            native_args = ['--path', path, '--args-b64', encoded]
        else:
            fields(args, ['observation_id', 'timeout_ms'], ['observation_id'])
            obs = self.observation
            if (not isinstance(args['observation_id'], str) or obs is None or
                (args['observation_id'] != obs.id and not (allow_latest and args['observation_id'] == 'latest')) or
                self.clock() - obs.created > self.ttl):
                raise EngineError('stale_observation', 'observe the exact window again before closing', 'blocked')
            native_args = ['--hwnd', obs.target['hwnd'], '--pid', str(obs.target['pid']),
                           '--timeout-ms', str(integer(args.get('timeout_ms', 1500), 'timeout_ms', 0, 10000))]
            for field in ('x', 'y', 'width', 'height'):
                native_args += [f'--expected-{field}', str(round(obs.window_geometry[field]))]
        self.observation = None
        try:
            status, data, errors = self.call_native(command, native_args + ['--allow-live-control'], deadline)
        except Exception as exc:
            return 'error', {'may_have_acted': True, 'automatic_retry': False}, [
                {'code': getattr(exc, 'code', 'native_error'), 'message': str(exc)}]
        return status, {**data, 'automatic_retry': False, 'may_have_acted': True,
                        'next': 'list windows and observe before further input'}, errors

    def batch(self, args, deadline):
        fields(args, ['actions','observe_after'], ['actions'])
        actions = args['actions']
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_BATCH:
            raise EngineError('invalid_argument', f'actions must contain 1..{MAX_BATCH} steps')
        if args.get('observe_after', True) is not True:
            raise EngineError('invalid_argument', 'observe_after must be true in this release')
        for step in actions:
            if not isinstance(step, dict) or set(step) != {'command','args'} or not isinstance(step['args'], dict):
                raise EngineError('invalid_argument', 'each step needs command and args')
            name = step['command']
            if not isinstance(name, str) or name not in COMMANDS or not COMMANDS[name].available_in_engine or name in {'batch','capabilities','history','workflow-plan','workflow-run','task-build','task-run','form-plan','form-run','watch','record-start','record-stop','record-read','app-profile','recovery-plan'}:
                raise EngineError('invalid_argument', 'unsupported batch command')
            if COMMANDS[name].effect == 'write' and not self.allow_live_control:
                raise EngineError('live_control_required', 'human must enable live control for this batch', 'blocked')
        steps, errors, last, failed = [], [], {}, False
        for index, step in enumerate(actions):
            if failed:
                steps.append({'command': step['command'], 'status': 'skipped', 'data': {},
                              'errors': [{'code': 'prior_step_failed', 'message': 'Not executed: earlier action failed.'}]})
                continue
            try:
                status, data, step_errors = self.execute(step['command'], step['args'], deadline, allow_latest=index > 0)
            except EngineError as exc:
                status, data, step_errors = exc.status, {}, [{'code': exc.code, 'message': str(exc)}]
            except Exception as exc:
                self.observation = None
                status, data, step_errors = 'error', {'may_have_acted': COMMANDS[step['command']].effect == 'write'}, [
                    {'code': 'internal_error', 'message': f'{type(exc).__name__}: {exc}'}]
            if 'image' in data:
                last = {k: data[k] for k in ('image','observation_id','target','geometry','window_geometry','captured_at') if k in data}
                last.update(image_from_step=index, image_state='latest_available')
            steps.append({'command': step['command'], 'status': status,
                          'data': {k:v for k,v in data.items() if k != 'image'}, 'errors': step_errors})
            errors.extend(step_errors)
            failed = status != 'ok'
        if failed:
            self.observation = None
            last.pop('observation_id', None)
            if 'image' in last:
                last['image_state'] = 'last_known_before_failure'
        return ('error' if failed else 'ok'), {'steps': steps, **last, 'automatic_retry': False,
                                              'verification': 'observed_not_asserted'}, errors

    def workflow_command(self, command, args, deadline):
        from .workflows import build_plan, form_plan, run_plan, task_plan, watch
        if command in {'workflow-plan', 'workflow-run'}:
            fields(args, ['workflow', 'dry_run'], ['workflow'])
            if 'dry_run' in args and type(args['dry_run']) is not bool:
                raise EngineError('invalid_argument', 'dry_run must be boolean')
            if command == 'workflow-plan':
                return 'ok', {'plan': build_plan(args['workflow'])}, []
            return run_plan(self, args['workflow'], deadline, dry_run=args.get('dry_run', False))
        if command in {'task-build', 'task-run'}:
            spec = task_plan(args)
            if command == 'task-build':
                return 'ok', {'workflow': spec, 'plan': build_plan(spec)}, []
            return run_plan(self, spec, deadline)
        if command in {'form-plan', 'form-run'}:
            spec = form_plan(args)
            if command == 'form-plan':
                return 'ok', {'workflow': spec, 'plan': build_plan(spec)}, []
            return run_plan(self, spec, deadline)
        if command == 'watch':
            return watch(self, args, deadline)
        if command.startswith('record-'):
            fields(args, [])
            if command == 'record-start':
                return 'ok', self.recorder.start(), []
            if command == 'record-stop':
                self.recorder.active = False
            return 'ok', self.recorder.snapshot(), []
        if command == 'recovery-plan':
            fields(args, ['failed_reason'])
            reason = args.get('failed_reason', '')
            if not isinstance(reason, str) or len(reason) > 256:
                raise EngineError('invalid_argument', 'failed_reason must be at most 256 characters')
            return 'ok', {'candidates': [{'command': 'windows', 'args': {}, 'effect': 'read',
                'reason': 'Re-identify the target and inspect any dialog before choosing another action'}],
                'failed_reason': reason, 'automatic_retry': False, 'automatic_dismissal': False,
                'requires_host_decision': True, 'observation_available': self.observation is not None}, []
        fields(args, ['observation_id'], ['observation_id'])
        obs = self.observation
        if obs is None or args['observation_id'] != obs.id or self.clock() - obs.created > self.ttl:
            raise EngineError('stale_observation', 'Observe the target again', 'blocked')
        from collections import Counter
        nodes = list(obs.elements.values())
        patterns = Counter(p for n in nodes for p in n.get('supported_patterns', n.get('patterns', [])))
        return 'ok', {'target': obs.target, 'observation_id': obs.id, 'ui_available': obs.ui_available,
            'element_count': len(nodes), 'control_types': dict(Counter(n.get('control_type', 'Unknown') for n in nodes)),
            'patterns': dict(patterns), 'routes': ['uia'] if nodes else ['screenshot'],
            'automatic_fallback': False, 'cdp_probed': False, 'model_provider_required': False}, []

    def process_observation(self, command, args, *, allow_latest=False):
        from .observation_processing import match_ocr_candidates, fuse_ocr_uia, screenshot_diff
        try:
            if command == 'screenshot-diff':
                before = next((s for s in self.snapshots if s['observation_id'] == args['before_id']), None)
                after = next((s for s in self.snapshots if s['observation_id'] == args['after_id']), None)
                if before is None or after is None:
                    raise EngineError('snapshot_unavailable', 'Only the two most recent snapshots remain in memory', 'blocked')
                if any(before[k] != after[k] for k in ('target', 'geometry', 'window_geometry')):
                    raise EngineError('incompatible_snapshots', 'Target and physical/image geometry must match exactly', 'blocked')
                raw_before = base64.b64decode(before['image']['data'], validate=True)
                raw_after = base64.b64decode(after['image']['data'], validate=True)
                report = screenshot_diff(raw_before, raw_after, threshold=args.get('threshold', 16),
                                         region=args.get('region'), ignore_regions=args.get('ignore_regions', []))
                diff_status = 'ok' if report.get('comparison_complete') else 'partial'
                diff_errors = [] if diff_status == 'ok' else [{'code': 'incomplete_comparison', 'message': 'No full comparison evidence is available'}]
                return diff_status, {**report, 'before_id': args['before_id'], 'after_id': args['after_id'],
                              'target': after['target'], 'verification': 'pixels_changed_not_task_success'}, diff_errors
            obs = self.observation
            if obs is None or (args['observation_id'] != obs.id and not (allow_latest and args['observation_id'] == 'latest')) or self.clock() - obs.created > self.ttl:
                raise EngineError('stale_observation', 'Capture a fresh window OCR observation', 'blocked')
            if obs.ocr is None:
                raise EngineError('ocr_observation_required', 'Use ocr-window before text search or fusion', 'blocked')
            matches = match_ocr_candidates(obs.ocr, args['text'], args.get('match', 'contains'),
                min_score=args.get('min_score', 0), limit=args.get('max_candidates', 50))
            if command == 'ocr-uia-fuse':
                if not obs.ui_available:
                    raise EngineError('ui_observation_required', 'ocr-window requires include_ui=true for fusion', 'blocked')
                report = fuse_ocr_uia(matches, obs.ui_nodes, geometry=obs.geometry,
                                     target=obs.target, uia_target=obs.target, limit=args.get('max_candidates', 8))
            else:
                report = matches
            result_status = 'partial' if report.get('status') == 'partial' else 'ok'
            result_errors = [] if result_status == 'ok' else [{'code': 'ambiguous_or_incomplete_observation', 'message': 'Inspect alternatives; no action was selected'}]
            return result_status, {**report, 'observation_id': obs.id, 'target': obs.target,
                          'automatic_action': False}, result_errors
        except ValueError as exc:
            raise EngineError('invalid_observation_data', str(exc)) from None
