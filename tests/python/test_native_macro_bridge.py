"""Native macro plan/report phases never execute native actions or grant authority."""
from pathlib import Path
import tempfile
import unittest
from pcucp_cli.legacy_cdp_bridge import handle
from pcucp_cli.legacy_host_protocol import LegacyHostError


class NativeMacroBridgeTests(unittest.TestCase):
    def test_typed_prepare_and_complete_preserve_raw_reply_and_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            startup=dict(cache_directory=folder,audit_directory=folder)
            plan=handle('native-macro-prepare',dict(name='native-health',rest=[]),**startup)
            self.assertEqual(plan,dict(argv=['-Action','health'],context={},live=False))
            reply=dict(ExitCode=2,Json=None,Raw='original raw\n',Err=None,ElapsedMs=0)
            result=handle('native-macro-complete',dict(name='native-health',rest=[],prepared=plan['context'],reply=reply,brief=True),**startup)
            self.assertEqual(result['exit'],1)
            self.assertEqual(result['brief'],'err native-health helper_unavailable raw=')
            result=handle('native-macro-complete',dict(name='native-health',rest=[],prepared={},reply=reply,brief=False),**startup)
            self.assertEqual(result['raw'],'original raw\n')

    def test_json_cannot_choose_directories_or_grant_live_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            startup=dict(cache_directory=folder,audit_directory=folder)
            for extra in ({'allow_live_control':True},{'paths':{'audit_directory':'other'}},{'cache_directory':'other'}):
                with self.assertRaises(ValueError): handle('native-macro-prepare',dict(name='native-health',rest=[],**extra),**startup)
            with self.assertRaises(PermissionError):
                handle('native-macro-prepare',dict(name='type-native',rest=['--text','--allow-live-control']),**startup)
            self.assertEqual(list(Path(folder).iterdir()),[])
            with self.assertRaises(ValueError):handle('native-macro-prepare',dict(name='native-health',rest=[]))

    def test_invalid_completion_and_reply_fail_before_trajectory_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            startup=dict(cache_directory=folder,audit_directory=folder,allow_live_control=True)
            request=dict(name='uia-invoke',rest=['--label','Owned'],prepared={'label':'Owned','unknown':True},brief=True,
                reply=dict(ExitCode=0,Json={'status':'ok'},Raw='{}',Err='',ElapsedMs=1))
            with self.assertRaises(LegacyHostError):handle('native-macro-complete',request,**startup)
            request['prepared']={'label':'Owned'};request['reply']['ExitCode']=True
            with self.assertRaises(ValueError):handle('native-macro-complete',request,**startup)
            self.assertEqual(list(Path(folder).iterdir()),[])
