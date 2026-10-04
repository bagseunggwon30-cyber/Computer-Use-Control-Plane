"""Python replacement of the original six read-only CUCP smoke checks."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class PythonEntrySyntaxTests(unittest.TestCase):
    def test_python_installer_and_helper_entry_points_parse(self):
        for name in ('install.py','scripts/cucp-native-helper.py','scripts/cucp-helper-server.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8-sig'),filename=name)


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_REQUIRE_LEGACY_FAST_SMOKE')=='1','Explicit published Windows read-only smoke gate')
class LegacyFastSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='CUCP-fast-smoke-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();cli=self.root/'src/cli.mjs';cli.parent.mkdir()
        cli.write_text('// ControlPlane owned fixture\nconsole.log(JSON.stringify({status:"ok"}));',encoding='utf-8')
        (self.root/'package.json').write_text('{"version":"0.0.0"}',encoding='utf-8')
        self.env=dict(os.environ,TEMP=str(self.root),TMP=str(self.root),CUCP_CLI_PATH=str(cli))
        self.env.pop('CUCP_STAGED_COMPILED_HELPER',None)
        self.env.pop('CUCP_STAGED_HELPER_READONLY_DESKTOP',None)

    def call(self,*arguments,expected=0):
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/cucp.ps1'),
            '-Quiet',*arguments],env=self.env,capture_output=True,timeout=30)
        self.assertIn(result.returncode,(expected,) if type(expected) is int else expected,result.stderr.decode('utf-8',errors='replace'))
        self.last_exit=result.returncode
        return result.stdout.decode('utf-8-sig')

    def test_unified_version_envelope(self):
        value=json.loads(self.call('version'));self.assertEqual(value['schema'],'cucp.version/v1')
        self.assertTrue(value['versions']['skill']);self.assertEqual(value['versions']['helper_server'],'2.0.0')
        self.assertEqual(value['sources']['helper_server'],'pcucp-next/bin/legacy-helper/manifest.json')

    def test_health_brief_has_no_helper_startup(self):
        self.assertIn('health-quick',self.call('-Brief','macro','health-quick',expected=(0,1)))
        value=json.loads(self.call('macro','health-quick',expected=(0,1)))
        if value['status']=='fail':
            self.assertEqual(self.last_exit,1)
            self.assertFalse(value['components']['win32_enum']['ok'])
            self.assertTrue(all(row['ok'] for name,row in value['components'].items() if name!='win32_enum'))
        else:
            self.assertEqual(value['status'],'ok');self.assertEqual(self.last_exit,0)
        self.assertFalse((self.root/'computer-use-control-plane/helper.pid').exists())

    def test_windows_observation_envelope(self):
        value=json.loads(self.call('macro','windows','--json-only',expected=(0,2)))
        self.assertEqual(value['schema'],'cucp.observation/v1');self.assertEqual(value['kind'],'windows')
        if value['status']=='partial':
            self.assertEqual(self.last_exit,2)
            self.assertIn('no_visible_windows',[row['code'] for row in value['recoverable_errors']])
        else:
            self.assertEqual(value['status'],'ok');self.assertEqual(self.last_exit,0)

    def test_cleanup_dry_run_has_no_deletions(self):
        value=json.loads(self.call('macro','cleanup','--dry-run','--json-only'))
        self.assertEqual(value['schema'],'cucp.cleanup/v1');self.assertEqual(value['mode'],'dry-run')
        self.assertEqual(value['deleted_count'],0)

    def test_governance_recorder_list_and_policy_confirmation_remain_available(self):
        self.call('macro','recorder','list')
        self.assertIn('require_confirm',self.call('-Brief','macro','policy-check','--action','click-label'))
