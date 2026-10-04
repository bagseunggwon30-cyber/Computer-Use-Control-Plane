"""Single-attempt, owned process transport for the three legacy coordinators.

The trusted provider validates a closed effect before dispatch. A cancelled,
malformed, lost, or uncertain session is terminal. It cannot resume or replay.
No PowerShell bridge and no generic function/script execution are installed.
"""
from __future__ import annotations

import base64
import binascii
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
from contextlib import contextmanager

from . import native_host
from .legacy_host_protocol import (Authority, Effect, FAMILIES, LegacyHostError, CHUNK_BYTES,
    MAX_FRAME_CHARACTERS, completion, exact, frames, parse_json, require, wire)


def _coordinator_argv():
    command, error = native_host._native_argv()
    require(command is not None, error)
    # Match the retained host's fixed executable/DLL boundary. In particular,
    # a trusted path override is not a generic Python/shell-script runner.
    require((len(command) == 1 and Path(command[0]).suffix.lower() == '.exe') or
            (len(command) == 2 and Path(command[1]).suffix.lower() == '.dll'),
            'Legacy coordinator runtime must be an executable or DLL, never a script.')
    return command


class Cancellation:
    """Read-only view of local and ancestor cancellation; never clears either."""
    def __init__(self, *events):
        self.events = tuple(event for event in events if event is not None)

    def is_set(self):
        return any(event.is_set() for event in self.events)

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.is_set() and time.monotonic() < deadline:
            time.sleep(min(.01, max(0, deadline - time.monotonic())))
        return self.is_set()


@contextmanager
def cancel_with_owner(port, cancelled):
    """Propagate cancellation into socket adapters during a blocking call."""
    if cancelled is None:
        yield port
        return
    require(not cancelled.is_set(), 'Owner cancelled before adapter dispatch; action not retried.')
    done = threading.Event()
    def watch():
        while not done.wait(.01):
            if cancelled.is_set():
                port.close()
                return
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        done.set()
        thread.join(.1)


class LegacyEffectSession:
    def __init__(self, *, timeout_s=30.0, parent_cancelled=None):
        require(type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0,
                'Legacy session timeout must be positive and finite.')
        self.timeout_s = timeout_s
        self._lock = threading.RLock()
        self._cancelled = threading.Event()
        self._cancellation = Cancellation(self._cancelled, parent_cancelled)
        self._process = None
        self._used = False
        self._threads = []
        self.dispatched = 0
        self.state_effect_seen = False
        self.live_effect_seen = False

    def close(self):
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None:
            native_host._terminate_process_tree(process)

    def _check(self, deadline):
        require(not self._cancellation.is_set(), 'Legacy session cancelled; action not retried.')
        require(time.monotonic() < deadline, 'Legacy session timed out; action not retried.')

    def run(self, family, startup, authority, provider):
        """Provider is trusted host code, never supplied by the wire or CLI.

        ``validate`` must reject outside its complete bounded surface before the
        state marker and ``dispatch``. Protocol/policy failures are never turned
        into recoverable effect replies. Expected leaf failures are OSError only.
        """
        require(family in FAMILIES and type(authority) is Authority, 'Invalid trusted legacy family or authority.')
        with self._lock:
            require(not self._used and not self._cancelled.is_set(), 'Legacy session is single-attempt and cannot restart.')
            self._used = True
        deadline = min(time.monotonic() + self.timeout_s, getattr(provider, 'parent_deadline', math.inf))
        if hasattr(provider, 'bind_session'):
            provider.bind_session(deadline, self._cancellation)
        provider.validate_startup(family, startup, authority)
        encoded = frames(startup, 0, startup=True)
        command = [*_coordinator_argv(), FAMILIES[family][0]]
        if authority.live:
            command.append('--allow-live-control')
        if authority.sensitive:
            command.append('--confirm-sensitive')
        inbox = queue.Queue(maxsize=4)
        stderr = bytearray()
        stderr_failed = threading.Event()
        process = None

        def put(value):
            while not self._cancelled.is_set():
                try:
                    inbox.put(value, timeout=.05)
                    return
                except queue.Full:
                    continue

        def read_output():
            try:
                while not self._cancelled.is_set():
                    # Frame content is ASCII, but honor the existing character
                    # bound after strict UTF-8 decoding as well as a byte bound.
                    line = process.stdout.readline(MAX_FRAME_CHARACTERS * 4 + 3)
                    if not line:
                        put(None)
                        return
                    require(line.endswith(b'\n'), 'Incomplete or oversized legacy frame.')
                    decoded = line[:-1].removesuffix(b'\r').decode('utf-8', errors='strict')
                    require(len(decoded) <= MAX_FRAME_CHARACTERS, 'Legacy frame exceeds 66000 characters.')
                    put(decoded)
            except (OSError, ValueError, UnicodeError, LegacyHostError) as failure:
                put(failure)
            finally:
                process.stdout.close()

        def read_error():
            try:
                while True:
                    chunk = process.stderr.read(1024)
                    if not chunk:
                        return
                    remaining = native_host.MAX_STDERR_BYTES - len(stderr)
                    stderr.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        stderr_failed.set()
                        native_host._terminate_process_tree(process)
                        return
            except OSError:
                return
            finally:
                process.stderr.close()

        def send(value):
            failures = []
            done = threading.Event()
            def write():
                try:
                    for line in value:
                        process.stdin.write(line)
                    process.stdin.flush()
                except (OSError, ValueError) as failure:
                    failures.append(failure)
                finally:
                    done.set()
            thread = threading.Thread(target=write, daemon=True)
            self._threads.append(thread)
            thread.start()
            while not done.wait(.02):
                self._check(deadline)
            require(not failures, 'Legacy reply write failed; action not retried.')

        def receive(expected):
            data = bytearray()
            target = None
            while True:
                self._check(deadline)
                require(not stderr_failed.is_set(), 'Legacy stderr exceeds 64 KiB.')
                try:
                    line = inbox.get(timeout=min(.05, max(.001, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if isinstance(line, BaseException):
                    raise LegacyHostError(str(line)) from line
                require(line is not None, 'Legacy runtime closed before a final report; action not retried.')
                frame = parse_json(line)
                require(type(frame) is dict, 'Legacy frame must be an object.')
                kind = frame.get('kind')
                require(kind in ('part', 'end'), 'Unknown legacy frame kind.')
                exact(frame, ('kind', 'target', 'id', 'data') if kind == 'part' else ('kind', 'target', 'id'))
                require(type(frame['id']) is int and frame['id'] == expected and
                        type(frame['target']) is str and frame['target'] in ('effect', 'complete', 'error'),
                        'Legacy frame is not bound to the outstanding sequence.')
                require(target is None or target == frame['target'], 'Legacy frame target changed.')
                target = frame['target']
                if kind == 'end':
                    return target, parse_json(data.decode('utf-8', errors='strict'))
                require(type(frame['data']) is str, 'Legacy chunk must be base64 text.')
                try:
                    part = base64.b64decode(frame['data'], validate=True)
                except (binascii.Error, ValueError) as failure:
                    raise LegacyHostError('Invalid legacy chunk encoding.') from failure
                require(len(part) <= CHUNK_BYTES, 'Legacy chunk exceeds 48 KiB.')
                data.extend(part)

        try:
            with native_host.guarded_launch(command) as (guarded, kwargs):
                process = subprocess.Popen(guarded, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, **kwargs)
            with self._lock:
                self._process = process
                with native_host._PROCESS_LOCK:
                    native_host._PROCESSES.add(process)
            self._check(deadline)
            for work in (read_output, read_error):
                thread = threading.Thread(target=work, daemon=True)
                self._threads.append(thread)
                thread.start()
            send(encoded)
            sequence = 1
            while True:
                target, message = receive(sequence)
                if target == 'error':
                    exact(message, ('message', 'mutation_may_have_occurred', 'automatic_retry'))
                    require(type(message['message']) is str and type(message['mutation_may_have_occurred']) is bool and
                            type(message['automatic_retry']) is bool and not message['automatic_retry'], 'Invalid legacy error envelope.')
                    raise LegacyHostError(message['message'], uncertain=message['mutation_may_have_occurred'])
                if target == 'complete':
                    result = completion(message, family)
                    provider.validate_completion(result)
                    process.stdin.close()
                    while process.poll() is None:
                        self._check(deadline)
                        time.sleep(.01)
                    for thread in self._threads:
                        thread.join(timeout=.25)
                    require(not stderr_failed.is_set(), 'Legacy stderr exceeds 64 KiB.')
                    require(not any(thread.is_alive() for thread in self._threads), 'Legacy runtime left owned protocol streams open.')
                    # Drain must contain EOF only. A post-completion effect is
                    # never dispatched, and no successful output is released.
                    tail = []
                    while not inbox.empty():
                        tail.append(inbox.get_nowait())
                    require(tail == [None], 'Legacy runtime emitted data after its final report.')
                    require(process.returncode == result['exit'], 'Legacy runtime exit disagrees with final report.')
                    return result
                effect = Effect.decode(message, authority)
                provider.validate(effect)
                self._check(deadline)
                current_changes_state = effect.may_change_state()
                self.state_effect_seen |= current_changes_state
                self.live_effect_seen |= effect.live
                self.dispatched += 1
                try:
                    value = provider.dispatch(effect)
                    self._check(deadline)
                    reply = {'state': 'ok', 'value': wire(value)}
                except OSError as failure:
                    reply = {'state': 'error', 'message': str(failure),
                             'mutation_may_have_occurred': current_changes_state or self.live_effect_seen}
                send(frames(reply, sequence))
                sequence += 1
        except BaseException as failure:
            uncertain = self.state_effect_seen or self.live_effect_seen or getattr(failure, 'uncertain', False)
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                # Preserve cancellation as cancellation, but do not erase a
                # dispatch record merely because a signal interrupted the wait.
                failure.uncertain = uncertain
                raise
            if isinstance(failure, LegacyHostError) and (failure.uncertain or not uncertain):
                raise
            raise LegacyHostError(str(failure), uncertain=uncertain) from failure
        finally:
            self.close()
            if process is not None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                with native_host._PROCESS_LOCK:
                    native_host._PROCESSES.discard(process)
                for thread in self._threads:
                    thread.join(timeout=.3)
                # Buffered stream.close() can wait forever for the lock held
                # by a blocked reader/writer if an unrelated descendant kept a
                # pipe handle. Do not turn bounded cancellation into that wait.
                # The daemon threads own their stream objects until EOF; a
                # poisoned host cannot create another invocation. Never kill
                # unowned application children to obtain a clean pipe EOF.
                if not any(thread.is_alive() for thread in self._threads):
                    for stream in (process.stdin, process.stdout, process.stderr):
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass
