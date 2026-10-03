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
        self.assertEqual(dispatch._canonical_text((ROOT / 'scripts/cucp.ps1').read_bytes()), dispatch._canonical_text(current))
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
            self.assertEqual(row['start_line'], first + (2 if first > 1304 else 0))
            self.assertEqual(row['end_line'], last + (2 if last > 1304 else 0))
        self.assertEqual(changed, ['Invoke-NativeHelper'])
        dispatch.assert_frozen_sources(ROOT)

    def test_all_dispatch_handler_and_safety_invariants_remain_identical(self):
        # The reviewed invariant digest was computed before the two-line source
        # refresh. Only source locations are excluded, never contract content.
        data = json.loads((ROOT / 'docs/legacy-dispatch-contract.json').read_text())
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
