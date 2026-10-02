"""Read-only session framing and prevalidated terminal persistence contracts."""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_legacy_precision_parity import fixtures, runner_command


def encode(value):
    if isinstance(value,list):return dict(kind='array',items=[encode(v) for v in value])
    if isinstance(value,dict):return dict(kind='object',properties=[dict(name=k,value=encode(v)) for k,v in value.items()])
    return dict(kind='scalar',value=value)


def decode(wire):
    if wire['kind']=='scalar':return wire['value']
    if wire['kind']=='array':return [decode(v) for v in wire['items']]
    return {p['name']:decode(p['value']) for p in wire['properties']}


def frames(value,request_id):
    raw=json.dumps(encode(value),ensure_ascii=True,separators=(',',':')).encode()
    return [json.dumps(dict(kind='part',id=request_id,data=base64.b64encode(raw[i:i+49152]).decode()))+'\n' for i in range(0,len(raw),49152)]+[json.dumps(dict(kind='end',id=request_id))+'\n']


def receive(proc):
    chunks=[];target=None;request_id=None
    while True:
        line=proc.stdout.readline()
        if not line:raise AssertionError('Session closed before terminal outcome: '+proc.stderr.read())
        frame=json.loads(line)
        if target is None:target=frame['target'];request_id=frame['id']
        if frame['target']!=target or frame['id']!=request_id:raise AssertionError('Interleaved precision message')
        if frame['kind']=='end':return target,request_id,decode(json.loads(b''.join(chunks)))
        chunk=base64.b64decode(frame['data'])
        if len(chunk)>49152:raise AssertionError('Unbounded precision output chunk')
        chunks.append(chunk)


def startup(fixture,root):
    args={k:copy.deepcopy(fixture[k]) for k in ('rest','cache_seconds','brief','now','history_max')}
    args.update(elapsed_ms=0,history_file=str(root/'history.jsonl'),cache_dir=str(root/'cache'))
    return dict(schema='cucp.precision-session/v1',operation=fixture['operation'],args=encode(args),culture='en-US')


@unittest.skipUnless(os.environ.get('CUCP_PRECISION_DOTNET') or shutil.which('dotnet'),'Requires .NET SDK session runner')
class PrecisionTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='CUCP precision protocol ')
        cls.root=Path(cls.temp.name);cls.command=runner_command(cls.root)+['--session-fixture']
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def spawn(self,fixture,root):
        proc=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        proc.stdin.write(json.dumps(startup(fixture,root),ensure_ascii=True)+'\n');proc.stdin.flush();return proc
    def finish(self,proc):
        proc.stdin.close();proc.wait(timeout=20)
        stderr=proc.stderr.read();proc.stdout.close();proc.stderr.close();return proc.returncode,stderr
    def reply(self,proc,request_id,value):
        for line in frames(dict(state='ok',value=value),request_id):proc.stdin.write(line)
        proc.stdin.flush()
    def test_read_order_true_arrays_and_large_history_before_one_terminal_write(self):
        fixture=next(f for f in fixtures() if f['operation']=='coord-anchor' and '--record-history' in f['rest'])
        fixture=copy.deepcopy(fixture);fixture['mapping']['warnings']=['single']
        with tempfile.TemporaryDirectory(prefix='CUCP precision commit ') as tmp:
            root=Path(tmp);proc=self.spawn(fixture,root)
            target,i,q=receive(proc);self.assertEqual((target,q['kind']),('read','coord-map'));self.reply(proc,i,fixture['mapping'])
            target,i,q=receive(proc);self.assertEqual((target,q['kind']),('read','history-lines'))
            lines=[json.dumps(dict(anchor_id=str(n),extra='x'*4000)) for n in range(500)]
            self.assertGreater(len(json.dumps(lines)),1048576);self.reply(proc,i,lines)
            target,i,state=receive(proc);self.assertEqual(target,'prepare');self.assertFalse((root/'history.jsonl').exists())
            self.assertEqual(state['payload']['warnings'],['single']);self.assertEqual(state['payload']['reuse_history']['total_records'],500)
            record=state['effects'][0]['args']['record'];serialized=json.dumps(record,ensure_ascii=False,separators=(',',':'))
            self.reply(proc,i,dict(serialized=serialized));target,i,receipt=receive(proc);self.assertEqual(target,'commit-ready');self.assertFalse((root/'history.jsonl').exists());self.reply(proc,i,receipt);target,i,outcome=receive(proc)
            self.assertEqual((target,outcome),('committed',dict(recorded=True)));self.assertEqual(self.finish(proc)[0],0)
            self.assertEqual((root/'history.jsonl').read_text(encoding='utf-8-sig'),serialized+'\n')
    def test_abort_prepare_has_no_write(self):
        fixture=next(f for f in fixtures() if f['operation']=='coord-anchor' and '--record-history' in f['rest'])
        with tempfile.TemporaryDirectory(prefix='CUCP precision abort ') as tmp:
            root=Path(tmp);proc=self.spawn(fixture,root)
            for reply in (fixture['mapping'],[]):
                target,i,_=receive(proc);self.assertEqual(target,'read');self.reply(proc,i,reply)
            target,i,_=receive(proc);self.assertEqual(target,'prepare');proc.stdin.close()
            target,_,error=receive(proc);self.assertEqual(target,'error');self.assertIn('closed',error['error']);proc.wait(timeout=20)
            self.assertFalse((root/'history.jsonl').exists());proc.stdout.close();proc.stderr.close()
    def test_terminal_serialization_cannot_change_identity(self):
        fixture=next(f for f in fixtures() if f['operation']=='coord-anchor' and '--record-history' in f['rest'])
        with tempfile.TemporaryDirectory(prefix='CUCP precision identity ') as tmp:
            root=Path(tmp);proc=self.spawn(fixture,root)
            for reply in (fixture['mapping'],[]):
                _,i,_=receive(proc);self.reply(proc,i,reply)
            _,i,state=receive(proc);record=state['effects'][0]['args']['record'];record['anchor_id']='different'
            self.reply(proc,i,dict(serialized=json.dumps(record)));target,_,error=receive(proc)
            self.assertEqual(target,'error');self.assertIn('prevalidated',error['error']);self.assertNotEqual(self.finish(proc)[0],0);self.assertFalse((root/'history.jsonl').exists())
    def test_guard_mismatch_never_requests_scan_cache_or_commit(self):
        fixture=next(f for f in fixtures() if f['operation']=='point-plan');fixture=copy.deepcopy(fixture)
        with tempfile.TemporaryDirectory(prefix='CUCP precision guard ') as tmp:
            proc=self.spawn(fixture,Path(tmp));target,i,q=receive(proc);self.assertEqual(q['kind'],'hit-test');self.reply(proc,i,dict(status='ok',matched=False))
            target,i,q=receive(proc);self.assertEqual(q['kind'],'coord-profile');self.reply(proc,i,fixture['profile'])
            target,_,state=receive(proc);self.assertEqual(target,'complete');self.assertEqual(state['payload']['reason'],'fast_guard_mismatch');self.assertEqual(state['effects'],[]);self.assertEqual(self.finish(proc)[0],2)
    def test_malformed_reply_stops_before_next_acquisition(self):
        fixture=next(f for f in fixtures() if f['operation']=='point-plan')
        with tempfile.TemporaryDirectory(prefix='CUCP precision malformed ') as tmp:
            proc=self.spawn(fixture,Path(tmp));_,i,_=receive(proc)
            proc.stdin.write(json.dumps(dict(kind='end',id=i+1))+'\n');proc.stdin.flush()
            target,_,state=receive(proc);self.assertEqual(target,'error');self.assertIn('outstanding',state['error']);self.assertEqual(self.finish(proc)[0],1)
    def test_later_reply_bom_is_rejected_without_acquisition_or_write(self):
        fixture=next(f for f in fixtures() if f['operation']=='coord-anchor' and '--record-history' in f['rest'])
        with tempfile.TemporaryDirectory(prefix='CUCP precision later BOM ') as tmp:
            root=Path(tmp);proc=self.spawn(fixture,root);_,i,_=receive(proc)
            reply=frames(dict(state='ok',value=fixture['mapping']),i)
            proc.stdin.write('\ufeff'+reply[0]);proc.stdin.flush()
            target,_,state=receive(proc);self.assertEqual(target,'error');self.assertEqual(state['queries'][0]['kind'],'coord-map')
            self.assertEqual(len(state['queries']),1);self.assertEqual(self.finish(proc)[0],1);self.assertFalse((root/'history.jsonl').exists())
    @unittest.skipUnless(sys.platform=='win32','Requires .NET Framework Process stdin characterization')
    def test_framework_emits_input_bom_before_replacement_writer(self):
        with tempfile.TemporaryDirectory(prefix='CUCP precision Framework BOM ') as tmp:
            root=Path(tmp);config=root/'command.json'
            config.write_text(json.dumps(dict(exe=self.command[0],dll=self.command[1])),encoding='utf-8-sig')
            script=root/'bom.ps1';script.write_text(r'''param([string]$Config)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$c=Get-Content -LiteralPath $Config -Raw -Encoding UTF8|ConvertFrom-Json
$previous=[Console]::InputEncoding;$process=New-Object Diagnostics.Process;$writer=$null
try{
 [Console]::InputEncoding=New-Object Text.UTF8Encoding($true)
 $psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName=$c.exe;$psi.Arguments='"'+$c.dll+'" --stdin-prefix-fixture'
 $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
 $process.StartInfo=$psi;[void]$process.Start()
 $writer=New-Object IO.StreamWriter -ArgumentList @($process.StandardInput.BaseStream,(New-Object Text.UTF8Encoding($false)))
 $writer.Write('abc');$writer.Flush();$writer.Close()
 $output=$process.StandardOutput.ReadToEnd();$errorText=$process.StandardError.ReadToEnd();$process.WaitForExit()
 if($process.ExitCode -ne 0){throw $errorText}
 [Console]::Out.Write($output)
}finally{if($writer){$writer.Dispose()};$process.Dispose();[Console]::InputEncoding=$previous}
''',encoding='utf-8-sig')
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-Config',str(config)],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'));self.assertEqual(json.loads(result.stdout.decode('utf-8-sig')),[239,187,191])
    def test_history_write_failure_is_bounded_false_commit(self):
        fixture=next(f for f in fixtures() if f['operation']=='coord-anchor' and '--record-history' in f['rest'])
        with tempfile.TemporaryDirectory(prefix='CUCP precision failed ') as tmp:
            root=Path(tmp);(root/'blocked').write_text('block',encoding='utf-8');proc=self.spawn(fixture,root/'blocked')
            for reply in (fixture['mapping'],[]):
                _,i,_=receive(proc);self.reply(proc,i,reply)
            _,i,state=receive(proc);self.reply(proc,i,dict(serialized=json.dumps(state['effects'][0]['args']['record'])))
            target,i,receipt=receive(proc);self.assertEqual(target,'commit-ready');self.reply(proc,i,receipt);target,_,value=receive(proc);self.assertEqual((target,value),('committed',dict(recorded=False)));self.assertEqual(self.finish(proc)[0],0);self.assertEqual((root/'blocked').read_text(),'block')

    def test_pure_helper_completes_large_records_without_read_or_write_effects(self):
        record=dict(anchor_id='same',target_match='W',normalized_window_point=dict(x=.5,y=.5),safe_to_reuse=True,coordinate_risk='low',coord_signature='one')
        records=[dict(record,extra='x'*3000) for _ in range(500)]
        request=dict(schema='cucp.precision-session/v1',operation='history-score',args=encode(dict(record=record,records=records,tolerance=.012,history_file='H')),culture='en-US')
        raw=json.dumps(request,ensure_ascii=True)+'\n';self.assertGreater(len(raw),1048576);self.assertLess(len(raw),4194304)
        proc=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        proc.stdin.write(raw);proc.stdin.flush();target,_,state=receive(proc)
        self.assertEqual(target,'complete');self.assertEqual(state['payload']['score'],100);self.assertEqual(state['queries'],[]);self.assertEqual(state['effects'],[]);self.assertEqual(self.finish(proc)[0],0)
    def test_storage_operation_is_not_available_through_planner_command(self):
        request=dict(schema='cucp.precision-session/v1',operation='cache-write',args=encode(dict(cache_dir='blocked',key='a'*32,serialized='{}')),culture='en-US')
        proc=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        proc.stdin.write(json.dumps(request)+'\n');proc.stdin.flush();target,_,state=receive(proc)
        self.assertEqual(target,'error');self.assertIn('pure precision helper',state['error']);self.assertEqual(self.finish(proc)[0],1)
    def test_depth_projection_uses_only_cutoff_string_conversion_and_exact_precommit(self):
        fixture=copy.deepcopy(next(f for f in fixtures() if f['operation']=='point-plan'))
        deep=dict(text='last',items=[1,None,True])
        for _ in range(20):deep=dict(nested=deep)
        fixture['scan']['Json']['best']['deep']=deep
        with tempfile.TemporaryDirectory(prefix='CUCP precision deep ') as tmp:
            root=Path(tmp);(root/'cache').mkdir();proc=self.spawn(fixture,root)
            for expected,value in (('hit-test',fixture['precheck']),('coord-profile',fixture['profile']),('cache-read',None),('hit-scan',fixture['scan'])):
                target,i,q=receive(proc);self.assertEqual((target,q['kind']),('read',expected));self.reply(proc,i,value)
            conversions={}
            while True:
                target,i,value=receive(proc)
                if target=='prepare':state=value;break
                self.assertEqual((target,value['kind']),('read','json-string'))
                key=json.dumps(value['args']['value'],sort_keys=True)
                conversions[key]='stringified:'+key
                self.reply(proc,i,conversions[key])
            self.assertTrue(conversions)
            def project(value,depth=0):
                if isinstance(value,(dict,list)) and depth>14:return conversions[json.dumps(value,sort_keys=True)]
                if isinstance(value,dict):return {k:project(v,depth+1) for k,v in value.items()}
                if isinstance(value,list):return [project(v,depth+1) for v in value]
                return value
            payload=project(state['payload']);serialized=json.dumps(payload)
            self.reply(proc,i,dict(serialized=serialized));target,i,receipt=receive(proc);self.assertEqual(target,'commit-ready');self.reply(proc,i,receipt)
            target,_,value=receive(proc);self.assertEqual((target,value),('committed',dict(recorded=None)));self.assertEqual(self.finish(proc)[0],0)
            cache=next((root/'cache').iterdir());self.assertEqual(json.loads(cache.read_text(encoding='utf-8-sig')),payload)
    def test_nonidentity_terminal_change_is_rejected_before_write(self):
        fixture=next(f for f in fixtures() if f['operation']=='coord-anchor' and '--record-history' in f['rest'])
        with tempfile.TemporaryDirectory(prefix='CUCP precision nonidentity ') as tmp:
            root=Path(tmp);proc=self.spawn(fixture,root)
            for reply in (fixture['mapping'],[]):
                _,i,_=receive(proc);self.reply(proc,i,reply)
            _,i,state=receive(proc);record=state['effects'][0]['args']['record'];record['safe_to_reuse']=not record['safe_to_reuse']
            self.reply(proc,i,dict(serialized=json.dumps(record)));target,_,value=receive(proc)
            self.assertEqual(target,'error');self.assertIn('prevalidated',value['error']);self.assertEqual(self.finish(proc)[0],1);self.assertFalse((root/'history.jsonl').exists())

    def test_separate_storage_command_uses_fixed_initial_paths_and_prebuilt_result(self):
        with tempfile.TemporaryDirectory(prefix='CUCP precision storage command ') as tmp:
            root=Path(tmp);path=root/'history.jsonl'
            request=dict(schema='cucp.precision-storage/v1',operation='history-append',args=encode(dict(history_file=str(path),maximum=500,serialized='{"value":[1,2],"Count":2}')),culture='en-US')
            command=self.command[:-1]+['--storage-session-fixture']
            proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
            proc.stdin.write(json.dumps(request)+'\n');proc.stdin.flush();target,_,state=receive(proc)
            self.assertEqual((target,state['payload']),('complete',True));self.assertEqual(self.finish(proc)[0],0)
            self.assertEqual(path.read_text(encoding='utf-8-sig'),'{"value":[1,2],"Count":2}\n')
            request.update(operation='history-file-read',args=encode(dict(history_file=str(path),last=500)))
            proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
            proc.stdin.write(json.dumps(request)+'\n');proc.stdin.flush();target,_,state=receive(proc)
            self.assertEqual(state['payload'],[dict(value=[1,2],Count=2)]);self.assertEqual(self.finish(proc)[0],0)
