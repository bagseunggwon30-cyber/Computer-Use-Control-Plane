"""Qualification selection must never turn a requested gate into an empty pass."""
import importlib.util
import contextlib
import io
from unittest.mock import patch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("qualification", ROOT / "pcucp-next/packaging/migration_qualification.py")
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


class QualificationSelectionTests(unittest.TestCase):
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
                (root / 'tests/python/test_legacy_workflow_parity.py').write_text('# fixture')
                qualification.run_family('foundation')
            projects = [args[args.index('--project') + 1] for args, _ in calls if '--project' in args]
            self.assertEqual(projects, [str(root / 'pcucp-next/dotnet' / name)
                                       for name in qualification.PROJECTS['foundation']])
            self.assertIn(str(root / 'pcucp-next/dotnet/PcuCp.LegacyWorkflow.ContractTests'), projects)
            suites = [args[args.index('-p') + 1] for args, _ in calls if '-p' in args]
            self.assertEqual(suites, ['test_migration_inventory.py', 'test_legacy_workflow_parity.py'])

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
