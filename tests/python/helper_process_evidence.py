"""Bounded raw evidence for newly owned fixture subprocesses, before assertions.

Readers retain prefixes while draining excess bytes. An inherited child pipe does
not delay evidence publication: EOF is bounded separately from process exit.
This helper never searches for, signals, or terminates a process by a lock PID.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
import subprocess
import threading
import time
import uuid


def validate_evidence_label(label):
    # Portable artifact basename, also accepted by Windows and CI upload tools.
    # No suffixes/dots: Path.with_suffix must preserve the UUID in every record.
    if not isinstance(label,str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,119}',label) is None:
        raise ValueError('Evidence label must be 1-120 ASCII letters/digits/hyphens/underscores, starting alphanumeric')
    return label


class OwnedProcess:
    def __init__(self, argv, *, cwd=None, env=None, limit=262144, input_bytes=None, creationflags=0, hide_window=False):
        allowed_flags = 0x00000008 | 0x00000010 | 0x00000200 | 0x08000000  # detached, owned console, group, no window
        if type(creationflags) is not int or creationflags < 0 or creationflags & ~allowed_flags:
            raise ValueError('Fixture creation flags are outside the owned startup modes')
        if type(hide_window) is not bool: raise ValueError('hide_window must be boolean')
        self.hide_window = hide_window
        self.creationflags = creationflags
        self.argv = [str(x) for x in argv]
        self.started = time.monotonic()
        self.limit = limit
        self.process = None
        self.launch_error = None
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.totals = {"stdout": 0, "stderr": 0}
        self.read_errors = {}
        self.guard = threading.Lock()
        self.readers = []
        self.stdin_error = None
        try:
            startup = None
            if hide_window:
                if os.name != 'nt': raise ValueError('Hidden fixture console requires Windows')
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
            self.process = subprocess.Popen(self.argv, cwd=cwd, env=env, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, shell=False, creationflags=self.creationflags, startupinfo=startup)
        except (OSError, ValueError) as exc:
            self.launch_error = f"{type(exc).__name__}: {exc}"
            return
        for name in self.buffers:
            thread = threading.Thread(target=self._read, args=(name, getattr(self.process, name)), daemon=True)
            thread.start()
            self.readers.append(thread)
        if input_bytes is not None:
            def write():
                try:
                    view = memoryview(input_bytes)
                    while view:
                        count = self.process.stdin.write(view)
                        if not count:
                            raise OSError('fixture stdin write made no progress')
                        view = view[count:]
                except (OSError, ValueError) as exc:
                    self.stdin_error = f"{type(exc).__name__}: {exc}"
                finally:
                    self.process.stdin.close()
            threading.Thread(target=write, daemon=True).start()

    def _read(self, name, stream):
        try:
            while True:
                data = os.read(stream.fileno(), 8192)
                if not data:
                    break
                with self.guard:
                    self.totals[name] += len(data)
                    remaining = self.limit - len(self.buffers[name])
                    if remaining > 0:
                        self.buffers[name].extend(data[:remaining])
        except (OSError, ValueError) as exc:
            with self.guard:
                self.read_errors[name] = f"{type(exc).__name__}: {exc}"
        finally:
            stream.close()

    def finish(self, directory, label, *, timeout=30, drain_timeout=.4):
        """Save evidence even for launch/timeout failures; return data, not verdict."""
        timed_out = False
        kill_error = None
        if self.process is not None:
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    self.process.kill()  # Retained newly launched Popen only.
                    self.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    kill_error = f"{type(exc).__name__}: {exc}"
        end = time.monotonic() + drain_timeout
        for reader in self.readers:
            reader.join(max(0, end - time.monotonic()))
        return self.snapshot(directory, label, timed_out=timed_out, kill_error=kill_error)

    def snapshot(self, directory, label, *, timed_out=False, kill_error=None):
        """Persist currently available prefixes without waiting or killing."""
        validate_evidence_label(label)
        with self.guard:
            raw = {name: bytes(value) for name, value in self.buffers.items()}
            result = dict(argv=self.argv, creationflags=self.creationflags, hide_window=self.hide_window, exit_code=self.process.poll() if self.process else None,
                          timed_out=timed_out, running=self.process is not None and self.process.poll() is None, launch_error=self.launch_error, kill_error=kill_error,
                          drain_incomplete=any(x.is_alive() for x in self.readers),
                          elapsed_ms=round((time.monotonic() - self.started) * 1000),
                          stdin_error=self.stdin_error, read_errors=dict(self.read_errors),
                          bytes_observed=dict(self.totals),
                          truncated={name: self.totals[name] > len(raw[name]) for name in raw},
                          stdout_base64=base64.b64encode(raw['stdout']).decode('ascii'),
                          stderr_base64=base64.b64encode(raw['stderr']).decode('ascii'))
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        stem = destination / f"{label}-{uuid.uuid4().hex[:12]}"
        for name, value in raw.items():
            stem.with_suffix(f".{name}.bin").write_bytes(value)
        stem.with_suffix('.json').write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding='utf-8')
        result.update(raw, evidence_path=str(stem.with_suffix('.json')))
        return result


def run_evidence(argv, *, directory, label, cwd=None, env=None, input_bytes=None, timeout=30, limit=262144, creationflags=0, hide_window=False):
    validate_evidence_label(label)  # Reject before Popen, not after a completed run.
    return OwnedProcess(argv, cwd=cwd, env=env, input_bytes=input_bytes, limit=limit, creationflags=creationflags, hide_window=hide_window).finish(directory, label, timeout=timeout)


def require_success(result, expected_exit=0):
    """Infrastructure failures cannot satisfy a negative-result expectation."""
    if (result.get('running') or result['launch_error'] or result['timed_out'] or result['kill_error'] or result['drain_incomplete']
            or result['stdin_error'] or result['read_errors'] or any(result['truncated'].values())
            or result['exit_code'] != expected_exit):
        raise AssertionError(f"Fixture process failed: {result['evidence_path']}: "
                             + json.dumps({k: v for k, v in result.items() if k not in {'stdout', 'stderr', 'stdout_base64', 'stderr_base64'}}))
    return result
