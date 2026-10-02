"""Windows PS5 pinned-tree differential. The old sources remain retirement oracles.

PowerShell is used only to run the historical oracle in this test, never by the
replacement implementation. Browser/socket dependencies are captured fixtures.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'pcucp-next/python'))
from pcucp_cli.legacy_cdp import LegacyCdpAdapter
from pcucp_cli.legacy_cdp_contract import score_pages, find_page, dom_bridge_plan
from test_legacy_cdp import smart_value, response_for

BASELINE_TREE='bf895d3120dd5e145f360cb1c41e1d79a061d048'
RUNNER=r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$names=@('_Cdp-ScorePages','_Cdp-FindPage','_Cdp-NewDomBridgePlan','_Js-StringLiteral','_Cdp-RunSmartDomAction',
 '_Action-CdpDetect','_Action-CdpEval','_Action-CdpType','_Action-CdpClick','_Action-CdpSmartFind',
 '_Action-CdpSmartTypeFind','_Action-CdpSmartClick','_Action-CdpSmartType','_Action-CdpDeepFind','_Action-CdpProseMirrorInsert')
foreach($name in $names){
 $f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($f.Count -ne 1){throw "Expected exact oracle function $name"};. ([scriptblock]::Create($f[0].Extent.Text))
}
function _Cdp-Detect {param([int]$Port) return $script:fixture.detect}
function _Cdp-WsCall {param([string]$WsUrl,[string]$Method,[hashtable]$Params=@{},[int]$TimeoutMs=5000,[int]$MessageId=1)
 [void]$script:calls.Add([ordered]@{ws_url=$WsUrl;method=$Method;params=$Params;timeout_ms=$TimeoutMs;message_id=$MessageId})
 $reply=$script:fixture.responses[$script:responseIndex];$script:responseIndex++;return $reply
}
function _Emit {param($Payload,[int]$ExitCode=0)
 $Payload['action']=$Action;$Payload['elapsed_ms']=0
 $script:emitted=[ordered]@{payload=$Payload;exit_code=$ExitCode};throw '__CDP_EMITTED__'
}
$all=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$case;$script:calls=New-Object Collections.ArrayList;$script:responseIndex=0;$script:emitted=$null
 $Action=$case.action;$CdpPort=9222;$CdpPageMatch=[string]$case.args.page_match
 $CdpExpr=[string]$case.args.expression;$CdpExprB64=[string]$case.args.expression_b64
 $CdpSelector=[string]$case.args.selector;$CdpText=[string]$case.args.needle;$Text=[string]$case.args.text
 $ClearFirst=[bool]$case.args.clear;$PressEnter=[bool]$case.args.enter
 if($Action -eq 'cdp-prosemirror-insert'){$CdpText=$Text}
 if($case.kind -eq 'score'){
   $s=@(_Cdp-ScorePages -Detect $case.detect -PageMatch $CdpPageMatch)
   $p=_Cdp-FindPage -Detect $case.detect -PageMatch $CdpPageMatch
   [void]$all.Add(@{scores=$s;page=$p;selection=$Script:_LastCdpPageSelection});continue
 }
 if($case.kind -eq 'plan'){
   [void]$all.Add((_Cdp-NewDomBridgePlan -DomAction $case.dom_action -Query $CdpText -Port $CdpPort -PageMatch $CdpPageMatch -TextToType $Text -Clear $ClearFirst -Enter $PressEnter));continue
 }
 $fn=switch($Action){
 'cdp-detect'{'_Action-CdpDetect'};'cdp-eval'{'_Action-CdpEval'};'cdp-type'{'_Action-CdpType'};'cdp-click'{'_Action-CdpClick'}
 'cdp-smart-find'{'_Action-CdpSmartFind'};'cdp-smart-type-find'{'_Action-CdpSmartTypeFind'};'cdp-smart-click'{'_Action-CdpSmartClick'}
 'cdp-smart-type'{'_Action-CdpSmartType'};'cdp-deep-find'{'_Action-CdpDeepFind'};'cdp-prosemirror-insert'{'_Action-CdpProseMirrorInsert'}
 }
 try {& $fn} catch {if($_.Exception.Message -ne '__CDP_EMITTED__'){throw}}
 [void]$all.Add(@{result=$script:emitted;calls=@($script:calls)})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 64 -Compress))
'''


def page():
    return dict(id='p',title='Fixture',url='http://fixture.test',type='page',ws_url='ws://127.0.0.1:9222/devtools/page/p')


def fixture(action,args=None,value=None):
    return dict(kind='action',action=action,args=args or {},detect=dict(available=True,port=9222,
        version={'Browser':'Mock','Protocol-Version':'1.3','User-Agent':'Fixture'},pages=[page()]),
        responses=[dict(ok=True,response={'id':1,**response_for(value)},error=None)])


def compatible_cases():
    cases=[fixture('cdp-detect'),fixture('cdp-eval',{'expression':'document.title'},'Fixture'),
        fixture('cdp-type',{'selector':'#field','text':'한글😀','clear':True,'enter':True},dict(ok=True,sent_enter=True,tag_name='INPUT',is_content_editable=False,is_input=True,current_value_length=4)),
        fixture('cdp-click',{'selector':'#save'},dict(ok=True,tag_name='BUTTON'))]
    for action in ('cdp-smart-find','cdp-smart-type-find','cdp-smart-click','cdp-smart-type'):
        value=smart_value();value.update(plan_only=action.endswith('find'))
        args=dict(needle='Save')
        if action=='cdp-smart-type':args.update(text='한글',clear=True,enter=True);value.update(text_length=2,sent_enter=True)
        cases.append(fixture(action,args,value))
    for action in ('cdp-eval','cdp-type','cdp-click','cdp-smart-find','cdp-smart-type-find','cdp-smart-click','cdp-smart-type'):
        args=dict(expression='1') if action=='cdp-eval' else dict(selector='#x') if action in ('cdp-type','cdp-click') else dict(needle='Save')
        if action in ('cdp-type','cdp-smart-type'):args['text']='a'
        c=fixture(action,args);c['detect'].update(available=False,error='tcp_port_closed_or_timeout',pages=[]);cases.append(c)
        c=fixture(action,{**args,'page_match':'missing'});cases.append(c)
    for action in ('cdp-type','cdp-click','cdp-smart-find','cdp-smart-type-find'):
        args=dict(selector='#x',text='a') if action=='cdp-type' else dict(selector='#x') if action=='cdp-click' else dict(needle='Save')
        cases.append(fixture(action,args,dict(ok=False,reason='no_text_match',candidate_count=2,top_score=45,candidate_summaries=[{'score':45}])))
    # Null, empty, single, multi, nested and value/Count-shaped objects retain their real runtime type.
    for value in (None,[],[{'score':1}],[{'score':1},{'score':2}],[[{'score':1}]],{'value':[{'score':1}],'Count':1}):
        s=smart_value();s['candidate_summaries']=value;cases.append(fixture('cdp-smart-find',{'needle':'Save'},s))
    return cases


@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Windows PowerShell 5 pinned-tree oracle')
class LegacyCdpPinnedParityTests(unittest.TestCase):
    def oracle(self,cases):
        with tempfile.TemporaryDirectory(prefix='cucp-legacy-cdp-oracle-') as directory:
            root=Path(directory)
            source=subprocess.check_output(['git','show',BASELINE_TREE+':scripts/cucp-native-helper.ps1'],cwd=ROOT)
            (root/'source.ps1').write_bytes(source)
            (root/'runner.ps1').write_text(RUNNER,encoding='utf-8-sig')
            (root/'cases.json').write_text(json.dumps(cases,ensure_ascii=False),encoding='utf-8-sig')
            p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(root/'runner.ps1'),'-Source',str(root/'source.ps1'),'-InputPath',str(root/'cases.json')],capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(p.returncode,0,p.stdout+'\n'+p.stderr)
            return json.loads(p.stdout)

    def test_exact_pure_scores_selection_and_bridge(self):
        cases=[]
        for match in ('','same','missing','FILE:x'):
            pages=[dict(id=str(i),title=title,url=url,type=kind,ws_url='') for i,(title,url,kind) in enumerate([
                ('same','https://x','page'),('Same','app:y','page'),('İ','file:x','webview'),('가','devtools://x','page'),
                ('ß','https://w','worker'),('','about:blank','iframe'),('A','httpfake','service_worker')])]
            cases.append(dict(kind='score',args=dict(page_match=match),detect=dict(available=True,pages=pages)))
        for action in ('click','type','find'):
            cases.append(dict(kind='plan',dom_action=action,args=dict(needle="이름 O'Brien",text='한글😀',clear=True,enter=True,page_match='App')))
        expected=self.oracle(cases)
        for case,want in zip(cases,expected):
            if case['kind']=='score':
                p,s=find_page(case['detect'],case['args']['page_match'])
                got=dict(scores=score_pages(case['detect'],case['args']['page_match']),page=p,selection=s)
            else:
                a=case['args'];got=dom_bridge_plan(case['dom_action'],a['needle'],9222,a['page_match'],a['text'],a['clear'],a['enter'])
            self.assertEqual(got,want,case)

    def test_exact_helper_outputs_except_explicit_safety_evidence(self):
        cases=compatible_cases();expected=self.oracle(cases)
        for case,want in zip(cases,expected):
            with self.subTest(action=case['action'],args=case['args']):
                adapter=LegacyCdpAdapter('http://127.0.0.1:9222',allow_live_control=True)
                replies=iter(case['responses'])
                with patch.object(adapter,'_discover',return_value=case['detect']),patch.object(adapter._transport,'call',side_effect=lambda *a,**kw:next(replies)['response']):
                    got=adapter.execute(case['action'],case['args'])
                payload=dict(got.payload);payload['elapsed_ms']=0
                self.assertEqual(payload,want['result']['payload'])
                self.assertEqual(got.exit_code,want['result']['exit_code'])

    def test_original_deep_and_prosemirror_broken_envelopes_are_characterized(self):
        deep=fixture('cdp-deep-find',{'needle':'Save'},dict(traversal={},found_count=1,top_matches=[]))
        pm=fixture('cdp-prosemirror-insert',{'selector':'.ProseMirror','text':'x'},'seed')
        pm['responses']=[dict(ok=True,response=dict(id=1,result={}),error=None)]*3+pm['responses']
        expected=self.oracle([deep,pm])
        self.assertEqual(expected[0]['result']['payload']['reason'],'no_result')
        self.assertEqual(expected[0]['result']['exit_code'],2)
        self.assertEqual(expected[1]['result']['payload']['reason'],'selector_not_found')
        self.assertEqual(expected[1]['result']['exit_code'],2)
        self.assertNotIn('Input.insertText',[c['method'] for c in expected[1]['calls']])


if __name__=='__main__':unittest.main()
