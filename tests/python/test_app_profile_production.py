"""Both shell transports retain the previously qualified production behavior."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_legacy_app_profile_parity import CAPTURE_RUNNER, fixtures, record_boundary_fixtures

ROOT=Path(__file__).resolve().parents[2]
BASELINE='cf3f031d15f6efb96a7890320c9821756efae873'


@unittest.skipUnless(sys.platform=='win32' and os.environ.get('CUCP_APP_PROFILE_TEST_HOST'),
                     'Requires Windows and matching native facade')
class AppProfileProductionTests(unittest.TestCase):
    def test_both_shells_preserve_transport_results_queries_errors_and_single_record(self):
        cases=[fixtures()[0],fixtures()[2],fixtures()[4],fixtures()[60],*record_boundary_fixtures()]
        for record in ({'Error':'failed'},[{'ERROR':None},{'error':False}],
                       [{'error':[False,False]}],[{'error':None},{'error':''}]):
            case=copy.deepcopy(record_boundary_fixtures()[0]);case['record']=record;cases.append(case)
        shells=['powershell.exe','pwsh.exe']
        self.assertTrue(all(shutil.which(shell) for shell in shells),'Both supported Windows shells required')
        env={**os.environ,'CUCP_NATIVE_HOST':os.environ['CUCP_APP_PROFILE_TEST_HOST']}
        with tempfile.TemporaryDirectory(prefix='CUCP profile ports 한글 ') as folder:
            root=Path(folder);old=root/'old.ps1'
            old.write_bytes(subprocess.check_output(['git','show',BASELINE+':scripts/cucp.ps1'],cwd=ROOT))
            runner=root/'capture.ps1';runner.write_text(CAPTURE_RUNNER,encoding='utf-8-sig')
            inputs=root/'fixtures.json';inputs.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            for shell in shells:
                command=[shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),
                         '-InputPath',str(inputs),'-CurrentBridge']
                results=[]
                for source in (old,ROOT/'scripts/cucp.ps1'):
                    process=subprocess.run([*command,'-Source',str(source)],env=env,capture_output=True,timeout=300)
                    self.assertEqual(process.returncode,0,process.stderr.decode('utf-8',errors='replace'))
                    results.append(json.loads(process.stdout.decode('utf-8-sig')))
                self.assertEqual(len(results[0]),len(cases))
                self.assertEqual(len(results[1]),len(cases))
                for index,(before,after) in enumerate(zip(*results)):
                    with self.subTest(shell=shell,index=index):
                        self.assertEqual(after['expected'],before['expected'])
                        self.assertEqual(after['bridge_calls'],before['bridge_calls'])
                        self.assertEqual(after['kernel_evaluations'],before['kernel_evaluations'])
                        self.assertEqual(after['bridge_calls_at_append'],before['bridge_calls_at_append'])


if __name__=='__main__':unittest.main()
