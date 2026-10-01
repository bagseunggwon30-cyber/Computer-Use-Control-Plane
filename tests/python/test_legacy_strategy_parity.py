"""Exact strategy-policy differential; supplied probes/history only, no real probing."""
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


def strategy_cases():
    cases = []
    for route in (None, '', 'CDP-click+fallback', 'uia_set_value', 'UIA_PATTERN', 'uia_precision_point',
                  'uia_coord', 'fusion_uia_invoke', 'fusion_coord', 'ocr_text', 'vision_precise',
                  ' custom ', 'uia_pattern\n', 'custom+a\nb', 'É', 'e\u0301'):
        cases.append({'operation': 'strategy-normalize', 'args': {'strategy': route}})
    route_orders = [[], ['uia_pattern', 'uia_click', 'precision_point', 'ocr'],
                    ['cdp_dom', 'uia_pattern', 'uia_click', 'ocr', 'precision_point'],
                    ['uia_set_value', 'safe_type_guarded', 'shortcut', 'precision_point', 'ocr']]
    for order, browser, office, no_probe in itertools.product(route_orders, (False, True), (False, True), (False, True)):
        cases.append({'operation': 'strategy-score', 'args': {'app_type': 'fixture', 'route_order': order,
                       'browser_like': browser, 'office_like': office, 'no_probe': no_probe,
                       'labels': ['Save', 'save', 'Save', '', ' ', None]}})
    for cdp, uia, persisted in itertools.product(
            (None, {}, {'available': False, 'reason': 'not running', 'port': 9222}, {'available': True, 'reason': 'ready', 'port': 9222}),
            (None, {}, {'available': False, 'affordance_count': 0},
             {'available': True, 'affordance_count': 5, 'small_icon_count': 2, 'label_hits': [{'found': True}, {'found': False}, {'found': True}]}),
            (None, {'strategy': 'uia_coord+fallback', 'source': 'history'})):
        cases.append({'operation': 'strategy-score', 'args': {'route_order': ['cdp_dom', 'uia_pattern', 'uia_click', 'ocr'],
                       'cdp_probe': cdp, 'uia_probe': uia, 'persisted_strategy': persisted,
                       'labels': ['é', 'e\u0301', 'É', '가', '가', ' save ', 'save']}})
    for order in (['é', 'e\u0301'], ['e\u0301', 'é'], ['가', '가'], ['가', '가'], ['uia_pattern'] * 40, ['', None, 'ocr_text', 'fusion_coord', 'uia_coord', 'uia_click'],
                  ['z', 'ä', 'a', 'é', 'e\u0301', '가', '가', 'I', 'İ', 'ı', 'i'],
                  ['a0'] * 8 + ['é', 'e\u0301', '가', '가', 'z'],
                  ['z'] * 8 + ['가', '가', 'e\u0301', 'é', 'a']):
        cases.append({'operation': 'strategy-score', 'args': {'route_order': order, 'office_like': False}})
    return cases


class StrategyFixtureTests(unittest.TestCase):
    def test_fixture_matrix_covers_culture_duplicates_and_probe_states(self):
        cases = strategy_cases()
        self.assertGreaterEqual(len(cases), 80)
        self.assertTrue(any(c['operation'] == 'strategy-normalize' and c['args']['strategy'] == ' custom ' for c in cases))


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_NATIVE_TEST_HOST'), 'Requires Windows legacy compatibility dispatcher')
class LegacyStrategyParityTests(unittest.TestCase):
    maxDiff = None
    def test_whole_strategy_results_match_pinned_powershell(self):
        self.compare_cases(strategy_cases())

    def test_process_local_culture_parity(self):
        project = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyStrategy.CultureTests'
        with tempfile.TemporaryDirectory(prefix='CUCP culture harness ') as temp:
            build = subprocess.run([shutil.which('dotnet'), 'build', str(project), '-c', 'Release', '--output', temp], capture_output=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout.decode('utf-8', errors='replace') + build.stderr.decode('utf-8', errors='replace'))
            host = Path(temp) / 'PcuCp.LegacyStrategy.CultureTests.dll'
            cases = []
            for order in (['I', 'i', 'İ', 'ı'], ['é', 'e\u0301'], ['가', '가'], ['ä', 'a', 'å'], ['straße', 'strasse']):
                for routes in (order, list(reversed(order))):
                    cases.append({'operation': 'strategy-score', 'args': {'route_order': routes, 'labels': order + order}})
            for culture in ('en-US', 'ko-KR', 'tr-TR', ''):
                with self.subTest(culture=culture):
                    self.compare_cases(cases, culture=culture, fixture_host=host)
                    self.compare_cases(cases, culture=culture, fixture_host=host, explicit_culture=True)

    def compare_cases(self, cases, culture=None, fixture_host=None, explicit_culture=False):
        if explicit_culture:
            cases = [{**c, 'args': {**c['args'], 'culture': culture}} for c in cases]
        source_data = subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT)
        with tempfile.TemporaryDirectory(prefix='CUCP strategy 한글 ') as temp:
            root = Path(temp)
            source, inputs, runner = root / 'original.ps1', root / 'cases.json', root / 'runner.ps1'
            source.write_bytes(source_data)
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            runner.write_text(r'''
param([string]$SourcePath,[string]$InputPath,[string]$CultureName,[switch]$SetCulture)
if ($SetCulture) { [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($(if ($CultureName -eq '__invariant__') { '' } else { $CultureName })) }
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source did not parse' }
foreach ($name in @('_AppStrategy-NormalizeRoute','_AppProfile-StrategyScore')) {
  $functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($functions.Count -ne 1) { throw "Expected one exact baseline function: $name" }
  . ([scriptblock]::Create($functions[0].Extent.Text))
}
$results=New-Object Collections.ArrayList
foreach ($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  $a=$case.args
  if ($case.operation -eq 'strategy-normalize') { $result=@{value=(_AppStrategy-NormalizeRoute -Strategy $a.strategy)} }
  else {
    $result=_AppProfile-StrategyScore -AppType $a.app_type -RouteOrder $a.route_order -CdpProbe $a.cdp_probe -UiaProbe $a.uia_probe -Labels $a.labels -PersistedStrategy $a.persisted_strategy -BrowserLike ([bool]$a.browser_like) -OfficeLike ([bool]$a.office_like) -NoProbe ([bool]$a.no_probe)
  }
  [void]$results.Add($result)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            baseline = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
                                       '-SourcePath', str(source), '-InputPath', str(inputs), *([] if culture is None else ['-SetCulture', '-CultureName', culture or '__invariant__'])], capture_output=True, timeout=30)
            self.assertEqual(baseline.returncode, 0, baseline.stderr.decode('utf-8', errors='replace'))
            expected = json.loads(baseline.stdout.decode('utf-8-sig'))
            self.assertEqual(len(expected), len(cases))
            host = fixture_host or Path(os.environ['CUCP_NATIVE_TEST_HOST'])
            native = [str(host)] if host.suffix.lower() == '.exe' else [shutil.which('dotnet'), str(host)]
            for case, before in zip(cases, expected):
                with self.subTest(case=case):
                    result = subprocess.run([*native, *( ['legacy-compat'] if culture is None else [('en-US' if explicit_culture else culture)])], input=json.dumps({'schema': 'cucp.legacy-compat/v1', **case}, ensure_ascii=True).encode(),
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                    after = json.loads(result.stdout.decode('utf-8-sig'))
                    self.assertEqual(after['status'], 'ok', after)
                    self.assertEqual(after['data'], before)
