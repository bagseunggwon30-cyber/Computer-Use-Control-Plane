"""Owned progress/metadata integration guards. No provider or desktop execution."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('progress_runner',ROOT/'pcucp-next/packaging/qualify_legacy_helper_providers.py')
RUNNER=importlib.util.module_from_spec(spec);spec.loader.exec_module(RUNNER)

class ProgressIntegrationTests(unittest.TestCase):
    def test_missing_trace_is_only_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(RUNNER.progress_snapshot(Path(temp)/'missing')['available'])
    def test_partial_trace_keeps_last_complete_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'owned.jsonl';path.write_bytes(b'{"phase":"request.start"}\n{"phase":')
            result=RUNNER.progress_snapshot(path)
            self.assertEqual(result['complete_records'],1)
            self.assertEqual(result['last_marker'],dict(phase='request.start'))
            self.assertEqual(result['parse_error'],'incomplete final line')
            self.assertEqual(path.read_bytes(),b'{"phase":"request.start"}\n{"phase":')
    def test_oversized_trace_not_read_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'owned.jsonl';path.write_bytes(b'x'*(RUNNER.PROGRESS_MAX_BYTES+1))
            self.assertIn('error',RUNNER.progress_snapshot(path))
    def metadata_tree(self,root,info='1.0.0+'+'a'*40):
        for project,name in [('tests/fixtures/legacy-observation-owned-window','ObservationOwnedWindow'),('tests/fixtures/legacy-helper-provider-probe','LegacyHelperProviderProbe'),('pcucp-next/dotnet/PcuCp.LegacyHelper','PcuCp.LegacyHelper'),('pcucp-next/dotnet/PcuCp.LegacyInterop','PcuCp.LegacyInterop')]:
            path=root/project/'obj/Release/net48'/f'{name}.AssemblyInfo.cs';path.parent.mkdir(parents=True)
            path.write_bytes(('[assembly: System.Reflection.AssemblyInformationalVersionAttribute("'+info+'")]\r\n[assembly: System.Reflection.AssemblyVersionAttribute("1.0.0.0")]\r\n').encode())
    def test_metadata_preserves_crlf_and_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';logs=Path(temp)/'logs';logs.mkdir();self.metadata_tree(root)
            records=RUNNER.retain_assembly_metadata(root,logs)
            self.assertEqual(len(records),4)
            for source,record in records.items():
                self.assertEqual(record['source_revision_suffix'],'a'*40)
                self.assertEqual((root/source).read_bytes(),(logs/record['evidence']).read_bytes())
            self.assertEqual(records,json.loads((logs/'assembly-metadata.json').read_text()))
    def test_metadata_missing_revision_is_not_invented(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';logs=Path(temp)/'logs';logs.mkdir();self.metadata_tree(root,'1.2.3')
            self.assertTrue(all(r['source_revision_suffix'] is None for r in RUNNER.retain_assembly_metadata(root,logs).values()))
    def test_metadata_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root';logs=Path(temp)/'logs';logs.mkdir()
            with self.assertRaises(FileNotFoundError):RUNNER.retain_assembly_metadata(root,logs)
    def cold_row(self):
        from test_legacy_helper_providers import uia,ready
        row=uia()
        row['calls'][:0]=[dict(operation=op,arguments=[],source='actual-provider',actual_result=None,result=None) for op in ('uia.load','win32.ensure')]
        return row,ready()
    def test_complete_cold_control_success(self):
        row,ready=self.cold_row();RUNNER.validate_cold_control([row],ready)
    def test_cold_initializer_missing_success_field_rejected(self):
        row,ready=self.cold_row();del row['calls'][0]['result']
        with self.assertRaises(AssertionError):RUNNER.validate_cold_control([row],ready)
    def test_cold_contradictory_state_rejected(self):
        for key,value in [('request_count',2),('uia_loaded',False),('win32_loaded',False),('ocr_warm',True)]:
            with self.subTest(key=key):
                row,ready=self.cold_row();row['state'][key]=value
                with self.assertRaises(AssertionError):RUNNER.validate_cold_control([row],ready)
    def test_cold_duplicate_initialization_rejected(self):
        row,ready=self.cold_row();row['calls'].insert(0,copy.deepcopy(row['calls'][0]))
        with self.assertRaises(AssertionError):RUNNER.validate_cold_control([row],ready)
    def test_cold_diagnostics_follow_returned_dispatch(self):
        source=(ROOT/'tests/fixtures/legacy-helper-provider-probe/Program.cs').read_text()
        self.assertIn('deferDiagnostics = caseGroup == "uia-cold"',source)
        self.assertIn('if (deferDiagnostics) deferredElements = result;',source)
        begin=source.index('private static void Run(');end=source.index('private sealed class Provider',begin);body=source[begin:end]
        self.assertLess(body.index('actions.Dispatch(action, arguments)'),body.index('progress.Emit("dispatch.end")'))
        self.assertLess(body.index('progress.Emit("dispatch.end")'),body.index('provider.CompleteDeferredDiagnostics()'))
        runner=(ROOT/'pcucp-next/packaging/qualify_legacy_helper_providers.py').read_text()
        self.assertIn("cold_control_required=True, cold_control_validated=False",runner)
        self.assertIn("validate_cold_control(rows,ready)",runner)
    def test_added_group_fits_unchanged_outer_budget(self):
        # 60s existing expectation preflight + 30s new progress preflight,
        # two 300s builds, 30s ready, seven 90s groups, 10s close.
        # Each of 12 bounded subprocesses can add at most 2s kill+0.4s drain;
        # fixture cleanup has the same 2.4s allowance. Reserve another 30s.
        maximum=60+30+2*300+30+7*90+10+13*2.4+30
        self.assertLess(maximum,1500)
    def test_sparse_test_only_instrumentation_and_budgets(self):
        source=(ROOT/'tests/fixtures/legacy-helper-provider-probe/Program.cs').read_text()
        self.assertIn('if (++index % 128 == 0)',source)
        self.assertIn('scannedNames % 128 == 0',source)
        self.assertIn('progress.DiagnosticTicks += Stopwatch.GetTimestamp() - started',source)
        self.assertIn('progress.ProviderTicks += Stopwatch.GetTimestamp() - started',source)
        self.assertNotIn('Console.Error.WriteLine("progress',source)
        runner=(ROOT/'pcucp-next/packaging/qualify_legacy_helper_providers.py').read_text()
        self.assertIn('timeout=90,creationflags=0x08000000',runner)
        self.assertIn("validate_progress((fixture_dir/(group+'-progress.jsonl')).read_bytes(),group)",runner)
        self.assertIn('timeout=1500',(ROOT/'pcucp-next/packaging/qualify_legacy_helper.py').read_text())

if __name__=='__main__':unittest.main()
