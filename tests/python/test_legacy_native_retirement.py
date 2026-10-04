"""Verify genuine native source replacement and explicit historical oracle scope."""
import hashlib
import re
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_native_desktop import ACTIONS as DESKTOP
from pcucp_cli.legacy_cdp_contract import ACTIONS as CDP
from legacy_historical_native import PINS, read, materialize


class NativeRetirementTests(unittest.TestCase):
    def test_all_original_helper_actions_have_a_python_or_csharp_route(self):
        raw = read('scripts/cucp-native-helper.ps1')
        source = raw.decode('utf-8-sig')
        match = re.search(r'\[ValidateSet\((.*?)\)\]\s*\[string\]\$Action', source, re.S)
        self.assertIsNotNone(match)
        expected = set(re.findall(r'"([a-z-]+)"', match[1]))
        self.assertEqual(len(expected), 34)
        self.assertEqual(expected, DESKTOP | CDP)
        self.assertFalse((ROOT / 'scripts/cucp-native-helper.ps1').exists())
        self.assertTrue((ROOT / 'scripts/cucp-native-helper.py').is_file())

    def test_oracle_is_hash_pinned_and_written_only_to_owned_temporary_source(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder).resolve() / 'oracle'
            materialize(destination)
            source = destination / 'cucp-native-helper.ps1'
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), PINS['scripts/cucp-native-helper.ps1'])
            source.write_text('owned changed fixture')
            with self.assertRaisesRegex(ValueError, 'collision'): materialize(destination)
        with self.assertRaises(ValueError): read('scripts/unknown.ps1')

    def test_production_entrypoint_has_no_script_fallback(self):
        for name in ('legacy_native_entry.py', 'legacy_native_desktop.py', 'legacy_execution_runtime.py'):
            source = (ROOT / 'pcucp-next/python/pcucp_cli' / name).read_text(encoding='utf-8')
            self.assertNotIn('powershell.exe', source.casefold())
            self.assertNotIn('legacy_historical_native', source)
            self.assertNotIn('cucp-native-helper.ps1', source)
