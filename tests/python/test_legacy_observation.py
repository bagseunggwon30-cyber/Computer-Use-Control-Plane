"""Historical adapter/library regression. Current Python native runtime is tested separately.

The old PowerShell helper is read from a pinned Git oracle, never production.
These structural checks are never Windows/provider proof.
"""
import copy
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest
from legacy_historical_native import helper as historical_native_helper, wrapper as historical_native_wrapper

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
        current = historical_native_helper().read_text(encoding='utf-8-sig')
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
        current = historical_native_helper().read_text(encoding='utf-8-sig')
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
        source = (ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation/WindowsObservationProvider.cs').read_text(encoding='utf-8')
        for token in ('CucpNative.WindowFromPoint','CucpNative.EnumerateTopLevel','AutomationElement.FromPoint',
                      'AutomationElement.FromHandle','TreeScope.Descendants','TryGetClickablePoint','GetCurrentPattern'):
            self.assertIn(token, source)
        for token in ('SendInput(', 'SendMouseClick(', '.Invoke()', '.Toggle()', '.Select()', '.SetValue(', 'ScriptBlock', 'PowerShell.Create'):
            self.assertNotIn(token, source)

    def test_candidate_is_opt_in_only(self):
        helper = historical_native_helper().read_text(encoding='utf-8-sig')
        self.assertIn("if ($env:CUCP_LEGACY_OBSERVATION_CANDIDATE) {",helper)
        self.assertIn("$env:CUCP_LEGACY_OBSERVATION_CANDIDATE -ne '1'",helper)
        self.assertEqual(helper.count(". (Join-Path $PSScriptRoot 'cucp-legacy-observation-adapter.ps1')"),1)
        library = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation'
        self.assertFalse(any('FixtureState' in p.read_text(encoding='utf-8') for p in library.glob('*.cs')))

    def test_fixture_cases_are_ordinary_counted_files(self):
        names=json.loads((FIXTURES/'cases.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(names),85)
        self.assertEqual(len(names),len(set(names)))
        for name in names:
            case=json.loads((FIXTURES/(name+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(name,case['Name'])
            self.assertIn(case['Operation'],('hit-test','hit-scan','uia-tree','uia-find','guard','refine','click','fusion','payload'))

    def test_mutation_tripwires_record_before_throw(self):
        source=(ROOT/'pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification/ScriptedObservation.cs').read_text(encoding='utf-8')
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
        project=(ROOT/'tests/fixtures/legacy-observation-provider-probe/ObservationProviderProbe.csproj').read_text(encoding='utf-8')
        code=(ROOT/'tests/fixtures/legacy-observation-provider-probe/ProviderLoadProbe.cs').read_text(encoding='utf-8')
        self.assertNotIn('<Reference ',project)
        self.assertNotIn('ProjectReference',project)
        self.assertIn('FirstChanceException+=Capture',code)
        self.assertIn('if(errors.Count>=256)',code)
        for token in ('AutomationElement.', 'RegisterClientSide', 'SetProxyDescription', 'SendInput(', 'SendMouseClick('):self.assertNotIn(token,code)

    def test_side_diagnostics_follow_unchanged_entry_pairs(self):
        source=(ROOT/'pcucp-next/packaging/qualify_legacy_observation.py').read_text(encoding='utf-8')
        self.assertLess(source.index('for label, arguments in cases + wrapper_cases:'),source.index("run('provider-identity-'"))
        self.assertIn("for mode in ('original', 'candidate', 'shared-current'):",source)
        self.assertIn("processes.append(result)",source)

    def test_intended_oracle_changes_only_one_counted_insertion(self):
        raw, _ = QUALIFY.source_bytes()
        hook = (ROOT/'tests/fixtures/legacy-observation-intended-initialization.ps1').read_bytes()
        corrected = QUALIFY.with_intended_initialization(raw)
        self.assertEqual(corrected.replace(hook,b'',1),raw)
        self.assertEqual(corrected.count(hook),1)
        for path in ('scripts/cucp-native-helper.ps1','scripts/cucp-legacy-observation-adapter.ps1'):
            self.assertNotIn('CUCP_OBSERVATION_INTENDED', (historical_native_helper() if path.endswith('cucp-native-helper.ps1') else ROOT/path).read_text(encoding='utf-8-sig'))
        with self.assertRaises(AssertionError):QUALIFY.with_intended_initialization(raw+b'switch ($Action) {')

    def test_intended_initializer_uses_one_public_read_without_proxy_changes(self):
        code=(ROOT/'tests/fixtures/legacy-observation-intended-provider/PublicUiaInitialization.cs').read_text(encoding='utf-8')
        self.assertEqual(code.count('AutomationElement.FromHandle('),1)
        for token in ('RegisterClientSide','SetProxy','GetField(', 'BindingFlags', 'DynamicMethod','SendInput(','.Invoke()', '.SetValue('):self.assertNotIn(token,code)
        source=(ROOT/'tests/fixtures/legacy-observation-intended-initialization.ps1').read_text(encoding='utf-8')
        self.assertIn('NativeWindowHandle -ne $intendedReady.hwnd',source)
        self.assertIn('ProcessId -ne $intendedReady.pid',source)

    def test_intended_tier_does_not_replace_raw_original_or_waive_planner(self):
        source=(ROOT/'pcucp-next/packaging/qualify_legacy_observation.py').read_text(encoding='utf-8')
        self.assertLess(source.index('for label, arguments in cases + wrapper_cases:'),source.index("for temperature in ('cold','warm'):"))
        self.assertIn("'wrapper-smart-plan: scalar proof and actual completed cold/warm route pending'",source)
        self.assertIn("intended.get('scalar_capture_proof') == 'passed'",source)
        self.assertIn('intended_cases = cases + wrapper_cases + [',source)
        self.assertIn("compare_entry(*pair)",source)

    def test_pre_fix_wrapper_is_exact_and_production_diff_is_two_scalar_copies(self):
        raw, manifest = QUALIFY.wrapper_source_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['windows_sha256'])
        current=historical_native_wrapper().read_text(encoding='utf-8-sig').replace('\r\n','\n')
        for name in ('raw','err'):
            line=f'    if (${name} -is [string]) {{ ${name} = [string]::new(${name}.ToCharArray()) }}\n'
            self.assertEqual(current.count(line),1)
            current=current.replace(line,'',1)
        self.assertEqual(current,raw.decode('utf-8-sig').replace('\r\n','\n'))

    def test_intended_identity_checks_real_button_edit_types_and_handles(self):
        source=(ROOT/'tests/fixtures/legacy-observation-provider-diagnostic.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('[System.Windows.Automation.Automation]::Compare($ownedElement,$nativeElement)',source)
        self.assertIn('$provider.Pattern($ownedElement,$patternKind)',source)
        self.assertIn('$provider.Bounds($ownedCurrent)',source)
        self.assertIn('$provider.ValueReadOnly($ownedPattern)',source)
        self.assertNotIn('ConvertFrom-Json $owned',source)

    def test_smart_plan_phase_probe_is_opt_in_and_keeps_raw_source(self):
        driver=(ROOT/'tests/fixtures/legacy-observation-wrapper.ps1').read_text(encoding='utf-8-sig')
        trace=(ROOT/'tests/fixtures/legacy-observation-smart-plan-trace.ps1').read_text(encoding='utf-8')
        self.assertIn('if($TraceSmartPlan)',driver)
        self.assertIn('Set-PSBreakpoint -Script $wrapper -Line $point.Line -Action $action',trace)
        self.assertIn('Get-ObservationTraceSourceHash',trace)
        self.assertIn('$stream.Flush($true)',trace)
        self.assertNotIn('Set-Content',trace)
        self.assertNotIn('ConvertTo-Json -InputObject $value',trace)
        gate=(ROOT/'pcucp-next/packaging/qualify_legacy_observation.py').read_text(encoding='utf-8')
        self.assertIn("'wrapper_sha256_after_process':after_hash",gate)

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


class IntendedVerdictTests(unittest.TestCase):
    def scalar_fixture(self):
        rich='한글 😀 "quote" C:\\owned\r\nNUL=\x00 tail'
        ok=json.dumps(dict(status='ok',text=rich,count=7,enabled=True,absent=None))
        cases=[('missing-both','','',False,False),('empty-both',None,None,False,False),
            ('missing-stdout-rich-stderr','',rich,False,True),('empty-stdout-missing-stderr',None,'',False,False),
            ('ok-json-rich-stderr',ok,rich,True,True),('partial-json','{"status":"partial","items":[]}',None,True,False),
            ('error-json','{"status":"error"}',rich,True,True),('nonzero-exit-preserved','{"status":"partial"}',rich,True,True),
            ('rich-raw-invalid-json',rich,rich,True,True),('whitespace-raw',' \t\r\n','',True,False),
            ('memory-null',None,None,False,False),('memory-empty','','',False,False),('memory-lone-surrogates','A\ud800Z','B\udc00Y',False,False)]
        def evidence(value,decorated):
            encoded=None if value is None else base64.b64encode(value.encode('utf-16le',errors='surrogatepass')).decode()
            after=dict(is_null=value is None,type='null' if value is None else 'System.String',properties=[] if value is None else ['Length'],utf16_length=None if value is None else len(value.encode('utf-16le',errors='surrogatepass'))//2,utf16le_base64=encoded)
            before=copy.deepcopy(after)
            if decorated:before['properties']=['PSDrive','PSProvider','Length']
            return dict(before=before,after=after,fresh_reference=True if value else None,exact_utf16=True,provider_expected=decorated)
        rows=[]
        for name,raw,err,raw_decorated,err_decorated in cases:
            initial=1 if name=='missing-stdout-rich-stderr' else 17 if name=='nonzero-exit-preserved' else 9 if name=='memory-lone-surrogates' else 0
            code={'partial-json':2,'error-json':1}.get(name,initial)
            data=json.loads(raw) if name in ('ok-json-rich-stderr','partial-json','error-json','nonzero-exit-preserved') else None
            lone=name=='memory-lone-surrogates'
            encoded=None if lone else json.dumps({'args':{'captured_replies':[{'result':dict(Raw=raw,Err=err,ExitCode=code,Json=data)}]}})
            rows.append(dict(id=name,raw=evidence(raw,raw_decorated),err=evidence(err,err_decorated),initial_exit=initial,exit_code=code,json_present=data is not None,json_status=None if data is None else data['status'],json_round_trip=not lone,surrogate_memory_only=lone,copied_capture_json=encoded))
        nonstrings=[]
        for name,types,values in [('int-and-bool',('System.Int32','System.Boolean'),(17,True)),('long-and-double',('System.Int64','System.Double'),(9007199254740993,2.5)),('object-and-array',('System.Management.Automation.PSCustomObject','System.Object[]'),(None,None))]:
            nonstrings.append(dict(id=name,**{field:dict(before_type=typ,after_type=typ,value_preserved=True,same_reference=value is None,scalar_value=value) for field,typ,value in zip(('raw','err'),types,values)}))
        return dict(schema='cucp.observation-scalar-capture/v1',status='ok',source_unchanged=True,wrapper_sha256='abc',powershell='5.1.1',source_statements=[f'if (${name} -is [string]) {{ ${name} = [string]::new(${name}.ToCharArray()) }}' for name in ('raw','err')],serialized_captures=12,decorated_fields=11,cases=rows,non_string_cases=nonstrings)

    def test_scalar_capture_verdict_accepts_complete_exact_text_and_nonstrings(self):
        QUALIFY.require_scalar_capture(self.scalar_fixture(),'abc')

    def test_scalar_capture_verdict_rejects_lost_metadata_text_types_and_status(self):
        for mutation in ('metadata','utf16','fresh-reference','exit','parsed-json','non-string','missing-case','missing-type'):
            with self.subTest(mutation=mutation):
                payload=self.scalar_fixture()
                if mutation=='metadata':payload['cases'][4]['raw']['after']['properties'].append('PSDrive')
                elif mutation=='utf16':payload['cases'][4]['raw']['after']['utf16le_base64']='QQA='
                elif mutation=='fresh-reference':payload['cases'][4]['raw']['fresh_reference']=False
                elif mutation=='exit':payload['cases'][5]['exit_code']=0
                elif mutation=='parsed-json':
                    row=payload['cases'][4];capture=json.loads(row['copied_capture_json']);capture['args']['captured_replies'][0]['result']['Json']['count']=8;row['copied_capture_json']=json.dumps(capture)
                elif mutation=='non-string':payload['non_string_cases'][2]['raw']['same_reference']=False
                elif mutation=='missing-type':del payload['cases'][4]['raw']['after']['type']
                else:payload['cases'].pop()
                with self.assertRaises(AssertionError):QUALIFY.require_scalar_capture(payload,'abc')

    def identity_fixture(self):
        framework=', UIAutomationClient, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35'
        ready={'pid':42,'run':dict(x=168,y=201,width=130,height=40,center_x=233,center_y=221),
               'edit':dict(x=328,y=281,width=270,height=20,center_x=463,center_y=291)}
        rows=[]
        for control,identity,role,name,pattern in [('run','RunButton','button','Run 한글','InvokePattern'),('edit','FixtureEdit','edit','Fixture value','ValuePattern')]:
            g=ready[control]
            rows.append(dict(control=control,point_x=g['center_x'],point_y=g['center_y'],expected_hwnd=100,original_hwnd=100,candidate_hwnd=100,
                original_pid=42,candidate_pid=42,automation_identity=True,element_type='System.Windows.Automation.AutomationElement'+framework,
                current_type='System.Windows.Automation.AutomationElement+AutomationElementInformation'+framework,
                direct_bounds=dict(X=float(g['x']),Y=float(g['y']),Width=float(g['width']),Height=float(g['height']),IsEmpty=False),
                payload=dict(automation_id=identity,role=role,name=name,rect={k:g[k] for k in ('x','y','width','height')}),
                pattern_type='System.Windows.Automation.'+pattern+framework,value_readonly=True if control=='edit' else None))
        return dict(error=None,first_chance_dropped=0,first_chance_uia=[],owned_object_boundaries=rows),ready

    def test_intended_identity_requires_complete_independent_evidence(self):
        payload,ready=self.identity_fixture()
        QUALIFY.require_intended_identity(payload,ready)

    def test_intended_identity_rejects_missing_types_and_geometry(self):
        for control in (0,1):
            for path in [('element_type',),('current_type',),('direct_bounds',),('direct_bounds','X'),('direct_bounds','IsEmpty'),('payload','rect'),('payload','rect','width')]:
                with self.subTest(control=control,path=path):
                    payload,ready=self.identity_fixture();node=payload['owned_object_boundaries'][control]
                    for key in path[:-1]:node=node[key]
                    del node[path[-1]]
                    with self.assertRaises(AssertionError):QUALIFY.require_intended_identity(payload,ready)

    def test_intended_identity_rejects_altered_types_and_geometry(self):
        for path,value in [(('element_type',),'System.Object'),(('current_type',),'System.Management.Automation.PSCustomObject'),
                           (('direct_bounds','X'),999), (('direct_bounds','Height'),float('nan')), (('direct_bounds','IsEmpty'),True),
                           (('payload','rect','x'),169), (('payload','rect','width'),True)]:
            with self.subTest(path=path,value=value):
                payload,ready=self.identity_fixture();node=payload['owned_object_boundaries'][0]
                for key in path[:-1]:node=node[key]
                node[path[-1]]=value
                with self.assertRaises(AssertionError):QUALIFY.require_intended_identity(payload,ready)
        payload,ready=self.identity_fixture()
        payload['owned_object_boundaries'][0]['direct_bounds']['X']=169
        payload['owned_object_boundaries'][0]['payload']['rect']['x']=169
        with self.assertRaises(AssertionError):QUALIFY.require_intended_identity(payload,ready)

    def trace_fixture(self, complete=False):
        phases=[('wrapper.sha.before',-1),('wrapper.sha.after.install',-1),
            ('compat.serialize.enter',0),('compat.serialize.done',0),('compat.process.start',0),('compat.process.wait.done',0),
            ('native.call.enter',0),('capture.replay',1),('compat.serialize.enter',1),('compat.serialize.done',1),('compat.process.start',1),('compat.process.wait.done',1),
            ('native.call.enter',1),('native.text.read.done',1),('capture.replay',2),('compat.serialize.enter',2)]
        if complete:phases += [('compat.serialize.done',2),('compat.process.start',2),('compat.process.wait.done',2),('plan.complete',2),('wrapper.sha.after.invocation',-1)]
        rows=[]
        for index,(phase,count) in enumerate(phases):
            row=dict(phase=phase,elapsed_ms=str(index*10),captures=str(count),**{'raw.type':'System.String','raw.length':'123','raw.properties':'PSPath|PSDrive|PSProvider|Length','err.type':'null','err.length':'null','err.properties':''})
            if phase.startswith('wrapper.sha.'):row['wrapper_sha256']='abc'
            rows.append(row)
        result=dict(timed_out=not complete,exit_code=0 if complete else 1,elapsed_ms=1200 if complete else 60050,launch_error=None,kill_error=None,drain_incomplete=False,running=False,stdin_error=None,read_errors={},truncated={'stdout':False,'stderr':False},stdout=b'{"schema":"cucp.smart-plan/v1","status":"ok","safe_to_act":true}')
        return rows,result

    def encode_trace(self,rows):
        return ('\n'.join('cucp.smart-plan-trace/v1\t'+'\t'.join(k+'='+str(v) for k,v in row.items()) for row in rows)+'\n').encode()

    def test_smart_plan_trace_classifies_only_instrumented_timeout_or_complete_plan(self):
        for complete,status in [(False,'captured-expected-serialization-timeout'),(True,'captured-completed-plan')]:
            rows,result=self.trace_fixture(complete)
            self.assertEqual(QUALIFY.require_smart_plan_trace(self.encode_trace(rows),result,'abc')['status'],status)

    def test_smart_plan_trace_rejects_before_only_and_early_driver_failure(self):
        rows,result=self.trace_fixture()
        for length in (0,1,2,5,12,14):
            with self.subTest(length=length):
                for timeout in (False,True):
                    result['timed_out']=timeout
                    with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(rows[:length]),result,'abc')
        result['timed_out']=False
        with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(rows),result,'abc')

    def test_smart_plan_trace_rejects_missing_native_capture_and_raw_metadata(self):
        rows,result=self.trace_fixture()
        for index in (6,7,12,13,14):
            with self.subTest(missing_index=index):
                altered=copy.deepcopy(rows);del altered[index]
                with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(altered),result,'abc')
        for field,value in [('raw.type','null'),('raw.length','0'),('raw.properties','Length'),('captures','1')]:
            altered=copy.deepcopy(rows);altered[-1][field]=value
            with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(altered),result,'abc')

    def test_smart_plan_trace_rejects_bad_hash_order_and_process_evidence(self):
        rows,result=self.trace_fixture()
        with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(rows),result,'changed')
        reordered=copy.deepcopy(rows);reordered[8],reordered[9]=reordered[9],reordered[8]
        with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(reordered),result,'abc')
        for field,value in [('elapsed_ms',50000),('running',True),('kill_error','failed'),('drain_incomplete',True),('read_errors',{'stdout':'failed'}),('truncated',{'stderr':True})]:
            altered=copy.deepcopy(result);altered[field]=value
            with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(rows),altered,'abc')

    def test_smart_plan_completed_trace_rejects_failure_exit_or_invalid_envelope(self):
        rows,result=self.trace_fixture(True)
        for field,value in [('exit_code',1),('stdout',b'{}')]:
            altered=copy.deepcopy(result);altered[field]=value
            with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(rows),altered,'abc')
        del rows[-1]
        with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(self.encode_trace(rows),result,'abc')

    def test_exact_observed_windows_phase_sequences_are_retained_and_classified(self):
        folder=FIXTURES/'observed-smart-plan-37120978323'
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        for record in manifest['records']:
            self.assertEqual(hashlib.sha256((folder/record['file']).read_bytes()).hexdigest(),record['sha256'])
        for mode in ('original','candidate'):
            trace=(folder/(mode+'-phases.txt')).read_bytes()
            result=json.loads((folder/(mode+'-process.json')).read_bytes())
            self.assertEqual(trace,base64.b64decode(result['stderr_base64']))
            verdict=QUALIFY.require_smart_plan_trace(trace,result,'e45d872e18d61e01027397bf72dc206c026f1fdcbe1c97d3bc8d2811a8f90729')
            self.assertEqual(verdict['status'],'captured-expected-serialization-timeout')
            self.assertEqual(verdict['phase_records'],16)
            lines=trace.splitlines(keepends=True)
            for index in range(2,len(lines)):
                with self.subTest(mode=mode,missing_phase=index):
                    with self.assertRaises(AssertionError):QUALIFY.require_smart_plan_trace(b''.join(lines[:index]+lines[index+1:]),result,'e45d872e18d61e01027397bf72dc206c026f1fdcbe1c97d3bc8d2811a8f90729')

if __name__=='__main__':unittest.main()
