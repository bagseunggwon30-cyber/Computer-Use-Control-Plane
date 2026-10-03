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

    def test_staged_autostart_explicitly_blocked_no_ps_fallback(self):
        text=(ROOT/'scripts/cucp.ps1').read_text(encoding='utf-8-sig')
        body=text.split('function Install-HelperAutostart {',1)[1].split('\nfunction ',1)[0]
        self.assertLess(body.index('staged_helper_autostart_unqualified'),body.index('WriteAllText'))

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
            env=dict(os.environ,TEMP=str(root),TMP=str(root),CUCP_STAGED_COMPILED_HELPER='1')
            env.pop('CUCP_STAGED_HELPER_READONLY_DESKTOP',None)
            def call(operation):
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
                require_success(evidence)
                return json.loads(evidence['stdout'].decode('utf-8-sig'))
            try:
                started=call('start');self.assertEqual(started['status'],'ok');self.assertFalse(started['reused'])
                status=call('status');self.assertTrue(status['alive']);self.assertEqual(started['pid'],status['pid'])
                version=call('version');self.assertEqual(version['versions']['helper_server'],'2.0.0')
                stopped=call('stop');self.assertEqual(stopped['reason'],'shutdown_requested');self.assertFalse(stopped['forced'])
            finally:
                # No PID-based termination, including after an assertion failure.
                deadline=time.monotonic()+15
                while list(root.rglob('helper-staged.pid')) and time.monotonic()<deadline: time.sleep(.05)
                self.assertEqual(list(root.rglob('helper-staged.pid')),[], 'staged service did not clean its lock before recovery deadline')
