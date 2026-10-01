"""One lazily started native worker per Python session; never retry or respawn on failure."""
from __future__ import annotations
import json
import math
import os
import subprocess
import threading
import time
from . import native_host as transport

MAX_REQUEST_BYTES = 128 * 1024

class NativeSession:
    def __init__(self, *, allow_live_control=False):
        self.allow_live_control = bool(allow_live_control)
        self._serial = threading.Lock()
        self._condition = threading.Condition(threading.RLock())
        self._process = None
        self._threads = []
        self._id = 0
        self._pending = None
        self._response = None
        self._error = None
        self._stderr = bytearray()
        self._closed = False

    @property
    def pid(self):
        return self._process.pid if self._process is not None else None

    def _fail(self, message):
        with self._condition:
            if self._error is None:
                self._error = message
            process = self._process
            self._condition.notify_all()
        if process is not None:
            transport._terminate_process_tree(process)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _start(self):
        argv, error = transport._native_argv()
        if argv is None:
            self._fail(error)
            return
        try:
            command = [*argv, 'serve', *(['--allow-live-control'] if self.allow_live_control else [])]
            with transport.guarded_launch(command) as (guarded_command, kwargs):
                process = subprocess.Popen(guarded_command,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        except (OSError, ValueError) as exc:
            self._fail(f'native session launch failed: {exc}')
            return
        with self._condition:
            self._process = process
            with transport._PROCESS_LOCK:
                transport._PROCESSES.add(process)
            if self._closed:
                transport._terminate_process_tree(process)
                return
        self._threads = [threading.Thread(target=self._read_stdout, args=(process,), daemon=True),
                         threading.Thread(target=self._read_stderr, args=(process,), daemon=True)]
        for thread in self._threads:
            thread.start()

    def _read_stdout(self, process):
        try:
            while True:
                line = process.stdout.readline(transport.MAX_STDOUT_BYTES + 1)
                if not line:
                    self._fail('native session exited; restart the computer session')
                    return
                if len(line) > transport.MAX_STDOUT_BYTES or not line.endswith(b'\n'):
                    raise ValueError('native response exceeds size limit or is incomplete')
                envelope = json.loads(line.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                if not isinstance(envelope, dict) or set(envelope) != {'schema', 'id', 'command', 'exit_code', 'payload'}:
                    raise ValueError('invalid native session envelope')
                with self._condition:
                    expected = self._pending
                    if (envelope['schema'] != 'pcucp.native.response/v1' or expected is None or
                        type(envelope['id']) is not int or (envelope['id'], envelope['command']) != expected or
                        type(envelope['exit_code']) is not int or not 0 <= envelope['exit_code'] <= 255):
                        raise ValueError('unsolicited or mismatched native response')
                    validation = transport._validate_payload(expected[1], envelope['payload'])
                    if validation:
                        raise ValueError(f'native protocol error: {validation}')
                    self._response = envelope
                    self._pending = None
                    self._condition.notify_all()
        except (OSError, ValueError, UnicodeError, RecursionError, TypeError) as exc:
            self._fail(f'native session protocol failure: {exc}')
        finally:
            process.stdout.close()

    def _read_stderr(self, process):
        try:
            while True:
                chunk = process.stderr.read(1024)
                if not chunk:
                    return
                with self._condition:
                    remaining = transport.MAX_STDERR_BYTES - len(self._stderr)
                    self._stderr.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self._fail('native session stderr exceeds size limit')
                    return
        except OSError:
            pass
        finally:
            process.stderr.close()

    def __call__(self, command, args=None, *, timeout_s=15.0):
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            return 2, None, 'native timeout must be a positive finite number'
        if not isinstance(command, str) or not command or '\0' in command or command == 'serve':
            return 2, None, 'invalid native session command'
        if args is not None and (not isinstance(args, list) or any(not isinstance(a, str) or '\0' in a for a in args)):
            return 2, None, 'native arguments must be strings without NUL'
        deadline = time.monotonic() + timeout_s
        if not self._serial.acquire(timeout=timeout_s):
            return 124, None, 'native session queue timed out; request not sent'
        try:
            with self._condition:
                if self._closed or self._error:
                    return 1, None, self._error or 'native session closed'
            if self._process is None:
                self._start()
            with self._condition:
                if self._error or self._closed:
                    return 2, None, self._error or 'native session closed'
                self._id += 1
                frame = (json.dumps({'schema':'pcucp.native.request/v1', 'id':self._id, 'command':command, 'args':args or []},
                                    ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
                if len(frame) > MAX_REQUEST_BYTES:
                    return 2, None, 'native request exceeds 128 KiB'
                self._pending, self._response = (self._id, command), None
                process = self._process
            # A stalled native process must not block the owner while writing to its pipe.
            def write():
                try:
                    process.stdin.write(frame)
                    process.stdin.flush()
                except (OSError, ValueError) as exc:
                    self._fail(f'native session write failed: {exc}')
            writer = threading.Thread(target=write, daemon=True)
            self._threads.append(writer)
            writer.start()
            with self._condition:
                while self._response is None and self._error is None and not self._closed:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
                response, error = self._response, self._error
                closed = self._closed
            if response is None or error or closed:
                self._fail(error or ('native session closed' if closed else 'native session timed out; action not retried'))
                return (1 if error or closed else 124), None, self._error
            code, payload = response['exit_code'], response['payload']
            payload.setdefault('route', {}).update(primary='dotnet-native-host', fallback=None, invoked_by='python-router', transport='persistent-stdio')
            if code != 0 and payload['status'] == 'ok':
                self._fail('native exit status disagrees with success payload')
                return 1, None, self._error
            if code == 0 and payload['status'] != 'ok':
                code = 3 if payload['status'] == 'partial' else 1
            return code, payload, ''
        except BaseException:
            self._fail('native session interrupted; action not retried')
            raise
        finally:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._serial.release()

    def close(self):
        with self._condition:
            self._closed = True
            process = self._process
            self._condition.notify_all()
        if process is None:
            return
        transport._terminate_process_tree(process)
        for thread in list(self._threads):
            if thread is not threading.current_thread():
                thread.join(timeout=0.25)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        # Only close stdin after a blocked writer has been released by process termination.
        if not any(thread.is_alive() for thread in self._threads):
            process.stdin.close()
        with transport._PROCESS_LOCK:
            transport._PROCESSES.discard(process)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
