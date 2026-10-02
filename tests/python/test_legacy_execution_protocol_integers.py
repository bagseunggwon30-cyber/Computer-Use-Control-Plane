"""Strict integer representation compatibility at retained PS5/PS7 protocol guards."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
DRIVER=ROOT/'tests/fixtures/legacy-protocol-integers.ps1'
MIN_INT=-(2**31)
MAX_INT=2**31-1


def cases():
    rows=[]
    valid={
        'execution_elapsed':[MIN_INT,-1,0,MAX_INT], 'execution_sleep':[0,MAX_INT],
        'precision_x':[MIN_INT,0,MAX_INT], 'precision_y':[MIN_INT,0,MAX_INT],
        'precision_age':[0,5,MAX_INT], 'profile_score':[50,75,100],
        'diagnostic_tail':[1,262144,MAX_INT], 'diagnostic_current':[0], 'diagnostic_previous':[0],
        'diagnostic_sleep':[1,3000,8000], 'diagnostic_age':[600], 'diagnostic_count':[50],
    }
    wrong_domain={'execution_sleep':-1,'precision_age':-1,'profile_score':49,'diagnostic_tail':0,
                  'diagnostic_current':-1,'diagnostic_previous':-1,'diagnostic_sleep':8001,
                  'diagnostic_age':601,'diagnostic_count':51}
    for field,numbers in valid.items():
        variants=('coord-map','hit-test','coord-profile') if field in ('precision_x','precision_y') else ('',)
        for variant in variants:
            def add(value,representation,expected,accept):
                rows.append(dict(id=len(rows)+1,field=field,variant=variant,value=value,representation=representation,
                                 expected_number=expected,accept=accept,
                                 leaf_calls=int(accept and (field.startswith('precision_') or field=='profile_score'))))
            for number in numbers:
                for representation in ('int32','int64','json'):add(number,representation,number,True)
            baseline=numbers[-1] if field=='diagnostic_previous' else numbers[0]
            for value,representation in ((True,'json'),(False,'json'),(str(baseline),'json'),
                                         (baseline,'double'),(baseline,'decimal'),(None,'json'),
                                         (MIN_INT-1,'int64'),(MAX_INT+1,'int64')):
                add(value,representation,baseline,False)
            if field in wrong_domain:add(wrong_domain[field],'int64',baseline,False)
            if field=='profile_score':add(101,'int64',baseline,False)
    rows.append(dict(id=len(rows)+1,field='diagnostic_previous',variant='no-previous',value=None,
                     representation='json',expected_number=0,accept=True,leaf_calls=0))
    return rows


class ProtocolIntegerInventoryTests(unittest.TestCase):
    def test_inventory_covers_all_twelve_fields_and_numeric_representations(self):
        rows=cases()
        self.assertEqual(len({row['field'] for row in rows}),12)
        self.assertEqual({row['representation'] for row in rows},{'int32','int64','json','double','decimal'})
        self.assertTrue(all(any(r['accept'] and r['representation']=='int64' for r in rows if r['field']==field)
                            for field in {row['field'] for row in rows}))
        self.assertTrue(all(r['leaf_calls']==0 for r in rows if not r['accept']))
        self.assertEqual({r['variant'] for r in rows if r['field']=='precision_x'}, {'coord-map','hit-test','coord-profile'})


@unittest.skipUnless(sys.platform=='win32','Requires Windows PS5 and PS7 protocol readers')
class ProtocolIntegerWindowsTests(unittest.TestCase):
    def run_shell(self,shell):
        executable=shutil.which(shell)
        self.assertIsNotNone(executable,f'{shell} must run the same strict protocol cases')
        rows=cases()
        with tempfile.TemporaryDirectory(prefix='cucp-integer-guards-') as tmp:
            inputs=Path(tmp)/'cases.json';inputs.write_text(json.dumps(rows),encoding='utf-8-sig')
            result=subprocess.run([executable,'-NoProfile','-NonInteractive','-File',str(DRIVER),
                '-Source',str(ROOT/'scripts/cucp.ps1'),'-DiagnosticSource',str(ROOT/'scripts/cucp-legacy-diagnostic-adapter.ps1'),
                '-InputPath',str(inputs)],capture_output=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8-sig',errors='replace'))
        actual=json.loads(result.stdout.decode('utf-8-sig'))
        self.assertEqual(len(actual),len(rows))
        for row,value in zip(rows,actual):
            with self.subTest(shell=shell,field=row['field'],variant=row['variant'],value=row['value'],representation=row['representation']):
                self.assertEqual(value['id'],row['id'])
                self.assertEqual(value['accepted'],row['accept'],value.get('error'))
                self.assertEqual(value['leaf_calls'],row['leaf_calls'])
                if row['representation'] in ('int32','int64','double','decimal'):
                    self.assertEqual(value['type'],{'int32':'Int32','int64':'Int64','double':'Double','decimal':'Decimal'}[row['representation']])
                if row['representation']=='json' and type(row['value']) is int and row['accept']:
                    self.assertEqual(value['type'],'Int32' if shell=='powershell.exe' else 'Int64')
        print(f'{shell}: compared {len(rows)} strict integer guard cases with inert leaves')

    def test_powershell_5_integer_representations(self):self.run_shell('powershell.exe')
    def test_powershell_7_integer_representations(self):self.run_shell('pwsh')


if __name__=='__main__':unittest.main()
