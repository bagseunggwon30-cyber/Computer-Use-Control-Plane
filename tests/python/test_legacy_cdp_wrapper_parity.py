"""Pinned wrapper query, effect, exit and Console differential on Windows PS5.

The retained shared host serializer serializes the Python-produced payload; both
payloads and exact Console bytes are compared. JSON serialization is explicitly
an injected host dependency, not an unproven Python imitation of PS5 formatting.
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

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'pcucp-next/python'))
from pcucp_cli.legacy_cdp_contract import prepare_macro,native_arguments,LegacyCdpResult
from pcucp_cli.legacy_cdp_macro import macro_output,port_closed_output
BASELINE_TREE='bf895d3120dd5e145f360cb1c41e1d79a061d048'
RUNNER=r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$names=@('_Read-OptValue','_Read-Switch','New-CdpDomBridgePlan','Emit-CdpPortClosed',
'Invoke-MacroCdpDetect','Invoke-MacroCdpEval','Invoke-MacroCdpType','Invoke-MacroCdpClick',
'Invoke-MacroCdpSmartFind','Invoke-MacroCdpSmartTypeFind','Invoke-MacroCdpSmartClick','Invoke-MacroCdpSmartType',
'Invoke-MacroCdpDeepFind','Invoke-MacroCdpProseMirrorInsert')
foreach($name in $names){$fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true));if($fn.Count -ne 1){throw $name};. ([scriptblock]::Create($fn[0].Extent.Text))}
$Script:CucpV14Schema=@{CdpDeepFind='cucp.cdp-deep-find/v1'}
function Test-CdpPortQuick {param([int]$Port,[int]$TimeoutMs)
 [void]$script:queries.Add(@{kind='port';port=$Port;timeout_ms=$TimeoutMs});return $script:fixture.port_open
}
function Invoke-NativeHelper {param([string[]]$ArgList)
 [void]$script:queries.Add(@{kind='native';argv=@($ArgList)})
 return @{Json=$script:fixture.reply.payload;ExitCode=$script:fixture.reply.exit_code;Raw=($script:fixture.reply.payload|ConvertTo-Json -Depth 8)+[Environment]::NewLine}
}
function _Trajectory-Append {param([string]$Kind,$Payload)
 [void]$script:trajectory.Add(@{kind=$Kind;payload=$Payload})
}
$all=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$case;$script:queries=New-Object Collections.ArrayList;$script:trajectory=New-Object Collections.ArrayList
 $Brief=[bool]$case.brief;$AllowLiveControl=[bool]$case.live
 $fn=switch($case.action){
 'cdp-detect'{'Invoke-MacroCdpDetect'};'cdp-eval'{'Invoke-MacroCdpEval'};'cdp-type'{'Invoke-MacroCdpType'};'cdp-click'{'Invoke-MacroCdpClick'}
 'cdp-smart-find'{'Invoke-MacroCdpSmartFind'};'cdp-smart-type-find'{'Invoke-MacroCdpSmartTypeFind'};'cdp-smart-click'{'Invoke-MacroCdpSmartClick'}
 'cdp-smart-type'{'Invoke-MacroCdpSmartType'};'cdp-deep-find'{'Invoke-MacroCdpDeepFind'};'cdp-prosemirror-insert'{'Invoke-MacroCdpProseMirrorInsert'}
 }
 $writer=New-Object IO.StringWriter;$original=[Console]::Out;$errorText=$null;$code=$null
 try{[Console]::SetOut($writer);$code=& $fn -Rest @($case.argv)}catch{$errorText=$_.Exception.Message}finally{[Console]::SetOut($original)}
 $actualConsole=$writer.ToString()
 # Use the same retained shared formatter on the independently computed Python payload.
 $expectedConsole=if($case.brief){[string]$case.proposed.brief_line+[Environment]::NewLine}else{($case.proposed.payload|ConvertTo-Json -Depth ([int]$case.proposed.json_depth))+[Environment]::NewLine}
 [void]$all.Add(@{exit_code=$code;error=$errorText;stdout=$actualConsole;proposed_stdout=$expectedConsole;queries=@($script:queries);trajectory=@($script:trajectory)})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 64 -Compress))
'''


def cases():
    rows=[]
    replies=dict(status='ok',port=9222,page_count=2,browser='Mock',protocol_version='1.3',result_type='object',
        result_value={'Count':2,'value':['한글','😀']},tag_name='INPUT',is_content_editable=False,is_input=True,
        current_value_length=4,sent_enter=False,page_id='p',page_title="한글 O'Brien",matched_text='Save',score=147,
        text_length=4,changed=True,before_length=2,after_length=6,found_count=2,
        traversal={'shadow_roots_seen':1,'iframes_seen':2})
    options={
        'cdp-detect':[], 'cdp-eval':['--expr','1'], 'cdp-click':['--selector','#x'],
        'cdp-type':['--selector','#x','--text','한글😀','--clear-first','--press-enter'],
        'cdp-smart-find':['--text','Save'],'cdp-smart-type-find':['--label','Name'],
        'cdp-smart-click':['--text','Save'],'cdp-smart-type':['--label','Name','--text','a','--clear-first','--press-enter'],
        'cdp-deep-find':['--text','Save'],'cdp-prosemirror-insert':['--selector','.ProseMirror','--text','x']}
    for action,argv in options.items():
        for opened,brief,status in ((False,False,'ok'),(False,True,'ok'),(True,False,'ok'),(True,True,'ok'),(True,False,'error'),(True,True,'partial'),(True,True,'blocked')):
            row=dict(action=action,argv=argv+['--page-match','Fixture','--port','9222'],live=True,port_open=opened,brief=brief,
                reply=dict(payload={**replies,'status':status,'reason':'fixture_error' if status!='ok' else ''},exit_code=0 if status=='ok' else 3 if status=='blocked' else 2))
            macro=prepare_macro(action,row['argv'],allow_live_control=True)
            out=macro_output(macro,LegacyCdpResult(**row['reply'])) if opened else port_closed_output(macro)
            row['proposed']=dict(payload=out.payload,brief_line=out.brief_line,json_depth=out.json_depth)
            row['expected_exit']=out.exit_code
            row['expected_queries']=[dict(kind='port',port=9222,timeout_ms=120)]+([dict(kind='native',argv=native_arguments(macro))] if opened else [])
            row['expected_trajectory']=[] if out.trajectory is None else [out.trajectory]
            rows.append(row)
    # UTF16 truncation, scalars, arrays and arbitrary value/Count objects are distinct.
    for value in ('a'*81,'😀'*41,True,3,None,['a','b'],{'value':['x'],'Count':1}):
        row=copy.deepcopy(next(r for r in rows if r['action']=='cdp-eval' and r['brief'] and r['port_open'] and r['reply']['payload']['status']=='ok'))
        row['reply']['payload']['result_value']=value
        macro=prepare_macro(row['action'],row['argv'],allow_live_control=True)
        out=macro_output(macro,LegacyCdpResult(**row['reply']))
        row['proposed']=dict(payload=out.payload,brief_line=out.brief_line,json_depth=out.json_depth)
        rows.append(row)
    return rows


@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Windows PowerShell 5 wrapper Console oracle')
class LegacyCdpWrapperParityTests(unittest.TestCase):
    def test_exact_wrapper_queries_effects_exit_and_console(self):
        rows=cases()
        with tempfile.TemporaryDirectory(prefix='cucp-legacy-cdp-wrapper-') as directory:
            d=Path(directory)
            (d/'source.ps1').write_bytes(subprocess.check_output(['git','show',BASELINE_TREE+':scripts/cucp.ps1'],cwd=ROOT))
            (d/'runner.ps1').write_text(RUNNER,encoding='utf-8-sig')
            (d/'cases.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8-sig')
            p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(d/'runner.ps1'),'-Source',str(d/'source.ps1'),'-InputPath',str(d/'cases.json')],capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(p.returncode,0,p.stdout+'\n'+p.stderr)
            expected=json.loads(p.stdout)
        for row,want in zip(rows,expected):
            with self.subTest(action=row['action'],brief=row['brief'],opened=row['port_open'],status=row['reply']['payload']['status']):
                self.assertIsNone(want['error'])
                self.assertEqual(want['exit_code'],row['expected_exit'])
                self.assertEqual(want['queries'],row['expected_queries'])
                self.assertEqual(want['trajectory'],row['expected_trajectory'])
                self.assertEqual(want['stdout'],want['proposed_stdout'])


if __name__=='__main__':unittest.main()
