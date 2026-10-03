"""Source-entry, typed child and daemon proof; only owned files/loopback fixtures.

CUCP_LEGACY_HOST_TEST_NATIVE chooses the actual Windows NativeHost when present.
CUCP_LEGACY_HOST_TEST_PORTABLE chooses the source-linked portable proof fixture.
Neither is silently auto-built or substituted by production code.
"""
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_host import (HostOptions, LegacyHost, ReleaseNotesProvider, _legacy_lines, READ_ONLY_CDP)
from pcucp_cli.legacy_host_protocol import Authority, Effect, LegacyHostError, wire
from pcucp_cli.legacy_host_entry import serve
from test_cdp import server

NATIVE = os.environ.get('CUCP_LEGACY_HOST_TEST_NATIVE')
PORTABLE = os.environ.get('CUCP_LEGACY_HOST_TEST_PORTABLE')
SELECTED = NATIVE or PORTABLE


def _owned_run(command, **kwargs):
    """Optional candidate-CI raw evidence, without changing command/oracle bytes."""
    directory = os.environ.get('CUCP_LEGACY_HOST_PROCESS_EVIDENCE')
    if not directory:
        return subprocess.run(command, **kwargs)
    from helper_process_evidence import run_evidence, require_success
    text = kwargs.pop('text', False)
    encoding = kwargs.pop('encoding', 'utf-8')
    raw = kwargs.pop('input', None)
    if isinstance(raw, str):
        raw = raw.encode(encoding)
    kwargs.pop('capture_output', None)
    label = 'original-brief' if any(str(value).endswith('oracle.ps1') for value in command) else 'host-process'
    result = run_evidence(command, directory=directory, label=label, input_bytes=raw,
                          limit=2 * 1024 * 1024, **kwargs)
    # Expected negative application exits remain the existing test's assertion;
    # a launch/timeout/truncation/pipe failure is never an expected negative exit.
    if type(result['exit_code']) is not int:
        raise AssertionError('Owned process has no terminal exit: ' + result['evidence_path'])
    require_success(result, expected_exit=result['exit_code'])
    out, err = result['stdout'], result['stderr']
    if text:
        out, err = out.decode(encoding), err.decode(encoding)
    return subprocess.CompletedProcess(command, result['exit_code'], out, err)


def child(argv, **kwargs):
    return dict(schema='cucp.legacy-python-child/v1', argv=argv, live=False, quiet=True,
                brief=True, confirm_sensitive=False, **kwargs)


def entry(rest, *, endpoint=None, changelog=None, stdin='', typed=False, extra=(), native=SELECTED):
    env = {key: value for key, value in os.environ.items() if not key.startswith('CUCP_')}
    env['PYTHONPATH'] = str(ROOT / 'pcucp-next/python')
    if native:
        env['CUCP_NATIVE_HOST'] = native
    command = [sys.executable, '-m', 'pcucp_cli.legacy_host_entry', '--staged-brief-host', '--brief']
    if endpoint:
        command += ['--cdp-endpoint', endpoint]
    if changelog:
        command += ['--changelog', str(changelog)]
    if typed:
        command += ['--typed-child']
    command += list(extra)
    if rest:
        command += ['--', *rest]
    return _owned_run(command, input=stdin, capture_output=True, text=True, encoding='utf-8', env=env, timeout=15)


class HostBoundaryTests(unittest.TestCase):
    def options(self, endpoint='http://127.0.0.1:9'):
        return HostOptions(str(ROOT / 'CHANGELOG.md'), endpoint)

    def test_every_unavailable_registered_macro_fails_before_acquisition(self):
        from pcucp_cli.legacy_dispatch import load_contract
        with patch('pcucp_cli.legacy_host.LegacyCdpAdapter') as adapter, patch('pcucp_cli.legacy_host.LegacyEffectSession') as kernel:
            host = LegacyHost(self.options(), Authority(True, True))
            try:
                for row in load_contract().clauses:
                    if row.name in READ_ONLY_CDP | {'release-notes'} or row.implementation == 'not_implemented':
                        continue
                    with self.subTest(macro=row.name), self.assertRaisesRegex(LegacyHostError, 'unqualified_surface'):
                        host.invoke(['macro', row.name], brief=True)
            finally:
                host.close()
            adapter.assert_not_called(); kernel.assert_not_called()

    def test_default_format_and_unknown_are_distinct_from_not_implemented(self):
        host = LegacyHost(self.options())
        try:
            with self.assertRaisesRegex(LegacyHostError, 'JSON formatting'):
                host.invoke(['macro', 'cdp-detect'], brief=False)
            with self.assertRaisesRegex(LegacyHostError, 'Unknown macro:'):
                host.invoke(['macro', 'unregistered'], brief=True)
            self.assertEqual(host.invoke(['macro', 'notify'], brief=True), (1, 'not_implemented notify\n'))
        finally:
            host.close()

    def test_typed_child_cannot_forge_ceiling_or_object_flags(self):
        host = LegacyHost(self.options())
        for changes in ({'live': True}, {'confirm_sensitive': True}, {'live': 'true'},
                        {'quiet': 1}, {'brief': 'true'}, {'script': 'arbitrary'}, {'argv': [True]}):
            request = {**child(['macro', 'notify']), **changes}
            with self.subTest(changes=changes), self.assertRaises(LegacyHostError):
                host.typed_child(request)
        host.close()

    def test_closed_host_cannot_restart_or_create_provider(self):
        host = LegacyHost(self.options()); host.close()
        with patch('pcucp_cli.legacy_host.LegacyCdpAdapter') as adapter:
            with self.assertRaisesRegex(LegacyHostError, 'closed'):
                host.invoke(['macro', 'cdp-detect'], brief=True)
            adapter.assert_not_called()

    def test_text_boundary_bom_empty_lines_and_unicode_separator(self):
        for raw, expected in [(b'', []), (b'a\r\nb\rc\n', ['a', 'b', 'c']), (b'\n', ['']),
                              ('a\u2028b'.encode('utf-8-sig'), ['a\u2028b']),
                              ('한글\n'.encode('utf-16'), ['한글'])]:
            self.assertEqual(_legacy_lines(raw), expected)
        if os.name != 'nt':
            with self.assertRaisesRegex(LegacyHostError, 'explicit BOM'):
                _legacy_lines('한글'.encode('utf-8'))

    def test_provider_exact_order_path_and_count(self):
        with tempfile.TemporaryDirectory(prefix='legacy-provider-') as root:
            path = Path(root) / 'CHANGELOG.md'; path.write_bytes(b'## 1.0.0\n')
            provider = ReleaseNotesProvider(HostOptions(str(path)))
            def effect(name, value):
                return Effect.decode(dict(kind='Diagnostic', name=name, argv=[],
                    data=wire(dict(name='', value=value)), live=False, quiet=False, brief=False,
                    confirm_sensitive=False), Authority())
            with self.assertRaises(LegacyHostError): provider.validate(effect('ReadLines', str(path)))
            with self.assertRaises(LegacyHostError): provider.validate(effect('ResolvePath', str(path) + '.other'))
            resolved = provider.dispatch(effect('ResolvePath', str(path)))
            with self.assertRaises(LegacyHostError): provider.validate(effect('ResolvePath', str(path)))
            self.assertEqual(provider.dispatch(effect('ReadLines', resolved)), ['## 1.0.0'])
            with self.assertRaises(LegacyHostError): provider.validate(effect('ReadLines', resolved))

    def test_provider_rejects_non_regular_and_replaced_files_before_read(self):
        with tempfile.TemporaryDirectory(prefix='legacy-identity-') as root:
            path = Path(root) / 'CHANGELOG.md'; path.write_bytes(b'## 1.0.0\n')
            def effect(name):
                return Effect.decode(dict(kind='Diagnostic', name=name, argv=[],
                    data=wire(dict(name='', value=str(path))), live=False, quiet=False, brief=False,
                    confirm_sensitive=False), Authority())
            provider = ReleaseNotesProvider(HostOptions(str(path)))
            provider.dispatch(effect('ResolvePath'))
            replacement = Path(root) / 'replacement'; replacement.write_bytes(b'## 2.0.0\n')
            os.replace(replacement, path)
            with self.assertRaisesRegex(LegacyHostError, 'identity changed'):
                provider.dispatch(effect('ReadLines'))
            if hasattr(os, 'mkfifo'):
                fifo = Path(root) / 'fifo'; os.mkfifo(fifo)
                provider = ReleaseNotesProvider(HostOptions(str(fifo)))
                changed = effect('ResolvePath')
                changed.data['value'] = str(fifo)
                with self.assertRaisesRegex(LegacyHostError, 'regular changelog'):
                    provider.dispatch(changed)

    def test_in_process_typed_reentry_retains_one_cdp_adapter_and_cache(self):
        with server() as (state, endpoint):
            port = str(state.port)
            host = LegacyHost(self.options(endpoint))
            try:
                with patch.object(host._port_cache, 'check', wraps=host._port_cache.check) as check:
                    first = host.invoke(['macro', 'cdp-detect', '--port', port], brief=True)
                    adapter = host._cdp
                    second = host.typed_child(child(['macro', 'CDP-DETECT', '--port', port, '--label', '-AllowLiveControl']))
                    self.assertEqual(first, second)
                    self.assertIs(host._cdp, adapter)
                    self.assertEqual(check.call_count, 2)
                    self.assertEqual(len(host._port_cache._entries), 1)
                    self.assertFalse(adapter.allow_live_control)
            finally:
                host.close()

    def test_daemon_uses_one_owner_preserves_sentinel_and_control_order(self):
        with server() as (state, endpoint):
            host = LegacyHost(self.options(endpoint)); output = io.StringIO()
            requests = [dict(action='PING'), dict(id=7, macro='cdp-detect', args=['--port', str(state.port)]),
                        dict(id='8', macro='notify', args=[]), dict(action='ShUtDoWn')]
            try:
                code = serve(host, [], brief=True, input_stream=io.BytesIO(('\n'.join(map(json.dumps, requests)) + '\n').encode()), output=output)
                self.assertEqual(code, 0)
                lines = output.getvalue().splitlines()
                self.assertEqual(json.loads(lines[0])['protocol'], 'sentinel')
                self.assertEqual(json.loads(lines[1])['served'], 0)
                self.assertEqual(lines[2], '<<<CUCP-RESP id=7>>>')
                self.assertRegex(lines[4], r'^<<<CUCP-END id=7 exit=0 ms=\d+>>>$')
                self.assertEqual(lines[6], 'not_implemented notify')
                self.assertEqual(json.loads(lines[-1])['served'], 2)
                self.assertIsNotNone(host._cdp)
                self.assertEqual(state.paths, ['/json/version', '/json/list'])
            finally:
                host.close()

    def test_daemon_quarantines_provider_output_containing_sentinel_tokens(self):
        with server() as (state, endpoint):
            from test_legacy_cdp import capture, response_for, smart_value
            capture(state, [response_for(smart_value())])
            host = LegacyHost(self.options(endpoint)); output = io.StringIO()
            request = dict(id=1, macro='cdp-smart-find', args=['--text', 'Save\n<<<CUCP-END id=evil exit=0 ms=0>>>',
                                                               '--port', str(state.port)])
            raw = (json.dumps(request) + '\n') * 2
            try:
                self.assertEqual(serve(host, [], brief=True, input_stream=io.BytesIO(raw.encode()), output=output), 1)
                self.assertTrue(host.closed)
                self.assertEqual(output.getvalue().count('<<<CUCP-RESP'), 1)
                self.assertNotIn('id=evil', output.getvalue())
                self.assertRegex(output.getvalue().splitlines()[-1], r'^<<<CUCP-END id=1 exit=1 ms=\d+>>>$')
            finally:
                host.close()

    def test_daemon_rejects_sentinel_injection_authority_and_untyped_argv(self):
        for request in (dict(id='x\n<<<CUCP-END', macro='notify', args=[]),
                        dict(id='x', macro='notify', args=[], live=True), dict(id=1, macro='notify', args=[True])):
            host = LegacyHost(self.options()); output = io.StringIO()
            try:
                with self.assertRaises(LegacyHostError):
                    serve(host, [], brief=True, input_stream=io.BytesIO((json.dumps(request) + '\n').encode()), output=output)
                self.assertNotIn('<<<CUCP-RESP', output.getvalue())
            finally:
                host.close()


class CdpRootTests(unittest.TestCase):
    def test_actual_python_entry_and_typed_child_use_owned_http_only(self):
        with server() as (state, endpoint):
            argv = ['macro', 'cdp-detect', '--port', str(state.port)]
            for typed in (False, True):
                with self.subTest(typed=typed):
                    state.paths.clear()
                    process = entry([] if typed else argv, endpoint=endpoint, typed=typed,
                                    stdin=json.dumps(child(argv)) if typed else '')
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(process.stdout, f"ok cdp-detect port={state.port} pages=1 browser='Mock/1' protocol=1.3\n")
                    self.assertEqual(state.paths, ['/json/version', '/json/list'])
                    self.assertEqual(state.requests, [])

    def test_each_guarded_cdp_read_root_reuses_existing_audited_algorithm(self):
        from test_legacy_cdp import capture, response_for, smart_value
        cases = [('cdp-smart-find', '--text', smart_value()),
                 ('cdp-smart-type-find', '--label', smart_value()),
                 ('cdp-deep-find', '--text', dict(traversal=dict(shadow_roots_seen=0, iframes_seen=0),
                    found_count=1, top_matches=[]))]
        for name, option, value in cases:
            with self.subTest(name=name), server() as (state, endpoint):
                capture(state, [response_for(value)])
                process = entry(['macro', name, option, 'Save', '--port', str(state.port)], endpoint=endpoint)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertTrue(process.stdout.startswith('ok ' + name + ' '), process.stdout)
                self.assertEqual(len(state.requests), 1)
                self.assertEqual(state.requests[0]['method'], 'Runtime.evaluate')
                self.assertIs(state.requests[0]['params']['throwOnSideEffect'], True)
                self.assertFalse(state.requests[0]['params'].get('awaitPromise', False))

    def test_signal_while_transport_lock_is_held_unwinds_before_cleanup(self):
        script = r"""
import signal
from unittest.mock import patch
from pcucp_cli.legacy_host_entry import main
def interrupted(adapter, macro, **kwargs):
    with adapter._transport._wire_lock:
        signal.raise_signal(signal.SIGTERM)
with patch('pcucp_cli.legacy_host.execute_macro', interrupted):
    raise SystemExit(main(['--staged-brief-host','--brief','--','macro','cdp-detect']))
"""
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'pcucp-next/python'))
        process = _owned_run([sys.executable, '-c', script], env=env, capture_output=True,
                                 text=True, timeout=3)
        self.assertEqual(process.returncode, 130, process.stderr)
        self.assertIn('cancelled; action not retried', process.stderr)

    def test_duplicate_startup_options_fail_before_provider_acquisition(self):
        with server() as (state, endpoint):
            process = entry(['macro', 'cdp-detect', '--port', str(state.port)], endpoint=endpoint,
                            extra=('--allow-live-control', '--allow-live-control'))
            self.assertEqual(process.returncode, 2)
            self.assertIn('duplicate startup option', process.stderr)
            self.assertEqual(state.paths, [])

    def test_actual_process_rejects_request_authority_before_network(self):
        with server() as (state, endpoint):
            request = child(['macro', 'cdp-detect', '--port', str(state.port)])
            request['live'] = True
            process = entry([], endpoint=endpoint, typed=True, stdin=json.dumps(request))
            self.assertEqual(process.returncode, 1)
            self.assertEqual(state.paths, [])
            self.assertIn('immutable live', process.stderr)

    def test_daemon_big_integer_or_duplicate_options_fail_before_ready(self):
        for rest in (['--max-commands', str(2**31)], ['--max-commands', '1', '--max-commands', '2']):
            process = entry(['macro', 'daemon', 'serve', *rest])
            self.assertEqual(process.returncode, 2)
            self.assertEqual(process.stdout, '')

    def test_actual_daemon_process_preserves_existing_envelopes(self):
        with server() as (state, endpoint):
            request = dict(id='owned-1', macro='cdp-detect', args=['--port', str(state.port)])
            process = entry(['macro', 'daemon', 'serve', '--max-commands', '1'], endpoint=endpoint,
                            stdin=json.dumps(request) + '\n')
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout.splitlines()[0])['schema'], 'cucp.daemon-serve/v1')
            self.assertIn('<<<CUCP-RESP id=owned-1>>>\n', process.stdout)
            self.assertRegex(process.stdout, r'<<<CUCP-END id=owned-1 exit=0 ms=\d+>>>\n$')


@unittest.skipUnless(SELECTED, 'Set an explicit native or portable qualification host; never silently substitute')
class KernelOwnedTests(unittest.TestCase):
    def test_actual_root_kernel_owned_file_output_and_filters(self):
        with tempfile.TemporaryDirectory(prefix='legacy-root-owned-') as root:
            path = Path(root) / 'CHANGELOG.md'
            path.write_text('## 2.1.0\n### Added\n- owned one\n## 1.0.0\n### Fixed\n- owned two\n', encoding='utf-8-sig')
            for args, expected in (([], 'notes=1 versions=2.1.0'), (['--version', '1.0.0'], 'notes=1 versions=1.0.0'),
                                   (['--since', '1.0.0'], 'notes=2 versions=2.1.0,1.0.0')):
                with self.subTest(args=args):
                    process = entry(['macro', 'release-notes', *args], changelog=path)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(process.stdout, 'ok release-notes ' + expected + '\n')

    def test_actual_typed_child_and_daemon_reenter_same_root_contract(self):
        with tempfile.TemporaryDirectory(prefix='legacy-child-owned-') as root:
            path = Path(root) / 'CHANGELOG.md'; path.write_bytes(b'## 1.2.3\n### Added\n- owned\n')
            process = entry([], changelog=path, typed=True, stdin=json.dumps(child(['macro', 'release-notes', '--version', '-AllowLiveControl'])))
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, 'ok release-notes notes=0 versions=\n')
            request = json.dumps(dict(id=1, macro='release-notes', args=[])) + '\n'
            process = entry(['macro', 'daemon', 'serve', '--max-commands', '2'], changelog=path, stdin=request * 2)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.count('ok release-notes notes=1 versions=1.2.3\n'), 2)

    def test_missing_file_failure_is_terminal_without_claiming_mutation(self):
        with tempfile.TemporaryDirectory(prefix='legacy-missing-owned-') as root:
            path = Path(root) / 'missing.md'
            request = json.dumps(dict(id=1, macro='release-notes', args=[])) + '\n'
            process = entry(['macro', 'daemon', 'serve'], changelog=path, stdin=request * 2)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(process.stdout.count('<<<CUCP-RESP'), 1)
            self.assertIn('CHANGELOG.md not found', process.stdout)
            self.assertIn('"mutation_may_have_occurred":false', process.stdout)

    def test_source_entry_runs_with_powershell_absent_from_path(self):
        with tempfile.TemporaryDirectory(prefix='legacy-no-ps-owned-') as root:
            path = Path(root) / 'CHANGELOG.md'; path.write_bytes(b'## 3.2.1\n')
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'pcucp-next/python'), CUCP_NATIVE_HOST=SELECTED)
            env['PATH'] = str(Path(shutil.which('dotnet')).parent)
            self.assertIsNone(shutil.which('powershell', path=env['PATH']))
            self.assertIsNone(shutil.which('powershell.exe', path=env['PATH']))
            self.assertIsNone(shutil.which('pwsh', path=env['PATH']))
            process = _owned_run([sys.executable, '-m', 'pcucp_cli.legacy_host_entry',
                '--staged-brief-host', '--brief', '--changelog', str(path), '--', 'macro', 'release-notes'],
                env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, 'ok release-notes notes=1 versions=3.2.1\n')

    @unittest.skipUnless(os.environ.get('CUCP_LEGACY_HOST_TRACE') == '1' and sys.platform.startswith('linux') and shutil.which('strace'), 'Explicit process-tracing gate; ptrace may be unavailable')
    def test_real_source_entry_has_no_powershell_execution_or_lookup(self):
        with tempfile.TemporaryDirectory(prefix='legacy-exec-trace-') as root:
            path = Path(root) / 'CHANGELOG.md'; path.write_bytes(b'## 3.2.1\n')
            trace = Path(root) / 'exec.trace'
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'pcucp-next/python'), CUCP_NATIVE_HOST=SELECTED)
            # Python and dotnet are absolute/known. No powershell executable is on PATH.
            env['PATH'] = str(Path(shutil.which('dotnet')).parent)
            self.assertIsNone(shutil.which('powershell', path=env['PATH']))
            self.assertIsNone(shutil.which('powershell.exe', path=env['PATH']))
            command = [shutil.which('strace'), '-f', '-e', 'trace=process', '-o', str(trace), sys.executable,
                       '-m', 'pcucp_cli.legacy_host_entry', '--staged-brief-host', '--brief', '--changelog', str(path),
                       '--', 'macro', 'release-notes']
            process = _owned_run(command, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, 'ok release-notes notes=1 versions=3.2.1\n')
            executed = [line for line in trace.read_text().splitlines() if 'execve(' in line]
            self.assertEqual(len(executed), 2, executed)
            self.assertIn('legacy_host_entry', executed[0])
            self.assertIn('dotnet', executed[1])
            self.assertFalse(any(re.search(r'powershell|pwsh|/bin/sh|/bin/bash', line, re.I) for line in executed))


@unittest.skipUnless(sys.platform == 'win32' and NATIVE, 'Actual Windows NativeHost and original PowerShell oracle gate')
class WindowsOriginalBriefTests(unittest.TestCase):
    def test_original_release_notes_brief_and_exit_match_new_root(self):
        baseline = 'bf895d3120dd5e145f360cb1c41e1d79a061d048'
        original = subprocess.check_output(['git', 'show', baseline + ':scripts/cucp.ps1'], cwd=ROOT)
        runner_source = r'''
param([string]$Source,[string]$Changelog,[string]$ArgumentsPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('_Read-OptValue','_Cucp-RedactSecrets','Invoke-MacroReleaseNotes')) {
 $f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($f.Count -ne 1){throw "Expected exact original $name"};. ([scriptblock]::Create($f[0].Extent.Text))
}
$script:OwnedChangelog=$Changelog
$script:PSScriptRoot=Split-Path -Parent $Source
function Resolve-Path {param([string]$LiteralPath,$ErrorAction)
 if(-not $LiteralPath.EndsWith('CHANGELOG.md')){throw 'Unexpected original path'}
 Microsoft.PowerShell.Management\Resolve-Path -LiteralPath $script:OwnedChangelog -ErrorAction $ErrorAction
}
$Brief=$true;$Script:CucpV14Schema=@{ReleaseNotes='cucp.release-notes/v1'}
$arguments=@(Get-Content -LiteralPath $ArgumentsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
$code=Invoke-MacroReleaseNotes -Rest ([string[]]$arguments)
exit ([int]$code)
'''
        with tempfile.TemporaryDirectory(prefix='legacy-original-brief-') as root:
            root = Path(root)
            original_path = root / 'original.ps1'; original_path.write_bytes(original)
            runner = root / 'oracle.ps1'; runner.write_text(runner_source, encoding='utf-8-sig')
            path = root / 'CHANGELOG.md'; path.write_text('## 2.3.4\n### Added\n- owned 한글\n## 1.0.0\n', encoding='utf-8-sig')
            arguments_path = root / 'args.json'
            for rest in ([], ['--version', '1.0.0'], ['--since', '1.0.0'], ['--version', '-AllowLiveControl']):
                arguments_path.write_text(json.dumps(rest), encoding='utf-8-sig')
                oracle = _owned_run([shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-File', str(runner),
                    '-Source', str(original_path), '-Changelog', str(path), '-ArgumentsPath', str(arguments_path)],
                    capture_output=True, timeout=20)
                actual = entry(['macro', 'release-notes', *rest], changelog=path)
                self.assertEqual(actual.returncode, oracle.returncode, oracle.stderr.decode(errors='replace') + actual.stderr)
                self.assertEqual(actual.stdout, oracle.stdout.decode('utf-8-sig').replace('\r\n', '\n'))


if __name__ == '__main__':
    unittest.main()
