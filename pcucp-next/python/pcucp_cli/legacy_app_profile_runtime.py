"""Bounded app-profile acquisition and single-write orchestration.

The closed C# facade supplies validated recipes. Ports supply existing desktop
and history facts; none of the request data selects a persistence destination.
"""
import copy
import math
import re
import time

from .legacy_cdp_contract import _ps_equal
from .legacy_host_protocol import exact, require
from .legacy_native_kernel import compatibility
from .legacy_native_macros import _truth


def _error_member(record):
    if type(record) is dict:
        return next((value for key, value in record.items() if key.lower() == 'error'), None)
    if type(record) is list:
        values = []
        for item in record:
            if type(item) is dict:
                for key, value in item.items():
                    if key.lower() == 'error':
                        values.extend(value if type(value) is list else [value])
                        break
        # Existing null-valued members still occupy array slots. Missing members
        # do not. Singleton output is unwrapped by the original condition.
        return values[0] if len(values) == 1 else values if values else None
    return None


class AppProfileRuntime:
    def __init__(self, acquire, *, history_file, culture='en-US', timeout_s=30,
                 parent_deadline=math.inf, cancelled=None, kernel=None, clock=time.monotonic):
        require(callable(acquire) and (history_file is None or type(history_file) is str)
                and type(culture) is str and type(timeout_s) in (int, float)
                and math.isfinite(timeout_s) and timeout_s > 0, 'Invalid app-profile startup.')
        self.acquire, self.history_file, self.culture = acquire, history_file, culture
        self.cancelled, self.clock, self._kernel = cancelled, clock, kernel
        self.deadline = min(parent_deadline, clock() + timeout_s)
        self.calls = self.evaluations = 0
        self.record_attempted = self.used = False

    def remaining(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'App-profile owner cancelled; no retry.')
        remaining = self.deadline - self.clock()
        require(remaining > 0, 'App-profile deadline expired; no retry.')
        return remaining

    def kernel(self, args):
        self.remaining()
        require(self.calls < 7, 'App-profile exceeded its facade call budget.')
        self.calls += 1
        if self._kernel is None:
            state = compatibility('app-profile-advance', args, culture=self.culture,
                                  timeout_s=self.remaining(), cancelled=self.cancelled)
        else:
            state = self._kernel(copy.deepcopy(args))
        self.remaining()
        require(type(state) is dict and state.get('facade') == 'cucp.app-profile-controller/v1'
                and type(state.get('kernel_evaluations')) is int
                and state['kernel_evaluations'] in (1, 2), 'Missing app-profile controller validation.')
        self.evaluations += state['kernel_evaluations']
        require(self.evaluations <= 8, 'App-profile exceeded its pure evaluation budget.')
        return state

    def run(self, rest, *, brief=False):
        require(not self.used, 'App-profile runtime already used; no queued replay.')
        self.used = True
        require(type(rest) is list and all(word is None or type(word) is str for word in rest)
                and type(brief) is bool, 'App-profile argv must be inert strings.')
        rest = ['' if word is None else word for word in rest]
        flag = lambda name: any(_ps_equal(word, name) for word in rest)
        requested = flag('--record-strategy') or flag('--remember-strategy')
        enabled = not flag('--no-strategy-history')
        args = dict(rest=rest, brief=brief, culture=self.culture, history_file=self.history_file,
                    elapsed_ms=0, cdp_elapsed_ms=0, uia_elapsed_ms=0, captured_replies=[])
        captures, ready, cdp_started, cdp_elapsed = [], None, None, None
        started = self.clock()
        elapsed = lambda since: round((self.clock() - since) * 1000)
        for probe in range(8):
            self.remaining()
            state = ready if ready is not None else self.kernel(args)
            require(state.get('state') != 'error', state.get('error', 'App-profile controller failed.'))
            trace = state.get('queries')
            require(type(trace) is list and trace[:len(captures)] ==
                    [dict(kind=row['kind'], argv=row['argv']) for row in captures],
                    'Invalid app-profile completion trace.')
            if state.get('state') == 'complete':
                require(len(trace) == len(captures), 'Invalid app-profile completion trace.')
                state['payload']['elapsed_ms'] = elapsed(started)
                render = brief and not flag('--json-only')
                return dict(payload=state['payload'], exit=state['exit'], json_depth=state['json_depth'],
                            queries=trace, emit_json=not render,
                            brief=re.sub(r'elapsed_ms=\d+$', 'elapsed_ms=' + str(state['payload']['elapsed_ms']),
                                         state['brief']) if render else None)
            query = state.get('query')
            require(probe < 7 and state.get('state') == 'query' and len(trace) == len(captures) + 1
                    and type(query) is dict and trace[-1] == query, 'Invalid app-profile acquisition state.')
            exact(query, ('kind', 'argv'))
            kind, argv = query['kind'], query['argv']
            require(type(argv) is list and all(type(word) is str for word in argv),
                    'Invalid app-profile acquisition state.')
            authorization = state.get('record_authorization')
            completion = state.get('record_completion')
            if kind == 'record':
                score = authorization.get('strategy_score', {}) if type(authorization) is dict else {}
                total = score.get('total_score')
                confidence = 'high' if type(total) is int and total >= 75 else 'medium'
                require(requested and enabled and not self.record_attempted
                        and state['kernel_evaluations'] == 2 and type(authorization) is dict
                        and authorization.get('schema') == 'cucp.app-profile-record-authorization/v1'
                        and type(completion) is dict and completion.get('state') == 'complete'
                        and completion.get('payload', {}).get('schema') == 'cucp.app-profile/v1'
                        and completion.get('queries') == trace and authorization.get('history_file') == self.history_file
                        and type(total) is int and 50 <= total <= 100 and score.get('confidence') == confidence
                        and len(argv) == 8 and authorization.get('query') == query,
                        'App-profile record lacks a valid explicit authorization.')
            else:
                require(authorization is None and completion is None and state['kernel_evaluations'] == 1,
                        'Unexpected app-profile record authorization.')
            closed = (kind == 'windows' and (argv == [] or len(argv) == 2 and argv[0] == '-Match') or
                      kind == 'cdp_port' and len(argv) == 2 and argv[1] == '120' or
                      kind == 'native' and len(argv) == 4 and argv[:3] == ['-Action', 'cdp-detect', '-CdpPort'] or
                      kind == 'uia' and len(argv) == 8 and argv[::2] == ['-FocusedWindow', '-MaxElements', '-MinSize', '-Hwnd'] and argv[5] == '6' or
                      kind == 'history' and len(argv) == 1 and enabled or kind == 'record' and len(argv) == 8)
            require(closed, 'Unsupported app-profile acquisition kind.')
            if kind == 'cdp_port':
                cdp_started = self.clock()
            uia_started = self.clock() if kind == 'uia' else None
            if kind == 'record':
                # Set before dispatch: an exception must never allow a second append.
                self.record_attempted = True
            self.remaining()
            reply = self.acquire(copy.deepcopy(query))
            require(type(reply) is dict and (set(reply) in ({'result'}, {'error'}) or
                    kind == 'record' and set(reply) == {'result', 'recorded'} and type(reply['recorded']) is bool)
                    and ('error' not in reply or type(reply['error']) is str), 'Invalid app-profile acquisition reply.')
            if 'error' in reply:
                require(kind != 'record', reply['error'])
            elif kind == 'record':
                record = reply['result']
                error = _error_member(record)
                completion['payload']['strategy_persistence'].update(
                    record=record, recorded=reply.get('recorded', _truth(record) and not _truth(error)))
                ready = completion
            elif kind == 'cdp_port' and not _truth(reply['result']) or kind == 'native':
                if 'error' not in reply:
                    require(cdp_started is not None, 'Missing app-profile CDP measurement.')
                    cdp_elapsed = elapsed(cdp_started)
            elif kind == 'uia':
                args['uia_elapsed_ms'] = elapsed(uia_started)
            if cdp_elapsed is not None:
                args['cdp_elapsed_ms'] = cdp_elapsed
            captures.append(dict(query, **{key:value for key,value in reply.items() if key != 'recorded'}))
            args['captured_replies'] = captures
        require(False, 'App-profile did not finish within its acquisition bound.')
