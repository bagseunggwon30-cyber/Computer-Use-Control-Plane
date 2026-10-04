"""Owned-file OCR qualification. No screenshots, UI, input, or model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_legacy_images import ROOT, BASELINE_TREE, PROJECT, adapter_source
from legacy_historical_native import helper as historical_native_helper

FUNCTIONS = ['_Ensure-OCR', '_Wait-AsyncOp', '_Load-SoftwareBitmapFromFile', '_Convert-OcrResult', '_Action-OcrImage']


def word(text, x=1, y=2, w=3, h=4):
    return dict(Text=text, BoundingRect=dict(X=x, Y=y, Width=w, Height=h))


def conversion_cases():
    cases = [dict(result=None), dict(result=dict(Text='', Lines=[])),
             dict(result=dict(Text='retain\r\nsource\n', Lines=[dict(Text='omit', Words=[])]))]
    for offsets in [(0, 0), (10, -20), (-100, -100), (2147483647, 0), (-2147483648, 0)]:
        cases.append(dict(result=dict(Text='한글 😀 source', Lines=[dict(Text='Ａ B', Words=[word('Ａ', 1.5, 2.5, 3, 5), word('B', 9.5, 8.5, 2.5, 1.5)])]), x=offsets[0], y=offsets[1]))
    cases.extend([dict(result=dict(Text='many\nlines', Lines=[dict(Text='empty', Words=[]), dict(Text='one', Words=[word('one')]), dict(Text='two three', Words=[word('two', -20, -10, 3, 3), word('three', -5, -6, 2, 2)])])),
                  dict(result=dict(Text=None, Lines=[dict(Text=None, Words=[word(None, 0, 0, 0, 0)])])),
                  dict(result=dict(Text='negative half', Lines=[dict(Text='negative half', Words=[word('a', -1.5, -2.5, 1, 1), word('b', -3.5, -4.5, 7, 9)])]))])
    return cases


RUNNER = r'''
param([string]$Mode,[string]$Operation,[string]$Source,[string]$Adapter,[string]$NativeSource,[string]$Dll,[string]$Root,[string]$CasePath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
function Load-Functions($Path,$Names) {
  $tokens=$null;$errors=$null
  $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
  if($errors.Count){throw "Source did not parse: $Path"}
  foreach($name in $Names){
    $functions=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
    if($functions.Count -ne 1){throw "Expected exactly one function $name"}
    Set-Item -Path "Function:script:$name" -Value ([scriptblock]::Create($functions[0].Body.Extent.Text.Substring(1,$functions[0].Body.Extent.Text.Length-2)))
  }
}
function Convert-Capture($Object) {
  if($null -eq $Object){return $null}
  if($Object -is [array]) { $items=New-Object Collections.ArrayList;foreach($item in $Object){[void]$items.Add((Convert-Capture $item))};return ,($items.ToArray()) }
  if($Object -is [Management.Automation.PSCustomObject]) { $result=@{};foreach($property in $Object.PSObject.Properties){$result[$property.Name]=Convert-Capture $property.Value};return $result }
  return $Object
}
if($Operation -eq 'generate'){
  Add-Type -AssemblyName System.Drawing
  foreach($format in @('Png','Bmp','Jpeg','Gif','Tiff')){
    $extension=@{Png='png';Bmp='bmp';Jpeg='jpg';Gif='gif';Tiff='tiff'}[$format]
    foreach($name in @('text','blank')){
      $bitmap=New-Object Drawing.Bitmap 640,160
      $graphics=[Drawing.Graphics]::FromImage($bitmap)
      $font=New-Object Drawing.Font ([Drawing.FontFamily]::GenericSansSerif),32
      try {
        $graphics.Clear([Drawing.Color]::White)
        if($name -eq 'text'){$graphics.DrawString('OWNED TEST 123',$font,[Drawing.Brushes]::Black,20,40)}
        $bitmap.Save((Join-Path $Root "$name.$extension"),[Drawing.Imaging.ImageFormat]::$format)
      }finally{$font.Dispose();$graphics.Dispose();$bitmap.Dispose()}
    }
  }
  Copy-Item -LiteralPath (Join-Path $Root 'text.png') -Destination (Join-Path $Root '한글 image.png')
  [IO.File]::WriteAllText((Join-Path $Root 'corrupt.bin'),'owned invalid image')
  [void][IO.Directory]::CreateDirectory((Join-Path $Root 'directory'))
  exit 0
}
$names=@('_Ensure-OCR','_Wait-AsyncOp','_Load-SoftwareBitmapFromFile','_Convert-OcrResult','_Action-OcrImage')
if($Mode -eq 'baseline'){Load-Functions $Source $names}else{$env:CUCP_LEGACY_IMAGES_DLL=$Dll;Load-Functions $Adapter (@('_Require-LegacyImages')+$names)}
if($Mode -eq 'baseline'){Load-Functions $Source @('_Emit')}else{Load-Functions $NativeSource @('_Emit')}
$Script:_StartedAt=[datetime]'2020-01-01T00:00:00Z'
function Get-Date { return [datetime]'2020-01-01T00:00:00.125Z' }
$Action='ocr-image';$Script:_OCRLoaded=$false;$Script:_OCREngine=$null;$Script:_OCRError=$null
$c=Get-Content -LiteralPath $CasePath -Raw -Encoding UTF8|ConvertFrom-Json
$OcrLanguage=[string]$c.language
$OcrPath=if($c.path){if($c.relative){[string]$c.path}else{Join-Path $Root $c.path}}else{''}
try {
  if($Operation -eq 'convert'){
    $result=_Convert-OcrResult (Convert-Capture $c.result) ([int]$c.x) ([int]$c.y)
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Depth 32 -Compress));exit 0
  }
  if($Operation -eq 'engine'){
    $available=_Ensure-OCR;$engine=$Script:_OCREngine;$initialOcrError=$Script:_OCRError
    $OcrLanguage='not_a_language';$again=_Ensure-OCR
    $language=$null;$engineType=$null
    if($engine){$language=$engine.RecognizerLanguage.LanguageTag;$engineType=$engine.GetType().FullName}
    $languages=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages|ForEach-Object{$_.LanguageTag})
    $data=[ordered]@{available=$available;loaded=$Script:_OCRLoaded;error=$initialOcrError;engine_type=$engineType;language=$language;installed_languages=$languages;cached_available=$again;same_engine=[object]::ReferenceEquals($engine,$Script:_OCREngine);same_error=($initialOcrError -ceq $Script:_OCRError)}
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $data -Depth 16 -Compress));exit 0
  }
  if($Operation -eq 'wait'){
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $completion=New-Object 'System.Threading.Tasks.TaskCompletionSource[int]'
    if($c.state -eq 'error'){$completion.SetException((New-Object InvalidOperationException 'owned async failure'))}
    elseif($c.state -eq 'cancelled'){$completion.SetCanceled()}else{$completion.SetResult(42)}
    $asOperation=[WindowsRuntimeSystemExtensions].GetMethods()|Where-Object{$_.Name -eq 'AsAsyncOperation' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1}|Select-Object -First 1
    $asyncOperation=$asOperation.MakeGenericMethod([int]).Invoke($null,@($completion.Task))
    $result=_Wait-AsyncOp $asyncOperation ([int])
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject ([ordered]@{value=$result;type=$result.GetType().FullName}) -Compress));exit 0
  }
  if($Operation -eq 'load'){
    [void](_Ensure-OCR)
    $bitmap=_Load-SoftwareBitmapFromFile $OcrPath
    try {
      $data=[ordered]@{type=$bitmap.GetType().FullName;width=$bitmap.PixelWidth;height=$bitmap.PixelHeight;format=[string]$bitmap.BitmapPixelFormat;alpha=[string]$bitmap.BitmapAlphaMode}
      if($c.recognize){
        $data['recognition_available']=($null -ne $Script:_OCREngine)
        $data['ocr_error']=$Script:_OCRError
        if($Script:_OCREngine){
          $recognized=_Wait-AsyncOp ($Script:_OCREngine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
          $data['result_type']=$recognized.GetType().FullName
          $data['converted']=_Convert-OcrResult $recognized
        }
      }
      [Console]::Out.WriteLine((ConvertTo-Json -InputObject $data -Depth 16 -Compress));exit 0
    }finally{if($bitmap -is [IDisposable]){$bitmap.Dispose()}}
  }
  if($Operation -eq 'action'){_Action-OcrImage}
  throw "Unknown fixture operation: $Operation"
}catch{
  [Console]::Out.WriteLine((ConvertTo-Json -InputObject ([ordered]@{status='error';detail=$_.Exception.Message}) -Compress));exit 1
}
'''


class FileOcrSourceTests(unittest.TestCase):
    def test_candidate_is_file_only_and_real_adapter_is_required(self):
        source = (PROJECT / 'FileOcr.cs').read_text()
        for denied in ('System.Management.Automation', 'Process.Start', 'CopyFromScreen', 'SendInput', 'UIAutomation', 'HttpClient'):
            self.assertNotIn(denied, source)
        self.assertIn('System.Runtime.WindowsRuntime', source)
        self.assertIn('GetSoftwareBitmapAsync', source)
        self.assertTrue(adapter_source().is_file())
        adapter = adapter_source().read_text(encoding='utf-8-sig')
        for name in FUNCTIONS + ['_Action-ScreenshotDiff']:
            self.assertIn('function ' + name + ' {', adapter)
        self.assertGreaterEqual(len(conversion_cases()), 10)


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_LEGACY_IMAGES_TEST_DLL'), 'Requires compiled net48 images and Windows PowerShell 5.1')
class FileOcrWindowsParityTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='CUCP file OCR 한글 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'original.ps1'
        source.write_bytes(subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp-native-helper.ps1'], cwd=ROOT))
        self.runner = self.root / 'runner.ps1'
        self.runner.write_text(RUNNER, encoding='utf-8-sig')
        self.command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(self.runner),
                        '-Root', str(self.root), '-Source', str(source), '-Adapter', str(adapter_source()), '-NativeSource', str(historical_native_helper()), '-Dll', os.environ['CUCP_LEGACY_IMAGES_TEST_DLL']]

    def compare(self, operation, case):
        path = self.root / 'case.json'
        path.write_text(json.dumps(case, ensure_ascii=True), encoding='utf-8-sig')
        results = [subprocess.run([*self.command, '-Mode', mode, '-Operation', operation, '-CasePath', str(path)],
                                  cwd=self.root, capture_output=True, timeout=45) for mode in ('baseline', 'adapter')]
        before, after = results
        self.assertTrue(before.stdout.strip(), before.stderr.decode('utf-8', errors='replace'))
        self.assertTrue(after.stdout.strip(), after.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(after.returncode, before.returncode, (before.stdout, after.stdout, before.stderr, after.stderr))
        expected, actual = [json.loads(result.stdout.decode('utf-8-sig')) for result in results]
        self.assertEqual(actual, expected)
        if actual.get('status') != 'error':
            self.assertEqual(after.stdout, before.stdout, 'Ordered helper/public Console output changed')
        return actual

    def generate(self):
        result = subprocess.run([*self.command, '-Operation', 'generate'], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_captured_conversion_matches_full_ordered_objects(self):
        for case in conversion_cases():
            with self.subTest(case=case):
                self.compare('convert', case)

    def test_actual_wait_helper_matches_success_failure_and_cancellation(self):
        for state in ('success', 'error', 'cancelled'):
            with self.subTest(state=state):
                result = self.compare('wait', dict(state=state))
                if state == 'success':
                    self.assertEqual(result, dict(value=42, type='System.Int32'))
                else:
                    self.assertEqual(result['status'], 'error')

    def test_actual_engine_selection_projection_and_cached_state(self):
        for language in ('', 'en-US', 'ko-KR', 'zz-ZZ', 'not_a_language', ' '):
            with self.subTest(language=language):
                result = self.compare('engine', dict(language=language))
                self.assertIn('loaded', result, result)
                self.assertTrue(result['loaded'] and result['same_engine'] and result['same_error'])
                self.assertEqual(result['available'], result['cached_available'])
                print('Owned-file OCR language availability: ' + json.dumps(result, ensure_ascii=True))
                if not result['available']:
                    self.assertIsNotNone(result['error'], 'Unavailable OS OCR must be reported explicitly')

    def test_generated_file_decoders_and_full_action_envelopes(self):
        self.generate()
        cases = [dict(path=f'{name}.{ext}') for ext in ('png', 'bmp', 'jpg', 'gif', 'tiff') for name in ('text', 'blank')]
        cases += [dict(path='한글 image.png'), dict(path='corrupt.bin'), dict(path='directory'),
                  dict(path='missing.png'), dict(path=''), dict(path='text.png', relative=True)]
        for case in cases:
            with self.subTest(helper='action', case=case):
                result = self.compare('action', case)
                self.assertEqual(result['action'], 'ocr-image')
                self.assertEqual(result['elapsed_ms'], 125)
                print('Owned-file OCR action evidence: ' + json.dumps(dict(case=case, status=result.get('status'), reason=result.get('reason'), engine_language=result.get('engine_language'), line_count=result.get('line_count')), ensure_ascii=True))
            if case['path']:
                with self.subTest(helper='load', case=case):
                    self.compare('load', case)
        with self.subTest(helper='recognize-return-object'):
            self.compare('load', dict(path='text.png', recognize=True))
        for language in ('en-US', 'ko-KR', 'zz-ZZ', 'not_a_language', ' '):
            with self.subTest(language=language):
                self.compare('action', dict(path='text.png', language=language))
