"""Provider-neutral, serialized computer-use session. No model API or shell evaluation."""
from __future__ import annotations
import base64
import math
import secrets
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable
from .native_host import run_native, native_host_available
from .registry import COMMANDS, capabilities

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

class ComputerSession:
    """One owner per session. Host-side live permission cannot be changed by a request."""
    def __init__(self, *, allow_live_control=False, native: Callable=run_native,
                 clock: Callable=time.monotonic, observation_ttl_s=60, native_transport="published executable per call"):
        self.native_transport = native_transport
        self.allow_live_control = bool(allow_live_control)
        self.native, self.clock, self.ttl = native, clock, observation_ttl_s
        self.observation = None
        self.seen, self.order = set(), deque()
        self.events = deque(maxlen=200)

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
        except EngineError as exc:
            status, data, errors = exc.status, {}, [{'code': exc.code, 'message': str(exc)}]
        except Exception as exc:
            self.observation = None
            status, data, errors = 'error', {}, [{'code': 'internal_error', 'message': f'{type(exc).__name__}: {exc}'}]
        duration = round((self.clock() - started) * 1000, 3)
        self.events.append({'id': rid, 'command': command, 'status': status, 'duration_ms': duration,
                            'error_codes': [e['code'] for e in errors]})
        return {'schema': 'cucp.response/v1', 'id': rid, 'command': command,
                'status': status, 'data': data, 'errors': errors, 'duration_ms': duration}

    def call_native(self, command, args, deadline):
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
        spec = COMMANDS.get(command)
        if spec is None or not spec.available_in_engine:
            raise EngineError('unknown_command', f'command not exposed by engine: {command}', 'blocked')
        if spec.effect == 'write' and not self.allow_live_control:
            raise EngineError('live_control_required', 'human operator must enable live control', 'blocked')
        if command == 'capabilities':
            fields(args, [])
            return 'ok', {'commands': capabilities(), 'allow_live_control': self.allow_live_control,
                          'platform': 'windows', 'max_batch': MAX_BATCH, 'observation_ttl_s': self.ttl,
                          'runtime_platform': sys.platform, 'native_host_configured': native_host_available(),
                          'request_id_retention': 1024,
                          'coordinate_space': 'returned screenshot image pixels', 'keys': sorted(KEYS),
                          'automatic_retry': False, 'native_transport': self.native_transport}, []
        if command == 'history':
            fields(args, [])
            return 'ok', {'events': list(self.events)}, []
        if command == 'windows':
            fields(args, [])
            return self.call_native(command, [], deadline)
        if command == 'privileges':
            fields(args, ['pid'])
            native_args = ['--pid', str(integer(args['pid'], 'pid', 1, 2**31-1))] if 'pid' in args else []
            return self.call_native(command, native_args, deadline)
        if command in {'observe', 'screenshot'}:
            fields(args, ['hwnd', 'pid', 'include_ui', 'max_width', 'max_height'], ['hwnd'])
            if 'include_ui' in args and not isinstance(args['include_ui'], bool):
                raise EngineError('invalid_argument', 'include_ui must be boolean')
            return self.observe(args, deadline, include_ui=args.get('include_ui', command == 'observe'))
        if command == 'uia-tree':
            fields(args, ['hwnd', 'max_depth', 'max_nodes'], ['hwnd'])
            return self.call_native(command, ['--hwnd', hwnd_value(args['hwnd']), '--max-depth',
                str(integer(args.get('max_depth', 2), 'max_depth', 0, 4)), '--max-nodes',
                str(integer(args.get('max_nodes', 300), 'max_nodes', 1, 1000))], deadline)
        if command == 'batch':
            return self.batch(args, deadline)
        return self.action(command, args, deadline, allow_latest=allow_latest)

    def observe(self, args, deadline, *, include_ui=False):
        self.observation = None
        hwnd = hwnd_value(args['hwnd'])
        native_args = ['--hwnd', hwnd, '--max-width', str(integer(args.get('max_width', 1600), 'max_width', 200, 2000)),
                       '--max-height', str(integer(args.get('max_height', 1000), 'max_height', 200, 2000))]
        if 'pid' in args:
            native_args += ['--pid', str(integer(args['pid'], 'pid', 1, 2**31-1))]
        status, data, errors = self.call_native('screenshot', native_args, deadline)
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
        self.observation = obs
        data = {**data, 'observation_id': obs.id, 'expires_in_ms': int(self.ttl * 1000)}
        if include_ui:
            ui_status, ui, ui_errors = self.call_native('uia-tree', ['--hwnd', hwnd, '--max-depth', '2', '--max-nodes', '300'], deadline)
            data['ui'] = {'status': ui_status, 'data': ui, 'errors': ui_errors}
            if ui_status != 'ok':
                status, errors = 'partial', errors + ui_errors
        return status, data, errors

    def action(self, command, args, deadline, *, allow_latest=False):
        if command == 'focus':
            fields(args, ['hwnd','pid'], ['hwnd','pid'])
            target = {'hwnd': hwnd_value(args['hwnd']), 'pid': integer(args['pid'], 'pid', 1, 2**31-1)}
            native_args = ['--hwnd', target['hwnd'], '--pid', str(target['pid'])]
        else:
            required = {'click': {'x','y'}, 'type': {'text'}, 'key': {'keys'}, 'scroll': {'direction','amount'}}[command]
            fields(args, required | {'observation_id'} | ({'button'} if command == 'click' else set()), required | {'observation_id'})
            obs = self.observation
            if not isinstance(args['observation_id'], str) or obs is None or (args['observation_id'] != obs.id and not (allow_latest and args['observation_id'] == 'latest')) or self.clock() - obs.created > self.ttl:
                raise EngineError('stale_observation', 'observe target again before acting', 'blocked')
            target = obs.target
            native_args = ['--hwnd', target['hwnd'], '--pid', str(target['pid'])]
            for field in ('x','y','width','height'):
                native_args += [f'--expected-{field}', str(round(obs.window_geometry[field]))]
            if command == 'click':
                x = integer(args['x'], 'x', 0, int(obs.geometry['image_width'])-1)
                y = integer(args['y'], 'y', 0, int(obs.geometry['image_height'])-1)
                button = args.get('button', 'left')
                if not isinstance(button, str) or button not in {'left','right','middle'}:
                    raise EngineError('invalid_argument', 'button must be left,right,middle')
                px = math.floor(obs.geometry['x'] + x * obs.geometry['width'] / obs.geometry['image_width'])
                py = math.floor(obs.geometry['y'] + y * obs.geometry['height'] / obs.geometry['image_height'])
                native_args += ['--x', str(px), '--y', str(py), '--button', button]
            elif command == 'type':
                value = args['text']
                if not isinstance(value, str) or not 1 <= len(value) <= 4096 or '\x00' in value:
                    raise EngineError('invalid_argument', 'text must contain 1..4096 characters, no NUL')
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
            if not isinstance(name, str) or name not in COMMANDS or not COMMANDS[name].available_in_engine or name in {'batch','capabilities','history'}:
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
