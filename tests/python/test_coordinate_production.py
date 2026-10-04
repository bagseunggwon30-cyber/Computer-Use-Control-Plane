"""Pinned PS5/PS7 coordinate acquisition fixtures and real readonly production paths."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_coordinate_runtime import CoordinateRuntime
from pcucp_cli.legacy_coordinates import Coordinates
from pcucp_cli.legacy_host_protocol import LegacyHostError
from pcucp_cli.legacy_native_kernel import compatibility

BASE = 'b1a5641f129c039afdc8cbe969c3d365e5539740'
HANDLERS = ('_Native-HitTestPoint', '_Build-CoordProfile', '_Build-CoordMap',
            'Invoke-MacroCoordProfile', 'Invoke-MacroCoordMap', 'Invoke-MacroHitTestBatch')
NATIVE = os.name == 'nt' and bool(os.environ.get('CUCP_NATIVE_HOST'))


def fixture():
    monitor = dict(device='DISPLAY1', primary=True, rect=dict(x=-500, y=0, width=1000, height=500),
                   work_rect=dict(x=-500, y=0, width=1000, height=480), dpi=dict(x=96, y=96, scale_x=1, scale_y=1))
    return dict(loaded=True, layout=dict(virtual_screen=dict(x=-500, y=0, width=1000, height=500,
                  right=500, bottom=500, monitor_count=1, same_display_format=True), monitors=[monitor],
                  point_monitor=monitor, target_monitor=None, target_window_dpi=None),
                target=dict(target_monitor=monitor, target_window_dpi=dict(dpi=96, scale=1)),
                windows=[dict(hwnd=42, title='Owned Editor', process='editor', pid=1, visible=True, minimized=False,
                              foreground=False, rect=dict(x=100, y=100, width=200, height=100), **{'class': 'Owned'})],
                hit=dict(status='ok', x=100, y=101, child_hwnd=43, root_hwnd=42, root_title='Owned Editor', child_title='',
                         root_class='Owned', process_id=1, process_name='editor', target_hwnd=42, target_match='',
                         matched=True, match_reason='hwnd_match', uia_skipped=True, source='wrapper_win32_fast'))


def project(value):
    if isinstance(value, dict):
        return {key: project(item) for key, item in value.items() if key != 'elapsed_ms'}
    return [project(item) for item in value] if isinstance(value, list) else value


class CoordinateBoundaryTests(unittest.TestCase):
    def test_unknown_fields_and_input_actions_fail_without_acquisition(self):
        runtime = CoordinateRuntime()
        try:
            with patch.object(runtime, 'read', side_effect=AssertionError('unexpected acquisition')):
                for action, args in [('click', {}), ('hit', dict(x=1, y=1, target_hwnd=0, target_match='', allow_live_control=True)),
                                     ('profile', dict(x=True, y=1, has_point=True, target_hwnd=0, target_match=''))]:
                    with self.subTest(action=action), self.assertRaises(LegacyHostError):
                        runtime.value(action, args)
        finally:
            runtime.close()


@unittest.skipUnless(NATIVE, 'Explicit compiled Windows coordinate backend')
class CoordinateParityTests(unittest.TestCase):
    def test_profile_math_risks_window_selection_and_macro_argv_in_both_shells(self):
        cases = []
        for x, y in ((100, 101), (300, 200), (-501, -1), (0, 0), (299, 199)):
            for target in (0, 42, 2147483648):
                for point in (False, True):
                    f = fixture()
                    f['args'] = dict(has_point=point, x=x, y=y, target_hwnd=target, target_match='')
                    f['operation'] = 'profile'
                    cases.append(f)
        for scale, count, matched, point_device in ((1.5, 2, False, 'DISPLAY2'), (1, 1, True, 'DISPLAY1')):
            f = fixture(); f['args'] = dict(has_point=True, x=101, y=102, target_hwnd=42, target_match='')
            f['target']['target_monitor']['dpi']['scale_x'] = scale
            f['layout']['virtual_screen']['monitor_count'] = count
            f['layout']['point_monitor']['device'] = point_device
            f['hit']['matched'] = matched; f['operation'] = 'profile'; cases.append(f)
        for size in (2, 3, 7, 17, 33, 100):
            f = fixture(); w = f['windows'][0]
            f['windows'] = [dict(w, hwnd=i+1, title=f'Probe {i}') for i in range(size)]
            f['args'] = dict(has_point=False, x=0, y=0, target_hwnd=0, target_match='Probe')
            f['operation'] = 'profile'; cases.append(f)
        for rest in ([], ['--x', '1'], ['--x', '0x64', '--y', '101', '--target-hwnd', '0x2a'],
                     ['--x', '100', '--y', '101', '--window', 'Editor'], ['--x', 'bad', '--y', 'bad'],
                     ['--target-hwnd', ' 0x2a '], ['--target-hwnd', '9223372036854775808']):
            for brief in (False, True):
                f = fixture();f.update(operation='macro', name='coord-profile', rest=rest, brief=brief);cases.append(f)
        for mode in ('screen', 'SCREEN', 'window', 'normalized', 'visible-normalized', 'bad'):
            for brief in (False, True):
                f=fixture();f.update(operation='macro', name='coord-map',
                    rest=['--from', mode, '--x', '0.5', '--y', '0.5', '--target-hwnd', '42'], brief=brief);cases.append(f)
        for points in (['1,2'], ['1,2', '0,1', 'bad', '-1,4'], ['١,٢'], ['2147483648,1'], [],
                       ['\x1c1,2'], [' 1 , 2 '], ['1,2\n'], ['𝟙,𝟚']):
            for brief in (False, True):
                rest = [word for point in points for word in ('--point', point)]
                f=fixture();f.update(operation='macro', name='hit-test-batch', rest=rest, brief=brief);cases.append(f)
        for has_point in (False, True):
            f=fixture();f['loaded']=False;f.update(operation='profile', args=dict(has_point=has_point,x=1,y=1,target_hwnd=0,target_match=''));cases.append(f)
        with tempfile.TemporaryDirectory(prefix='CUCP coordinate oracle ') as directory:
            owned=Path(directory);source=owned/'original.ps1';source.write_bytes(subprocess.check_output(['git','show',BASE+':scripts/cucp.ps1'],cwd=ROOT))
            inputs=owned/'input.json';inputs.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig')
            oracle=owned/'oracle.ps1'
            oracle.write_text(r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
class CucpWin32 {
 static [object]$F
 static [object] GetVirtualScreenInfo(){ $v=[CucpWin32]::F.layout.virtual_screen;return @{X=$v.x;Y=$v.y;Width=$v.width;Height=$v.height;MonitorCount=$v.monitor_count;SameDisplayFormat=$v.same_display_format} }
 static [object] ConvertMonitor([object]$m){if($null -eq $m){return $null};return @{DeviceName=$m.device;Primary=$m.primary;X=$m.rect.x;Y=$m.rect.y;Width=$m.rect.width;Height=$m.rect.height;WorkX=$m.work_rect.x;WorkY=$m.work_rect.y;WorkWidth=$m.work_rect.width;WorkHeight=$m.work_rect.height;DpiX=$m.dpi.x;DpiY=$m.dpi.y;ScaleX=$m.dpi.scale_x;ScaleY=$m.dpi.scale_y} }
 static [object[]] EnumerateMonitors(){return @([CucpWin32]::F.layout.monitors|ForEach-Object{[CucpWin32]::ConvertMonitor($_)})}
 static [object] MonitorFromScreenPointInfo([int]$x,[int]$y){return [CucpWin32]::ConvertMonitor([CucpWin32]::F.layout.point_monitor)}
 static [object] MonitorFromWindowInfo([IntPtr]$h){return [CucpWin32]::ConvertMonitor([CucpWin32]::F.target.target_monitor)}
 static [int] GetWindowDpiValue([IntPtr]$h){return [CucpWin32]::F.target.target_window_dpi.dpi}
}
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('_Read-OptValue','_Read-AllOptValues','_Read-Switch','_Native-FindWindow','_CoordProfile-MonitorObject','_CoordProfile-WindowFromPrecheck','_Build-CoordProfile','_Build-CoordMap','Invoke-MacroCoordProfile','Invoke-MacroCoordMap','Invoke-MacroHitTestBatch','_CoordMap-ResolveWindow','_Invoke-LegacyCompatibility')){
 $f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true));if($f.Count -ne 1){throw 'Missing original function.'};. ([scriptblock]::Create($f[0].Extent.Text))
}
function _Ensure-Win32Loaded {return [CucpWin32]::F.loaded}
function _Enumerate-Win32Windows {param([string]$Match) foreach($w in [CucpWin32]::F.windows){if(-not $Match -or $w.title.ToLowerInvariant().IndexOf($Match.ToLowerInvariant()) -ge 0 -or $w.process.ToLowerInvariant().IndexOf($Match.ToLowerInvariant()) -ge 0){$w}}}
function _Native-HitTestPoint {param([int]$X,[int]$Y,[int]$TargetHwnd,[string]$TargetMatch) $h=[CucpWin32]::F.hit.PSObject.Copy();$h.x=$X;$h.y=$Y;$h.target_hwnd=$TargetHwnd;$h.target_match=$TargetMatch;return $h}
$results=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 [CucpWin32]::F=$case;$Brief=[bool]$case.brief;$value=$null;$failed=$false;$exit=$null;$previous=[Console]::Out;$writer=New-Object IO.StringWriter
 try{[Console]::SetOut($writer);if($case.operation -eq 'profile'){$a=$case.args;$value=_Build-CoordProfile -HasPoint $a.has_point -X $a.x -Y $a.y -TargetHwnd $a.target_hwnd -TargetMatch $a.target_match}
 else{$name=switch($case.name){'coord-profile'{'Invoke-MacroCoordProfile'};'coord-map'{'Invoke-MacroCoordMap'};'hit-test-batch'{'Invoke-MacroHitTestBatch'}};$exit=& $name -Rest ([string[]]$case.rest)}}catch{$failed=$true}finally{[Console]::SetOut($previous)}
 [void]$results.Add(@{value=$value;failed=$failed;exit=$exit;output=$writer.ToString()});$writer.Dispose()
}
[Console]::WriteLine((ConvertTo-Json -InputObject @($results) -Depth 64 -Compress))
''',encoding='utf-8-sig')
            for host in filter(None,(shutil.which('powershell.exe'),shutil.which('pwsh.exe'))):
                process=subprocess.run([host,'-NoProfile','-NonInteractive','-File',str(oracle),'-Source',str(source),'-InputPath',str(inputs)],capture_output=True,timeout=180)
                self.assertEqual(process.returncode,0,process.stderr.decode('utf-8',errors='replace'))
                expected=json.loads(process.stdout.decode('utf-8-sig'))
                for case, before in zip(cases,expected):
                    def read(operation, argv):
                        if operation=='ensure-win32':return case['loaded']
                        if operation=='windows':return copy.deepcopy(case['windows'])
                        if operation=='coordinate-snapshot':return copy.deepcopy(case['layout'])
                        if operation=='coordinate-target':return copy.deepcopy(case['target'])
                        values=dict(zip(argv[::2],argv[1::2]));return dict(case['hit'],x=int(values['--x']),y=int(values['--y']),target_hwnd=int(values['--target-hwnd']),target_match=values['--target-match'])
                    runtime=CoordinateRuntime(modern=Path(host).name.lower()=='pwsh.exe')
                    try:
                        with patch.object(runtime,'read',side_effect=read):
                            runtime.coordinates.read=read
                            failed=False
                            try:after=runtime.value('profile',case['args']) if case['operation']=='profile' else runtime.run(case['name'],case['rest'],brief=case['brief'])
                            except (LegacyHostError,ValueError,OverflowError):failed=True;after=None
                        with self.subTest(host=Path(host).name,case=case['operation'],args=case.get('args'),name=case.get('name'),rest=case.get('rest')):
                            self.assertEqual(failed,before['failed'])
                            if failed:continue
                            if case['operation']=='profile':self.assertEqual(project(after),project(before['value']))
                            else:
                                self.assertEqual(after['exit'],before['exit'])
                                if after['emit_json']:self.assertEqual(project(after['payload']),project(json.loads(before['output'])))
                                else:
                                    import re
                                    self.assertEqual(re.sub(r'elapsed_ms=\d+','elapsed_ms=N',after['brief']),re.sub(r'elapsed_ms=\d+','elapsed_ms=N',before['output'].strip()))
                    finally:runtime.close()

    def test_actual_production_wrapper_reads_and_batch_reuse_without_input(self):
        if not shutil.which('powershell.exe'):self.skipTest('Windows shell is unavailable.')
        commands=[['coord-profile','--x','-100000','--y','-100000','--target-match','CUCP absent coordinate target'],
                  ['coord-map','--from','window','--x','1','--y','2','--target-match','CUCP absent coordinate target'],
                  ['hit-test-batch','--points','1,1;2,2;0,1;bad']]
        for rest in commands:
            process=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(ROOT/'scripts/cucp.ps1'),
                                    '-Quiet','macro',*rest],capture_output=True,timeout=45)
            payload=json.loads(process.stdout.decode('utf-8-sig'))
            self.assertIn(process.returncode,(0,2));self.assertIn(payload['status'],('ok','partial'))
        runtime=CoordinateRuntime(timeout_s=30)
        try:
            result=runtime.value('batch',dict(points=['1,1']*50,maximum=200,target_hwnd=0,target_match=''))
            self.assertEqual(result['result_count'],50)
            self.assertEqual(runtime.native._id,51)  # One ensure and fifty reads, one worker.
            self.assertIsNotNone(runtime.native.pid)
        finally:runtime.close()


if __name__=='__main__':unittest.main()
