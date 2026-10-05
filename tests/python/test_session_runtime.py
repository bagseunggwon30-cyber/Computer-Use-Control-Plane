"""Physical cache behavior, lifecycle argv, immutable authority and terminal scope."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from pcucp_cli.legacy_cdp_bridge import handle
from pcucp_cli.legacy_host_protocol import LegacyHostError
from pcucp_cli.legacy_session_runtime import SessionRuntime


class SessionRuntimeTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='CUCP session owned ')
        self.addCleanup(folder.cleanup);root=Path(folder.name).resolve()
        self.context=dict(cache_directory=str(root/'cache'),audit_directory=str(root/'audit'),
            wrapper_log=str(root/'wrapper.log'),cli_path=None,cache_seconds=2,lock_file=str(root/'audit/helper.pid'),
            desktop=False,staged=True,modern=False,startup_directory=None,metadata_directory=None)
        Path(self.context['cache_directory']).mkdir()
        self.calls=[]
    def runtime(self,reply=None,**kwargs):
        if reply is None:reply=dict(status='ok',alive=False)
        def helper(operation,args):self.calls.append((operation,args));return copy.deepcopy(reply)
        return SessionRuntime(self.context,helper=helper,**kwargs)
    def test_all_lifecycle_commands_preserve_arguments_shapes_and_brief_json_choices(self):
        reply=dict(status='ok',reused=True,pid=37,pipe_name='owned',alive=True,uptime_s=12.5,
                   request_count=4,stopped_pid=37,forced=False,shim_path='owned.cmd',removed=True,installed=True)
        operations={'start-helper':'start','stop-helper':'stop','helper-status':'status',
            'install-autostart':'autostart-install','uninstall-autostart':'autostart-uninstall','autostart-status':'autostart-status'}
        for name,operation in operations.items():
            with self.subTest(name=name):
                result=self.runtime(reply,allow_live_control=True).run([name,'--idle-timeout-ms','2500','--force'],brief=True)
                self.assertEqual(result['exit'],0);self.assertIn('session '+name,result['brief'])
                self.assertFalse(result['emit_json']);self.assertEqual(self.calls[-1][0],operation)
                expected=dict(idle_timeout_ms=2500) if name in ('start-helper','install-autostart') else dict(force=True) if name=='stop-helper' else {}
                self.assertEqual(self.calls[-1][1],expected)
        for value,expected in ((None,60000),('bad',60000),('0',0),('-1',-1),('0xFFFFFFFF',-1),('2.5',2),('2147483648',60000)):
            rest=['start-helper']+(['--idle-timeout-ms',value] if value is not None else [])
            self.runtime(reply).run(rest)
            self.assertEqual(self.calls[-1][1],dict(idle_timeout_ms=expected))
        self.runtime(reply,allow_live_control=True).run(['install-autostart'])
        self.assertEqual(self.calls[-1][1],dict(idle_timeout_ms=28800000))
        self.context['modern']=True
        for raw in (' ','\t','\u00a0'):
            self.runtime(reply).run(['start-helper','--idle-timeout-ms',raw])
            self.assertEqual(self.calls[-1][1],dict(idle_timeout_ms=0))
    def test_cache_count_clear_and_no_recursive_or_out_of_root_deletion(self):
        cache=Path(self.context['cache_directory'])
        for name in ('appshot-a.json','APPSHOT-UPPER.JSON','point-plan-a.json','keep.json','appshot-not.json.txt'):
            (cache/name).write_text('{}')
        nested=cache/'appshot-nested.json';nested.mkdir();(nested/'keep').write_text('owned')
        empty=cache/'point-plan-empty.json';empty.mkdir()
        result=self.runtime().run(['info'],brief=True)
        self.assertEqual(result['payload']['cache_files'],3)
        self.assertEqual(result['payload']['point_plan_cache_files'],2)
        self.assertTrue(result['emit_json']);self.assertIsNone(result['brief'])
        result=self.runtime().run(['clear-cache'],brief=True)
        self.assertFalse(result['emit_json']);self.assertIsNone(result['brief'])
        self.assertEqual(result['notices'][0]['level'],'OK')
        self.assertEqual(sorted(path.name for path in cache.iterdir()),['appshot-nested.json','appshot-not.json.txt','keep.json'])
        self.assertEqual((nested/'keep').read_text(),'owned')
    def test_permissions_and_deadlines_precede_effects_and_repeated_calls_do_not_replay(self):
        for name in ('install-autostart','uninstall-autostart'):
            with self.assertRaisesRegex(LegacyHostError,'requires -AllowLiveControl'):self.runtime().run([name])
        self.assertEqual(self.calls,[])
        event=threading.Event();event.set()
        for kwargs in ({'cancelled':event},{'parent_deadline':time.monotonic()-1}):
            with self.assertRaises(LegacyHostError):self.runtime(**kwargs).run(['start-helper'])
        self.assertEqual(self.calls,[])
        runtime=self.runtime();runtime.run(['helper-status'])
        with self.assertRaises(LegacyHostError):runtime.run(['helper-status'])
        self.assertEqual(len(self.calls),1)
    def test_info_helper_failure_is_null_and_status_error_is_not_successfully_retried(self):
        def fail(operation,args):self.calls.append(operation);raise OSError('owned failure')
        result=SessionRuntime(self.context,helper=fail).run(['info'])
        self.assertIsNone(result['payload']['helper_server']);self.assertEqual(self.calls,['status'])
        with self.assertRaisesRegex(OSError,'owned failure'):SessionRuntime(self.context,helper=fail).run(['helper-status'])
        self.assertEqual(self.calls,['status','status'])
        for name in ('start-helper','stop-helper','install-autostart','uninstall-autostart'):
            result=self.runtime(dict(status='error',reason='owned'),allow_live_control=True).run([name])
            self.assertEqual(result['exit'],1)
        result=self.runtime(dict(status='error')).run(['autostart-status'])
        self.assertEqual(result['exit'],0)
    def test_request_data_cannot_choose_context_or_grant_authority(self):
        for extra in ('context','allow_live_control','lock_file','helper'):
            request=dict(rest=['install-autostart'],brief=False,**{extra:True})
            with self.assertRaises((LegacyHostError,ValueError)):
                handle('session',request,session_context=self.context)
        with self.assertRaisesRegex(LegacyHostError,'requires -AllowLiveControl'):
            handle('session',dict(rest=['install-autostart','--allow-live-control'],brief=False),session_context=self.context)
        with self.assertRaises(ValueError):handle('session',dict(rest=[],brief=False),session_context=self.context,cache_directory='other')


if __name__=='__main__':unittest.main()
