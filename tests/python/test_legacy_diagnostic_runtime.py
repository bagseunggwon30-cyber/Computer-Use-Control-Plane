"""Real coordinator/native/Node integration without controlling target applications."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_diagnostic_runtime import DiagnosticRuntime
from pcucp_cli.legacy_host_protocol import Authority, LegacyHostError
from pcucp_cli.legacy_host_session import LegacyEffectSession
from pcucp_cli.legacy_label_provider import LabelReadProvider


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_DIAGNOSTIC_PROVIDER_NATIVE') and shutil.which('node'),
                     'Explicit Windows native and Node integration gate')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP runtime 한글 ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        (self.root / 'audit').mkdir()
        (self.root / 'cache').mkdir()
        (self.root / 'cli').mkdir()
        (self.root / 'package.json').write_text(json.dumps({'name': 'computer-use-control-plane'}), encoding='utf-8')
        # Owned dependency fixture: exercise native argv, Unicode paths, and the
        # existing artifact ABI. This does not certify the absent desktop CLI.
        (self.root / 'cli/cli.mjs').write_text('''import fs from 'node:fs';
const args = process.argv.slice(2);
const out = args.indexOf('--out');
const artifact = {type:'desktop_appshot',observation_id:'fixture-owned',focused_window:'',
 screenshot_path:'fixture.png',text:{items:[{affordance_id:'fixture-text',rect:{x:1,y:2,width:3,height:4}}]}};
const fusion = {type:'desktop_observation_fusion',fused_elements:[],
 grounded_elements:[{affordance_id:'fixture-grounded',rect:{x:5,y:6,width:7,height:8}}]};
const result = {status:'ok',version:'2.0.0',artifacts:[artifact,fusion]};
if(out>=0) fs.writeFileSync(args[out+1],JSON.stringify(result));
console.log(JSON.stringify(result));
''', encoding='utf-8')
        (self.root / 'CHANGELOG.md').write_text('## 2.3.4\n### Added\n- 한글\n', encoding='utf-8-sig')
        (self.root / 'wrapper.log').write_text('INFO first\nERROR fixture\n', encoding='utf-8')
        (self.root / 'audit/trajectory.ndjson').write_text(
            json.dumps({'kind': 'click', 'exit': 0, 'macro': 'windows'}) + '\n', encoding='utf-8')
        self.context = dict(audit_directory=str(self.root / 'audit'), cache_directory=str(self.root / 'cache'),
            wrapper_log=str(self.root / 'wrapper.log'), cli_path=str(self.root / 'cli/cli.mjs'),
            changelog_path=str(self.root / 'CHANGELOG.md'), temp_root=str(self.root),
            benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')
        environment = patch.dict(os.environ, CUCP_NATIVE_HOST=os.environ['CUCP_DIAGNOSTIC_PROVIDER_NATIVE'])
        environment.start()
        self.addCleanup(environment.stop)

    def runtime(self, **options):
        return DiagnosticRuntime(self.context, timeout_s=30, helper_status=lambda: False, **options)

    def test_all_nine_families_produce_original_payload_and_exit_boundaries(self):
        cases = [('release-notes', []), ('log-tail', []), ('audit-summary', []), ('health-quick', []),
                 ('health-detail', []), ('diagnose-lag', ['--sample-ms', '1']),
                 ('benchmark', ['--iters', '1']), ('perf', ['--quick', '--iters', '1']),
                 ('perf', ['--iters', '1', '--include-live-ish']), ('self-test', [])]
        for operation, rest in cases:
            with self.subTest(operation=operation):
                result = self.runtime().run(operation, rest)
                self.assertIn(result['exit'], (0, 1, 2))
                self.assertTrue(result['emit_json'])
                self.assertIsInstance(result['payload'], dict)
                self.assertIn('status', result['payload'])
                if operation in {'release-notes', 'log-tail', 'audit-summary', 'health-quick', 'self-test'}:
                    self.assertEqual(result['exit'], 0)
                if operation == 'self-test':
                    self.assertEqual(result['payload']['failed'], 0)
                    self.assertTrue(result['payload']['helper_running'])

    def test_appshot_preserves_cache_and_existing_artifact_shape(self):
        runtime = self.runtime()
        value = dict(match='selftest-cache', semantic=False, no_cache=True, cache_max_seconds=None)
        first = runtime._appshot(value)
        value.update(no_cache=False, cache_max_seconds=600)
        second = runtime._appshot(value)
        self.assertFalse(first['FromCache'])
        self.assertTrue(second['FromCache'])
        self.assertEqual(second['ObservationId'], 'fixture-owned')
        self.assertEqual(set(second['Affordances']), {'fixture-text', 'fixture-grounded'})
        self.assertTrue(Path(first['Path']).is_file())
        self.assertNotEqual(first['Path'], second['Path'])
        self.assertEqual(runtime._metrics()['counters']['observations'], 1)

    def test_find_label_uses_original_coordinator_and_fast_no_window_boundary(self):
        runtime = self.runtime()
        with runtime.native_factory(allow_live_control=False) as native:
            runtime.native = native
            provider = LabelReadProvider(runtime, ['--label', 'fixture', '--match', 'CUCP-no-such-owned-test-window', '--fast'])
            result = LegacyEffectSession().run('interaction', provider.startup(), Authority(), provider)
        self.assertEqual(result['exit'], 2)
        self.assertEqual(result['payload']['recoverable_errors'][0]['code'], 'no_window')
        self.assertTrue(result['payload']['data']['fast_path'])

    def test_sampling_and_nested_dependencies_share_the_owner_deadline(self):
        runtime = DiagnosticRuntime(self.context, timeout_s=.4, helper_status=lambda: False)
        started = time.monotonic()
        with self.assertRaisesRegex(LegacyHostError, 'timed out'):
            runtime.run('diagnose-lag', ['--sample-ms', '3000'])
        self.assertLess(time.monotonic() - started, 1.5)

    def test_missing_external_cli_is_reported_without_synthetic_appshot(self):
        self.context['cli_path'] = None
        runtime = self.runtime()
        self.assertEqual(runtime._cli(['version']), {'exit': 1, 'json': None})
        self.assertIsNone(runtime._appshot(dict(match='', semantic=False, no_cache=True, cache_max_seconds=None)))
        result = runtime.run('health-detail', [])
        self.assertEqual(result['exit'], 1)
        self.assertFalse(result['payload']['required_ok'])

    def test_brief_and_metrics_preserve_retained_semantics(self):
        runtime = self.runtime()
        result = runtime.run('release-notes', [], brief=True)
        self.assertFalse(result['emit_json'])
        self.assertIn('2.3.4', result['brief'])
        metrics = runtime._metrics()
        self.assertEqual(metrics['counters']['clicks'], 1)
        self.assertEqual(metrics['rates']['click_success_pct'], 100)


if __name__ == '__main__':
    unittest.main()
