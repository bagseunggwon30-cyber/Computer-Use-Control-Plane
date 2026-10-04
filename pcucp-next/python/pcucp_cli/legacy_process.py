"""Bounded argv-only capture for dependencies which do not speak NativeHost ABI."""
import math
import os
import subprocess
import threading
import time
from . import native_host
from .legacy_host_protocol import require


def capture(argv, timeout_s, *, cancelled=None):
    require(type(argv) is list and argv and all(type(item) is str and '\0' not in item for item in argv),
            'Dependency argv must be inert strings.')
    require(type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0,
            'Dependency timeout must be finite and positive.')
    if cancelled is not None and cancelled.is_set():
        raise OSError('Dependency owner cancelled before dispatch; action not retried.')
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    with native_host._PROCESS_LOCK:
        native_host._PROCESSES.add(process)
    output, errors, overflow = bytearray(), bytearray(), threading.Event()
    def drain(stream, target, maximum):
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                remaining = maximum - len(target)
                target.extend(chunk[:max(0, remaining)])
                if len(chunk) > remaining:
                    overflow.set()
                    process.kill()
                    return
        except (OSError, ValueError):
            overflow.set()
        finally:
            stream.close()
    readers = [threading.Thread(target=drain, args=(stream, target, maximum), daemon=True)
        for stream, target, maximum in ((process.stdout, output, native_host.MAX_STDOUT_BYTES),
                                        (process.stderr, errors, native_host.MAX_STDERR_BYTES))]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout_s
    try:
        while process.poll() is None:
            if cancelled is not None and cancelled.is_set():
                raise OSError('Dependency owner cancelled; action not retried.')
            if time.monotonic() >= deadline:
                raise TimeoutError('Dependency owner timed out; action not retried.')
            time.sleep(.01)
        for reader in readers:
            reader.join(min(.25, max(0, deadline - time.monotonic())))
        if overflow.is_set() or any(reader.is_alive() for reader in readers):
            raise OSError('Dependency output exceeded its budget or streams remain open; action not retried.')
        return process.returncode, bytes(output), bytes(errors)
    finally:
        # Own the control process handle only. Never terminate user application
        # descendants to force EOF or obtain a successful final report.
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        for reader in readers:
            reader.join(.1)
        with native_host._PROCESS_LOCK:
            native_host._PROCESSES.discard(process)
