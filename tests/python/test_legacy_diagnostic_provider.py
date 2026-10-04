"""Owned files, closed capability bounds and actual managed coordinator integration."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_diagnostic_provider import DiagnosticProvider
from pcucp_cli.legacy_host_protocol import Authority, Effect, LegacyHostError
from pcucp_cli.legacy_host_session import LegacyEffectSession


class ProviderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP diagnostic 한글 ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.context = dict(audit_directory=str(self.root / 'audit'), cache_directory=str(self.root / 'cache'),
            wrapper_log=str(self.root / 'wrapper.log'), cli_path=None, changelog_path=str(self.root / 'CHANGELOG.md'),
            temp_root=str(self.root), benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')
        for name in ('audit', 'cache'):
            (self.root / name).mkdir()
        (self.root / 'CHANGELOG.md').write_text('## 2.3.4\n### Added\n- 한글\n## 1.0.0\n', encoding='utf-8-sig')

    def provider(self, operation='release-notes', rest=None, **kwargs):
        return DiagnosticProvider(operation=operation, rest=rest or [], context=self.context, **kwargs)

    def run_effect(self, provider, name, value=None, sub='', argv=()):
        effect = Effect('Diagnostic', name, tuple(argv), {'name': sub, 'value': value}, False, False, False, False)
        provider.validate(effect)
        return provider.dispatch(effect)

    def test_changelog_has_owned_resolve_then_exact_read(self):
        provider = self.provider()
        with self.assertRaises(LegacyHostError):
            self.run_effect(provider, 'ReadLines', self.context['changelog_path'])
        path = self.run_effect(provider, 'ResolvePath', self.context['changelog_path'])
        self.assertEqual(self.run_effect(provider, 'ReadLines', path)[2], '- 한글')
        with self.assertRaises(LegacyHostError):
            self.run_effect(provider, 'ReadLines', str(self.root / 'private.txt'))

    def test_log_tail_is_bounded_and_explicit_selected_paths_are_preserved(self):
        path = self.root / 'chosen.log'
        path.write_bytes(b'first\nERROR last\n')
        provider = self.provider('log-tail', ['--path', str(path), '--max-bytes', '11'])
        result = self.run_effect(provider, 'TailBytes', {'path': str(path), 'max_bytes': 11})
        self.assertEqual(result, {'total_bytes': 17, 'tail_bytes': 11, 'text': 'ERROR last\n'})
        with self.assertRaises(LegacyHostError):
            self.run_effect(provider, 'TailBytes', {'path': str(path), 'max_bytes': True})

    def test_audit_only_reads_files_from_this_invocation(self):
        path = self.root / 'audit/trajectory-fixture.ndjson'
        path.write_text('{"macro":"windows"}\n', encoding='utf-8')
        provider = self.provider('audit-summary')
        rows = self.run_effect(provider, 'ListFiles', dict(path=self.context['audit_directory'],
                              recurse=True, filter='trajectory*.ndjson', file=False))
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.run_effect(provider, 'ReadLines', rows[0]['full_name']), ['{"macro":"windows"}'])
        replacement = self.root / 'audit/replacement.tmp'
        replacement.write_text('different object', encoding='utf-8')
        os.replace(replacement, path)
        # Same-name replacement is not granted acquisition authority from its name.
        with self.assertRaises(LegacyHostError):
            self.run_effect(provider, 'ReadLines', rows[0]['full_name'])

    def test_mutating_or_unknown_callbacks_are_rejected_before_dispatch(self):
        calls = []
        provider = self.provider('benchmark', callbacks={'Native': lambda *args: calls.append(args)})
        for action in ('click', 'type', 'process', 'registry'):
            with self.assertRaises(LegacyHostError):
                self.run_effect(provider, 'Native', argv=('-Action', action))
        effect = Effect('Diagnostic', 'ReadLines', (), {'name': '', 'value': self.context['changelog_path']}, True, False, False, False)
        with self.assertRaises(LegacyHostError):
            provider.validate(effect)
        self.assertEqual(calls, [])

    def test_read_text_keeps_original_line_separators(self):
        path = self.root / 'baseline.json'
        path.write_bytes(b'\xef\xbb\xbf{\r\n "value": 1\r\n}\r\n')
        provider = self.provider('benchmark', ['--baseline', str(path)])
        self.assertEqual(self.run_effect(provider, 'ReadText', str(path)), '{\r\n "value": 1\r\n}\r\n')

    def test_health_probe_and_cache_clear_cannot_escape_owned_directories(self):
        provider = self.provider('health-quick')
        self.run_effect(provider, 'AuditProbe', self.context['audit_directory'], '.health-quick-probe-')
        self.assertEqual(list((self.root / 'audit').iterdir()), [])
        with self.assertRaises(LegacyHostError):
            self.run_effect(provider, 'AuditProbe', str(self.root), '.health-quick-probe-')
        cache = self.root / 'cache/appshot-safe.json'
        cache.write_text('{}', encoding='utf-8')
        sentinel = self.root / 'cache/user.json'
        sentinel.write_text('{}', encoding='utf-8')
        provider = self.provider('perf', ['--include-live-ish'])
        self.run_effect(provider, 'ClearAppshotCache', self.context['cache_directory'], 'appshot-*.json')
        self.assertFalse(cache.exists())
        self.assertTrue(sentinel.exists())

    @unittest.skipUnless(os.environ.get('CUCP_DIAGNOSTIC_PROVIDER_NATIVE'), 'Explicit actual NativeHost coordinator gate')
    def test_actual_managed_release_log_and_audit_use_python_files_only(self):
        (self.root / 'wrapper.log').write_text('first\nERROR last\n', encoding='utf-8')
        (self.root / 'audit/trajectory-owned.ndjson').write_text(json.dumps({'macro': 'windows', 'exit_code': 0}) + '\n', encoding='utf-8')
        for operation, rest in (('release-notes', ['--version', '1.0.0']), ('log-tail', []), ('audit-summary', [])):
            with self.subTest(operation=operation):
                provider = self.provider(operation, rest)
                with patch.dict(os.environ, CUCP_NATIVE_HOST=os.environ['CUCP_DIAGNOSTIC_PROVIDER_NATIVE']):
                    result = LegacyEffectSession().run('diagnostics', provider.startup(), Authority(), provider)
                self.assertEqual(result['exit'], 0)
                self.assertEqual(result['payload']['status'], 'ok')
                if operation == 'release-notes':
                    self.assertEqual(result['payload']['notes'][0]['version'], '1.0.0')


if __name__ == '__main__':
    unittest.main()
