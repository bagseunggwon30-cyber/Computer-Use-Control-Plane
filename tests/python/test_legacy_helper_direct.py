"""Explicit direct modes; generated owned peers/files only, no desktop provider."""
from datetime import datetime,timezone
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from helper_process_evidence import OwnedProcess,run_evidence,require_success
from pcucp_cli.legacy_helper_client import inspect_lock,LockSnapshot

ROOT=Path(__file__).resolve().parents[2]


class DirectHelperPortableTests(unittest.TestCase):
    def test_observed_short_path_failure_and_package_provenance_remain_exact(self):
        directory=ROOT/'tests/fixtures/legacy-helper/observed-direct-path'
        raw=(directory/'manifest.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'1f761b60d627f2d1aa598c7015b1ac32fbb90217ef5adf786800368874bd4fc1')
        manifest=json.loads(raw);self.assertEqual(manifest['status'],'failed-unqualified')
        for name,record in manifest['files'].items():
            data=(directory/name).read_bytes()
            self.assertEqual(len(data),record['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
        failed=json.loads((directory/'failed-start.json').read_bytes())
        self.assertEqual(failed['exit_code'],1);self.assertFalse(failed['timed_out'])
        self.assertIn('RUNNER~1',failed['argv'][failed['argv'].index('--lock-file')+1])
        self.assertEqual((directory/'failed-start.stderr.bin').read_bytes(),
                         b'ArgumentException: direct lock path must not require normalization\r\n')
        self.assertIn(b'FAILED (failures=10)',(directory/'failed-suite.stderr.bin').read_bytes())
        package=json.loads((directory/'package-manifest.json').read_bytes())
        closure=json.loads((directory/'package-build-closure.json').read_bytes())
        self.assertEqual(package['files'],{name:closure['build_output'][name] for name in closure['included']})

    def test_converting_checkout_preserves_every_direct_observation_and_manifest(self):
        source=ROOT/'tests/fixtures/legacy-helper/observed-direct-path'
        with tempfile.TemporaryDirectory(prefix='direct-observed-checkout-') as temporary:
            root=Path(temporary);target=root/source.relative_to(ROOT);target.mkdir(parents=True)
            originals={item.name:item.read_bytes() for item in source.iterdir()}
            for name,data in originals.items(): (target/name).write_bytes(data)
            (root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            control=root/'unprotected-manifest.json';control.write_bytes(originals['manifest.json'])
            def git(*arguments):
                return subprocess.run(['git','-c','core.autocrlf=true','-c','core.eol=crlf','-c','core.safecrlf=false',
                    '-c',f'core.attributesFile={os.devnull}',*arguments],cwd=root,capture_output=True,check=True,timeout=30)
            git('init','--quiet');git('add','--force','--','.gitattributes',source.relative_to(ROOT).as_posix(),control.name)
            for name in originals: (target/name).unlink()
            control.unlink();git('checkout-index','--force','--all')
            for name,data in originals.items(): self.assertEqual((target/name).read_bytes(),data)
            self.assertEqual(control.read_bytes(),originals['manifest.json'].replace(b'\n',b'\r\n'))
            self.assertNotEqual(control.read_bytes(),originals['manifest.json'])

    def test_custom_direct_record_remains_unusable_for_automatic_discovery(self):
        record=dict(pid=123,pipe_name='explicit-custom',owner_user='owned',helper_version='2.0.0',started_at='2026-01-01T00:00:00Z')
        state=inspect_lock(LockSnapshot(json.dumps(record).encode(),(1,2,3)),owner_user='owned',
            now=datetime(2026,1,1,tzinfo=timezone.utc),process_alive=lambda pid:pid==123)
        self.assertFalse(state.usable);self.assertEqual(state.reason,'invalid_pipe_name')

    def test_gate_requires_explicit_owned_windows_selection_despite_inherited_flag(self):
        import importlib.util
        import io
        from contextlib import redirect_stdout,redirect_stderr
        from unittest.mock import patch
        for module,variants in (('qualify_legacy_helper.py',[((),False),(('--windows',),True)]),
            ('qualify_staged_legacy_helper.py',[((),False),(('--direct',),False),(('--windows',),False),(('--windows','--direct'),True)])):
            spec=importlib.util.spec_from_file_location('owned_gate_selection',ROOT/'pcucp-next/packaging'/module)
            gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
            for argv,wanted in variants:
                with self.subTest(module=module,argv=argv),tempfile.TemporaryDirectory(prefix='cucp-direct-gate-') as temporary:
                    calls=[]
                    def capture(command,**kwargs):
                        calls.append((command,dict(kwargs['env'])))
                        return dict(stdout=b'',stderr=b'',evidence_path='owned-gate-fixture',exit_code=0,running=False,
                            launch_error=None,timed_out=False,kill_error=None,drain_incomplete=False,stdin_error=None,
                            read_errors={},truncated={'stdout':False,'stderr':False})
                    with patch.object(gate,'run_evidence',side_effect=capture),patch.object(gate.sys,'platform','win32'), \
                         patch.dict(os.environ,{'CUCP_REQUIRE_HELPER_DIRECT':'1'}),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                        self.assertEqual(gate.main([*argv,'--log-dir',temporary]),0)
                    suites=[env for command,env in calls if 'unittest' in command]
                    self.assertTrue(suites)
                    self.assertTrue(all((env.get('CUCP_REQUIRE_HELPER_DIRECT')=='1')==wanted for env in suites))
                    if wanted:
                        self.assertTrue(all(env.get('CUCP_LEGACY_HELPER_TRANSPORT_PROBE') for env in suites))

    def test_direct_contracts_execute_actual_shared_validation_and_log_writer(self):
        host=Path(os.environ.get('CUCP_LEGACY_HELPER_CONTRACT_HOST',ROOT/'pcucp-next/dotnet/PcuCp.LegacyHelper.ContractTests/bin/Release/net8.0/PcuCp.LegacyHelper.ContractTests.dll'))
        dotnet=os.environ.get('DOTNET') or shutil.which('dotnet')
        if not dotnet or not host.is_file(): self.skipTest('Requires built actual portable helper contracts')
        with tempfile.TemporaryDirectory(prefix='cucp-direct-contracts-') as temporary:
            result=run_evidence([dotnet,str(host),'--self-test'],directory=os.environ.get('CUCP_HELPER_EVIDENCE_DIR',temporary),label='direct-portable-contracts',timeout=20)
            require_success(result)
            self.assertIn(b'Legacy helper direct contracts:',result['stdout'])
            self.assertIn(b'Passed 117 helper action contracts',result['stdout'])
            self.assertIn(b'Passed 45 helper wire contracts',result['stdout'])


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_REQUIRE_HELPER_DIRECT')=='1',
                     'Requires explicit owned Windows direct-mode gate')
class DirectHelperWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='CUCP direct owned 한글 ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR',self.root/'evidence'))
        self.host=Path(os.environ.get('CUCP_LEGACY_HELPER_TEST_HOST',ROOT/'pcucp-next/bin/legacy-helper/PcuCp.LegacyHelper.exe'))
        self.probe=Path(os.environ['CUCP_LEGACY_HELPER_TRANSPORT_PROBE'])
        self.assertTrue(self.host.is_file());self.assertTrue(self.probe.is_file())
        self.owned=[];self.serial=0;self.addCleanup(self.cleanup)
    def cleanup(self):
        for process in self.owned:
            if process.process and process.process.poll() is None: process.process.kill()
            process.finish(self.logs,'direct-owned-final',timeout=3)
    def run_host(self,args,*,expected=0,timeout=6,label='direct-cli'):
        result=run_evidence([self.host,*args],directory=self.logs,label=label,cwd=self.root,timeout=timeout)
        require_success(result,expected_exit=expected)
        return result
    def start(self,*,name=None,lock=None,idle=4000,debug=False):
        self.serial+=1
        name=name or 'cucp-owned-direct-'+uuid.uuid4().hex
        lock=lock or self.root/f'owned-{self.serial}.pid'
        command=[self.host,'serve-direct','--pipe-name',name,'--lock-file',lock,'--idle-timeout-ms',str(idle),'--diagnostic-phases','--diagnostic-acl']
        if debug: command.append('--debug-log')
        process=OwnedProcess(command,cwd=self.root);self.owned.append(process)
        process.snapshot(self.logs,'direct-started')
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            evidence=process.snapshot(self.logs,'direct-starting')
            if b'helper_phase=pipe.acl.verified' in evidence['stderr']:
                record=json.loads(lock.read_text(encoding='utf-8-sig'))
                self.assertEqual(record['pid'],process.process.pid);self.assertEqual(record['pipe_name'],name)
                return process,lock,record
            if process.process is None or process.process.poll() is not None: break
            time.sleep(.02)
        evidence=process.finish(self.logs,'direct-start-failed',timeout=.1)
        self.fail('Direct service did not become ready: '+evidence['evidence_path'])
    def exchange(self,name,request,*,expected=0,connect=1500,read=1500):
        self.serial+=1;path=self.root/f'request-{self.serial}.json'
        path.write_bytes(request if isinstance(request,bytes) else json.dumps(request,ensure_ascii=False).encode())
        return self.run_host(['exchange-direct','--pipe-name',name,'--request-file',path,
                             '--connect-timeout-ms',str(connect),'--read-timeout-ms',str(read),'--diagnostic-phases'],expected=expected,label='direct-exchange')
    def reply(self,name,action='health',**fields):
        result=self.exchange(name,dict(id=17,action=action,args={},**fields))
        return json.loads(result['stdout'].decode('utf-8-sig'))
    def finish(self,process):
        result=process.finish(self.logs,'direct-finished',timeout=6);require_success(result);return result

    def test_literal_custom_names_schema_owner_acl_and_shutdown(self):
        for suffix in ('plain','한글 공백 (a) %!&^_+=','MiXeD.Case'):
            with self.subTest(suffix=suffix):
                name='CUCP explicit literal '+uuid.uuid4().hex+'-'+suffix
                process,lock,data=self.start(name=name)
                self.assertEqual(set(data),{'pid','pipe_name','started_at','helper_version','owner_user','owner_sid'})
                first=self.reply(name);second=self.reply(name)
                self.assertEqual(first['exit_code'],0);self.assertEqual(first['id'],17)
                self.assertEqual(first['result']['pid'],process.process.pid);self.assertEqual(first['result']['pipe_name'],name)
                self.assertEqual(first['result']['request_count'],1);self.assertEqual(second['result']['request_count'],2)
                self.assertFalse(first['result']['win32_loaded'])
                self.assertTrue(self.reply(name,'shutdown')['result']['shutting_down'])
                evidence=self.finish(process);self.assertFalse(lock.exists())
                acl=[json.loads(line.split(b'=',1)[1]) for line in evidence['stderr'].splitlines() if line.startswith(b'helper_acl_evidence=')]
                self.assertGreaterEqual(len(acl),1)
                for row in acl:
                    self.assertEqual(row['owner_sid'],data['owner_sid']);self.assertTrue(row['protected']);self.assertTrue(row['canonical'])
                    self.assertEqual(len(row['aces']),1);self.assertEqual(row['aces'][0]['sid'],data['owner_sid'])
                    self.assertEqual(row['aces'][0]['type'],'AccessAllowed')
                self.assertNotIn(b'helper_debug ',evidence['stderr'])

    def alias_directories(self):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        def convert(name,path):
            function=getattr(kernel,name);function.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD];function.restype=wintypes.DWORD
            output=ctypes.create_unicode_buffer(32768)
            size=function(str(path),output,len(output))
            self.assertGreater(size,0);self.assertLess(size,len(output));return Path(output.value)
        long=convert('GetLongPathNameW',self.root);short=convert('GetShortPathNameW',long)
        self.assertNotEqual(str(short).casefold(),str(long).casefold(),'Owned gate must exercise a genuine 8.3 alias')
        self.assertTrue(os.path.samefile(short,long))
        return short,long

    def test_short_and_long_directory_aliases_share_owned_lock_and_lifetime(self):
        short,long=self.alias_directories()
        for selected,other in ((short,long),(long,short)):
            with self.subTest(selected=str(selected)):
                lock=selected/'literal-owned-한글.pid';alias=other/lock.name
                process,lock,data=self.start(lock=lock);original=lock.read_bytes()
                self.assertTrue(os.path.samefile(lock,alias));self.assertEqual(alias.read_bytes(),original)
                self.assertEqual(self.reply(data['pipe_name'])['result']['pid'],process.process.pid)
                refusal=self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,
                    '--lock-file',alias],expected=1)
                self.assertEqual(refusal['stdout'],b'');self.assertEqual(alias.read_bytes(),original)
                for directory in (short,long):
                    with self.assertRaises(OSError): directory.rename(directory.parent/('uncreated-move-'+uuid.uuid4().hex))
                self.reply(data['pipe_name'],'shutdown');self.finish(process)
                self.assertFalse(lock.exists());self.assertFalse(alias.exists())

    def test_raw_lexical_normalization_is_refused_through_short_and_long_parents(self):
        short,long=self.alias_directories();ordinary=self.root/'ordinary';ordinary.mkdir()
        for parent in (short,long):
            base=str(parent)
            for tail in ('ordinary\\.\\owned.pid','ordinary\\..\\owned.pid','ordinary\\\\owned.pid',
                         'ordinary/owned.pid','ordinary.\\owned.pid','ordinary \\owned.pid','ordinary:stream\\owned.pid',
                         'NUL\\owned.pid','COM1.log\\owned.pid','ordinary\\owned.pid:stream','ordinary\\helper.pid'):
                with self.subTest(parent=base,tail=tail):
                    result=self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,
                        '--lock-file',base+'\\'+tail],expected=1)
                    self.assertIn(b'ArgumentException: direct lock',result['stderr'])
                    self.assertEqual(result['stdout'],b'')
        self.assertEqual(list(ordinary.iterdir()),[])
        self.assertEqual({item.name for item in self.root.iterdir()}-{'evidence'},{'ordinary'})

    def test_default_modes_keep_custom_option_and_target_refusal(self):
        lock=self.root/'uncreated.pid';request=self.root/'request.json';request.write_bytes(b'{}')
        for args in (['serve','--lock-file',lock,'--pipe-name','custom'],['serve','--lock-file',lock,'--debug-log','true'],
                     ['exchange','--pipe','custom','--request-file',request]):
            result=self.run_host(args,expected=1)
            self.assertFalse(lock.exists());self.assertEqual(result['stdout'],b'')
        result=self.run_host(['exchange','--request-file',self.root/'absent-request.json'],expected=1)
        self.assertIn(b'FileNotFoundException',result['stderr'])  # Existing request-before-target precedence.

    def test_direct_closed_options_and_invalid_names_fail_before_lock(self):
        lock=self.root/'uncreated.pid'
        common=['serve-direct','--lock-file',lock]
        for name in ('','Anonymous','a\n','a/b','a\\b','a:b','a.','a ','x'*248,r'\\.\pipe\name'):
            self.run_host([*common,'--pipe-name',name],expected=1);self.assertFalse(lock.exists())
        for args in (common,['serve-direct','--pipe-name','custom'],
            [*common,'--pipe-name','custom','--pipe-name','other'],[*common,'--pipe-name','custom','--unknown','x'],
            [*common,'--pipe-name','custom','--idle-timeout-ms','-1'],[*common,'--pipe-name','custom','--debug-log','false']):
            self.run_host(args,expected=1);self.assertFalse(lock.exists())

    def test_direct_lock_refuses_discovery_devices_ads_missing_and_relative_paths(self):
        for path in ('relative.pid',self.root/'helper.pid',self.root/'HELPER-STAGED.PID',self.root/'helper.pid::$DATA',
                     self.root/'owned.pid:stream',self.root/'NUL.pid',self.root/'COM1.log',self.root/'missing/owned.pid',r'\\remote.invalid\share\owned.pid'):
            with self.subTest(path=str(path)):
                self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,'--lock-file',path],expected=1)
        self.assertEqual([p.name for p in self.root.iterdir() if p.name!='evidence'],[])

    def test_existing_lock_and_pipe_collision_never_overwrite_or_retry(self):
        existing=self.root/'owned-existing.pid';existing.write_bytes(b'preserved')
        self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,'--lock-file',existing],expected=1)
        self.assertEqual(existing.read_bytes(),b'preserved')
        process,lock,data=self.start();other=self.root/'collision.pid'
        result=self.run_host(['serve-direct','--pipe-name',data['pipe_name'],'--lock-file',other,'--debug-log'],expected=1)
        self.assertIn(b'owner-only pipe creation or verification failed',result['stderr'])
        self.assertFalse(other.exists());self.assertTrue(lock.exists())
        self.assertEqual(self.reply(data['pipe_name'])['result']['pid'],process.process.pid)
        self.reply(data['pipe_name'],'shutdown');self.finish(process)

    def test_lock_byte_edit_survives_and_lifetime_directory_lease_blocks_replacement(self):
        process,lock,data=self.start();original=lock.read_bytes();changed=original+b' '
        lock.write_bytes(changed)
        self.reply(data['pipe_name'],'shutdown');self.finish(process)
        self.assertEqual(lock.read_bytes(),changed)
        process,lock,data=self.start();original=lock.read_bytes()
        new=self.root/'replacement.pid';new.write_bytes(original)
        # The direct lifetime lease is stronger than automatic mode: do not
        # weaken it just to force a replacement fixture through. The unchanged
        # automatic transport tests separately prove cleanup's identity CAS.
        with self.assertRaises(OSError): os.replace(new,lock)
        self.assertEqual(lock.read_bytes(),original);self.assertEqual(new.read_bytes(),original)
        self.reply(data['pipe_name'],'shutdown');self.finish(process);self.assertFalse(lock.exists())

    def test_zero_idle_success_and_negative_refusal_remain_separate(self):
        for value,code in ((0,0),(-1,1),(-2147483648,1)):
            lock=self.root/f'idle-{value}.pid'
            self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,
                           '--lock-file',lock,'--idle-timeout-ms',str(value)],expected=code)
            self.assertFalse(lock.exists())

    def test_request_cannot_elevate_default_provider_or_enable_logging(self):
        process,lock,data=self.start()
        result=self.exchange(data['pipe_name'],dict(id='secret-id',action='windows',args=dict(allow_readonly_desktop=True,debug_log=True)))
        self.assertEqual(json.loads(result['stdout'].decode('utf-8-sig'))['exit_code'],1)
        health=self.reply(data['pipe_name']);self.assertFalse(health['result']['win32_loaded'])
        self.reply(data['pipe_name'],'shutdown');evidence=self.finish(process)
        self.assertNotIn(b'helper_debug ',evidence['stderr']);self.assertNotIn(b'secret-id',evidence['stderr'])

    def test_debug_metadata_is_capped_and_never_contains_raw_request_secrets(self):
        process,lock,data=self.start(debug=True)
        for i in range(48):
            result=self.exchange(data['pipe_name'],dict(id='TOKEN_SECRET_'+str(i),action='unknown\nPAYLOAD_SECRET',args=dict(secret='ARG_SECRET')))
            self.assertEqual(json.loads(result['stdout'].decode('utf-8-sig'))['exit_code'],99)
        self.reply(data['pipe_name'],'shutdown');evidence=self.finish(process)
        lines=[line for line in evidence['stderr'].splitlines() if line.startswith(b'helper_debug ')]
        self.assertEqual(len(lines),129);self.assertEqual(lines[-1],b'helper_debug event=limit')
        self.assertTrue(all(len(line)<=192 for line in lines))
        self.assertIn(b'action=other id_kind=string',b'\n'.join(lines))
        for value in (b'TOKEN_SECRET',b'PAYLOAD_SECRET',b'ARG_SECRET'): self.assertNotIn(value,evidence['stderr'])

    def test_direct_maximum_literal_name_roundtrip(self):
        prefix='cucp-owned-direct-'+uuid.uuid4().hex
        name=prefix+'x'*(247-len(prefix))
        process,lock,data=self.start(name=name)
        self.assertEqual(self.reply(name)['result']['pipe_name'],name)
        self.reply(name,'shutdown');self.finish(process);self.assertFalse(lock.exists())

    def test_retained_directory_ancestors_and_junction_refusal(self):
        ancestor=self.root/'retained-ancestor';directory=ancestor/'locks';directory.mkdir(parents=True)
        process,lock,data=self.start(lock=directory/'owned.pid')
        with self.assertRaises(OSError): ancestor.rename(self.root/'moved-ancestor')
        self.reply(data['pipe_name'],'shutdown');self.finish(process)
        target=self.root/'junction-target';target.mkdir();junction=self.root/'junction'
        command=[os.path.join(os.environ['SystemRoot'],'System32','cmd.exe'),'/d','/c','mklink','/J',str(junction),str(target)]
        created=run_evidence(command,directory=self.logs,label='direct-owned-junction',timeout=5)
        require_success(created)
        try:
            for parent in self.alias_directories():
                result=self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,
                    '--lock-file',parent/junction.name/'owned.pid'],expected=1)
                self.assertIn(b'directory must exist without reparse components',result['stderr'])
                self.assertEqual(list(target.iterdir()),[])
        finally: junction.rmdir()

    def test_fixture_and_readonly_authority_are_mutually_exclusive_before_acquisition(self):
        lock=self.root/'authority-conflict.pid'
        result=self.run_host(['serve-direct','--pipe-name','cucp-owned-direct-'+uuid.uuid4().hex,'--lock-file',lock,
                             '--fixture',self.root/'deliberately-missing.json','--allow-readonly-desktop'],expected=1)
        self.assertIn(b'fixture and desktop provider are mutually exclusive',result['stderr'])
        self.assertFalse(lock.exists())

    def peer_exchange(self,mode,*,request=b'{}',connect=500,read=300,expected=1):
        name='cucp-owned-direct-'+uuid.uuid4().hex
        ready=self.root/(name+'.ready.json');spec=self.root/(name+'.spec.json')
        spec.write_text(json.dumps(dict(mode=mode,ready=str(ready),pipe_name=name)),encoding='utf-8')
        peer=OwnedProcess([self.probe,'peer-direct',spec],cwd=self.root);self.owned.append(peer)
        deadline=time.monotonic()+5
        record=None
        while time.monotonic()<deadline and peer.process and peer.process.poll() is None:
            try:
                record=json.loads(ready.read_text())
                if record.get('pipe_name')==name: break
            except (OSError,ValueError): pass
            time.sleep(.01)
        peer.snapshot(self.logs,'direct-peer-ready');self.assertIsNotNone(record)
        self.assertEqual(record['pipe_name'],name)
        started=time.monotonic();result=self.exchange(name,request,connect=connect,read=read,expected=expected)
        self.assertLess(time.monotonic()-started,3)
        evidence=peer.finish(self.logs,'direct-peer-finished',timeout=3);require_success(evidence)
        self.assertLessEqual(evidence['stdout'].count(b'peer_connected'),1)
        self.assertLessEqual(evidence['stdout'].count(b'peer_read_one_request'),1)
        self.assertLessEqual(result['stderr'].count(b'helper_phase=client.connect.start '),1)
        return result,evidence

    def test_custom_exchange_deadlines_and_uncertain_disconnect_are_not_retried(self):
        for mode,request,error in [('stall-read',b'x'*(1024*1024-1),b'pipe_write_timeout'),
                                  ('stall-write',b'{}',b'pipe_read_timeout'),('slow-drip',b'{}',b'pipe_read_timeout'),
                                  ('disconnect',b'{"action":"shutdown"}',b'pipe_empty_response')]:
            with self.subTest(mode=mode):
                result,peer=self.peer_exchange(mode,request=request)
                self.assertIn(error,result['stderr'])
                self.assertEqual(peer['stdout'].count(b'peer_connected'),1)
                self.assertEqual(result['stderr'].count(b'helper_phase=client.connect.start '),1)
        result,peer=self.peer_exchange('absent',connect=150)
        self.assertIn(b'TimeoutException',result['stderr']);self.assertNotIn(b'peer_connected',peer['stdout'])

    def test_custom_exchange_frame_bounds_encoding_and_invalid_timeout_refusal(self):
        result,peer=self.peer_exchange('oversized',read=1500)
        self.assertIn(b'pipe_response_too_large',result['stderr']);self.assertEqual(result['stdout'],b'')
        result,peer=self.peer_exchange('invalid-utf8')
        self.assertIn(b'DecoderFallbackException',result['stderr'])
        result,peer=self.peer_exchange('unicode-split',read=1500,expected=0)
        self.assertEqual(result['stdout'],'한글😀\n'.encode())
        for request,connect,read,error in ((b'x'*(1024*1024),500,300,b'pipe_request_too_large'),
            (b'{}',0,300,b'bounded connection'),(b'{}',500,0,b'bounded connection')):
            result,peer=self.peer_exchange('stall-read',request=request,connect=connect,read=read)
            self.assertIn(error,result['stderr']);self.assertNotIn(b'peer_connected',peer['stdout'])
            self.assertNotIn(b'helper_phase=client.connect.start ',result['stderr'])
