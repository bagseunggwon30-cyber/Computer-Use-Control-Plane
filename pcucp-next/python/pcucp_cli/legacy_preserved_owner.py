"""Shared staged owner for the already connected preserved legacy surfaces.

Every public invocation takes a fresh bounded scope. Typed nested calls reuse
the owner and restrict both ceilings; they do not acquire/overwrite an outer
session lock, reset the deadline, or create an implicit replay. This candidate
does not change the production launcher or advertise the remaining cutovers.
"""
from dataclasses import dataclass
import json
import math
import threading
import time
from .legacy_cdp import LegacyCdpAdapter
from .legacy_cdp_contract import ACTIONS as CDP, LIVE_ACTIONS as CDP_LIVE, prepare_macro
from .legacy_cdp_macro import LegacyCdpPortCache, execute_macro
from .legacy_coordinates import Coordinates
from .legacy_diagnostic_provider import OPERATIONS as DIAGNOSTICS, owned_path, option
from .legacy_diagnostic_runtime import DiagnosticRuntime
from .legacy_dispatch import classify_top_level, requires_direct_safety
from .legacy_execution_provider import OPERATIONS as EXECUTION
from .legacy_execution_runtime import ExecutionRuntime
from .legacy_host_protocol import Authority, LegacyHostError, require
from .legacy_host_session import Cancellation, LegacyEffectSession, cancel_with_owner
from .legacy_label_provider import LabelReadProvider
from .legacy_native_kernel import compatibility
from .legacy_native_macros import NativeMacros, OPERATIONS as NATIVE
from .legacy_planning_runtime import PlanningRuntime
from .legacy_storage import append_trajectory
from .legacy_windows import observe_windows
from .native_session import NativeSession

PLANNING = frozenset(('workflow-plan', 'task-plan', 'form-plan', 'task-preset', 'smart-plan'))


@dataclass(frozen=True)
class Invocation:
    authority: Authority
    deadline: float
    cancelled: object
    depth: int = 0

    def remaining(self):
        require(not self.cancelled.is_set(), 'Legacy owner cancelled; action not retried.')
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'Legacy invocation timed out; action not retried.')
        return remaining

    def child(self, authority):
        require(self.depth < 64, 'Legacy invocation nesting exceeds 64.')
        ceiling = self.authority.restrict(authority.live, authority.sensitive)
        return Invocation(ceiling, self.deadline, self.cancelled, self.depth + 1)


def render(result):
    if result.get('raw') is not None:
        return result['raw']
    text = ''.join(result.get('console', []))
    if result.get('brief') is not None:
        text += result['brief'] + '\n'
    elif result['emit_json']:
        text += json.dumps(result['payload'], ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    return text


def capture(result):
    raw = render(result)
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    return dict(exit=result['exit'], raw=raw, json=value)


class PreservedOwner:
    def __init__(self, context, *, authority=Authority(), culture='en-US', timeout_s=30, cache_seconds=2):
        require(type(authority) is Authority and type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0,
            'Invalid preserved owner startup.')
        self.context = dict(context)
        for key in ('audit_directory', 'cache_directory', 'wrapper_log', 'changelog_path', 'temp_root'):
            self.context[key] = str(owned_path(context[key]))
        self.authority, self.culture, self.timeout_s, self.cache_seconds = authority, culture, timeout_s, cache_seconds
        self._cancelled, self._serial, self._lock = threading.Event(), threading.Lock(), threading.RLock()
        self._active, self._cdp_cache = set(), LegacyCdpPortCache()

    @property
    def closed(self):
        return self._cancelled.is_set()

    def close(self):
        self._cancelled.set()
        with self._lock:
            active = tuple(self._active)
        for port in active:
            port.close()

    def _owned(self, port, scope, callback):
        scope.remaining()
        with self._lock:
            require(not self.closed, 'Preserved owner closed; action not retried.')
            self._active.add(port)
        try:
            with cancel_with_owner(port, scope.cancelled):
                result = callback(port)
            scope.remaining()
            return result
        finally:
            port.close()
            with self._lock:
                self._active.discard(port)

    def _planning(self, scope):
        return PlanningRuntime(culture=self.culture, timeout_s=scope.remaining(), parent_deadline=scope.deadline,
            cancelled=scope.cancelled, audit_directory=self.context['audit_directory'], cache_seconds=self.cache_seconds,
            child=lambda argv, port: capture(self._invoke(argv, scope.child(Authority()), brief=False, quiet=True)))

    def _desktop_runtime(self, scope, **ports):
        return ExecutionRuntime(audit_directory=self.context['audit_directory'], cache_directory=self.context['cache_directory'],
            authority=scope.authority, timeout_s=scope.remaining(), parent_deadline=scope.deadline, culture=self.culture,
            cache_seconds=self.cache_seconds, vision_available=bool(self.context.get('cli_path')), parent_cancelled=scope.cancelled, **ports)

    def _observations(self, scope, callback):
        runtime = DiagnosticRuntime(self.context, culture=self.culture, timeout_s=scope.remaining(),
            cache_seconds=self.cache_seconds, parent_deadline=scope.deadline, parent_cancelled=scope.cancelled)
        runtime._bind_session(scope.deadline, scope.cancelled)
        def observe(native):
            runtime.native = native
            return callback(runtime)
        return self._owned(NativeSession(), scope, observe)

    def invoke(self, argv, *, brief=False, quiet=False):
        require(type(brief) is bool and type(quiet) is bool, 'Legacy invocation output flags must be Boolean.')
        require(self._serial.acquire(blocking=False), 'Preserved owner already has an invocation; no queued replay.')
        scope = Invocation(self.authority, time.monotonic() + self.timeout_s, self._cancelled)
        try:
            result = self._invoke(argv, scope, brief=brief, quiet=quiet)
            return result['exit'], render(result)
        except LegacyHostError as error:
            if error.uncertain or self._cancelled.is_set():
                self.close()
            raise
        finally:
            self._serial.release()

    def _invoke(self, argv, scope, *, brief, quiet):
        scope.remaining()
        require(type(argv) is list and all(type(word) is str for word in argv), 'Legacy invocation argv must be inert strings.')
        route = classify_top_level(argv)
        require(route.kind == 'macro' and route.macro is not None,
            'unqualified_surface: top-level aliases/Node forwarding still require their separate cutover.')
        name, rest = route.macro.name, list(route.rest)
        if route.macro.implementation == 'not_implemented':
            payload = dict(schema='cucp.not-implemented/v1', status='not_implemented', macro=name,
                summary=f"매크로 '{name}' 는 이 버전에서 아직 구현되지 않았습니다 (surface 에는 등록됨).", hint=route.macro.hint or '',
                next_action="다른 매크로로 대체하거나, 이 기능이 필요하면 별도 구현 요청. 'cucp macro' 로 사용 가능 목록 확인.")
            return dict(payload=payload, exit=1, json_depth=6, brief='not_implemented ' + name if brief else None, emit_json=not brief)
        available = name in DIAGNOSTICS | EXECUTION | PLANNING | NATIVE | CDP | {'windows', 'metrics', 'find-label'}
        require(available, 'unqualified_surface: preserved macro ' + name + ' still requires its closed provider.')
        # Derive consent only from the invocation's original argv and ceiling.
        confirmed = compatibility('execution-confirmation', dict(original_argv=rest), culture=self.culture,
            timeout_s=scope.remaining(), cancelled=scope.cancelled)['confirmed'] and scope.authority.sensitive
        scope = Invocation(Authority(scope.authority.live, bool(confirmed)), scope.deadline, scope.cancelled, scope.depth)
        if scope.authority.live and requires_direct_safety(name) and not confirmed:
            safety = compatibility('safety-classify', dict(text=' '.join([name, *rest]), macro=name), culture=self.culture,
                timeout_s=scope.remaining(), cancelled=scope.cancelled)
            if safety['requires_explicit_confirmation']:
                payload = dict(schema='cucp.safety-block/v1', status='blocked', reason='sensitive_action_requires_confirmation',
                    macro=name, confirmation_flag='--confirm-sensitive', safety=safety,
                    next_action='Re-run with --confirm-sensitive only if the user explicitly approved this exact sensitive live action.')
                return dict(payload=payload, exit=3, json_depth=10, emit_json=not brief,
                    brief=f"blocked {name} reason=sensitive_action_requires_confirmation risk={safety['risk_level']}" if brief else None)
        if name in DIAGNOSTICS:
            runtime = DiagnosticRuntime(self.context, culture=self.culture, timeout_s=scope.remaining(), cache_seconds=self.cache_seconds,
                parent_deadline=scope.deadline, parent_cancelled=scope.cancelled)
            return runtime.run(name, rest, brief=brief)
        if name in PLANNING:
            return self._planning(scope).run(name, rest, brief=brief)
        if name in EXECUTION:
            def child(effect, provider):
                ceiling = scope.authority.restrict(effect.live, effect.confirm_sensitive)
                return capture(self._invoke(list(effect.argv), scope.child(ceiling), brief=effect.brief, quiet=effect.quiet))
            def local(effect, provider):
                ceiling = scope.authority.restrict(effect.live, False)
                return capture(self._invoke(['macro', effect.name, *effect.argv], scope.child(ceiling), brief=brief, quiet=quiet))
            runtime = self._desktop_runtime(scope, child=child, local_macro=local)
            result = self._owned(runtime, scope, lambda port: port.run(name, rest, brief=brief))
            # Execution Console effects are WriteLine; native interaction effects
            # separately retain Write. Keep this distinction in the root report.
            result['console'] = [line + '\n' for line in result['console']]
            return result
        if name in NATIVE:
            runtime = self._desktop_runtime(scope)
            def run(port):
                native = lambda argv, ceiling: port.native(argv, scope.authority.restrict(ceiling.live, ceiling.sensitive), scope)
                return NativeMacros(native, cache_directory=self.context['cache_directory'], audit_directory=self.context['audit_directory'],
                    authority=scope.authority).run(name, rest, brief=brief)
            return self._owned(runtime, scope, run)
        if name in CDP:
            macro = prepare_macro(name, rest, allow_live_control=scope.authority.live)
            remaining = min(30, scope.remaining())
            require(remaining >= .05, 'Insufficient inherited CDP budget.')
            adapter = LegacyCdpAdapter(f'http://127.0.0.1:{macro.port}', allow_live_control=scope.authority.live, timeout_s=remaining)
            result = self._owned(adapter, scope, lambda port: execute_macro(port, macro, cache=self._cdp_cache))
            if result.trajectory:
                append_trajectory(self.context['audit_directory'], result.trajectory['kind'], result.trajectory['payload'])
            return dict(payload=result.payload, exit=result.exit_code, json_depth=result.json_depth,
                brief=result.brief_line if brief else None, emit_json=not brief)
        if name == 'find-label':
            def labels(runtime):
                provider = LabelReadProvider(runtime, rest, brief=brief)
                return self._owned(LegacyEffectSession(timeout_s=scope.remaining(), parent_cancelled=scope.cancelled), scope,
                    lambda session: session.run('interaction', provider.startup(), Authority(), provider))
            return self._observations(scope, labels)
        if name == 'windows':
            def windows(runtime):
                code, payload, line = observe_windows(runtime, rest)
                render_brief = brief and '--json-only' not in rest
                return dict(payload=payload, exit=code, json_depth=8, brief=line if render_brief else None, emit_json=not render_brief)
            return self._observations(scope, windows)
        if name == 'metrics':
            payload = DiagnosticRuntime(self.context, culture=self.culture, timeout_s=scope.remaining(), cache_seconds=self.cache_seconds)._metrics()
            return dict(payload=payload, exit=0, json_depth=8, brief=None, emit_json=True)
        require(False, 'Unknown explicitly connected legacy macro.')
