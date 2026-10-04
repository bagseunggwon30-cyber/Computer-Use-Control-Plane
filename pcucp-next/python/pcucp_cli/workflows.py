"""Bounded, declarative workflow runtime; no PowerShell, shell, eval or model SDK.

Plans are data, never executable code. A plan is not authorization. Every leaf
operation passes through the session's immutable live gate. Failed mutations,
including successful input followed by failed observation, are never retried.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, deque
from .registry import COMMANDS

MAX_STEPS = 64
MAX_PLAN_BYTES = 256 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
CONTROL_COMMANDS = frozenset({
    'batch', 'workflow-plan', 'workflow-run', 'form-plan', 'form-run', 'task-build', 'task-run',
    'watch', 'record-start', 'record-stop', 'record-read', 'recovery-plan',
    'capabilities', 'history', 'app-profile',
})
_ID = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,47}$')


class WorkflowError(ValueError):
    def __init__(self, code, message, status='error'):
        super().__init__(message)
        self.code, self.status = code, status


def _fields(obj, allowed, required=()):
    if not isinstance(obj, dict) or set(obj) - set(allowed) or set(required) - set(obj):
        raise WorkflowError('invalid_plan', f'Expected object with fields {sorted(allowed)}; required {sorted(required)}')


def _integer(value, lo, hi, name):
    if type(value) is not int or not lo <= value <= hi:
        raise WorkflowError('invalid_plan', f'{name} must be integer {lo}..{hi}')
    return value


def _path(value):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 512:
        raise WorkflowError('invalid_reference', 'Reference path must be a bounded JSON pointer')
    parts = value[1:].split('/')
    if len(parts) > 16 or any(re.search(r'~(?![01])', p) for p in parts):
        raise WorkflowError('invalid_reference', 'Invalid JSON pointer')
    return [p.replace('~1', '/').replace('~0', '~') for p in parts]


def _lookup(value, pointer):
    for part in _path(pointer):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise WorkflowError('unresolved_reference', f'Reference is unavailable: {pointer}', 'blocked')
    return copy.deepcopy(value)


def _walk(value, prior, depth=0):
    if depth > 16:
        raise WorkflowError('invalid_plan', 'Arguments exceed maximum nesting depth')
    if isinstance(value, dict):
        if '$ref' in value:
            if set(value) != {'$ref'}:
                raise WorkflowError('invalid_reference', '$ref must be the only key')
            parts = _path(value['$ref'])
            if len(parts) < 2 or parts[0] not in prior:
                raise WorkflowError('invalid_reference', 'References must name an earlier step and its output')
        else:
            for item in value.values():
                _walk(item, prior, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _walk(item, prior, depth + 1)


def _resolve(value, results):
    if isinstance(value, dict):
        if set(value) == {'$ref'}:
            return _lookup(results, value['$ref'])
        return {k: _resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, results) for v in value]
    return value


def _assertion(value):
    _fields(value, ('path', 'equals', 'count', 'exists'), ('path',))
    _path(value['path'])
    operators = set(value) - {'path'}
    if len(operators) != 1:
        raise WorkflowError('invalid_plan', 'Assertion needs exactly one of equals, count, exists')
    if 'count' in value:
        _integer(value['count'], 0, 10000, 'assert.count')
    if 'exists' in value and type(value['exists']) is not bool:
        raise WorkflowError('invalid_plan', 'assert.exists must be boolean')


def json_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def condition_matches(data, condition):
    try:
        result = _lookup(data, condition['path'])
    except WorkflowError:
        return condition.get('exists') is False
    if 'exists' in condition:
        return condition['exists']
    if 'count' in condition:
        return isinstance(result, (list, dict, str)) and len(result) == condition['count']
    # Python considers True == 1; JSON conditions intentionally do not.
    expected = condition['equals']
    return json_equal(result, expected)


def build_plan(spec):
    _fields(spec, ('schema', 'name', 'steps', 'timeout_ms', 'settle_ms', 'read_retries'), ('steps',))
    if spec.get('schema', 'cucp.workflow/v2') != 'cucp.workflow/v2':
        raise WorkflowError('invalid_plan', 'Expected cucp.workflow/v2')
    try:
        encoded = json.dumps(spec, ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise WorkflowError('invalid_plan', 'Plan must be finite JSON data') from None
    if len(encoded.encode('ascii')) > MAX_PLAN_BYTES:
        raise WorkflowError('invalid_plan', 'Plan exceeds 256 KiB serialized size')
    name = spec.get('name', 'workflow')
    if not isinstance(name, str) or not 1 <= len(name) <= 128 or '\x00' in name:
        raise WorkflowError('invalid_plan', 'name must have 1..128 characters')
    steps = spec['steps']
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise WorkflowError('invalid_plan', f'Workflow requires 1..{MAX_STEPS} steps')
    timeout = _integer(spec.get('timeout_ms', 30000), 100, 60000, 'timeout_ms')
    settle = _integer(spec.get('settle_ms', 0), 0, 2000, 'settle_ms')
    retries = _integer(spec.get('read_retries', 0), 0, 3, 'read_retries')
    prior, compiled = set(), []
    for index, step in enumerate(steps):
        _fields(step, ('id', 'command', 'args', 'assert'), ('command', 'args'))
        sid = step.get('id', f'step{index + 1}')
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in prior:
            raise WorkflowError('invalid_plan', 'Step IDs must be unique simple identifiers')
        command = step['command']
        if not isinstance(command, str) or command not in COMMANDS:
            raise WorkflowError('unsupported_step', f'Unknown workflow command: {command}')
        cap = COMMANDS[command]
        if not cap.available_in_engine or command in CONTROL_COMMANDS or cap.effect not in ('read', 'write'):
            raise WorkflowError('unsupported_step', f'Nested/control/legacy command blocked: {command}')
        if not isinstance(step['args'], dict):
            raise WorkflowError('invalid_plan', 'Step args must be an object')
        _walk(step['args'], prior)
        if 'assert' in step:
            _assertion(step['assert'])
        compiled.append({**copy.deepcopy(step), 'id': sid, 'effect': cap.effect})
        prior.add(sid)
    return {'schema': 'cucp.workflow-plan/v2', 'name': name, 'steps': compiled,
            'step_count': len(compiled), 'live_step_count': sum(s['effect'] == 'write' for s in compiled),
            'timeout_ms': timeout, 'settle_ms': settle, 'read_retries': retries,
            'stop_on_error': True, 'automatic_mutation_retry': False,
            'authorization': 'Plan does not grant permission; host approval and startup live mode are required'}


def _pause(session, milliseconds, deadline):
    # Short slices allow cancellation during settle/read-only polling.
    until = min(deadline, session.clock() + milliseconds / 1000)
    while session.clock() < until:
        if session.cancelled.is_set():
            raise WorkflowError('session_cancelled', 'Session was cancelled', 'blocked')
        session.sleep(min(.05, until - session.clock()))
    if session.clock() >= deadline:
        raise WorkflowError('deadline_exceeded', 'Workflow deadline reached', 'blocked')


def run_plan(session, spec, deadline, *, dry_run=False):
    plan = build_plan(spec)
    if dry_run:
        return 'ok', {'plan': plan, 'dry_run': True, 'executed_count': 0}, []
    if plan['live_step_count'] and not session.allow_live_control:
        raise WorkflowError('live_control_required', 'Human operator must enable live control for the whole workflow', 'blocked')
    # Preflight schema/unknown-key validation for all steps before first mutation.
    from .mcp_server import SCHEMAS
    from .validation import validate
    for step in plan['steps']:
        validate(step['args'], SCHEMAS[step['command']], allow_references=True)
    deadline = min(deadline, session.clock() + plan['timeout_ms'] / 1000)
    results, report, errors, last_image = {}, [], [], {}
    failed = False
    retained_bytes = 0
    for step in plan['steps']:
        item = {'id': step['id'], 'command': step['command'], 'effect': step['effect']}
        if failed:
            report.append({**item, 'status': 'skipped', 'attempts': 0})
            continue
        attempts = 0
        try:
            args = _resolve(step['args'], results)
            validate(args, SCHEMAS[step['command']])
            while True:
                if session.cancelled.is_set():
                    raise WorkflowError('session_cancelled', 'Session was cancelled', 'blocked')
                if session.clock() >= deadline:
                    raise WorkflowError('deadline_exceeded', 'Workflow deadline reached', 'blocked')
                attempts += 1
                status, data, leaf_errors = session.execute(step['command'], args, deadline, allow_latest=bool(report))
                # Only repeat read calls that returned a nonterminal error, never partial or mutations.
                retry = (step['effect'] == 'read' and status == 'error' and attempts <= plan['read_retries']
                         and not session.cancelled.is_set()
                         and all(e.get('code') in {'native_unavailable', 'deadline_exceeded'} for e in leaf_errors))
                if not retry:
                    break
                _pause(session, 100, deadline)
            if status == 'ok' and 'assert' in step and not condition_matches(data, step['assert']):
                status = 'error'
                leaf_errors = [{'code': 'assertion_failed', 'message': 'Step result did not satisfy its explicit assertion'}]
            if 'image' in data:
                last_image = {k: data[k] for k in ('image', 'target', 'geometry', 'window_geometry', 'observation_id', 'captured_at') if k in data}
                last_image['image_from_step'] = step['id']
            stripped = {k: v for k, v in data.items() if k != 'image'}
            retained_bytes += len(json.dumps(stripped, ensure_ascii=True, allow_nan=False).encode('ascii'))
            if retained_bytes > MAX_RESULT_BYTES:
                raise WorkflowError('result_budget_exceeded', 'Workflow metadata exceeded 2 MiB; later steps were not started')
            results[step['id']] = stripped
            report.append({**item, 'status': status, 'operation_status': status, 'attempts': attempts,
                           'may_have_acted': step['effect'] == 'write' and attempts > 0,
                           'data': results[step['id']], 'errors': leaf_errors})
            errors.extend(leaf_errors)
            failed = status != 'ok'
            if not failed and plan['settle_ms']:
                _pause(session, plan['settle_ms'], deadline)
        except Exception as exc:
            if report and report[-1]['id'] == step['id']:
                report[-1]['status'] = 'partial' if step['effect'] == 'write' else getattr(exc, 'status', 'error')
                report[-1]['completion_phase'] = 'settle'
                report[-1]['may_have_acted'] = step['effect'] == 'write'
                report[-1]['errors'] = [{'code': getattr(exc, 'code', 'workflow_error'), 'message': str(exc)}]
            else:
                report.append({**item, 'status': getattr(exc, 'status', 'error'), 'attempts': attempts,
                               'may_have_acted': step['effect'] == 'write' and attempts > 0,
                               'errors': [{'code': getattr(exc, 'code', 'workflow_error'), 'message': str(exc)}]})
            errors.extend(report[-1]['errors'])
            failed = True
    if failed:
        session.observation = None
        last_image.pop('observation_id', None)
    may_have_acted = any(s.get('may_have_acted', False) for s in report)
    return ('partial' if failed and may_have_acted else 'error' if failed else 'ok'), {'schema': 'cucp.workflow-run/v2', 'name': plan['name'],
        'steps': report, 'executed_count': sum(s['attempts'] > 0 for s in report),
        'failed_count': sum(s['status'] not in ('ok', 'skipped') for s in report),
        'automatic_mutation_retry': False, 'rollback': False, 'may_have_acted': may_have_acted,
        'image_state': 'last_known_before_failure' if failed else 'latest_available', **last_image}, errors


def form_plan(args):
    _fields(args, ('hwnd', 'pid', 'fields', 'submit', 'timeout_ms'), ('hwnd', 'fields'))
    entries = args['fields']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 15:
        raise WorkflowError('invalid_plan', 'fields requires 1..15 exact UIA selectors and values')
    target = {k: args[k] for k in ('hwnd', 'pid') if k in args}
    steps = []
    for i, entry in enumerate(entries + ([{'selector': args['submit']}] if 'submit' in args else [])):
        is_submit = i == len(entries)
        _fields(entry, ('selector',) if is_submit else ('selector', 'text'), ('selector',) if is_submit else ('selector', 'text'))
        selector = entry['selector']
        _fields(selector, ('name', 'automation_id', 'control_type'))
        if not selector or any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in selector.values()):
            raise WorkflowError('invalid_plan', 'Each selector needs at least one exact nonempty filter')
        if not is_submit:
            from .engine import input_text
            input_text(entry['text'], allow_empty=True)
        obs, find, action = f'observe{i}', f'find{i}', f'action{i}'
        steps.extend([
            {'id': obs, 'command': 'observe', 'args': {**target, 'include_ui': True}},
            {'id': find, 'command': 'uia-find', 'args': {'observation_id': {'$ref': f'/{obs}/observation_id'}, **selector}, 'assert': {'path': '/count', 'equals': 1}},
            {'id': action, 'command': 'uia-invoke' if is_submit else 'uia-set-value', 'args': {
                'observation_id': {'$ref': f'/{obs}/observation_id'},
                'element_ref': {'$ref': f'/{find}/matches/0/element_ref'},
                **({} if is_submit else {'text': entry['text']})}},
        ])
    return {'schema': 'cucp.workflow/v2', 'name': 'form', 'steps': steps, 'timeout_ms': args.get('timeout_ms', 60000)}


def watch(session, args, deadline):
    _fields(args, ('command', 'args', 'until', 'interval_ms', 'max_cycles'), ('command', 'args'))
    plan = build_plan({'steps': [{'command': args['command'], 'args': args['args']}]})
    if plan['live_step_count']:
        raise WorkflowError('read_only_required', 'Watch accepts read-only leaf commands only', 'blocked')
    from .mcp_server import SCHEMAS
    from .validation import validate
    validate(args['args'], SCHEMAS[args['command']])
    # References have no preceding step and are rejected by build_plan.
    interval = _integer(args.get('interval_ms', 500), 100, 5000, 'interval_ms')
    limit = _integer(args.get('max_cycles', 20), 1, 100, 'max_cycles')
    if 'until' in args:
        _assertion(args['until'])
    cycles, previous, final, found = [], None, {}, False
    for index in range(limit):
        if session.cancelled.is_set():
            raise WorkflowError('session_cancelled', 'Session was cancelled', 'blocked')
        if session.clock() >= deadline:
            raise WorkflowError('deadline_exceeded', 'Watch deadline reached', 'blocked')
        status, data, errors = session.execute(args['command'], args['args'], deadline)
        # No screenshot/text history, only bounded change metadata and final result.
        encoded = json.dumps({k: v for k, v in data.items() if k not in ('image', 'observation_id', 'captured_at', 'expires_in_ms')}, sort_keys=True, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_RESULT_BYTES:
            raise WorkflowError('result_budget_exceeded', 'Watch metadata exceeds 2 MiB')
        signature = hashlib.sha256(encoded).digest()
        cycles.append({'cycle': index + 1, 'status': status, 'changed': previous is not None and signature != previous})
        final, previous = data, signature
        if status != 'ok':
            return status, {'cycles': cycles, 'until_matched': False, 'last': {k: v for k, v in final.items() if k != 'image'}}, errors
        found = 'until' in args and condition_matches(data, args['until'])
        if found or index + 1 == limit:
            break
        _pause(session, interval, deadline)
    if 'until' in args and not found:
        return 'partial', {'cycles': cycles, 'until_matched': False, **final}, [{'code': 'condition_not_met', 'message': 'Condition was not met within requested cycles'}]
    return 'ok', {'cycles': cycles, 'until_matched': found, **final}, []


class Recorder:
    """Memory-only action metadata. Never retains args, values, titles, images or errors' text."""
    def __init__(self):
        self.active = False
        self.entries = deque(maxlen=1000)
        self.dropped = 0

    def start(self):
        if self.active:
            raise WorkflowError('recording_active', 'Stop the current recording before starting another', 'blocked')
        self.entries.clear()
        self.dropped = 0
        self.active = True
        return self.snapshot()

    def append(self, event):
        if self.active:
            if len(self.entries) == self.entries.maxlen:
                self.dropped += 1
            # request IDs are host-controlled and may contain sensitive data; exclude them too.
            event = {**event, 'command': event.get('command') if event.get('command') in COMMANDS else '[unknown]'}
            self.entries.append({k: copy.deepcopy(event[k]) for k in ('command', 'status', 'duration_ms', 'error_codes') if k in event})

    def snapshot(self):
        events = list(self.entries)
        return {'active': self.active, 'events': events, 'dropped': self.dropped,
                'capacity': 1000, 'storage': 'session_memory',
                'counts': dict(Counter(e.get('status') for e in events)),
                'replayable': False}


def task_plan(args):
    """Compile common launch/wait/fill/type/key/submit intent into explicit leaf steps."""
    _fields(args, ('name', 'target', 'launch', 'wait', 'focus', 'fields', 'text', 'keys', 'submit', 'timeout_ms'))
    if ('target' in args) == ('wait' in args):
        raise WorkflowError('invalid_plan', 'Provide exactly one explicit target or wait-window selector')
    if 'launch' in args and 'wait' not in args:
        raise WorkflowError('invalid_plan', 'Launching requires a wait selector for the new process')
    if 'focus' in args and type(args['focus']) is not bool:
        raise WorkflowError('invalid_plan', 'focus must be boolean')
    steps = []
    if 'launch' in args:
        _fields(args['launch'], ('path', 'arguments'), ('path',))
        steps.append({'id': 'launch', 'command': 'app-launch', 'args': copy.deepcopy(args['launch'])})
    if 'wait' in args:
        _fields(args['wait'], ('title', 'pid', 'timeout_ms', 'poll_ms'), ('title',))
        wait_args = copy.deepcopy(args['wait'])
        if 'launch' in args:
            if 'pid' in wait_args:
                raise WorkflowError('invalid_plan', 'Do not override launched process PID')
            wait_args['pid'] = {'$ref': '/launch/pid'}
        steps.append({'id': 'wait', 'command': 'wait-window', 'args': wait_args})
        target = {'hwnd': {'$ref': '/wait/windows/0/hwnd'}, 'pid': {'$ref': '/wait/windows/0/process_id'}}
    else:
        _fields(args['target'], ('hwnd', 'pid'), ('hwnd', 'pid'))
        target = copy.deepcopy(args['target'])
    if args.get('focus', False):
        steps.append({'id': 'focus', 'command': 'focus', 'args': copy.deepcopy(target)})
    if args.get('fields'):
        fields_spec = form_plan({**target, 'fields': args['fields']})
        steps.extend(fields_spec['steps'])
    elif 'fields' in args and args['fields'] != []:
        raise WorkflowError('invalid_plan', 'fields must be an array')
    if 'text' in args:
        from .engine import input_text
        input_text(args['text'])
        steps += [{'id': 'observe_text', 'command': 'observe', 'args': copy.deepcopy(target)},
                  {'id': 'type_text', 'command': 'type', 'args': {'observation_id': {'$ref': '/observe_text/observation_id'}, 'text': args['text']}}]
    keys = args.get('keys', [])
    if not isinstance(keys, list) or len(keys) > 8:
        raise WorkflowError('invalid_plan', 'keys must contain at most eight explicit shortcuts')
    from .engine import KEYS
    for i, key in enumerate(keys):
        if not isinstance(key, str) or key.upper() not in KEYS:
            raise WorkflowError('invalid_plan', 'Unsupported key; inspect capabilities.keys')
        steps += [{'id': f'observe_key{i}', 'command': 'observe', 'args': copy.deepcopy(target)},
                  {'id': f'key{i}', 'command': 'key', 'args': {'observation_id': {'$ref': f'/observe_key{i}/observation_id'}, 'keys': key.upper()}}]
    if 'submit' in args:
        selector = args['submit']
        _fields(selector, ('name', 'automation_id', 'control_type'))
        if not selector or any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in selector.values()):
            raise WorkflowError('invalid_plan', 'submit requires an exact nonempty selector')
        steps += [{'id': 'observe_submit', 'command': 'observe', 'args': {**copy.deepcopy(target), 'include_ui': True}},
                  {'id': 'find_submit', 'command': 'uia-find', 'args': {'observation_id': {'$ref': '/observe_submit/observation_id'}, **selector}, 'assert': {'path': '/count', 'equals': 1}},
                  {'id': 'submit', 'command': 'uia-invoke', 'args': {'observation_id': {'$ref': '/observe_submit/observation_id'}, 'element_ref': {'$ref': '/find_submit/matches/0/element_ref'}}}]
    if not steps:
        steps.append({'id': 'observe', 'command': 'observe', 'args': target})
    return {'schema': 'cucp.workflow/v2', 'name': args.get('name', 'task'), 'steps': steps,
            'timeout_ms': args.get('timeout_ms', 60000)}
