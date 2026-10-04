"""Opt-in candidate for the *legacy*, detached shared helper service.

The explicit unqualified production stage supplies concrete adapters; default
shipping routing remains unchanged. Acquisition stays explicit: a caller must
supply a lock store, process-existence probe, clock, pipe transport, and (only for
an explicit start) an owned detached launcher. This pure client has no executable resolver,
PowerShell evaluator, autostart, input surface, or modern NativeSession coupling.

The published reference is commit 3e892ab02395bdc916a5814e39d4154efd1f6249,
tree e36329b2a6b07539faacd070d661bc0e3819140d, scripts/cucp.ps1.
Intentional corrections, not parity claims: strict bounded frames and integer
IDs, revalidation before pipe contact, foreign-lock non-deletion, and atomic
identity-aware conditional cleanup. Legacy owner_user absence is still accepted;
owner/name/PID checks do NOT authenticate the server or prevent PID reuse. A
request may still race replacement after its final snapshot check; transport
peer authentication remains out of scope. A trusted same-user service/transport acquisition boundary remains necessary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re
import threading
from typing import Any, Callable, Mapping, Protocol

READ_ACTIONS = frozenset(('windows', 'health', 'focused', 'modal-detect',
                          'ocr-screen-fast', 'uia-find-fast'))
PIPE_ACTIONS = READ_ACTIONS | {'shutdown'}
HOT_ACTIONS = frozenset(('windows', 'health', 'focused', 'modal-detect'))
FORWARDED_OPTIONS = ('Match', 'TargetMatch', 'TargetHwnd')
MAX_FRAME_BYTES = 1024 * 1024
MAX_LOCK_BYTES = 16384


class HelperClientError(RuntimeError):
    def __init__(self, code: str, detail: str = ''):
        self.code = code
        super().__init__(code + (': ' + detail if detail else ''))


class Clock(Protocol):
    def utcnow(self) -> datetime: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class LockSnapshot:
    """Bytes plus an acquisition identity, not just the advertised PID.

    Stores must return a stable identity that changes even when a replacement
    lock has identical contents. No code here derives process ownership from it.
    """
    raw: bytes
    identity: object


class LockStore(Protocol):
    def read(self) -> LockSnapshot | None: ...
    def compare_delete(self, expected: LockSnapshot) -> bool:
        """Atomically delete only this acquisition identity AND exact bytes.

        A read/check followed by a pathname unlink does not satisfy this contract.
        If the platform adapter cannot guarantee this, it must return False.
        """
        ...


class PipeTransport(Protocol):
    def exchange(self, pipe_name: str, request: bytes, *, connect_timeout_ms: int,
                 read_timeout_ms: int) -> bytes:
        """One connection/request/line; enforce deadlines and close on all paths.

        The adapter must bound reads to MAX_FRAME_BYTES and never retry. A timeout
        or disconnect after sending does not prove the operation was unexecuted.
        """
        ...


class OwnedDetachedProcess(Protocol):
    pid: int
    def terminate_owned(self) -> None:
        """Terminate only the retained newly launched process object/handle."""
        ...


class DetachedLauncher(Protocol):
    def launch(self, *, idle_timeout_ms: int) -> OwnedDetachedProcess:
        """Start the fixed candidate service detached, without parent-death kill.

        The adapter must retain the created process identity; a PID lookup is not
        an owned handle. No service path/argv is accepted from a helper request.
        """
        ...


@dataclass(frozen=True)
class LockRecord:
    pid: int
    pipe_name: str
    started_at: str
    helper_version: str
    owner_user: str | None


@dataclass(frozen=True)
class LockState:
    kind: str
    reason: str
    snapshot: LockSnapshot | None
    record: LockRecord | None = None

    @property
    def usable(self) -> bool:
        return self.kind == 'valid'


# PowerShell string comparisons in the retained wrappers are case-insensitive.
def _eq(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON member')
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('nonfinite JSON exponent')
    return value


def _json(raw: str | bytes):
    return json.loads(raw, object_pairs_hook=_strict_object, parse_float=_finite_float,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read_lock_safely(snapshot: LockSnapshot | None) -> Mapping[str, Any] | None:
    if snapshot is None or not isinstance(snapshot.raw, bytes) or len(snapshot.raw) > MAX_LOCK_BYTES:
        return None
    try:
        value = _json(snapshot.raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def inspect_lock(snapshot: LockSnapshot | None, *, owner_user: str,
                 now: datetime, process_alive: Callable[[int], bool]) -> LockState:
    """Pure except the explicit, read-only process-existence acquisition seam."""
    if snapshot is None:
        return LockState('missing', 'helper_lock_missing', None)
    value = read_lock_safely(snapshot)
    if value is None:
        return LockState('malformed', 'helper_lock_malformed', snapshot)
    owner = value.get('owner_user')
    if owner not in (None, ''):
        if not isinstance(owner, str) or not _eq(owner, owner_user):
            return LockState('foreign', 'foreign_owner', snapshot)
    pid = value.get('pid')
    if type(pid) is not int or not 0 < pid <= 2147483647:
        return LockState('stale', 'invalid_pid', snapshot)
    # Never contact or terminate the advertised process: existence is read-only.
    try:
        if not process_alive(pid):
            return LockState('stale', 'process_missing', snapshot)
    except Exception:
        return LockState('stale', 'process_probe_failed', snapshot)
    started = value.get('started_at')
    try:
        if not isinstance(started, str) or not started:
            raise ValueError('missing date')
        date = datetime.fromisoformat(started.replace('Z', '+00:00'))
        # Unlike culture-dependent DateTime.Parse, only explicit-offset ISO dates
        # are accepted by this candidate; this is an intentional fail-closed edge.
        if date.tzinfo is None or now.tzinfo is None:
            raise ValueError('timezone required')
        if (now.astimezone(timezone.utc) - date.astimezone(timezone.utc)).total_seconds() > 86400:
            return LockState('stale', 'lock_expired', snapshot)
    except (ValueError, TypeError, OverflowError):
        return LockState('stale', 'invalid_started_at', snapshot)
    pipe = value.get('pipe_name')
    if not isinstance(pipe, str) or not _eq(pipe, f'cucp-helper-{pid}'):
        return LockState('stale', 'invalid_pipe_name', snapshot)
    version = value.get('helper_version')
    if not isinstance(version, str) or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) is None:
        return LockState('stale', 'invalid_helper_version', snapshot)
    return LockState('valid', '', snapshot, LockRecord(pid, pipe, started, version, owner))


def _positive_integer(value, label):
    if type(value) is not int or not 0 < value <= 2147483647:
        raise ValueError(f'{label} must be a positive 32-bit integer')
    return value


def _idle_timeout(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise ValueError('idle_timeout_ms must be a nonnegative 32-bit integer')
    return value


def frame_request(request_id: int, action: str, args: Mapping[str, Any], timeout_ms: int) -> bytes:
    _positive_integer(request_id, 'request_id')
    _positive_integer(timeout_ms, 'timeout_ms')
    if not isinstance(action, str) or action.casefold() not in PIPE_ACTIONS:
        raise HelperClientError('unsupported_helper_action')
    if not isinstance(args, Mapping) or any(not isinstance(key, str) for key in args):
        raise HelperClientError('invalid_helper_args')
    # Data only, never a method, executable, command, script or expression field.
    allowed = {name.casefold() for name in (*FORWARDED_OPTIONS, 'Label', 'X', 'Y', 'W', 'H')}
    if any(key.casefold() not in allowed for key in args):
        raise HelperClientError('unsupported_helper_argument')
    if action.casefold() == 'shutdown' and args:
        raise HelperClientError('unexpected_helper_argument')
    try:
        result = json.dumps(dict(id=request_id, action=action, args=dict(args), timeout_ms=timeout_ms),
                            ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8') + b'\n'
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise HelperClientError('invalid_helper_args') from exc
    if len(result) > MAX_FRAME_BYTES:
        raise HelperClientError('pipe_request_too_large')
    return result


def parse_response(raw: bytes, request_id: int) -> dict:
    if not isinstance(raw, bytes):
        raise HelperClientError('pipe_invalid_response')
    if len(raw) > MAX_FRAME_BYTES:
        raise HelperClientError('pipe_response_too_large')
    if not raw.strip():
        raise HelperClientError('pipe_empty_response')
    try:
        line = raw.decode('utf-8-sig').removesuffix('\n').removesuffix('\r')
        if '\r' in line or '\n' in line:
            raise ValueError('more than one response line')
        response = _json(line)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HelperClientError('pipe_invalid_response') from exc
    if not isinstance(response, dict):
        raise HelperClientError('pipe_invalid_response')
    if type(response.get('id')) is not int or response['id'] != request_id:
        raise HelperClientError('pipe_id_mismatch')
    code = response.get('exit_code')
    if type(code) is not int or not -2147483648 <= code <= 2147483647:
        raise HelperClientError('pipe_invalid_exit_code')
    return response


def status_envelope(state: LockState, extra: Mapping | None = None) -> dict:
    record = state.record if state.usable else None
    result = dict(schema='cucp.helper-status/v1', alive=bool(record),
                  pid=record.pid if record else None,
                  pipe_name=record.pipe_name if record else None,
                  started_at=record.started_at if record else None,
                  uptime_s=0, request_count=0,
                  helper_version=record.helper_version if record else None)
    if record and isinstance(extra, Mapping):
        for key in ('uptime_s', 'request_count'):
            value = extra.get(key)
            # Do not promote arbitrary objects or bools to status counters.
            if type(value) is int and 0 <= value <= 2147483647:
                result[key] = value
    return result


class LegacyHelperClient:
    def __init__(self, *, store: LockStore, transport: PipeTransport, clock: Clock,
                 process_alive: Callable[[int], bool], owner_user: str):
        if not isinstance(owner_user, str) or not owner_user:
            raise ValueError('Explicit owner_user is required')
        self.store, self.transport, self.clock = store, transport, clock
        self.process_alive, self.owner_user = process_alive, owner_user
        self._request_id = 0
        self._request_lock = threading.Lock()

    def state(self) -> LockState:
        try:
            snapshot = self.store.read()
        except (OSError, ValueError):
            return LockState('unreadable', 'helper_lock_unreadable', None)
        return inspect_lock(snapshot, owner_user=self.owner_user, now=self.clock.utcnow(),
                            process_alive=self.process_alive)

    def _delete(self, state: LockState) -> bool:
        if state.snapshot is None or state.kind in {'foreign', 'missing', 'malformed'}:
            return False
        try:
            return bool(self.store.compare_delete(state.snapshot))
        except (OSError, ValueError):
            return False

    def invoke(self, action: str, args: Mapping[str, Any] | None = None, *,
               timeout_ms: int = 30000, expected: LockState | None = None) -> dict:
        # Validate before lock acquisition; unsupported/mutation routes never
        # acquire a pipe, even when no service currently exists.
        args = {} if args is None else args
        frame_request(1, action, args, timeout_ms)
        with self._request_lock:
            state = self.state()
            if not state.usable:
                raise HelperClientError(state.reason)
            if expected is not None and (not expected.usable or state.snapshot != expected.snapshot):
                raise HelperClientError('helper_lock_changed')
            self._request_id += 1
            if self._request_id > 2147483647:
                self._request_id = 1
            request_id = self._request_id
            frame = frame_request(request_id, action, args, timeout_ms)
            try:
                raw = self.transport.exchange(state.record.pipe_name, frame,
                                              connect_timeout_ms=min(2000, timeout_ms),
                                              read_timeout_ms=timeout_ms)
            except TimeoutError as exc:
                raise HelperClientError('pipe_read_timeout') from exc
            except OSError as exc:
                raise HelperClientError('pipe_transport_error') from exc
            return parse_response(raw, request_id)

    def status(self) -> dict:
        state = self.state()
        extra = None
        if state.usable:
            try:
                response = self.invoke('health', timeout_ms=1500, expected=state)
                if response['exit_code'] == 0:
                    extra = response.get('result')
            except HelperClientError:
                pass
        # Legacy alive means fresh lock + existing PID, not authenticated health.
        return status_envelope(state, extra)

    def start(self, launcher: DetachedLauncher, *, idle_timeout_ms: int = 60000) -> dict:
        _idle_timeout(idle_timeout_ms)
        state = self.state()
        if state.usable:
            return _started(state.record, reused=True)
        if state.kind == 'unreadable':
            return dict(status='error', reason='helper_lock_unreadable')
        if state.kind == 'foreign':
            return dict(status='error', reason='foreign_lock_ignored')
        if state.kind == 'stale' and not self._delete(state):
            return dict(status='error', reason='helper_lock_changed_or_not_removable')
        if state.kind == 'malformed':
            return dict(status='error', reason='helper_lock_malformed')
        # Deliberately no catch-and-respawn. A launch adapter error may still
        # mean a child exists; it must retain its own evidence/ownership.
        process = launcher.launch(idle_timeout_ms=idle_timeout_ms)
        succeeded = False
        try:
            _positive_integer(process.pid, 'launched pid')
            deadline = self.clock.monotonic() + 3.0
            while self.clock.monotonic() < deadline:
                self.clock.sleep(min(.05, max(0.0, deadline - self.clock.monotonic())))
                observed = self.state()
                if observed.usable and observed.record.pid == process.pid:
                    succeeded = True
                    return _started(observed.record, reused=False)
        finally:
            # Successful services outlive this invocation. On failure, only this
            # newly launched handle can be killed. Even a matching lock PID is
            # insufficient to prove that its file belongs to the launch, so
            # timeout cleanup conservatively leaves it for the owned server.
            if not succeeded:
                try:
                    process.terminate_owned()
                except OSError:
                    pass
        return dict(status='error', reason='server_start_timeout')

    def stop(self, *, force: bool = False) -> dict:
        if type(force) is not bool:
            raise ValueError('force must be boolean')
        state = self.state()
        if state.kind in {'missing', 'malformed'}:
            return dict(status='ok', reason='no_helper_running')
        if state.kind == 'unreadable':
            return dict(status='error', reason='helper_lock_unreadable', stopped_pid=None, forced=False)
        if state.kind == 'foreign':
            return dict(status='ok', reason='foreign_lock_ignored', stopped_pid=None, forced=False)
        if not state.usable:
            deleted = self._delete(state)
            return dict(status='ok', reason='stale_lock_removed' if deleted else 'stale_lock_preserved',
                        stopped_pid=None, forced=False)
        try:
            response = self.invoke('shutdown', timeout_ms=1500, expected=state)
            if response['exit_code'] != 0:
                raise HelperClientError('shutdown_not_acknowledged')
        except HelperClientError:
            return dict(status='error', reason='shutdown_not_acknowledged_no_pid_kill',
                        stopped_pid=None, forced=False)
        self._delete(state)
        return dict(status='ok', reason='shutdown_requested', stopped_pid=state.record.pid, forced=False)


def _started(record: LockRecord, *, reused: bool) -> dict:
    return dict(status='ok', reused=reused, pid=record.pid,
                pipe_name=record.pipe_name, started_at=record.started_at)


def legacy_environment_truth(value: str | None) -> bool:
    """PowerShell nonempty environment strings, including '0'/'false', are true."""
    if value is not None and not isinstance(value, str):
        raise ValueError('Environment values must be strings or None')
    return bool(value)


@dataclass(frozen=True)
class RoutePlan:
    action: str
    forwarded_args: Mapping[str, str]
    pipe_eligible: bool
    hot_key: str | None
    timeout_ms: int
    argv: tuple[str, ...]


def plan_route(argv, *, force_child=False, force_child_env=None, hot_cache_disable_env=None,
               cache_seconds=2, timeout_ms=0, default_timeout_ms=30000) -> RoutePlan:
    if (not isinstance(argv, (list, tuple)) or len(argv) < 2 or
            any(not isinstance(value, str) for value in argv) or
            not _eq(argv[0], '-Action') or not argv[1]):
        raise ValueError('Native helper requests must begin with -Action and a nonempty action value.')
    if type(force_child) is not bool:
        raise ValueError('force_child must be boolean')
    if type(timeout_ms) is not int:
        raise ValueError('timeout_ms must be an integer')
    if isinstance(cache_seconds, bool) or not isinstance(cache_seconds, (int, float)) or not math.isfinite(cache_seconds):
        raise ValueError('cache_seconds must be finite')
    timeout = timeout_ms if timeout_ms > 0 else default_timeout_ms
    _positive_integer(timeout, 'timeout_ms')
    action = argv[1]
    forwarded = {}
    for name in FORWARDED_OPTIONS:
        for index in range(len(argv) - 1):
            if _eq(argv[index], '-' + name):
                forwarded[name] = argv[index + 1]
                break
    eligible = (not force_child and not legacy_environment_truth(force_child_env)
                and action.casefold() in READ_ACTIONS)
    hot = None
    if (not legacy_environment_truth(hot_cache_disable_env) and cache_seconds > 0
            and action.casefold() in HOT_ACTIONS):
        # The legacy hashtable's cache keys are case-insensitive, including values.
        hot = (action + '|' + ''.join('-' + key + '=' + value + '|' for key, value in forwarded.items())).casefold()
    return RoutePlan(action, forwarded, eligible, hot, timeout, tuple(argv))


@dataclass(frozen=True)
class ChildResult:
    exit_code: int
    raw: str
    stderr: str = ''
    elapsed_ms: int = 0
    timed_out: bool = False
    launch_error: str | None = None


def child_envelope(child: ChildResult) -> dict:
    if child.timed_out:
        return dict(ExitCode=124, Json=None, Raw='', Err=child.stderr, ElapsedMs=child.elapsed_ms)
    if child.launch_error is not None:
        return dict(ExitCode=1, Json=None, Raw='', Err=child.launch_error,
                    ElapsedMs=child.elapsed_ms, Route='child-error')
    value = None
    try:
        value = _json(child.raw) if child.raw.strip() else None
    except (ValueError, RecursionError):
        pass
    code = child.exit_code
    if code == 0 and isinstance(value, dict):
        status = value.get('status')
        if isinstance(status, str):
            code = {'partial': 2, 'error': 1}.get(status.casefold(), 0)
    return dict(ExitCode=code, Json=value, Raw=child.raw, Err=child.stderr,
                ElapsedMs=child.elapsed_ms, FromHotCache=False, Route='child')


@dataclass
class HotCache:
    entries: dict = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    def get(self, key: str | None, now: float) -> dict | None:
        if key is None:
            return None
        if key in self.entries:
            expires, result = self.entries[key]
            if expires > now:
                self.hits += 1
                return dict(result, Err=None, ElapsedMs=0, FromHotCache=True, Route='hot-cache')
            self.evictions += 1
            del self.entries[key]
        self.misses += 1
        return None

    def put(self, key: str | None, now: float, result: dict) -> None:
        value = result.get('Json')
        # PS truth: objects (even empty objects) are true; empty/single arrays
        # differ from Python. Cache only nonempty truthy results as PS does.
        if key is None or result.get('ExitCode') != 0 or not _ps_truth(value):
            return
        self.entries[key] = (now + .5, dict(result))
        if len(self.entries) > 16:
            oldest = min(self.entries, key=lambda item: self.entries[item][0])
            del self.entries[oldest]
            self.evictions += 1


def _ps_truth(value) -> bool:
    if isinstance(value, dict):
        return True
    if isinstance(value, list):
        return len(value) > 1 or (len(value) == 1 and _ps_truth(value[0]))
    return bool(value)


class LegacyHelperRouter:
    """Only known read acquisitions may fall back after an uncertain pipe call.

    plan_route can describe other legacy actions, but invoke cannot execute them.
    The explicit child_read callback is a typed acquisition seam, not a generic
    command runner. shutdown is available only via client.stop(), never replayed.
    """
    def __init__(self, client: LegacyHelperClient, child_read: Callable[[RoutePlan], ChildResult]):
        self.client, self.child_read, self.cache = client, child_read, HotCache()

    def invoke(self, argv, *, native_helper_available: bool = True, **options) -> dict:
        plan = plan_route(argv, **options)
        if plan.action.casefold() not in READ_ACTIONS:
            raise HelperClientError('unsupported_read_acquisition')
        if type(native_helper_available) is not bool:
            raise ValueError('native_helper_available must be boolean')
        if not native_helper_available:
            return dict(ExitCode=1, Json=None, Raw='', Err='native_helper_missing', ElapsedMs=0)
        started = self.client.clock.monotonic()
        if plan.pipe_eligible:
            state = self.client.state()
            if state.usable:
                try:
                    response = self.client.invoke(plan.action, plan.forwarded_args,
                                                  timeout_ms=plan.timeout_ms, expected=state)
                    if response['exit_code'] != 99:
                        value = response.get('result')
                        return dict(ExitCode=response['exit_code'], Json=value,
                                    Raw=json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')),
                                    Err=str(response['error']) if response.get('error') else '',
                                    ElapsedMs=int((self.client.clock.monotonic() - started) * 1000),
                                    FromHotCache=False, Route='pipe')
                except HelperClientError:
                    # Cleanup uses the *attempted* acquisition only. A replacement
                    # discovered after failure is never deleted by this request.
                    current = self.client.state()
                    if current.kind == 'stale' and current.snapshot == state.snapshot:
                        self.client._delete(current)
        cached = self.cache.get(plan.hot_key, self.client.clock.monotonic())
        if cached is not None:
            return cached
        result = child_envelope(self.child_read(plan))
        if result.get('Route') == 'child':
            self.cache.put(plan.hot_key, self.client.clock.monotonic(), result)
        return result
