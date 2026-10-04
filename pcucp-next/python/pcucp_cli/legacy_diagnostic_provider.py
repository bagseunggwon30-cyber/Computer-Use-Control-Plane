"""Python acquisition for the existing managed diagnostic coordinators.

The coordinator owns calculations and formatting. This provider owns fixed
startup paths, opened-file identities, and a closed read-only callback surface.
No PowerShell or command-string evaluation is available at this boundary.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import fnmatch
import hashlib
import os
from pathlib import Path
import shutil
import stat
import time
import uuid
import math

from .legacy_host_protocol import Authority, LegacyHostError, exact, require
from .legacy_values import int32, positive_option

OPERATIONS = frozenset(('perf', 'diagnose-lag', 'health-quick', 'health-detail',
                        'log-tail', 'benchmark', 'self-test', 'audit-summary', 'release-notes'))
KINDS = frozenset('Clock Timestamp FileExists ListFiles FileStat ReadLines ReadText TailBytes ResolvePath '
                  'NodeVersion Cli Native Macro AuditProbe EnsureWin32 EnsureUia HelperUp FindCodex '
                  'Processes ProcessMetrics ProcessorCount Windows Sleep ClearAppshotCache '
                  'AssertAuthorized Appshot CacheKey Uia Notice'.split())
CALLBACKS = frozenset('Cli Native Macro EnsureWin32 EnsureUia HelperUp Processes ProcessMetrics '
                      'Windows Appshot Uia AssertAuthorized'.split())
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_FILES = 20000


def timestamp(value=None):
    value = value or datetime.now().astimezone()
    return value.isoformat(timespec='microseconds').replace(value.strftime('%f'), value.strftime('%f') + '0')


def option(rest, name, default=None):
    for index, value in enumerate(rest[:-1]):
        if value.casefold() == name.casefold():
            return rest[index + 1]
    return default


def owned_path(value):
    """Check original path components before canonicalizing Windows aliases."""
    require(type(value) is str and '\0' not in value and Path(value).is_absolute(), 'Diagnostic paths must be absolute.')
    path = Path(os.path.abspath(value))
    for current in (path, *path.parents):
        if current.exists() or current.is_symlink():
            info = current.lstat()
            require(not current.is_symlink() and not (getattr(info, 'st_file_attributes', 0) & 0x400),
                    'Diagnostic path traverses a reparse point.')
    return path.resolve()


def identity(path):
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), 'Diagnostic input must be a regular file.')
    return info.st_dev, info.st_ino


def read_regular(path, *, expected=None, maximum=MAX_FILE_BYTES, tail=False, head=False):
    path = owned_path(str(path))
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), 'Opened diagnostic object is not a regular file.')
        require(expected is None or expected == (info.st_dev, info.st_ino), 'Diagnostic file identity changed.')
        if tail:
            stream.seek(max(0, info.st_size - maximum))
        raw = stream.read(maximum if head else maximum + 1)
        require(len(raw) <= maximum, 'Diagnostic file exceeds its bounded read budget.')
        return raw, info.st_size


class DiagnosticProvider:
    def __init__(self, *, operation, rest, context, culture='en-US', brief=False,
                 cache_seconds=2, callbacks=None, clock=time.monotonic, sleep=time.sleep,
                 parent_deadline=math.inf, on_session=None):
        require(operation in OPERATIONS, 'Unknown diagnostic operation.')
        exact(context, ('audit_directory', 'cache_directory', 'wrapper_log', 'cli_path', 'changelog_path',
                        'temp_root', 'benchmark_schema', 'release_schema'))
        require(type(rest) is list and all(type(value) is str for value in rest), 'Diagnostic argv must be strings.')
        self.operation, self.rest, self.context = operation, tuple(rest), dict(context)
        self.culture, self.brief, self.cache_seconds = culture, brief, cache_seconds
        self.callbacks, self.clock, self.sleep = dict(callbacks or {}), clock, sleep
        self.parent_deadline, self.on_session = parent_deadline, on_session
        self.deadline, self.cancelled = math.inf, None
        require(not (set(self.callbacks) - CALLBACKS), 'Unknown diagnostic callback.')
        self.paths = {key: owned_path(context[key]) for key in
                      ('audit_directory', 'cache_directory', 'wrapper_log', 'changelog_path', 'temp_root')}
        if context['cli_path'] is not None:
            self.paths['cli_path'] = owned_path(context['cli_path'])
        self.explicit = {}
        for name in ('--path', '--baseline'):
            value = option(rest, name)
            if value:
                self.explicit[name] = owned_path(str(Path(value).absolute()))
        self.readable = {}
        self.clocks, self.counts = {}, Counter()
        self.process_rows = []
        self.metric_order, self.metric_cursor = [], 0
        self.cache_key = None
        self.resolved_changelog = None

    def startup(self):
        return dict(schema='cucp.diagnostic-start/v1', operation=self.operation, rest=list(self.rest),
                    brief=self.brief, cache_seconds=self.cache_seconds, vision_available=bool(self.context['cli_path']),
                    culture=self.culture, context=dict(self.context))

    def bind_session(self, deadline, cancelled):
        self.deadline, self.cancelled = deadline, cancelled
        if self.on_session:
            self.on_session(deadline, cancelled)

    def _check(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'Diagnostic owner cancelled; action not retried.')
        require(time.monotonic() < self.deadline, 'Diagnostic owner timed out; action not retried.')

    def validate_startup(self, family, startup, authority):
        require(family == 'diagnostics' and startup == self.startup() and authority == Authority(),
                'Diagnostic startup or authority changed.')

    def _limit(self, key, count):
        require(self.counts[key] < count, 'Diagnostic effect exceeded its invocation count: ' + key)
        self.counts[key] += 1

    def _selected_path(self, value):
        require(type(value) is str, 'Diagnostic path must be a string.')
        path = owned_path(value)
        candidates = set(self.paths.values()) | set(self.explicit.values()) | set(self.readable)
        require(path in candidates, 'Diagnostic path is not owned by this invocation.')
        return path

    def _allow_argv(self, kind, name, argv):
        require(all(type(value) is str for value in argv), 'Diagnostic argv must be strings.')
        op, rest = self.operation, tuple(value.casefold() for value in self.rest)
        if kind == 'Cli':
            allowed = {('version',), ('tools',), ('observe', 'windows')} if op == 'self-test' else {('version',)}
            if op == 'perf':
                allowed = {('version',), ('release',)}
                if '--quick' not in rest:
                    allowed |= {('health',), ('observe', 'context'), ('observe', 'screenshot'),
                                ('observe', 'appshot', '--match', 'unlikely-perf-target-window')}
                if '--include-live-ish' in rest:
                    allowed.add(('observe', 'appshot'))
            require(tuple(argv) in allowed and op in {'self-test', 'perf', 'health-detail'}, 'CLI exceeds read-only diagnostic scope.')
            limit = positive_option(self.rest, '--iters', 3) if op == 'perf' else 1
            if tuple(argv) == ('observe', 'appshot'):
                limit = min(2147483647, limit * 2)
            self._limit('cli:' + repr(argv), limit)
        elif kind == 'Native':
            require(tuple(argv) in {('-Action', 'health'), ('-Action', 'windows'), ('-Action', 'focused'),
                                    ('-Action', 'modal-detect')} and op == 'benchmark', 'Native diagnostic call exceeds its scope.')
            try:
                limit = int32(option(self.rest, '--iters', '3'))
            except LegacyHostError:
                limit = 3
            self._limit('native:' + argv[1], min(10, max(1, limit)))
        elif kind == 'Macro':
            base = ('--label', '__cucp_unlikely_label__', '--match', 'unlikely-perf-target-window')
            allowed = name in {'metrics', 'health-quick'} and not argv
            if name == 'windows':
                allowed = tuple(argv) in {(), ('--match', 'unlikely-perf-target-window')} or '--quick' not in rest and tuple(argv) == ('--rich',)
            if name == 'find-label':
                allowed = tuple(argv) == base + ('--fast',) or '--quick' not in rest and tuple(argv) == base
            require(op == 'perf' and allowed, 'Diagnostic macro is outside its original argument scope.')
            self._limit('macro:' + name + repr(argv), positive_option(self.rest, '--iters', 3))
        elif kind == 'AssertAuthorized':
            require(op == 'self-test' and tuple(argv) in {
                ('act', 'click', '--x', '0', '--y', '0', '--after', 'fake'),
                ('act', 'click', '--x', '100', '--y', '100')}, 'Self-test assertion changed.')
            self._limit('gate:' + repr(argv), 1)

    def validate(self, effect):
        require(effect.kind == 'Diagnostic' and effect.name in KINDS and
                not any((effect.live, effect.quiet, effect.brief, effect.confirm_sensitive)), 'Unexpected diagnostic capability.')
        exact(effect.data, ('name', 'value'))
        kind, name, value = effect.name, effect.data['name'], effect.data['value']
        require(type(name) is str, 'Diagnostic suboperation must be text.')
        if kind not in {'Clock', 'Timestamp', 'Macro', 'AuditProbe', 'ClearAppshotCache', 'Notice'}:
            require(name == '', 'Unexpected diagnostic suboperation.')
        if kind in {'Cli', 'Native', 'Macro', 'AssertAuthorized'}:
            require(value is None, 'Unexpected diagnostic call payload.')
            self._allow_argv(kind, name, effect.argv)
        else:
            require(not effect.argv, 'Unexpected diagnostic argv.')
        if kind == 'Clock':
            scopes = {'perf': 'perf-sample', 'benchmark': 'benchmark-sample', 'health-quick': 'health-quick',
                      'diagnose-lag': 'diagnose-lag', 'log-tail': 'log-tail'}
            require(name in {'start', 'stop', 'elapsed'} and value == scopes.get(self.operation) and
                    (name != 'elapsed' or self.operation == 'log-tail'), 'Invalid diagnostic clock.')
        elif kind == 'Timestamp':
            require(name == 'o' and value is None and self.operation in {'perf', 'health-quick', 'health-detail',
                    'diagnose-lag', 'log-tail', 'audit-summary'}, 'Invalid diagnostic timestamp.')
        elif kind in {'FileExists', 'FileStat', 'ReadLines', 'ReadText', 'ResolvePath'}:
            path = self._selected_path(value)
            if kind == 'FileExists':
                allowed = {
                    'health-quick': {'cli_path', 'cache_directory', 'audit_directory', 'wrapper_log'},
                    'health-detail': {'cli_path'}, 'diagnose-lag': {'temp_root', 'cache_directory', 'wrapper_log'},
                    'audit-summary': {'audit_directory'}, 'log-tail': {'wrapper_log'},
                }.get(self.operation, set())
                paths = {self.paths[key] for key in allowed if key in self.paths}
                if self.operation == 'log-tail' and '--path' in self.explicit:
                    paths = {self.explicit['--path']}
                if self.operation == 'benchmark' and '--baseline' in self.explicit:
                    paths = {self.explicit['--baseline']}
                if self.operation == 'self-test' and self.cache_key:
                    paths = {self.paths['cache_directory'] / ('appshot-' + self.cache_key + '.json')}
                require(path in paths, 'Diagnostic file probe changed its requested path.')
            if kind == 'FileStat':
                require(self.operation in {'health-quick', 'diagnose-lag'} and path == self.paths['wrapper_log'], 'Invalid diagnostic stat.')
            if kind == 'ResolvePath':
                require(self.operation == 'release-notes' and path == self.paths['changelog_path'], 'Changelog resolution changed.')
                self._limit('resolve', 1)
            if kind == 'ReadText':
                require(self.operation == 'benchmark' and path == self.explicit.get('--baseline'), 'Baseline read changed.')
            if kind == 'ReadLines':
                require(path in self.readable, 'Diagnostic read was not preceded by owned resolution/enumeration.')
        elif kind == 'TailBytes':
            exact(value, ('path', 'max_bytes'))
            path = self._selected_path(value['path'])
            expected = self.explicit.get('--path', self.paths['wrapper_log']) if self.operation == 'log-tail' else self.paths['wrapper_log']
            maximum = positive_option(self.rest, '--max-bytes', 262144) if self.operation == 'log-tail' else 65536
            require(self.operation in {'log-tail', 'health-quick', 'diagnose-lag'} and path == expected and
                    type(value['max_bytes']) is int and value['max_bytes'] == maximum and maximum <= MAX_FILE_BYTES,
                    'Tail window differs from its original diagnostic.')
            self._limit('tail', 1)
        elif kind == 'ListFiles':
            exact(value, ('path', 'recurse', 'filter', 'file'))
            path = self._selected_path(value['path'])
            require(path in {self.paths['audit_directory'], self.paths['cache_directory'], self.paths['temp_root']},
                    'Diagnostic enumeration is not an owned directory.')
            require(type(value['recurse']) is bool and type(value['file']) is bool and
                    (value['filter'] is None or type(value['filter']) is str and '/' not in value['filter'] and '\\' not in value['filter']),
                    'Invalid file enumeration descriptor.')
            descriptor = (path, value['recurse'], value['filter'], value['file'])
            allowed = {
                'audit-summary': {(self.paths['audit_directory'], True, 'trajectory*.ndjson', False)},
                'health-quick': {(self.paths['cache_directory'], False, None, True), (self.paths['audit_directory'], True, None, True)},
                'diagnose-lag': {(self.paths['cache_directory'], False, None, True), (self.paths['temp_root'], True, None, True)},
            }.get(self.operation, set())
            require(descriptor in allowed, 'Enumeration is outside its original diagnostic.')
            self._limit('list:' + str(path), 1)
        elif kind == 'AuditProbe':
            require(self.operation in {'health-quick', 'health-detail'} and value == self.context['audit_directory'] and
                    name == ('.health-quick-probe-' if self.operation == 'health-quick' else '.health-probe-'), 'Invalid audit probe.')
            self._limit('audit-probe', 1)
        elif kind == 'ClearAppshotCache':
            require(self.operation == 'perf' and any(item.casefold() == '--include-live-ish' for item in self.rest) and
                    value == self.context['cache_directory'] and name == 'appshot-*.json', 'Invalid cache clear.')
            self._limit('cache-clear', 1)
        elif kind == 'Sleep':
            expected = min(8000, positive_option(self.rest, '--sample-ms', 3000))
            require(self.operation == 'diagnose-lag' and type(value) is int and value == expected and len(self.process_rows) == 1,
                    'Diagnostic sampling delay changed.')
            self._limit('sleep', 1)
        elif kind == 'ProcessMetrics':
            exact(value, ('current_ordinal', 'previous_ordinal'))
            require(self.operation == 'diagnose-lag' and len(self.process_rows) == 2, 'Process metrics have no owned snapshots.')
            current, previous = value['current_ordinal'], value['previous_ordinal']
            require(type(current) is int and 0 <= current < len(self.process_rows[1]), 'Invalid current process ordinal.')
            require(previous is None or type(previous) is int and 0 <= previous < len(self.process_rows[0]), 'Invalid previous process ordinal.')
            require(previous is None or self.process_rows[0][previous]['id'] == self.process_rows[1][current]['id'], 'Process ordinal identity changed.')
            require(self.counts['processor-count'] == 1 and self.metric_cursor < len(self.metric_order) and
                    self.metric_order[self.metric_cursor] == current, 'Process metrics changed their original grouped order.')
            expected = next((index for index in reversed(range(len(self.process_rows[0])))
                             if self.process_rows[0][index]['id'] == self.process_rows[1][current]['id']), None)
            require(previous == expected, 'Process metrics changed the previous retained object.')
            self.metric_cursor += 1
        elif kind == 'CacheKey':
            require(self.operation == 'self-test' and value == 'selftest-cache', 'Invalid self-test cache key.')
            self._limit('cache-key', 1)
        elif kind == 'Appshot':
            exact(value, ('match', 'semantic', 'no_cache', 'cache_max_seconds'))
            require(self.operation == 'self-test' and type(value['semantic']) is bool and type(value['no_cache']) is bool and
                    value['match'] in {'selftest-cache', ''}, 'Invalid diagnostic appshot.')
            expected = [dict(match='selftest-cache', semantic=False, no_cache=True, cache_max_seconds=None),
                        dict(match='selftest-cache', semantic=False, no_cache=False, cache_max_seconds=600)]
            if any(item.casefold() == '--deep' for item in self.rest):
                expected.append(dict(match='', semantic=True, no_cache=True, cache_max_seconds=None))
            require(value in expected, 'Appshot exceeds fixed self-test scope.')
            self._limit('appshot:' + str(expected.index(value)), 1)
        elif kind == 'Uia':
            require(self.operation == 'self-test' and any(item.casefold() == '--deep' for item in self.rest) and
                    value == {'focused_window': '', 'max_elements': 50}, 'Invalid deep UIA self-test.')
            self._limit('uia', 1)
        elif kind in {'EnsureWin32', 'EnsureUia', 'HelperUp', 'FindCodex'}:
            require(self.operation == ('health-quick' if kind == 'EnsureWin32' else 'health-detail') and value is None,
                    'Provider check is outside its original diagnostic.')
            self._limit(kind, 1)
        elif kind == 'Processes':
            require(self.operation == 'diagnose-lag' and value is None and
                    (not self.process_rows or self.counts['sleep'] == 1), 'Invalid process snapshot order.')
        elif kind == 'ProcessorCount':
            require(self.operation == 'diagnose-lag' and value is None and len(self.process_rows) == 2, 'Invalid processor-count query.')
            self._limit('processor-count', 1)
        elif kind == 'Windows':
            require(self.operation == 'diagnose-lag' and value is None, 'Invalid foreground query.')
            self._limit('windows', 1)
        elif kind == 'NodeVersion':
            require(self.operation in {'health-quick', 'health-detail'} and value is None, 'Invalid node probe.')
            self._limit('node', 1)
        elif kind == 'Notice':
            flags = {item.casefold() for item in self.rest}
            expected = 'self-test 시작 (deep=' + str('--deep' in flags) + ', strict=' + str('--strict' in flags) + ')'
            require(self.operation == 'self-test' and name == 'INFO' and value == expected, 'Invalid self-test notice.')
            self._limit('notice', 1)
        elif kind in CALLBACKS:
            require(kind in {'Cli', 'Native', 'Macro', 'AssertAuthorized', 'Appshot', 'Uia'} or value is None, 'Unexpected callback data.')
        else:
            require(value is None or kind == 'Notice' and type(value) is str, 'Unexpected diagnostic value.')

    def dispatch(self, effect):
        # LegacyEffectSession validates once, before marking possible effects.
        self._check()
        kind, name, value = effect.name, effect.data['name'], effect.data['value']
        if kind == 'Clock':
            if name == 'start':
                self.clocks[value] = self.clock()
                return 0
            require(value in self.clocks, 'Diagnostic clock has not started.')
            elapsed = (self.clock() - self.clocks[value]) * 1000
            return int(elapsed) if value == 'benchmark-sample' else round(elapsed)
        if kind == 'Timestamp':
            return timestamp()
        if kind == 'FileExists':
            return self._selected_path(value).exists()
        if kind == 'FileStat':
            path = self._selected_path(value)
            identity(path)
            return {'length': path.stat().st_size}
        if kind == 'ResolvePath':
            path = self.paths['changelog_path']
            if not path.exists():
                return None
            self.readable[path] = identity(path)
            self.resolved_changelog = path
            return str(path)
        if kind == 'ListFiles':
            base = self._selected_path(value['path'])
            if not base.is_dir():
                return []
            results, pending = [], [base]
            while pending:
                directory = owned_path(str(pending.pop()))
                self._check()
                require(directory.is_relative_to(base), 'Diagnostic directory escaped its owned root.')
                for entry in directory.iterdir():
                    self._check()
                    if entry.is_symlink() or getattr(entry.lstat(), 'st_file_attributes', 0) & 0x400:
                        continue
                    if entry.is_dir() and value['recurse']:
                        pending.append(entry)
                    if value['file'] and not entry.is_file() or value['filter'] and not fnmatch.fnmatchcase(entry.name.casefold(), value['filter'].casefold()):
                        continue
                    require(len(results) < MAX_FILES, 'Diagnostic enumeration exceeds its file budget.')
                    info = entry.stat()
                    path = entry.resolve()
                    if entry.is_file():
                        self.readable[path] = (info.st_dev, info.st_ino)
                    results.append(dict(full_name=str(path), length=info.st_size if entry.is_file() else None,
                                        last_write_time=timestamp(datetime.fromtimestamp(info.st_mtime).astimezone())))
            return results
        if kind == 'ReadLines':
            from .legacy_host import _legacy_lines, _read_lines
            path = self._selected_path(value)
            raw, _ = read_regular(path, expected=self.readable[path])
            return _read_lines(raw.decode('utf-8-sig', errors='replace')) if self.operation == 'audit-summary' else _legacy_lines(raw)
        if kind == 'ReadText':
            from .legacy_host import _legacy_text
            raw, _ = read_regular(self._selected_path(value))
            return _legacy_text(raw)
        if kind == 'TailBytes':
            raw, total = read_regular(self._selected_path(value['path']), maximum=value['max_bytes'], tail=True)
            return dict(total_bytes=total, tail_bytes=len(raw), text=raw.decode('utf-8', errors='replace'))
        if kind == 'AuditProbe':
            directory = self.paths['audit_directory']
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / (name + uuid.uuid4().hex)
            descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(descriptor, b'\xef\xbb\xbfok\r\n')
            finally:
                os.close(descriptor)
                probe.unlink()
            return None
        if kind == 'ClearAppshotCache':
            base = self.paths['cache_directory']
            if base.is_dir():
                for path in base.glob('appshot-*.json'):
                    if path.is_file() and not path.is_symlink() and not (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
                        owned_path(str(path)).unlink()
            return None
        if kind == 'NodeVersion':
            executable = shutil.which('node')
            if not executable:
                raise FileNotFoundError('node was not found')
            from .legacy_process import capture
            code, stdout, stderr = capture([executable, '--version'], min(10, self.deadline - time.monotonic()), cancelled=self.cancelled)
            return {'exit': code, 'output': (stdout + stderr).decode('utf-8', errors='replace').rstrip('\r\n')}
        if kind == 'FindCodex':
            return shutil.which('codex')
        if kind == 'ProcessorCount':
            return os.cpu_count() or 1
        if kind == 'Sleep':
            duration = min(value / 1000, max(0, self.deadline - time.monotonic()))
            if self.cancelled is not None and self.sleep is time.sleep:
                self.cancelled.wait(duration)
            else:
                self.sleep(duration)
            self._check()
            return None
        if kind == 'CacheKey':
            self.cache_key = hashlib.md5(value.lower().encode('utf-8')).hexdigest()
            path = self.paths['cache_directory'] / ('appshot-' + self.cache_key + '.json')
            self.readable[path] = None
            return self.cache_key
        if kind == 'Notice':
            return None
        require(kind in self.callbacks, 'Diagnostic callback is not supplied: ' + kind)
        result = self.callbacks[kind](name, list(effect.argv), value)
        if kind == 'Processes':
            require(type(result) is list and all(type(row) is dict and type(row.get('id')) is int and
                    type(row.get('name')) is str for row in result), 'Invalid process snapshot.')
            self._limit('processes', 2)
            self.process_rows.append(result)
            if len(self.process_rows) == 2:
                for group in ({'codex'}, {'electron', 'code', 'cursor', 'windsurf'}, {'node'}, {'powershell', 'pwsh'},
                              {'chrome', 'msedge', 'brave', 'whale'}, {'cucp-helper', 'windows-mcp-helper'}):
                    self.metric_order.extend(index for index, row in enumerate(result) if row['name'].casefold() in group)
        return result

    def validate_completion(self, result):
        require(type(result['exit']) is int and type(result['emit_json']) is bool, 'Invalid diagnostic completion.')
        payload = result['payload']
        require(payload is None or type(payload) is dict, 'Invalid diagnostic result object.')
