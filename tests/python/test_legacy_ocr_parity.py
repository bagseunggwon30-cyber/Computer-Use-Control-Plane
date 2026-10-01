"""Differential migration evidence against original functions in Git history.

No legacy desktop entry point is executed. Tests extract only five pure OCR
functions from the pinned published baseline, in a temporary directory.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = '9ffa354b9904235835a7bc6eb78ed8d3d76317c8'


def word(text, x=0, y=-3, w=21, h=11):
    return {'text': text, 'x': x, 'y': y, 'w': w, 'h': h, 'cx': x+round(w/2), 'cy': y+round(h/2)}


def body(texts):
    words = [word(text, x=i*27) for i, text in enumerate(texts)]
    return {'lines': [{**word(' '.join(texts), w=(len(words)-1)*27+21), 'words': words}]}


def cases():
    values = []
    for query, texts in [
        ('Save', ['Save', 'As', 'Document']), ('Save As', ['Save', 'As', 'Document']),
        ('저장', ['다른', '이름으로', '저장']), ('다른 이름으로', ['다른', '이름으로', '저장']),
        ('설정', ['설졍', '설정']), ('ＳＡＶＥ', ['Save', 'save']),
        ('I', ['İ', 'ı', 'I', 'i']), ('ΟΣ', ['ος', 'οσ', 'ΟΣ']),
        ('Straße', ['STRASSE', 'Straße']), ('가', ['가', '가']),
        ('𐐀', ['𐐀', '𐐁']), ('ＡＢ １２', ['AB', '12']),
        ('!!!', ['!', '?']), ('', ['Save']),
    ]:
        for mode in ('exact', 'prefix', 'contains', 'fuzzy'):
            values.append({'schema': 'cucp.legacy-ocr-match/v1', 'body': body(texts), 'needle': query, 'mode': mode})
    return values


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_NATIVE_TEST_HOST'), 'requires built Windows native host')
class LegacyOcrParityTests(unittest.TestCase):
    def test_original_dotnet_powershell_functions_match_native_kernel(self):
        powershell = shutil.which('powershell.exe')
        self.assertIsNotNone(powershell, 'Windows PowerShell 5.1 is needed to qualify legacy compatibility')
        host = Path(os.environ['CUCP_NATIVE_TEST_HOST'])
        native = [str(host)] if host.suffix.lower() == '.exe' else [shutil.which('dotnet'), str(host)]
        original = subprocess.check_output(['git', 'show', f'{BASELINE}:scripts/cucp-native-helper.ps1'], cwd=ROOT)
        requests = cases()
        with tempfile.TemporaryDirectory(prefix='CUCP OCR 한글 ') as tmp:
            root = Path(tmp)
            source, runner, inputs = root/'original.ps1', root/'pure.ps1', root/'cases.json'
            source.write_bytes(original)
            inputs.write_text(json.dumps(requests, ensure_ascii=False), encoding='utf-8-sig')
            runner.write_text(r'''
param([string]$SourcePath, [string]$InputPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($SourcePath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Cannot parse pinned legacy source' }
foreach ($name in @('_Normalize-OcrText','_Levenshtein-Distance','_Similarity-Percent','_Score-OcrText','_Match-OcrCandidates')) {
  $found = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
  if ($found.Count -ne 1) { throw "Expected exactly one original function: $name" }
  . ([scriptblock]::Create($found[0].Extent.Text))
}
$cases = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
$results = New-Object System.Collections.ArrayList
foreach ($case in $cases) {
  $matches = @(_Match-OcrCandidates -Body $case.body -Needle $case.needle -Mode $case.mode)
  [void]$results.Add([pscustomobject]@{ candidates=$matches; candidate_count=$matches.Count })
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            proc = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
                                   '-SourcePath', str(source), '-InputPath', str(inputs)], capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8', errors='replace'))
            expected = json.loads(proc.stdout.decode('utf-8-sig'))
            self.assertEqual(len(expected), len(requests))
            for request, before in zip(requests, expected):
                with self.subTest(needle=request['needle'], mode=request['mode']):
                    after = subprocess.run([*native, 'legacy-ocr-match'], input=json.dumps(request, ensure_ascii=False).encode(),
                                           capture_output=True, timeout=15)
                    self.assertEqual(after.returncode, 0, after.stdout.decode('utf-8', errors='replace'))
                    response = json.loads(after.stdout)
                    self.assertEqual(response['status'], 'ok', response)
                    self.assertEqual(response['data']['candidates'], before['candidates'])
                    self.assertEqual(response['data']['candidate_count'], before['candidate_count'])
            # The retained PS entry point must actually route through the new
            # stdin bridge, preserving arrays/UTF-8 and native output shape.
            bridge_runner = root/'bridge.ps1'
            bridge_runner.write_text(runner.read_text(encoding='utf-8-sig').replace(
                "@('_Normalize-OcrText','_Levenshtein-Distance','_Similarity-Percent','_Score-OcrText','_Match-OcrCandidates')",
                "@('_Match-OcrCandidates')"), encoding='utf-8-sig')
            bridged = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(bridge_runner),
                '-SourcePath', str(ROOT/'scripts/cucp-native-helper.ps1'), '-InputPath', str(inputs)],
                env={**os.environ, 'CUCP_NATIVE_HOST': str(host)}, capture_output=True, timeout=90)
            self.assertEqual(bridged.returncode, 0, bridged.stderr.decode('utf-8', errors='replace'))
            self.assertEqual(json.loads(bridged.stdout.decode('utf-8-sig')), expected)


    def test_kernel_rejects_malformed_and_oversized_stdin(self):
        host = Path(os.environ['CUCP_NATIVE_TEST_HOST'])
        native = [str(host)] if host.suffix.lower() == '.exe' else [shutil.which('dotnet'), str(host)]
        for raw in (b'{}', b'{', b'x'*(1024*1024+1)):
            result = subprocess.run([*native, 'legacy-ocr-match'], input=raw, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['status'], 'error')
