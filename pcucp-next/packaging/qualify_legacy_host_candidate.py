"""Bounded, opt-in CI qualification of the staged read-only legacy host.

Never promotes an adapter, edits a launcher, installs a tracer, changes security
settings or substitutes portable evidence for the actual Windows NativeHost.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASE_PATH = ROOT / 'tests/fixtures/legacy-host-candidate/cases.json'
ORIGINAL = 'bf895d3120dd5e145f360cb1c41e1d79a061d048'
MAX_PROCESS_BYTES = 4 * 1024 * 1024
sys.path[:0] = [str(ROOT / 'tests/python'), str(ROOT / 'pcucp-next/python')]
from helper_process_evidence import run_evidence, require_success


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contract():
    value = json.loads(CASE_PATH.read_text(encoding='utf-8'))
    if value.get('schema') != 'cucp.legacy-host-ci-cases/v1' or value.get('candidate_only') is not True:
        raise ValueError('Invalid candidate-only CI case contract')
    expected = {'host': 66, 'windows-safeguards': 20, 'orchestration': 36}
    for group, count in expected.items():
        ids = [name for values in value['groups'][group].values() for name in values]
        if len(ids) != count or len(set(ids)) != count:
            raise ValueError('CI case inventory drift; expected exact non-vacuous group ' + group)
    return value


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.success_ids = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.success_ids.append(test.id())


def validate_suite_report(report, *, target, group):
    expected = contract()
    ids = sorted(name for values in expected['groups'][group].values() for name in values)
    allowed = sorted(expected['allowed_skips'][target]) if group == 'host' else []
    if (report.get('schema') != 'cucp.legacy-host-ci-tests/v1' or report.get('target') != target or
            report.get('group') != group or report.get('test_ids') != ids or
            report.get('tests_run') != len(ids) or report.get('failures') or report.get('errors') or
            report.get('unexpected_successes') or report.get('expected_failures') or
            sorted(row['id'] for row in report.get('skipped', [])) != allowed or
            sorted(report.get('success_ids', [])) != sorted(set(ids) - set(allowed))):
        raise ValueError('Missing, skipped, failed or vacuous required candidate tests: ' + group)
    return report


def run_suite(target, group, destination):
    """Internal subprocess mode; caller supplies explicit platform/provider flags."""
    configured = contract()
    suites, ids = [], []
    for name, expected in configured['groups'][group].items():
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        actual = sorted(test.id() for test in flatten(suite))
        if actual != sorted(expected):
            raise ValueError('Required test IDs changed or failed to import: ' + name)
        suites.append(suite); ids.extend(actual)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult)
    result = runner.run(unittest.TestSuite(suites))
    report = dict(schema='cucp.legacy-host-ci-tests/v1', candidate_only=True, target=target, group=group,
        test_ids=sorted(ids), tests_run=result.testsRun, success_ids=sorted(result.success_ids),
        skipped=[dict(id=test.id(), reason=reason) for test, reason in result.skipped],
        failures=[dict(id=test.id(), detail=detail) for test, detail in result.failures],
        errors=[dict(id=test.id(), detail=detail) for test, detail in result.errors],
        unexpected_successes=[test.id() for test in result.unexpectedSuccesses],
        expected_failures=[test.id() for test, detail in result.expectedFailures])
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=True) + '\n')
    validate_suite_report(report, target=target, group=group)
    return 0


def validate_process_artifacts(directory, target):
    paths = sorted(directory.glob('*.json'))
    if len(paths) < 10 or len(paths) > 100:
        raise ValueError('Owned inner-process evidence count is missing or out of bounds')
    originals, host_entries, modes = [], [], set()
    for path in paths:
        if path.stat().st_size > 6 * 1024 * 1024:
            raise ValueError('Oversized process metadata')
        record = json.loads(path.read_text(encoding='utf-8'))
        for stream in ('stdout', 'stderr'):
            import base64
            raw = path.with_suffix('.' + stream + '.bin').read_bytes()
            if len(raw) > 2 * 1024 * 1024 or base64.b64decode(record[stream + '_base64'], validate=True) != raw:
                raise ValueError('Inner-process raw evidence changed or exceeds its bound')
            if record['bytes_observed'][stream] != len(raw) or record['truncated'][stream] is not False:
                raise ValueError('Incomplete inner-process raw stream')
        if (type(record.get('exit_code')) is not int or any(record.get(key) for key in
                ('running', 'launch_error', 'timed_out', 'kill_error', 'drain_incomplete', 'stdin_error', 'read_errors'))):
            raise ValueError('Nonterminal or failed inner-process capture')
        if any(str(arg).endswith('oracle.ps1') for arg in record['argv']):
            originals.append((record, path.with_suffix('.stdout.bin').read_bytes()))
        if 'pcucp_cli.legacy_host_entry' in record['argv']:
            host_entries.append(record)
            argv = record['argv']
            modes.add('typed-child' if '--typed-child' in argv else
                      'daemon' if any(argv[index:index+2] == ['daemon', 'serve'] for index in range(len(argv)-1)) else 'root')
    if len(host_entries) < 10 or modes != {'root', 'typed-child', 'daemon'}:
        raise ValueError('Production Python root/typed-child/daemon entries were not exercised non-vacuously')
    required = contract()['required_original_oracle_processes'] if target == 'windows' else 0
    if len(originals) != required or any(row['exit_code'] != 0 for row, raw in originals):
        raise ValueError('Original Windows brief oracle did not run exactly four successful comparisons')
    if target == 'windows':
        expected = {'ok release-notes notes=1 versions=2.3.4\n', 'ok release-notes notes=1 versions=1.0.0\n',
                    'ok release-notes notes=2 versions=2.3.4,1.0.0\n', 'ok release-notes notes=0 versions=\n'}
        observed = {raw.decode('utf-8-sig').replace('\r\n', '\n') for row, raw in originals}
        if observed != expected:
            raise ValueError('Original brief oracle output cases were missing or duplicated')
    return dict(process_count=len(paths), entry_count=len(host_entries), modes=sorted(modes), original_oracle_count=len(originals))


def validate_source_map(path):
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Missing or oversized retained production source map')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != 'cucp.migration-source-map/v1' or value.get('encoding') != 'utf-8-no-bom-lf':
        raise ValueError('Invalid production AST source-map schema')
    rows = value.get('files', [])
    files = {row['path']: row for row in rows}
    if len(files) != len(rows):
        raise ValueError('Duplicate source-map paths')
    from pcucp_cli.legacy_dispatch import load_contract
    frozen = load_contract().metadata
    required = [row for row in frozen['sources'] if row['path'].endswith('.ps1')]
    for row in required:
        if row['path'] not in files or files[row['path']]['sha256'] != row['sha256']:
            raise ValueError('Production AST source hash drift: ' + row['path'])
    extents = [row for row in frozen['extents'] if row['kind'] == 'function']
    for row in extents:
        matches = [item for item in files[row['path']]['functions']
                   if item['name'] == row['name'] and item['parent_function'] is None]
        if len(matches) != 1 or matches[0]['sha256'] != row['sha256']:
            raise ValueError('Production AST function extent drift: ' + row['name'])
    if len(required) != 8 or len(extents) != 123:
        raise ValueError('Unexpected production AST coverage count')
    return dict(required_sources=len(required), required_function_extents=len(extents), sha256=sha(path))


def _command(argv, destination, label, env, *, timeout=300, input_bytes=None):
    result = run_evidence([str(value) for value in argv], directory=destination, label=label,
        cwd=ROOT, env=env, timeout=timeout, limit=MAX_PROCESS_BYTES, input_bytes=input_bytes)
    print(result['evidence_path'], flush=True)
    print(result['stdout'].decode('utf-8', errors='replace')[-8192:], end='')
    print(result['stderr'].decode('utf-8', errors='replace')[-8192:], end='', file=sys.stderr)
    require_success(result)
    return result


def trace_modes(host, dotnet, tracer, destination, env):
    """Raw strace stderr is bounded/persisted before any parsing or assertion."""
    from legacy_host_trace import validate_trace
    result = []
    with tempfile.TemporaryDirectory(prefix='legacy-host-trace-owned-') as temp:
        path = Path(temp) / 'CHANGELOG.md'; path.write_bytes(b'## 3.2.1\n### Added\n- owned\n')
        owned_env = dict(env, PATH=str(dotnet.parent), CUCP_NATIVE_HOST=str(host))
        for name in ('powershell', 'powershell.exe', 'pwsh', 'sh', 'bash'):
            if shutil.which(name, path=owned_env['PATH']):
                raise ValueError('Trace PATH unexpectedly contains a shell: ' + name)
        for mode in contract()['trace_modes']:
            root = [sys.executable, '-m', 'pcucp_cli.legacy_host_entry', '--staged-brief-host', '--brief', '--changelog', str(path)]
            stdin = None
            if mode == 'typed-child':
                root += ['--typed-child']
                stdin = json.dumps(dict(schema='cucp.legacy-python-child/v1', argv=['macro', 'release-notes'],
                    live=False, quiet=True, brief=True, confirm_sensitive=False)).encode('utf-8')
            elif mode == 'daemon':
                root += ['--', 'macro', 'daemon', 'serve', '--max-commands', '1']
                stdin = b'{"id":"owned-trace","macro":"release-notes","args":[]}\n'
            else:
                root += ['--', 'macro', 'release-notes']
            evidence = _command([tracer, '-f', '-q', '-e', 'trace=process', '-s', '4096', *root],
                destination, 'trace-' + mode, owned_env, timeout=30, input_bytes=stdin)
            output = evidence['stdout'].decode('utf-8')
            if mode == 'daemon':
                lines = output.splitlines()
                import re
                if (len(lines) != 4 or json.loads(lines[0]).get('protocol') != 'sentinel' or
                        lines[1] != '<<<CUCP-RESP id=owned-trace>>>' or lines[2] != 'ok release-notes notes=1 versions=3.2.1' or
                        re.fullmatch(r'<<<CUCP-END id=owned-trace exit=0 ms=\d+>>>', lines[3]) is None):
                    raise ValueError('Traced daemon did not produce the exact owned result')
            elif output != 'ok release-notes notes=1 versions=3.2.1\n':
                raise ValueError('Traced entry did not produce the exact owned result')
            proof = validate_trace(evidence['stderr'], expected_python=sys.executable,
                expected_dotnet=str(dotnet), expected_dll=str(host), mode=mode, expected_root_argv=root)
            proof['raw_evidence'] = Path(evidence['evidence_path']).name
            result.append(proof)
    if len(result) != 3:
        raise ValueError('Missing root/typed-child/daemon process traces')
    return result


def check_options(args):
    if not args.candidate_only:
        raise ValueError('The explicit --candidate-only gate is required')
    if args.target == 'linux':
        if not sys.platform.startswith('linux') or not args.require_process_trace or args.require_windows_oracle:
            raise ValueError('Linux gate requires actual Linux and --require-process-trace only')
    elif sys.platform != 'win32' or not args.require_windows_oracle or args.require_process_trace:
        raise ValueError('Windows gate requires actual Windows and --require-windows-oracle only')


def run(args):
    check_options(args)
    owned_logs = ROOT.resolve() / '.migration-logs'
    destination = args.log_dir.resolve()
    if owned_logs.is_symlink() or not destination.is_relative_to(owned_logs) or destination.exists():
        raise ValueError('Use a fresh owned directory under this checkout .migration-logs')
    destination.mkdir(parents=True)
    report_path = destination / 'qualification.json'
    report = dict(schema='cucp.legacy-host-candidate-qualification/v1', candidate_only=True,
        production_cutover=False, target=args.target, status='running', trace_required=args.require_process_trace,
        windows_oracle_required=args.require_windows_oracle, errors=[])
    def save():
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    save()
    try:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith('CUCP_')}
        env.update(PYTHONPATH=str(ROOT / 'pcucp-next/python'), PYTHONIOENCODING='utf-8',
                   PYTHONDONTWRITEBYTECODE='1', DOTNET_ROLL_FORWARD='LatestPatch')
        dotnet_name = shutil.which('dotnet.exe' if args.target == 'windows' else 'dotnet')
        if not dotnet_name:
            raise ValueError('Required official .NET SDK executable is missing')
        dotnet = Path(dotnet_name).absolute()
        commit = _command(['git', 'rev-parse', 'HEAD'], destination, 'commit', env)['stdout'].decode().strip()
        tree = _command(['git', 'rev-parse', 'HEAD^{tree}'], destination, 'tree', env)['stdout'].decode().strip()
        clean = _command(['git', 'status', '--porcelain', '--untracked-files=all'], destination, 'source-state', env)['stdout']
        if clean.strip():
            raise ValueError('Qualification requires a clean concrete source commit')
        from pcucp_cli.legacy_dispatch import assert_frozen_sources
        assert_frozen_sources(ROOT)
        report.update(commit=commit, tree=tree, python=sys.version, platform=platform.platform(),
            case_manifest_sha256=sha(CASE_PATH), frozen_dispatch_sha256=sha(ROOT / 'docs/legacy-dispatch-contract.json'))
        _command([dotnet, '--info'], destination, 'dotnet-info', env)
        project_name = 'PcuCp.NativeHost' if args.target == 'windows' else 'PcuCp.LegacyHost.Qualification'
        project = ROOT / 'pcucp-next/dotnet' / project_name
        _command([dotnet, 'build', project, '-c', 'Release', '--no-incremental', '-warnaserror', '-m:1', '-p:UseSharedCompilation=false'],
                 destination, 'host-build', env, timeout=300)
        framework = 'net8.0-windows10.0.19041.0' if args.target == 'windows' else 'net8.0'
        host = project / 'bin/Release' / framework / (project_name + '.dll')
        runtime_config = host.with_suffix('.runtimeconfig.json')
        runtime_options = json.loads(runtime_config.read_text())['runtimeOptions']
        frameworks = runtime_options.get('frameworks', [runtime_options.get('framework', {})])
        expected_frameworks = {'Microsoft.NETCore.App', 'Microsoft.WindowsDesktop.App'} if args.target == 'windows' else {'Microsoft.NETCore.App'}
        if ({row.get('name') for row in frameworks} != expected_frameworks or
                any(not row.get('version', '').startswith('8.0.') for row in frameworks) or
                runtime_options.get('rollForward') not in (None, 'LatestPatch')):
            raise ValueError('Candidate host must bind the actual .NET8 runtime family')
        report.update(host_path=str(host.relative_to(ROOT)), host_sha256=sha(host),
            runtimeconfig_sha256=sha(runtime_config), runtime_options=runtime_options,
            dotnet_roll_forward='LatestPatch', source_files={})
        sources = [CASE_PATH, Path(__file__), *list((ROOT / 'pcucp-next/python/pcucp_cli').glob('legacy_host*.py')),
                   ROOT / 'pcucp-next/python/pcucp_cli/legacy_dispatch.py', ROOT / 'tests/python/legacy_host_trace.py',
                   ROOT / 'tests/python/helper_process_evidence.py', ROOT / 'tests/python/test_legacy_host_owned.py',
                   ROOT / 'tests/python/test_legacy_host_protocol.py', ROOT / 'tests/python/test_legacy_host_trace.py',
                   ROOT / 'tests/python/test_legacy_host_candidate_qualification.py',
                   ROOT / 'tests/python/test_legacy_dispatch_contract.py', ROOT / 'tests/python/test_legacy_dispatch_refresh.py',
                   ROOT / '.github/workflows/legacy-host-candidate.yml']
        report['source_files'] = {str(path.relative_to(ROOT)): sha(path) for path in sources}
        env['CUCP_LEGACY_HOST_TEST_NATIVE' if args.target == 'windows' else 'CUCP_LEGACY_HOST_TEST_PORTABLE'] = str(host)
        inner = destination / 'owned-processes'
        env['CUCP_LEGACY_HOST_PROCESS_EVIDENCE'] = str(inner)
        if args.target == 'linux':
            tracer = shutil.which('strace')
            if not tracer or Path(tracer).resolve() != Path('/usr/bin/strace').resolve():
                raise ValueError('Required preinstalled /usr/bin/strace is unavailable; no trace qualification')
            report['tracer'] = dict(path=tracer, sha256=sha(tracer))
            _command([tracer, '--version'], destination, 'tracer-version', env)
            env['CUCP_LEGACY_HOST_TRACE'] = '1'
            report['traces'] = trace_modes(host, dotnet, tracer, destination, env)
        else:
            for shell in ('powershell.exe', 'pwsh.exe'):
                if not shutil.which(shell):
                    raise ValueError('Required Windows shell missing for unchanged oracles: ' + shell)
            _command(['git', 'cat-file', '-e', ORIGINAL + ':scripts/cucp.ps1'], destination, 'original-source', env)
            env['CUCP_EXECUTION_STARTUP_TEST_HOST'] = str(host)
        suites = ['orchestration', 'host', 'windows-safeguards'] if args.target == 'windows' else ['orchestration', 'host']
        report['suites'] = {}
        for group in suites:
            output = destination / (group + '.tests.json')
            _command([sys.executable, __file__, '--candidate-only', '--target', args.target,
                '--require-windows-oracle' if args.target == 'windows' else '--require-process-trace',
                '--internal-suite', group, '--suite-report', output], destination, group + '-tests', env, timeout=900)
            report['suites'][group] = validate_suite_report(json.loads(output.read_text()), target=args.target, group=group)
        report['owned_processes'] = validate_process_artifacts(inner, args.target)
        if args.target == 'windows':
            _command(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                ROOT / 'tests/fixtures/migration-source-map.ps1', '-Root', ROOT,
                '-OutputPath', destination / 'source-map.json'], destination, 'production-source-map', env, timeout=180)
            report['production_ast_source_map'] = validate_source_map(destination / 'source-map.json')
        final_state = _command(['git', 'status', '--porcelain', '--untracked-files=all'], destination, 'final-source-state', env)['stdout']
        if final_state.strip() or sha(host) != report['host_sha256']:
            raise ValueError('Source or qualified host changed during the candidate gate')
        report['status'] = 'passed-candidate-only'
        save()
        return 0
    except BaseException as error:
        report['status'] = 'failed-unqualified'
        report['errors'].append(type(error).__name__ + ': ' + str(error))
        save()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--candidate-only', action='store_true', required=True)
    parser.add_argument('--target', choices=('linux', 'windows'), required=True)
    parser.add_argument('--require-process-trace', action='store_true')
    parser.add_argument('--require-windows-oracle', action='store_true')
    parser.add_argument('--log-dir', type=Path)
    parser.add_argument('--internal-suite', choices=('host', 'windows-safeguards', 'orchestration'), help=argparse.SUPPRESS)
    parser.add_argument('--suite-report', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    check_options(args)
    if args.internal_suite:
        if args.suite_report is None or args.internal_suite == 'windows-safeguards' and args.target != 'windows':
            parser.error('Invalid internal candidate suite report')
        owned_logs = ROOT.resolve() / '.migration-logs'
        report_path = args.suite_report.resolve()
        if owned_logs.is_symlink() or not report_path.is_relative_to(owned_logs) or not report_path.parent.is_dir() or report_path.exists():
            parser.error('Internal suite requires a fresh report inside owned .migration-logs')
        return run_suite(args.target, args.internal_suite, report_path)
    if args.suite_report:
        parser.error('--suite-report requires an internal suite')
    args.log_dir = args.log_dir or ROOT / '.migration-logs/legacy-host-candidate' / args.target
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
