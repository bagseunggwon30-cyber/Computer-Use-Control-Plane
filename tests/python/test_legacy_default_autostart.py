"""Default logon migration in disposable folders; never discover real Startup."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from pcucp_cli.legacy_default_autostart import DefaultAutostartController, legacy_shim
from pcucp_cli.legacy_helper_autostart import SHIM_NAME, WindowsAutostartStore
from pcucp_cli.legacy_helper_runtime import WindowsAuthority, StagedHelperRuntime
from test_legacy_helper_autostart import OwnedFixtureStore

ROOT=Path(__file__).resolve().parents[2]


class FixtureStore(OwnedFixtureStore):
    def replace_known(self, expected, raw):
        self.calls.append(('rewrite',SHIM_NAME))
        if self.replace_before_delete==SHIM_NAME:
            self.replace(SHIM_NAME,expected.raw);self.replace_before_delete=None
        if self.read(SHIM_NAME)!=expected: return False
        if self.fail_create==SHIM_NAME: raise OSError('injected rewrite failure')
        self.replace(SHIM_NAME,raw)
        return True


class AutostartFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='CUCP-default-autostart-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.startup=self.root/'startup';self.state=self.root/'state'
        self.startup.mkdir();self.state.mkdir();self.store=FixtureStore(self.startup,self.state)
        self.old=ROOT/'scripts/cucp-helper-server.ps1';self.validate=Mock()
        self.controller=self.controller_for(self.store)

    def controller_for(self, store, allow_change=True):
        return DefaultAutostartController(self.startup,sys.executable,ROOT/'pcucp-next/python/legacy_helper_autostart_default.py',
            metadata_directory=self.state,store=store,allow_change=allow_change,desktop=True,
            validate_install=self.validate,legacy_server=self.old)


class DefaultAutostartTests(AutostartFixture,unittest.TestCase):
    def test_create_reconfigure_idempotence_and_remove_preserve_public_schema(self):
        first=self.controller.install(1000);self.assertEqual(first['status'],'ok',first)
        self.assertEqual(set(first),{'status','action','shim_path','idle_timeout_ms','note'})
        raw=(self.startup/SHIM_NAME).read_bytes();self.assertNotIn(b'powershell',raw.lower())
        self.assertIn(b'legacy_helper_autostart_default.py',raw)
        self.assertIn(b'--allow-readonly-desktop',raw)
        self.store.calls=[];self.assertEqual(self.controller.install(1000),first)
        self.assertFalse(any(c[0] in ('create','delete','rewrite') for c in self.store.calls))
        self.assertEqual(self.controller.install(2000)['status'],'ok')
        self.assertNotEqual((self.startup/SHIM_NAME).read_bytes(),raw)
        self.assertEqual(self.controller.status()['installed'],True)
        self.assertEqual(list(self.state.iterdir()),[])
        result=self.controller.uninstall();self.assertTrue(result['removed']);self.assertEqual(result['status'],'ok')
        self.assertFalse(self.controller.uninstall()['removed'])

    def test_exact_original_launcher_is_adopted_and_negative_idle_preserves_no_expiry(self):
        for old_idle in (28800000,0,-1,-2147483648,2147483647):
            with self.subTest(old_idle=old_idle):
                self.store.replace(SHIM_NAME,legacy_shim(self.old,old_idle))
                result=self.controller.install(old_idle);self.assertEqual(result['status'],'ok',result)
                self.assertEqual(result['idle_timeout_ms'],old_idle)
                self.assertEqual((self.startup/SHIM_NAME).read_bytes(),self.controller._plan(max(0,old_idle))['shim'])
                self.assertTrue(self.controller.uninstall()['removed'])

    def test_uninstall_original_known_launcher_without_compiled_package(self):
        self.store.replace(SHIM_NAME,legacy_shim(self.old,12345));self.validate.side_effect=ValueError('missing package')
        self.assertTrue(self.controller.uninstall()['removed']);self.validate.assert_not_called()

    def test_modified_and_other_repository_launchers_are_preserved(self):
        for raw in (b'@echo off\r\necho user-owned\r\n',legacy_shim(self.root/'other/cucp-helper-server.ps1',1000),
                    legacy_shim(self.old,1000)+b'echo changed\r\n',legacy_shim(self.old,1000).replace(b'1000',b'01000')):
            self.store.replace(SHIM_NAME,raw)
            self.assertEqual(self.controller.install()['status'],'error')
            self.assertEqual(self.controller.uninstall()['status'],'error')
            self.assertEqual((self.startup/SHIM_NAME).read_bytes(),raw)

    def test_same_byte_replacement_race_is_preserved(self):
        self.store.replace(SHIM_NAME,legacy_shim(self.old,1000));self.store.replace_before_delete=SHIM_NAME
        result=self.controller.install(2000);self.assertEqual(result['status'],'error')
        self.assertEqual((self.startup/SHIM_NAME).read_bytes(),legacy_shim(self.old,1000))

    def test_failed_update_keeps_original_shim(self):
        raw=legacy_shim(self.old,1000);self.store.replace(SHIM_NAME,raw);self.store.fail_create=SHIM_NAME
        self.assertEqual(self.controller.install(2000)['status'],'error')
        self.assertEqual((self.startup/SHIM_NAME).read_bytes(),raw)

    def test_authority_and_invalid_requests_have_no_effect(self):
        denied=self.controller_for(self.store,False)
        for call in (denied.install,denied.uninstall):
            with self.assertRaises(PermissionError): call()
        self.assertEqual(self.store.calls,[]);self.validate.assert_not_called()
        for value in (True,'1000',1.5,2147483648,-2147483649):
            self.assertEqual(self.controller.install(value)['status'],'error')
        self.assertEqual(self.store.calls,[]);self.validate.assert_not_called()
        for args in ({'idle_timeout_ms':1000,'legacy_server':'other'}, {'idle_timeout_ms':1000,'allow_change':True}):
            with self.assertRaises(ValueError): self.controller.handle(dict(operation='autostart-install',arguments=args))


@unittest.skipUnless(os.name=='nt','Owned NTFS-only autostart migration')
class DefaultAutostartWindowsTests(AutostartFixture,unittest.TestCase):
    def test_retained_handle_rewrite_preserves_identity_and_truncates(self):
        store=WindowsAutostartStore(self.startup,self.state,WindowsAuthority());controller=self.controller_for(store)
        self.assertEqual(controller.install(2147483647)['status'],'ok')
        with store.operation(): before=store.read(SHIM_NAME)
        result=controller.install(0);self.assertEqual(result['status'],'ok',result)
        with store.operation(): after=store.read(SHIM_NAME)
        self.assertEqual(after.identity,before.identity)
        self.assertEqual(after.raw,controller._plan(0)['shim'])
        self.assertLess(len(after.raw),len(before.raw));self.assertTrue(controller.uninstall()['removed'])

    def test_real_original_adoption_and_foreign_identity_rejection(self):
        store=WindowsAutostartStore(self.startup,self.state,WindowsAuthority());controller=self.controller_for(store)
        (self.startup/SHIM_NAME).write_bytes(legacy_shim(self.old,1000))
        result=controller.install(2000);self.assertEqual(result['status'],'ok',result)
        with store.operation(): expected=store.read(SHIM_NAME)
        replacement=self.root/'replacement';replacement.write_bytes(expected.raw)
        os.replace(replacement,self.startup/SHIM_NAME)
        with store.operation(): self.assertFalse(store.replace_known(expected,b'ignored'))
        self.assertEqual((self.startup/SHIM_NAME).read_bytes(),expected.raw)
        self.assertTrue(controller.uninstall()['removed'])

    def test_partial_native_write_failure_restores_original_through_retained_handle(self):
        import ctypes
        from unittest.mock import patch
        store=WindowsAutostartStore(self.startup,self.state,WindowsAuthority())
        original=legacy_shim(self.old,1000);(self.startup/SHIM_NAME).write_bytes(original)
        with store.operation(): expected=store.read(SHIM_NAME)
        real_write=store.authority.k.WriteFile;calls=[]
        def fail_once(handle,data,length,written,overlapped):
            calls.append(length)
            if len(calls)==1:
                self.assertTrue(real_write(handle,data,2,written,overlapped))
                ctypes.set_last_error(5)
                return False
            return real_write(handle,data,length,written,overlapped)
        with store.operation(),patch.object(store.authority.k,'WriteFile',side_effect=fail_once):
            with self.assertRaises(OSError): store.replace_known(expected,b'changed')
        self.assertEqual(calls,[7,len(original)])
        with store.operation(): restored=store.read(SHIM_NAME)
        self.assertEqual(restored,expected)

    @unittest.skipUnless(os.environ.get('CUCP_REQUIRE_PYTHON_HELPER_PRODUCTION')=='1','Explicit owned compiled service gate')
    def test_generated_login_launcher_starts_default_lock_and_connects_without_powershell(self):
        store=WindowsAutostartStore(self.startup,self.state,WindowsAuthority());controller=self.controller_for(store)
        result=controller.install(30000);self.assertEqual(result['status'],'ok',result)
        env=dict(os.environ,TEMP=str(self.root),TMP=str(self.root))
        lock=self.root/'computer-use-control-plane/helper.pid'
        runtime=StagedHelperRuntime(ROOT/'pcucp-next/bin/legacy-helper',lock,desktop=True)
        command=[os.path.join(os.environ['SystemRoot'],'System32','cmd.exe'),'/d','/c',str(self.startup/SHIM_NAME)]
        try:
            done=subprocess.run(command,env=env,capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(done.returncode,0,done.stderr+done.stdout)
            self.assertTrue(runtime.client.state().usable,done.stdout)
            self.assertFalse(lock.with_name('helper-staged.pid').exists())
            reply=runtime.client.invoke('windows',{'Match':'CUCP-owned-absent-default-autostart'})
            self.assertEqual(reply['exit_code'],0);self.assertEqual(reply['result']['count'],0)
        finally:
            if lock.exists(): self.assertEqual(runtime.client.stop()['reason'],'shutdown_requested')
            controller.uninstall()
        self.assertFalse(lock.exists())
