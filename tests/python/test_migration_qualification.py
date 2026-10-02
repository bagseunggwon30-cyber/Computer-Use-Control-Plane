"""Qualification selection must never turn a requested gate into an empty pass."""
import importlib.util
import contextlib
import io
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("qualification", ROOT / "pcucp-next/packaging/migration_qualification.py")
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


class QualificationSelectionTests(unittest.TestCase):
    def test_default_runs_all_families_and_full_cannot_be_weakened_by_focus(self):
        families = list(qualification.FAMILIES)
        self.assertEqual(qualification.select_scope("", "Implement batch"), (families, False))
        self.assertEqual(qualification.select_scope("", "[focus cdp] [full regression] Verify batch"), (families, True))
        self.assertEqual(qualification.select_scope("full", "[focus cdp]"), (families, True))

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
            self.assertEqual(qualification.enabled_adapters(root), set(qualification.FAMILIES))

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
