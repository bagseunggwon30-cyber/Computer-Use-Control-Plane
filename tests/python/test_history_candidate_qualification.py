"""History scope is explicit, candidate-only, complete and fail-closed."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qualification = load('history_scope_selection', ROOT/'pcucp-next/packaging/migration_qualification.py')
gate = load('history_candidate_gate', ROOT/'pcucp-next/packaging/history_candidate_qualification.py')
history = load('history_evidence_fixture', ROOT/'tests/python/test_legacy_history_reducers.py')


class HistoryScopeTests(unittest.TestCase):
    def test_history_is_explicit_and_defaults_keep_six_families(self):
        six = ('execution','precision','cdp','interaction','diagnostics','file-images')
        self.assertEqual(qualification.FAMILIES,six)
        for explicit,message in (('history-candidate',''),('','[focus history-candidate] Qualify data reducers')):
            self.assertEqual(qualification.select_scope(explicit,message),(['history-candidate'],False))
        self.assertEqual(qualification.select_scope('all',''),(list(six),False))
        self.assertEqual(qualification.select_scope('full','[focus history-candidate]'),(list(six),True))
        self.assertNotIn('history-candidate',qualification.available_families(ROOT))
    def test_history_cannot_be_marked_promoted(self):
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned);(root/'.github').mkdir()
            (root/'.github/migration-adapters.json').write_text('{"test_adapters":["history-candidate"]}')
            with self.assertRaisesRegex(ValueError,'Candidate-only'):
                qualification.enabled_adapters(root)
    def test_each_required_file_blocks_before_hosts_or_processes(self):
        for absent in gate.REQUIRED_FILES:
            with self.subTest(absent=absent), tempfile.TemporaryDirectory() as owned:
                root=Path(owned)/'repo';root.mkdir()
                for name in gate.REQUIRED_FILES:
                    if name!=absent:
                        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('fixture')
                log=Path(owned)/'logs'
                with patch.object(gate,'resolve_hosts') as hosts, contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError,'Missing required'):
                        gate.run(root,log,check_adapters=lambda _:set())
                    hosts.assert_not_called()
                summary=json.loads((log/'candidate-summary.json').read_text(encoding='utf-8', errors='strict'))
                self.assertEqual(summary['status'],'blocked')
                self.assertIs(summary['production_cutover'],False)
    def test_nonwindows_and_missing_hosts_leave_blocked_evidence(self):
        for windows in (False,True):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory() as owned:
                log=Path(owned)/'logs'
                with patch.object(gate,'windows_host',return_value=windows), patch.object(gate,'resolve_hosts',side_effect=ValueError('missing host')), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(ValueError): gate.run(ROOT,log,check_adapters=lambda _:set())
                summary=json.loads((log/'candidate-summary.json').read_text(encoding='utf-8', errors='strict'))
                self.assertEqual(summary['status'],'blocked')
                self.assertEqual(summary['completed_stages'],[])
    def test_windows_contract_mode_is_nonzero_on_portable_host(self):
        if os.name=='nt': self.skipTest('Portable-host refusal applies off Windows')
        with tempfile.TemporaryDirectory() as owned:
            path=Path(owned)/'contracts.json'
            self.assertEqual(history.windows_contracts(path),1)
            report=json.loads(path.read_text(encoding='utf-8', errors='strict'))
            self.assertEqual(report['status'],'blocked')
            with self.assertRaises(ValueError): gate.validate_contract_report(path)
    def test_contract_evidence_requires_no_skips_and_codepage_probe(self):
        good=dict(schema='cucp.history-windows-contracts/v1',status='passed-windows-contracts',test_ids=['history.'+gate.CODEPAGE_TEST],tests_run=1,skipped=[],failures=[],errors=[],owned_non65001_probe='passed',process_artifact_directory='windows-contract-processes',process_artifact_count=1)
        with tempfile.TemporaryDirectory() as owned:
            path=Path(owned)/'contracts.json';path.write_text(json.dumps(good))
            artifacts=path.parent/'windows-contract-processes';artifacts.mkdir()
            raw=history.dumps(dict(input_code_page=949,output_code_page=1252,reports=[{'runtime':'ps51'},{'runtime':'ps7'}])).encode()
            (artifacts/'probe.stdout.bin').write_bytes(raw);(artifacts/'probe.stderr.bin').write_bytes(b'')
            (artifacts/'probe.process.json').write_text(json.dumps(dict(command=['python','--owned-console-utf8-probe'],exit_code=0,launch_error=None,timed_out=False,stdout_truncated=False,stderr_truncated=False,stdout_artifact='probe.stdout.bin',stdout_bytes=len(raw),stderr_bytes=0,stdout_sha256=history.digest(raw),stderr_sha256=history.digest(b''))))
            gate.validate_contract_report(path)
            for changes in ({'status':'blocked'},{'skipped':[['probe','skip']]},{'tests_run':0},{'test_ids':[]},{'owned_non65001_probe':'not-run'},{'failures':['failed']},{'process_artifact_count':0},{'process_artifact_directory':'missing'}):
                path.write_text(json.dumps(dict(good,**changes)))
                with self.assertRaises(ValueError):gate.validate_contract_report(path)
    def test_windows_contract_evidence_cannot_omit_inner_process_files(self):
        report=dict(schema='cucp.history-windows-contracts/v1',status='passed-windows-contracts',test_ids=['history.'+gate.CODEPAGE_TEST],tests_run=1,skipped=[],failures=[],errors=[],owned_non65001_probe='passed',process_artifact_directory='windows-contract-processes',process_artifact_count=1)
        with tempfile.TemporaryDirectory() as owned:
            path=Path(owned)/'contracts.json';path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'inner-process'):gate.validate_contract_report(path)
            directory=path.parent/'windows-contract-processes';directory.mkdir()
            (directory/'missing.process.json').write_text(json.dumps({'stdout_artifact':'missing.stdout.bin'}))
            with self.assertRaisesRegex(ValueError,'inner-process'):gate.validate_contract_report(path)
    def test_runner_selects_hosts_selftest_windows_suite_and_six_run_gate(self):
        # Planning-only double; actual evidence acceptance is tested separately.
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned)/'repo';root.mkdir();log=Path(owned)/'logs'
            for name in gate.REQUIRED_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            dll=root/'pcucp-next/dotnet/PcuCp.LegacyHistory.Qualification/bin/Release/net8.0/PcuCp.LegacyHistory.Qualification.dll'
            dll.parent.mkdir(parents=True);dll.write_bytes(b'fixture')
            hosts={name:Path(owned)/(name+'.exe') for name in ('ps51','ps7','dotnet')}
            for path in hosts.values():path.write_bytes(b'fixture')
            calls=[]
            def run(argv,**kwargs):
                calls.append((argv,kwargs))
                if '-Runtime' in argv:
                    runtime=argv[argv.index('-Runtime')+1]
                    return json.dumps({'host':{'ps_version':'5.1.1' if runtime=='ps51' else '7.5.1'}}).encode()
                return b'fixture'
            fake=SimpleNamespace(fixtures=lambda:[{'id':'case'}],input_bytes=lambda _:b'fixture',
                materialize_original=lambda owner,**kw:Path(owner)/'original.ps1',run_bounded=run,
                validate_report=lambda *a,**kw:None,SOURCE_SHA256='source',ORIGINAL_SHA256='manifest',digest=lambda _: 'hash')
            with patch.object(gate,'windows_host',return_value=True),patch.object(gate,'resolve_hosts',return_value=hosts),patch.object(gate,'load_history_tests',return_value=fake),patch.object(gate,'validate_contract_report',return_value={'status':'passed-windows-contracts'}),patch.object(gate,'validate_differential',return_value={'runs':[None]*6}),contextlib.redirect_stdout(io.StringIO()):
                gate.run(root,log,check_adapters=lambda _:set())
            self.assertEqual(len(calls),6)
            self.assertEqual([argv[0] for argv,_ in calls[:2]],[str(hosts['ps51']),str(hosts['ps7'])])
            self.assertIn('-SourcePath',calls[0][0])
            self.assertIn('build',calls[2][0]);self.assertEqual(calls[3][0][-1],'--self-test')
            self.assertIn('--windows-contracts',calls[4][0])
            self.assertIn('--differential',calls[5][0])
            for flag,name in (('--ps51','ps51'),('--ps7','ps7')):
                self.assertEqual(calls[5][0][calls[5][0].index(flag)+1],str(hosts[name]))
            self.assertTrue(all('artifact_prefix' in kwargs for _,kwargs in calls))
            summary=json.loads((log/'candidate-summary.json').read_text(encoding='utf-8', errors='strict'))
            self.assertEqual(summary['status'],'passed-candidate-only')
            self.assertIs(summary['production_cutover'],False)
            self.assertEqual(summary['differential_runs'],6)
    def test_workflow_has_separate_complete_candidate_job(self):
        text=(ROOT/'.github/workflows/migration-qualification.yml').read_text(encoding='utf-8', errors='strict')
        self.assertIn('history-candidate, full]',text)
        job=text.split('  windows-history-candidate:\n',1)[1].split('  cdp-browser:\n',1)[0]
        for required in ("contains(fromJSON(needs.scope.outputs.families), 'history-candidate')",'runs-on: windows-latest','fetch-depth: 0',"dotnet-version: '8.0.x'",'--family history-candidate --log-dir .migration-logs/history-candidate','if: always()','if-no-files-found: error','include-hidden-files: true'):
            self.assertIn(required,job)
        self.assertNotIn('continue-on-error',job)
        self.assertIn('uses: ./.github/workflows/core.yml',text.split('  full-regression:\n',1)[1])


class HistoryRequiredArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=history.fixtures()
    def make_evidence(self,directory):
        def write(name,value):
            data=history.dumps(value).encode('utf-8')
            (directory/name).write_bytes(data)
            return data
        (directory/'input.json').write_bytes(history.input_bytes(self.cases))
        runs=[]
        for runtime,batch,repeat in sorted(gate.EXPECTED_RUNS):
            subset=self.cases[:1] if batch=='singleton' else self.cases
            (directory/f'{runtime}-{batch}-input.json').write_bytes(history.input_bytes(subset))
            prefix=f'{runtime}-{batch}-{repeat}'
            results=[dict(id=f['id'],operation=f['operation'],wire={'kind':'null'},compact_json='null',compact_json_items=['null'],console='',errors=[]) for f in subset]
            hashes={}
            host={'ps_version':'5.1.123' if runtime=='ps51' else '7.5.1'}
            for kind in ('candidate','observed'):
                value=dict(schema=history.SCHEMA,runtime=runtime,kind='candidate-inferred' if kind=='candidate' else 'windows-observation',host=host,results=results)
                if kind=='observed':value.update(source_sha256=history.SOURCE_SHA256,manifest_sha256=history.ORIGINAL_SHA256,input_sha256=history.digest(history.input_bytes(subset)),serialization_probes=[dict(id=name,wire={'kind':'null'},compact_json=None,compact_json_items=[]) for name in history.SERIALIZATION_PROBES])
                raw=write(f'{prefix}-{kind}.raw.json',value);hashes[kind]=history.digest(raw)
                (directory/f'{prefix}-{kind}.stdout.bin').write_bytes(raw)
                (directory/f'{prefix}-{kind}.stderr.bin').write_bytes(b'')
                write(f'{prefix}-{kind}.process.json',dict(command=['fixture'],exit_code=0,timed_out=False,launch_error=None,stdout_truncated=False,stderr_truncated=False,stdout_artifact=f'{prefix}-{kind}.stdout.bin',stdout_bytes=len(raw),stderr_bytes=0,stdout_sha256=hashes[kind],stderr_sha256=history.digest(b'')))
            write(f'{prefix}-mismatches.json',[])
            runs.append(dict(runtime=runtime,batch=batch,repeat=repeat,count=len(subset),mismatch_count=0,observed_host=host,candidate_sha256=hashes['candidate'],observed_sha256=hashes['observed']))
        report=dict(schema='cucp.history-reducer-gate/v1',status='passed-candidate-parity',production_cutover=False,errors=[],fixture_count=465,source_sha256=history.SOURCE_SHA256,manifest_sha256=history.ORIGINAL_SHA256,input_sha256=history.digest(history.input_bytes(self.cases)),candidate_source_sha256={p.name:history.digest(p.read_bytes()) for p in sorted(history.PROJECT.glob('*')) if p.is_file()},oracle_source_sha256=history.digest((history.FIXTURES/'oracle.ps1').read_bytes()),runs=runs)
        write('report.json',report)
        return report
    def test_exact_six_run_evidence_is_required(self):
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned);report=self.make_evidence(root)
            self.assertEqual(len(gate.validate_differential(root,history)['runs']),6)
            for changes in ({'status':'blocked'},{'status':'failed-parity'},{'runs':report['runs'][:-1]},{'runs':report['runs'][:1]*6},{'fixture_count':1},{'production_cutover':True},{'errors':['failure']}):
                (root/'report.json').write_text(json.dumps(dict(report,**changes)))
                with self.assertRaises(ValueError):gate.validate_differential(root,history)
    def test_missing_required_artifact_cannot_pass(self):
        for name in ('report.json','input.json','ps51-many-input.json','ps7-many-1-candidate.raw.json','ps51-singleton-0-observed.stdout.bin','ps51-many-1-observed.stderr.bin','ps7-many-0-candidate.process.json','ps51-many-0-mismatches.json'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as owned:
                root=Path(owned);self.make_evidence(root);(root/name).unlink()
                with self.assertRaises(ValueError):gate.validate_differential(root,history)
    def test_timeout_missing_flags_and_raw_changes_cannot_pass(self):
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned);self.make_evidence(root)
            path=root/'ps51-many-0-candidate.process.json';original=json.loads(path.read_text(encoding='utf-8', errors='strict'))
            for changes in ({'timed_out':True},{'stdout_truncated':True},{'exit_code':7},{'exit_code':False}):
                path.write_text(json.dumps(dict(original,**changes)))
                with self.assertRaises(ValueError):gate.validate_differential(root,history)
            changed=copy.deepcopy(original);changed.pop('timed_out');path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):gate.validate_differential(root,history)
            path.write_text(json.dumps(original));(root/'ps51-many-0-candidate.stdout.bin').write_bytes(b'changed')
            with self.assertRaises(ValueError):gate.validate_differential(root,history)


if __name__=='__main__':unittest.main()
