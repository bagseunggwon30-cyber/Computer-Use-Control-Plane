"""Pinned app-profile qualification using captured replies; no live probes or writes."""
import copy
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = 'bf895d3120dd5e145f360cb1c41e1d79a061d048'
PROJECT = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyAppProfile.ContractTests'


def fixtures():
    window = dict(title='Fixture Editor', process='notepad', **{'class': 'MainWindow'}, hwnd=12345, pid=987,
                  visible=True, minimized=False, foreground=True, rect=dict(x=-20, y=10, width=640, height=480))
    affordance = dict(text='Save', role='Button', rect=dict(x=1, y=2, width=18, height=18),
                      small_icon=True, confidence=0.9, synonyms=['Save document', '저장'])
    base = dict(rest=[], brief=False, culture='en-US', history_file='Z:\\fixture-only\\app-strategy.jsonl',
                windows=[window], matched=[window], port=True,
                cdp=dict(ExitCode=0, Json=dict(status='ok', browser='Chrome/Fixture', protocol_version='1.3', page_count=2)),
                uia=[affordance], history=None, record=dict(ts='2000-01-01T00:00:00.0000000Z', success=True, strategy='uia_pattern'))
    cases = []

    def add(**overrides):
        f = copy.deepcopy(base)
        f.update(copy.deepcopy(overrides))
        cases.append(f)
        return f

    for process, flags in itertools.product(
            ('notepad', 'chrome', 'msedge', 'firefox', 'electron', 'cursor', 'code', 'windsurf', 'app', 'winword'),
            ([], ['--no-probe'], ['--probe'], ['--probe-uia'], ['--probe-cdp'], ['--include-affordances', '--record-strategy'])):
        f = add(rest=flags)
        f['windows'][0]['process'] = process
    for flags in (['--match', 'Fixture'], ['--window', 'Fixture'], ['--match', '', '--window', 'Fallback'],
                  ['--match', '--json-only'], ['--match', "O'Brien 한글😀\nTitle", '--include-affordances'],
                  ['--remember-strategy', '--probe'], ['--record-strategy', '--no-strategy-history', '--probe'],
                  ['--auto-probe', '--no-probe'], ['--probe', '--cdp-port', '9333'], ['--probe', '--cdp-port', '-1', '--port', '9444'],
                  ['--LABEL', 'Case', '--label', 'case', '--label', 'Case', '--click-label', 'Other', '--field', ' Name =value=rest'],
                  ['--label', '--label', 'skipped', '--label', '', '--field', '=empty', '--field', 'noequal', '--field', '  =value'],
                  ['--json-only'], ['--unknown', 'value'], ['--probe-uia-limit'], ['--match', None, '--window', ''],
                  ['--probe-uia', '--probe-uia-limit', '1', '--label', 'Save', '--label', '저장', '--label', 'Save document']):
        add(rest=flags)
    for windows, matched, flags in (([], [], []), ([], [], ['--record-strategy']),
                                   ([window], [], ['--match', 'Missing', '--remember-strategy']),
                                   ([window], [], ['--match', 'Missing', '--no-strategy-history']),
                                   ([], [window], ['--window', 'matched']),
                                   ([dict(window, visible=False)], [], [])):
        add(windows=windows, matched=matched, rest=flags)
    for field, values in (
            ('visible', (False, True, 0, 1, '', 'false', None, [], [False], [False, False])),
            ('foreground', (False, True, 0, 1, '', 'false', None, [], [False], [False, False])),
            ('minimized', (False, True, 0, 1, '', 'false', None, [], [False], [False, False])),
            ('title', ('', None, 0, 42, False, 'Untitled')), ('process', ('', None, 0, ' Chrome ', 'CHROME')),
            ('class', ('Chrome_WidgetWin_1', 'chrome_widgetwin_0', 'Main', None))):
        for value in values:
            f = add(); f['windows'][0][field] = value
    for count in (2, 3, 5, 10, 17, 33):
        tied = [dict(window, title=f'Tie {i}', process=f'process{i}', hwnd=i + 1) for i in range(count)]
        add(windows=tied)
        add(windows=list(reversed(tied)))
    for field, values in (('foreground', (False, True, False)), ('minimized', (True, True, False)), ('title', ('', 'Named', ''))):
        add(windows=[dict(window, hwnd=i + 1, **{field: value}) for i, value in enumerate(values)])
    add(windows=[dict(window, hwnd=i + 1, rect=dict(width=width, height=height)) for i, (width, height) in enumerate(((20, 10), (10, 100), (100, 100), (0, 999)))])
    for width in (None, '20', 0, -1, 1.5, 2.5, 2147483647, -2147483648, 2147483648, 'bad', '', ' '):
        f = add(); f['windows'][0]['rect']['width'] = width
    for hwnd in (None, '12345', -1, 'bad', 9223372036854775807, '9223372036854775807', '9223372036854775808'):
        f = add(rest=['--probe-uia']); f['windows'][0]['hwnd'] = hwnd
    for option, value in itertools.product(('--cdp-port', '--port', '--probe-uia-limit'),
                                         ('', ' ', 'bad', '1.5', '2.5', '-1', '0', '2147483647', '2147483648', '-2147483649', '0xFFFFFFFF', '0x100000000', '1e40', 'NaN', 'Infinity', '1,234')):
        add(rest=['--probe', option, value])
    for port in (False, True, None, '', 'false', 0, 1, [], [False], [False, False]):
        add(rest=['--probe'], port=port)
    for json_value in (None, {}, dict(status='partial'), dict(status='partial', reason='blocked'),
                       dict(status='ok', page_count='bad'), dict(status='OK', page_count=1.5),
                       dict(status='ok', page_count=2147483648), dict(status='ok', browser=['a', 'b'], protocol_version=0)):
        add(rest=['--probe'], cdp=dict(ExitCode=124, Json=json_value))
    for items in ([], [{}], [dict(affordance, small_icon=False)], [dict(affordance, small_icon='false')],
                  [dict(affordance, text='', synonyms=['Save'])], [dict(affordance, text='a', synonyms=None)],
                  [dict(affordance, text=False, synonyms=['', None, 'Save'])],
                  [dict(affordance, role='button'), dict(affordance, role='Button')],
                  [dict(affordance, role=f'Role{i}') for i in range(12)],
                  [dict(affordance, role=role) for role in ('é', 'e\u0301', 'É', 'a', 'I', 'İ', 'ı', 'i')]):
        add(rest=['--probe-uia', '--label', 'Save', '--label', 'a', '--label', 'SAVE', '--label', 'missing'], uia=items)
    for history in (None, {}, dict(strategy='uia_pattern'), dict(strategy='uia_coord+fallback', source='fixture'),
                    dict(strategy='cdp_click'), dict(strategy=0), dict(strategy=False), dict(strategy=''),
                    dict(strategy='uİa_pattern'), dict(strategy='uıa_pattern'), dict(strategy='vİsİon_precİse'),
                    dict(strategy='é'), dict(strategy='e\u0301'), [], ['single'], ['first', 'second']):
        add(history=history, rest=['--remember-strategy'])
    for record in (None, {}, dict(error='write failed'), dict(error=''), dict(error=False), dict(error='false'),
                   dict(success=False), False, 'recorded', [], ['recorded']):
        add(rest=['--record-strategy', '--probe'], record=record)
    for stage in ('windows', 'matched', 'port', 'cdp', 'uia', 'history', 'record'):
        add(rest=['--match', 'Fixture', '--auto-probe', '--record-strategy'], throw_stage=stage)
    for culture, process, strategy in itertools.product(('en-US', 'ko-KR', 'tr-TR', ''),
                                                       ('app', 'firefox', 'fİrefox', 'notepad'),
                                                       ('uİa_pattern', 'uıa_pattern', 'vİsİon_precİse')):
        f = add(culture=culture, rest=['--probe-uia', '--label', 'é', '--label', 'e\u0301', '--label', '가', '--label', '가', '--label', 'I', '--label', 'i'], history=dict(strategy=strategy))
        f['windows'][0]['process'] = process
    for case in copy.deepcopy(cases[:12] + cases[76:82]):
        case['brief'] = True
        cases.append(case)
    add(rest=['--json-only'], brief=True)
    return cases


CAPTURE_RUNNER = r'''
param([string]$Source,[string]$InputPath,[string]$CandidatePath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Pinned source did not parse'}
$names=@('_Read-OptValue','_Read-AllOptValues','_Read-Switch','_TaskPlan-QuoteToken','_TaskPlan-StepString',
         '_AppStrategy-NormalizeRoute','_AppStrategy-Key','_AppProfile-StrategyScore','Invoke-MacroAppProfile')
foreach($name in $names){
 $fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($fn.Count -ne 1){throw "Expected exact source function $name"}
 $body=$fn[0].Extent.Text
 if($name -eq 'Invoke-MacroAppProfile'){
   # Only measured elapsed values are normalized; payload/format/error code is unchanged.
   $pattern='\[int\]\$(?:pSw|sw)\.Elapsed\.TotalMilliseconds'
   if([regex]::Matches($body,$pattern).Count -ne 4){throw 'Expected four app-profile elapsed seams'}
   $body=[regex]::Replace($body,$pattern,'0')
 }
 . ([scriptblock]::Create($body))
}
function Capture-Reply($kind,$argv,$stage,$result,[switch]$Enumerate){
 [void]$script:queries.Add([ordered]@{kind=$kind;argv=@($argv)})
 if($script:fixture.throw_stage -eq $stage){[void]$script:replies.Add(@{kind=$kind;argv=@($argv);error="fixture_$stage"});throw "fixture_$stage"}
 [void]$script:replies.Add(@{kind=$kind;argv=@($argv);result=$result})
 if($Enumerate){foreach($item in @($result)){Write-Output -NoEnumerate $item}}
 else{Write-Output -NoEnumerate $result}
}
function _Enumerate-Win32Windows {param([string]$Match)
 if($PSBoundParameters.ContainsKey('Match')){Capture-Reply 'windows' @('-Match',"$Match") 'matched' $script:fixture.matched -Enumerate}
 else{Capture-Reply 'windows' @() 'windows' $script:fixture.windows -Enumerate}
}
function Test-CdpPortQuick {param([int]$Port,[int]$TimeoutMs) Capture-Reply 'cdp_port' @("$Port","$TimeoutMs") 'port' $script:fixture.port}
function Invoke-NativeHelper {param([string[]]$ArgList) Capture-Reply 'native' $ArgList 'cdp' $script:fixture.cdp}
function _Get-UIAffordances {param([string]$FocusedWindow,[int]$MaxElements,[int]$MinSize,[int64]$Hwnd)
 Capture-Reply 'uia' @('-FocusedWindow',"$FocusedWindow",'-MaxElements',"$MaxElements",'-MinSize',"$MinSize",'-Hwnd',"$Hwnd") 'uia' $script:fixture.uia -Enumerate
}
function _AppStrategy-LastGood {param([string]$AppKey) Capture-Reply 'history' @("$AppKey") 'history' $script:fixture.history}
function _AppStrategy-Append {param([string]$AppKey,[string]$AppType,[string]$Strategy,[string]$Confidence,[int]$Score,[string]$Process,[string]$Class,[string]$Title)
 Capture-Reply 'record' @("$AppKey","$AppType","$Strategy","$Confidence","$Score","$Process","$Class","$Title") 'record' $script:fixture.record
}
$candidateResults=if($CandidatePath){@(Get-Content -LiteralPath $CandidatePath -Raw -Encoding UTF8|ConvertFrom-Json)}else{@()}
$all=New-Object Collections.ArrayList;$caseIndex=0
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$fixture;$script:queries=New-Object Collections.ArrayList;$script:replies=New-Object Collections.ArrayList
 [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$fixture.culture)
 $Brief=[bool]$fixture.brief;$Script:AppStrategyFile=$fixture.history_file
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
 try{
  $exitCode=Invoke-MacroAppProfile -Rest $fixture.rest
  $console=$writer.ToString();$raw=$console.TrimEnd([char[]]"`r`n")
  if($Brief -and -not ($fixture.rest -contains '--json-only')){$payload=$null;$brief=$raw;$depth=if($exitCode -eq 2){12}else{14}}
  else{$payload=$raw|ConvertFrom-Json;$brief=$null;$depth=if($payload.status -eq 'partial'){12}else{14}}
  $expected=@{state='complete';payload=$payload;exit=[int]$exitCode;brief=$brief;json_depth=$depth;queries=@($script:queries)}
 }catch{$expected=@{state='error';error=$_.Exception.Message;queries=@($script:queries)}}
 finally{[Console]::SetOut($previous);$expected['console']=$writer.ToString();$writer.Dispose()}
 $entry=@{expected=$expected;args=@{rest=@($fixture.rest);brief=$Brief;culture=[string]$fixture.culture;history_file=$fixture.history_file;elapsed_ms=0;cdp_elapsed_ms=0;uia_elapsed_ms=0;captured_replies=@($script:replies)}}
 if($CandidatePath){
  $state=$candidateResults[$caseIndex];$writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
  try{
   if($state.state -eq 'complete'){
    if($null -ne $state.brief){[Console]::Out.WriteLine([string]$state.brief)}
    else{[Console]::Out.WriteLine(($state.payload|ConvertTo-Json -Depth ([int]$state.json_depth)))}
   }
  }finally{[Console]::SetOut($previous);$entry['candidate_console']=$writer.ToString();$writer.Dispose()}
 }
 [void]$all.Add($entry);$caseIndex++
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 64 -Compress))
'''


class AppProfileSourceTests(unittest.TestCase):
    def test_candidate_is_isolated_and_oracle_is_pinned(self):
        source = (ROOT / 'pcucp-next/dotnet/PcuCp.LegacyAppProfile/LegacyAppProfileKernel.cs').read_text()
        for forbidden in ('Process.Start', 'System.Management.Automation', 'HttpClient', 'File.Read', 'File.Write', 'SendInput'):
            self.assertNotIn(forbidden, source)
        self.assertGreaterEqual(len(fixtures()), 300)
        self.assertNotIn('LegacyAppProfile', (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/PcuCp.NativeHost.csproj').read_text())
        self.assertNotIn('app-profile-advance', (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/LegacyCompatibilityDispatcher.cs').read_text())
        self.assertIn("if([regex]::Matches($body,$pattern).Count -ne 4)", CAPTURE_RUNNER)
        self.assertIn("'_AppProfile-StrategyScore'", CAPTURE_RUNNER)


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell 5.1 app-profile oracle')
class AppProfileWindowsTests(unittest.TestCase):
    maxDiff = None

    def test_complete_payload_errors_order_argv_exit_and_console(self):
        cases = fixtures()
        with tempfile.TemporaryDirectory(prefix='CUCP app-profile 한글 ') as temp:
            root = Path(temp)
            source = root / 'original.ps1'
            source.write_bytes(subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT))
            inputs = root / 'fixtures.json'; inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            runner = root / 'capture.ps1'; runner.write_text(CAPTURE_RUNNER, encoding='utf-8-sig')
            capture = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner), '-Source', str(source), '-InputPath', str(inputs)]
            original = subprocess.run(capture, capture_output=True, timeout=180)
            self.assertEqual(original.returncode, 0, original.stderr.decode('utf-8', errors='replace'))
            captured = json.loads(original.stdout.decode('utf-8-sig'))
            self.assertEqual(len(captured), len(cases))
            build = subprocess.run([shutil.which('dotnet'), 'build', str(PROJECT), '-c', 'Release', '--output', str(root / 'build')], capture_output=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout.decode('utf-8', errors='replace') + build.stderr.decode('utf-8', errors='replace'))
            command = [shutil.which('dotnet'), str(root / 'build/PcuCp.LegacyAppProfile.ContractTests.dll')]
            after = subprocess.run(command, input=json.dumps([c['args'] for c in captured], ensure_ascii=True).encode(), capture_output=True, timeout=60)
            self.assertEqual(after.returncode, 0, after.stderr.decode('utf-8', errors='replace'))
            results = json.loads(after.stdout)
            self.assertEqual(len(results), len(cases))
            candidates = root / 'candidate.json'; candidates.write_text(json.dumps(results, ensure_ascii=True), encoding='utf-8-sig')
            rendered = subprocess.run([*capture, '-CandidatePath', str(candidates)], capture_output=True, timeout=180)
            self.assertEqual(rendered.returncode, 0, rendered.stderr.decode('utf-8', errors='replace'))
            formatted = json.loads(rendered.stdout.decode('utf-8-sig'))
            self.assertEqual(len(formatted), len(cases))
            for fixture, old, new, console in zip(cases, captured, results, formatted):
                with self.subTest(fixture=fixture):
                    expected = {k: v for k, v in old['expected'].items() if k != 'console'}
                    if expected.get('brief') is not None:
                        new = {**new, 'payload': None}
                    self.assertEqual(new, expected)
                    self.assertEqual(console['candidate_console'], old['expected']['console'])
                    self.assertEqual(console['expected'], old['expected'])
            prefixes, traces = [], []
            for old in captured:
                for index in range(len(old['args']['captured_replies'])):
                    prefixes.append({**old['args'], 'captured_replies': old['args']['captured_replies'][:index]})
                    traces.append(old['expected']['queries'][:index + 1])
            process = subprocess.run(command, input=json.dumps(prefixes, ensure_ascii=True).encode(), capture_output=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            prefix_results = json.loads(process.stdout)
            self.assertEqual(len(prefix_results), len(traces))
            for state, trace in zip(prefix_results, traces):
                self.assertEqual(state, dict(state='query', query=trace[-1], queries=trace))
