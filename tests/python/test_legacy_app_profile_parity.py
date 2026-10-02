"""Pinned app-profile qualification using captured replies; no live probes or writes."""
import copy
import itertools
import json
import os
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
    # -replace uses case-insensitive regex even after invariant lowercasing.
    # Preserve the exact original key and classification, including characters
    # whose regex folding differs from NLS equality or ordinary ASCII matching.
    for culture, field, value in itertools.product(('en-US', 'ko-KR', 'tr-TR', ''),
                                                   ('process', 'class', 'title'),
                                                   ('appİ', 'appı', 'appſ', 'İıſK', 'i\u0307', 'é e\u0301',
                                                    'fİrefox', 'fırefox', 'wİndſurf', 'wİnword', 'wınword',
                                                    'Chrome_WidgetWİn_1', 'Chrome_WidgetWın_1')):
        f = add(culture=culture, rest=['--no-probe'])
        # Neutralize the base notepad identity so title/class fixtures actually
        # determine browser/document classification rather than being masked.
        f['windows'][0].update(title='Fixture', process='fixture', **{'class': 'Fixture'})
        f['windows'][0][field] = value
    for case in copy.deepcopy(cases[:12] + cases[76:82]):
        case['brief'] = True
        cases.append(case)
    add(rest=['--json-only'], brief=True)
    return cases


def record_boundary_fixtures():
    """Additional write-boundary cases; every original 496 fixture is retained."""
    base = fixtures()[0]
    base.update(rest=['--match', 'Fixture', '--probe', '--label', 'Save', '--record-strategy'],
                history={'strategy': 'cdp_dom'}, boundary_case='seven_queries_high_confidence')
    for windows in (base['windows'], base['matched']):
        windows[0]['process'] = 'chrome'
    cases = [copy.deepcopy(base)]
    for record in (None, {}, {'error': 'write failed'}, {'error': ''}, {'error': False},
                   {'error': 'false'}, {'success': False}, False, 'recorded', [], ['recorded']):
        case = copy.deepcopy(base)
        case.update(record=record, boundary_case='record_result_shape')
        cases.append(case)
    for stage in ('record', 'history'):
        case = copy.deepcopy(base)
        case.update(throw_stage=stage, boundary_case='record_or_history_exception')
        cases.append(case)
    for extra in (['--remember-strategy'], ['--record-strategy', '--remember-strategy'],
                  ['--record-strategy', '--no-strategy-history'], []):
        case = copy.deepcopy(base)
        case.update(rest=base['rest'][:-1] + extra, boundary_case='explicit_record_flags')
        cases.append(case)
    for overrides in ({'history': None}, {'port': False}, {'cdp': {'Json': {'status': 'partial'}}},
                      {'history_file': None}, {'history_file': ''},
                      {'rest': ['--match', 'Fixture', '--no-probe', '--record-strategy'], 'history': None}):
        case = copy.deepcopy(base)
        case.update(overrides, boundary_case='record_gate_or_destination')
        cases.append(case)
    return cases


def receipt_transport_fixtures():
    """History must not be copied one level deeper into the returned receipt."""
    cases = []
    for depth in (18, 19):
        case = copy.deepcopy(record_boundary_fixtures()[0])
        nested = 'fixture_leaf'
        for _ in range(depth):
            nested = {'child': nested}
        case['history']['extra'] = nested
        case['boundary_case'] = f'deep_history_{depth}'
        cases.append(case)
    near_limit = copy.deepcopy(record_boundary_fixtures()[0])
    near_limit['history']['extra'] = 'x' * 1040000
    near_limit['record'] = {'success': True, 'extra': 'r' * 20000}
    near_limit['boundary_case'] = 'near_request_limit_record_result'
    cases.append(near_limit)
    return cases


CAPTURE_RUNNER = r'''
param([string]$Source,[string]$InputPath,[string]$CandidatePath,[switch]$CurrentBridge,[string]$AdapterPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Pinned source did not parse'}
$names=@('_Read-OptValue','_Read-AllOptValues','_Read-Switch','_TaskPlan-QuoteToken','_TaskPlan-StepString',
         '_AppStrategy-NormalizeRoute','_AppStrategy-Key','_AppProfile-StrategyScore','Invoke-MacroAppProfile')
if($CurrentBridge){$names=@('_Invoke-LegacyCompatibility','_Read-OptValue','_Read-AllOptValues','_Read-Switch','_AppStrategy-Key','Invoke-MacroAppProfile')}
foreach($name in $names){
 $functionAst=$ast
 if($CurrentBridge -and $AdapterPath -and $name -eq 'Invoke-MacroAppProfile'){
  $functionAst=[Management.Automation.Language.Parser]::ParseFile($AdapterPath,[ref]$tokens,[ref]$errors)
  if($errors.Count){throw 'Draft adapter did not parse'}
 }
 $fn=@($functionAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($fn.Count -ne 1){throw "Expected exact source function $name"}
 $body=$fn[0].Extent.Text
 if($name -eq 'Invoke-MacroAppProfile'){
   # Only measured elapsed values are normalized; payload/format/error code is unchanged.
   if($CurrentBridge){
    $pattern='\[int\]\$(?:cdpWatch|uiaWatch|sw)\.Elapsed\.TotalMilliseconds'
    if([regex]::Matches($body,$pattern).Count -ne 3){throw 'Expected three retained-adapter elapsed seams'}
   }else{
    $pattern='\[int\]\$(?:pSw|sw)\.Elapsed\.TotalMilliseconds'
    if([regex]::Matches($body,$pattern).Count -ne 4){throw 'Expected four app-profile elapsed seams'}
   }
   $body=[regex]::Replace($body,$pattern,'0')
   if(-not $CurrentBridge){
    # Observe the original local object before its retained depth-limited
    # serialization. This assignment changes no payload, output or acquisition.
    $formatSeam='(?m)^[ \t]+if \(\$Brief -and -not \$jsonOnly\)'
    if([regex]::Matches($body,$formatSeam).Count -ne 2){throw 'Expected two original app-profile Console branches'}
    $body=[regex]::Replace($body,$formatSeam,'  $script:OriginalProfileRawPayload=$payload' + "`n" + '$0')
   }
 }
 . ([scriptblock]::Create($body))
}
if($CurrentBridge){
 # Count calls while executing the exact extracted transport, including each
 # real native process. This wrapper changes neither arguments nor responses.
 $script:ActualProfileBridge=${function:_Invoke-LegacyCompatibility}
 function _Invoke-LegacyCompatibility {
  param([string]$Operation,[hashtable]$Arguments,[switch]$PreserveInvalidArguments)
  if($script:appendObserved){throw 'Fixture forbids compatibility transport after Append'}
  $script:bridgeCalls++
  $frame=@{schema='cucp.legacy-compat/v1';operation=$Operation;args=$Arguments;culture=[Globalization.CultureInfo]::CurrentCulture.Name}|ConvertTo-Json -Depth 24 -Compress
  $script:maxBridgeRequestBytes=[Math]::Max($script:maxBridgeRequestBytes,[Text.Encoding]::UTF8.GetByteCount($frame))
  $response=& $script:ActualProfileBridge @PSBoundParameters
  $script:kernelEvaluations += [int]$response.kernel_evaluations
  return $response
 }
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
 $script:appendObserved=$true
 $script:bridgeCallsAtAppend=$script:bridgeCalls
 Capture-Reply 'record' @("$AppKey","$AppType","$Strategy","$Confidence","$Score","$Process","$Class","$Title") 'record' $script:fixture.record
}
$candidateResults=if($CandidatePath){@(Get-Content -LiteralPath $CandidatePath -Raw -Encoding UTF8|ConvertFrom-Json)}else{@()}
$all=New-Object Collections.ArrayList;$caseIndex=0
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$fixture;$script:queries=New-Object Collections.ArrayList;$script:replies=New-Object Collections.ArrayList
 $script:bridgeCalls=0;$script:kernelEvaluations=0;$script:appendObserved=$false;$script:bridgeCallsAtAppend=$null;$script:maxBridgeRequestBytes=0;$script:OriginalProfileRawPayload=$null
 [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$fixture.culture)
 $Brief=[bool]$fixture.brief;$Script:AppStrategyFile=$fixture.history_file
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
 try{
  $exitCode=Invoke-MacroAppProfile -Rest $fixture.rest
  $console=$writer.ToString();$raw=$console.TrimEnd([char[]]"`r`n")
  if($Brief -and -not ($fixture.rest -contains '--json-only')){$payload=$null;$capturedBriefText=$raw;$depth=if($exitCode -eq 2){12}else{14}}
  else{$payload=$raw|ConvertFrom-Json;$capturedBriefText=$null;$depth=if($payload.status -eq 'partial'){12}else{14}}
  $expected=@{state='complete';payload=$payload;exit=[int]$exitCode;brief=$capturedBriefText;json_depth=$depth;queries=@($script:queries)}
 }catch{$expected=@{state='error';error=$_.Exception.Message;queries=@($script:queries)}}
 finally{[Console]::SetOut($previous);$expected['console']=$writer.ToString();$writer.Dispose()}
 $entry=@{expected=$expected;args=@{rest=@($fixture.rest);brief=[bool]$fixture.brief;culture=[string]$fixture.culture;history_file=$fixture.history_file;elapsed_ms=0;cdp_elapsed_ms=0;uia_elapsed_ms=0;captured_replies=@($script:replies)}}
 if(-not $CurrentBridge){$entry['raw_payload']=$script:OriginalProfileRawPayload}
 if($CurrentBridge){
  $entry['bridge_calls']=$script:bridgeCalls;$entry['kernel_evaluations']=$script:kernelEvaluations
  $entry['bridge_calls_at_append']=$script:bridgeCallsAtAppend
  $entry['max_bridge_request_bytes']=$script:maxBridgeRequestBytes
  if($fixture.boundary_case -eq 'near_request_limit_record_result'){
   # A hypothetical final replay already exceeds the cap without any receipt.
   # The real adapter must instead finish from its prevalidated completion.
   $postFrame=@{schema='cucp.legacy-compat/v1';operation='app-profile-advance';args=$entry.args;culture=[Globalization.CultureInfo]::CurrentCulture.Name}|ConvertTo-Json -Depth 24 -Compress
   $entry['hypothetical_final_request_bytes']=[Text.Encoding]::UTF8.GetByteCount($postFrame)
  }
 }
 if($CandidatePath){
  $state=$candidateResults[$caseIndex];$writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer)
  try{
   if($state.state -eq 'complete'){
    if($null -ne $state.brief){[Console]::Out.WriteLine([string]$state.brief)}
    else{[Console]::Out.WriteLine(($state.payload|ConvertTo-Json -Depth ([int]$state.json_depth)))}
   }
  }finally{
   [Console]::SetOut($previous);$entry['candidate_console']=$writer.ToString()
   $entry['candidate_payload']=if($state.state -eq 'complete' -and $null -eq $state.brief){$writer.ToString()|ConvertFrom-Json}else{$null}
   $writer.Dispose()
  }
 }
 [void]$all.Add($entry);$caseIndex++
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 64 -Compress))
'''


class AppProfileSourceTests(unittest.TestCase):
    def test_kernel_is_pure_and_oracle_is_pinned(self):
        source = (ROOT / 'pcucp-next/dotnet/PcuCp.LegacyAppProfile/LegacyAppProfileKernel.cs').read_text()
        for forbidden in ('Process.Start', 'System.Management.Automation', 'HttpClient', 'File.Read', 'File.Write', 'SendInput'):
            self.assertNotIn(forbidden, source)
        self.assertGreaterEqual(len(fixtures()), 300)
        host = (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/PcuCp.NativeHost.csproj').read_text()
        dispatcher = (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/LegacyCompatibilityDispatcher.cs').read_text()
        # The pure candidate may be centrally registered only with its source link.
        self.assertEqual('LegacyAppProfile' in host, '"app-profile-advance" => LegacyAppProfileController.Advance(args)' in dispatcher)
        self.assertIn("if([regex]::Matches($body,$pattern).Count -ne 4)", CAPTURE_RUNNER)
        self.assertIn('Expected two original app-profile Console branches', CAPTURE_RUNNER)
        self.assertIn('$script:OriginalProfileRawPayload=$payload', CAPTURE_RUNNER)
        self.assertIn("'_AppProfile-StrategyScore'", CAPTURE_RUNNER)
        self.assertIn('brief=[bool]$fixture.brief;', CAPTURE_RUNNER)
        self.assertNotIn('$brief=$', CAPTURE_RUNNER.lower())


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell 5.1 app-profile oracle')
class AppProfileWindowsTests(unittest.TestCase):
    maxDiff = None

    def test_runtime_array_capture_wire_and_boolean_condition(self):
        values = [[], [False], [False, False], ['single'], ['first', 'second'],
                  [[False]], [[], []], {'value': [], 'Count': 0},
                  {'value': [False], 'Count': 1}, None, False, 'false']
        script = r'''
param([string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
function Emit-Reply {param($Value) Write-Output -NoEnumerate $Value}
$results=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $received=Emit-Reply -Value $fixture.value
 $originalCondition=if(Emit-Reply -Value $fixture.value){$true}else{$false}
 $capture=@{result=$received}
 $runtimeArray=$capture.result -is [array]
 if($runtimeArray){$capture.result=$capture.result.Clone()}
 $wire=$capture|ConvertTo-Json -Depth 24 -Compress
 [void]$results.Add(@{runtime_array=$runtimeArray;wire=$wire;condition=$originalCondition;boolean_capture=[bool](Emit-Reply -Value $fixture.value)})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
'''
        with tempfile.TemporaryDirectory(prefix='CUCP array wire ') as temp:
            root = Path(temp)
            source = root / 'wire.ps1'; source.write_text(script, encoding='utf-8-sig')
            inputs = root / 'inputs.json'; inputs.write_text(json.dumps([{'value': value} for value in values]), encoding='utf-8-sig')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(source), '-InputPath', str(inputs)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            rows = json.loads(result.stdout.decode('utf-8-sig'))
            self.assertEqual(len(rows), len(values))
            for value, row in zip(values, rows):
                with self.subTest(value=value):
                    self.assertEqual(row['runtime_array'], isinstance(value, list))
                    self.assertEqual(json.loads(row['wire'])['result'], value)
                    self.assertEqual(row['boolean_capture'], row['condition'])
            self.assertEqual([row['condition'] for row in rows[:3]], [False, False, True])
            self.assertTrue(rows[7]['condition'])

    def test_a_characterize_fresh_and_mixed_culture_regex_cache(self):
        # The public wrapper dispatches once and exits. This deliberately mixed
        # test documents why changing culture in one oracle process is unsafe.
        baseline = subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT)
        text = baseline.decode('utf-8-sig')
        dispatch = text[text.index('# Macro path'):]
        self.assertIn('$code = Invoke-Macro -ArgList $CucpArgs', dispatch)
        self.assertLess(dispatch.index('exit $code'), dispatch.index('# Direct CLI passthrough'))
        self.assertNotIn('CurrentCulture=', text)
        self.assertNotIn('CurrentCulture =', text)
        base = copy.deepcopy(fixtures()[0])
        base.update(rest=['--no-probe'], culture='en-US')
        base['windows'][0].update(process='fİrefox', title='Fixture')
        fresh = copy.deepcopy(base); fresh['culture'] = ''
        with tempfile.TemporaryDirectory(prefix='CUCP culture boundary ') as temp:
            root = Path(temp)
            source = root/'original.ps1'; source.write_bytes(baseline)
            runner = root/'capture.ps1'; runner.write_text(CAPTURE_RUNNER, encoding='utf-8-sig')
            def capture(items, name):
                inputs=root/(name+'.json'); inputs.write_text(json.dumps(items, ensure_ascii=True), encoding='utf-8-sig')
                result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),'-Source',str(source),'-InputPath',str(inputs)],capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
                return json.loads(result.stdout.decode('utf-8-sig'))
            fresh_result=capture([fresh],'fresh')[0]['expected']
            mixed_result=capture([base,fresh],'mixed')[1]['expected']
            self.assertEqual(fresh_result['payload']['app_type'],'win32_desktop')
            self.assertEqual(fresh_result['payload']['strategy_persistence']['app_key'],'f-refox|mainwindow|win32_desktop')
            self.assertEqual(mixed_result['payload']['app_type'],'browser_or_electron')
            self.assertEqual(mixed_result['payload']['strategy_persistence']['app_key'],'fİrefox|mainwindow|browser_or_electron')
            self.assertEqual(fresh_result['exit'],0)
            self.assertEqual(mixed_result['exit'],0)

    def test_complete_payload_errors_order_argv_exit_and_console(self):
        cases = fixtures() + record_boundary_fixtures() + receipt_transport_fixtures()
        # Keep every original case and every assertion. Fresh processes retain
        # each public invocation's ambient culture, without an earlier culture's
        # cached PowerShell -match/-replace regexes contaminating later cases.
        for culture in dict.fromkeys(case['culture'] for case in cases):
            with self.subTest(culture=culture):
                self.compare_cases([case for case in cases if case['culture']==culture])

    def compare_cases(self, cases):
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
            for fixture, old in zip(cases, captured):
                if fixture.get('boundary_case') == 'seven_queries_high_confidence':
                    self.assertEqual([q['kind'] for q in old['expected']['queries']],
                                     ['windows', 'windows', 'cdp_port', 'native', 'uia', 'history', 'record'])
                    self.assertEqual(old['expected']['payload']['strategy_score']['confidence'], 'high')
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
                    if expected['state'] == 'complete':
                        expected = {**expected, 'payload': old['raw_payload']}
                    self.assertEqual(new, expected)
                    if old['expected']['state'] == 'complete':
                        self.assertEqual(console['candidate_payload'], old['expected']['payload'])
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


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_APP_PROFILE_TEST_HOST'),
                     'Requires Windows retained app-profile adapter and matching native host')
class AppProfileAdapterWindowsTests(unittest.TestCase):
    maxDiff = None

    def test_actual_bridge_all_payloads_console_errors_exits_and_queries(self):
        self.assertEqual(len(fixtures()), 496)
        cases = fixtures() + record_boundary_fixtures() + receipt_transport_fixtures()
        for culture in dict.fromkeys(case['culture'] for case in cases):
            with self.subTest(culture=culture), tempfile.TemporaryDirectory(prefix='CUCP profile bridge 한글 ') as temp:
                root = Path(temp)
                source = root / 'original.ps1'
                source.write_bytes(subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT))
                selected = [case for case in cases if case['culture'] == culture]
                inputs = root / 'fixtures.json'
                inputs.write_text(json.dumps(selected, ensure_ascii=True), encoding='utf-8-sig')
                runner = root / 'capture.ps1'
                runner.write_text(CAPTURE_RUNNER, encoding='utf-8-sig')
                command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner), '-InputPath', str(inputs)]
                env = {**os.environ, 'CUCP_NATIVE_HOST': os.environ['CUCP_APP_PROFILE_TEST_HOST']}
                before = subprocess.run([*command, '-Source', str(source)], env=env, capture_output=True, timeout=180)
                bridge = [*command, '-Source', str(ROOT / 'scripts/cucp.ps1'), '-CurrentBridge']
                if os.environ.get('CUCP_APP_PROFILE_ADAPTER_SOURCE'):
                    bridge += ['-AdapterPath', os.environ['CUCP_APP_PROFILE_ADAPTER_SOURCE']]
                after = subprocess.run(bridge, env=env, capture_output=True, timeout=900)
                self.assertEqual(before.returncode, 0, before.stderr.decode('utf-8', errors='replace'))
                self.assertEqual(after.returncode, 0, after.stderr.decode('utf-8', errors='replace'))
                old = json.loads(before.stdout.decode('utf-8-sig'))
                new = json.loads(after.stdout.decode('utf-8-sig'))
                self.assertEqual(len(old), len(selected))
                self.assertEqual(len(new), len(selected))
                for fixture, left, right in zip(selected, old, new):
                    with self.subTest(fixture=fixture):
                        # Compare real Console text, JSON, exit/error and only real
                        # acquisition traces. Preflight supplies data; it calls no stub.
                        self.assertEqual(right['expected'], left['expected'])
                        trace = right['expected']['queries']
                        record_count = sum(query['kind'] == 'record' for query in trace)
                        self.assertLessEqual(record_count, 1)
                        self.assertLessEqual(len(trace), 7)
                        self.assertLessEqual(right['bridge_calls'], 7)
                        self.assertLessEqual(right['kernel_evaluations'], 8)
                        # Numeric/semantic input failures now also pass through
                        # the facade. Preflight is a second internal evaluation,
                        # never an extra acquisition or a native process retry.
                        self.assertEqual(right['bridge_calls'], len(trace) + 1 - record_count)
                        self.assertEqual(right['kernel_evaluations'], len(trace) + 1)
                        if record_count:
                            self.assertEqual(right['bridge_calls'], right['bridge_calls_at_append'])
                        else:
                            self.assertIsNone(right['bridge_calls_at_append'])
                        if fixture.get('boundary_case') == 'seven_queries_high_confidence':
                            self.assertEqual(len(trace), 7)
                            self.assertEqual(record_count, 1)
                            self.assertEqual(right['bridge_calls'], 7)
                            self.assertEqual(right['kernel_evaluations'], 8)
                        if fixture.get('boundary_case') == 'near_request_limit_record_result':
                            self.assertEqual(record_count, 1)
                            self.assertGreater(right['max_bridge_request_bytes'], 1040000)
                            self.assertLessEqual(right['max_bridge_request_bytes'], 1048576)
                            self.assertGreater(right['hypothetical_final_request_bytes'], 1048576)
