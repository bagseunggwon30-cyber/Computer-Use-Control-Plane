"""Read-only production-source freeze and inert legacy routing contracts.

All mutations use owned temporary source/manifest fixtures. These tests never
invoke PowerShell, a helper service, a browser, or a live desktop operation.
"""
from dataclasses import FrozenInstanceError, asdict
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pcucp-next/python"))
from pcucp_cli import legacy_dispatch as dispatch


class LegacyDispatchContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = dispatch.load_contract()
        self.source = (ROOT / "scripts/cucp.ps1").read_text(encoding="utf-8-sig")

    def test_checkpoint_matches_current_production_sources(self):
        dispatch.assert_frozen_sources(ROOT)
        self.assertEqual(self.contract.metadata["checkpoint"]["commit"],
                         "8fafca8cc4b59d86a34ee6674aaea88b97009afb")

    def test_exact_ordered_clauses_independently_match_production(self):
        # Extract only the existing one-line return clauses, not an executable
        # copy or a generated handler table from the modern engine registry.
        begin = self.source.index("function Invoke-Macro {")
        end = self.source.index("\nfunction _Read-OptValue", begin)
        body = self.source[begin:end]
        lines = re.findall(r'^    "([a-z-]+)"\s+\{ return ([^\n]+) \}$', body, re.M)
        expected = []
        for name, invocation in lines:
            handler = invocation.split()[0]
            if handler == "_Macro-NotImplemented":
                matched = re.fullmatch(r'_Macro-NotImplemented -Macro "([a-z-]+)" -Hint "([^"]*)"', invocation)
                self.assertIsNotNone(matched)
                self.assertEqual(matched[1], name)
                hint, options, state = matched[2], (), "not_implemented"
            else:
                matched = re.fullmatch(r'[\w-]+ -Rest \$rest((?: -\w+)*)', invocation)
                self.assertIsNotNone(matched)
                hint, options, state = None, tuple(flag[1:] for flag in matched[1].split()), "retained"
            expected.append((name, handler, options, state, hint))
        self.assertEqual(expected, [(r.name, r.handler, r.options, r.implementation, r.hint)
                                    for r in self.contract.clauses])
        self.assertEqual(len(expected), 109)
        self.assertEqual(len({r.name for r in self.contract.clauses}), 108)
        self.assertEqual(tuple(r.clause_index for r in self.contract.clauses), tuple(range(109)))
        for row in self.contract.clauses:
            self.assertIn('"' + row.name + '"', self.source.splitlines()[row.source_line - 1])

    def test_duplicate_returns_first_clause_without_deduplication(self):
        records = [row for row in self.contract.clauses if row.name == "click-point"]
        self.assertEqual([row.clause_index for row in records], [11, 42])
        self.assertIs(dispatch.resolve_macro("click-point"), records[0])
        self.assertIs(dispatch.resolve_macro("CLICK-POINT"), records[0])
        self.assertEqual(records[0].handler, records[1].handler)

    def test_every_macro_resolves_case_insensitively_to_first_record(self):
        first = {}
        for record in self.contract.clauses:
            first.setdefault(record.name, record)
            for name in (record.name, record.name.upper(), record.name.title()):
                self.assertIs(dispatch.resolve_macro(name), first[record.name])

    def test_only_two_macro_aliases_inject_fixed_options(self):
        aliases = {row.name: row.options for row in self.contract.clauses if row.options}
        self.assertEqual(aliases, {"double-click-label": ("Double",),
                                   "right-click-label": ("RightClick",)})
        for name in aliases:
            self.assertEqual(dispatch.resolve_macro(name).handler, "Invoke-MacroClickLabel")

    def test_wrapper_option_aliases_defaults_and_binding_are_frozen(self):
        params = {entry["name"]: entry for entry in self.contract.metadata["wrapper_parameters"]}
        self.assertEqual(params["AllowLiveControl"]["aliases"], ("AllowLive",))
        self.assertIs(params["AllowLiveControl"]["default"], False)
        self.assertEqual(params["CacheSeconds"]["aliases"], ("CacheSec",))
        self.assertEqual(params["CacheSeconds"]["default"], 2)
        self.assertEqual(params["InvokeTimeoutMs"]["aliases"], ("TimeoutMs", "InvokeTimeout"))
        self.assertEqual(params["InvokeTimeoutMs"]["effective_minimum"], 1000)
        self.assertEqual(params["CucpArgs"]["binding"], "ValueFromRemainingArguments")

    def test_all_seven_exact_not_implemented_hints(self):
        expected = {
            "process": "프로세스 조회/종료는 미구현. 위험 작업이라 게이트 설계 후 별도 구현 필요.",
            "registry": "레지스트리 읽기/쓰기는 미구현. 쓰기는 고위험이라 신중한 게이트 필요.",
            "notify": "토스트 알림은 미구현.",
            "multi-select": "다중 선택은 미구현.",
            "multi-edit": "다중 편집은 미구현.",
            "scrape": "스크레이프는 미구현. CDP/OCR 매크로로 대체 가능.",
            "dom-snapshot": "DOM 스냅샷은 미구현. cdp-deep-find / cdp-eval 로 대체 가능.",
        }
        actual = {r.name: r.hint for r in self.contract.clauses if r.implementation == "not_implemented"}
        self.assertEqual(actual, expected)
        self.assertEqual(self.contract.metadata["not_implemented"]["exit_code"], 1)
        self.assertEqual(self.contract.metadata["not_implemented"]["schema"], "cucp.not-implemented/v1")
        for name in expected:
            self.assertEqual(dispatch.resolve_macro(name.upper()).name, name)
            self.assertFalse(dispatch.requires_direct_safety(name))

    def test_unknown_unavailable_and_not_implemented_remain_distinct(self):
        self.assertIsNone(dispatch.resolve_macro("missing-macro"))
        self.assertEqual(dispatch.resolve_macro("process").implementation, "not_implemented")
        self.assertEqual(dispatch.resolve_macro("click-point").implementation, "retained")
        # The record carries no callable or candidate-availability switch.
        self.assertIsInstance(dispatch.resolve_macro("click-point").handler, str)
        self.assertNotIn("available", asdict(dispatch.resolve_macro("click-point")))
        for name in (" click-point", "click-point ", "click_point", "*", "^click-point$",
                     "Invoke-MacroClickPoint", "click-point; exit", ""):
            self.assertIsNone(dispatch.resolve_macro(name))
        for name in (None, True, 1, ["click-point"]):
            with self.assertRaises(TypeError):
                dispatch.resolve_macro(name)

    def test_direct_safety_list_is_exact_and_does_not_imply_authority(self):
        block = re.search(r'\$directSafetyLiveMacros = @\((.*?)\n  \)', self.source, re.S)[1]
        expected = tuple(re.findall(r'"([a-z-]+)"', block))
        self.assertEqual(self.contract.direct_safety_macros, expected)
        self.assertEqual(len(expected), 41)
        self.assertEqual(len(set(expected)), 41)
        for name in expected:
            self.assertTrue(dispatch.requires_direct_safety(name.upper()))
        # Family-specific gates still apply to these absent list members.
        for name in ("workflow-run", "task-run", "recovery-plan", "not-a-macro"):
            self.assertFalse(dispatch.requires_direct_safety(name))
        with self.assertRaises(TypeError):
            dispatch.requires_direct_safety(False)

    def test_top_level_routing_order_and_case(self):
        cases = [([], "help"), (["--"], "help"), (["version"], "version"),
                 (["VERSION", "--json-only"], "version"),
                 (["macro", "version"], "macro"), (["MaCrO"], "macro"),
                 (["macro", "unknown"], "macro"), (["ACT", "click"], "cli_json"),
                 (["plan", "run"], "cli_json"), (["benchmark"], "cli_stream"),
                 (["--", "--"], "cli_stream"), (["macro "], "cli_stream")]
        for argv, kind in cases:
            with self.subTest(argv=argv):
                self.assertEqual(dispatch.classify_top_level(argv).kind, kind)
        self.assertIsNone(dispatch.classify_top_level(["macro"]).macro)
        self.assertIsNone(dispatch.classify_top_level(["macro", "unknown"]).macro)
        self.assertEqual(dispatch.classify_top_level(["--", "macro", "VERSION"]).macro.name, "version")
        for word in self.contract.metadata["top_level"]["json_capture_first_words"]:
            kind = "version" if word == "version" else "cli_json"
            self.assertEqual(dispatch.classify_top_level([word.upper()]).kind, kind)

    def test_argv_is_copied_not_parsed_as_grants_or_code(self):
        argv = ["macro", "double-click-label", "--text", "--confirm-sensitive", "-AllowLiveControl", "$(exit)"]
        route = dispatch.classify_top_level(argv)
        argv[:] = ["version"]
        self.assertEqual(route.rest, ("--text", "--confirm-sensitive", "-AllowLiveControl", "$(exit)"))
        self.assertEqual(route.macro.options, ("Double",))
        self.assertFalse(hasattr(route, "authority"))
        for invalid in ("macro version", None, {"macro": "version"}, ["macro", None], [True]):
            with self.assertRaises(TypeError):
                dispatch.classify_top_level(invalid)

    def test_contract_records_and_nested_metadata_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.contract.clauses[0].name = "changed"
        with self.assertRaises(FrozenInstanceError):
            self.contract.clauses = ()
        with self.assertRaises(TypeError):
            self.contract.metadata["schema"] = "changed"
        with self.assertRaises(TypeError):
            self.contract.metadata["clauses"][0]["options"] = ("Injected",)
        self.assertIsInstance(self.contract.metadata["clauses"], tuple)

    def test_source_relative_contract_ignores_working_directory_and_env(self):
        with tempfile.TemporaryDirectory(prefix="legacy dispatch cwd ") as folder:
            original = Path.cwd()
            try:
                os.chdir(folder)
                with mock.patch.dict(os.environ, {"CUCP_ROOT": folder}):
                    dispatch.load_contract.cache_clear()
                    self.assertEqual(len(dispatch.load_contract().clauses), 109)
                    dispatch.assert_frozen_sources()
            finally:
                os.chdir(original)

    def test_source_assertions_bind_every_dispatch_handler_and_inventory_location(self):
        locations = {entry["path"]: {row["name"]: row["line"] for row in entry["functions"]}
                     for entry in json.loads((ROOT / "docs/legacy-function-inventory.json").read_text(encoding="utf-8"))["files"]}
        relationships = self.contract.metadata["dispatch_relationships"]
        self.assertEqual(len(relationships), 109)
        extents = {(e["path"], e["name"]): e for e in self.contract.metadata["extents"]}
        for record, relation in zip(self.contract.clauses, relationships):
            self.assertEqual(relation["clause_index"], record.clause_index)
            self.assertEqual(relation["caller"], "Invoke-Macro")
            self.assertEqual(relation["callee"], record.handler)
            self.assertEqual(extents[(relation["callee_path"], record.handler)]["start_line"],
                             relation["callee_start_line"])
            if relation["callee_path"] in locations:
                self.assertEqual(locations[relation["callee_path"]][record.handler], relation["callee_start_line"])

    def test_real_macro_callers_remain_entry_recorder_daemon_and_serve(self):
        calls = [row for row in self.contract.metadata["call_sites"] if row["callee"] == "Invoke-Macro"]
        self.assertEqual([row["caller"] for row in calls],
                         ["Invoke-MacroRecorder", "Invoke-MacroDaemon", "Invoke-MacroDaemonServe", "<top-level>"])
        actual_lines = [number for number, line in enumerate(self.source.splitlines(), 1)
                        if not line.lstrip().startswith("#") and re.search(r'\bInvoke-Macro\s+-ArgList\b', line)]
        self.assertEqual(actual_lines, [row["line"] for row in calls])

    def test_sensitive_live_and_effect_gate_order_is_bound(self):
        def ordered(function, tokens):
            _, _, body = dispatch._function_extent(self.source, function)
            positions = [body.index(token) for token in tokens]
            self.assertEqual(positions, sorted(positions), function)
        ordered("Invoke-Macro", ["$AllowLiveControl -and", "$directSafetyLiveMacros -contains $sub",
                "_Read-StandaloneConfirmation -Rest $rest", "_Classify-SafetyFromText", "return 3", "switch ($sub)"])
        ordered("Assert-Authorized", ["Test-LiveControlRequest", "Test-CoordinateMissingObservation",
                "if ($missingObs)", "if ($isLive -and -not $AllowLiveControl)"])
        ordered("_Read-StandaloneConfirmation", ["Get-Variable", "return $false", "_Invoke-LegacyCompatibility", "return [bool]$result.confirmed"])
        ordered("_Invoke-LegacyExecutionFamily", ["$liveCeiling=", "$sensitiveCeiling=", "$inherited=", "$restCopy=", "return _Invoke-LegacyExecutionHost"])
        ordered("_Invoke-LegacyExecutionEffectLoop", ["_Execution-ValidateEffect $message", "$State.live_effect_seen=$true", "_Execution-Dispatch $message"])
        self.assertEqual(self.contract.metadata["authority_order"]["diagnostics_family"][1],
                         "copy context and original rest into new state with live=false and sensitive=false")
        self.assertEqual(self.contract.metadata["confirmation_contract"]["inherited_global"],
                         "CUCP_EXECUTION_SENSITIVE_CEILING")

    def _fixture(self, folder):
        root = Path(folder)
        for source in self.contract.metadata["sources"]:
            path = root / source["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source["path"], path)
        return root

    def test_every_frozen_source_rejects_owned_fixture_drift(self):
        with tempfile.TemporaryDirectory(prefix="legacy dispatch drift ") as folder:
            root = self._fixture(folder)
            dispatch.assert_frozen_sources(root)
            for source in self.contract.metadata["sources"]:
                with self.subTest(source=source["path"]):
                    path = root / source["path"]
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n# changed fixture\n")
                    with self.assertRaisesRegex(dispatch.LegacyDispatchContractError, "source drift"):
                        dispatch.assert_frozen_sources(root)
                    path.write_bytes(original)

    def test_caller_only_mutation_and_missing_source_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="legacy dispatch caller ") as folder:
            root = self._fixture(folder)
            path = root / "scripts/cucp.ps1"
            text = path.read_text(encoding="utf-8-sig")
            path.write_text(text.replace("Invoke-Macro -ArgList $CucpArgs", "Invoke-Macro -ArgList $OtherArgv"), encoding="utf-8")
            with self.assertRaisesRegex(dispatch.LegacyDispatchContractError, "source drift"):
                dispatch.assert_frozen_sources(root)
            path.unlink()
            with self.assertRaisesRegex(dispatch.LegacyDispatchContractError, "source unavailable"):
                dispatch.assert_frozen_sources(root)

    def test_checkout_bom_and_crlf_do_not_create_false_source_drift(self):
        with tempfile.TemporaryDirectory(prefix="legacy dispatch CRLF ") as folder:
            root = self._fixture(folder)
            for source in self.contract.metadata["sources"]:
                path = root / source["path"]
                text = dispatch._canonical_text(path.read_bytes())
                path.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
            dispatch.assert_frozen_sources(root)

    def test_tampered_manifest_cannot_introduce_arbitrary_handler(self):
        with tempfile.TemporaryDirectory(prefix="legacy dispatch contract ") as folder:
            path = Path(folder) / "forged.json"
            path.write_text(dispatch.CONTRACT_PATH.read_text(encoding="utf-8").replace("Invoke-MacroSafetyClassify", "Invoke-ArbitraryExecutable"), encoding="utf-8")
            dispatch.load_contract.cache_clear()
            try:
                with mock.patch.object(dispatch, "CONTRACT_PATH", path):
                    with self.assertRaisesRegex(dispatch.LegacyDispatchContractError, "digest drift"):
                        dispatch.load_contract()
            finally:
                dispatch.load_contract.cache_clear()

    def test_resolving_never_starts_a_process_or_performs_network_io(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), \
             mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            for record in self.contract.clauses:
                self.assertIsNotNone(dispatch.resolve_macro(record.name))
            dispatch.classify_top_level(["macro", "process"])
            dispatch.assert_frozen_sources(ROOT)
        module_source = Path(dispatch.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from .registry", module_source)
        self.assertNotRegex(module_source, r"\b(?:eval|exec|Popen)\(")
        self.assertNotIn("getattr(", module_source)


if __name__ == "__main__":
    unittest.main()
