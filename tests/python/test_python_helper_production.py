"""Actual default wrapper helper lifecycle in an owned TEMP tree; no input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_REQUIRE_PYTHON_HELPER_PRODUCTION')=='1', 'Explicit actual owned wrapper lifecycle gate')
class PythonHelperProductionTests(unittest.TestCase):
    def test_default_start_status_pipe_shutdown_reuses_fixed_python_transport(self):
        with tempfile.TemporaryDirectory(prefix='CUCP-helper-production-') as folder:
            temp=Path(folder).resolve(); cli=temp/'cli.mjs'
            cli.write_text('// ControlPlane owned fixture\nconsole.log(JSON.stringify({status:"ok"}));',encoding='utf-8')
            env=dict(os.environ,TEMP=str(temp),TMP=str(temp),CUCP_CLI_PATH=str(cli))
            env.pop('CUCP_STAGED_COMPILED_HELPER',None)
            env.pop('CUCP_STAGED_HELPER_READONLY_DESKTOP',None)
            def call(*arguments):
                result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/cucp.ps1'),
                    '-Quiet','macro','session',*arguments],env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                return json.loads(result.stdout)
            try:
                first=call('start-helper','--idle-timeout-ms','30000')
                self.assertEqual(first['status'],'ok')
                second=call('start-helper','--idle-timeout-ms','30000')
                self.assertTrue(second['reused']); self.assertEqual(second['pid'],first['pid'])
                status=call('helper-status')
                self.assertTrue(status['alive']);self.assertEqual(status['pid'],first['pid'])
                cold=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/cucp.ps1'),
                    '-Quiet','macro','native-health'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(cold.returncode,0,cold.stderr+cold.stdout)
                self.assertEqual(json.loads(cold.stdout)['helper_mode'],'persistent_server')
            finally:
                stopped=call('stop-helper')
                self.assertEqual(stopped['status'],'ok')
            self.assertFalse((temp/'computer-use-control-plane/helper.pid').exists())
