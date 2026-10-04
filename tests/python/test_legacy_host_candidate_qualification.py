"""Candidate CI orchestration tests; no tracer/security changes or real desktop."""
import argparse
import base64
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'pcucp-next/packaging/qualify_legacy_host_candidate.py'
spec = importlib.util.spec_from_file_location('legacy_host_candidate_qualification', PATH)
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


def options(target='linux', **changes):
    return argparse.Namespace(candidate_only=True, target=target, require_process_trace=target == 'linux',
        require_windows_oracle=target == 'windows', **changes)


def report(target='linux', group='host'):
    contract = runner.contract()
    ids = sorted(name for rows in contract['groups'][group].values() for name in rows)
    skipped = contract['allowed_skips'][target] if group == 'host' else []
    return dict(schema='cucp.legacy-host-ci-tests/v1', target=target, group=group, test_ids=ids,
        tests_run=len(ids), success_ids=sorted(set(ids) - set(skipped)), failures=[], errors=[],
        skipped=[dict(id=name, reason='platform gate') for name in skipped], unexpected_successes=[], expected_failures=[])


class CandidateQualificationTests(unittest.TestCase):
    def test_explicit_platform_requirements_never_turn_missing_trace_into_success(self):
        with patch.object(runner.sys, 'platform', 'linux'):
            runner.check_options(options())
            for field in ('candidate_only', 'require_process_trace'):
                value = options(); setattr(value, field, False)
                with self.assertRaises(ValueError): runner.check_options(value)
            with self.assertRaises(ValueError): runner.check_options(options('windows'))
        with patch.object(runner.sys, 'platform', 'win32'):
            runner.check_options(options('windows'))
            with self.assertRaises(ValueError): runner.check_options(options('linux'))
            value = options('windows'); value.require_windows_oracle = False
            with self.assertRaises(ValueError): runner.check_options(value)

    def test_exact_cases_include_registry_refresh_and_original_oracle(self):
        cases = runner.contract()
        self.assertEqual(sum(map(len, cases['groups']['host'].values())), 66)
        self.assertEqual(sum(map(len, cases['groups']['windows-safeguards'].values())), 20)
        self.assertEqual(len(cases['groups']['host']['test_legacy_dispatch_refresh']), 4)
        self.assertEqual(cases['required_original_oracle_processes'], 4)
        self.assertEqual(cases['trace_modes'], ['root', 'typed-child', 'daemon'])
        for target in ('linux', 'windows'):
            runner.validate_suite_report(report(target), target=target, group='host')
        runner.validate_suite_report(report('windows', 'windows-safeguards'), target='windows', group='windows-safeguards')

    def test_missing_duplicate_extra_skip_failure_and_xfail_fail_closed(self):
        for target in ('linux', 'windows'):
            baseline = report(target)
            mutations = []
            value = copy.deepcopy(baseline); value['tests_run'] = 0; mutations.append(value)
            value = copy.deepcopy(baseline); value['test_ids'].pop(); mutations.append(value)
            value = copy.deepcopy(baseline); value['success_ids'].append(value['success_ids'][0]); mutations.append(value)
            value = copy.deepcopy(baseline); value['skipped'].append(dict(id=value['success_ids'].pop(), reason='not installed')); mutations.append(value)
            for name in ('failures', 'errors', 'expected_failures', 'unexpected_successes'):
                value = copy.deepcopy(baseline); value[name] = ['failure']; mutations.append(value)
            for value in mutations:
                with self.subTest(target=target), self.assertRaises(ValueError):
                    runner.validate_suite_report(value, target=target, group='host')

    def test_windows_startup_safeguards_cannot_skip(self):
        value = report('windows', 'windows-safeguards')
        value['skipped'].append(dict(id=value['success_ids'].pop(), reason='missing PowerShell'))
        with self.assertRaises(ValueError):
            runner.validate_suite_report(value, target='windows', group='windows-safeguards')

    def test_workflow_is_narrow_candidate_only_read_only_and_bounded(self):
        source = (ROOT / '.github/workflows/legacy-host-candidate.yml').read_text()
        self.assertIn('branches: [migration/python-csharp-runtime]', source)
        self.assertIn('workflow_dispatch:', source)
        self.assertIn('contents: read', source)
        self.assertNotIn('write-all', source)
        self.assertNotIn('pull_request:', source)
        self.assertNotIn('continue-on-error', source)
        self.assertNotIn('sudo', source)
        self.assertNotIn('apt-get', source)
        self.assertNotIn('sysctl', source)
        self.assertIn('--candidate-only --target linux --require-process-trace', source)
        self.assertIn('--candidate-only --target windows --require-windows-oracle', source)
        self.assertEqual(source.count('if-no-files-found: error'), 2)
        self.assertEqual(source.count('if: always()'), 2)
        self.assertEqual(source.count('fetch-depth: 0'), 2)
        self.assertEqual(len(re.findall(r'timeout-minutes: \d+', source)), 2)
        collector = PATH.read_text()
        self.assertIn("[tracer, '-f', '-q', '-e', 'trace=process', '-s', '4096', *root]", collector)
        self.assertNotIn("'-qq'", collector)
        for path in ('PcuCp.NativeHost/**', 'PcuCp.LegacyInteraction/**', 'PcuCp.LegacyPrecision/**',
                     'PcuCp.LegacyTaskPreset/LegacyTaskPresetKernel.cs', 'PcuCp.LegacyTaskForm/LegacyTaskFormKernel.cs',
                     'PcuCp.LegacySmartPlan/LegacySmartPlanKernel.cs', 'PcuCp.LegacyAppProfile/LegacyAppProfileKernel.cs',
                     'PcuCp.LegacyAppProfile/LegacyAppProfileController.cs'):
            self.assertIn('pcucp-next/dotnet/' + path, source)

    def test_ast_source_map_requires_every_frozen_ps_source_and_function(self):
        from pcucp_cli.legacy_dispatch import load_contract
        frozen = load_contract().metadata
        files = {row['path']: dict(path=row['path'], sha256=row['sha256'], functions=[])
                 for row in frozen['sources'] if row['path'].endswith('.ps1')}
        for row in frozen['extents']:
            if row['kind'] == 'function':
                files[row['path']]['functions'].append(dict(name=row['name'], parent_function=None, sha256=row['sha256']))
        value = dict(schema='cucp.migration-source-map/v1', encoding='utf-8-no-bom-lf', files=list(files.values()))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'source-map.json'; path.write_text(json.dumps(value))
            result = runner.validate_source_map(path)
            self.assertEqual((result['required_sources'], result['required_function_extents']), (7, 123))
            for mutation in ('file', 'extent', 'duplicate'):
                changed = copy.deepcopy(value)
                if mutation == 'file': changed['files'][0]['sha256'] = 'bad'
                elif mutation == 'extent':
                    next(row for row in changed['files'] if row['functions'])['functions'][0]['sha256'] = 'bad'
                else: changed['files'].append(changed['files'][0])
                path.write_text(json.dumps(changed))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    runner.validate_source_map(path)

    def test_failed_bounded_capture_is_persisted_before_assertion(self):
        with tempfile.TemporaryDirectory(prefix='host-ci-failure-evidence-') as root:
            with self.assertRaises(AssertionError):
                runner._command([sys.executable, '-c', 'import sys;sys.stderr.write("owned failure");sys.exit(9)'],
                    Path(root), 'owned-failure', dict(__import__('os').environ), timeout=10)
            files = list(Path(root).glob('*.json'))
            self.assertEqual(len(files), 1)
            value = json.loads(files[0].read_text())
            self.assertEqual(value['exit_code'], 9)
            self.assertEqual(files[0].with_suffix('.stderr.bin').read_bytes(), b'owned failure')

    def make_processes(self, root, target='linux'):
        for index in range(10):
            argv = ['python', '-m', 'pcucp_cli.legacy_host_entry']
            argv += ['--typed-child'] if index == 1 else ['--', 'macro', 'daemon', 'serve'] if index == 2 else ['--', 'macro', 'release-notes']
            self.write_process(root / f'entry-{index}.json', argv)
        if target == 'windows':
            outputs = ['ok release-notes notes=1 versions=2.3.4\n', 'ok release-notes notes=1 versions=1.0.0\n',
                       'ok release-notes notes=2 versions=2.3.4,1.0.0\n', 'ok release-notes notes=0 versions=\n']
            for index, output in enumerate(outputs):
                self.write_process(root / f'oracle-{index}.json', ['powershell.exe', '-File', 'oracle.ps1'], output.encode())

    def write_process(self, path, argv, out=b'owned\n'):
        err = b''
        value = dict(argv=argv, exit_code=0, running=False, launch_error=None, timed_out=False,
            kill_error=None, drain_incomplete=False, stdin_error=None, read_errors={},
            bytes_observed=dict(stdout=len(out), stderr=0), truncated=dict(stdout=False, stderr=False),
            stdout_base64=base64.b64encode(out).decode(), stderr_base64='')
        path.write_text(json.dumps(value)); path.with_suffix('.stdout.bin').write_bytes(out); path.with_suffix('.stderr.bin').write_bytes(err)

    def test_raw_process_evidence_requires_all_entry_modes_and_exact_oracles(self):
        for target in ('linux', 'windows'):
            with tempfile.TemporaryDirectory() as root:
                root = Path(root); self.make_processes(root, target)
                result = runner.validate_process_artifacts(root, target)
                self.assertEqual(result['modes'], ['daemon', 'root', 'typed-child'])
                self.assertEqual(result['original_oracle_count'], 4 if target == 'windows' else 0)
                self.write_process(root / 'entry-1.json', ['python', '-m', 'pcucp_cli.legacy_host_entry', '--', 'macro', 'release-notes'])
                with self.assertRaises(ValueError): runner.validate_process_artifacts(root, target)

    def test_raw_process_tamper_timeout_and_oracle_vacuity_are_rejected(self):
        for mutation in ('bytes', 'timed_out', 'oracle'):
            with tempfile.TemporaryDirectory() as root:
                root = Path(root); self.make_processes(root, 'windows')
                if mutation == 'bytes': (root / 'entry-0.stdout.bin').write_bytes(b'changed')
                elif mutation == 'timed_out':
                    p = root / 'entry-0.json'; value = json.loads(p.read_text()); value['timed_out'] = True; p.write_text(json.dumps(value))
                else: self.write_process(root / 'oracle-0.json', ['powershell.exe', '-File', 'oracle.ps1'])
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    runner.validate_process_artifacts(root, 'windows')


if __name__ == '__main__':
    unittest.main()
