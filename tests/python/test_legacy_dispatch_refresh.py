"""Narrow reviewed source refresh; no arbitrary normalization or dispatch change."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli import legacy_dispatch as dispatch

BASE_BLOB = 'dc4d420158f490000c85e0b8a0eb483f022dcc76'
CURRENT_BLOB = '8e996169535fb4c6ffa57207711ead9cf85b30df'
BASE_DISPATCH_INVARIANTS = '197e928b0dc9b729f7089cffe8ac12e11bc62351990979676c76adf510c2284d'


class RegistryRefreshTests(unittest.TestCase):
    def test_exact_reviewed_two_line_delta_and_public_baseline_provenance(self):
        base = subprocess.check_output(['git', 'cat-file', 'blob', BASE_BLOB], cwd=ROOT)
        current = subprocess.check_output(['git', 'cat-file', 'blob', CURRENT_BLOB], cwd=ROOT)
        marker = b'    if (Test-Path -LiteralPath $stderrFile) { $err = Get-Content -LiteralPath $stderrFile -Raw -Encoding UTF8 }\n'
        addition = (b'    if ($raw -is [string]) { $raw = [string]::new($raw.ToCharArray()) }\n'
                    b'    if ($err -is [string]) { $err = [string]::new($err.ToCharArray()) }\n')
        self.assertEqual(base.count(marker), 1)
        self.assertEqual(base.replace(marker, marker + addition, 1), current)
        # Preserve the historical two-line correction proof. The subsequently
        # reviewed Python transport changes only this one function and its path.
        actual = dispatch._canonical_text((ROOT / 'scripts/cucp.ps1').read_bytes())
        old_body = dispatch._function_extent(dispatch._canonical_text(current), 'Invoke-NativeHelper')[2]
        new_body = dispatch._function_extent(actual, 'Invoke-NativeHelper')[2]
        expected = dispatch._canonical_text(current).replace(old_body, new_body, 1).replace(
            '$Script:NativeHelperPath = Join-Path $PSScriptRoot "cucp-native-helper.ps1"',
            '$Script:NativeHelperPath = Join-Path $PSScriptRoot "cucp-native-helper.py"', 1)
        for name in ('_Read-LockSafely','_Is-StaleLock','_Try-Delete-Lock','Get-HelperServerStatus','Invoke-HelperPipe','Start-HelperServer','Stop-HelperServer',
                     'Install-HelperAutostart','Uninstall-HelperAutostart','Get-HelperAutostartStatus','_Read-HelperServerVersion','Get-CucpVersionReport'):
            expected = expected.replace(dispatch._function_extent(expected,name)[2], dispatch._function_extent(actual,name)[2],1)
        from test_legacy_native_macros import HANDLERS
        for name in HANDLERS.values():
            expected=expected.replace(dispatch._function_extent(expected,name)[2],dispatch._function_extent(actual,name)[2],1)
        from test_python_history_production import HANDLERS as HISTORY_HANDLERS
        for name in HISTORY_HANDLERS:
            expected=expected.replace(dispatch._function_extent(expected,name)[2],dispatch._function_extent(actual,name)[2],1)
        history_capture=dispatch._function_extent(actual,'_History-Capture')[2]
        expected=expected.replace('function Invoke-MacroHistory {',history_capture+'\n\nfunction Invoke-MacroHistory {',1)
        helper=dispatch._function_extent(actual,'_Invoke-LegacyNativeMacro')[2]
        expected=expected.replace('function Invoke-MacroNativeHealth {',helper+'\n\nfunction Invoke-MacroNativeHealth {',1)
        for before,after in (
            ('$Script:HelperServerScript = Join-Path $PSScriptRoot "cucp-helper-server.ps1"','$Script:HelperServerScript = Join-Path $PSScriptRoot "cucp-helper-server.py"'),
            ('# cucp-helper-server.ps1 (named pipe server) 와의 JSON-line IPC 헬퍼.','# Python/C# read-only helper named-pipe client.'),
            ('# 없거나 stale 이면 child PowerShell fallback.','# 없거나 stale 이면 Python/C# cold path.'),
            ('# server 가 직접 처리 가능한 action 화이트리스트 (cucp-helper-server.ps1 v1.7.0 의 _Dispatch 와 일치)','# Closed read-only action list supported by the compiled helper.')):
            self.assertEqual(expected.count(before),1)
            expected=expected.replace(before,after,1)
        self.assertEqual(actual, expected)
        self.assertIn("-Operation 'desktop-native'", new_body)
        self.assertNotIn('Start-Process', new_body)
        self.assertNotIn('$stdoutFile', new_body)
        revision = dispatch.load_contract().metadata['checkpoint']['source_revision']
        self.assertEqual(revision['base_public_commit'], '968379e6eca731ff849fd554339601261c291584')
        self.assertEqual(revision['base_tree'], '5fb9191301f91e585efe40c8c86c0f74b296f92c')
        self.assertEqual((revision['base_wrapper_blob'], revision['current_wrapper_blob']), (BASE_BLOB, CURRENT_BLOB))

    def test_only_native_helper_function_extent_changed(self):
        base = dispatch._canonical_text(subprocess.check_output(['git', 'cat-file', 'blob', BASE_BLOB], cwd=ROOT))
        contract = dispatch.load_contract()
        changed = []
        for row in contract.metadata['extents']:
            if row['path'] != 'scripts/cucp.ps1' or row['kind'] != 'function':
                continue
            first, last, body = dispatch._function_extent(base, row['name'])
            if dispatch._digest(body) != row['sha256']:
                changed.append(row['name'])
            actual = dispatch._canonical_text((ROOT / row['path']).read_bytes())
            current_first, current_last, current_body = dispatch._function_extent(actual, row['name'])
            self.assertEqual((row['start_line'], row['end_line'], row['sha256']),
                (current_first, current_last, dispatch._digest(current_body)))
        from test_legacy_native_macros import HANDLERS
        self.assertEqual(set(changed),{'Invoke-NativeHelper','Invoke-MacroHistory',*HANDLERS.values()})
        dispatch.assert_frozen_sources(ROOT)

    def test_all_dispatch_handler_and_safety_invariants_remain_identical(self):
        # The reviewed invariant digest was computed before the two-line source
        # refresh. Only source locations are excluded, never contract content.
        data = json.loads((ROOT / 'docs/legacy-dispatch-contract.json').read_text(encoding='utf-8'))
        value = {key: data[key] for key in ('semantics', 'wrapper_parameters', 'direct_safety_macros',
            'not_implemented', 'unknown_macro', 'direct_safety_order', 'confirmation_contract',
            'authority_order', 'live_request_rules', 'coordinate_observation_gate')}
        value['clauses'] = [{key: item for key, item in row.items() if key != 'source_line'} for row in data['clauses']]
        value['dispatch_relationships'] = [{key: item for key, item in row.items() if key != 'callee_start_line'}
                                           for row in data['dispatch_relationships']]
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, BASE_DISPATCH_INVARIANTS)
        self.assertEqual(data['checkpoint']['source_revision']['dispatch_and_safety_invariants_sha256'], BASE_DISPATCH_INVARIANTS)
        self.assertEqual(len(value['clauses']), 109)
        self.assertEqual(len({row['name'] for row in value['clauses']}), 108)
        self.assertEqual(len(value['dispatch_relationships']), 109)

    def test_entire_cli_json_capture_list_includes_numeric_name(self):
        source = (ROOT / 'scripts/cucp.ps1').read_text(encoding='utf-8-sig')
        block = re.search(r'\$_jsonSurfacedFirstWords = @\((.*?)\n\)', source, re.S)[1]
        expected = tuple(re.findall(r'"([^"\r\n]+)"', block))
        self.assertEqual(dispatch.load_contract().metadata['top_level']['json_capture_first_words'], expected)
        self.assertEqual(expected, ('plan', 'scenario', 'tools', 'version', 'health', 'release',
                                    'observe', 'act', 'app', 'desktop', 'l5', 'replay'))
        self.assertEqual(dispatch.classify_top_level(['l5']).kind, 'cli_json')
        self.assertEqual(dispatch.classify_top_level(['L5', 'run']).kind, 'cli_json')


if __name__ == '__main__':
    unittest.main()
