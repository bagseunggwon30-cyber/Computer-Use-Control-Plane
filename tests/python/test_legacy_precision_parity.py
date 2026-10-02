"""Pinned precision-family differential. No live UI or input is invoked."""
import copy
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
PROJECT = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyPrecision.ContractTests'
KERNEL = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyPrecision'
NOW = '2026-10-02T01:02:03.0000000+00:00'


def fixtures():
    point = dict(x=110, y=110, confidence='high', point_source='native_clickable', native_clickable=True)
    rect = dict(x=100, y=100, width=40, height=40)
    best = dict(match=dict(rect=rect, area=1600), area=1600, support=3, role='Button', pattern='Invoke')
    precheck = dict(status='ok', matched=True, match_reason='title', root_hwnd=42, root_title='한글 창', process_name='fixture')
    profile = dict(status='ok', coordinate_risk='low', coord_signature='geometry-one', warnings=[], elapsed_ms=11)
    plan = dict(status='ok', safe_to_act=True, recommended_point=point, recommended_command=['macro','click-point','--x','110','--y','110'],
                precheck=precheck, coordinate_profile=profile, confidence='high', best=best, reason='')
    mapping = dict(status='ok', selected_window=dict(hwnd=42,title='한글 창',process='fixture', **{'class':'Window'},rect=dict(x=-100,y=0,width=400,height=400)),
                   normalized_window_point=dict(x=.525,y=.275),visible_window_clip=dict(x=0,y=0,width=300,height=400),
                   visible_window_point=dict(x=110,y=110), screen_point=dict(x=110,y=110),inside_window=True,inside_visible_clip=True,coordinate_profile=profile,warnings=[])
    common = dict(rest=['--x','110','--y','110','--target-match','한글 창'], cache_seconds=7,brief=False,now=NOW,
                  history_file='fixture-history.jsonl',history_max=500,cache_dir='fixture-cache',history_lines=[],append_result=True,
                  precheck=precheck,profile=profile,cache=None,scan=dict(ExitCode=0,ElapsedMs=7,Json=dict(status='ok',best=best,recommended_point=point,sample_count=49)),
                  plan_result=dict(exit=0,raw='captured child console',json=plan),mapping=mapping)
    cases=[]
    def add(op, **changes):
        f=copy.deepcopy(common);f.update(changes);f['operation']=op;cases.append(f);return f
    for operation in ('coord-anchor','point-plan','target-validate'):
        for brief in (False,True):
            add(operation,brief=brief)
            add(operation,brief=brief,rest=common['rest']+['--json-only'])
        for options in ([],['--x','0','--y','2'],['--x','1'],['--x','bad','--y','2'],['--x','1','--y','2','--target-hwnd','2147483648'],
                        ['--x','1','--y','2','--radius','-1','--step','0','--cache-ttl','-1'],['--x','1','--y','2','--radius','99','--step','99','--no-cache'],
                        ['--x','1','--y','2','--window',"한글 O'Brien"],['--x','1','--y','2','--target-match','','--match','fallback'],
                        ['--X','1','--Y','2','--x','4','--y','5']):
            add(operation,rest=options)
    for status in (None,{},dict(status='partial',reason='target_window_not_found'),dict(status='partial'),dict(status='error',reason='geometry')):
        add('coord-anchor',mapping=status)
    for risk in ('low','medium','high',None):
        for inside in (True,False):
            f=add('coord-anchor',rest=common['rest']+['--record-history']);f['mapping']['coordinate_profile']['coordinate_risk']=risk;f['mapping']['inside_visible_clip']=inside
    for flags in (['--no-history'],['--no-history','--record-history'],['--learn-history'],['--history-tolerance','0'],['--history-tolerance','1'],['--history-tolerance','.001']):
        add('coord-anchor',rest=common['rest']+flags)
    for lines in ([],['bad','', 'null'],[json.dumps(dict(anchor_id='other',target_match='한글 창',normalized_window_point=dict(x=.525,y=.275),safe_to_reuse=True,coord_signature='geometry-one',ts='old'))]*6):
        add('coord-anchor',history_lines=lines)
    for stage in ('mapping','history','precheck','profile','scan','cache','plan'):
        add('coord-anchor' if stage in ('mapping','history') else 'target-validate' if stage=='plan' else 'point-plan',throw_stage=stage)
    for guard in (None,{},dict(status='error',matched=False),dict(status='ok',matched='false')):
        add('point-plan',precheck=guard)
    for scan in (None,{},dict(ExitCode=124,ElapsedMs=3,Json=None),dict(ExitCode=2,ElapsedMs=8,Json=dict(status='partial',reason='none')),
                 dict(ExitCode=0,ElapsedMs=3,Json=dict(status='ok',recommended_point={},best={})),dict(ExitCode=0,ElapsedMs=3,Json=dict(status='ok',recommended_point=point,best={'deep':{'nested':{'array':[1,None,'한글']}}}))):
        add('point-plan',scan=scan)
    for cached in (dict(status='ok',confidence='high',recommended_point=point),dict(status='partial',reason='old'),dict(status='ok',recommended_point=None),{'value':[1,2],'Count':2}):
        add('point-plan',cache=dict(Json=cached,Path='fixture-cache/point-plan-cache.json',AgeMs=27))
    for child in (None,{},dict(exit=7,raw='not json',json=None),dict(exit=2,raw='',json={}),dict(exit=99,raw='',json=plan)):
        add('target-validate',plan_result=child)
    for confidence in ('low','medium','high','none','HIGH',''):
        for native in (False,True):
            for width,height in ((10,10),(44,32),(80,80),(200,200),(0,0)):
                f=add('target-validate');p=f['plan_result']['json'];p['confidence']=confidence;p['recommended_point']['native_clickable']=native;p['best']['pattern']='';p['best']['support']=1
                p['best']['match']['rect'].update(width=width,height=height);p['best']['area']=width*height
    for point_xy in ((100,100),(99,100),(139,139),(140,140),(110,110)):
        f=add('target-validate');f['plan_result']['json']['recommended_point'].update(x=point_xy[0],y=point_xy[1])
    for flags in (['--min-confidence','bad'],['--min-confidence','HIGH'],['--allow-large-surface'],['--no-cache'],['--click-inset','-1']):
        add('target-validate',rest=common['rest']+flags)
    for name,value in (('precheck',None),('coordinate_profile',None),('confidence',None),('recommended_command',[]),('recommended_point',None),('best',None),('safe_to_act',False)):
        f=add('target-validate');f['plan_result']['json'][name]=value
    f=add('target-validate');f['plan_result']['json']['coordinate_profile'].update(coordinate_risk='high',warnings=['z','a','Z',None,''])
    for command in ([],['single'],['macro',None,'click-point'],[['macro','click-point'],'--label',"O'Brien"],{'value':['macro','click-point'],'Count':2}):
        f=add('target-validate');f['plan_result']['json']['recommended_command']=command
    deep={'text':'depth cutoff','items':[1,None,'한글']}
    for _ in range(20):deep={'nested':deep}
    f=add('point-plan');f['scan']['Json']['best']['deep']=deep
    return cases


CAPTURE_RUNNER = r'''
param([string]$Source,[string]$InputPath,[string]$Adapter,[switch]$CurrentBridge)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Source did not parse'}
$names=@('_Read-OptValue','_Read-Switch','Get-CacheKey','_TaskPlan-QuoteToken','_TaskPlan-StepString','_AnchorHistory-NormDistance','_AnchorHistory-Score','Invoke-MacroCoordAnchor','_PointPlan-CacheKey','Invoke-MacroPointPlan','_TargetValidate-ConfidenceRank','_TargetValidate-SizeClass','_TargetValidate-PointEdgeDistance','Invoke-MacroTargetValidate','_Set-ObjectProperty')
if($CurrentBridge){$names+=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and ($n.Name -like '_Precision-*' -or $n.Name -like '_Invoke-LegacyPrecision*')},$true)|ForEach-Object {$_.Name})}
foreach($name in $names){
 $found=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($found.Count -ne 1){throw "Expected one source function $name"}
 $text=$found[0].Extent.Text
 if($name -eq '_Invoke-LegacyPrecision'){$text=$text.Replace('[Console]::Out.WriteLine($completed.console)','$script:FullPayload=$completed.state.payload; $script:Effects.Clear(); foreach($e in @($completed.state.effects)){[void]$script:Effects.Add($e)}; [Console]::Out.WriteLine($completed.console)')}
 if($name -like 'Invoke-Macro*'){
  $text=$text.Replace('if ($Brief -and -not $jsonOnly)', '$script:FullPayload=$payload; if ($Brief -and -not $jsonOnly)')
  $text=$text.Replace('[Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 8))','$script:FullPayload=$payload; [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 8))')
 }
 . ([scriptblock]::Create($text))
}
if($Adapter){
 $draftTokens=$null;$draftErrors=$null;$draft=[Management.Automation.Language.Parser]::ParseFile($Adapter,[ref]$draftTokens,[ref]$draftErrors)
 if($draftErrors.Count){throw 'Precision adapter did not parse'}
 foreach($f in @($draft.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true))){
  $text=$f.Extent.Text
  if($f.Name -eq '_Invoke-LegacyPrecision'){$text=$text.Replace('[Console]::Out.WriteLine($completed.console)','$script:FullPayload=$completed.state.payload; $script:Effects.Clear(); foreach($e in @($completed.state.effects)){[void]$script:Effects.Add($e)}; [Console]::Out.WriteLine($completed.console)')}
  . ([scriptblock]::Create($text))
 }
}
function Capture($kind,$parameters,$stage,$value){
 [void]$script:Queries.Add([ordered]@{kind=$kind;args=$parameters})
 if($script:f.throw_stage -eq $stage){[void]$script:Replies.Add(@{kind=$kind;args=$parameters;error="fixture_$stage"});throw "fixture_$stage"}
 [void]$script:Replies.Add(@{kind=$kind;args=$parameters;result=$value})
 # Objects shaped value/Count remain ordinary objects. Only actual arrays get
 # array transport; no Count-based guessing or ETS wrapper reconstruction.
 if($null -ne $value){Write-Output -NoEnumerate $value}
}
function _Build-CoordMap {param($From,$X,$Y,$NormX,$NormY,$HasNorm,$TargetHwnd,[string]$TargetMatch) Capture 'coord-map' ([ordered]@{from=$From;x=[int]$X;y=[int]$Y;norm_x=0;norm_y=0;has_norm=$false;target_hwnd=[int64]$TargetHwnd;target_match=$TargetMatch}) 'mapping' $script:f.mapping}
function _Native-HitTestPoint {param($X,$Y,$TargetHwnd,[string]$TargetMatch) Capture 'hit-test' ([ordered]@{x=[int]$X;y=[int]$Y;target_hwnd=[int]$TargetHwnd;target_match=$TargetMatch}) 'precheck' $script:f.precheck}
function _Build-CoordProfile {param($HasPoint,$X,$Y,$TargetHwnd,[string]$TargetMatch) Capture 'coord-profile' ([ordered]@{has_point=[bool]$HasPoint;x=[int]$X;y=[int]$Y;target_hwnd=[int64]$TargetHwnd;target_match=$TargetMatch}) 'profile' $script:f.profile}
function _Precision-HistoryLines {param([string]$Path) $null=Capture 'history-lines' ([ordered]@{path=$Path}) 'history' $script:f.history_lines;foreach($line in @($script:f.history_lines)){$line}}
function _AnchorHistory-Read {param($Last=500)
 $null=Capture 'history-lines' ([ordered]@{path=$Script:AnchorHistoryFile}) 'history' $script:f.history_lines
 foreach($line in @($script:f.history_lines | Select-Object -Last $Last)){if("$line".Trim()){try{$line|ConvertFrom-Json -ErrorAction Stop}catch{}}}
}
function _AnchorHistory-Append {param($Record)
 [void]$script:Effects.Add([ordered]@{kind='history-append';args=[ordered]@{path=$Script:AnchorHistoryFile;record=$Record;max=[int]$Script:AnchorHistoryMax};bind='reuse_history.recorded'})
 return [bool]$script:f.append_result
}
function _PointPlan-ReadCache {param($Key,$MaxAgeSeconds)
 if(-not $Key -or $MaxAgeSeconds -le 0){return $null}
 Capture 'cache-read' ([ordered]@{directory=$Script:CacheDir;key=$Key;max_age_seconds=[int]$MaxAgeSeconds}) 'cache' $script:f.cache
}
function _PointPlan-WriteCache {param($Key,$Payload)
 [void]$script:Effects.Add([ordered]@{kind='cache-write';args=[ordered]@{directory=$Script:CacheDir;key=$Key};bind='payload'})
}
function Invoke-NativeHelper {param([string[]]$ArgList) Capture 'hit-scan' ([ordered]@{argv=@($ArgList)}) 'scan' $script:f.scan}
function _TargetValidate-InvokePointPlanJson {param([string[]]$PointPlanArgs) Capture 'point-plan-child' ([ordered]@{argv=@($PointPlanArgs)}) 'plan' $script:f.plan_result}
function Get-Date { [DateTimeOffset]::Parse($script:f.now) }
$all=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:f=$fixture;$script:Queries=New-Object Collections.ArrayList;$script:Replies=New-Object Collections.ArrayList;$script:Effects=New-Object Collections.ArrayList;$script:FullPayload=$null
 $CacheSeconds=[int]$fixture.cache_seconds;$Brief=[bool]$fixture.brief;$Script:AnchorHistoryFile=$fixture.history_file;$Script:AnchorHistoryMax=[int]$fixture.history_max;$Script:CacheDir=$fixture.cache_dir
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
 try{
  $exitCode=switch($fixture.operation){'coord-anchor'{Invoke-MacroCoordAnchor -Rest $fixture.rest};'point-plan'{Invoke-MacroPointPlan -Rest $fixture.rest};'target-validate'{Invoke-MacroTargetValidate -Rest $fixture.rest}}
  $raw=$writer.ToString().TrimEnd([char[]]"`r`n")
  $briefText=if($Brief -and -not ($fixture.rest -contains '--json-only') -and $script:FullPayload.reason -ne 'point_plan_unparseable'){$raw -replace 'elapsed_ms=\d+','elapsed_ms=0'}else{$null}
  $depth=if($fixture.operation -eq 'coord-anchor'){if($script:FullPayload.status -eq 'ok'){14}else{12}}elseif($fixture.operation -eq 'point-plan'){12}elseif($script:FullPayload.reason -eq 'point_plan_unparseable'){8}else{18}
  $expected=@{state='complete';payload=$script:FullPayload;exit=[int]$exitCode;brief=$briefText;json_depth=$depth;queries=@($script:Queries);effects=@($script:Effects)}
 }catch{$expected=@{state='error';error=$_.Exception.Message;queries=@($script:Queries)}}
 finally{[Console]::SetOut($previous)}
 [void]$all.Add(@{expected=$expected;console=$writer.ToString();request=@{operation=$fixture.operation;args=@{rest=@($fixture.rest);cache_seconds=$CacheSeconds;brief=[bool]$fixture.brief;elapsed_ms=0;now=$fixture.now;history_file=$fixture.history_file;history_max=$fixture.history_max;cache_dir=$fixture.cache_dir;captured_replies=@($script:Replies)}}})
 $writer.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
'''


def normalize(value):
    if isinstance(value, dict):
        return {k: (0 if k == 'elapsed_ms' else normalize(v)) for k, v in value.items()}
    if isinstance(value, list):return [normalize(v) for v in value]
    return value


def runner_command(root):
    dotnet = os.environ.get('CUCP_PRECISION_DOTNET') or shutil.which('dotnet')
    if not dotnet: raise unittest.SkipTest('dotnet unavailable')
    output=root/'build'
    build=subprocess.run([dotnet,'build',str(PROJECT),'-c','Release','--output',str(output)],capture_output=True,timeout=120)
    if build.returncode: raise AssertionError(build.stdout.decode(errors='replace')+build.stderr.decode(errors='replace'))
    return [dotnet,str(output/'PcuCp.LegacyPrecision.ContractTests.dll')]


def run_batch(command, requests):
    proc=subprocess.run(command,input=json.dumps(requests,ensure_ascii=True).encode(),capture_output=True,timeout=90)
    if proc.returncode:raise AssertionError(proc.stderr.decode(errors='replace'))
    return json.loads(proc.stdout)


class PrecisionSourceTests(unittest.TestCase):
    def test_closed_engine_and_comprehensive_matrix(self):
        source='\n'.join(p.read_text() for p in KERNEL.glob('LegacyPrecision*cs') if p.name!='LegacyPrecisionStorage.cs')
        for forbidden in ('Process.Start','System.Management.Automation','HttpClient','File.Read','SendInput','File.Write','File.Append'):
            self.assertNotIn(forbidden,source)
        self.assertGreater(len(fixtures()),150)
        self.assertIn('"effects", Effects.ToArray()',source)
        self.assertIn('FullPayload',CAPTURE_RUNNER)
        self.assertNotIn('$brief=$',CAPTURE_RUNNER.lower())


@unittest.skipUnless(sys.platform=='win32','Requires pinned Windows PowerShell 5.1 differential')
class PrecisionWindowsTests(unittest.TestCase):
    maxDiff=None
    def test_payload_queries_brief_errors_and_exit(self):
        cases=fixtures()
        with tempfile.TemporaryDirectory(prefix='CUCP precision 한글 ') as tmp:
            root=Path(tmp);source=root/'original.ps1';source.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            data=root/'fixtures.json';data.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            runner=root/'capture.ps1';runner.write_text(CAPTURE_RUNNER,encoding='utf-8-sig')
            before=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),'-Source',str(source),'-InputPath',str(data)],capture_output=True,timeout=90)
            self.assertEqual(before.returncode,0,before.stderr.decode(errors='replace'))
            captured=json.loads(before.stdout.decode('utf-8-sig'));command=runner_command(root)
            actual=run_batch(command,[c['request'] for c in captured]);self.assertEqual(len(actual),len(cases))
            for fixture,old,new in zip(cases,captured,actual):
                with self.subTest(fixture=fixture):
                    expected=normalize(old['expected']);new=normalize(new)
                    # This boolean is the only local terminal-effect binding;
                    # completion never re-enters the kernel after a write.
                    if new.get('effects') and fixture['operation']=='coord-anchor':new['payload']['reuse_history']['recorded']=fixture['append_result']
                    self.assertEqual(new,expected)
            # Render the candidate through the same retained PS5 JSON boundary.
            # Compare Console separately: its finite depth is not the payload oracle.
            for fixture,state in zip(cases,actual):
                if state.get('effects') and fixture['operation']=='coord-anchor':state['payload']['reuse_history']['recorded']=fixture['append_result']
            rendered=root/'candidate.json';rendered.write_text(json.dumps(actual,ensure_ascii=True),encoding='utf-8-sig')
            formatter=root/'format.ps1';formatter.write_text(r'''param([string]$InputPath)
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$all=New-Object Collections.ArrayList
foreach($state in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 if($state.state -ne 'complete'){[void]$all.Add($null);continue}
 if($null -ne $state.brief){$text=[string]$state.brief}else{$text=$state.payload|ConvertTo-Json -Depth ([int]$state.json_depth)}
 [void]$all.Add(($text+[Environment]::NewLine))
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 4 -Compress))
''',encoding='utf-8-sig')
            formatted=subprocess.run(['powershell.exe','-NoProfile','-File',str(formatter),'-InputPath',str(rendered)],capture_output=True,timeout=90)
            self.assertEqual(formatted.returncode,0,formatted.stderr.decode(errors='replace'))
            console=json.loads(formatted.stdout.decode('utf-8-sig'))
            for fixture,old,text,new in zip(cases,captured,console,actual):
                if new.get('state')!='complete':continue
                with self.subTest(console_fixture=fixture):
                    clean=lambda v:re.sub(r'(elapsed_ms[=\"\s:]*)[0-9]+',lambda m:m.group(1)+'0',v)
                    self.assertEqual(clean(text),clean(old['console']))
            prefixes=[];traces=[]
            for old in captured:
                for index in range(len(old['request']['args']['captured_replies'])):
                    req=copy.deepcopy(old['request']);req['args']['captured_replies']=req['args']['captured_replies'][:index]
                    prefixes.append(req);traces.append(old['expected']['queries'][:index+1])
            for new,trace in zip(run_batch(command,prefixes),traces):self.assertEqual(new,dict(state='query',query=trace[-1],queries=trace))


if __name__ == '__main__':unittest.main()


@unittest.skipUnless(sys.platform=='win32' and os.environ.get('CUCP_PRECISION_TEST_HOST'),
                     'Requires integrated precision adapter and matching NativeHost')
class PrecisionAdapterWindowsTests(unittest.TestCase):
    maxDiff=None
    def test_actual_adapters_console_payload_errors_effects_and_exit(self):
        cases=fixtures()
        with tempfile.TemporaryDirectory(prefix='CUCP precision adapter ') as tmp:
            root=Path(tmp);source=root/'original.ps1';source.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            for case in cases:case['history_file']=str(root/'history.jsonl');case['cache_dir']=str(root/'cache')
            (root/'cache').mkdir()
            data=root/'fixtures.json';data.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            runner=root/'capture.ps1';runner.write_text(CAPTURE_RUNNER,encoding='utf-8-sig')
            cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),'-InputPath',str(data)]
            env={**os.environ,'CUCP_NATIVE_HOST':os.environ['CUCP_PRECISION_TEST_HOST']}
            before=subprocess.run([*cmd,'-Source',str(source)],capture_output=True,timeout=90,env=env)
            candidate=[*cmd,'-Source',str(ROOT/'scripts/cucp.ps1'),'-CurrentBridge']
            if os.environ.get('CUCP_PRECISION_ADAPTER_DRAFT'):candidate=[*cmd,'-Source',str(source),'-Adapter',os.environ['CUCP_PRECISION_ADAPTER_DRAFT']]
            after=subprocess.run(candidate,capture_output=True,timeout=900,env=env)
            self.assertEqual(before.returncode,0,before.stderr.decode(errors='replace'));self.assertEqual(after.returncode,0,after.stderr.decode(errors='replace'))
            old=json.loads(before.stdout.decode('utf-8-sig'));new=json.loads(after.stdout.decode('utf-8-sig'));self.assertEqual(len(old),len(new))
            for fixture,left,right in zip(cases,old,new):
                with self.subTest(fixture=fixture):
                    self.assertEqual(normalize(left['expected']),normalize(right['expected']))
                    clean=lambda v:re.sub(r'(elapsed_ms[=\"\s:]*)[0-9]+',lambda m:m.group(1)+'0',v)
                    self.assertEqual(clean(left['console']),clean(right['console']))
