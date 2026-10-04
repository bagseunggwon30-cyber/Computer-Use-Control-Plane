"""Historical functions versus actual wrapper/Python bridge on owned files."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_cdp_bridge import handle
from pcucp_cli.legacy_host_protocol import LegacyHostError

BASE = '03e021d359515be338e5b382b458f51eafed30de'
HANDLERS = ('Invoke-MacroHistory', '_History-Append', '_History-PickBestStrategy', '_History-Stats')


class HistoryBoundaryTests(unittest.TestCase):
    def test_json_cannot_change_destination_or_retention_or_launch_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'history.ndjson')
            for request in (
                dict(action='stats', args={}, history_file=path),
                dict(action='clear', args={}),
                dict(action='append', args=dict(label='a', match='b', strategy='c', success=True, elapsed_ms=True)),
                dict(action='pick', args=dict(label='a', match='b', lookback=True)),
                dict(action='macro', args=dict(rest=[], brief=False, allow_live_control=True)),
            ):
                with self.subTest(request=request), self.assertRaises((ValueError, LegacyHostError)):
                    handle('history-storage', request, history_file=path, history_maximum=1000)
            self.assertFalse(Path(path).exists())

    def test_startup_paths_and_limits_are_required_and_separate(self):
        for kwargs in ({}, dict(history_file='relative', history_maximum=1000),
                       dict(history_file=str(ROOT / 'work.ndjson'), history_maximum=0),
                       dict(history_file=str(ROOT / 'work.ndjson'), history_maximum=1000, endpoint='http://localhost')):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, LegacyHostError)):
                handle('history-storage', dict(action='stats', args={}), **kwargs)
        with self.assertRaises(ValueError):
            handle('native-prepare', dict(argv=[]), history_file=str(ROOT / 'unused'))


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Actual Windows history bridge')
class ProductionHistoryParityTests(unittest.TestCase):
    def test_all_305_existing_history_reducer_cases_with_caller_scalar_facts(self):
        import test_legacy_history_reducers as historical
        cases = [case for case in historical.fixtures() if case['operation'] in ('pick', 'stats')]
        for successful in (1, 3, 113):
            cases.append(dict(id=f'stats-decimal-midpoint-{successful}', operation='stats', culture='en-US', exists=True,
                              lines=[json.dumps(dict(strategy='x', success=i < successful)) for i in range(2000)]))
        with tempfile.TemporaryDirectory(prefix='CUCP history corpus ') as directory:
            owned = Path(directory)
            source = historical.materialize_original(owned)
            inputs = owned / 'cases.json'
            inputs.write_bytes(historical.input_bytes(cases))
            capture = owned / 'capture.ps1'
            capture.write_text(r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_History-Capture'},$true))
if($e.Count -or $f.Count -ne 1){throw 'Invalid capture source.'}
. ([scriptblock]::Create($f[0].Extent.Text))
function _Invoke-LegacyCdpBridge {param($Operation,$Request) if($Operation -ne 'history-storage' -or $Request.action -ne 'read'){throw 'Unexpected acquisition.'};return @{exists=[bool]$script:case.exists;lines=[string[]]$script:case.lines}}
$results=New-Object Collections.ArrayList
foreach($script:case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json).fixtures){
 [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$case.culture)
 $result=_History-Capture -Label ([string]$case.label) -Match ([string]$case.match) -Pick:($case.operation -eq 'pick') -Stats:($case.operation -eq 'stats')
 [void]$results.Add($result)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 64 -Compress))
''', encoding='utf-8-sig')
            for runtime, host in (('ps51', shutil.which('powershell.exe')), ('ps7', shutil.which('pwsh.exe'))):
                if not host:
                    continue
                expected_process = subprocess.run([host, '-NoProfile', '-NonInteractive', '-File', str(historical.FIXTURES / 'oracle.ps1'),
                    '-InputPath', str(inputs), '-SourcePath', str(source), '-Runtime', runtime], capture_output=True, timeout=90)
                self.assertEqual(expected_process.returncode, 0, expected_process.stderr.decode('utf-8', errors='replace'))
                expected = json.loads(expected_process.stdout.decode('utf-8-sig'))['results']
                facts_process = subprocess.run([host, '-NoProfile', '-NonInteractive', '-File', str(capture),
                    '-InputPath', str(inputs), '-Source', str(ROOT / 'scripts/cucp.ps1')], capture_output=True, timeout=90)
                self.assertEqual(facts_process.returncode, 0, facts_process.stderr.decode('utf-8', errors='replace'))
                captures = json.loads(facts_process.stdout.decode('utf-8-sig'))
                self.assertEqual(len(captures), len(expected))
                for case, before, captured in zip(cases, expected, captures):
                    arguments = dict(rows=captured['rows'])
                    if case['operation'] == 'pick':
                        arguments['lookback'] = case.get('lookback', 5)
                    reply = handle('history-storage', dict(action=case['operation'], args=arguments),
                                   history_file=str(owned / 'unused.ndjson'), history_maximum=1000)
                    actual = reply['value']
                    if case['operation'] == 'stats':
                        actual['strategies'] = {pair['name']: pair['count'] for pair in reply['strategy_pairs']}
                    if reply.get('tie'):
                        # The final linguistic -contains comparison belongs to
                        # the caller; every tie in this corpus chooses its most
                        # recent successful top group.
                        actual = next(row['strategy'] for row in reply['candidates']
                                      if row['success'] and row['strategy'] in reply['top'])
                    expected_value = json.loads(before['compact_json']) if before['compact_json'] else None
                    with self.subTest(runtime=runtime, case=case['id']):
                        self.assertEqual(actual, expected_value)

    def test_selection_statistics_reports_clear_append_and_rotation(self):
        base = subprocess.check_output(['git', 'show', BASE + ':scripts/cucp.ps1'], cwd=ROOT)
        cases = []
        rows = [dict(label='Save', match='Editor', strategy='UIA', success=True, elapsed_ms=4),
                dict(label='Save', match='Editor', strategy='OCR', success=True, elapsed_ms=5),
                dict(label='SAVE', match='editor', strategy='uia', success=False, elapsed_ms=6),
                dict(label='Save', match='Editor', strategy='OCR', success='True', elapsed_ms=7)]
        fixtures = [None, [], [json.dumps(rows[0])], ['broken', *map(json.dumps, rows), '{'],
                    ['null', 'false', '0', '"text"', '{}'],
                    [json.dumps(dict(label='한글😀', match='Editor', strategy='é', success=v))
                     for v in (True, False, 0, 1, 2, 'True', 'false', [True], [False], [False, True])],
                    [json.dumps(dict(rows[0], strategy=key)) for key in ('Keys', 'Values', 'Count', 'psobject', 'GetType', '')]]
        for lines in fixtures:
            for rest in ([], ['show', '--last', '1'], ['show', '--label', 'save', '--last', '0x3'],
                         ['stats'], ['clear']):
                for brief in (False, True):
                    cases.append(dict(handler='Invoke-MacroHistory', lines=lines, rest=rest, brief=brief))
            for lookback in (0, -1, 1, 2, 5):
                cases.append(dict(handler='_History-PickBestStrategy', lines=lines, lookback=lookback))
        for rest in (['wrong'], ['show', '--last', 'bad'], ['show', '--last', '2147483648']):
            cases.append(dict(handler='Invoke-MacroHistory', lines=[], rest=rest, brief=False))
        large = [json.dumps(dict(rows[0], detail='가' * 1200)) for _ in range(300)]
        cases.append(dict(handler='Invoke-MacroHistory', lines=large, rest=['show', '--last', '1'], brief=False))
        for handler, rest in (('_History-PickBestStrategy', []), ('_History-Stats', []),
                              ('Invoke-MacroHistory', ['show']), ('Invoke-MacroHistory', ['stats'])):
            cases.append(dict(handler=handler, lines=[json.dumps(rows[0])], rest=rest, brief=False, locked=True, lookback=5))
        for lines in (None, [json.dumps(rows[0])], [' ' * 600000, ' ' * 600000]):
            cases.append(dict(handler='_History-Append', lines=lines))
        for lines in (None, [json.dumps(rows[0])], [json.dumps(dict(rows[0], success=False))],
                      [json.dumps(rows[0]), json.dumps(dict(rows[0], success=False))]):
            cases.append(dict(handler='_History-Stats', lines=lines))
        with tempfile.TemporaryDirectory(prefix='CUCP history 한글 ') as directory:
            owned = Path(directory)
            original = owned / 'original.ps1'
            original.write_bytes(base)
            inputs = owned / 'input.json'
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            oracle = owned / 'oracle.ps1'
            oracle.write_text(r'''
param([string]$Source,[string]$InputPath,[string]$Owned,[switch]$Current)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Source did not parse.'}
foreach($name in @('_Read-OptValue','Invoke-MacroHistory','_History-Append','_History-PickBestStrategy','_History-Stats')){
 $function=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
 if($function.Count -ne 1){throw 'Missing function.'}
 . ([scriptblock]::Create($function[0].Extent.Text))
}
if($Current){
 $function=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq '_History-Capture'},$true))
 if($function.Count -ne 1){throw 'Missing capture function.'}
 . ([scriptblock]::Create($function[0].Extent.Text))
 $Script:LegacyCdpSourceRoot=Split-Path -Parent (Split-Path -Parent $Source)
 . (Join-Path $Script:LegacyCdpSourceRoot 'scripts/cucp-legacy-cdp-adapter.ps1')
}
$Script:HistoryFile=Join-Path $Owned 'smart-click-history.ndjson';$Script:HistoryMax=2
$results=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 Remove-Item -LiteralPath $Script:HistoryFile -Force -ErrorAction SilentlyContinue
 if($null -ne $case.lines){[IO.File]::WriteAllLines($Script:HistoryFile,[string[]]$case.lines,(New-Object Text.UTF8Encoding($true)))}
 $Brief=[bool]$case.brief;$value=$null;$errorText=$null;$exit=$null
 $previous=[Console]::Out;$writer=New-Object IO.StringWriter;$locked=$null
 if($case.locked){$locked=[IO.File]::Open($Script:HistoryFile,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
 try{
  [Console]::SetOut($writer)
  switch($case.handler){
   'Invoke-MacroHistory' {$exit=Invoke-MacroHistory -Rest ([string[]]$case.rest)}
   '_History-PickBestStrategy' {$value=_History-PickBestStrategy -Label 'Save' -Match 'Editor' -LookbackN ([int]$case.lookback)}
   '_History-Stats' {$value=_History-Stats}
   '_History-Append' {_History-Append -Label '한글😀' -Match 'Editor' -Strategy 'UIA' -Success $true -ElapsedMs 7}
  }
 }catch{$errorText=$_.Exception.Message}finally{[Console]::SetOut($previous);if($null -ne $locked){$locked.Dispose()}}
 $records=@()
 if($case.handler -eq '_History-Append' -and (Test-Path -LiteralPath $Script:HistoryFile)){
  foreach($line in (Get-Content -LiteralPath $Script:HistoryFile -Encoding UTF8)){try{$row=$line|ConvertFrom-Json -ErrorAction Stop;$row.PSObject.Properties.Remove('ts');$records+=$row}catch{}}
 }
 $mapType='';$rateType='';if($case.handler -eq '_History-Stats' -and $null -ne $value){$mapType=$value.strategies.GetType().FullName;$rateType=$value.success_rate.GetType().FullName}
 [void]$results.Add(@{output=$writer.ToString();value=$value;exit=$exit;failed=($null -ne $errorText);records=$records;exists=(Test-Path -LiteralPath $Script:HistoryFile);map_type=$mapType;rate_type=$rateType})
 $writer.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            for host in filter(None, (shutil.which('powershell.exe'), shutil.which('pwsh.exe'))):
                def run(source, current=False):
                    command = [host, '-NoProfile', '-NonInteractive', '-File', str(oracle), '-Source', str(source),
                               '-InputPath', str(inputs), '-Owned', str(owned)] + (['-Current'] if current else [])
                    env = dict(os.environ, CUCP_LEGACY_CDP_PYTHON=sys.executable)
                    process = subprocess.run(command, env=env, capture_output=True, timeout=240)
                    self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))
                    return json.loads(process.stdout.decode('utf-8-sig'))
                expected, actual = run(original), run(ROOT / 'scripts/cucp.ps1', True)
                self.assertEqual(len(expected), len(actual))
                for case, before, after in zip(cases, expected, actual):
                    with self.subTest(host=Path(host).name, case=case):
                        for key in ('value', 'exit', 'failed', 'records', 'exists', 'map_type', 'rate_type'):
                            self.assertEqual(after[key], before[key], key)
                        if not before['failed']:
                            if case.get('brief'):
                                self.assertEqual(after['output'], before['output'])
                            elif before['output']:
                                self.assertEqual(json.loads(after['output']), json.loads(before['output']))
                            else:
                                self.assertEqual(after['output'], '')


if __name__ == '__main__':
    unittest.main()
