"""Original direct macro acquisition and report parity; callbacks stay inert."""
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
from pcucp_cli.legacy_native_macros import NativeMacros, LIVE
from pcucp_cli.legacy_host_protocol import Authority
from pcucp_cli.legacy_native_desktop import DesktopSession

CASES = {
    'native-health': [], 'native-windows': ['--match', 'CUCP owned absent'],
    'native-screenshot': ['--out', 'owned.png', '--x', '0', '--width', '32', '--height', '16'],
    'type-native': ['--text', '한글😀 " --confirm-sensitive', '--clear', '--enter'],
    'shortcut-native': ['--keys', 'ctrl+s'], 'uia-click-label': ['--label', 'Owned', '--match', 'Editor', '--button', 'right'],
    'uia-invoke': ['--label', 'Owned', '--role', 'Button'], 'uia-set-value': ['--label', 'Owned', '--value', ''],
    'uia-toggle': ['--label', 'Owned', '--match', 'Editor'], 'ocr-screen': ['--region', '0, 0, 32, 16', '--language', 'en-US'],
    'ocr-image': ['--path', 'owned.png', '--language', 'en-US'],
    'ocr-find-text': ['--text', 'Owned', '--max-candidates', '0x4', '--path', 'owned.png', '--region', '0,0,32,16'],
    'ocr-uia-fuse': ['--text', 'Owned', '--match-window', 'Editor', '--language', 'en-US'],
    'ocr-uia-invoke': ['--text', 'Owned', '--match', 'exact', '--match-window', 'Editor'],
    'screenshot-diff': ['--before', 'before.png', '--after', 'after.png', '--threshold', '3', '--ignore-region', '0,0,2,2'],
    'ime-paste': ['--text', '한글😀', '--press-enter', '--target-match', 'Editor', '--target-hwnd', '0x7b'],
    'modal-detect': ['--match', 'Editor', '--target-hwnd', 'bad'],
}
HANDLERS = {name: 'Invoke-Macro' + ''.join(word.title() for word in name.split('-')) for name in CASES}
HANDLERS.update({'uia-click-label': 'Invoke-MacroUiaClickLabel', 'ocr-uia-fuse': 'Invoke-MacroOcrUiaFuse',
    'ocr-uia-invoke': 'Invoke-MacroOcrUiaInvoke'})


class AuthorityTests(unittest.TestCase):
    def test_live_direct_macro_denied_before_native_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            runtime = NativeMacros(lambda *args: calls.append(args), cache_directory=folder, audit_directory=folder)
            for name in LIVE:
                with self.subTest(name=name), self.assertRaises(PermissionError):
                    runtime.run(name, CASES[name])
            self.assertEqual(calls, [])


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Pinned inert Windows macro oracle')
class DirectMacroParityTests(unittest.TestCase):
    def test_all_direct_options_brief_reports_raw_outputs_and_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix='CUCP native macros 한글 ') as folder:
            root = Path(folder).resolve()
            source = root / 'original.ps1'
            source.write_bytes(subprocess.check_output(['git', 'show', '9ffa354b9904235835a7bc6eb78ed8d3d76317c8:scripts/cucp.ps1'], cwd=ROOT))
            fixture = dict(status='ok', count=2, win32=True, uia=True, ocr=True, ocr_languages=['en-US'],
                out_path='owned.png', bytes=123, x=4, y=5, matched_text='Owned', reason='fixture_reason', method='invoke',
                mouse_moved=False, value_length=0, keyboard_used=False, previous_state='Off', line_count=1, word_count=2,
                engine_language='en-US', top=dict(text='Owned', score=100, cx=4, cy=5), candidate_count=2,
                ocr_top=dict(text='Owned', score=100), can_invoke=True, invoke_pattern='Invoke', recommendation='uia_invoke',
                uia_name='', uia_automation_id='owned', uia_class_name='Button', ocr_score=100, changed=True,
                changed_ratio=.5, changed_pixels=10, effective_pixels=20, ignored_pixels=2, text_len=4,
                restored_clipboard=True, recommended_action='observe')
            cases = []
            for name, rest in CASES.items():
                for brief in (False, True):
                    for status in ('ok', 'partial', 'blocked', None):
                        payload = {**fixture, 'status': status} if status is not None else None
                        cases.append(dict(name=name, handler=HANDLERS[name], rest=rest, brief=brief,
                            reply=dict(ExitCode=0 if status == 'ok' else 3 if status == 'blocked' else 2,
                                Json=payload, Raw='RAW owned 한글\n', Err='fixture error', ElapsedMs=7)))
            inputs, script = root / 'cases.json', root / 'oracle.ps1'
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            script.write_text(r'''
param([string]$SourcePath,[string]$CasesPath,[string]$Cache)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$t,[ref]$e)
$rows=Get-Content -LiteralPath $CasesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$names=@('_Read-OptValue','_Read-Switch')+@($rows.handler|Select-Object -Unique)
foreach($name in $names){
 $f=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($f.Count -ne 1){throw "Missing original function: $name"}
 . ([scriptblock]::Create($f[0].Extent.Text))
}
function Invoke-NativeHelper {param([string[]]$ArgList) $script:capturedArgs=@($ArgList);return $script:reply}
function _Trajectory-Append {param($Kind,$Payload)}
$Script:CacheDir=$Cache;$AllowLiveControl=$true
$Script:CucpV14Schema=@{ImePaste='cucp.ime-paste/v1';ModalDetect='cucp.modal-detect/v1'}
$results=New-Object Collections.ArrayList
foreach($case in $rows){
 $Brief=$case.brief;$script:reply=$case.reply;$script:capturedArgs=@()
 $previous=[Console]::Out;$writer=New-Object IO.StringWriter
 try{[Console]::SetOut($writer);$exit=& $case.handler -Rest ([string[]]$case.rest)}finally{[Console]::SetOut($previous)}
 [void]$results.Add(@{exit=[int]$exit;argv=$script:capturedArgs;output=$writer.ToString()})
 $writer.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            result = subprocess.run([shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-File', str(script),
                '-SourcePath', str(source), '-CasesPath', str(inputs), '-Cache', str(root)], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            expected = json.loads(result.stdout.decode('utf-8-sig'))
            for case, original in zip(cases, expected):
                with self.subTest(name=case['name'], brief=case['brief'], status=case['reply']['Json'] and case['reply']['Json']['status']):
                    acquired = []
                    def native(argv, authority):
                        acquired.append(argv)
                        self.assertEqual(authority.live, case['name'] in LIVE)
                        return case['reply']
                    reply = NativeMacros(native, cache_directory=root, audit_directory=root, authority=Authority(True)).run(
                        case['name'], case['rest'], brief=case['brief'])
                    self.assertEqual(acquired, [original['argv']])
                    self.assertEqual(reply['exit'], original['exit'])
                    if case['brief']:
                        self.assertEqual(reply['brief'] + os.linesep, original['output'])
                    elif reply['raw'] is not None:
                        self.assertEqual(reply['raw'], original['output'])
                    else:
                        self.assertEqual(reply['payload'], json.loads(original['output']))


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_LEGACY_DESKTOP_EXE'), 'Actual Windows direct macro read')
class ActualMacroReadTests(unittest.TestCase):
    def test_real_health_windows_missing_image_and_modal_reports(self):
        with tempfile.TemporaryDirectory(prefix='CUCP macro read 한글 ') as folder:
            native = lambda argv, authority: DesktopSession(authority=authority).run(argv)
            runtime = NativeMacros(native, cache_directory=folder, audit_directory=folder)
            for name, rest, expected in [('native-health', [], 0), ('native-windows', ['--match', 'CUCP unique absent'], 0),
                ('ocr-image', ['--path', str(Path(folder) / 'absent.png')], 1), ('modal-detect', ['--match', 'CUCP unique absent'], 0)]:
                with self.subTest(name=name):
                    result = runtime.run(name, rest, brief=True)
                    self.assertEqual(result['exit'], expected)
                    self.assertIn(name, result['brief'])


if __name__ == '__main__':
    unittest.main()
