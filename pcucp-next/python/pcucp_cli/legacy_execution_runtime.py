"""Owned execution-family runtime with native desktop and CDP acquisition.

The root supplies typed child and local macro ports. There is no child shell,
generic interpreter, availability substitution, automatic replay, or PS leaf.
"""
import json
import math
import socket
import threading
import time
from .legacy_cdp import LegacyCdpAdapter
from .legacy_cdp_contract import prepare_native
from .legacy_execution_provider import ExecutionProvider
from .legacy_history import SmartClickHistory
from .legacy_host_protocol import Authority, LegacyHostError, require
from .legacy_host_session import Cancellation, LegacyEffectSession, cancel_with_owner
from .legacy_native_desktop import DesktopSession
from .legacy_storage import append_trajectory


class ExecutionRuntime:
    def __init__(self, *, audit_directory, cache_directory, authority=Authority(), timeout_s=30,
                 parent_deadline=math.inf, culture='en-US', cache_seconds=2, vision_available=False,
                 child=None, local_macro=None, desktop_executable=None, parent_cancelled=None):
        self.audit_directory, self.cache_directory = audit_directory, cache_directory
        self.authority, self.timeout_s, self.parent_deadline = authority, timeout_s, parent_deadline
        self.culture, self.cache_seconds, self.vision_available = culture, cache_seconds, vision_available
        self.child, self.local_macro, self.desktop_executable = child, local_macro, desktop_executable
        self.history = SmartClickHistory(audit_directory)
        self._cancelled, self._parent_cancelled = threading.Event(), parent_cancelled
        self._active, self._lock, self._used = set(), threading.RLock(), False

    def close(self):
        self._cancelled.set()
        with self._lock:
            active = tuple(self._active)
        for port in active:
            port.close()

    def _remaining(self, provider):
        require(not self._cancelled.is_set() and (self._parent_cancelled is None or not self._parent_cancelled.is_set()),
            'Execution root cancelled; action not retried.')
        return min(self.timeout_s, provider.remaining())

    def _owned(self, port, operation):
        with self._lock:
            require(not self._cancelled.is_set(), 'Execution runtime closed; action not retried.')
            self._active.add(port)
        try:
            return operation()
        finally:
            port.close()
            with self._lock:
                self._active.discard(port)

    def native(self, argv, authority, provider):
        started = time.monotonic()
        if len(argv) >= 2 and argv[0] == '-Action' and argv[1].startswith('cdp-'):
            plan = prepare_native(argv)
            remaining = min(30, self._remaining(provider))
            require(remaining >= .05, 'Insufficient inherited CDP acquisition budget; action not retried.')
            adapter = LegacyCdpAdapter(f'http://127.0.0.1:{plan.port}', allow_live_control=authority.live,
                timeout_s=remaining)
            with cancel_with_owner(adapter, provider.cancelled):
                result = self._owned(adapter, lambda: adapter.execute(plan.action, plan.args))
            self._remaining(provider)
            return dict(ExitCode=result.exit_code, Json=result.payload, Raw=json.dumps(result.payload, ensure_ascii=False) + '\n',
                Err='', ElapsedMs=round((time.monotonic() - started) * 1000))
        port = DesktopSession(self.desktop_executable, authority=authority, culture=self.culture,
            timeout_s=self._remaining(provider), cancelled=provider.cancelled)
        return self._owned(port, lambda: port.run(argv))

    def _port(self, effect, provider):
        kind = effect.kind
        child_authority = self.authority.restrict(effect.live, effect.confirm_sensitive)
        if kind == 'Native':
            return self.native(list(effect.argv), child_authority, provider)
        if kind == 'Child':
            require(self.child is not None, 'Root typed child port is unavailable.')
            return self.child(effect, provider)
        if kind == 'LocalMacro':
            require(self.local_macro is not None, 'Root local macro port is unavailable.')
            return self.local_macro(effect, provider)
        if kind == 'SendEscape':
            # Both authority gates have already passed independent validation.
            reply = self.native(['-Action', 'shortcut', '-Keys', 'escape'], child_authority, provider)
            if reply['ExitCode'] != 0:
                raise OSError(reply['Err'] or reply['Raw'])
            return None
        if kind == 'CdpPort':
            port, milliseconds = map(int, effect.argv)
            if not 1 <= port <= 65535:
                return False
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=min(milliseconds / 1000, self._remaining(provider))):
                    return True
            except OSError:
                return False
        if kind == 'HistoryRead':
            return self.history.pick(effect.argv[0], effect.argv[1], int(effect.argv[2]))
        if kind == 'HistoryAppend':
            self.history.append(*effect.argv, **effect.data)
            return None
        if kind == 'TrajectoryAppend':
            append_trajectory(self.audit_directory, effect.name, effect.data)
            return None
        require(False, 'Unknown closed execution port.')

    def run(self, operation, rest, *, brief=False):
        with self._lock:
            require(not self._used and not self._cancelled.is_set(), 'Execution invocation is single-attempt and cannot resume.')
            self._used = True
        provider = ExecutionProvider(operation=operation, rest=rest, authority=self.authority,
            cache_directory=self.cache_directory, culture=self.culture, brief=brief, cache_seconds=self.cache_seconds,
            vision_available=self.vision_available, parent_deadline=self.parent_deadline,
            ports={name: self._port for name in ('Child', 'Native', 'LocalMacro', 'CdpPort', 'HistoryRead', 'HistoryAppend', 'TrajectoryAppend', 'SendEscape')})
        session = LegacyEffectSession(timeout_s=self.timeout_s, parent_cancelled=Cancellation(self._cancelled, self._parent_cancelled))
        try:
            result = self._owned(session, lambda: session.run('execution', provider.startup(), self.authority, provider))
            return {**result, 'console': list(provider.console)}
        finally:
            self.close()
