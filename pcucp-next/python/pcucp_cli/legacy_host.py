"""Opt-in legacy host spine, with an intentionally small qualified surface.

Session/daemon caches live on this owner. Each coordinator invocation gets fresh
invocation state; no retained PowerShell leaf or modern engine fallback exists.
The complete frozen legacy registry is metadata, not an availability promise.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import math
import stat
from pathlib import Path
import threading

from .legacy_cdp import LegacyCdpAdapter
from .legacy_cdp_contract import ACTIONS, LIVE_ACTIONS, prepare_macro
from .legacy_cdp_macro import LegacyCdpPortCache, execute_macro
from .legacy_host_protocol import Authority, LegacyHostError, exact, require
from .legacy_host_session import LegacyEffectSession

READ_ONLY_CDP = frozenset(ACTIONS - LIVE_ACTIONS)


@dataclass(frozen=True)
class HostOptions:
    changelog_path: str
    cdp_endpoint: str = 'http://127.0.0.1:9222'
    timeout_s: float = 30.0
    culture: str = 'en-US'

    def __post_init__(self):
        require(type(self.changelog_path) is str and '\0' not in self.changelog_path and Path(self.changelog_path).is_absolute(),
                'Changelog startup path must be absolute without NUL.')
        require(type(self.culture) is str and len(self.culture) <= 128, 'Invalid startup culture.')
        require(type(self.timeout_s) in (int, float) and math.isfinite(self.timeout_s) and self.timeout_s > 0,
                'Legacy startup timeout must be positive and finite.')


def _legacy_text(raw):
    """Get-Content's reached text-file boundary: BOM or Windows ANSI.

    Portable qualification files must be ASCII or BOM-marked. A Linux locale is
    not proof of the user's Windows ACP, and is never silently substituted.
    """
    if raw.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        text = raw.decode('utf-32', errors='replace')
    elif raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = raw.decode('utf-16', errors='replace')
    elif raw.startswith(b'\xef\xbb\xbf'):
        text = raw.decode('utf-8-sig', errors='replace')
    elif os.name == 'nt':
        import ctypes
        text = raw.decode(f'cp{ctypes.windll.kernel32.GetACP()}', errors='replace')
    else:
        require(raw.isascii(), 'Portable legacy text qualification requires ASCII or an explicit BOM.')
        text = raw.decode('ascii')
    return text


def _legacy_lines(raw):
    # StreamReader.ReadLine recognizes CR, LF, CRLF, not every Unicode separator.
    return _read_lines(_legacy_text(raw))


def _read_lines(text):
    import re
    lines = re.split(r'\r\n|\r|\n', text)
    if lines and not lines[-1]:
        lines.pop()
    return lines


class ReleaseNotesProvider:
    """Exactly the two read-only effects reached by release-notes, once each."""
    def __init__(self, options):
        self.options = options
        self.phase = 0
        self.resolved = None
        self.identity = None

    def context(self):
        # Unused contexts are inert strings, not authority to access these paths.
        return dict(audit_directory='', cache_directory='', wrapper_log='', cli_path=None,
                    changelog_path=self.options.changelog_path, temp_root='',
                    benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')

    def validate_startup(self, family, startup, authority):
        exact(startup, ('schema', 'operation', 'rest', 'brief', 'cache_seconds', 'vision_available', 'culture', 'context'))
        require(family == 'diagnostics' and startup['schema'] == 'cucp.diagnostic-start/v1' and
                startup['operation'] == 'release-notes' and startup['brief'] is True and
                startup['vision_available'] is False and type(startup['cache_seconds']) is int and
                startup['cache_seconds'] == 2 and startup['culture'] == self.options.culture and
                startup['context'] == self.context() and authority == Authority(), 'Unqualified diagnostic startup.')
        require(type(startup['rest']) is list and all(type(value) is str for value in startup['rest']), 'Invalid original argv.')

    def validate(self, effect):
        require(effect.kind == 'Diagnostic' and effect.name in ('ResolvePath', 'ReadLines') and
                not any((effect.live, effect.quiet, effect.brief, effect.confirm_sensitive)) and not effect.argv,
                'Effect is outside the qualified release-notes provider.')
        exact(effect.data, ('name', 'value'))
        require(effect.data['name'] == '' and type(effect.data['value']) is str, 'Invalid diagnostic path descriptor.')
        if effect.name == 'ResolvePath':
            require(self.phase == 0 and effect.data['value'] == self.options.changelog_path,
                    'Changelog resolution changed its startup path or order.')
        else:
            require(self.phase == 1 and self.resolved is not None and effect.data['value'] == self.resolved,
                    'Changelog read lacks matching owned resolution.')

    def dispatch(self, effect):
        self.validate(effect)
        if effect.name == 'ResolvePath':
            self.phase = 1
            path = Path(self.options.changelog_path)
            if not path.exists():
                return None
            # The current checkpoint does not qualify reparse/symlink semantics.
            require(not path.is_symlink(), 'Symlink changelog paths are not qualified.')
            info = path.stat()
            require(stat.S_ISREG(info.st_mode), 'Only regular changelog files are qualified.')
            self.identity = (info.st_dev, info.st_ino)
            self.resolved = str(path.absolute())
            return self.resolved
        self.phase = 2
        path = Path(self.resolved)
        require(not path.is_symlink(), 'Changelog path changed to a symlink after resolution.')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
        # A FIFO swapped in after resolution must not block; compare the opened
        # object before reading any bytes, never silently follow a new target.
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == self.identity,
                    'Changelog file identity changed after owned resolution.')
            return _legacy_lines(stream.read())

    def validate_completion(self, result):
        require(self.phase == 2 and result['exit'] == 0 and result['emit_json'] is False and
                type(result['brief']) is str and type(result['payload']) is dict and
                result['payload'].get('schema') == 'cucp.release-notes/v1', 'Unexpected release-notes completion.')


class LegacyHost:
    """One trusted owner per entry/daemon, with immutable startup ceilings."""
    def __init__(self, options, authority=Authority()):
        require(type(options) is HostOptions and type(authority) is Authority, 'Invalid host startup.')
        self._options = options
        self._authority = authority
        self._cdp = None
        self._port_cache = LegacyCdpPortCache()
        self._active = None
        self._closed = False
        self._serial = threading.Lock()
        self._state_lock = threading.RLock()

    @property
    def authority(self):
        return self._authority

    @property
    def closed(self):
        with self._state_lock:
            return self._closed

    def close(self):
        with self._state_lock:
            self._closed = True
            active, cdp = self._active, self._cdp
        if active is not None:
            active.close()
        if cdp is not None:
            cdp.close()

    def invoke(self, argv, *, brief, quiet=False, authority=None):
        require(type(argv) is list and all(type(item) is str for item in argv), 'Legacy argv must be a string array.')
        require(type(brief) is bool and type(quiet) is bool, 'Legacy options must be booleans.')
        require(brief, 'unqualified_surface: exact legacy JSON formatting is not enabled in this checkpoint.')
        authority = self.authority if authority is None else self.authority.restrict(authority.live, authority.sensitive)
        from .legacy_dispatch import classify_top_level
        route = classify_top_level(argv)
        require(route.kind == 'macro' and len(route.argv) >= 2, 'unqualified_surface: only explicit legacy macro entry is enabled.')
        record = route.macro
        require(record is not None, 'Unknown macro: ' + route.argv[1])
        name, rest = record.name, list(route.rest)
        available = name in READ_ONLY_CDP or name == 'release-notes' or record.implementation == 'not_implemented'
        require(available, 'unqualified_surface: legacy macro ' + name + ' still requires retained providers.')
        # Availability and format checks precede all provider acquisition.
        require(self._serial.acquire(blocking=False), 'Legacy host already owns an invocation; no queued replay.')
        try:
            with self._state_lock:
                require(not self._closed, 'Legacy host closed; action not retried.')
            if record.implementation == 'not_implemented':
                return 1, 'not_implemented ' + name + '\n'
            if name == 'release-notes':
                provider = ReleaseNotesProvider(self._options)
                startup = dict(schema='cucp.diagnostic-start/v1', operation=name, rest=rest,
                               brief=True, cache_seconds=2, vision_available=False,
                               culture=self._options.culture, context=provider.context())
                session = LegacyEffectSession(timeout_s=self._options.timeout_s)
                with self._state_lock:
                    self._active = session
                    require(not self._closed, 'Legacy host closed; action not retried.')
                try:
                    result = session.run('diagnostics', startup, Authority(), provider)
                except BaseException:
                    self.close()
                    raise
                return result['exit'], result['brief'] + '\n'
            macro = prepare_macro(name, rest, allow_live_control=False)
            with self._state_lock:
                require(not self._closed, 'Legacy host closed; action not retried.')
                if self._cdp is None:
                    self._cdp = LegacyCdpAdapter(self._options.cdp_endpoint, allow_live_control=False,
                                                 timeout_s=min(self._options.timeout_s, 8))
                adapter = self._cdp
            result = execute_macro(adapter, macro, cache=self._port_cache)
            with self._state_lock:
                require(not self._closed, 'Legacy host cancelled; action not retried.')
            return result.exit_code, result.render(brief=True)
        finally:
            with self._state_lock:
                self._active = None
            self._serial.release()

    def typed_child(self, request):
        """Typed re-entry shares the owner, cache and immutable startup authority.

        All control-looking argv values remain data. No child can mint a ceiling;
        no process-per-effect cache reset is hidden behind this boundary.
        """
        exact(request, ('schema', 'argv', 'live', 'quiet', 'brief', 'confirm_sensitive'))
        require(request['schema'] == 'cucp.legacy-python-child/v1', 'Invalid typed legacy child schema.')
        child_authority = self.authority.restrict(request['live'], request['confirm_sensitive'])
        return self.invoke(request['argv'], brief=request['brief'], quiet=request['quiet'], authority=child_authority)
