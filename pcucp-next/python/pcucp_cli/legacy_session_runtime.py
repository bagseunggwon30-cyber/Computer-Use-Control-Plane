"""Complete session macro: cache IO and the existing owned helper lifecycle."""
import fnmatch
import math
from pathlib import Path
import sys
import time
import unicodedata

from .legacy_cdp_contract import _ps_equal, ps_string
from .legacy_diagnostic_provider import option, owned_path
from .legacy_host_protocol import exact, LegacyHostError, require
from .legacy_native_macros import _truth
from .legacy_values import int32

FIELDS = ('cache_directory', 'audit_directory', 'wrapper_log', 'cli_path', 'cache_seconds',
          'lock_file', 'desktop', 'staged', 'modern', 'startup_directory', 'metadata_directory')
COMMANDS = ('clear-cache', 'info', 'start-helper', 'stop-helper', 'helper-status',
            'install-autostart', 'uninstall-autostart', 'autostart-status')
HELP = 'session 하위 명령: ' + ', '.join(COMMANDS)


def _get(reply, name):
    if type(reply) is dict:
        return next((value for key, value in reply.items() if key.lower() == name.lower()), None)
    return None


def _layer(schema, reply):
    result = dict(schema=schema)
    require(type(reply) is dict, 'Helper lifecycle result must be an object.')
    for key, value in reply.items():
        existing = next((old for old in result if old.lower() == key.lower()), key)
        result[existing] = value
    return result


class SessionRuntime:
    def __init__(self, context, *, allow_live_control=False, timeout_s=30,
                 parent_deadline=math.inf, cancelled=None, helper=None, mutation=None):
        exact(context, FIELDS)
        require(type(allow_live_control) is bool and type(timeout_s) in (int, float)
                and math.isfinite(timeout_s) and timeout_s > 0, 'Invalid session startup.')
        require(type(context['desktop']) is bool and type(context['staged']) is bool and type(context['modern']) is bool
                and type(context['cache_seconds']) is int and
                all(context[key] is None or type(context[key]) is str for key in
                    ('cli_path', 'startup_directory', 'metadata_directory')), 'Invalid session context.')
        self.context = dict(context)
        self.paths = {key: owned_path(context[key]) for key in
                      ('cache_directory', 'audit_directory', 'wrapper_log', 'lock_file')}
        self.allow_live_control, self.cancelled, self.helper = allow_live_control, cancelled, helper
        self.mutation = mutation
        self.deadline = min(time.monotonic() + timeout_s, parent_deadline)
        self.used = False

    def remaining(self):
        require(self.cancelled is None or not self.cancelled.is_set(), 'Session owner cancelled; no retry.')
        value = self.deadline - time.monotonic()
        require(value > 0, 'Session deadline expired; no retry.')
        return value

    def _files(self, pattern):
        self.remaining()
        root = self.paths['cache_directory']
        try:
            for entry in root.iterdir():
                self.remaining()
                if not fnmatch.fnmatchcase(entry.name.lower(), pattern):
                    continue
                try:
                    info = entry.lstat()
                    # Get-ChildItem without -Force excludes Hidden/System.
                    if getattr(info, 'st_file_attributes', 0) & 6:
                        continue
                except OSError:
                    continue
                yield entry
        except OSError:
            return

    def _helper(self, operation, arguments):
        self.remaining()
        def mark():
            if operation in ('start','stop','autostart-install','autostart-uninstall') and self.mutation is not None:
                self.mutation.set()
        if self.helper is not None:
            mark()
            return self.helper(operation, arguments)
        from .legacy_helper_runtime import StagedHelperRuntime, WindowsAuthority, validate_package
        package = Path(__file__).resolve().parents[2] / 'bin/legacy-helper'
        try:
            if operation.startswith('autostart-'):
                from .legacy_helper_autostart import AutostartController, WindowsAutostartStore
                from .legacy_default_autostart import DefaultAutostartController
                startup, metadata = self.context['startup_directory'], self.context['metadata_directory']
                require(startup is not None and metadata is not None, 'fixed_autostart_directories_required')
                authority = WindowsAuthority()
                controller = AutostartController if self.context['staged'] else DefaultAutostartController
                bootstrap = 'legacy_helper_autostart_entry.py' if self.context['staged'] else 'legacy_helper_autostart_default.py'
                source = Path(__file__).resolve().parents[1]
                extra = {} if self.context['staged'] else dict(legacy_server=source.parents[1] / 'scripts/cucp-helper-server.ps1')
                runtime = controller(startup, sys.executable, source / bootstrap, metadata_directory=metadata,
                    store=WindowsAutostartStore(startup, metadata, authority), allow_change=self.allow_live_control,
                    desktop=self.context['desktop'], validate_install=lambda: validate_package(package), **extra)
            else:
                runtime = StagedHelperRuntime(package, self.paths['lock_file'], desktop=self.context['desktop'])
            mark()
            reply = runtime.handle(dict(operation=operation, arguments=arguments))
        except Exception as error:
            raise LegacyHostError('Staged helper failed; no fallback or retry: ' + str(error)[:512]) from error
        self.remaining()
        return reply

    def run(self, rest, *, brief=False):
        require(not self.used, 'Session runtime already used; no queued replay.')
        self.used = True
        require(type(rest) is list and all(type(word) is str for word in rest) and type(brief) is bool,
                'Session argv must be inert strings.')
        self.remaining()
        name = next((name for name in COMMANDS if rest and _ps_equal(rest[0], name)), None)
        def output(payload=None, line=None, exit=0, notices=None):
            return dict(payload=payload, brief=line if brief else None, emit_json=payload is not None and not (brief and line),
                        exit=exit, json_depth=6, notices=notices or [])
        if name is None:
            return output(exit=1, notices=[dict(level='ERROR', message=HELP)])
        if name in ('install-autostart', 'uninstall-autostart'):
            require(self.allow_live_control, 'session ' + name + ' requires -AllowLiveControl')
        if name == 'clear-cache':
            for pattern in ('appshot-*.json', 'point-plan-*.json'):
                for path in self._files(pattern):
                    self.remaining()
                    # Only immediate, fixed-pattern entries; no recursive deletion.
                    require(path.parent == self.paths['cache_directory'], 'Session cache target escaped its startup root.')
                    try:
                        if self.mutation is not None:
                            self.mutation.set()
                        if path.is_dir() and not path.is_symlink():
                            path.rmdir()  # nonempty directories remain, as without -Recurse
                        else:
                            path.unlink()
                    except OSError:
                        pass
            return output(notices=[dict(level='OK', message='관찰/포인트 캐시를 비웠습니다.')])
        if name == 'info':
            count = sum(1 for _ in self._files('appshot-*.json'))
            points = sum(1 for _ in self._files('point-plan-*.json'))
            try:
                log = self.paths['wrapper_log']
                size = log.stat().st_size if log.is_file() else None if log.exists() else 0
            except OSError:
                size = 0
            try:
                helper = self._helper('status', {})
            except Exception:
                self.remaining()
                helper = None
            payload = dict(cache_dir=self.context['cache_directory'], audit_dir=self.context['audit_directory'],
                cache_files=count, point_plan_cache_files=points, log_path=self.context['wrapper_log'],
                log_size_bytes=size, cli_path=self.context['cli_path'], cache_seconds=self.context['cache_seconds'], helper_server=helper)
            # The original info always emits JSON, even in brief mode.
            result = output(payload); result['emit_json'] = True
            return result
        arguments = {}
        operation = {'start-helper':'start', 'stop-helper':'stop', 'helper-status':'status',
                     'install-autostart':'autostart-install', 'uninstall-autostart':'autostart-uninstall',
                     'autostart-status':'autostart-status'}[name]
        if name in ('start-helper', 'install-autostart'):
            default = 60000 if name == 'start-helper' else 28800000
            raw = option(rest, '--idle-timeout-ms')
            try:
                whitespace = bool(raw) and all(ch in '\t\n\v\f\r\u0085' or unicodedata.category(ch) in ('Zs','Zl','Zp') for ch in raw)
                idle = 0 if self.context['modern'] and whitespace else int32(raw) if raw else default
            except LegacyHostError:
                idle = default
            arguments = dict(idle_timeout_ms=idle)
        elif name == 'stop-helper':
            arguments = dict(force=any(_ps_equal(word, '--force') for word in rest))
        reply = self._helper(operation, arguments)
        ok = type(_get(reply, 'status')) is str and _ps_equal(_get(reply, 'status'), 'ok')
        s = lambda key: ps_string(_get(reply, key))
        if name == 'start-helper':
            state = 'reused' if _truth(_get(reply, 'reused')) else 'spawned'
            line = f"ok session start-helper {state} pid={s('pid')} pipe={s('pipe_name')}" if ok else f"error session start-helper reason={s('reason')}"
            return output(_layer('cucp.helper-server-start/v1', reply), line, 0 if ok else 1)
        if name == 'stop-helper':
            line = f"{s('status')} session stop-helper stopped_pid={s('stopped_pid')} forced={s('forced')}"
            return output(_layer('cucp.helper-server-stop/v1', reply), line, 0 if ok else 1)
        if name == 'helper-status':
            line = f"ok session helper-status alive pid={s('pid')} uptime_s={s('uptime_s')} requests={s('request_count')}" if _truth(_get(reply, 'alive')) else 'ok session helper-status not_running'
            return output(reply, line)
        line = (f"{s('status')} session install-autostart shim={s('shim_path')}" if name == 'install-autostart' else
                f"{s('status')} session uninstall-autostart removed={s('removed')}" if name == 'uninstall-autostart' else
                f"ok session autostart-status installed={s('installed')}")
        return output(_layer('cucp.helper-autostart/v1', reply), line, 0 if ok or name == 'autostart-status' else 1)
