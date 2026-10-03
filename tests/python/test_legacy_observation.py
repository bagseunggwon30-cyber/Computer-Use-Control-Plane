"""Candidate structural/protocol tests. These are never Windows/provider proof."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qualify_legacy_observation', ROOT / 'pcucp-next/packaging/qualify_legacy_observation.py')
QUALIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFY)
FIXTURES = ROOT / 'tests/fixtures/legacy-observation'

class SourceTests(unittest.TestCase):
    def test_original_source_is_available_and_pinned(self):
        raw, manifest = QUALIFY.source_bytes()
        self.assertEqual(len(raw), manifest['raw_bytes'])
        self.assertEqual(manifest['retirement_credit'], 0)

    def test_all_original_function_bodies_remain_exact(self):
        raw, manifest = QUALIFY.source_bytes()
        source = raw.decode('utf-8-sig').replace('\r\n','\n')
        current = (ROOT / 'scripts/cucp-native-helper.ps1').read_text(encoding='utf-8-sig')
        encoded = source.encode('utf-16le')
        for record in manifest['functions']:
            body = encoded[2*record['start_utf16']:2*record['end_utf16']].decode('utf-16le')
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), record['sha256'])
            self.assertEqual(len(body.encode()), record['utf8_bytes'])
            self.assertEqual(current.count(body), 1, record['name'])
        self.assertEqual(sum(f['utf8_bytes'] for f in manifest['functions'][:11]), 25216)

    def test_entire_original_entry_is_preserved_except_candidate_hook(self):
        raw, _ = QUALIFY.source_bytes()
        source = raw.decode('utf-8-sig').replace('\r\n','\n')
        current = (ROOT / 'scripts/cucp-native-helper.ps1').read_text(encoding='utf-8-sig')
        hook = "if ($env:CUCP_LEGACY_OBSERVATION_CANDIDATE) {\n  if ($env:CUCP_LEGACY_OBSERVATION_CANDIDATE -ne '1') { throw 'Invalid observation candidate selector; expected 1 or unset.' }\n  . (Join-Path $PSScriptRoot 'cucp-legacy-observation-adapter.ps1')\n}\n"
        self.assertEqual(current.count(hook), 1)
        self.assertEqual(current.replace(hook,''), source)

    def test_seams_are_pinned_and_read_only(self):
        raw, manifest = QUALIFY.source_bytes()
        encoded = raw.decode('utf-8-sig').replace('\r\n','\n').encode('utf-16le')
        for record in manifest['functions']:
            body = encoded[2*record['start_utf16']:2*record['end_utf16']].decode('utf-16le')
            for old, new in manifest['type_seams'].items():
                self.assertEqual(body.count(old), record['type_seams'].get(old,0))
                self.assertTrue(new.startswith('PcuCp.LegacyObservation.Qualification.Fixture'))

    def test_provider_owns_reads_and_has_no_mutations(self):
        source = (ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation/WindowsObservationProvider.cs').read_text()
        for token in ('CucpNative.WindowFromPoint','CucpNative.EnumerateTopLevel','AutomationElement.FromPoint',
                      'AutomationElement.FromHandle','TreeScope.Descendants','TryGetClickablePoint','GetCurrentPattern'):
            self.assertIn(token, source)
        for token in ('SendInput(', 'SendMouseClick(', '.Invoke()', '.Toggle()', '.Select()', '.SetValue(', 'ScriptBlock', 'PowerShell.Create'):
            self.assertNotIn(token, source)

    def test_candidate_is_opt_in_only(self):
        helper = (ROOT / 'scripts/cucp-native-helper.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("if ($env:CUCP_LEGACY_OBSERVATION_CANDIDATE) {",helper)
        self.assertIn("$env:CUCP_LEGACY_OBSERVATION_CANDIDATE -ne '1'",helper)
        self.assertEqual(helper.count(". (Join-Path $PSScriptRoot 'cucp-legacy-observation-adapter.ps1')"),1)
        library = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation'
        self.assertFalse(any('FixtureState' in p.read_text() for p in library.glob('*.cs')))

    def test_fixture_cases_are_ordinary_counted_files(self):
        names=json.loads((FIXTURES/'cases.json').read_text())
        self.assertGreaterEqual(len(names),85)
        self.assertEqual(len(names),len(set(names)))
        for name in names:
            case=json.loads((FIXTURES/(name+'.json')).read_text())
            self.assertEqual(name,case['Name'])
            self.assertIn(case['Operation'],('hit-test','hit-scan','uia-tree','uia-find','guard','refine','click','fusion','payload'))

    def test_mutation_tripwires_record_before_throw(self):
        source=(ROOT/'pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification/ScriptedObservation.cs').read_text()
        for name in ('Invoke','Toggle','Select'):
            self.assertRegex(source,r'public void '+name+r'\(\) \{FixtureState.Mutations\+\+;FixtureState.Record\("mutation-attempt:'+name+r'"\);throw')

    def test_adapter_does_not_weaken_actual_shared_callers(self):
        adapter=(ROOT/'scripts/cucp-legacy-observation-adapter.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('function _Action-Click',adapter)
        self.assertNotIn('function _Resolve-OcrUiaFusionCandidate',adapter)
        self.assertNotIn('SendMouseClick',adapter)
        self.assertEqual(adapter.count('function _Test-CoordsInTarget'),1)

    def test_wrapper_driver_flattens_json_before_typed_binding(self):
        source=(ROOT/'tests/fixtures/legacy-observation-wrapper.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("$arguments=New-Object 'System.Collections.Generic.List[string]'",source)
        self.assertIn('foreach($item in $decoded)',source)
        self.assertIn('-CucpArgs ([string[]]$arguments.ToArray())',source)
        self.assertNotIn('$argv=@(',source)

    def test_provider_probe_cannot_initialize_or_change_uia(self):
        project=(ROOT/'tests/fixtures/legacy-observation-provider-probe/ObservationProviderProbe.csproj').read_text()
        code=(ROOT/'tests/fixtures/legacy-observation-provider-probe/ProviderLoadProbe.cs').read_text()
        self.assertNotIn('<Reference ',project)
        self.assertNotIn('ProjectReference',project)
        self.assertIn('FirstChanceException+=Capture',code)
        self.assertIn('if(errors.Count>=256)',code)
        for token in ('AutomationElement.', 'RegisterClientSide', 'SetProxyDescription', 'SendInput(', 'SendMouseClick('):self.assertNotIn(token,code)

    def test_side_diagnostics_follow_unchanged_entry_pairs(self):
        source=(ROOT/'pcucp-next/packaging/qualify_legacy_observation.py').read_text()
        self.assertLess(source.index('for label, arguments in cases + wrapper_cases:'),source.index("run('provider-identity-'"))
        self.assertIn("for mode in ('original', 'candidate', 'shared-current'):",source)
        self.assertIn("processes.append(result)",source)

class ComparisonTests(unittest.TestCase):
    def envelope(self):
        return dict(schema='cucp.observation-oracle/v1',scenario='plain',mode='original',captured={'exit_code':0,'payload':{'status':'ok','elapsed_ms':1}},return_value=None,error=None,acquisition=['ensure-win32'],inert_mutations=0)

    def test_only_declared_elapsed_is_excluded(self):
        a=self.envelope();b=copy.deepcopy(a);b['mode']='candidate';b['captured']['payload']['elapsed_ms']=20
        self.assertEqual(QUALIFY.compare_oracle(a,b),1)
        self.assertEqual(a['captured']['payload']['elapsed_ms'],1)

    def test_boolean_numeric_type_difference_fails(self):
        a=self.envelope();b=copy.deepcopy(a);a['return_value']=True;b['return_value']=1
        with self.assertRaises(AssertionError):QUALIFY.compare_oracle(a,b)

    def test_array_order_difference_fails(self):
        a=self.envelope();b=copy.deepcopy(a);a['return_value']=[1,2];b['return_value']=[2,1]
        with self.assertRaises(AssertionError):QUALIFY.compare_oracle(a,b)

    def test_scalar_array_shape_difference_fails(self):
        a=self.envelope();b=copy.deepcopy(a);a['return_value']={'a':1};b['return_value']=[{'a':1}]
        with self.assertRaises(AssertionError):QUALIFY.compare_oracle(a,b)

    def test_acquisition_order_difference_fails(self):
        a=self.envelope();b=copy.deepcopy(a);a['acquisition']=['first','second'];b['acquisition']=['second','first']
        with self.assertRaises(AssertionError):QUALIFY.compare_oracle(a,b)

    def test_diagnostics_are_not_blanket_normalized(self):
        a=self.envelope();b=copy.deepcopy(a);a['error']='first';b['error']='second'
        with self.assertRaises(AssertionError):QUALIFY.compare_oracle(a,b)

    def test_undeclared_elapsed_field_stays_exact(self):
        a={'status':'ok','elapsed_ms':1,'nested':{'elapsed_ms':1}};b=copy.deepcopy(a);b['nested']['elapsed_ms']=2
        with self.assertRaises(AssertionError):QUALIFY.compare_entry(a,b)

    def test_bad_elapsed_is_rejected(self):
        for value in (-1,True,'1',None):
            with self.assertRaises(AssertionError):QUALIFY.remove_elapsed({'elapsed_ms':value},[('elapsed_ms',)])

    def test_mutation_attempt_fails_even_if_both_match(self):
        a=self.envelope();a['inert_mutations']=1
        with self.assertRaises(AssertionError):QUALIFY.compare_oracle(a,copy.deepcopy(a))

    def test_matching_failure_status_is_not_owned_outcome(self):
        for label, payload, code in [('helper-tree-no-match', {'status':'partial','reason':'uia_unavailable'},2),('helper-hit-missing', {'status':'error','reason':'win32_load_failed'},1),('helper-hit-mismatch',{'status':'partial','reason':'no_window_at_coords'},2)]:
            with self.assertRaises(AssertionError):QUALIFY.require_entry_outcome(label,payload,code,{'hwnd':100,'pid':42})

    def test_precise_negative_owned_outcomes_are_accepted(self):
        QUALIFY.require_entry_outcome('helper-tree-no-match',{'status':'partial','reason':'no_matching_window'},2,{})
        QUALIFY.require_entry_outcome('helper-hit-missing',{'status':'error','reason':'missing_coords'},1,{})
        QUALIFY.require_entry_outcome('helper-hit-mismatch',{'status':'partial','root_hwnd':100,'process_id':42,'matched':False,'match_reason':'title_mismatch'},2,{'hwnd':100,'pid':42})

    def test_windows_request_cannot_fall_back_to_linux(self):
        import sys
        if sys.platform=='win32':self.skipTest('negative platform test is non-Windows only')
        with self.assertRaises(SystemExit) as raised:QUALIFY.main(['--windows'])
        self.assertEqual(raised.exception.code,2)

if __name__=='__main__':unittest.main()
