"""Characterize PS5 regex alias folding independently from NLS route collation."""
import copy
import itertools
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_legacy_strategy_parity as strategy

ROOT = Path(__file__).resolve().parents[2]


def alias_cases():
    aliases = ['uia_set_value', 'uia_pattern', 'uia_precision_point', 'uia_coord',
               'fusion_uia_invoke', 'fusion_coord', 'ocr_text', 'vision_precise']
    values = ['custom', ' custom ', 'cdp-click+fallback', 'uia_pattern\n', 'custom+a\nb',
              'K', 'KEY', 'ſ', 'viſion_precise', 'K+fallback', 'İıſK']
    for alias in aliases:
        values.extend((alias.upper(), alias.replace('i', 'İ'), alias.replace('i', 'ı'), alias.replace('i', 'i\u0307')))
    return [dict(operation='strategy-score', args=dict(app_type='fixture', route_order=[value, 'uia_pattern', 'ocr'],
                 persisted_strategy=dict(strategy=value), labels=['I', 'i', 'İ', 'ı', 'é', 'e\u0301'])) for value in values]


class StrategyCultureAliasSourceTests(unittest.TestCase):
    def test_unicode_alias_corpus(self):
        cases = alias_cases()
        self.assertGreaterEqual(len(cases), 35)
        routes = [c['args']['route_order'][0] for c in cases]
        self.assertTrue(any('İ' in route for route in routes))
        self.assertTrue(any('ı' in route for route in routes))
        self.assertTrue(any('i\u0307' in route for route in routes))


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell 5.1 regex alias characterization')
class StrategyCultureAliasWindowsTests(unittest.TestCase):
    maxDiff = None

    def test_explicit_and_ambient_culture_against_complete_original_score(self):
        project = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyStrategy.CultureTests'
        with tempfile.TemporaryDirectory(prefix='CUCP strategy alias culture ') as temp:
            build = subprocess.run([shutil.which('dotnet'), 'build', str(project), '-c', 'Release', '--output', temp], capture_output=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout.decode('utf-8', errors='replace') + build.stderr.decode('utf-8', errors='replace'))
            host = Path(temp) / 'PcuCp.LegacyStrategy.CultureTests.dll'
            for culture, explicit in itertools.product(('en-US', 'ko-KR', 'tr-TR', ''), (False, True)):
                with self.subTest(culture=culture, explicit=explicit):
                    # Existing helper invokes the pinned PS functions unchanged.
                    # Explicit-culture candidates run in en-US, proving that the
                    # argument governs normalization as well as NLS ordering.
                    strategy.LegacyStrategyParityTests.compare_cases(self, copy.deepcopy(alias_cases()), culture=culture,
                                                                     fixture_host=host, explicit_culture=explicit)


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell 5.1 quote/casing characterization')
class SharedQuoteAndCasingWindowsTests(unittest.TestCase):
    maxDiff = None

    def test_direct_quote_and_nls_casing_against_framework(self):
        values = ['', 'plain', "O'Brien", 'a b', '$name; data', '가😀', 'I', 'i', 'İ', 'ı', 'ſ', 'K',
                  'É', 'e\u0301', 'Σ', 'σ', 'ς', 'ΟΣ', 'İıſK', 'i\u0307', 'K\u0301', '𐐀𐐨', '𞤀𞤢',
                  'appİ', 'Chrome_WidgetWİn_1', 'C:\\Users\\Fixture', 'literal\n', 'a\nb']
        project = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyAppProfile.ContractTests'
        with tempfile.TemporaryDirectory(prefix='CUCP quote casing ') as temp:
            root = Path(temp)
            source = root/'original.ps1'
            source.write_bytes(subprocess.check_output(['git','show',f'{strategy.BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            runner = root/'capture.ps1'
            runner.write_text(r'''
param([string]$Source,[string]$InputPath,[string]$CultureName)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$culture=[Globalization.CultureInfo]::GetCultureInfo($(if($CultureName -eq '__invariant__'){''}else{$CultureName}))
[Threading.Thread]::CurrentThread.CurrentCulture=$culture
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
foreach($name in @('_TaskPlan-QuoteToken','_TaskPlan-StepString')){
 $fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($fn.Count -ne 1){throw "Expected one original function $name"}
 . ([scriptblock]::Create($fn[0].Extent.Text))
}
$output=New-Object Collections.ArrayList
foreach($value in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $chars=foreach($c in $value.ToCharArray()){$culture.TextInfo.ToLower([char]$c)}
 [void]$output.Add(@{quote=@{value=(_TaskPlan-QuoteToken -Value $value);step=(_TaskPlan-StepString -Command @('macro',$value))};casing=@{invariant=$value.ToLowerInvariant();current=$culture.TextInfo.ToLower([string]$value);characters=(-join $chars)}})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($output) -Depth 8 -Compress))
''',encoding='utf-8-sig')
            inputs=root/'values.json';inputs.write_text(json.dumps(values,ensure_ascii=True),encoding='utf-8-sig')
            build=subprocess.run([shutil.which('dotnet'),'build',str(project),'-c','Release','--output',str(root/'build')],capture_output=True,timeout=90)
            self.assertEqual(build.returncode,0,build.stdout.decode('utf-8',errors='replace')+build.stderr.decode('utf-8',errors='replace'))
            host=root/'build/PcuCp.LegacyAppProfile.ContractTests.dll'
            for culture in ('en-US','ko-KR','tr-TR',''):
                with self.subTest(culture=culture):
                    original=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(runner),'-Source',str(source),'-InputPath',str(inputs),'-CultureName',culture or '__invariant__'],capture_output=True,timeout=30)
                    self.assertEqual(original.returncode,0,original.stderr.decode('utf-8',errors='replace'))
                    expected=json.loads(original.stdout.decode('utf-8-sig'))
                    self.assertEqual(len(expected),len(values))
                    for operation in ('quote','casing'):
                        payload=[dict(value=value,culture=culture) for value in values]
                        current=subprocess.run([shutil.which('dotnet'),str(host),f'--{operation}-fixtures'],input=json.dumps(payload,ensure_ascii=True).encode(),capture_output=True,timeout=30)
                        self.assertEqual(current.returncode,0,current.stderr.decode('utf-8',errors='replace'))
                        results=json.loads(current.stdout)
                        self.assertEqual(len(results),len(values))
                        for value,before,after in zip(values,expected,results):
                            with self.subTest(value=value,operation=operation):
                                self.assertEqual(after,before[operation])
