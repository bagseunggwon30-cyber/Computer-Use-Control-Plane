"""Generated-image differential; no screenshots, user files, or desktop actions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BASELINE_TREE = 'bf895d3120dd5e145f360cb1c41e1d79a061d048'
PROJECT = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyImages'
DRAFT = ROOT / 'tests/fixtures/legacy-file-images-adapter.ps1'


def adapter_source():
    override = os.environ.get('CUCP_LEGACY_IMAGES_ADAPTER_SOURCE')
    if override:
        source = Path(override)
        if not source.is_absolute():
            source = ROOT / source
    else:
        manifest = json.loads((ROOT / '.github/migration-adapters.json').read_text())
        source = ROOT / 'scripts/cucp-native-helper.ps1' if 'file-images' in manifest['test_adapters'] else DRAFT
    if not source.is_file():
        raise FileNotFoundError(f'Configured file-images adapter source is missing: {source}')
    return source


def image_cases():
    cases = []
    for fmt in ('png', 'bmp', 'jpg', 'gif', 'tiff'):
        for right in ('before', 'after'):
            cases.append(dict(before=f'before.{fmt}', after=f'{right}.{fmt}'))
    for extra in ({'threshold': 0}, {'threshold': -1}, {'threshold': 765}, {'threshold': 16},
                  {'x': 2, 'y': 1, 'width': 4, 'height': 3}, {'x': -2, 'y': -3},
                  {'x': 20}, {'y': 20}, {'width': -1, 'height': -1},
                  {'ignore': '0,0,8,6'}, {'ignore': '-2,-2,4,4;1,1,4,3;1,1,4,3'},
                  {'ignore': 'bad;1,2,3;;'}, {'ignore': '0x0,0,0x4,2'},
                  {'ignore': 'oops,0,1,1'}, {'ignore': '2147483648,0,1,1'},
                  {'ignore': ',,2,2'}, {'ignore': '1.5,0,1,1'}, {'ignore': '2.5,0,1,1'},
                  {'ignore': '-1.5,0,3,1'}, {'ignore': '1e0,0,1e0,1'},
                  {'ignore': '2147483647,0,2147483647,1'},
                  {'x': 2, 'ignore': '-2147483648,0,2147483647,1'},
                  {'ignore': '0,0,-1,2;99,99,4,4'}, {'x': 2, 'ignore': '0,0,4,6'}):
        cases.append(dict(before='before.png', after='after.png', **extra))
    for before, after in (('before.png', 'small.png'), ('before.png', 'alpha.png'),
                          ('before.png', 'corrupt.bin'), ('corrupt.bin', 'before.png'),
                          ('directory', 'before.png'), ('missing.png', 'before.png'),
                          ('before.png', 'missing.png'), ('', 'before.png')):
        cases.append(dict(before=before, after=after))
    for coordinate in ('  +1  ', '-1', '-0x1', '0X4', '1kb', 'NaN', 'Infinity',
                       '2147483646', '2147483647', '2147483648',
                       '-2147483647', '-2147483648', '-2147483649'):
        cases.append(dict(before='before.png', after='after.png', ignore=f'{coordinate},0,4,1'))
    return cases


class ImagesSourceTests(unittest.TestCase):
    def test_adapter_source_override_is_explicit_and_missing_source_fails(self):
        with tempfile.TemporaryDirectory(prefix='CUCP adapter selection ') as temp:
            source = Path(temp) / 'owned.ps1'
            source.write_text('# owned source')
            with mock.patch.dict(os.environ, {'CUCP_LEGACY_IMAGES_ADAPTER_SOURCE': str(source)}):
                self.assertEqual(adapter_source(), source)
                source.unlink()
                with self.assertRaises(FileNotFoundError):
                    adapter_source()

    def test_codec_and_disposal_boundary_remains_framework_drawing(self):
        source = (PROJECT / 'ScreenshotDiff.cs').read_text()
        for required in ('Image.FromFile', 'LockBits', 'Format32bppArgb', 'Marshal.Copy', 'UnlockBits', 'bmp1.Dispose()', 'bmp2.Dispose()'):
            self.assertIn(required, source)
        self.assertNotIn('CopyFromScreen', source)
        self.assertNotIn('System.Management.Automation', source)
        self.assertGreaterEqual(len(image_cases()), 35)

    def test_publisher_uses_argv_only_separate_assembly(self):
        spec = importlib.util.spec_from_file_location('publish_images', ROOT / 'pcucp-next/packaging/publish_legacy_images.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        command = module.build_command('C:/SDK space/dotnet.exe', '한글 image output')
        self.assertEqual(command[0], 'C:/SDK space/dotnet.exe')
        self.assertIn('PcuCp.LegacyImages.csproj', command[2])
        self.assertEqual(module.ASSEMBLY, 'PcuCp.LegacyImages.dll')


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_LEGACY_IMAGES_TEST_DLL'), 'Requires compiled net48 images and Windows PowerShell 5.1')
class ImagesWindowsParityTests(unittest.TestCase):
    maxDiff = None

    def test_generated_images_and_errors_match_whole_pinned_result(self):
        self._run_matrix(False)

    def test_actual_adapter_and_original_emit_match_pinned_boundary(self):
        self._run_matrix(True)

    def _run_matrix(self, boundary):
        with tempfile.TemporaryDirectory(prefix='CUCP images 한글 ') as temp:
            folder = Path(temp)
            source = folder / 'original.ps1'
            source.write_bytes(subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp-native-helper.ps1'], cwd=ROOT))
            runner = folder / 'runner.ps1'
            runner.write_text(r'''
param([string]$Mode,[string]$Root,[string]$Source,[string]$Dll,[string]$CasePath,[string]$Adapter,[string]$NativeSource,[switch]$Boundary)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Drawing
if ($Mode -eq 'generate') {
  foreach ($format in @('Png','Bmp','Jpeg','Gif','Tiff')) {
    $ext=@{Png='png';Bmp='bmp';Jpeg='jpg';Gif='gif';Tiff='tiff'}[$format]
    foreach ($name in @('before','after')) {
      $bmp=New-Object Drawing.Bitmap 8,6
      try {
        for ($y=0;$y -lt 6;$y++) { for ($x=0;$x -lt 8;$x++) {
          $c=[Drawing.Color]::FromArgb(255,($x*20),($y*30),40)
          if ($name -eq 'after' -and $x -eq 3 -and $y -eq 2) { $c=[Drawing.Color]::FromArgb(255,255,0,0) }
          $bmp.SetPixel($x,$y,$c)
        }}
        $bmp.Save((Join-Path $Root "$name.$ext"),[Drawing.Imaging.ImageFormat]::$format)
      } finally { $bmp.Dispose() }
    }
  }
  $small=New-Object Drawing.Bitmap 3,2
  try { $small.Save((Join-Path $Root 'small.png'),[Drawing.Imaging.ImageFormat]::Png) } finally { $small.Dispose() }
  $alpha=[Drawing.Bitmap]::FromFile((Join-Path $Root 'before.png'))
  try { $alpha.SetPixel(3,2,[Drawing.Color]::FromArgb(128,60,60,40));$alpha.Save((Join-Path $Root 'alpha.png'),[Drawing.Imaging.ImageFormat]::Png) } finally { $alpha.Dispose() }
  [IO.File]::WriteAllText((Join-Path $Root 'corrupt.bin'),'not an image')
  [void][IO.Directory]::CreateDirectory((Join-Path $Root 'directory'))
  exit 0
}
$c=Get-Content -LiteralPath $CasePath -Raw -Encoding UTF8 | ConvertFrom-Json
$DiffBefore=if ($c.before) { Join-Path $Root $c.before } else { '' }
$DiffAfter=if ($c.after) { Join-Path $Root $c.after } else { '' }
$ScreenshotX=[int]$c.x;$ScreenshotY=[int]$c.y;$ScreenshotW=[int]$c.width;$ScreenshotH=[int]$c.height
$DiffThreshold=16;if ($null -ne $c.threshold) { $DiffThreshold=[int]$c.threshold }
$DiffIgnoreRegions=[string]$c.ignore
if ($Mode -eq 'candidate') {
  [void][Reflection.Assembly]::LoadFrom($Dll)
  $r=[PcuCp.LegacyImages.ScreenshotDiff]::Compare($DiffBefore,$DiffAfter,$ScreenshotX,$ScreenshotY,$ScreenshotW,$ScreenshotH,$DiffThreshold,$DiffIgnoreRegions)
  [Console]::Out.WriteLine((ConvertTo-Json -InputObject $r.Data -Depth 16 -Compress))
  exit $r.ExitCode
}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Action-ScreenshotDiff'},$true))
if ($fn.Count -ne 1) { throw 'Expected exactly one pinned image function' }
. ([scriptblock]::Create($fn[0].Extent.Text))
if ($Mode -eq 'adapter') {
  $env:CUCP_LEGACY_IMAGES_DLL=$Dll
  $draft=[Management.Automation.Language.Parser]::ParseFile($Adapter,[ref]$tokens,[ref]$errors)
  if ($errors.Count) { throw 'Image adapter parse failed' }
  foreach($name in @('_Require-LegacyImages','_Action-ScreenshotDiff')) {
    $entry=@($draft.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
    if($entry.Count -ne 1){throw "Expected exactly one adapter $name"}
    . ([scriptblock]::Create($entry[0].Extent.Text))
  }
}
if ($Boundary) {
  $emitterAst=$ast
  if ($Mode -eq 'adapter') {
    $emitterAst=[Management.Automation.Language.Parser]::ParseFile($NativeSource,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw 'Current native emitter source did not parse' }
  }
  $emitter=@($emitterAst.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Emit'},$true))
  if($emitter.Count -ne 1){throw 'Expected exactly one original emitter'}
  . ([scriptblock]::Create($emitter[0].Extent.Text))
  $Script:_StartedAt=[datetime]'2020-01-01T00:00:00Z'
  function Get-Date { return [datetime]'2020-01-01T00:00:00.125Z' }
  $Action='screenshot-diff'
} else {
  function _Emit { param($Payload,[int]$ExitCode=0) [Console]::Out.WriteLine((ConvertTo-Json -InputObject $Payload -Depth 16 -Compress));exit $ExitCode }
}
_Action-ScreenshotDiff
''', encoding='utf-8-sig')
            command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner), '-Root', str(folder), '-Source', str(source), '-Dll', os.environ['CUCP_LEGACY_IMAGES_TEST_DLL'], '-Adapter', str(adapter_source()), '-NativeSource', str(ROOT / 'scripts/cucp-native-helper.ps1')]
            if boundary:
                command.append('-Boundary')
            generation = subprocess.run([*command, '-Mode', 'generate'], capture_output=True, timeout=30)
            self.assertEqual(generation.returncode, 0, generation.stderr.decode('utf-8', errors='replace'))
            for case in image_cases():
                with self.subTest(case=case):
                    path = folder / 'case.json'
                    path.write_text(json.dumps(case, ensure_ascii=True), encoding='utf-8-sig')
                    before = subprocess.run([*command, '-Mode', 'baseline', '-CasePath', str(path)], capture_output=True, timeout=15)
                    after = subprocess.run([*command, '-Mode', 'adapter' if boundary else 'candidate', '-CasePath', str(path)], capture_output=True, timeout=15)
                    self.assertEqual(after.returncode, before.returncode, (before.stderr, after.stderr))
                    actual = json.loads(after.stdout.decode('utf-8-sig'))
                    expected = json.loads(before.stdout.decode('utf-8-sig'))
                    self.assertEqual(actual, expected)
                    if boundary:
                        self.assertEqual(actual['elapsed_ms'], 125)
                        self.assertEqual(actual['action'], 'screenshot-diff')
                        if actual['status'] == 'ok':
                            self.assertEqual(after.stdout, before.stdout, 'Ordered public Console output changed')
