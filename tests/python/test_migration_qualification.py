"""Qualification selection must never turn a requested gate into an empty pass."""
import importlib.util
import contextlib
import io
from unittest.mock import patch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("qualification", ROOT / "pcucp-next/packaging/migration_qualification.py")
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


class QualificationSelectionTests(unittest.TestCase):
    def test_logged_diagnostics_capture_stays_under_family_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp) / 'logs'
            calls = []
            def capture(argv, **kwargs):
                calls.append((argv, dict(kwargs['env']), kwargs['log_path']))
            with patch.object(qualification, 'run_logged', side_effect=capture):
                qualification.run_family('diagnostics', log_dir=logs)
            self.assertTrue(any('test_legacy_diagnostics*.py' in argv for argv, _, _ in calls))
            for _, env, log_path in calls:
                self.assertEqual(env['CUCP_DIAGNOSTICS_RETAINED_CAPTURE_DIR'], str(logs / 'retained-diagnostics'))
                self.assertEqual(log_path.parent, logs)

    def test_logged_failure_preserves_all_bytes_and_exit_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "logs/01.log"
            output = io.StringIO()
            command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x'*100000+b'\\xffFAILURE\\n'); sys.exit(7)"]
            with contextlib.redirect_stdout(output), self.assertRaises(subprocess.CalledProcessError) as caught:
                qualification.run_logged(command, cwd=root, env=dict(os.environ), log_path=log)
            self.assertEqual(caught.exception.returncode, 7)
            self.assertEqual(log.read_bytes(), b"x" * 100000 + b"\xffFAILURE\n")
            self.assertIn("FAILURE", output.getvalue())
            self.assertIn("full output is in the log artifact", output.getvalue())
            self.assertLess(len(output.getvalue()), 67000)

    def test_legacy_console_cannot_mask_failure_or_change_artifact_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);log=root/'log.txt';console_bytes=io.BytesIO()
            console=io.TextIOWrapper(console_bytes,encoding='cp1252',errors='strict')
            payload='한글 😀\n'.encode('utf-8')
            command=[sys.executable,'-c',f'import os; os.write(1,{payload!r}); raise SystemExit(7)']
            with patch.object(sys,'stdout',console), self.assertRaises(subprocess.CalledProcessError) as caught:
                qualification.run_logged(command,cwd=root,env=dict(os.environ),log_path=log)
            console.flush()
            self.assertEqual(caught.exception.returncode,7)
            self.assertEqual(log.read_bytes(),payload)
            self.assertIn(b'\\ud55c\\uae00',console_bytes.getvalue())
            self.assertIn(b'\\U0001f600',console_bytes.getvalue())
            console.close()

    def test_logged_success_combines_stdout_and_stderr_without_losing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "01.log"
            command = [sys.executable, "-c", "import os; os.write(1,b'out\\n'); os.write(2,b'err\\n')"]
            with contextlib.redirect_stdout(io.StringIO()):
                qualification.run_logged(command, cwd=root, env=dict(os.environ), log_path=log)
            self.assertEqual(log.read_bytes(), b"out\nerr\n")

    def test_default_runs_all_families_and_full_cannot_be_weakened_by_focus(self):
        families = list(qualification.FAMILIES)
        self.assertEqual(qualification.select_scope("", "Implement batch"), (families, False))
        self.assertEqual(qualification.select_scope("", "[focus cdp] [full regression] Verify batch"), (families, True))
        self.assertEqual(qualification.select_scope("full", "[focus cdp]"), (families, True))
        self.assertEqual(qualification.select_scope("", "[focus next-batch] Qualify candidates"),
                         (list(qualification.NEXT_BATCH), False))

    def test_only_a_single_known_first_line_scope_is_accepted(self):
        for family in (*qualification.FAMILIES, "foundation"):
            self.assertEqual(qualification.select_scope("", f"[focus {family}] Fix fixture"), ([family], False))
        self.assertEqual(qualification.select_scope("", "Ordinary title\n[focus cdp]"), (list(qualification.FAMILIES), False))
        for explicit, message in [("none", ""), ("", "[focus unknown]"), ("", "[focus cdp] [focus precision]")]:
            with self.assertRaises(ValueError):
                qualification.select_scope(explicit, message)

    def test_adapter_manifest_rejects_unknown_duplicate_or_nonstring_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".github").mkdir()
            path = root / ".github/migration-adapters.json"
            for data in [[], {"test_adapters": ["unknown"]}, {"test_adapters": [True]},
                         {"test_adapters": ["cdp", "cdp"]}, {"test_adapters": [], "extra": True}]:
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    qualification.enabled_adapters(root)
            path.write_text('{"test_adapters":["execution","precision","cdp"]}')
            self.assertEqual(qualification.enabled_adapters(root), {"execution", "precision", "cdp"})

    def test_full_suite_discovers_any_staged_family_implementation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(qualification.available_families(root), [])
            (root / "pcucp-next/dotnet/PcuCp.LegacyPrecision").mkdir(parents=True)
            self.assertEqual(qualification.available_families(root), ["precision"])
            path = root / "pcucp-next/python/pcucp_cli/legacy_cdp.py"
            path.parent.mkdir(parents=True)
            path.write_text("# fixture")
            self.assertEqual(qualification.available_families(root), ["precision", "cdp"])
            for name in ("PcuCp.LegacyInteraction", "PcuCp.LegacyDiagnostics", "PcuCp.LegacyImages"):
                (root / "pcucp-next/dotnet" / name).mkdir()
            (root / "pcucp-next/dotnet/PcuCp.LegacyImages/FileOcr.cs").write_text("// fixture")
            self.assertEqual(qualification.available_families(root),
                             ["precision", "cdp", "interaction", "diagnostics", "file-images"])

    def test_foundation_gate_keeps_inventory_and_adds_exact_workflow_candidate_suite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('tests/python', 'pcucp-next/dotnet/PcuCp.NativeHost', *(
                    'pcucp-next/dotnet/' + p for p in qualification.PROJECTS['foundation'])):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / 'tests/python/test_migration_inventory.py').write_text('# fixture')
            calls = []
            def capture(argv, **kwargs): calls.append((argv, dict(kwargs['env'])))
            with patch.object(qualification, 'ROOT', root), patch.object(qualification.subprocess, 'run', side_effect=capture), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'test_legacy_workflow_parity.py'):
                    qualification.run_family('foundation')
                self.assertEqual(calls, [])
                for index, name in enumerate(qualification.REQUIRED_FOUNDATION_TESTS):
                    with self.assertRaisesRegex(ValueError, name):
                        qualification.run_family('foundation')
                    self.assertEqual(calls, [])
                    (root / 'tests/python' / name).write_text('# fixture')
                qualification.run_family('foundation')
            projects = [args[args.index('--project') + 1] for args, _ in calls if '--project' in args]
            self.assertEqual(projects, [str(root / 'pcucp-next/dotnet' / name)
                                       for name in qualification.PROJECTS['foundation']])
            self.assertIn(str(root / 'pcucp-next/dotnet/PcuCp.LegacyWorkflow.ContractTests'), projects)
            suites = [args[args.index('-p') + 1] for args, _ in calls if '-p' in args]
            self.assertEqual(suites, ['test_migration_inventory.py', 'test_legacy_workflow*.py'])

    def make_foundation_root(self, root):
        for name in ('tests/python', 'pcucp-next/dotnet/PcuCp.NativeHost', *(
                'pcucp-next/dotnet/' + p for p in qualification.PROJECTS['foundation'])):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in ('test_migration_inventory.py', *qualification.REQUIRED_FOUNDATION_TESTS):
            (root / 'tests/python' / name).write_text('# fixture')

    def test_foundation_requires_each_current_suite_before_any_subprocess(self):
        required = {
            'test_legacy_workflow_parity.py', 'test_legacy_workflow_boundaries.py',
            'test_legacy_workflow_diagnostics.py', 'test_legacy_workflow_embedded_fixtures.py',
            'test_legacy_workflow_observed_diagnostics.py', 'test_legacy_workflow_evidence.py',
        }
        self.assertEqual(set(qualification.REQUIRED_FOUNDATION_TESTS), required)
        for missing in ('test_migration_inventory.py', *sorted(required)):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.make_foundation_root(root)
                (root / 'tests/python' / missing).unlink()
                with patch.object(qualification, 'ROOT', root), \
                     patch.object(qualification.subprocess, 'run') as run:
                    with self.assertRaisesRegex(ValueError, re.escape(missing)):
                        qualification.run_family('foundation', log_dir=root / 'logs')
                    run.assert_not_called()

    def test_full_workflow_uses_shared_foundation_gate_and_always_uploads_evidence(self):
        core = (ROOT / '.github/workflows/core.yml').read_text(encoding='utf-8')
        job = core.split('  windows-contracts:\n', 1)[1].split('  windows-profile-candidate:\n', 1)[0]
        step = job.split('      - name: Workflow exact parsed-plan and candidate qualification (parser retained)\n', 1)[1].split('      - ', 1)[0]
        self.assertIn("if: ${{ !cancelled() && steps.build_native.outcome == 'success' }}", step)
        self.assertIn('shell: pwsh', step)
        host = "$env:CUCP_NATIVE_TEST_HOST = (Resolve-Path 'pcucp-next/dotnet/PcuCp.NativeHost/bin/Release/net8.0-windows10.0.19041.0/PcuCp.NativeHost.dll').Path"
        command = 'python pcucp-next/packaging/migration_qualification.py run --family foundation --log-dir .migration-logs/foundation-full'
        self.assertIn(host, step)
        self.assertIn(command, step)
        self.assertLess(step.index(host), step.index(command))
        self.assertIn('if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }', step)
        self.assertNotIn('-p test_legacy_workflow_parity.py', step)
        upload = job.split('      - name: Retain full foundation qualification evidence\n', 1)[1].split('      - ', 1)[0]
        for setting in ('uses: actions/upload-artifact@v4', 'if: always()',
                        'name: qualification-foundation-full', 'path: .migration-logs/foundation-full',
                        'include-hidden-files: true', 'retention-days: 7'):
            self.assertIn(setting, upload)
        focused = (ROOT / '.github/workflows/migration-qualification.yml').read_text(encoding='utf-8')
        full = focused.split('  full-regression:\n', 1)[1]
        self.assertIn("if: needs.scope.outputs.full == 'true'", full)
        self.assertIn('uses: ./.github/workflows/core.yml', full)
        family = focused.split('  windows-family:\n', 1)[1].split('  cdp-browser:\n', 1)[0]
        self.assertIn("if: needs.scope.outputs.full != 'true'", family)
        for source in (core, focused):
            self.assertNotIn('CUCP_REQUIRE_WORKFLOW_PARSER_PARITY', source)
            self.assertNotIn('CUCP_REQUIRE_WORKFLOW_DIAGNOSTIC_PARITY', source)

    def test_logged_foundation_selects_all_suites_and_preserves_native_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_foundation_root(root)
            # The wildcard must also include future workflow modules.
            future = 'test_legacy_workflow_future.py'
            (root / 'tests/python' / future).write_text('# fixture')
            host = str(root / 'already-built native host.dll')
            logs = root / 'logs'
            calls = []
            def capture(argv, **kwargs):
                calls.append((argv, dict(kwargs['env']), kwargs['log_path']))
            with patch.object(qualification, 'ROOT', root), \
                 patch.object(qualification, 'run_logged', side_effect=capture), \
                 patch.dict(os.environ, {'CUCP_NATIVE_TEST_HOST': host}):
                qualification.run_family('foundation', log_dir=logs)
            self.assertEqual(calls[0][0], ['dotnet', 'build', str(root / 'pcucp-next/dotnet/PcuCp.NativeHost'), '-c', 'Release', '-warnaserror'])
            projects = [Path(argv[argv.index('--project') + 1]).name for argv, _, _ in calls if '--project' in argv]
            self.assertEqual(projects, ['PcuCp.LegacyPure.ContractTests', 'PcuCp.LegacyTaskForm.ContractTests', 'PcuCp.LegacyWorkflow.ContractTests'])
            patterns = [argv[argv.index('-p') + 1] for argv, _, _ in calls if '-p' in argv]
            self.assertEqual(patterns, ['test_migration_inventory.py', 'test_legacy_workflow*.py'])
            selected = {path.name for pattern in patterns for path in (root / 'tests/python').glob(pattern)}
            self.assertEqual(selected, {'test_migration_inventory.py', future, *qualification.REQUIRED_FOUNDATION_TESTS})
            for index, (_, env, log_path) in enumerate(calls, 1):
                self.assertEqual(env['CUCP_NATIVE_TEST_HOST'], host)
                self.assertEqual(env['CUCP_WORKFLOW_DIAGNOSTIC_CAPTURE'], str(logs / 'workflow-parser-raw-diagnostics.json'))
                self.assertEqual(env['PYTHONPATH'], str(root / 'pcucp-next/python'))
                self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')
                self.assertEqual(log_path, logs / f'{index:02d}.log')
            self.assertEqual(calls[-1][0][-2:], ['-OutputPath', str(logs / 'source-map.json')])

    def test_foundation_failures_keep_complete_logs_raw_capture_and_source_map(self):
        # Build/contract failures must retain source provenance too. A raw
        # capture exists only after the diagnostic suite actually runs.
        for fail_at in (1, 2, 5, 6):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.make_foundation_root(root)
                logs = root / 'logs'
                payload = b'x' * 100000 + b'\xff qualification output\n'
                raw = b'{"comparison_completed":false,"cases":[{"id":"retained"}]}\r\n'
                source_map = b'{"schema":"cucp.migration-source-map/v1","files":[]}\n'
                calls = []
                def capture(argv, **kwargs):
                    calls.append(argv)
                    kwargs['stdout'].write(payload)
                    if 'test_legacy_workflow*.py' in argv:
                        Path(kwargs['env']['CUCP_WORKFLOW_DIAGNOSTIC_CAPTURE']).write_bytes(raw)
                    if '-OutputPath' in argv:
                        Path(argv[argv.index('-OutputPath') + 1]).write_bytes(source_map)
                    return subprocess.CompletedProcess(argv, 7 if len(calls) == fail_at else 0)
                with patch.object(qualification, 'ROOT', root), \
                     patch.object(qualification.subprocess, 'run', side_effect=capture), \
                     contextlib.redirect_stdout(io.StringIO()), \
                     self.assertRaises(subprocess.CalledProcessError) as caught:
                    qualification.run_family('foundation', log_dir=logs)
                self.assertEqual(caught.exception.returncode, 7)
                self.assertEqual(len(calls), fail_at + 1)
                self.assertEqual(calls[-1][0], 'powershell.exe')
                self.assertIn(str(root / 'tests/fixtures/migration-source-map.ps1'), calls[-1])
                self.assertEqual((logs / 'source-map.json').read_bytes(), source_map)
                self.assertEqual(len(list(logs.glob('*.log'))), len(calls))
                for path in logs.glob('*.log'):
                    self.assertEqual(path.read_bytes(), payload)
                raw_path = logs / 'workflow-parser-raw-diagnostics.json'
                if fail_at == 6:
                    self.assertEqual(raw_path.read_bytes(), raw)
                else:
                    self.assertFalse(raw_path.exists())

    def test_file_images_requires_and_runs_both_exact_suites_with_matching_dll(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("tests/python", "tests/fixtures", ".github", "pcucp-next/packaging",
                         "pcucp-next/dotnet/PcuCp.NativeHost", *(
                         "pcucp-next/dotnet/" + p for p in qualification.PROJECTS["file-images"])):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / ".github/migration-adapters.json").write_text('{"test_adapters":[]}')
            (root / "tests/fixtures/legacy-file-images-adapter.ps1").write_text("# fixture")
            publisher = root / "pcucp-next/packaging/publish_legacy_images.py"
            publisher.write_text("# fixture")
            (root / "tests/python/test_legacy_images.py").write_text("# fixture")
            calls = []
            with patch.object(qualification, "ROOT", root), patch.object(qualification.subprocess, "run",
                    side_effect=lambda argv, **kw: calls.append((argv, dict(kw['env'])))), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'test_legacy_file_ocr.py'):
                    qualification.run_family('file-images')
                self.assertEqual(calls, [])
                (root / 'tests/python/test_legacy_file_ocr.py').write_text('# fixture')
                qualification.run_family('file-images')
            self.assertIn([sys.executable, str(publisher)], [args for args, _ in calls])
            suites = [(args, env) for args, env in calls if '-m' in args and 'unittest' in args]
            self.assertEqual([args[args.index('-p')+1] for args, _ in suites],
                             ['test_legacy_images.py', 'test_legacy_file_ocr.py'])
            for _, env in suites:
                self.assertEqual(env['CUCP_LEGACY_IMAGES_TEST_DLL'],
                                 str(root / 'pcucp-next/bin/legacy/PcuCp.LegacyImages.dll'))
                self.assertEqual(env['CUCP_LEGACY_IMAGES_ADAPTER_SOURCE'],
                                 str(root / 'tests/fixtures/legacy-file-images-adapter.ps1'))
            # Promotion must exercise the installed body. A stale caller
            # override cannot keep a deleted draft passing in its place.
            (root / 'scripts').mkdir()
            production = root / 'scripts/cucp-native-helper.ps1'
            production.write_text('# production adapter')
            (root / '.github/migration-adapters.json').write_text('{"test_adapters":["file-images"]}')
            (root / 'tests/fixtures/legacy-file-images-adapter.ps1').unlink()
            calls.clear()
            with patch.object(qualification, 'ROOT', root), patch.object(qualification.subprocess, 'run',
                    side_effect=lambda argv, **kw: calls.append((argv, dict(kw['env'])))), \
                    patch.dict(os.environ, {'CUCP_LEGACY_IMAGES_ADAPTER_SOURCE':'stale-draft.ps1'}), \
                    contextlib.redirect_stdout(io.StringIO()):
                qualification.run_family('file-images')
                suites = [(args, env) for args, env in calls if '-m' in args and 'unittest' in args]
                self.assertEqual(len(suites), 2)
                for _, env in suites:
                    self.assertEqual(env['CUCP_LEGACY_IMAGES_ADAPTER_SOURCE'], str(production))
                production.unlink()
                with self.assertRaisesRegex(ValueError, 'Missing promoted file-images adapter source'):
                    qualification.run_family('file-images')

    def test_candidate_kernel_gate_cannot_claim_adapter_retirement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('tests/python', '.github', 'pcucp-next/dotnet/PcuCp.NativeHost', *(
                    'pcucp-next/dotnet/' + p for p in qualification.PROJECTS['interaction'])):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / '.github/migration-adapters.json').write_text('{"test_adapters":[]}')
            (root / 'tests/python/test_legacy_interaction_fixture.py').write_text('# fixture')
            output = io.StringIO()
            with patch.object(qualification, 'ROOT', root), patch.object(qualification.subprocess, 'run'), \
                    patch.object(qualification, 'CANDIDATE_ONLY', frozenset({'interaction'})), \
                    patch.dict(os.environ, {'GITHUB_STEP_SUMMARY':str(root / 'summary.md')}), \
                    contextlib.redirect_stdout(output):
                qualification.run_family('interaction')
            self.assertIn('CANDIDATE ONLY', output.getvalue())
            self.assertIn('retirement are NOT qualified', output.getvalue())
            self.assertIn('CANDIDATE ONLY', (root / 'summary.md').read_text())
            # Removing the candidate-only declaration is insufficient: the
            # next stage must actually provide the production-boundary suite.
            with patch.object(qualification, 'ROOT', root), patch.object(qualification, 'CANDIDATE_ONLY', frozenset()):
                with self.assertRaisesRegex(ValueError, 'Missing exact adapter tests'):
                    qualification.run_family('interaction')


    def test_new_family_gates_require_actual_adapter_suite_and_matching_host(self):
        for family in ('interaction', 'diagnostics'):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                for name in ('tests/python', 'scripts', '.github', 'pcucp-next/dotnet/PcuCp.NativeHost', *(
                        'pcucp-next/dotnet/'+p for p in qualification.PROJECTS[family])):
                    (root/name).mkdir(parents=True,exist_ok=True)
                (root/'.github/migration-adapters.json').write_text('{"test_adapters":[]}')
                (root/f'tests/python/test_legacy_{family}_parity.py').write_text('# fixture')
                calls=[]
                def capture(argv,**kw):calls.append((argv,dict(kw['env'])))
                with patch.object(qualification,'ROOT',root), patch.object(qualification.subprocess,'run',side_effect=capture), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError,'Missing exact adapter tests'):
                        qualification.run_family(family)
                    self.assertEqual(calls,[])
                    (root/'tests/python'/qualification.REQUIRED_ADAPTER_TESTS[family]).write_text('# actual adapter fixture')
                    with self.assertRaisesRegex(ValueError,'Missing exact '+family+' adapter draft'):
                        qualification.run_family(family)
                    (root/qualification.DRAFT_ADAPTERS[family]).write_text('# actual draft')
                    qualification.run_family(family)
                host=str(root/'pcucp-next/dotnet/PcuCp.NativeHost/bin/Release/net8.0-windows10.0.19041.0/PcuCp.NativeHost.dll')
                self.assertEqual(calls[-1][1]['CUCP_INTERACTION_TEST_HOST' if family=='interaction' else 'CUCP_DIAGNOSTICS_TEST_HOST'],host)
                self.assertEqual(calls[-1][1]['PYTHONIOENCODING'],'utf-8')
                self.assertTrue(any('PcuCp.LegacyExecution.StartupTests' in str(args) for args,_ in calls))

    def test_execution_draft_and_promoted_modes_run_real_adapter_gates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("tests/python", "tests/fixtures", ".github", "pcucp-next/dotnet/PcuCp.NativeHost", *(
                    "pcucp-next/dotnet/" + p for p in qualification.PROJECTS["execution"])):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / "tests/python/test_legacy_execution_fixture.py").write_text("# fixture")
            draft = root / "tests/fixtures/legacy-execution-adapter.ps1"
            draft.write_text("# fixture")
            (root / "pcucp-next/dotnet/PcuCp.NativeHost/LegacyExecutionStartup.cs").write_text("// fixture")
            manifest = root / ".github/migration-adapters.json"
            calls = []
            def capture(argv, **kwargs):
                calls.append((argv, dict(kwargs["env"])))
            with patch.object(qualification, "ROOT", root), patch.object(qualification.subprocess, "run", side_effect=capture), contextlib.redirect_stdout(io.StringIO()):
                manifest.write_text('{"test_adapters":[]}')
                qualification.run_family("execution")
                env = calls[-1][1]
                self.assertEqual(env["CUCP_EXECUTION_ADAPTER_SOURCE"], str(draft))
                self.assertIn("CUCP_EXECUTION_TEST_HOST", env)
                self.assertIn("CUCP_EXECUTION_STARTUP_TEST_HOST", env)
                manifest.write_text('{"test_adapters":["execution"]}')
                qualification.run_family("execution")
                self.assertNotIn("CUCP_EXECUTION_ADAPTER_SOURCE", calls[-1][1])
                self.assertIn("CUCP_EXECUTION_TEST_HOST", calls[-1][1])
                manifest.write_text('{"test_adapters":[]}')
                draft.unlink()
                with self.assertRaisesRegex(ValueError, "Missing exact execution adapter draft"):
                    qualification.run_family("execution")

    def test_explicit_browser_run_enables_required_browser_assertions(self):
        calls = []
        with patch.object(qualification.subprocess, "run", side_effect=lambda argv, **kw: calls.append(kw["env"])):
            qualification.run_family("cdp", browser=True)
        self.assertEqual(calls[-1]["CUCP_CHROME_TEST"], "1")
        self.assertEqual(calls[-1]["CUCP_LEGACY_CDP_BROWSER_TEST"], "1")


if __name__ == "__main__":
    unittest.main()
