"""Exact SmartPlan captured-reply qualification; external probes only are stubbed."""
import copy
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = 'bf895d3120dd5e145f360cb1c41e1d79a061d048'
PROJECT = ROOT / 'pcucp-next/dotnet/PcuCp.LegacySmartPlan.ContractTests'


def fixtures():
    top = dict(score=80, text='Save', role='Button', automation_id='save', invoke_pattern='Invoke',
               rect=dict(x=1,y=2,width=30,height=20), click_point=dict(x=15,y=12))
    base = dict(rest=['--label','Save'], cache_seconds=7, brief=False, history=None, port=False,
                cdp=dict(ExitCode=0,Json=dict(status='ok',score=90,matched_text='Save',tag_name='button',role='button',page_title='Page',rect=None)),
                uia=dict(ExitCode=0,Json=dict(status='ok',top=top,ambiguous=False)),
                ocr=dict(ExitCode=0,Json=dict(status='ok',recommendation='uia_invoke',ocr_top=dict(score=80,text='Save'),uia_match=None,invoke_pattern='Invoke')))
    result=[]
    for flags, pattern, point in itertools.product(
            ([], ['--precision-points','--match','Window'], ['--include-ocr'], ['--type-text',''], ['--type-text','안녕😀','--match','Window','--press-enter','--clear-first']),
            ('Invoke','',None), (dict(x=15,y=12),dict(x=0,y=12),None)):
        f=copy.deepcopy(base);f['rest']+=flags;f['uia']['Json']['top'].update(invoke_pattern=pattern,click_point=point);result.append(f)
    for cdp_status, uia_status, ocr_rec in itertools.product(('ok','partial'), ('ok','partial'), ('uia_invoke','ocr_click','none')):
        f=copy.deepcopy(base);f.update(port=True);f['rest']+=['--allow-cdp','--include-ocr','--cdp-page-match','Page','--role','Button'];f['cdp']['Json']['status']=cdp_status;f['uia']['Json']['status']=uia_status;f['ocr']['Json']['recommendation']=ocr_rec;result.append(f)
    for value, readonly in itertools.product((True,False,'false',None),(True,False,'false',None)):
        f=copy.deepcopy(base);f['rest']+=['--type-text','text','--match','Window'];f['uia']['Json']['top'].update(value_pattern=value,value_readonly=readonly);result.append(f)
    for exitcode, jsonvalue in itertools.product((0,2,3,124),(None,{},dict(status='error',reason='blocked'),dict(status='ok',top={},ambiguous=False))):
        f=copy.deepcopy(base);f['uia']=dict(ExitCode=exitcode,Json=jsonvalue);result.append(f)
    for extras in (['--allow-cdp'],['--cdp-port','0'],['--allow-cdp','--no-cdp'],['--point-plan','--window',"한글 O'Brien",'--point-radius','99','--point-step','0','--cache-ttl','-4'],
                   ['--label','Other'],['--LABEL','Other','--json-only'],['--precision-radius','bad'],['--cdp-port','bad']):
        f=copy.deepcopy(base);f['rest']+=extras;result.append(f)
    for history in (None,{},dict(strategy='old',nested=dict(labels=['a',None,3])),['first','second'],[],['single'],[None],[['nested','values']]):
        f=copy.deepcopy(base);f['history']=history;result.append(f)
    for top_override in ({'score':-40},{'score':60},{'score':100},{'score':'bad'},{'ambiguous':True}):
        f=copy.deepcopy(base);f['uia']['Json']['top'].update(top_override);result.append(f)
    for score in (69,70,0,'bad'):
        f=copy.deepcopy(base);f['rest']+=['--include-ocr'];f['ocr']['Json'].update(recommendation='ocr_click',ocr_top=dict(score=score));result.append(f)
    for precision in (False,True):
        f=copy.deepcopy(base);f.update(port=True);f['rest']+=['--allow-cdp','--include-ocr','--match','W'];f['cdp'].update(ExitCode=124);f['cdp']['Json']['score']=0
        f['uia']['Json']['top']['score']=175 if precision else 60;f['ocr']['Json']['ocr_top']['score']=370
        if precision:f['rest']+=['--precision-points'];f['uia']['Json']['top']['invoke_pattern']=''
        result.append(f)
    for stage in ('history','port','uia','cdp','ocr'):
        f=copy.deepcopy(base);f.update(port=True,throw_stage=stage);f['rest']+=['--allow-cdp','--include-ocr'];result.append(f)
    for rest in ([],['--label'],['--label',''],['--label','--match','Window']):
        f=copy.deepcopy(base);f['rest']=rest;result.append(f)
    for score in (-2147483649,-2147483648,-2147483647,2147483602,2147483603,2147483646,2147483647,2147483648,1.5,2.5):
        for route in ('cdp','uia_pattern','uia_value','precision','ocr'):
            f=copy.deepcopy(base)
            if route=='cdp':f.update(port=True);f['rest']+=['--allow-cdp'];f['cdp']['Json']['score']=score
            elif route=='ocr':f['rest']+=['--include-ocr'];f['ocr']['Json']['ocr_top']['score']=score
            else:
                f['uia']['Json']['top']['score']=score
                if route=='uia_value':f['rest']+=['--type-text','text'];f['uia']['Json']['top']['value_pattern']=True
                if route=='precision':f['rest']+=['--precision-points','--match','W'];f['uia']['Json']['top']['invoke_pattern']=''
            result.append(f)
    for option,value in itertools.product(('--precision-radius','--precision-step','--point-cache-ttl','--cdp-port'),('1.5','2.5','bad','2147483648','-2147483649')):
        f=copy.deepcopy(base);f['rest'] += [option,value];result.append(f)
    # Both render modes must retain the same exit and acquisition sequence.
    for f in copy.deepcopy(result[:6]): f['brief']=True;result.append(f)
    return result


CAPTURE_RUNNER = r'''
param([string]$Source,[string]$InputPath,[switch]$CurrentBridge,[switch]$ExactConsole)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$names=@('_Read-OptValue','_Read-Switch','_TaskPlan-QuoteToken','_TaskPlan-StepString','Invoke-MacroSmartPlan')
if($CurrentBridge){$names=@('_Invoke-LegacyCompatibility')+$names}
foreach($name in $names) {
 $fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($fn.Count -ne 1){throw "Expected exact source function $name"}
 $body=$fn[0].Extent.Text
 if($ExactConsole -and $name -eq 'Invoke-MacroSmartPlan') {
   $pattern='(?m)^[ \t]*if \(\$Brief'
   $matches=[regex]::Matches($body,$pattern)
   if($matches.Count -ne 1){throw 'Expected one SmartPlan pre-format elapsed seam'}
   # Only elapsed changes, immediately before the original formatting branch.
   # Both original $payload and retained-adapter $state.payload are supported.
   $seam='$elapsed=0; if (Get-Variable payload -Scope Local -ErrorAction SilentlyContinue) { $payload.elapsed_ms=0 }; if (Get-Variable state -Scope Local -ErrorAction SilentlyContinue) { $state.payload.elapsed_ms=0 };' + "`n"
   $body=$body.Insert($matches[0].Index,$seam)
 }
 . ([scriptblock]::Create($body))
}
function Capture-Reply($kind,$argv,$stage,$result) {
 [void]$script:queries.Add([ordered]@{kind=$kind;argv=@($argv)})
 if($script:fixture.throw_stage -eq $stage){[void]$script:replies.Add(@{kind=$kind;argv=@($argv);error="fixture_$stage"});throw "fixture_$stage"}
 [void]$script:replies.Add(@{kind=$kind;argv=@($argv);result=$result})
 Write-Output -NoEnumerate $result
}
function _History-PickBestStrategy {param($Label,$Match,$LookbackN) Capture-Reply 'history' @("$Label","$Match","$LookbackN") 'history' $script:fixture.history}
function Test-CdpPortQuick {param($Port,$TimeoutMs) Capture-Reply 'cdp_port' @("$Port","$TimeoutMs") 'port' $script:fixture.port}
function Invoke-NativeHelper {param([string[]]$ArgList)
 $stage=if($ArgList[1] -eq 'uia-find'){'uia'}elseif($ArgList[1] -eq 'ocr-uia-fuse'){'ocr'}else{'cdp'}
 Capture-Reply 'native' $ArgList $stage $script:fixture.$stage
}
$all=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)) {
 $script:fixture=$fixture;$script:queries=New-Object Collections.ArrayList;$script:replies=New-Object Collections.ArrayList
 $CacheSeconds=[int]$fixture.cache_seconds;$Brief=[bool]$fixture.brief
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
 try {
  $exitCode=Invoke-MacroSmartPlan -Rest $fixture.rest
  $console=$writer.ToString()
  $raw=$console.TrimEnd([char[]]"`r`n")
  if($Brief -and -not ($fixture.rest -contains '--json-only')) {$payload=$null;$brief=$raw -replace 'elapsed_ms=\d+','elapsed_ms=0'}
  else {$payload=$raw|ConvertFrom-Json;$payload.elapsed_ms=0;$brief=$null}
  $expected=@{state='complete';payload=$payload;exit=[int]$exitCode;brief=$brief;queries=@($script:queries)}
 }catch{$expected=@{state='error';error=$_.Exception.Message;queries=@($script:queries)}}
 finally{[Console]::SetOut($previous);if($ExactConsole){$expected['console']=$writer.ToString()};$writer.Dispose()}
 [void]$all.Add(@{expected=$expected;args=@{rest=@($fixture.rest);cache_seconds=$CacheSeconds;brief=$Brief;elapsed_ms=0;captured_replies=@($script:replies)}})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 64 -Compress))
'''


class SmartPlanSourceTests(unittest.TestCase):
    def test_isolated_and_fixture_matrix(self):
        source=(ROOT/'pcucp-next/dotnet/PcuCp.LegacySmartPlan/LegacySmartPlanKernel.cs').read_text()
        for forbidden in ('Process.Start','System.Management.Automation','HttpClient','File.Read','SendInput'):
            self.assertNotIn(forbidden,source)
        self.assertGreaterEqual(len(fixtures()),100)
        self.assertTrue((PROJECT/'PcuCp.LegacySmartPlan.ContractTests.csproj').is_file())
        self.assertNotEqual((ROOT/'pcucp-next/dotnet/PcuCp.LegacySmartPlan').parent.name,'PcuCp.NativeHost')


@unittest.skipUnless(sys.platform=='win32','Requires Windows PowerShell 5.1 captured-reply differential')
class SmartPlanWindowsTests(unittest.TestCase):
    maxDiff=None
    def test_exact_payload_query_order_errors_brief_and_exit(self):
        cases=fixtures()
        with tempfile.TemporaryDirectory(prefix='CUCP smart-plan 한글 ') as tmp:
            root=Path(tmp);source=root/'original.ps1';source.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            data=root/'fixtures.json';data.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            runner=root/'capture.ps1'
            runner.write_text(CAPTURE_RUNNER,encoding='utf-8-sig')
            original=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),'-Source',str(source),'-InputPath',str(data)],capture_output=True,timeout=90)
            self.assertEqual(original.returncode,0,original.stderr.decode('utf-8',errors='replace'))
            captured=json.loads(original.stdout.decode('utf-8-sig'))
            build=subprocess.run([shutil.which('dotnet'),'build',str(PROJECT),'-c','Release','--output',str(root/'build')],capture_output=True,timeout=90)
            self.assertEqual(build.returncode,0,build.stdout.decode('utf-8',errors='replace'))
            command=[shutil.which('dotnet'),str(root/'build/PcuCp.LegacySmartPlan.ContractTests.dll')]
            after=subprocess.run(command,input=json.dumps([c['args'] for c in captured],ensure_ascii=True).encode(),capture_output=True,timeout=30)
            self.assertEqual(after.returncode,0,after.stderr.decode('utf-8',errors='replace'))
            results=json.loads(after.stdout)
            self.assertEqual(len(captured),len(cases))
            self.assertEqual(len(results),len(cases))
            for fixture,old,new in zip(cases,captured,results):
                with self.subTest(fixture=fixture):
                    expected=old['expected']
                    # Brief mode deliberately doesn't serialize the original payload;
                    # compare its exact brief/exit/query result, with payload covered by JSON cases.
                    if expected.get('brief') is not None:new={**new,'payload':None}
                    self.assertEqual(new,expected)
            # Every captured prefix must request exactly the next original query.
            prefixes=[];expected_queries=[]
            for old in captured:
                for index,reply in enumerate(old['args']['captured_replies']):
                    prefixes.append({**old['args'],'captured_replies':old['args']['captured_replies'][:index]})
                    expected_queries.append(old['expected']['queries'][:index+1])
            process=subprocess.run(command,input=json.dumps(prefixes,ensure_ascii=True).encode(),capture_output=True,timeout=30)
            self.assertEqual(process.returncode,0,process.stderr)
            prefix_results=json.loads(process.stdout)
            self.assertEqual(len(prefix_results),len(expected_queries))
            for new,trace in zip(prefix_results,expected_queries):
                self.assertEqual(new,dict(state='query',query=trace[-1],queries=trace))


@unittest.skipUnless(sys.platform=='win32' and os.environ.get('CUCP_SMART_PLAN_TEST_HOST'),
                     'Requires Windows retained SmartPlan adapter and matching native host')
class SmartPlanAdapterWindowsTests(unittest.TestCase):
    maxDiff=None

    def test_actual_adapter_payload_console_errors_exit_and_queries(self):
        cases=fixtures()
        with tempfile.TemporaryDirectory(prefix='CUCP smart adapter 한글 ') as temp:
            root=Path(temp)
            original=root/'original.ps1'
            original.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            inputs=root/'fixtures.json'
            inputs.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            runner=root/'capture.ps1';runner.write_text(CAPTURE_RUNNER,encoding='utf-8-sig')
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),'-InputPath',str(inputs),'-ExactConsole']
            env={**os.environ,'CUCP_NATIVE_HOST':os.environ['CUCP_SMART_PLAN_TEST_HOST']}
            before=subprocess.run([*command,'-Source',str(original)],capture_output=True,timeout=90,env=env)
            after=subprocess.run([*command,'-Source',str(ROOT/'scripts/cucp.ps1'),'-CurrentBridge'],capture_output=True,timeout=600,env=env)
            self.assertEqual(before.returncode,0,before.stderr.decode('utf-8',errors='replace'))
            self.assertEqual(after.returncode,0,after.stderr.decode('utf-8',errors='replace'))
            old=json.loads(before.stdout.decode('utf-8-sig'));new=json.loads(after.stdout.decode('utf-8-sig'))
            self.assertEqual(len(old),len(cases));self.assertEqual(len(new),len(cases))
            for fixture,left,right in zip(cases,old,new):
                with self.subTest(fixture=fixture):
                    # Console is the actual StringWriter output including CRLF,
                    # indentation, property order and ConvertTo-Json depth behavior.
                    # Do not reserialize payloads or normalize emitted Console text.
                    self.assertEqual(right['expected'],left['expected'])
