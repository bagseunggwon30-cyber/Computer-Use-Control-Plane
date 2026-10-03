"""Failure evidence is durable before qualification assertions run."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import legacy_diagnostic_evidence as evidence
import test_legacy_diagnostics_retained as retained
from test_legacy_diagnostics_adapters import UNCERTAIN_MESSAGE


class DiagnosticEvidenceTests(unittest.TestCase):
    def capture(self, root, routes=('pure',)):
        with contextlib.redirect_stdout(io.StringIO()):
            return evidence.DiagnosticEvidence(root, [dict(case_id='inert/한국어')], routes)

    def manifest(self, capture):
        return json.loads((capture.directory / 'manifest.json').read_text(encoding='utf-8'))

    def test_nonzero_decode_json_shape_and_count_failures_keep_original_bytes(self):
        scenarios = [(7, b'partial\xff\r\n', AssertionError), (0, b'\xff', UnicodeDecodeError),
            (0, b'{broken', json.JSONDecodeError), (0, b'{}', AssertionError), (0, b'[]', AssertionError)]
        for code, stdout, exception in scenarios:
            with self.subTest(code=code, stdout=stdout), tempfile.TemporaryDirectory() as temp:
                capture = self.capture(temp)
                stderr = 'inert stderr 한국어\r\n'.encode()
                with patch.object(evidence.subprocess, 'run', return_value=subprocess.CompletedProcess(['inert'], code, stdout, stderr)) as run:
                    process = capture.run('pure', ['inert'], case_ids=['inert/한국어'], timeout=1)
                run.assert_called_once()
                self.assertEqual((capture.directory / 'pure.stdout').read_bytes(), stdout)
                self.assertEqual((capture.directory / 'pure.stderr').read_bytes(), stderr)
                self.assertEqual(self.manifest(capture)['routes']['pure']['returncode'], code)
                with self.assertRaises(exception):
                    capture.rows(self, 'pure', process, 1)
                capture.finish()
                manifest = self.manifest(capture)
                self.assertEqual(manifest['routes']['pure']['validation'], 'failed')
                self.assertFalse(manifest['qualification_passed'])
                self.assertEqual(manifest['case_ids'], ['inert/한국어'])

    def test_timeout_and_launch_errors_keep_partial_streams_and_prior_routes_without_retry(self):
        for error, status, stdout, stderr in (
            (subprocess.TimeoutExpired(['inert'], 2, output=b'partial\x00\xff', stderr=b'timeout\r\n'), 'timeout', b'partial\x00\xff', b'timeout\r\n'),
            (FileNotFoundError('inert executable missing'), 'launch_error', b'', b''),
        ):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                capture = self.capture(temp, ('original-file', 'pure', 'candidate-file'))
                with patch.object(evidence.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess(['inert'], 0, b'[{}]', b'first stderr'), error]) as run:
                    process = capture.run('original-file', ['inert'], timeout=1)
                    capture.rows(self, 'original-file', process, 1)
                    with self.assertRaises(type(error)):
                        capture.run('pure', ['inert'], timeout=2)
                self.assertEqual(run.call_count, 2)
                capture.finish()
                manifest = self.manifest(capture)
                self.assertEqual(manifest['routes']['pure']['status'], status)
                self.assertIsNone(manifest['routes']['pure']['returncode'])
                self.assertFalse(manifest['routes']['pure']['automatic_retry'])
                self.assertEqual((capture.directory / 'pure.stdout').read_bytes(), stdout)
                self.assertEqual((capture.directory / 'pure.stderr').read_bytes(), stderr)
                self.assertEqual((capture.directory / 'original-file.stdout').read_bytes(), b'[{}]')
                self.assertEqual(manifest['unattempted_routes'], ['candidate-file'])
                self.assertFalse(manifest['qualification_passed'])

    def test_output_limit_is_explicit_and_never_parses_truncated_data(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(evidence, 'MAX_STDOUT', 4), patch.object(evidence, 'MAX_STDERR', 3):
            capture = self.capture(temp)
            with patch.object(evidence.subprocess, 'run', return_value=subprocess.CompletedProcess(['inert'], 0, b'abcdefgh', b'12345')):
                with self.assertRaisesRegex(AssertionError, 'evidence bound'):
                    capture.run('pure', ['inert'], timeout=1)
            manifest = self.manifest(capture)
            record = manifest['routes']['pure']
            self.assertEqual(manifest['limits']['stdout_bytes'], 4)
            self.assertEqual(manifest['limits']['stderr_bytes'], 3)
            self.assertEqual(record['status'], 'output_limit_exceeded')
            self.assertEqual((capture.directory / 'pure.stdout').read_bytes(), b'abcd')
            self.assertEqual((capture.directory / 'pure.stderr').read_bytes(), b'123')
            self.assertEqual(record['stdout'], dict(file='pure.stdout', bytes=8, saved_bytes=4,
                sha256=hashlib.sha256(b'abcdefgh').hexdigest(), truncated=True))
            self.assertEqual(record['stderr']['bytes'], 5)
            self.assertEqual(record['validation'], 'failed')

    def test_unique_directories_fixed_filenames_and_one_attempt_preserve_previous_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            one, two = self.capture(temp), self.capture(temp)
            self.assertNotEqual(one.directory, two.directory)
            with patch.object(evidence.subprocess, 'run', return_value=subprocess.CompletedProcess(['inert'], 0, b'[]', b'')) as run:
                one.run('pure', ['inert'], timeout=1)
                with self.assertRaises(ValueError):
                    one.run('pure', ['inert'], timeout=1)
                with self.assertRaises(ValueError):
                    two.run('../outside', ['inert'], timeout=1)
                run.assert_called_once()
            self.assertEqual((one.directory / 'pure.stdout').read_bytes(), b'[]')
            self.assertFalse((Path(temp) / 'outside.stdout').exists())
            self.assertEqual(self.manifest(two)['routes'], {})

    def test_unittest_subtest_mismatch_is_saved_before_suppression(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = self.capture(temp, ())
            class Probe(unittest.TestCase):
                def runTest(self):
                    self.addCleanup(capture.finish)
                    with self.subTest(case='inert'), capture.comparison('inert', 'actual-candidate'):
                        self.assertEqual({'complete': 'original'}, {'complete': 'candidate'})
                    capture.complete()
            result = unittest.TestResult()
            Probe().run(result)
            self.assertEqual(len(result.failures), 1)
            self.assertEqual(result.errors, [])
            manifest = self.manifest(capture)
            self.assertTrue(manifest['comparison_completed'])
            self.assertFalse(manifest['qualification_passed'])
            self.assertEqual(manifest['comparisons'][0]['status'], 'failed')
            self.assertEqual(manifest['comparisons'][0]['error']['type'], 'AssertionError')

    def run_real_method(self, root, *, failure=None, mismatch=False):
        host = root / 'inert-host.dll'
        host.write_bytes(b'inert host identity')
        fixtures = [dict(case_id='inert/audit', operation='audit-summary', rest=[], replies=[]),
                    dict(case_id='inert/benchmark', operation='benchmark', rest=[], replies=[dict(throw='inert failure')])]
        effect = dict(kind='Native', name='', argv=['-Action', 'windows'], data=None)
        wire_empty = dict(kind='array', items=[])
        # The scalar tag preserves this synthetic trace object for the decoder;
        # actual transport framing remains covered by the unchanged wire suites.
        wire_native = dict(kind='array', items=[dict(kind='scalar', value=effect)])
        original = [dict(state='complete', payload=None, exit=0, console='original audit\r\n', effects=wire_empty, consumed=0),
                    dict(state='complete', payload=None, exit=0, console='original benchmark\r\n', effects=wire_native, consumed=1)]
        pure = [dict(state='complete', payload=None, exit=1 if mismatch else 0, effects=[], consumed=0),
                dict(state='complete', payload=None, exit=0, effects=[effect], consumed=1)]
        uncertain = dict(state='error', error=UNCERTAIN_MESSAGE, console='', effects=wire_native, consumed=1)
        calls = []
        def run(argv, **kwargs):
            if argv[0] == 'git':
                route = 'git-head' if argv[1] == 'rev-parse' else 'git-status' if argv[1] == 'status' else 'pinned-source'
                stdout = b'a' * 40 + b'\n' if route == 'git-head' else b'' if route == 'git-status' else b'inert pinned source\r\n'
            elif '--info' in argv:
                route, stdout = 'dotnet-info', b'inert runtime info\r\n'
            elif 'build' in argv:
                route, stdout = 'pure-build', b'inert build stdout\r\n'
            elif '--fixtures' in argv:
                route, stdout = 'pure', json.dumps(pure).encode()
            else:
                file_group = 'file-oracle.ps1' in argv[argv.index('-File') + 1]
                name = 'production' if '-ProductionEntry' in argv else 'candidate' if '-AdapterSource' in argv else 'original'
                route = name + ('-file' if file_group else '-runtime')
                stdout = json.dumps([original[0] if file_group else uncertain if name == 'candidate' else original[1]]).encode()
            calls.append(route)
            if failure == route:
                raise FileNotFoundError('inert requested launch failure')
            return subprocess.CompletedProcess(argv, 0, stdout, (route + ' stderr\r\n').encode())
        class Probe(unittest.TestCase):
            def runTest(self):
                retained.RetainedDiagnosticWindowsTests.test_pinned_original_current_original_pure_candidate_and_actual_candidate(self)
        result = unittest.TestResult()
        with patch.object(retained, 'retained_candidate_cases', return_value=fixtures), \
             patch.object(retained.shutil, 'which', side_effect=lambda name: 'inert-' + name), \
             patch.object(evidence.subprocess, 'run', side_effect=run), \
             patch.dict(os.environ, {evidence.CAPTURE_ENV: str(root / 'artifacts'), 'CUCP_DIAGNOSTICS_TEST_HOST': str(host)}, clear=False), \
             contextlib.redirect_stdout(io.StringIO()):
            Probe().run(result)
        directories = list((root / 'artifacts').iterdir())
        self.assertEqual(len(directories), 1)
        directory = directories[0]
        return result, directory, json.loads((directory / 'manifest.json').read_text()), calls

    def test_real_four_route_method_keeps_every_raw_result_after_temporary_cleanup_and_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            result, directory, manifest, calls = self.run_real_method(Path(temp), mismatch=True)
            self.assertEqual(len(result.failures), 1, result.failures)
            self.assertEqual(result.errors, [])
            self.assertEqual(len(calls), 12)
            self.assertEqual(set(manifest['routes']), set(manifest['planned_routes']))
            self.assertFalse(manifest['qualification_passed'])
            self.assertTrue(manifest['comparison_completed'])
            self.assertEqual([c['route'] for c in manifest['comparisons'] if c['status'] == 'failed'], ['pure-candidate'])
            self.assertEqual(manifest['routes']['pure']['case_ids'], ['inert/audit', 'inert/benchmark'])
            raw_input = (directory / 'pure.stdin').read_bytes()
            self.assertEqual(manifest['routes']['pure']['stdin']['sha256'], hashlib.sha256(raw_input).hexdigest())
            self.assertEqual(manifest['routes']['pure']['stdin']['bytes'], len(raw_input))
            self.assertEqual([f['case_id'] for f in json.loads(raw_input)], ['inert/audit', 'inert/benchmark'])
            for route in calls:
                self.assertTrue((directory / (route + '.stdout')).is_file())
                self.assertEqual((directory / (route + '.stderr')).read_bytes(), (route + ' stderr\r\n').encode())
            self.assertEqual(manifest['routes']['candidate-file']['metadata']['case_indices'], [0])
            self.assertEqual(manifest['routes']['candidate-runtime']['metadata']['case_indices'], [1])
            self.assertFalse(Path(manifest['provenance']['pinned_source']['path']).exists())
            self.assertEqual((directory / 'pinned-source.stdout').read_bytes(), b'inert pinned source\r\n')
            self.assertEqual(manifest['provenance']['pinned_source']['sha256'], hashlib.sha256(b'inert pinned source\r\n').hexdigest())
            self.assertEqual(manifest['provenance']['git_head'], 'a' * 40)
            self.assertIn('python_version', manifest['provenance'])

    def test_real_method_preserves_build_pure_and_grouped_launch_failures(self):
        for route in ('pure-build', 'pure', 'pinned-source', 'production-file', 'candidate-runtime'):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp:
                result, directory, manifest, calls = self.run_real_method(Path(temp), failure=route)
                self.assertEqual(len(result.errors), 1)
                self.assertEqual(result.failures, [])
                self.assertEqual(calls[-1], route)
                self.assertEqual(calls.count(route), 1)
                self.assertEqual(manifest['routes'][route]['status'], 'launch_error')
                self.assertFalse(manifest['qualification_passed'])
                self.assertFalse(manifest['comparison_completed'])
                self.assertEqual((directory / (route + '.stdout')).read_bytes(), b'')
                self.assertEqual(manifest['case_ids'], ['inert/audit', 'inert/benchmark'])
                self.assertEqual(set(manifest['unattempted_routes']), set(manifest['planned_routes']) - set(calls))
                self.assertEqual([c['route'] for c in manifest['comparisons'] if c['status'] == 'failed'], ['all-routes'])


if __name__ == '__main__':
    unittest.main()
