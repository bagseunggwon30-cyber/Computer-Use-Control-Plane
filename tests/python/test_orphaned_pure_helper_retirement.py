"""Keep retired private helpers out of production while preserving pinned oracles."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
QUALIFIED_TREE = 'd4c9660d40c7e909f18afb166a8e846798f63b1d'
SOURCE_SHA256 = '6fa1802661fd935df2c4d643aba8b5300723f8e0f75aac9d8fcf284688c28ba9'
REMOVED = {
    '_TaskPlan-QuoteToken': 218,
    '_TaskPlan-StepString': 542,
    '_TaskPlan-UnwrapCommand': 214,
    '_AppStrategy-Key': 350,
    '_Cucp-RedactSecrets': 771,
    '_Iif': 95,
    '_Set-ObjectProperty': 261,
}


def original_imports(source):
    """Inspect the unconditional original-source list, before any bridge branch."""
    match = re.search(r'^\$names=@\((.*?)\)', source, re.M | re.S)
    if not match:
        raise AssertionError('Missing pinned-original import list')
    return set(re.findall(r"'([^']+)'", match[1]))


class OrphanedPureHelperRetirementTests(unittest.TestCase):
    def test_production_has_no_retired_names_and_keeps_shared_route_helper(self):
        for path in (ROOT / 'scripts').glob('*.ps1'):
            source = path.read_text(encoding='utf-8-sig').lower()
            for name in REMOVED:
                with self.subTest(path=path.name, function=name):
                    self.assertNotIn(name.lower(), source)
        current = (ROOT / 'scripts/cucp.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('function _AppStrategy-NormalizeRoute {', current)
        self.assertIn('(_AppStrategy-NormalizeRoute -Strategy $Strategy)', current)

    def test_inventory_extents_match_qualified_windows_source_map(self):
        original = subprocess.check_output(
            ['git', 'show', f'{QUALIFIED_TREE}:scripts/cucp.ps1'], cwd=ROOT
        ).decode('utf-8-sig').replace('\r\n', '\n')
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), SOURCE_SHA256)
        utf16 = original.encode('utf-16-le')
        inventory = json.loads((ROOT / 'docs/legacy-function-inventory.json').read_text())
        rows = {row['name']: row for row in inventory['retired_functions']
                if row['path'] == 'scripts/cucp.ps1' and row['name'] in REMOVED}
        self.assertEqual(set(rows), set(REMOVED))
        self.assertEqual(sum(REMOVED.values()), 2451)
        for name, size in REMOVED.items():
            with self.subTest(function=name):
                row = rows[name]
                body = utf16[row['original_start_utf16'] * 2:row['original_end_utf16'] * 2]
                body = body.decode('utf-16-le').encode()
                self.assertTrue(body.startswith(f'function {name} '.encode()))
                self.assertEqual(row['original_source_sha256'], SOURCE_SHA256)
                self.assertEqual(row['original_body_bytes'], size)
                self.assertEqual(len(body), size)
                self.assertEqual(hashlib.sha256(body).hexdigest(), row['original_body_sha256'])
                self.assertTrue((ROOT / row['replacement']).is_file())

    def test_pinned_original_imports_still_include_retired_helpers(self):
        from test_legacy_app_profile_parity import CAPTURE_RUNNER as app_profile
        from test_legacy_precision_parity import CAPTURE_RUNNER as precision
        from test_legacy_smart_plan_parity import CAPTURE_RUNNER as smart_plan
        from test_legacy_task_preset_parity import PS_RUNNER as preset
        quoting = {'_TaskPlan-QuoteToken', '_TaskPlan-StepString'}
        expected = (
            (app_profile, quoting | {'_AppStrategy-Key'}),
            (precision, quoting | {'_Set-ObjectProperty'}),
            (smart_plan, quoting),
            (preset, quoting | {'_TaskPlan-UnwrapCommand'}),
        )
        for source, names in expected:
            self.assertTrue(names <= original_imports(source))
        for family, helper in (('file', '_Cucp-RedactSecrets'), ('runtime', '_Iif')):
            source = (ROOT / f'tests/fixtures/legacy-diagnostics-{family}-oracle.ps1').read_text(encoding='utf-8-sig')
            self.assertIn(helper, original_imports(source))
            # Only production entry loading may omit this unused original helper.
            self.assertIn(f"if($ProductionEntry){{$names=@($names|Where-Object {{$_ -ne '{helper}'}})}}", source)
