"""Independent pinned hit macro options, reports and readonly fast dispatch."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcucp_cli.legacy_host_protocol import Authority, LegacyHostError
from pcucp_cli.legacy_native_macros import NativeMacros

ROOT=Path(__file__).resolve().parents[2]
BASE='3916e00a43639a64a38883fc99401e25b77d82db'
HANDLERS=('Invoke-MacroHitTest','Invoke-MacroHitScan')

def project(value):
    if isinstance(value,dict):
        return {key:project(item) for key,item in value.items() if key!='elapsed_ms'}
    if isinstance(value,list):return [project(item) for item in value]
    return value

def cases():
    hit=dict(status='ok',root_hwnd=42,root_title='Owned 한글',process_name='owned',matched=True,
             match_reason='hwnd_match',uia_skipped=True)
    scan=dict(status='ok',best=dict(role='Button',final_score=93,support=3),
              recommended_point=dict(x=4,y=5,confidence='high',point_source='uia'),sample_count=9,target_matched_samples=3)
    rests=[['--x','4','--y','5'],['--x','0x4','--y','5','--target-hwnd','-1','--click-inset','-1'],
           ['--x','4','--y','5','--target-match','Owned --fast','--target-hwnd','0x2a','--no-uia'],
           ['--x','4','--y','5','--radius','-1','--step','0'],
           ['--x','4','--y','5','--radius','0x6','--step','2'],
           ['--x','bad','--y','5'],['--x','0','--y','5'],
           ['--x','4','--y','5','--target-hwnd','2147483648'],
           ['--x','4','--y','5','--radius','bad']]
    result=[]
    for name,base in [('hit-test',hit),('hit-scan',scan)]:
        payloads=[base,{**base,'status':'partial','reason':''},None,{},dict(hit,uia_point={}),
                  dict(hit,uia_point=dict(refined_x=4,refined_y=5,role='Button',score=92,point_source='uia'))]
        for rest in rests:
            for brief in (False,True):
                for payload in payloads if rest==rests[0] else [base]:
                    result.append(dict(name=name,rest=rest,brief=brief,fast=hit,reply=dict(ExitCode=2,Json=payload,
                        Raw='RAW owned 한글\n',Err='',ElapsedMs=7)))
        if name=='hit-test':
            for rest in rests:
                for brief in (False,True):
                    for status in ('ok','partial','unexpected') if rest==rests[0] else ('ok',):
                        result.append(dict(name=name,rest=rest+['--fast'],brief=brief,fast={**hit,'status':status},
                            reply=dict(ExitCode=2,Json=hit,Raw='ignored',Err='',ElapsedMs=7)))
    return result

class HitBoundaryTests(unittest.TestCase):
    def test_bad_coordinates_and_completion_never_acquire_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            runtime=NativeMacros(lambda *args:calls.append(args),cache_directory=folder,audit_directory=folder,
                                 fast_hit=lambda *args:calls.append(args))
            for name in ('hit-test','hit-scan'):
                with self.assertRaises((ValueError,LegacyHostError)):runtime.run(name,['--x','bad','--y','1'])
            with self.assertRaises(LegacyHostError):
                runtime.complete('hit-test',[],dict(Json={},ExitCode=0,Raw='',Err='',ElapsedMs=0),
                    dict(x=1,y=1,fast=True,target_hwnd=0,target_match='',allow_live_control=True))
            self.assertEqual(calls,[])
            self.assertEqual(list(Path(folder).iterdir()),[])

@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Actual pinned Windows macro functions')
class HitParityTests(unittest.TestCase):
    def test_original_and_production_argv_reports_failures_and_fast_path(self):
        with tempfile.TemporaryDirectory(prefix='CUCP hit oracle ') as directory:
            owned=Path(directory);source=owned/'original.ps1'
            source.write_bytes(subprocess.check_output(['git','show',BASE+':scripts/cucp.ps1'],cwd=ROOT))
            rows=cases();inputs=owned/'cases.json';inputs.write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8-sig')
            oracle=owned/'oracle.ps1'
            oracle.write_text(r'''
param([string]$Source,[string]$Cases,[string]$Cache,[switch]$Current)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$names=@('_Read-OptValue','_Read-Switch','Invoke-MacroHitTest','Invoke-MacroHitScan')
if($Current){$names+='_Invoke-LegacyNativeMacro';$Script:LegacyCdpSourceRoot=Split-Path -Parent (Split-Path -Parent $Source);. (Join-Path $Script:LegacyCdpSourceRoot 'scripts/cucp-legacy-cdp-adapter.ps1')}
foreach($name in $names){$f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true));if($f.Count -ne 1){throw 'Missing function.'};. ([scriptblock]::Create($f[0].Extent.Text))}
function Invoke-NativeHelper {param([string[]]$ArgList) $script:argv=@($ArgList);return $script:reply}
function _Native-HitTestPoint {param([int]$X,[int]$Y,[int]$TargetHwnd,[string]$TargetMatch) $script:fastCalls++;return $script:fast.PSObject.Copy()}
$Script:CacheDir=$Cache;$Script:AuditDir=$Cache;$AllowLiveControl=$false
$output=New-Object Collections.ArrayList
foreach($row in (Get-Content -LiteralPath $Cases -Raw -Encoding UTF8|ConvertFrom-Json)){
 $Brief=[bool]$row.brief;$script:argv=@();$script:fastCalls=0;$script:reply=$row.reply;$script:fast=$row.fast
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out;$failed=$false;$exit=$null
 try{[Console]::SetOut($writer);$name=if($row.name -eq 'hit-test'){'Invoke-MacroHitTest'}else{'Invoke-MacroHitScan'};$exit=& $name -Rest ([string[]]$row.rest)}
 catch{$failed=$true}finally{[Console]::SetOut($previous)}
 [void]$output.Add(@{failed=$failed;exit=$exit;argv=$script:argv;fast_calls=$script:fastCalls;output=$writer.ToString()});$writer.Dispose()
}
[Console]::WriteLine((ConvertTo-Json -InputObject @($output) -Depth 32 -Compress))
''',encoding='utf-8-sig')
            hosts=list(filter(None,(shutil.which('powershell.exe'),shutil.which('pwsh.exe'))))
            for host in hosts:
                def capture(path,current=False):
                    command=[host,'-NoProfile','-NonInteractive','-File',str(oracle),'-Source',str(path),'-Cases',str(inputs),'-Cache',str(owned)]
                    if current:command+=['-Current']
                    process=subprocess.run(command,capture_output=True,timeout=300)
                    self.assertEqual(process.returncode,0,process.stderr.decode('utf-8',errors='replace'))
                    return json.loads(process.stdout.decode('utf-8-sig'))
                expected=capture(source);production=capture(ROOT/'scripts/cucp.ps1',True)
                self.assertEqual(len(production),len(expected))
                for row,before,after in zip(rows,expected,production):
                    with self.subTest(host=Path(host).name,name=row['name'],rest=row['rest'],brief=row['brief'],payload=row['reply']['Json']):
                        self.assertEqual(after['failed'],before['failed'])
                        if before['failed']:continue
                        self.assertEqual(after['argv'],before['argv']);self.assertEqual(after['fast_calls'],before['fast_calls'])
                        self.assertEqual(after['exit'],before['exit'])
                        fast=row['name']=='hit-test' and '--fast' in row['rest']
                        if fast and not row['brief']:
                            self.assertEqual(project(json.loads(after['output'])),project(json.loads(before['output'])))
                        else:
                            normalize=lambda text:re.sub(r'elapsed_ms=\d+','elapsed_ms=N',text).replace('\r\n','\n')
                            self.assertEqual(normalize(after['output']),normalize(before['output']))
                        calls=[];fast_calls=[]
                        def native(argv,authority):
                            self.assertFalse(authority.live);calls.append(argv);return row['reply']
                        def fast_hit(*args):
                            fast_calls.append(args);return dict(row['fast'])
                        runtime=NativeMacros(native,cache_directory=owned,audit_directory=owned,fast_hit=fast_hit)
                        result=runtime.run(row['name'],row['rest'],brief=row['brief'])
                        self.assertEqual(calls,[before['argv']] if before['argv'] else [])
                        self.assertEqual(len(fast_calls),before['fast_calls']);self.assertEqual(result['exit'],before['exit'])
                        if row['brief']:self.assertEqual(normalize(result['brief']+'\n'),normalize(before['output']))
                        elif fast:self.assertEqual(project(result['payload']),project(json.loads(before['output'])))
                        else:self.assertEqual(result['raw'],before['output'])

if __name__=='__main__':unittest.main()
