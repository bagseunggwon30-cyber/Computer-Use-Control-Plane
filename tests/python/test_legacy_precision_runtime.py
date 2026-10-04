"""Actual precision pure facade, terminal cache, and fixed Windows root reads."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_precision_runtime import PrecisionRuntime, PrecisionStorage
from pcucp_cli.legacy_native_kernel import precision
from pcucp_cli.legacy_host_protocol import LegacyHostError
from pcucp_cli.legacy_preserved_owner import PreservedOwner


class StorageBoundaryTests(unittest.TestCase):
    def test_invalid_cache_key_never_selects_a_path(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = PrecisionStorage(folder, folder)
            for key in ('../owned', 'A' * 32, 'a' * 31):
                with self.assertRaises(LegacyHostError):
                    storage.path(key)


@unittest.skipUnless(os.environ.get('CUCP_NATIVE_HOST'), 'Explicit actual precision facade')
class FacadeTests(unittest.TestCase):
    def test_closed_pure_helpers_and_invalid_operation_boundary(self):
        result = precision('confidence-rank', dict(value='high'))
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['queries'], [])
        self.assertEqual(result['effects'], [])
        self.assertEqual(result['payload'], 3)
        with self.assertRaises(LegacyHostError):
            precision('RunScript', dict(value='macro click'))

    def test_point_plan_cache_cold_warm_and_prebuilt_terminal_output(self):
        # Owned fixed acquisition fixture. This proves facade/cache contracts,
        # not UIA discovery or action in a third-party application.
        class Coordinates:
            def hit(self, x, y, hwnd, match):
                return dict(status='ok', matched=True, root_hwnd=123, root_title='Owned', process_name='fixture',
                    target_hwnd=hwnd, match_reason='hwnd_match')
            def profile(self, **args):
                return dict(status='ok', coordinate_risk='low', coord_signature='owned', warnings=[], elapsed_ms=1)
        calls = []
        def native(argv):
            calls.append(argv)
            point = dict(x=20, y=30, confidence='high', point_source='native_clickable', native_clickable=True)
            body = dict(status='ok', recommended_point=point, best=dict(rect=dict(x=10, y=20, width=30, height=30),
                role='Button', support=3, area=900, native_clickable=True), sample_count=1)
            return dict(ExitCode=0, Json=body, Raw=json.dumps(body), Err='', ElapsedMs=1)
        with tempfile.TemporaryDirectory(prefix='CUCP precision cache 한글 ') as folder:
            root = Path(folder).resolve(); (root / 'cache').mkdir()
            factory = lambda: PrecisionRuntime(Coordinates(), native, audit_directory=root / 'audit', cache_directory=root / 'cache')
            rest = ['--x', '20', '--y', '30', '--target-hwnd', '123', '--cache-ttl', '60']
            first = factory().run('point-plan', rest)
            self.assertEqual(first['exit'], 0)
            self.assertEqual(json.loads(first['raw']), first['payload'])
            self.assertFalse(first['payload']['from_cache'])
            second = factory().run('point-plan', rest)
            self.assertEqual(second['exit'], 0)
            self.assertTrue(second['payload']['from_cache'])
            self.assertEqual(len(calls), 1, 'Warm facade must not repeat the native acquisition.')
            self.assertEqual(len(list((root / 'cache').glob('*.json'))), 1)


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_NATIVE_HOST') and os.environ.get('CUCP_LEGACY_DESKTOP_EXE'),
    'Actual Windows preserved precision root')
class RootPrecisionTests(unittest.TestCase):
    def test_missing_target_runs_all_three_planners_without_input(self):
        with tempfile.TemporaryDirectory(prefix='CUCP precision root 한글 ') as folder:
            root = Path(folder).resolve()
            context = dict(audit_directory=str(root / 'audit'), cache_directory=str(root / 'cache'), wrapper_log=str(root / 'wrapper.log'),
                cli_path=None, changelog_path=str(root / 'CHANGELOG.md'), temp_root=str(root),
                benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')
            owner = PreservedOwner(context)
            self.addCleanup(owner.close)
            for name in ('coord-anchor', 'point-plan', 'target-validate'):
                with self.subTest(name=name):
                    code, output = owner.invoke(['macro', name, '--x', '1', '--y', '1', '--target-match', 'CUCP unique absent precision target', '--no-cache'])
                    payload = json.loads(output)
                    self.assertEqual(payload['schema'], 'cucp.' + name + '/v1')
                    self.assertIn(code, (0, 2))
                    if name != 'coord-anchor':
                        self.assertEqual(code, 2)
            self.assertEqual(list(root.glob('cache/*.json')), [])


if __name__ == '__main__':
    unittest.main()
