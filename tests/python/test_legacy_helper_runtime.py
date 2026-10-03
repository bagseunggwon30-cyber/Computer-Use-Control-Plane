"""Staged concrete adapters. Windows-only methods never enable desktop providers."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli import legacy_helper_runtime as runtime
from pcucp_cli.legacy_helper_client import LockSnapshot, inspect_lock


def package(root):
    wanted = dict(schema='cucp.legacy-helper-package/v1', status='staged-unqualified', helper_version='2.0.0',
        runtime='net48', runtime_dependencies=['Windows', '.NET Framework 4.8'], entrypoint=runtime.REQUIRED_FILES[0], files={})
    for name in runtime.REQUIRED_FILES:
        data = ('test-only-inert-' + name).encode()
        (root / name).write_bytes(data)
        wanted['files'][name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    (root / 'manifest.json').write_text(json.dumps(wanted))
    return wanted


class StagedPackageRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.manifest = package(self.root)

    def test_exact_package_validates_without_executing(self):
        self.assertEqual(runtime.validate_package(self.root), self.manifest)

    def test_tamper_and_missing_artifact_fail_before_authority(self):
        (self.root / runtime.REQUIRED_FILES[0]).write_bytes(b'mismatch')
        with patch.object(runtime, 'WindowsAuthority') as authority:
            with self.assertRaises(ValueError): runtime.StagedHelperRuntime(self.root, self.root / 'lock')
            authority.assert_not_called()

    def test_extra_payload_rejected(self):
        (self.root / 'evil.exe').write_bytes(b'x')
        with self.assertRaises(ValueError): runtime.validate_package(self.root)

    def test_wrong_status_runtime_and_file_inventory_rejected(self):
        for key, value in [('status', 'qualified'), ('runtime', 'net8'), ('files', {}), ('entrypoint', '../evil.exe')]:
            with self.subTest(key=key):
                (self.root / 'manifest.json').write_text(json.dumps(dict(self.manifest, **{key: value})))
                with self.assertRaises(ValueError): runtime.validate_package(self.root)

    def test_duplicate_and_oversized_manifest_rejected(self):
        for data in ('{"schema":1,"schema":2}', ' ' * 16385):
            (self.root / 'manifest.json').write_text(data)
            with self.assertRaises(ValueError): runtime.validate_package(self.root)

    def test_snapshot_roundtrip_and_strict_types(self):
        snapshot = LockSnapshot(b'\xef\xbb\xbf{"pid":1}', (1, 2, 3))
        self.assertEqual(runtime.decode_snapshot(runtime.encode_snapshot(snapshot)), snapshot)
        for value in (None, {}, dict(raw='?',identity=[1,2,3]), dict(raw='',identity=[True,2,3]),
                      dict(raw='',identity=[1,2]), dict(raw='A'*22001,identity=[1,2,3])):
            with self.subTest(value=str(value)[:50]):
                with self.assertRaises((ValueError, TypeError)): runtime.decode_snapshot(value)

    def test_no_windows_authority_on_nonwindows(self):
        if os.name == 'nt': self.skipTest('Linux refusal control')
        with self.assertRaisesRegex(OSError, 'requires_windows'): runtime.WindowsAuthority()


class StagedBoundaryTests(unittest.TestCase):
    def test_nonpositive_idle_and_invalid_types_rejected_before_any_effect(self):
        from pcucp_cli.legacy_helper_client import LegacyHelperClient, LockState, LockRecord
        client=object.__new__(LegacyHelperClient)
        client.state=Mock(return_value=LockState('valid','',None,LockRecord(1,'cucp-helper-1','2026-01-01T00:00:00Z','2.0.0','owner')))
        launcher=Mock()
        for value in (-2147483648,-1,0,True,1.5,'10',2147483648,-2147483649):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): client.start(launcher,idle_timeout_ms=value)
        client.state.assert_not_called()
        launcher.launch.assert_not_called()
        for value in (1,60000,2147483647): self.assertTrue(client.start(launcher,idle_timeout_ms=value)['reused'])
        launcher.launch.assert_not_called()

    def test_exchange_worker_bounds_and_timeout_never_retry(self):
        for command, pattern in (([sys.executable,'-c','import sys;sys.stdout.buffer.write(b"x"*1048577)'],'limit'),
                                 ([sys.executable,'-c','import sys;sys.stderr.buffer.write(b"x"*65537)'],'limit')):
            with self.assertRaisesRegex(OSError,pattern): runtime.capture_exchange(command,5)
        with self.assertRaises(TimeoutError): runtime.capture_exchange([sys.executable,'-c','import time;time.sleep(5)'],.05)
        self.assertEqual(runtime.capture_exchange([sys.executable,'-c','print("ok")'],5).strip(),b'ok')


class StagedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.host = object.__new__(runtime.StagedHelperRuntime)
        self.host.client = Mock(); self.host.launcher = Mock(); self.host.manifest = dict(helper_version='2.0.0')

    def handle(self, op, **args): return self.host.handle(dict(operation=op, arguments=args))

    def test_unknown_fields_operations_and_authority_rejected_before_effect(self):
        requests = [dict(operation='start',arguments=dict(idle_timeout_ms=10, desktop=True)),
                    dict(operation='shell',arguments={}), dict(operation='invoke',arguments=dict(action='health')),
                    dict(operation='status',arguments={}, executable='evil.exe'), [], None]
        for request in requests:
            with self.subTest(request=request):
                with self.assertRaises(ValueError): self.host.handle(request)
        self.assertEqual(self.host.client.mock_calls, [])
        self.assertEqual(self.host.launcher.mock_calls, [])

    def test_start_and_stop_each_dispatched_once(self):
        self.handle('start', idle_timeout_ms=60000)
        self.host.client.start.assert_called_once_with(self.host.launcher, idle_timeout_ms=60000)
        self.handle('stop', force=True)
        self.host.client.stop.assert_called_once_with(force=True)

    def test_invoke_request_id_and_original_arguments(self):
        self.handle('invoke',action='windows',args={'Match':'한글'},timeout_ms=500,request_id=17,snapshot=None)
        self.assertEqual(self.host.client._request_id,16)
        self.host.client.invoke.assert_called_once_with('windows', {'Match':'한글'}, timeout_ms=500, expected=None)

    def test_attempted_snapshot_reaches_client_expected_boundary(self):
        raw=json.dumps(dict(pid=123,pipe_name='cucp-helper-123',owner_user='owner',
            helper_version='2.0.0',started_at='2026-10-03T00:00:00Z')).encode()
        snapshot=LockSnapshot(raw,(1,2,3))
        self.host.client.owner_user='owner'
        self.host.client.clock.utcnow.return_value=datetime(2026,10,3,tzinfo=timezone.utc)
        self.host.client.process_alive=lambda pid: pid==123
        self.handle('invoke',action='health',args={},timeout_ms=500,request_id=1,snapshot=runtime.encode_snapshot(snapshot))
        expected=self.host.client.invoke.call_args.kwargs['expected']
        self.assertTrue(expected.usable);self.assertEqual(expected.snapshot,snapshot)

    def test_invalid_request_ids_never_contact(self):
        for value in (0, -1, True, 2147483648, '1'):
            with self.assertRaises(ValueError): self.handle('invoke',action='health',args={},timeout_ms=500,request_id=value,snapshot=None)
        self.host.client.invoke.assert_not_called()

    def test_replacement_is_stale_and_cannot_be_deleted(self):
        expected = LockSnapshot(b'{"pid":1}', (1,2,3))
        replacement = LockSnapshot(expected.raw, (1,2,4))
        self.host.client.state.return_value = Mock(usable=True, snapshot=replacement, kind='valid')
        self.assertTrue(self.handle('stale', snapshot=runtime.encode_snapshot(expected)))
        self.assertFalse(self.handle('delete', snapshot=runtime.encode_snapshot(expected)))
        self.host.client._delete.assert_not_called()

    def test_delete_requires_identical_stale_acquisition(self):
        snapshot = LockSnapshot(b'{"pid":1}', (1,2,3))
        state = Mock(usable=False,snapshot=snapshot,kind='stale')
        self.host.client.state.return_value=state
        self.assertTrue(self.handle('delete',snapshot=runtime.encode_snapshot(snapshot)))
        self.host.client._delete.assert_called_once_with(state)

    def test_malformed_foreign_valid_and_missing_are_not_deleted(self):
        snapshot = LockSnapshot(b'{"pid":1}', (1,2,3))
        for kind in ('malformed','foreign','valid','missing','unreadable'):
            self.host.client.state.return_value=Mock(usable=kind=='valid',snapshot=snapshot,kind=kind)
            self.assertFalse(self.handle('delete',snapshot=runtime.encode_snapshot(snapshot)))
        self.host.client._delete.assert_not_called()

    def test_packaged_version_does_not_use_ps_header(self):
        self.assertEqual(self.handle('version'),dict(version='2.0.0',error=None))
        self.assertEqual(self.host.client.mock_calls, [])

    def test_launch_error_not_retried(self):
        self.host.client.start.side_effect=OSError('uncertain launch')
        with self.assertRaises(OSError): self.handle('start',idle_timeout_ms=10)
        self.assertEqual(self.host.client.start.call_count,1)


class StagedWrapperStructureTests(unittest.TestCase):
    def test_seven_delegates_and_unchanged_default_routing(self):
        text=(ROOT/'scripts/cucp.ps1').read_text(encoding='utf-8-sig')
        for name, op in [('_Read-LockSafely','read'),('_Is-StaleLock','stale'),('_Try-Delete-Lock','delete'),
                         ('Get-HelperServerStatus','status'),('Invoke-HelperPipe','invoke'),('Start-HelperServer','start'),('Stop-HelperServer','stop')]:
            body=text.split('function '+name+' {',1)[1].split('\nfunction ',1)[0]
            self.assertIn("-Operation '"+op+"'",body)
            self.assertIn('$Script:StagedCompiledHelper',body)
        native=text.split('function Invoke-NativeHelper {',1)[1].split('\nfunction ',1)[0]
        self.assertLess(native.index('Invoke-HelperPipe'),native.index('$hotKey = $null'))
        self.assertIn('$resp.exit_code -ne 99',native)
        self.assertIn('@("Match","TargetMatch","TargetHwnd")',native)
        self.assertIn('-not $ForceChild -and -not $env:CUCP_FORCE_CHILD',native)
        self.assertIn('_Try-Delete-Lock -ExpectedLock $lock',native)

    def test_staged_autostart_preserves_live_guards_and_has_no_legacy_fallback(self):
        text=(ROOT/'scripts/cucp.ps1').read_text(encoding='utf-8-sig')
        for name,operation in (('Install-HelperAutostart','autostart-install'),('Uninstall-HelperAutostart','autostart-uninstall'),('Get-HelperAutostartStatus','autostart-status')):
            body=text.split('function '+name+' {',1)[1].split('\nfunction ',1)[0]
            self.assertIn("return (_Invoke-StagedHelper -Operation '"+operation+"'",body)
        self.assertIn('session install-autostart requires -AllowLiveControl',text)
        self.assertIn('session uninstall-autostart requires -AllowLiveControl',text)
        adapter=(ROOT/'scripts/cucp-staged-helper-adapter.ps1').read_text()
        self.assertIn('$Script:StagedAutostartLive = [bool]$AllowLiveControl',adapter)
        self.assertIn('if ($Script:StagedAutostartLive)',adapter)

    def test_observed_startup_failures_remain_hash_pinned(self):
        fixtures=ROOT/'tests/fixtures/legacy-helper'
        pin=json.loads((fixtures/'observed-staged-startup-manifest.json').read_text())
        self.assertEqual(pin['status'],'failed-unqualified-baseline')
        for name, entry in pin['files'].items():
            raw=(fixtures/name).read_bytes()
            self.assertEqual(len(raw),entry['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
        self.assertIn(b'Console.set_OutputEncoding',(fixtures/'observed-detached-startup.stderr.bin').read_bytes())
        self.assertIn(b'The system cannot find the file specified',(fixtures/'observed-staged-wrapper-launch.log.bin').read_bytes())

    def test_multiple_application_failure_is_pinned_and_selection_pattern_shared(self):
        fixtures=ROOT/'tests/fixtures/legacy-helper'
        pin=json.loads((fixtures/'observed-staged-python-resolution.json').read_text())
        raw=(fixtures/pin['raw_file']).read_bytes()
        self.assertEqual(len(raw),pin['raw_bytes']);self.assertEqual(hashlib.sha256(raw).hexdigest(),pin['raw_sha256'])
        record=pin['observed']
        self.assertEqual(record['command_count'],2)
        self.assertEqual(record['file_name'],' '.join(row['source'] for row in record['commands']))
        self.assertTrue(all(row['command_type']=='Application' for row in record['commands']))
        pattern='Get-Command python.exe -CommandType Application -TotalCount 1 -ErrorAction Stop'
        self.assertIn(pattern,(ROOT/'scripts/cucp-staged-helper-adapter.ps1').read_text())
        self.assertIn(pattern,(ROOT/'scripts/cucp-legacy-cdp-adapter.ps1').read_text(encoding='utf-8-sig'))
        shared=(ROOT/'tests/cucp.LegacyRegression.Tests.ps1').read_text()
        self.assertIn('actual staged helper bridge',shared)
        self.assertIn('without discovering a replacement',shared)

    def test_void_completion_failure_record_and_inert_reply_vectors(self):
        pin=json.loads((ROOT/'tests/fixtures/legacy-helper/observed-staged-void-completion.json').read_text())
        raw=(ROOT/'tests/fixtures/legacy-helper'/pin['raw_file']).read_bytes()
        self.assertEqual(len(raw),pin['raw_bytes']);self.assertEqual(hashlib.sha256(raw).hexdigest(),pin['raw_sha256'])
        value=json.loads(raw)
        self.assertEqual(value['Count'],2);self.assertEqual(value['SyncRoot'][0],{})
        self.assertEqual(value['SyncRoot'][1]['status'],'ok');self.assertNotIn('status',value)
        fixture=ROOT/'tests/fixtures/legacy-helper-staged-reply.py'
        for operation,arguments,expected in (('read',{},None),('stale',{'snapshot':None},False),
                ('delete',{'snapshot':None},True),('status',{},dict(marker='owned-scalar-reply',empty=[],number=0,flag=False))):
            completed=subprocess.run([sys.executable,str(fixture),'--staged-unqualified','--lock-file','unused'],
                input=json.dumps(dict(operation=operation,arguments=arguments)).encode(),capture_output=True,timeout=5)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertEqual(json.loads(completed.stdout)['data'],expected)

    def test_async_write_completion_suppression_matches_qualified_cdp_bridge(self):
        expression='[void]$write.GetAwaiter().GetResult()'
        for name in ('cucp-staged-helper-adapter.ps1','cucp-legacy-cdp-adapter.ps1'):
            self.assertIn(expression,(ROOT/'scripts'/name).read_text(encoding='utf-8-sig'))
        shared=(ROOT/'tests/cucp.LegacyRegression.Tests.ps1').read_text()
        self.assertIn('does not emit async write completion objects',shared)
        self.assertIn('$replies.Count | Should -Be 1',shared)

    def test_service_encodes_streams_without_console_codepage_mutation(self):
        source=(ROOT/'pcucp-next/dotnet/PcuCp.LegacyHelper/Program.cs').read_text()
        self.assertNotIn('Console.OutputEncoding =',source)
        self.assertIn('Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false))',source)
        self.assertIn('Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false))',source)
        self.assertIn('AutoFlush = true',source)

    def test_failed_launch_metadata_uses_existing_first_application_pattern(self):
        source=(ROOT/'scripts/cucp-staged-helper-adapter.ps1').read_text()
        self.assertIn('Get-Command python.exe -CommandType Application -TotalCount 1 -ErrorAction Stop',source)
        self.assertIn('$python = $pythonCommands[0]',source)
        self.assertIn('$pythonCommands.Count -ne 1',source)
        self.assertIn('[System.Management.Automation.ApplicationInfo]',source)
        self.assertIn('$psi.FileName = $python.Source',source)
        self.assertIn('STAGED HELPER LAUNCH RESOLUTION',source)
        self.assertIn('command_count=$commands.Count',source)
        self.assertIn('Select-Object -First 4',source)
        self.assertEqual(source.count('$process.Start()'),1)

    def test_wrapper_fixture_propagates_nested_exit(self):
        text=(ROOT/'tests/fixtures/legacy-helper-staged-wrapper.ps1').read_text()
        self.assertIn('exit [int]$LASTEXITCODE',text)

    def test_staged_adapter_has_bounded_reads_and_no_command_evaluation(self):
        text=(ROOT/'scripts/cucp-staged-helper-adapter.ps1').read_text()
        self.assertIn('ReadAsync',text);self.assertNotIn('ReadToEnd',text)
        self.assertNotIn('Invoke-Expression',text);self.assertNotIn('powershell.exe',text)
        self.assertNotIn('Stop-Process',text);self.assertNotIn('taskkill',text)
        self.assertIn('operation not retried',text)
        self.assertIn('$Script:StagedHelperDesktop',text)


WINDOWS_ENABLED = os.name=='nt' and os.environ.get('CUCP_REQUIRE_STAGED_HELPER')=='1'
@unittest.skipUnless(WINDOWS_ENABLED,'Requires explicit Windows staged runtime gate and built fixed package')
class StagedWindowsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cucp staged 한글 ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.lock=self.root/'helper.pid'
        self.runtime=runtime.StagedHelperRuntime(ROOT/'pcucp-next/bin/legacy-helper',self.lock,desktop=False)
        self.owned=[];self.addCleanup(self.cleanup)
        launch=self.runtime.launcher.launch
        def retained(**kwargs):
            process=launch(**kwargs);self.owned.append(process);return process
        self.runtime.launcher.launch=retained

    def cleanup(self):
        for process in self.owned:
            if process.process.poll() is None: process.terminate_owned()

    def test_concrete_start_reuse_health_shutdown_without_desktop(self):
        first=self.runtime.client.start(self.runtime.launcher,idle_timeout_ms=10000)
        self.assertEqual(first['status'],'ok')
        second=self.runtime.client.start(self.runtime.launcher,idle_timeout_ms=10000)
        self.assertTrue(second['reused']);self.assertEqual(first['pid'],second['pid'])
        self.assertEqual(len(self.owned),1)
        response=self.runtime.client.invoke('health')
        self.assertEqual(response['exit_code'],0);self.assertEqual(response['result']['pid'],first['pid'])
        self.assertFalse(response['result']['win32_loaded'])
        self.assertEqual(self.runtime.client.stop(force=True)['reason'],'shutdown_requested')
        self.owned[0].process.wait(timeout=5);self.assertFalse(self.lock.exists())

    def test_direct_service_retains_zero_and_negative_idle_boundaries(self):
        # Direct CLI remains nonnegative; client start is stricter (positive).
        # Preserve all prior vectors while restoring pre-lock negative refusal.
        for value, expected_exit in ((0,0),(-1,1),(-2147483648,1)):
            with self.subTest(idle_timeout_ms=value):
                process=self.runtime.launcher.launch(idle_timeout_ms=value)
                self.assertEqual(process.process.wait(timeout=5),expected_exit)
                self.assertFalse(self.lock.exists())

    def test_packaged_utf8_streams_and_cli_rejection_under_all_start_modes(self):
        from helper_process_evidence import run_evidence, require_success
        logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR',self.root/'evidence'))
        host=ROOT/'pcucp-next/bin/legacy-helper/PcuCp.LegacyHelper.exe'
        fixture=self.root/'inert-unicode.json'
        text='한글😀'
        fixture.write_text(json.dumps(dict(calls=[],clock=['2026-01-01T00:00:00Z'],
            requests=[dict(id=text,action='unsupported-'+text,args={})])),encoding='utf-8')
        outputs=[]
        for mode, flags in (('inherited',0),('no-window',subprocess.CREATE_NO_WINDOW),
                            ('detached',subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)):
            with self.subTest(mode=mode):
                result=run_evidence([host,'fixture','--input-file',fixture],directory=logs,
                    label='packaged-utf8-'+mode,timeout=5,limit=65536,creationflags=flags)
                require_success(result)
                self.assertFalse(result['stdout'].startswith(b'\xef\xbb\xbf'))
                self.assertTrue(result['stdout'].endswith(b'\r\n'))
                decoded=json.loads(result['stdout'].decode('utf-8',errors='strict'))
                self.assertEqual(decoded['responses'][0]['id'],text)
                self.assertEqual(decoded['responses'][0]['result']['action'],'unsupported-'+text)
                self.assertEqual(decoded['responses'][0]['exit_code'],99)
                self.assertEqual(result['stderr'],b'')
                outputs.append(result['stdout'])
                rejected=run_evidence([host,'serve','--lock-file',self.lock,'--bad_'+text,'value'],
                    directory=logs,label='packaged-utf8-reject-'+mode,timeout=5,limit=65536,creationflags=flags)
                require_success(rejected,expected_exit=1)
                self.assertEqual(rejected['stdout'],b'')
                self.assertEqual(rejected['stderr'],('ArgumentException: unknown candidate option: bad_'+text+'\r\n').encode('utf-8'))
                self.assertFalse(self.lock.exists())
        self.assertTrue(all(value==outputs[0] for value in outputs))

    def test_cas_same_file_change_and_identical_replacement_survive(self):
        store=self.runtime.client.store
        self.lock.write_bytes(b'first');snapshot=store.read()
        self.lock.write_bytes(b'other');self.assertFalse(store.compare_delete(snapshot))
        self.lock.write_bytes(b'first');snapshot=store.read()
        replacement=self.root/'replacement';replacement.write_bytes(b'first');os.replace(replacement,self.lock)
        self.assertFalse(store.compare_delete(snapshot));self.assertEqual(self.lock.read_bytes(),b'first')
        current=store.read();self.assertTrue(store.compare_delete(current));self.assertFalse(self.lock.exists())

    def test_concrete_foreign_lock_preserved_without_launch(self):
        self.lock.write_text(json.dumps(dict(owner_user=self.runtime.authority.owner_user+'-foreign',pid=1)))
        self.assertEqual(self.runtime.client.start(self.runtime.launcher)['reason'],'foreign_lock_ignored')
        self.assertEqual(self.owned,[]);self.assertTrue(self.lock.exists())

    def test_concrete_bounded_lock_refuses_oversize(self):
        self.lock.write_bytes(b'x'*16385)
        self.assertEqual(self.runtime.client.state().kind,'unreadable')
        self.assertTrue(self.lock.exists())

@unittest.skipUnless(WINDOWS_ENABLED,'Requires explicit Windows staged gate and PS5 production wrapper')
class StagedProductionWrapperWindowsTests(unittest.TestCase):
    def test_real_wrapper_bridge_failure_retains_cache_child_and_version(self):
        from helper_process_evidence import run_evidence, require_success
        import shutil
        with tempfile.TemporaryDirectory(prefix='cucp staged fallback ') as root:
            logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR',Path(root)/'evidence'))
            evidence=run_evidence([shutil.which('powershell.exe'),'-NoProfile','-NonInteractive','-File',
                str(ROOT/'tests/fixtures/legacy-helper-staged-fallback.ps1'),'-Wrapper',str(ROOT/'scripts/cucp.ps1'),'-Work',root],
                directory=logs,label='staged-wrapper-fallback',cwd=ROOT,timeout=20)
            require_success(evidence)
            result=json.loads(evidence['stdout'].decode('utf-8-sig'))
            self.assertEqual(result,dict(status='ok',checks=4,desktop_acquired=False))

    def test_real_wrapper_cross_process_start_status_stop_and_version(self):
        # Public user-facing path, copied bootstrap authority and real fixed package.
        # Never kill an advertised PID. The service's own 10 s idle expiry is the
        # recovery guard if shutdown fails; raw failure evidence stays unqualified.
        from helper_process_evidence import run_evidence, require_success
        import shutil
        with tempfile.TemporaryDirectory(prefix='cucp staged wrapper 한글 ') as root:
            root=Path(root)
            logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR',root/'evidence'))
            # Owned metadata-only CLI fixture: the production wrapper may read
            # it, but executing it writes a tripwire and exits 97. No real CLI,
            # Node installation, or package installation is performed.
            profile=root/'empty-profile';profile.mkdir()
            cli_dir=root/'owned-cli/src';cli_dir.mkdir(parents=True)
            cli=cli_dir/'cli.mjs';tripwire=root/'unexpected-cli-execution'
            cli.write_text('// ControlPlane inert metadata fixture\nimport fs from "node:fs";\n'
                +'fs.writeFileSync('+json.dumps(str(tripwire))+', "unexpected"); process.exit(97);\n',encoding='utf-8')
            metadata=cli_dir.parent/'package.json'
            metadata.write_text(json.dumps(dict(name='computer-use-control-plane',version='0.0.0')),encoding='utf-8')
            env=dict(os.environ,TEMP=str(root),TMP=str(root),USERPROFILE=str(profile),
                     CUCP_CLI_PATH=str(cli),CUCP_STAGED_COMPILED_HELPER='1')
            env.pop('CUCP_STAGED_HELPER_READONLY_DESKTOP',None)
            def call(operation, *, expected_exit=0):
                evidence=run_evidence([shutil.which('powershell.exe'),'-NoProfile','-NonInteractive','-File',
                    str(ROOT/'tests/fixtures/legacy-helper-staged-wrapper.ps1'),'-Wrapper',str(ROOT/'scripts/cucp.ps1'),
                    '-Operation',operation],directory=logs,label='staged-wrapper-'+operation,cwd=ROOT,env=env,timeout=20)
                # Quiet suppresses console diagnostics; preserve the owned wrapper
                # log before checking exit/JSON and before TemporaryDirectory cleanup.
                wrapper_log=root/'computer-use-control-plane/cucp-wrapper.log'
                if wrapper_log.is_file():
                    with wrapper_log.open('rb') as stream: raw_log=stream.read(65537)
                    log_path=Path(evidence['evidence_path']).with_suffix('.wrapper.log.bin')
                    log_path.write_bytes(raw_log[:65536])
                    if len(raw_log)>65536: self.fail('Owned wrapper log exceeded diagnostic bound')
                require_success(evidence,expected_exit=expected_exit)
                return json.loads(evidence['stdout'].decode('utf-8-sig'))
            try:
                started=call('start')
                self.assertEqual(set(started),{'schema','status','reused','pid','pipe_name','started_at'})
                self.assertEqual(started['status'],'ok');self.assertFalse(started['reused'])
                status=call('status')
                self.assertEqual(set(status),{'schema','alive','pid','pipe_name','started_at','uptime_s','request_count','helper_version'})
                self.assertTrue(status['alive']);self.assertEqual(started['pid'],status['pid'])
                version=call('version')
                self.assertEqual(version['schema'],'cucp.version/v1')
                self.assertEqual(version['status'],'ok')
                self.assertEqual(version['surface'],'wrapper+cli')
                self.assertEqual(version['helper_mode'],'persistent_server')
                self.assertEqual(version['versions']['cli'],'0.0.0')
                self.assertEqual(version['versions']['helper_server'],'2.0.0')
                self.assertEqual(version['recoverable_errors'],[])
                self.assertFalse(tripwire.exists(),'Metadata-only CLI fixture was executed')
                metadata.unlink()  # Only the package metadata created above.
                partial=call('version',expected_exit=2)
                self.assertEqual(partial['schema'],'cucp.version/v1')
                self.assertEqual(partial['status'],'partial')
                self.assertEqual(partial['surface'],'wrapper_only')
                self.assertEqual(partial['helper_mode'],'persistent_server')
                self.assertIsNone(partial['versions']['cli'])
                self.assertEqual(partial['versions']['helper_server'],'2.0.0')
                self.assertEqual(partial['recoverable_errors'],[dict(code='package_json_not_found',layer='cli',
                    recommended_action='Set CUCP_CLI_PATH or run wrapper-only mode')])
                stopped=call('stop');self.assertEqual(stopped['reason'],'shutdown_requested');self.assertFalse(stopped['forced'])
            finally:
                # No PID-based termination, including after an assertion failure.
                deadline=time.monotonic()+15
                while list(root.rglob('helper-staged.pid')) and time.monotonic()<deadline: time.sleep(.05)
                self.assertEqual(list(root.rglob('helper-staged.pid')),[], 'staged service did not clean its lock before recovery deadline')
                self.assertFalse(tripwire.exists(),'Metadata-only CLI fixture was executed')
