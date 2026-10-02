"""Opt-in actual external adapter drafts: Windows PS5 -> fixed Python process.

These tests AST-load the real counted draft source, not a second imitation of its code.
Central PS sources stay unchanged until the draft and browser gates qualify.
"""
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

ROOT=Path(__file__).resolve().parents[2]
PYTHON=os.environ.get('CUCP_LEGACY_CDP_TEST_PYTHON')
BASELINE_TREE='bf895d3120dd5e145f360cb1c41e1d79a061d048'
sys.path.insert(0,str(ROOT/'pcucp-next/python'))
from test_legacy_cdp_wrapper_parity import RUNNER as WRAPPER_RUNNER,cases
from test_cdp import server
from test_legacy_cdp import capture,response_for,smart_value


def draft_blocks():
    path=ROOT/'tests/fixtures/legacy-cdp-adapter.ps1'
    if not path.is_file():path=ROOT/'scripts/cucp-legacy-cdp-adapter.ps1'
    text=path.read_text(encoding='utf-8-sig')
    blocks=dict(re.findall(r'^# region ([^\n]+)\n(.*?)^# endregion$',text,re.S|re.M))
    if set(blocks)!={'cdp-process-bridge','cdp-macro-delegate','cdp-native-intercept','cdp-native-delegate'}:
        raise AssertionError('Expected four exact adapter source regions')
    return blocks


def adapter_mode():
    explicit=os.environ.get('CUCP_LEGACY_CDP_ADAPTER_MODE')
    if explicit is not None:
        if explicit not in ('draft','production'):raise AssertionError('Invalid CDP adapter mode')
        return explicit
    enabled=json.loads((ROOT/'.github/migration-adapters.json').read_text())['test_adapters']
    return 'production' if 'cdp' in enabled else 'draft'


def adapter_blocks():
    blocks=draft_blocks()
    fixture=ROOT/'tests/fixtures/legacy-cdp-adapter.ps1'
    shared=ROOT/'scripts/cucp-legacy-cdp-adapter.ps1'
    production=adapter_mode()=='production'
    result={}
    groups={}
    for name,code in blocks.items():
        if production:
            source=shared if shared.is_file() else ROOT/('scripts/cucp-native-helper.ps1' if name=='cdp-native-delegate' else 'scripts/cucp.ps1')
        else:source=fixture if fixture.is_file() else shared
        names=re.findall(r'^function\s+(\S+)\s*\{',code,re.M)
        groups[name]=(source,names)
    if production:groups['cdp-production-route']=(ROOT/'scripts/cucp.ps1',['Invoke-NativeHelper'])
    for name,(source,names) in groups.items():
        literal="'"+str(source).replace("'","''")+"'"
        named=','.join("'"+item+"'" for item in names)
        result[name]=(f"$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile({literal},[ref]$t,[ref]$e)\n"
            f"foreach($name in @({named})){{\n"
            "$f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))\n"
            "if($f.Count -ne 1){throw \"Required CDP adapter function is absent: $name\"}\n"
            ". ([scriptblock]::Create($f[0].Extent.Text))\n}")
    return result


INVOKE_RUNNER=r'''
param([string]$Draft,[string]$RepositoryRoot,[string]$Python,[string]$InputPath,[switch]$LiveAuthority,[switch]$TypedHelper)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$Script:LegacyCdpSourceRoot=$RepositoryRoot;$env:CUCP_LEGACY_CDP_PYTHON=$Python;$env:CUCP_LEGACY_CDP_HOST=$null;$AllowLiveControl=[bool]$LiveAuthority
. ([scriptblock]::Create((Get-Content -LiteralPath $Draft -Raw -Encoding UTF8)))
$inputData=Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $TypedHelper){
 $result=_Invoke-LegacyCdpNativeArgv -ArgList @($inputData.argv) -LiveAuthority:$LiveAuthority
 [Console]::Out.WriteLine(($result|ConvertTo-Json -Depth 32 -Compress));exit 0
}
$Action=[string]$inputData.action;$CdpPort=[int]$inputData.port
$CdpPageMatch=[string]$inputData.args.page_match;$CdpSelector=[string]$inputData.args.selector
$CdpExpr=[string]$inputData.args.expression;$CdpExprB64=[string]$inputData.args.expression_b64
$CdpText=[string]$inputData.args.needle;$Text=[string]$inputData.args.text
$ClearFirst=[bool]$inputData.args.clear;$PressEnter=[bool]$inputData.args.enter
$CdpStartup=@{allow_live_control=[bool]$LiveAuthority}
if($Action -eq 'cdp-prosemirror-insert'){$CdpText=$Text}
function _Emit {param($Payload,[int]$ExitCode=0)
 [Console]::Out.WriteLine(($Payload|ConvertTo-Json -Depth 32 -Compress));exit $ExitCode
}
_Invoke-LegacyCdpNative $Action
'''


@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe') and PYTHON,
    'Enable CUCP_LEGACY_CDP_TEST_PYTHON on Windows for actual external adapter drafts')
class LegacyCdpActualDraftTests(unittest.TestCase):
    def run_script(self,text,data,*,blocks=None,root=ROOT,flags=(),timeout=240):
        with tempfile.TemporaryDirectory(prefix='cucp-cdp-actual-adapter-') as folder:
            d=Path(folder)
            (d/'runner.ps1').write_text(text,encoding='utf-8-sig')
            selected=blocks or adapter_blocks()
            (d/'draft.ps1').write_text('\n'.join(selected.values()),encoding='utf-8-sig')
            (d/'input.json').write_text(json.dumps(data,ensure_ascii=True),encoding='utf-8-sig')
            return subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(d/'runner.ps1'),
                '-Draft',str(d/'draft.ps1'),'-RepositoryRoot',str(root),'-Python',PYTHON,'-InputPath',str(d/'input.json'),*flags],
                capture_output=True,text=True,encoding='utf-8',timeout=timeout)

    def test_actual_macro_draft_exact_queries_effects_and_console(self):
        rows=cases()
        text=WRAPPER_RUNNER.replace('param([string]$Source,[string]$InputPath)',
            'param([string]$Draft,[string]$RepositoryRoot,[string]$Python,[string]$InputPath)')
        # Read original wrapper definitions from a pinned temporary source file.
        with tempfile.TemporaryDirectory(prefix='cucp-cdp-pinned-source-') as directory:
            source=Path(directory)/'source.ps1'
            source.write_bytes(subprocess.check_output(['git','show',BASELINE_TREE+':scripts/cucp.ps1'],cwd=ROOT))
            source_literal="'"+str(source).replace("'","''")+"'"
            text=text.replace("$ErrorActionPreference='Stop';",f"$Source={source_literal};$ErrorActionPreference='Stop';",1)
            marker="$Script:CucpV14Schema="
            pos=text.index(marker)
            text=text[:pos]+"$Script:LegacyCdpSourceRoot=$RepositoryRoot;$env:CUCP_LEGACY_CDP_PYTHON=$Python;$env:CUCP_LEGACY_CDP_HOST=$null;$AllowLiveControl=[bool]$LiveAuthority\n. ([scriptblock]::Create((Get-Content -LiteralPath $Draft -Raw -Encoding UTF8)))\n"+text[pos:]
            p=self.run_script(text,rows)
        self.assertEqual(p.returncode,0,p.stdout+'\n'+p.stderr)
        actual=json.loads(p.stdout)
        self.assertEqual(len(actual),len(rows))
        for row,want in zip(rows,actual):
            with self.subTest(action=row['action'],brief=row['brief'],opened=row['port_open'],status=row['reply']['payload']['status']):
                self.assertIsNone(want['error'])
                self.assertEqual(want['exit_code'],row['expected_exit'])
                self.assertEqual(want['queries'],row['expected_queries'])
                self.assertEqual(want['trajectory'],row['expected_trajectory'])
                self.assertEqual(want['stdout'],want['proposed_stdout'])

    def test_native_interceptor_control_looking_values_do_not_bind_authority(self):
        values=['-CdpAllowLiveControl','-CdpStartup','-AllowLiveControl','-Action','--allow-live-control',"x\"; Write-Output injected; #"]
        for live in (False,True):
            for value in values:
                with self.subTest(live=live,value=value),server() as (state,endpoint):
                    capture(state,[response_for('safe')])
                    argv=['-Action','cdp-eval','-CdpExpr',value,'-CdpPageMatch','Fixture','-CdpPort',str(state.port)]
                    p=self.run_script(INVOKE_RUNNER,dict(argv=argv),flags=['-LiveAuthority'] if live else [],timeout=30)
                    self.assertEqual(p.returncode,0,p.stderr)
                    result=json.loads(p.stdout)
                    self.assertEqual(result['ExitCode'],0 if live else 3)
                    self.assertEqual(len(state.requests),1 if live else 0)
                    if live:self.assertEqual(state.requests[0]['params']['expression'],value)
            # Text and page-match values are inert under the same closed parser.
            with server() as (state,endpoint):
                capture(state,[response_for(smart_value())])
                argv=['-Action','cdp-smart-type','-CdpText','-CdpStartup','-Text','-AllowLiveControl',
                      '-CdpPageMatch','-CdpAllowLiveControl','-CdpPort',str(state.port)]
                p=self.run_script(INVOKE_RUNNER,dict(argv=argv),flags=['-LiveAuthority'] if live else [],timeout=30)
                self.assertEqual(p.returncode,0,p.stderr)
                result=json.loads(p.stdout)
                self.assertEqual(result['ExitCode'],2 if live else 3)
                self.assertEqual(result['Json']['reason'],'no_matching_page' if live else 'live_control_required')
                self.assertEqual(state.requests,[])

    def test_actual_typed_native_helper_read_and_live_gate(self):
        for live in (False,True):
            with self.subTest(live=live),server() as (state,endpoint):
                capture(state,[response_for('safe')])
                p=self.run_script(INVOKE_RUNNER,dict(action='cdp-eval',port=state.port,args=dict(expression='-CdpStartup',page_match='Fixture')),
                    flags=['-TypedHelper']+(['-LiveAuthority'] if live else []),timeout=30)
                self.assertEqual(p.returncode,0 if live else 3,p.stderr)
                payload=json.loads(p.stdout)
                self.assertEqual(payload['status'],'ok' if live else 'blocked')
                self.assertEqual(len(state.requests),1 if live else 0)

    @unittest.skipUnless(adapter_mode()=='production','Central route gate activates only after production promotion')
    def test_promoted_invoke_native_helper_intercepts_before_missing_old_runtime(self):
        runner=INVOKE_RUNNER.replace('_Invoke-LegacyCdpNativeArgv -ArgList @($inputData.argv) -LiveAuthority:$LiveAuthority',
            'Invoke-NativeHelper -ArgList @($inputData.argv)')
        for live in (False,True):
            with self.subTest(live=live),server() as (state,endpoint):
                capture(state,[response_for('safe')])
                argv=['-Action','cdp-eval','-CdpExpr','-CdpStartup','-CdpPort',str(state.port)]
                p=self.run_script(runner,dict(argv=argv),flags=['-LiveAuthority'] if live else [],timeout=30)
                self.assertEqual(p.returncode,0,p.stderr)
                result=json.loads(p.stdout)
                self.assertEqual(result['ExitCode'],0 if live else 3)
                self.assertEqual(len(state.requests),1 if live else 0)

    def test_successful_live_dispatch_with_large_reply_or_log_failure_is_uncertain(self):
        runner=INVOKE_RUNNER[:INVOKE_RUNNER.index('$inputData=')]+r'''
$inputData=Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json
$script:calls=0;$script:logs=0;$AllowLiveControl=$true;$Brief=$false
function Test-CdpPortQuick {param([int]$Port,[int]$TimeoutMs) return $true}
function Invoke-NativeHelper {param([string[]]$ArgList)
 $script:calls++
 $raw=if($inputData.large_reply){'x'*1048576}else{'{"status":"ok"}'}
 return @{ExitCode=0;Json=@{status='ok';page_id='p';tag_name='BUTTON'};Raw=$raw}
}
function _Trajectory-Append {param([string]$Kind,$Payload)
 $script:logs++;if($inputData.fail_log){throw 'fixture_log_failed'}
}
$writer=New-Object IO.StringWriter;$original=[Console]::Out
try {[Console]::SetOut($writer);$code=_Invoke-LegacyCdpMacro -ActionName 'cdp-click' -Rest @('--selector','#save')}
finally {[Console]::SetOut($original)}
[Console]::Out.WriteLine((@{exit_code=$code;stdout=$writer.ToString();calls=$script:calls;logs=$script:logs}|ConvertTo-Json -Depth 8 -Compress))
'''
        for fixture in (dict(large_reply=True,fail_log=False),dict(large_reply=False,fail_log=True)):
            with self.subTest(fixture=fixture):
                p=self.run_script(runner,fixture,timeout=30)
                self.assertEqual(p.returncode,0,p.stderr)
                actual=json.loads(p.stdout);payload=json.loads(actual['stdout'])
                self.assertEqual(actual['calls'],1)
                self.assertEqual(actual['exit_code'],2)
                self.assertLess(len(actual['stdout']),512)
                self.assertEqual(payload,dict(status='partial',reason='cdp_post_dispatch_reporting_failed',action='cdp-click',
                    mutation_may_have_occurred=True,automatic_retry=False))

    def test_read_bridge_failure_in_live_process_does_not_claim_input(self):
        runner=INVOKE_RUNNER[:INVOKE_RUNNER.index('$inputData=')]+r'''
$inputData=Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json
function _Invoke-LegacyCdpBridge {
 param([string]$Operation,$Request,[switch]$LiveAuthority,[int]$Port)
 if($Operation -eq 'native-prepare'){return @{action=$inputData.action;args=@{};port=9222}}
 throw 'fixture_bridge_failure'
}
$result=_Invoke-LegacyCdpNativeArgv -ArgList @('-Action',$inputData.action) -LiveAuthority
[Console]::Out.WriteLine(($result|ConvertTo-Json -Depth 16 -Compress))
'''
        for action,uncertain in (('cdp-smart-find',False),('cdp-deep-find',False),('cdp-eval',True),('cdp-click',True)):
            with self.subTest(action=action):
                p=self.run_script(runner,dict(action=action),timeout=30)
                self.assertEqual(p.returncode,0,p.stderr)
                actual=json.loads(p.stdout)
                self.assertIs(actual['Json']['mutation_may_have_occurred'],uncertain)
                self.assertEqual(actual['Json']['reason'],'cdp_bridge_failed')

    def test_bounded_stdout_stderr_and_timeout_have_no_fallback(self):
        fixtures=[('stdout',"import sys\nsys.stdin.readline()\nsys.stdout.write('x'*5000000)\nsys.stdout.flush()\n"),
                  ('stderr',"import sys\nsys.stdin.readline()\nsys.stderr.write('x'*70000)\nsys.stderr.flush()\n"),
                  ('timeout',"import sys,time\nsys.stdin.readline()\ntime.sleep(30)\n")]
        # Invoke the common bridge directly; no real browser or helper is launched.
        runner=INVOKE_RUNNER[:INVOKE_RUNNER.index('$inputData=')]+r'''
try {_Invoke-LegacyCdpBridge -Operation 'macro-prepare' -Request @{action='cdp-detect';argv=@()};exit 9}
catch {[Console]::Out.WriteLine($_.Exception.Message);exit 0}
'''
        for kind,program in fixtures:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory(prefix='cucp-cdp-process-fixture-') as directory:
                root=Path(directory);package=root/'pcucp-next/python/pcucp_cli';package.mkdir(parents=True)
                (package/'__init__.py').write_text('',encoding='utf-8')
                (package/'legacy_cdp_bridge.py').write_text(program,encoding='utf-8')
                p=self.run_script(runner,{},root=root,timeout=23)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertIn('no retry was attempted',p.stdout)
                self.assertIn('timed out' if kind=='timeout' else kind,p.stdout)


if __name__=='__main__':unittest.main()
