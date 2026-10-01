"""Differential tests against pinned PS safety functions; fixtures, no live actions."""
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


def safety_cases():
    cases = []
    for text in ('', None, 'ordinary text', 'password', 'PASSWORD', 'api-key API_key api key',
                 '비밀번호 인증번호 일회용 토큰', '결제 카드 계좌 입금', 'delete account 영구 삭제',
                 'submit 공유 업로드', '여권 개인정보', 'firewall 관리자 권한', 'settings 환경설정',
                 'checkout password delete upload', 'unforced', 'İD CARD', 'admin', 'A\x00password'):
        cases.append({'operation': 'safety-classify', 'args': {'text': text, 'macro': ''}})
    for macro in ('registry', 'REGISTRY', 'process', 'PROCESS', 'app-close', 'APP-CLOSE', 'notify', 'NoTiFy', None):
        for text in ('', '--force', 'send token'):
            cases.append({'operation': 'safety-classify', 'args': {'text': text, 'macro': macro}})
    for text in ('a' * 180, 'a' * 181, '한' * 181, 'a' * 178 + '😀x', 'a' * 179 + '😀x'):
        cases.append({'operation': 'safety-classify', 'args': {'text': text, 'macro': 'type'}})
    for value, maximum in ((None, 180), ('', 0), ('abc', 0), ('abc', 3), ('abcdef', 3), ('😀x', 2), ('😀x', 1)):
        cases.append({'operation': 'safety-truncate', 'args': {'value': value, 'max': maximum}})
    return cases


class SafetyFixtureTests(unittest.TestCase):
    def test_differential_fixture_covers_confirmation_and_utf16_edges(self):
        cases = safety_cases()
        self.assertGreaterEqual(len(cases), 50)
        self.assertTrue(any(c['args'].get('macro') == 'REGISTRY' for c in cases))
        self.assertTrue(any(c['args'].get('max') == 1 and c['args'].get('value') == '😀x' for c in cases))


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_NATIVE_TEST_HOST'), 'Requires Windows native compatibility dispatcher')
class LegacySafetyParityTests(unittest.TestCase):
    def native(self):
        host = Path(os.environ['CUCP_NATIVE_TEST_HOST'])
        return [str(host)] if host.suffix.lower() == '.exe' else [shutil.which('dotnet'), str(host)]

    def test_pinned_powershell_matches_safety_kernel(self):
        cases = safety_cases()
        original = subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT)
        with tempfile.TemporaryDirectory(prefix='CUCP safety 한글 ') as temp:
            root = Path(temp)
            source, inputs, runner = root / 'original.ps1', root / 'cases.json', root / 'runner.ps1'
            source.write_bytes(original)
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            runner.write_text(r'''
param([string]$SourcePath, [string]$InputPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source did not parse' }
foreach ($name in @('_Safety-Truncate','_Classify-SafetyFromText')) {
  $function=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($function.Count -ne 1) { throw "Expected one exact baseline function: $name" }
  . ([scriptblock]::Create($function[0].Extent.Text))
}
$results=New-Object Collections.ArrayList
foreach ($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  if ($case.operation -eq 'safety-classify') { $result=_Classify-SafetyFromText -Text $case.args.text -MacroName $case.args.macro }
  else { $result=@{value=(_Safety-Truncate -Value $case.args.value -Max $case.args.max)} }
  [void]$results.Add($result)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            baseline = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
                                       '-SourcePath', str(source), '-InputPath', str(inputs)], capture_output=True, timeout=30)
            self.assertEqual(baseline.returncode, 0, baseline.stderr.decode('utf-8', errors='replace'))
            expected = json.loads(baseline.stdout.decode('utf-8-sig'))
            self.assertEqual(len(expected), len(cases))
            for case, before in zip(cases, expected):
                with self.subTest(case=case):
                    body = {'schema': 'cucp.legacy-compat/v1', **case}
                    result = subprocess.run([*self.native(), 'legacy-compat'], input=json.dumps(body, ensure_ascii=True).encode(),
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                    after = json.loads(result.stdout.decode('utf-8-sig'))
                    self.assertEqual(after['status'], 'ok', after)
                    self.assertEqual(after['data'], before)

    def test_malformed_safety_input_does_not_return_low_risk(self):
        for args in ({'text': 1}, {'text': 'password', 'bypass': True}, {'macro': 'x' * 129}):
            request = {'schema': 'cucp.legacy-compat/v1', 'operation': 'safety-classify', 'args': args}
            result = subprocess.run([*self.native(), 'legacy-compat'], input=json.dumps(request).encode(), capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
