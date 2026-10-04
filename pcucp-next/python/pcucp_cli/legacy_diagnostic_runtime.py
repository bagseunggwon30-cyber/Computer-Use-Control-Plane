"""Owned Python runtime for the nine preserved legacy diagnostics.

This source entry is explicit until the complete wrapper replacement qualifies.
It runs the original managed coordinators and real bounded Python/C# leaves.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import math

from .legacy_diagnostic_provider import DiagnosticProvider, OPERATIONS, owned_path, read_regular, timestamp
from .legacy_host_protocol import Authority, LegacyHostError, parse_json, require
from .legacy_host_session import LegacyEffectSession, cancel_with_owner
from .native_session import NativeSession


def validate_cli(path):
    if not path:
        return None
    path = owned_path(str(Path(path).absolute()))
    require(path.suffix.lower() == '.mjs' and path.is_file(), 'Select the existing desktop cli.mjs, not a shell wrapper.')
    package = path.parent.parent / 'package.json'
    if package.is_file():
        raw, _ = read_regular(package, maximum=65536)
        try:
            name = json.loads(raw.decode('utf-8-sig')).get('name')
        except (ValueError, AttributeError):
            name = None
        require(not name or name == 'computer-use-control-plane', 'Configured Node package is not the desktop control plane.')
        if name == 'computer-use-control-plane':
            return str(path)
    raw, _ = read_regular(path, maximum=1024 * 1024, head=True)
    header = '\n'.join(raw.decode('utf-8-sig').splitlines()[:60])
    require(bool(re.search(r'ControlPlane|control-plane\.mjs|observeAppshot|"observe"\s+&&\s+subcommand', header)),
            'Configured Node entry is not the desktop control plane.')
    return str(path)


class DiagnosticRuntime:
    def __init__(self, context, *, culture='en-US', timeout_s=30, cache_seconds=2,
                 cli_path=None, helper_status=None, read_macro=None, native_factory=NativeSession, parent_deadline=math.inf,
                 parent_cancelled=None):
        self.context = dict(context)
        self.context['cli_path'] = validate_cli(cli_path or context.get('cli_path'))
        self.culture, self.timeout_s, self.cache_seconds = culture, timeout_s, cache_seconds
        self.helper_status, self.read_macro, self.native_factory = helper_status, read_macro, native_factory
        self.native = None
        self.parent_deadline, self._deadline, self._cancelled = parent_deadline, math.inf, parent_cancelled
        self.parent_cancelled = parent_cancelled

    def _bind_session(self, deadline, cancelled):
        self._deadline, self._cancelled = deadline, cancelled

    def _remaining(self):
        require(self._cancelled is None or not self._cancelled.is_set(), 'Diagnostic owner cancelled; action not retried.')
        remaining = min(self.timeout_s, self._deadline - time.monotonic())
        require(remaining > 0, 'Diagnostic owner timed out; action not retried.')
        return remaining

    def _read(self, operation, value=None):
        args = ['--operation', operation]
        if operation == 'process-metrics':
            args.extend(['--current', str(value['current_ordinal'])])
            if value['previous_ordinal'] is not None:
                args.extend(['--previous', str(value['previous_ordinal'])])
        code, payload, error = self.native('legacy-diagnostic-read', args, timeout_s=self._remaining())
        if code != 0 or payload is None:
            raise OSError(error or 'Read-only native diagnostic acquisition failed')
        return payload['data']['value']

    def _cli(self, argv):
        node = shutil.which('node')
        path = self.context['cli_path']
        if not node or not path:
            return {'exit': 1, 'json': None}
        # Read-only callbacks never introduce startup input permission.
        require(tuple(argv[:1]) in {('version',), ('tools',), ('health',), ('release',), ('observe',)},
                'Diagnostic CLI callback is not read-only.')
        from .legacy_process import capture
        code, stdout, stderr = capture([node, path, *argv], self._remaining(), cancelled=self._cancelled)
        try:
            data = json.loads(stdout.decode('utf-8', errors='strict'))
        except ValueError:
            data = None
        return {'exit': code, 'json': data}

    def _native(self, action):
        data = self._read('native-' + action)
        status = data.get('status') if isinstance(data, dict) else None
        return {'exit': 0 if status == 'ok' else 2 if status == 'partial' else 1, 'json': data}

    def _windows(self, match=None):
        rows = self._read('windows')
        if match:
            rows = [row for row in rows if match.casefold() in row['title'].casefold() or match.casefold() in row['process'].casefold()]
        return rows

    def _affordances(self, match='', maximum=50):
        code, payload, error = self.native('legacy-diagnostic-read', ['--operation', 'uia-affordances',
            '--focused-window', match, '--max-elements', str(maximum)], timeout_s=self._remaining())
        if code != 0 or payload is None:
            raise OSError(error or 'Legacy UIA affordance acquisition failed')
        return payload['data']['value']

    def _appshot_result(self, data, path, cached):
        appshot, fusion = None, None
        for artifact in data.get('artifacts') or []:
            if artifact.get('type') == 'desktop_appshot':
                appshot = artifact
            elif artifact.get('type') == 'desktop_observation_fusion':
                fusion = artifact
        if appshot is None and data.get('type') == 'desktop_appshot':
            appshot = data
        appshot, fusion = appshot or {}, fusion or {}
        items = (appshot.get('text') or {}).get('items') or []
        grounded = fusion.get('grounded_elements') or []
        if not grounded:
            grounded = self._affordances(appshot.get('focused_window') or '', 400)
        affordances = {}
        for item in grounded:
            if item.get('affordance_id') and item.get('rect'):
                affordances[item['affordance_id']] = item
        for item in items:
            if item.get('affordance_id') and item.get('rect'):
                affordances.setdefault(item['affordance_id'], item)
        return dict(Json=data, Path=str(path), FromCache=cached, ObservationId=appshot.get('observation_id'),
                    FocusedWindow=appshot.get('focused_window'), ScreenshotPath=appshot.get('screenshot_path'),
                    Items=items, FusedElements=fusion.get('fused_elements') or [], Grounded=grounded, Affordances=affordances)

    def _appshot(self, value):
        import hashlib
        match = value['match']
        key = hashlib.md5((match.lower() if match.strip() else '_full').encode('utf-8')).hexdigest()
        directory = owned_path(self.context['cache_directory'])
        cache = owned_path(str(directory / ('appshot-' + key + '.json')))
        maximum = self.cache_seconds if value['cache_max_seconds'] is None else value['cache_max_seconds']
        if not value['no_cache'] and maximum > 0 and cache.is_file():
            if datetime.now().timestamp() - cache.stat().st_mtime <= maximum:
                try:
                    raw, _ = read_regular(cache)
                    return self._appshot_result(parse_json(raw.decode('utf-8-sig')), cache, True)
                except (OSError, ValueError, LegacyHostError):
                    pass
        if not self.context['cli_path']:
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        fresh = directory / ('appshot-fresh-' + os.urandom(16).hex() + '.json')
        temporary = directory / (cache.name + '.tmp-' + os.urandom(16).hex())
        try:
            args = ['observe', 'appshot']
            if match:
                args += ['--match', match]
            args.append('--annotate' if value['semantic'] else '--no-semantic')
            args += ['--out', str(fresh)]
            reply = self._cli(args)
            if reply['exit'] != 0 or not fresh.is_file():
                return None
            raw, _ = read_regular(fresh)
            result = parse_json(raw.decode('utf-8-sig'))
            with temporary.open('xb') as stream:
                stream.write(raw)
            os.replace(temporary, cache)
            result = self._appshot_result(result, fresh, False)
            from .legacy_storage import append_trajectory
            append_trajectory(self.context['audit_directory'], 'observation', dict(observation_id=result['ObservationId'],
                focused_window=result['FocusedWindow'], match=match, affordance_count=len(result['Affordances']), from_cache=False))
            return result
        finally:
            temporary.unlink(missing_ok=True)

    def _metrics(self):
        from .legacy_values import int32
        path = Path(self.context['audit_directory']) / 'trajectory.ndjson'
        rows = []
        if path.is_file():
            raw, _ = read_regular(path, maximum=32 * 1024 * 1024)
            for line in raw.decode('utf-8-sig', errors='replace').splitlines()[-500:]:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
                except ValueError:
                    pass
        grouped = {kind: [row for row in rows if str(row.get('kind', '')).casefold() == kind]
                   for kind in ('observation', 'click', 'vision_find', 'vision_click')}
        clicks, observations = grouped['click'], grouped['observation']
        successful = sum(1 for row in clicks if int32(row.get('exit')) == 0)
        cached = sum(1 for row in observations if row.get('from_cache') is True)
        log = Path(self.context['wrapper_log'])
        cache = Path(self.context['cache_directory'])
        return dict(status='ok', collected_at=timestamp(),
            counters=dict(observations=len(observations), clicks=len(clicks), vision_finds=len(grouped['vision_find']),
                          vision_clicks=len(grouped['vision_click']), total_actions=len(clicks) + len(grouped['vision_click'])),
            rates=dict(click_success_pct=round(successful / len(clicks) * 100, 1) if clicks else 0,
                       cache_hit_pct=round(cached / len(observations) * 100, 1) if observations else 0),
            storage=dict(audit_log_bytes=log.stat().st_size if log.exists() else 0,
                         cache_files=len(list(cache.glob('appshot-*.json'))) if cache.is_dir() else 0,
                         cache_dir=str(cache), trajectory_path=str(path)),
            config=dict(cache_seconds=self.cache_seconds, invoke_timeout_ms=int(self.timeout_s * 1000), cli_path=self.context['cli_path']))

    def _helper_up(self):
        if self.helper_status is not None:
            return bool(self.helper_status())
        from .legacy_helper_runtime import StagedHelperRuntime
        package = Path(__file__).resolve().parents[2] / 'bin/legacy-helper'
        if not package.is_dir():
            return False
        runtime = StagedHelperRuntime(package, Path(self.context['temp_root']) / 'helper.pid')
        return runtime.handle({'operation': 'status', 'arguments': {}}).get('alive') is True

    @staticmethod
    def _assert_authorized(argv):
        # The diagnostic owner is read-only. Apply both original gate predicates;
        # the fixed self-test cannot grant input or dispatch an action.
        coordinates = argv[:2] == ['act', 'click']
        missing_observation = coordinates and '--after' not in argv
        return missing_observation or coordinates

    def _macro(self, name, argv):
        if self.read_macro is not None:
            return self.read_macro(name, argv)
        if name == 'health-quick':
            return DiagnosticRuntime(self.context, culture=self.culture, timeout_s=self.timeout_s,
                cache_seconds=self.cache_seconds, helper_status=self.helper_status, parent_deadline=self._deadline,
                parent_cancelled=self._cancelled).run(name, argv)['exit']
        if name == 'windows':
            from .legacy_windows import observe_windows
            return observe_windows(self, argv)[0]
        if name == 'find-label':
            from .legacy_label_provider import LabelReadProvider
            provider = LabelReadProvider(self, argv)
            return LegacyEffectSession(timeout_s=self._remaining(), parent_cancelled=self._cancelled).run('interaction', provider.startup(), Authority(), provider)['exit']
        if name == 'metrics':
            self._metrics()
            return 0
        raise LegacyHostError('Unknown read-only diagnostic macro')

    def run(self, operation, rest, *, brief=False):
        require(operation in OPERATIONS, 'Unknown legacy diagnostic operation.')
        with self.native_factory(allow_live_control=False) as native, cancel_with_owner(native, self.parent_cancelled):
            self.native = native
            callbacks = {
                'Cli': lambda name, argv, value: self._cli(argv),
                'Native': lambda name, argv, value: self._native(argv[1]),
                'Macro': lambda name, argv, value: self._macro(name, argv),
                'EnsureWin32': lambda *unused: self._read('ensure-win32'),
                'EnsureUia': lambda *unused: self._read('ensure-uia'),
                'HelperUp': lambda *unused: self._helper_up(),
                'Processes': lambda *unused: self._read('processes'),
                'ProcessMetrics': lambda name, argv, value: self._read('process-metrics', value),
                'Windows': lambda *unused: self._windows(),
                'AssertAuthorized': lambda name, argv, value: self._assert_authorized(argv),
                'Appshot': lambda name, argv, value: self._appshot(value),
                'Uia': lambda name, argv, value: self._affordances('', value['max_elements']),
            }
            provider = DiagnosticProvider(operation=operation, rest=rest, context=self.context, culture=self.culture,
                brief=brief, cache_seconds=self.cache_seconds, callbacks=callbacks,
                parent_deadline=self.parent_deadline, on_session=self._bind_session)
            return LegacyEffectSession(timeout_s=self.timeout_s, parent_cancelled=self.parent_cancelled).run('diagnostics', provider.startup(), Authority(), provider)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--operation', choices=sorted(OPERATIONS), required=True)
    parser.add_argument('--audit-directory', type=Path, required=True)
    parser.add_argument('--cache-directory', type=Path, required=True)
    parser.add_argument('--wrapper-log', type=Path, required=True)
    parser.add_argument('--changelog', type=Path, required=True)
    parser.add_argument('--temp-root', type=Path, required=True)
    parser.add_argument('--cli-path')
    parser.add_argument('--culture', default='en-US')
    parser.add_argument('--cache-seconds', type=int, default=2)
    parser.add_argument('--timeout-s', type=float, default=30)
    parser.add_argument('--brief', action='store_true')
    parser.add_argument('--stdin-argv', action='store_true')
    parser.add_argument('rest', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        rest = args.rest[1:] if args.rest[:1] == ['--'] else args.rest
        if args.stdin_argv:
            require(not rest, 'Typed diagnostic argv cannot be mixed with positional arguments.')
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, 'Diagnostic argv exceeds 1 MiB.')
            rest = parse_json(raw.decode('utf-8-sig'))
            require(type(rest) is list and all(type(item) is str for item in rest), 'Typed diagnostic argv must be strings.')
        context = dict(audit_directory=str(args.audit_directory.absolute()), cache_directory=str(args.cache_directory.absolute()),
            wrapper_log=str(args.wrapper_log.absolute()), cli_path=args.cli_path, changelog_path=str(args.changelog.absolute()),
            temp_root=str(args.temp_root.absolute()), benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')
        runtime = DiagnosticRuntime(context, culture=args.culture, timeout_s=args.timeout_s, cache_seconds=args.cache_seconds)
        result = runtime.run(args.operation, rest, brief=args.brief)
        if result['emit_json']:
            print(json.dumps(result['payload'], ensure_ascii=False, indent=2, allow_nan=False))
        elif result['brief'] is not None:
            print(result['brief'])
        return result['exit']
    except (OSError, ValueError, LegacyHostError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
