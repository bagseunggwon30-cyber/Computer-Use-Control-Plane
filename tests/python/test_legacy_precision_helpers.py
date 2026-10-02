"""Helper and generated-file parity for the pinned precision family."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_legacy_precision_parity import BASELINE_TREE, ROOT, runner_command, run_batch


def helper_cases():
    cases=[]
    def add(op, **args):cases.append(dict(operation=op,args=args))
    for value in ('high','HIGH','medium','low','unknown',''):
        add('confidence-rank',value=value)
    for width,height in ((0,0),(1,1),(20,100),(21,43),(44,60),(45,50),(140,100),(141,100),(100,101)):
        for area in (-1,0,1,900,901,2200,2201):add('size-class',rect=dict(width=width,height=height),area=area)
    for point in (None,{},dict(x=9,y=9),dict(x=10,y=10),dict(x=-1,y=0),dict(x=1.5,y=2.5)):
        for rect in (None,{},dict(x=0,y=0,width=10,height=10),dict(x=-200,y=-100,width=30,height=20)):
            add('edge-distance',point=point,rect=rect)
    for a,b in ((None,None),({},{}),(dict(x=0,y=0),dict(x=3,y=4)),(dict(x='bad',y=1),dict(x=0,y=0))):add('history-distance',a=a,b=b)
    record=dict(anchor_id='A',target_match='Window',process='app',**{'class':'Frame'},normalized_window_point=dict(x=.5,y=.5),safe_to_reuse=True,coordinate_risk='low',coord_signature='one')
    for count in (0,1,2,5,9):
        for safe in (True,False,'true','false',1,0):
            records=[dict(record,safe_to_reuse=safe,ts=f'time-{n}',screen_point=dict(x=n,y=n)) for n in range(count)]
            add('history-score',record=record,records=records,history_file='H',tolerance=.012)
    for tolerance in (-1,0,.001,.012,1):
        recs=[dict(record,anchor_id='b',normalized_window_point=dict(x=.512,y=.5),coord_signature='two'),dict(record,anchor_id='',target_match='other')]
        add('history-score',record=record,records=recs,history_file='H',tolerance=tolerance)
    add('history-score',record=None,records=[],history_file='H',tolerance=.012)
    add('history-score',record={'value':[1,2],'Count':2},records=[{'value':[1,2],'Count':2}],history_file='H',tolerance=.012)
    for x in (0,1,-1,2147483647):
        add('cache-key',x=x,y=2,radius=6,step=2,click_inset=2,target_hwnd=42,target_match='한글 K',precheck=dict(root_hwnd=123,root_title='Window',process_name='Test'),coord_signature='ABC')
    return cases


HELPER_RUNNER=r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('Get-CacheKey','_AnchorHistory-NormDistance','_AnchorHistory-Score','_PointPlan-CacheKey','_TargetValidate-ConfidenceRank','_TargetValidate-SizeClass','_TargetValidate-PointEdgeDistance')){
 $n=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true));if($n.Count -ne 1){throw $name};. ([scriptblock]::Create($n[0].Extent.Text))
}
function _AnchorHistory-Read {param($Last) foreach($r in @($script:fixtureArgs.records)){$r}}
$all=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixtureArgs=$case.args;$a=$case.args;$Script:AnchorHistoryFile=$a.history_file
 try{
  $value=switch($case.operation){
   'confidence-rank'{_TargetValidate-ConfidenceRank -Confidence $a.value}
   'size-class'{_TargetValidate-SizeClass -Rect $a.rect -Area $a.area}
   'edge-distance'{_TargetValidate-PointEdgeDistance -Point $a.point -Rect $a.rect}
   'history-distance'{_AnchorHistory-NormDistance -A $a.a -B $a.b}
   'history-score'{_AnchorHistory-Score -Record $a.record -Tolerance $a.tolerance}
   'cache-key'{_PointPlan-CacheKey -X $a.x -Y $a.y -Radius $a.radius -Step $a.step -ClickInset $a.click_inset -TargetHwnd $a.target_hwnd -TargetMatch $a.target_match -Precheck $a.precheck -CoordSignature $a.coord_signature}
  }
  [void]$all.Add(@{state='complete';payload=$value})
 }catch{[void]$all.Add(@{state='error';error=$_.Exception.Message})}
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 64 -Compress))
'''


class PrecisionHelperSourceTests(unittest.TestCase):
    def test_helper_boundaries(self):
        self.assertGreater(len(helper_cases()),100)
        self.assertEqual({c['operation'] for c in helper_cases()},{'confidence-rank','size-class','edge-distance','history-distance','history-score','cache-key'})


@unittest.skipUnless(sys.platform=='win32','Requires pinned Windows PowerShell helper oracle')
class PrecisionHelperWindowsTests(unittest.TestCase):
    maxDiff=None
    def test_helper_payloads_and_errors(self):
        cases=helper_cases()
        with tempfile.TemporaryDirectory(prefix='CUCP precision helpers ') as tmp:
            root=Path(tmp);source=root/'original.ps1';source.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            data=root/'fixtures.json';data.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            runner=root/'helpers.ps1';runner.write_text(HELPER_RUNNER,encoding='utf-8-sig')
            old=subprocess.run(['powershell.exe','-NoProfile','-File',str(runner),'-Source',str(source),'-InputPath',str(data)],capture_output=True,timeout=90)
            self.assertEqual(old.returncode,0,old.stderr.decode(errors='replace'));expected=json.loads(old.stdout.decode('utf-8-sig'))
            actual=run_batch(runner_command(root),cases)
            for case,before,after in zip(cases,expected,actual):
                with self.subTest(case=case):
                    self.assertEqual({k:v for k,v in after.items() if k in ('state','payload','error')},before)


if __name__=='__main__':unittest.main()
