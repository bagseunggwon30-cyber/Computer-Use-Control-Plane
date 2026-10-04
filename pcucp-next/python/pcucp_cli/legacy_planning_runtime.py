"""Retained task/form/preset acquisition around the qualified C# recipe kernels."""
import math
import json
import re
import socket
import time
from .legacy_cdp import LegacyCdpAdapter
from .legacy_cdp_contract import _ps_equal, prepare_native
from .legacy_diagnostic_provider import option
from .legacy_host_protocol import Authority
from .legacy_host_session import cancel_with_owner
from .legacy_native_desktop import DesktopSession
from .legacy_history import SmartClickHistory
from .legacy_values import int32
from .legacy_host_protocol import exact, require
from .legacy_native_kernel import compatibility
from .legacy_workflow_plan import workflow_plan


class PlanningRuntime:
    def __init__(self, *, child=None, culture='en-US', timeout_s=30, parent_deadline=math.inf, cancelled=None,
                 audit_directory=None, cache_seconds=2, native=None):
        self.child, self.culture, self.cancelled = child, culture, cancelled
        self.deadline = min(time.monotonic() + timeout_s, parent_deadline)
        self.history = SmartClickHistory(audit_directory) if audit_directory is not None else None
        self.cache_seconds, self.native = cache_seconds, native

    def remaining(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'Planning owner cancelled; action not retried.')
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'Planning owner timed out; action not retried.')
        return remaining

    def kernel(self, operation, args):
        return compatibility(operation, args, culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled)

    def workflow(self, rest):
        return workflow_plan(rest, culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled)

    def _native(self, argv):
        if self.native is not None:
            return self.native(argv, self)
        if argv[1].startswith('cdp-'):
            macro = prepare_native(argv)
            require(macro.action in {'cdp-smart-find', 'cdp-smart-type-find'}, 'Planning cannot execute a CDP action.')
            remaining = min(30, self.remaining())
            require(remaining >= .05, 'Insufficient inherited planning CDP budget; action not retried.')
            adapter = LegacyCdpAdapter(f'http://127.0.0.1:{macro.port}', timeout_s=remaining)
            started = time.monotonic()
            try:
                with cancel_with_owner(adapter, self.cancelled):
                    result = adapter.execute(macro.action, macro.args)
                self.remaining()
                return dict(ExitCode=result.exit_code, Json=result.payload, Raw=json.dumps(result.payload), Err='',
                    ElapsedMs=round((time.monotonic() - started) * 1000))
            finally:
                adapter.close()
        require(argv[1] in {'uia-find', 'ocr-uia-fuse'}, 'Planning cannot execute a native action.')
        return DesktopSession(authority=Authority(), culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled).run(argv)

    def smart(self, rest, brief):
        args = dict(rest=rest, cache_seconds=self.cache_seconds, brief=brief, elapsed_ms=0, captured_replies=[])
        state = self.kernel('smart-plan-advance', args)
        require(state.get('state') != 'error', state.get('error', 'Invalid smart-plan input.'))
        label, match = option(rest, '--label'), option(rest, '--match') or option(rest, '--window') or ''
        role, text = option(rest, '--role'), option(rest, '--type-text')
        page, raw_port = option(rest, '--cdp-page-match'), option(rest, '--cdp-port')
        port = int32(raw_port)
        if port <= 0:
            port = 9222
        flag = lambda name: any(_ps_equal(word, name) for word in rest)
        schedule = [dict(kind='history', argv=[label, match, '5'])]
        if not flag('--no-cdp') and (flag('--allow-cdp') or page or raw_port):
            schedule.append(dict(kind='cdp_port', argv=[str(port), '120']))
        uia = ['-Action', 'uia-find', '-Label', label]
        if match:
            uia += ['-Match', match]
        if role:
            uia += ['-Role', role]
        schedule.append(dict(kind='native', argv=uia))
        if flag('--include-ocr') and text is None:
            ocr = ['-Action', 'ocr-uia-fuse', '-OcrText', label, '-OcrMatch', option(rest, '--ocr-match') or 'contains']
            if match:
                ocr += ['-Match', match]
            if option(rest, '--ocr-language'):
                ocr += ['-OcrLanguage', option(rest, '--ocr-language')]
            schedule.append(dict(kind='native', argv=ocr))
        started, captured = time.monotonic(), []
        for probe in range(6):
            require(state.get('state') != 'error', state.get('error', 'Smart-plan replay failed.'))
            require(type(state.get('queries')) is list, 'Missing original smart-plan acquisition trace.')
            if state['state'] == 'complete':
                require(probe == len(schedule) and state['queries'] == schedule, 'Smart-plan completed before its original schedule.')
                payload = state['payload']
                require(payload.get('schema') == 'cucp.smart-plan/v1' and type(payload.get('safe_to_act')) is bool and
                    payload.get('status') in {'ok', 'partial'} and state.get('exit') in {0, 2} and
                    (payload['status'] == 'ok') == payload['safe_to_act'] == (state['exit'] == 0), 'Invalid smart-plan completion.')
                elapsed = round((time.monotonic() - started) * 1000)
                payload['elapsed_ms'] = elapsed
                render = brief and not flag('--json-only')
                return dict(payload=payload, exit=state['exit'], json_depth=12, emit_json=not render,
                    brief=re.sub(r'elapsed_ms=\d+$', 'elapsed_ms=' + str(elapsed), state['brief']) if render else None)
            require(probe < 5 and probe < len(schedule) and state['state'] == 'query' and
                state['queries'] == schedule[:probe + 1] and state.get('query') == schedule[probe],
                'Smart-plan query exceeds the locally reconstructed read-only schedule.')
            descriptor = schedule[probe]
            reply = dict(descriptor)
            if descriptor['kind'] == 'history':
                reply['result'] = self.history.pick(label, match) if self.history is not None else None
            elif descriptor['kind'] == 'cdp_port':
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=min(.12, self.remaining())):
                        opened = True
                except OSError:
                    opened = False
                reply['result'] = opened
                if opened:
                    argv = ['-Action', 'cdp-smart-type-find' if text is not None else 'cdp-smart-find', '-CdpText', label, '-CdpPort', str(port)]
                    if page or match:
                        argv += ['-CdpPageMatch', page or match]
                    schedule.insert(probe + 1, dict(kind='native', argv=argv))
            else:
                try:
                    reply['result'] = self._native(descriptor['argv'])
                except OSError as error:
                    reply['error'] = str(error)
            captured.append(reply)
            args.update(captured_replies=captured, elapsed_ms=round((time.monotonic() - started) * 1000))
            state = self.kernel('smart-plan-advance', args)
        require(False, 'Smart-plan exceeded its original five-probe bound.')

    def _query(self, query, allowed):
        require(type(query) is dict and type(query.get('kind')) is str and type(query.get('argv')) is list,
            'Invalid planning query descriptor.')
        argv = query['argv']
        require(all(type(word) is str for word in argv) and len(argv) >= 4 and argv[:2] == ['-Quiet', 'macro'] and
            query['kind'] in allowed and argv[2] == allowed[query['kind']] and argv[-1] == '--json-only',
            'Planning query is outside the original read-only recipe.')
        require(self.child is not None, 'Root read-only planning child port is unavailable.')
        self.remaining()
        reply = self.child(argv[1:], self)
        exact(reply, ('exit', 'raw', 'json'))
        require(type(reply['exit']) is int and type(reply['raw']) is str and
            (reply['json'] is None or type(reply['json']) is dict), 'Invalid owned planning child reply.')
        self.remaining()
        return dict(kind=query['kind'], argv=argv, **reply)

    def run(self, operation, rest, *, brief=False):
        require(type(rest) is list and all(type(word) is str for word in rest), 'Planning argv must be strings.')
        if operation == 'smart-plan':
            return self.smart(rest, brief)
        if operation == 'workflow-plan':
            payload = self.workflow(rest)
            line = f"{payload['status']} workflow-plan steps={payload['step_count']} live={payload['live_step_count']} errors={len(payload['errors'])}"
            depth = 12
        elif operation in {'task-plan', 'form-plan'}:
            prepared = self.kernel(operation + '-prepare', dict(rest=rest))
            require(prepared.get('schema') == 'cucp.' + operation + '-preparation/v1' and type(prepared.get('queries')) is list,
                'Invalid task/form preparation response.')
            started = time.monotonic()
            allowed = {'smart_plan': 'smart-plan'}
            if operation == 'task-plan':
                allowed['form_plan'] = 'form-plan'
            captured = [self._query(query, allowed) for query in prepared['queries']]
            args = dict(rest=rest, captured_query_results=captured)
            if operation == 'task-plan':
                assembly = self.kernel('task-plan-assemble', args)
                require(assembly.get('schema') == 'cucp.task-plan-assembly/v1' and type(assembly.get('workflow_required')) is bool and
                    type(assembly.get('workflow_rest')) is list and all(type(word) is str for word in assembly['workflow_rest']),
                    'Invalid task workflow assembly response.')
                args['captured_workflow_plan'] = self.workflow(assembly['workflow_rest']) if assembly['workflow_required'] else None
            args['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            payload = self.kernel(operation + '-complete', args)
            safe = 'safe_to_run' if operation == 'task-plan' else 'safe_to_act'
            require(payload.get('schema') == 'cucp.' + operation + '/v1' and type(payload.get(safe)) is bool and
                payload.get('status') in {'ok', 'partial'} and (payload['status'] == 'ok') == payload[safe],
                'Invalid task/form planning completion response.')
            if operation == 'task-plan':
                line = f"{payload['status']} task-plan steps={payload['step_count']} live={payload['live_step_count']} errors={len(payload['errors'])} elapsed_ms={payload['elapsed_ms']}"
                depth = 18
            else:
                errors = '' if payload[safe] else f" errors={len(payload['errors'])}"
                line = f"{payload['status']} form-plan steps={payload['step_count']} safe={payload['safe_step_count']}{errors} match='{payload['match'] or ''}' elapsed_ms={payload['elapsed_ms']}"
                depth = 16
        elif operation == 'task-preset':
            prepared = self.kernel('task-preset-prepare', dict(rest=rest))
            require(prepared.get('schema') == 'cucp.task-preset-preparation/v1' and prepared.get('mode') in {'task', 'workflow'} and
                type(prepared.get('queries')) is list and len(prepared['queries']) == 1, 'Invalid task preset preparation.')
            query, elapsed = prepared['queries'][0], 0
            if prepared['mode'] == 'task':
                require(query.get('rest') is None, 'Unexpected task preset step string.')
                started = time.monotonic()
                reply = self._query(query, {'task_plan': 'task-plan'})
                captured = {key: reply[key] for key in ('exit', 'raw', 'json')}
                elapsed = round((time.monotonic() - started) * 1000)
            else:
                require(query.get('kind') == 'workflow_plan' and query.get('argv') is None and type(query.get('rest')) is list and
                    query['rest'] and all(type(word) is str for word in query['rest']), 'Invalid task preset workflow descriptor.')
                captured = dict(workflow_plan=self.workflow(query['rest']))
            payload = self.kernel('task-preset-complete', dict(rest=rest, captured_query_result=captured, elapsed_ms=elapsed))
            require(payload.get('schema') == 'cucp.task-preset/v1' and payload.get('status') in {'ok', 'partial'} and
                payload.get('kind') == prepared.get('kind'), 'Invalid task preset completion.')
            if prepared['mode'] == 'workflow':
                line = f"{payload['status']} task-preset kind={payload['kind']} mode=workflow steps={len(prepared['workflow_steps'])}"
            else:
                line = f"{payload['status']} task-preset kind={payload['kind']} task_plan_exit={payload['task_plan_exit']} elapsed_ms={payload['elapsed_ms']}"
            depth = 18
        else:
            require(False, 'Unknown retained planning operation.')
        render = brief and not any(_ps_equal(word, '--json-only') for word in rest)
        return dict(payload=payload, exit=0 if payload['status'] == 'ok' else 2, json_depth=depth,
            brief=line if render else None, emit_json=not render)
