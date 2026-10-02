"""Characterize PS5 regex alias folding independently from NLS route collation."""
import copy
import itertools
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_legacy_strategy_parity as strategy

ROOT = Path(__file__).resolve().parents[2]


def alias_cases():
    aliases = ['uia_set_value', 'uia_pattern', 'uia_precision_point', 'uia_coord',
               'fusion_uia_invoke', 'fusion_coord', 'ocr_text', 'vision_precise']
    values = ['custom', ' custom ', 'cdp-click+fallback', 'uia_pattern\n', 'custom+a\nb']
    for alias in aliases:
        values.extend((alias.upper(), alias.replace('i', 'İ'), alias.replace('i', 'ı'), alias.replace('i', 'i\u0307')))
    return [dict(operation='strategy-score', args=dict(app_type='fixture', route_order=[value, 'uia_pattern', 'ocr'],
                 persisted_strategy=dict(strategy=value), labels=['I', 'i', 'İ', 'ı', 'é', 'e\u0301'])) for value in values]


class StrategyCultureAliasSourceTests(unittest.TestCase):
    def test_unicode_alias_corpus(self):
        cases = alias_cases()
        self.assertGreaterEqual(len(cases), 35)
        routes = [c['args']['route_order'][0] for c in cases]
        self.assertTrue(any('İ' in route for route in routes))
        self.assertTrue(any('ı' in route for route in routes))
        self.assertTrue(any('i\u0307' in route for route in routes))


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell 5.1 regex alias characterization')
class StrategyCultureAliasWindowsTests(unittest.TestCase):
    maxDiff = None

    def test_explicit_and_ambient_culture_against_complete_original_score(self):
        project = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyStrategy.CultureTests'
        with tempfile.TemporaryDirectory(prefix='CUCP strategy alias culture ') as temp:
            build = subprocess.run([shutil.which('dotnet'), 'build', str(project), '-c', 'Release', '--output', temp], capture_output=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout.decode('utf-8', errors='replace') + build.stderr.decode('utf-8', errors='replace'))
            host = Path(temp) / 'PcuCp.LegacyStrategy.CultureTests.dll'
            for culture, explicit in itertools.product(('en-US', 'ko-KR', 'tr-TR', ''), (False, True)):
                with self.subTest(culture=culture, explicit=explicit):
                    # Existing helper invokes the pinned PS functions unchanged.
                    # Explicit-culture candidates run in en-US, proving that the
                    # argument governs normalization as well as NLS ordering.
                    strategy.LegacyStrategyParityTests.compare_cases(self, copy.deepcopy(alias_cases()), culture=culture,
                                                                     fixture_host=host, explicit_culture=explicit)
