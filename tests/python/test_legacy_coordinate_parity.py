"""Pinned coordinate-math differential; acquisition is replaced by fixed fixtures."""
import copy
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
DESKTOP = {'x': -1920, 'y': -200, 'width': 3840, 'height': 1280, 'right': 1920, 'bottom': 1080, 'monitor_count': 2}


def coordinate_cases():
    cases = []
    rectangles = [(-100, 0, 400, 300), (-2000, -250, 400, 300), (1800, 900, 400, 300), (2500, 0, 100, 100), (0, 0, 0, 0)]
    for rect in rectangles:
        window = {'hwnd': 42, 'title': '한글 창', 'process': 'fixture', 'class': 'FixtureClass',
                  'rect': dict(zip(('x', 'y', 'width', 'height'), rect))}
        for mode in ('screen', 'window', 'visible-window', 'normalized', 'visible-normalized'):
            for x, y in ((0, 0), (.5, .5), (1, 1), (-.5, 2.5)):
                cases.append({'from': mode, 'x': x, 'y': y, 'selected_window': window, 'virtual_screen': DESKTOP})
    for norm in ((0, 1), (.333333333, .666666666), (1.2, -.2)):
        args = copy.deepcopy(cases[12])
        args.update(has_norm=True, norm_x=norm[0], norm_y=norm[1], x=99, y=88)
        cases.append(args)
    for mode in ('screen', 'SCREEN', 'bad-mode', ''):
        args = copy.deepcopy(cases[0]); args['from'] = mode; cases.append(args)
        args = {**args, 'selected_window': None, 'target_hwnd': 123, 'target_match': 'missing'}
        cases.append(args)
    for profile in (None, {}, {'coordinate_risk': 'low', 'warnings': ['not copied']},
                    {'coordinate_risk': 'HIGH', 'warnings': ['negative_origin', None, '', 'mixed_dpi'], 'elapsed_ms': 77}):
        args = copy.deepcopy(cases[0]); args['coordinate_profile'] = profile; cases.append(args)
    return cases


class CoordinateFixtureTests(unittest.TestCase):
    def test_fixtures_cover_edges_and_clip_modes(self):
        cases = coordinate_cases()
        self.assertGreaterEqual(len(cases), 100)
        self.assertTrue(any(c['from'] == 'normalized' and c['x'] == 1 for c in cases))
        self.assertTrue(any(c.get('selected_window') is None for c in cases))


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('CUCP_NATIVE_TEST_HOST'), 'Requires Windows compatibility dispatcher')
class LegacyCoordinateParityTests(unittest.TestCase):
    def test_all_deterministic_coordinate_fields_match_pinned_function(self):
        cases = coordinate_cases()
        original = subprocess.check_output(['git', 'show', f'{BASELINE_TREE}:scripts/cucp.ps1'], cwd=ROOT)
        with tempfile.TemporaryDirectory(prefix='CUCP coord 한글 ') as temp:
            root = Path(temp)
            source, inputs, runner = root / 'original.ps1', root / 'cases.json', root / 'runner.ps1'
            source.write_bytes(original)
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            runner.write_text(r'''
param([string]$SourcePath,[string]$InputPath,[switch]$Bridge)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
class CucpWin32 {
  static [object] $Fixture
  static [object] GetVirtualScreenInfo() { return [CucpWin32]::Fixture }
}
function _Ensure-Win32Loaded { return $true }
function _CoordMap-ResolveWindow { return $script:Fixture.selected_window }
function _Native-HitTestPoint { return $null }
function _CoordProfile-WindowFromPrecheck { return $null }
function _Build-CoordProfile { return $script:Fixture.coordinate_profile }
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pinned source did not parse' }
$names=@('_CoordMap-Rect','_CoordMap-ClipRect','_CoordMap-MakePoint','_Build-CoordMap')
if ($Bridge) { $names=@('_Invoke-LegacyCompatibility','_Build-CoordMap') }
foreach ($name in $names) {
  $functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
  if ($functions.Count -ne 1) { throw "Expected one exact baseline function: $name" }
  . ([scriptblock]::Create($functions[0].Extent.Text))
}
$results=New-Object Collections.ArrayList
foreach ($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
  $script:Fixture=$case
  $v=$case.virtual_screen
  [CucpWin32]::Fixture=[pscustomobject]@{X=$v.x;Y=$v.y;Width=$v.width;Height=$v.height;MonitorCount=$v.monitor_count}
  $result=_Build-CoordMap -From $case.from -X $case.x -Y $case.y -NormX $case.norm_x -NormY $case.norm_y -HasNorm ([bool]$case.has_norm) -TargetHwnd $case.target_hwnd -TargetMatch $case.target_match
  $result.PSObject.Properties.Remove('elapsed_ms')
  [void]$results.Add($result)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            baseline = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
                                       '-SourcePath', str(source), '-InputPath', str(inputs)], capture_output=True, timeout=30)
            self.assertEqual(baseline.returncode, 0, baseline.stderr.decode('utf-8', errors='replace'))
            expected = json.loads(baseline.stdout.decode('utf-8-sig'))
            self.assertEqual(len(expected), len(cases))
            host = Path(os.environ['CUCP_NATIVE_TEST_HOST'])
            native = [str(host)] if host.suffix.lower() == '.exe' else [shutil.which('dotnet'), str(host)]
            for args, before in zip(cases, expected):
                with self.subTest(mode=args['from'], args=args):
                    request = {'schema': 'cucp.legacy-compat/v1', 'operation': 'coord-map', 'args': args}
                    result = subprocess.run([*native, 'legacy-compat'], input=json.dumps(request, ensure_ascii=True).encode(), capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                    body = json.loads(result.stdout.decode('utf-8-sig'))
                    self.assertEqual(body['status'], 'ok', body)
                    after = body['data']
                    after.pop('elapsed_ms', None)
                    self.assertEqual(after, before)

            # Preserve the qualified PS/C# math facade as an immutable oracle.
            # Current Python acquisition/reporting is exercised separately by
            # test_coordinate_production, not substituted for this fixture.
            previous = root / 'previous-math-facade.ps1'
            previous.write_bytes(subprocess.check_output(['git','show',
                'b1a5641f129c039afdc8cbe969c3d365e5539740:scripts/cucp.ps1'],cwd=ROOT))
            bridge = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(runner),
                '-SourcePath', str(previous), '-InputPath', str(inputs), '-Bridge'],
                env={**os.environ, 'CUCP_NATIVE_HOST': str(host)}, capture_output=True, timeout=120)
            self.assertEqual(bridge.returncode, 0, bridge.stderr.decode('utf-8', errors='replace'))
            self.assertEqual(json.loads(bridge.stdout.decode('utf-8-sig')), expected)
