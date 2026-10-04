"""Typed classic helper arguments and one-attempt owned desktop transport."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from . import native_host
from .legacy_host_protocol import Authority, LegacyHostError, exact, parse_json, require
from .legacy_values import int32

INTEGER_OPTIONS = frozenset(('X', 'Y', 'ScreenshotX', 'ScreenshotY', 'ScreenshotW', 'ScreenshotH', 'MaxElements',
    'MinSize', 'WindowHwnd', 'TargetHwnd', 'ClickInset', 'ScanRadius', 'ScanStep', 'OcrMaxCandidates', 'DiffThreshold'))
SWITCH_OPTIONS = frozenset(('ClearFirst', 'PressEnter', 'SkipUia', 'JsonOnly', 'Quiet'))
TEXT_OPTIONS = frozenset(('Action', 'Match', 'Button', 'Text', 'Value', 'Keys', 'OutPath', 'Label', 'Role',
    'WindowTitle', 'TargetMatch', 'ClickRefine', 'OcrLanguage', 'OcrPath', 'OcrText', 'OcrMatch',
    'DiffBefore', 'DiffAfter', 'DiffIgnoreRegions'))
ACTIONS = frozenset(('windows', 'focused', 'focus', 'screenshot', 'click', 'type', 'shortcut', 'uia-tree', 'uia-find',
    'uia-click', 'uia-invoke', 'uia-set-value', 'uia-toggle', 'ocr-screen', 'ocr-image', 'ocr-find-text',
    'ocr-uia-fuse', 'ocr-uia-invoke', 'screenshot-diff', 'hit-test', 'hit-scan', 'ime-paste', 'modal-detect', 'health'))
LIVE_ACTIONS = frozenset(('focus', 'click', 'type', 'shortcut', 'uia-click', 'uia-invoke', 'uia-set-value',
                        'uia-toggle', 'ocr-uia-invoke', 'ime-paste'))
MAX_FRAME = 32 * 1024 * 1024


def prepare_desktop(argv):
    require(type(argv) is list and all(type(value) is str and '\0' not in value for value in argv), 'Native argv must be inert strings.')
    names = {name.casefold(): name for name in INTEGER_OPTIONS | SWITCH_OPTIONS | TEXT_OPTIONS}
    options, index = {}, 0
    while index < len(argv):
        word = argv[index]
        require(word.startswith('-'), 'Native helper option must begin with a dash.')
        spelling = word.lstrip('-').casefold()
        candidates = [name for key, name in names.items() if key.startswith(spelling)]
        name = names.get(spelling)
        if name is None:
            require(len(candidates) == 1, 'Unknown or ambiguous native helper option: ' + word)
            name = candidates[0]
        require(name not in options, 'Duplicate native helper option: ' + word)
        if name in SWITCH_OPTIONS:
            options[name] = True
            index += 1
        else:
            require(index + 1 < len(argv), 'Missing native helper value: ' + word)
            options[name] = int32(argv[index + 1]) if name in INTEGER_OPTIONS else argv[index + 1]
            index += 2
    require(options.get('Action', '').casefold() in ACTIONS, 'Unknown native helper action.')
    return options


class DesktopSession:
    def __init__(self, executable=None, *, authority=Authority(), culture='en-US', timeout_s=30, cancelled=None):
        require(type(authority) is Authority and type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0,
                'Invalid desktop startup authority or timeout.')
        from .protocol import repo_root, frozen
        default = (repo_root() / 'legacy-desktop' if frozen() else repo_root() / 'pcucp-next/bin/legacy-desktop') / 'PcuCp.LegacyDesktop.exe'
        self.executable = Path(executable or os.environ.get('CUCP_LEGACY_DESKTOP_EXE') or default)
        require(self.executable.is_absolute() and self.executable.name == 'PcuCp.LegacyDesktop.exe' and self.executable.is_file(),
                'Published legacy desktop executable is unavailable; no script fallback or action-time build exists.')
        self.authority, self.culture, self.timeout_s = authority, culture, timeout_s
        self._cancelled, self._parent_cancelled = threading.Event(), cancelled
        self._lock, self._process, self._used = threading.RLock(), None, False

    def close(self):
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None:
            native_host._terminate_process_tree(process)

    def _check(self, deadline):
        require(not self._cancelled.is_set() and (self._parent_cancelled is None or not self._parent_cancelled.is_set()),
                'Desktop owner cancelled; action not retried.')
        require(time.monotonic() < deadline, 'Desktop owner timed out; action not retried.')

    def run(self, argv):
        options = prepare_desktop(argv)
        live = options['Action'].casefold() in LIVE_ACTIONS
        require(not live or self.authority.live, 'Live native helper action exceeds immutable startup authority.')
        with self._lock:
            require(not self._used and not self._cancelled.is_set(), 'Desktop session is single-attempt; action not retried.')
            self._used = True
        frame = self._encode(dict(schema='cucp.legacy-desktop-request/v1', options=options))
        command = [str(self.executable), *(['--allow-live-control'] if self.authority.live else [])]
        deadline = time.monotonic() + self.timeout_s
        inbox, stderr, threads = queue.Queue(maxsize=4), bytearray(), []
        process = None
        def put(value):
            while not self._cancelled.is_set():
                try:
                    inbox.put(value, timeout=.05)
                    return
                except queue.Full:
                    continue
        def output():
            try:
                while not self._cancelled.is_set():
                    line = process.stdout.readline(MAX_FRAME + 1)
                    if not line:
                        put(None)
                        return
                    require(len(line) <= MAX_FRAME and line.endswith(b'\n'), 'Oversized or incomplete desktop frame.')
                    put(parse_json(line))
            except (OSError, ValueError, LegacyHostError) as error:
                put(error)
            finally:
                process.stdout.close()
        def error_output():
            try:
                while True:
                    block = process.stderr.read(1024)
                    if not block:
                        return
                    remaining = native_host.MAX_STDERR_BYTES - len(stderr)
                    stderr.extend(block[:max(0, remaining)])
                    if len(block) > remaining:
                        put(LegacyHostError('Desktop stderr exceeds 64 KiB.'))
                        self.close()
                        return
            except OSError:
                return
            finally:
                process.stderr.close()
        def send(encoded):
            done, errors = threading.Event(), []
            def write():
                try:
                    process.stdin.write(encoded)
                    process.stdin.flush()
                except (OSError, ValueError) as error:
                    errors.append(error)
                finally:
                    done.set()
            thread = threading.Thread(target=write, daemon=True)
            threads.append(thread)
            thread.start()
            while not done.wait(.01):
                self._check(deadline)
            require(not errors, 'Desktop reply write failed; action not retried.')
        try:
            self._check(deadline)
            with native_host.guarded_launch(command) as (guarded, kwargs):
                process = subprocess.Popen(guarded, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
            with self._lock:
                self._process = process
            with native_host._PROCESS_LOCK:
                native_host._PROCESSES.add(process)
            for work in (output, error_output):
                thread = threading.Thread(target=work, daemon=True); threads.append(thread); thread.start()
            send(frame)
            effects = 0
            while True:
                self._check(deadline)
                try:
                    message = inbox.get(timeout=.05)
                except queue.Empty:
                    continue
                if isinstance(message, BaseException):
                    raise message
                require(message is not None and type(message) is dict, 'Desktop worker closed without a final report: ' + stderr.decode('utf-8', errors='replace'))
                if message.get('schema') == 'cucp.legacy-desktop-effect/v1':
                    exact(message, ('schema', 'operation', 'body', 'needle', 'mode'))
                    require(options['Action'].casefold() in {'ocr-find-text', 'ocr-uia-fuse', 'ocr-uia-invoke'} and
                        effects == 0 and message['operation'] == 'ocr-match' and type(message['body']) is dict and
                        message['needle'] == options.get('OcrText', '') and message['mode'] == options.get('OcrMatch', 'contains'),
                        'Desktop effect is outside its original acquisition scope.')
                    effects += 1
                    from .legacy_native_kernel import ocr_match
                    candidates = ocr_match(message['body'], message['needle'], message['mode'], culture=self.culture,
                        timeout_s=min(15, deadline - time.monotonic()), cancelled=self._parent_cancelled or self._cancelled)
                    send(self._encode(dict(schema='cucp.legacy-desktop-reply/v1', candidates=candidates)))
                    continue
                require(message.get('action') == options['Action'].casefold() and message.get('status') in {'ok', 'error', 'partial', 'blocked'},
                        'Invalid desktop final report.')
                expected = {'ok': 0, 'error': 1, 'partial': 2, 'blocked': 3}[message['status']]
                process.stdin.close()
                while process.poll() is None:
                    self._check(deadline)
                    time.sleep(.01)
                for thread in threads:
                    thread.join(.25)
                require(not any(thread.is_alive() for thread in threads) and list(inbox.queue) == [None], 'Desktop worker emitted output after its final report.')
                require(process.returncode == expected, 'Desktop worker exit disagrees with its report.')
                return dict(ExitCode=expected, Json=message, Raw=json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n',
                            Err=stderr.decode('utf-8', errors='replace'), ElapsedMs=message['elapsed_ms'])
        except BaseException as error:
            uncertain = live and process is not None or getattr(error, 'uncertain', False)
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                error.uncertain = uncertain
                raise
            raise LegacyHostError(str(error), uncertain=uncertain) from error
        finally:
            self.close()
            if process is not None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                for thread in threads:
                    thread.join(.1)
                with native_host._PROCESS_LOCK:
                    native_host._PROCESSES.discard(process)
                if not any(thread.is_alive() for thread in threads):
                    for stream in (process.stdin, process.stdout, process.stderr):
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass

    @staticmethod
    def _encode(value):
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
        require(len(data) <= MAX_FRAME, 'Desktop typed frame exceeds 32 MiB.')
        return data
