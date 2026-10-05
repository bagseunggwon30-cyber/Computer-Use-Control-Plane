"""Actual session in the shared owner uses the same backend and invocation ceiling."""
import json
import os
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest

from pcucp_cli.legacy_host_protocol import Authority, LegacyHostError
from pcucp_cli.legacy_preserved_owner import PreservedOwner


class SessionOwnerTests(unittest.TestCase):
    def test_owned_cache_info_clear_and_denied_autostart_leave_owner_usable(self):
        with tempfile.TemporaryDirectory(prefix='CUCP session owner ') as folder:
            root=Path(folder).resolve()
            context=dict(audit_directory=str(root/'audit'),cache_directory=str(root/'cache'),wrapper_log=str(root/'wrapper.log'),
                cli_path=None,changelog_path=str(root/'CHANGELOG.md'),temp_root=str(root),benchmark_schema='cucp.benchmark/v1',
                release_schema='cucp.release-notes/v1')
            owner=PreservedOwner(context);self.addCleanup(owner.close)
            # Original owner needs compiled confirmation even for read-only paths;
            # this is a scope/port test, not native confirmation qualification.
            from unittest.mock import patch
            with patch('pcucp_cli.legacy_preserved_owner.compatibility',return_value=dict(confirmed=False)):
                (root/'cache/appshot-owned.json').write_text('{}')
                code,output=owner.invoke(['macro','session','info'],brief=True)
                self.assertEqual(code,0);self.assertEqual(json.loads(output)['cache_files'],1)
                code,output=owner.invoke(['macro','session','clear-cache'],quiet=True)
                self.assertEqual((code,output),(0,''));self.assertFalse((root/'cache/appshot-owned.json').exists())
                self.assertIn('OK 관찰/포인트 캐시를 비웠습니다.',(root/'wrapper.log').read_text(encoding='utf-8'))
                with self.assertRaisesRegex(LegacyHostError,'requires -AllowLiveControl'):
                    owner.invoke(['macro','session','install-autostart'])
                code,output=owner.invoke(['macro','session','info'])
                self.assertEqual(code,0);self.assertEqual(json.loads(output)['cache_files'],0)
                self.assertFalse(owner.closed)


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_NATIVE_HOST'),'Actual compiled Windows reads')
class SessionNativeTests(unittest.TestCase):
    def test_autostart_install_status_uninstall_use_only_owned_test_directories(self):
        from pcucp_cli.legacy_session_runtime import SessionRuntime
        with tempfile.TemporaryDirectory(prefix='CUCP session autostart owned ') as folder:
            root=Path(folder).resolve();(root/'startup').mkdir();(root/'metadata').mkdir()
            context=dict(cache_directory=str(root/'cache'),audit_directory=str(root/'audit'),wrapper_log=str(root/'wrapper.log'),
                cli_path=None,cache_seconds=2,lock_file=str(root/'audit/helper.pid'),staged=False,desktop=False,modern=False,
                startup_directory=str(root/'startup'),metadata_directory=str(root/'metadata'))
            installed=SessionRuntime(context,allow_live_control=True).run(['install-autostart'])
            self.assertEqual(installed['exit'],0,installed['payload'])
            try:
                status=SessionRuntime(context).run(['autostart-status'])
                self.assertTrue(status['payload']['installed'])
                shim=Path(installed['payload']['shim_path'])
                self.assertEqual(shim.parent,root/'startup')
                self.assertNotIn('powershell.exe',shim.read_text(encoding='utf-8'))
            finally:
                removed=SessionRuntime(context,allow_live_control=True).run(['uninstall-autostart'])
                self.assertEqual(removed['exit'],0,removed['payload'])
            self.assertFalse(shim.exists())

    def test_special_folders_match_the_original_system_getters_without_path_selection(self):
        from pcucp_cli.native_session import NativeSession
        with NativeSession() as native:
            code,payload,error=native('legacy-diagnostic-read',['--operation','special-folders'])
            self.assertEqual(code,0,error)
            value=payload['data']['value']
            for shell in ('powershell.exe','pwsh.exe'):
                self.assertIsNotNone(shutil.which(shell))
                script="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);@{startup_directory=[Environment]::GetFolderPath([Environment+SpecialFolder]::Startup);metadata_directory=[Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)}|ConvertTo-Json -Compress"
                result=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0)
                self.assertEqual(value,json.loads(result.stdout.decode('utf-8-sig')))
            code,payload,error=native('legacy-diagnostic-read',['--operation','special-folders','--startup-directory','other'])
            self.assertNotEqual(code,0)

    def test_session_is_really_connected_to_the_owner_with_an_owned_readonly_helper(self):
        with tempfile.TemporaryDirectory(prefix='CUCP actual session owner ') as folder:
            root=Path(folder).resolve()
            context=dict(audit_directory=str(root/'audit'),cache_directory=str(root/'cache'),wrapper_log=str(root/'wrapper.log'),
                cli_path=None,changelog_path=str(root/'CHANGELOG.md'),temp_root=str(root),benchmark_schema='cucp.benchmark/v1',
                release_schema='cucp.release-notes/v1',helper_staged=True,helper_desktop=False)
            owner=PreservedOwner(context);self.addCleanup(owner.close)
            try:
                code,output=owner.invoke(['macro','session','start-helper','--idle-timeout-ms','30000'])
                self.assertEqual(code,0);first=json.loads(output)
                code,output=owner.invoke(['macro','session','helper-status'])
                self.assertEqual(code,0);self.assertEqual(json.loads(output)['pid'],first['pid'])
                code,output=owner.invoke(['macro','session','info'],brief=True)
                self.assertEqual(code,0);self.assertTrue(json.loads(output)['helper_server']['alive'])
                with self.assertRaisesRegex(LegacyHostError,'requires -AllowLiveControl'):
                    owner.invoke(['macro','session','install-autostart'])
                self.assertFalse(owner.closed)
            finally:
                code,output=owner.invoke(['macro','session','stop-helper'])
                self.assertEqual(code,0)
            self.assertFalse((root/'audit/helper-staged.pid').exists())
