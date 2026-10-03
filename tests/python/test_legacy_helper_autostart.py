"""Owned-temp autostart planning/ownership tests; never touch real Startup."""
from __future__ import annotations
import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from pcucp_cli.legacy_helper_autostart import (AutostartController, WindowsAutostartStore,
    plan_autostart, SHIM_NAME, MANIFEST_NAME, MAX_BYTES)
from pcucp_cli.legacy_helper_client import LockSnapshot
from pcucp_cli.legacy_helper_runtime import WindowsAuthority

ROOT=Path(__file__).resolve().parents[2]


class OwnedFixtureStore:
    """Deterministic acquisition/CAS seam, only an owned TemporaryDirectory.

    Its simulated compare/delete is not a production atomicity claim. Concrete
    Windows CAS is exercised separately under an explicit platform gate.
    """
    def __init__(self, directory, metadata_directory):
        self.directory=Path(directory);self.metadata_directory=Path(metadata_directory);self.calls=[];self.identities={};self.serial=0
        self.held=False;self.active=False
        self.fail_create=None;self.fail_delete=None;self.replace_before_delete=None
    def path(self,name):
        if name not in (SHIM_NAME,MANIFEST_NAME): raise ValueError('unexpected fixture name')
        return (self.metadata_directory if name==MANIFEST_NAME else self.directory)/name
    @property
    def startup_identity(self):
        stat=self.directory.stat();return (0,(stat.st_ino>>32)&0xffffffff,stat.st_ino&0xffffffff)
    @contextmanager
    def operation(self):
        self.active=True
        try: yield
        finally: self.active=False
    @contextmanager
    def marker(self,create=None):
        from pcucp_cli.legacy_helper_autostart import _MarkerLease
        if self.held: raise OSError('injected sharing violation')
        if create is not None: self.create_new(MANIFEST_NAME,create)
        snapshot=self.read(MANIFEST_NAME)
        self.held=True
        try: yield _MarkerLease(snapshot,lambda:self.compare_delete(MANIFEST_NAME,snapshot)) if snapshot is not None else None
        finally: self.held=False
    def exists(self,name): self.calls.append(('exists',name));return self.path(name).exists()
    def read(self,name):
        self.calls.append(('read',name))
        try:
            with self.path(name).open('rb') as stream: raw=stream.read(MAX_BYTES+1)
        except FileNotFoundError: return None
        if len(raw)>MAX_BYTES: raise ValueError('fixture file exceeds bound')
        if name not in self.identities: self.serial+=1;self.identities[name]=self.serial
        return LockSnapshot(raw,self.identities[name])
    def create_new(self,name,raw):
        self.calls.append(('create',name))
        if self.fail_create==name: raise OSError('injected create failure')
        with self.path(name).open('xb') as stream: stream.write(raw)
        self.serial+=1;self.identities[name]=self.serial
    def replace(self,name,raw):
        self.path(name).write_bytes(raw);self.serial+=1;self.identities[name]=self.serial
    def compare_delete(self,name,expected):
        self.calls.append(('delete',name))
        if self.replace_before_delete==name:
            self.replace(name,expected.raw);self.replace_before_delete=None
        if self.fail_delete==name or self.read(name)!=expected: return False
        self.path(name).unlink();self.identities.pop(name,None);return True


class AutostartControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cucp owned autostart ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.startup=self.root/'startup';self.metadata=self.root/'state'
        self.startup.mkdir();self.metadata.mkdir();self.store=OwnedFixtureStore(self.startup,self.metadata)
        self.validate=Mock()
        self.controller=AutostartController(self.startup,self.root/'python.exe',self.root/'bootstrap.py',metadata_directory=self.metadata,
            store=self.store,allow_change=True,desktop=False,validate_install=self.validate)
    def contents(self): return {p.name:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_plan_is_read_only_fixed_name_bounded_and_has_no_powershell(self):
        p=plan_autostart(self.root,self.root/'python.exe',self.root/'bootstrap.py')
        self.assertEqual(self.contents(),{})
        self.assertEqual(Path(p['shim_path']).name,SHIM_NAME)
        self.assertLessEqual(len(p['shim']),MAX_BYTES)
        self.assertNotIn(b'powershell',p['shim'].lower());self.assertNotIn(b'pwsh',p['shim'].lower())
        self.assertEqual(p['idle_timeout_ms'],28800000)
        self.assertNotIn('--allow-readonly-desktop',p['command'])

    def test_invalid_idle_authority_and_paths_fail_before_write(self):
        for value in (0,-1,True,1.5,'1',2**31):
            with self.assertRaises(ValueError): plan_autostart(self.root,'python.exe','bootstrap.py',idle_timeout_ms=value)
        for value in (None,1,'true'):
            with self.assertRaises(ValueError): plan_autostart(self.root,'python.exe','bootstrap.py',desktop=value)
        for value in ('bad\npath','bad\rpath','bad"path','bad\0path'):
            with self.assertRaises(ValueError): plan_autostart(self.root,value,'bootstrap.py')
        with self.assertRaises(ValueError): plan_autostart(self.root,'a'*9000,'bootstrap.py')
        self.assertEqual(self.contents(),{})

    def test_mutations_require_bootstrap_authority_before_any_store_or_package_read(self):
        denied=AutostartController(self.startup,'python.exe','bootstrap.py',metadata_directory=self.metadata,store=self.store,allow_change=False,validate_install=self.validate)
        for request in (dict(operation='autostart-install',arguments=dict(idle_timeout_ms=1000)),
                        dict(operation='autostart-uninstall',arguments={})):
            with self.assertRaises(PermissionError): denied.handle(request)
        self.assertEqual(self.store.calls,[]);self.validate.assert_not_called()

    def test_request_cannot_change_path_executable_or_authority(self):
        for request in (dict(operation='autostart-install',arguments=dict(idle_timeout_ms=1000,allow_change=True)),
                        dict(operation='autostart-status',arguments=dict(directory='elsewhere')),
                        dict(operation='serve',arguments={}),dict(operation='autostart-status',arguments={},desktop=True)):
            with self.assertRaises(ValueError): self.controller.handle(request)
        self.assertEqual(self.store.calls,[]);self.validate.assert_not_called()

    def test_create_publish_order_schema_and_identical_idempotency(self):
        first=self.controller.install()
        self.assertEqual(first['status'],'ok');self.assertEqual(first['action'],'install-autostart')
        self.assertEqual(set(first),{'status','action','shim_path','idle_timeout_ms','note'})
        self.assertEqual([c for c in self.store.calls if c[0]=='create'],[('create',MANIFEST_NAME),('create',SHIM_NAME)])
        old=self.contents();self.store.calls=[]
        self.assertEqual(self.controller.install(),first);self.assertEqual(self.contents(),old)
        self.assertFalse(any(c[0] in ('create','delete') for c in self.store.calls))

    def test_changed_owned_idle_or_authority_refuses_without_touching_files(self):
        self.controller.install();old=self.contents();self.store.calls=[]
        self.assertEqual(self.controller.install(1000)['status'],'error')
        different=AutostartController(self.startup,self.root/'python.exe',self.root/'bootstrap.py',metadata_directory=self.metadata,store=self.store,allow_change=True,desktop=True)
        self.assertEqual(different.install()['status'],'error')
        self.assertEqual(self.contents(),old)
        self.assertFalse(any(c[0] in ('create','delete') for c in self.store.calls))

    def test_status_and_uninstall_work_after_package_disappears(self):
        self.controller.install();self.validate.reset_mock();self.validate.side_effect=ValueError('package missing')
        self.assertEqual(self.controller.status(),dict(status='ok',installed=True,shim_path=str(self.startup/SHIM_NAME)))
        removed=self.controller.uninstall();self.assertTrue(removed['removed']);self.assertEqual(removed['status'],'ok')
        self.validate.assert_not_called();self.assertEqual(self.contents(),{})
        self.assertFalse(self.controller.uninstall()['removed'])

    def test_missing_package_never_creates_any_file(self):
        self.validate.side_effect=ValueError('package missing')
        self.assertEqual(self.controller.install()['reason'],'shim_write_failed')
        self.assertEqual(self.contents(),{});self.assertEqual(self.store.calls,[])

    def test_legacy_and_unowned_shims_are_preserved_for_install_and_uninstall(self):
        self.store.replace(SHIM_NAME,b'old powershell launcher, retained fixture')
        before=self.contents()
        self.assertTrue(self.controller.status()['installed'])
        self.assertEqual(self.controller.install()['reason'],'shim_write_failed')
        self.assertEqual(self.controller.uninstall()['reason'],'shim_remove_failed')
        self.assertEqual(self.contents(),before)

    def test_tampered_command_or_marker_is_never_removed(self):
        for target in (SHIM_NAME,MANIFEST_NAME):
            with self.subTest(target=target):
                for p in self.root.rglob('*'):
                    if p.is_file(): p.unlink()
                self.store.identities.clear();self.controller.install()
                self.store.replace(target,b'changed')
                before=self.contents()
                self.assertEqual(self.controller.install()['status'],'error')
                self.assertEqual(self.controller.uninstall()['status'],'error')
                self.assertEqual(self.contents(),before)

    def test_malformed_duplicate_oversized_and_unknown_marker_fields_preserved(self):
        self.controller.install()
        original=self.store.path(MANIFEST_NAME).read_bytes()
        values=[b'[]',b'{"schema":1,"schema":2}',b'x'*(MAX_BYTES+1)]
        decoded=json.loads(original);values.append(json.dumps(dict(decoded,unexpected=True)).encode())
        for raw in values:
            self.store.replace(MANIFEST_NAME,raw);before=self.contents()
            self.assertEqual(self.controller.uninstall()['status'],'error');self.assertEqual(self.contents(),before)

    def test_identical_byte_replacement_survives_uninstall_cas(self):
        self.controller.install();before=self.contents();self.store.replace_before_delete=SHIM_NAME
        self.assertEqual(self.controller.uninstall()['status'],'error')
        self.assertEqual(self.contents(),before)
        self.assertNotIn(('delete',MANIFEST_NAME),self.store.calls)

    def test_delete_failure_is_not_retried_or_followed_by_marker_delete(self):
        self.controller.install();self.store.calls=[];self.store.fail_delete=SHIM_NAME
        self.assertEqual(self.controller.uninstall()['status'],'error')
        self.assertEqual([c for c in self.store.calls if c[0]=='delete'],[('delete',SHIM_NAME)])

    def test_create_failure_preserves_marker_and_next_explicit_call_can_recover(self):
        self.store.fail_create=SHIM_NAME
        self.assertEqual(self.controller.install()['status'],'error')
        self.assertEqual(set(self.contents()),{MANIFEST_NAME})
        self.assertEqual([c for c in self.store.calls if c[0]=='create'],[('create',MANIFEST_NAME),('create',SHIM_NAME)])
        self.store.fail_create=None
        result=self.controller.install();self.assertEqual(result['status'],'ok',result)
        self.assertEqual(set(self.contents()),{MANIFEST_NAME,SHIM_NAME})

    def test_orphan_marker_can_be_removed_without_package_or_command(self):
        self.store.fail_create=SHIM_NAME;self.controller.install()
        self.validate.side_effect=ValueError('missing package')
        result=self.controller.uninstall();self.assertEqual(result['status'],'ok');self.assertFalse(result['removed'])
        self.assertEqual(self.contents(),{})

    def test_owned_marker_is_preserved_if_second_delete_cas_fails(self):
        self.controller.install();self.store.fail_delete=MANIFEST_NAME
        self.assertEqual(self.controller.uninstall()['status'],'error')
        self.assertEqual(set(self.contents()),{MANIFEST_NAME})

    def test_metadata_is_outside_startup_and_bound_to_path_and_directory_identity(self):
        self.controller.install()
        self.assertEqual({p.name for p in self.startup.iterdir()},{SHIM_NAME})
        marker=json.loads(self.store.path(MANIFEST_NAME).read_bytes())
        self.assertEqual(marker['startup_directory'],str(self.startup))
        self.assertEqual(marker['startup_identity'],list(self.store.startup_identity))
        other=self.root/'other-startup';other.mkdir()
        other_store=OwnedFixtureStore(other,self.metadata)
        other_controller=AutostartController(other,self.root/'python.exe',self.root/'bootstrap.py',
            metadata_directory=self.metadata,store=other_store,allow_change=True)
        before=self.contents()
        self.assertEqual(other_controller.install()['status'],'error')
        self.assertEqual(other_controller.uninstall()['status'],'error')
        self.assertEqual(self.contents(),before);self.assertEqual(list(other.iterdir()),[])
        previous=self.root/'previous-startup';self.startup.rename(previous);self.startup.mkdir()
        self.assertEqual(self.controller.install()['status'],'error')
        self.assertEqual(self.controller.uninstall()['status'],'error')
        self.assertTrue((previous/SHIM_NAME).exists());self.assertTrue((self.metadata/MANIFEST_NAME).exists())

    def test_metadata_directory_cannot_be_inside_startup(self):
        for metadata in (self.startup,self.startup/'nested',self.root/'state/../startup'):
            with self.assertRaises(ValueError):
                AutostartController(self.startup,'python.exe','bootstrap.py',metadata_directory=metadata,
                    store=self.store,allow_change=True)

    def test_generated_manifest_cannot_substitute_an_unrelated_target_name(self):
        store=object.__new__(WindowsAutostartStore);store.directory=self.startup;store.metadata_directory=self.metadata
        for name in ('../elsewhere','other.cmd','',str(self.root/'other')):
            with self.assertRaises(ValueError): store._path(name)


    def test_default_autostart_bodies_are_exact_pinned_historical_source(self):
        import hashlib
        import re
        from helper_process_evidence import run_evidence,require_success
        pin=json.loads((ROOT/'tests/fixtures/legacy-helper/source-manifest.json').read_text())
        entry=next(value for value in pin['files'] if value['path']=='scripts/cucp.ps1')
        result=run_evidence(['git','show',pin['published_tree']+':scripts/cucp.ps1'],
            directory=self.root/'source-evidence',label='original-autostart-wrapper',cwd=ROOT,timeout=10,limit=2*1024*1024)
        require_success(result)
        self.assertEqual(hashlib.sha256(result['stdout']).hexdigest(),entry['raw_sha256'])
        original=result['stdout'].decode('utf-8-sig').replace('\r\n','\n')
        current=(ROOT/'scripts/cucp.ps1').read_text(encoding='utf-8-sig')
        for name in ('_Get-AutostartShimPath','Install-HelperAutostart','Uninstall-HelperAutostart','Get-HelperAutostartStatus'):
            pattern=r'(?ms)^function '+re.escape(name)+r' \{.*?^\}'
            before=re.findall(pattern,original);after=re.findall(pattern,current)
            self.assertEqual(len(before),1);self.assertEqual(len(after),1)
            prologues={
                'Install-HelperAutostart': "  if ($Script:StagedCompiledHelper) { return (_Invoke-StagedHelper -Operation 'autostart-install' -Arguments @{idle_timeout_ms=$IdleTimeoutMs}) }\n",
                'Uninstall-HelperAutostart': "  if ($Script:StagedCompiledHelper) { return (_Invoke-StagedHelper -Operation 'autostart-uninstall') }\n",
                'Get-HelperAutostartStatus': "  if ($Script:StagedCompiledHelper) { return (_Invoke-StagedHelper -Operation 'autostart-status') }\n"}
            retained=after[0]
            if name in prologues:
                self.assertEqual(retained.count(prologues[name]),1)
                retained=retained.replace(prologues[name],'',1)
            self.assertEqual(retained,before[0],name)


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_REQUIRE_STAGED_AUTOSTART')=='1',
                     'Requires owned Windows temporary-directory autostart gate')
class AutostartWindowsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cucp autostart owned NTFS ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.startup=self.root/'startup';self.metadata=self.root/'state'
        self.startup.mkdir();self.metadata.mkdir()
        self.store=WindowsAutostartStore(self.startup,self.metadata,WindowsAuthority())
        self.controller=AutostartController(self.startup,sys.executable,ROOT/'pcucp-next/python/legacy_helper_autostart_entry.py',metadata_directory=self.metadata,
            store=self.store,allow_change=True)
    def test_real_handle_store_create_status_idempotence_and_uninstall_in_temp_only(self):
        result=self.controller.install();self.assertEqual(result['status'],'ok',result)
        self.assertTrue(self.controller.status()['installed'])
        result=self.controller.install();self.assertEqual(result['status'],'ok',result)
        result=self.controller.uninstall();self.assertEqual(result['status'],'ok',result)
        self.assertEqual(list(self.startup.iterdir()),[]);self.assertEqual(list(self.metadata.iterdir()),[])
    def test_real_same_byte_replacement_survives_cas(self):
        result=self.controller.install();self.assertEqual(result['status'],'ok',result)
        with self.store.operation():
            expected=self.store.read(SHIM_NAME)
            replacement=self.root/'owned replacement';replacement.write_bytes(expected.raw)
            os.replace(replacement,self.startup/SHIM_NAME)
            self.assertFalse(self.store.compare_delete(SHIM_NAME,expected))
            self.assertEqual((self.startup/SHIM_NAME).read_bytes(),expected.raw)
    def test_marker_lease_excludes_competing_mutation_rename_and_write(self):
        result=self.controller.install();self.assertEqual(result['status'],'ok',result)
        original=(self.metadata/MANIFEST_NAME).read_bytes()
        second_store=WindowsAutostartStore(self.startup,self.metadata,WindowsAuthority())
        second=AutostartController(self.startup,sys.executable,ROOT/'pcucp-next/python/legacy_helper_autostart_entry.py',
            metadata_directory=self.metadata,store=second_store,allow_change=True)
        with self.store.operation():
            with self.store.marker() as lease:
                self.assertIsNotNone(lease)
                with self.assertRaises(OSError): (self.metadata/MANIFEST_NAME).unlink()
                with self.assertRaises(OSError): (self.metadata/MANIFEST_NAME).write_bytes(b'changed')
                with self.assertRaises(OSError): os.replace(self.metadata/MANIFEST_NAME,self.metadata/'moved')
                self.assertEqual(second.uninstall()['status'],'error')
                self.assertTrue((self.startup/SHIM_NAME).exists())
        self.assertEqual((self.metadata/MANIFEST_NAME).read_bytes(),original)
        result=self.controller.uninstall();self.assertEqual(result['status'],'ok',result)

    def test_ancestor_rename_and_reparse_directories_are_refused(self):
        ancestor=self.root/'ancestor';nested=ancestor/'startup';nested.mkdir(parents=True)
        store=WindowsAutostartStore(nested,self.metadata,WindowsAuthority())
        with store.operation():
            with self.assertRaises(OSError): ancestor.rename(self.root/'moved-ancestor')
        target=self.root/'junction-target';target.mkdir()
        junction=self.root/'junction'
        command=[os.path.join(os.environ['SystemRoot'],'System32','cmd.exe'),'/d','/c','mklink','/J',str(junction),str(target)]
        result=subprocess.run(command,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        try:
            bad=WindowsAutostartStore(junction,self.metadata,WindowsAuthority())
            with self.assertRaises(ValueError):
                with bad.operation(): self.fail('Junction root was accepted')
            (target/'nested').mkdir()
            bad=WindowsAutostartStore(junction/'nested',self.metadata,WindowsAuthority())
            with self.assertRaises(ValueError):
                with bad.operation(): self.fail('Junction ancestor was accepted')
            self.assertEqual(list(self.metadata.iterdir()),[])
        finally: junction.rmdir()

    def test_actual_retained_directory_identities_reject_metadata_aliases_inside_startup(self):
        nested=self.startup/'nested';nested.mkdir()
        for metadata in (self.metadata/'../startup',self.metadata/'../startup/nested'):
            store=WindowsAutostartStore(self.startup,metadata,WindowsAuthority())
            with self.assertRaisesRegex(ValueError,'metadata_must_be_outside_startup'):
                with store.operation(): self.fail('Metadata inside Startup was accepted')
        self.assertEqual(list(nested.iterdir()),[])

    def test_created_and_marker_only_leases_exclude_competing_recovery_and_uninstall(self):
        second_store=WindowsAutostartStore(self.startup,self.metadata,WindowsAuthority())
        second=AutostartController(self.startup,sys.executable,ROOT/'pcucp-next/python/legacy_helper_autostart_entry.py',
            metadata_directory=self.metadata,store=second_store,allow_change=True)
        with self.store.operation():
            plan=self.controller._plan()
            with self.store.marker(create=plan['manifest']):
                for result in (second.install(),second.uninstall()): self.assertEqual(result['status'],'error',result)
                self.assertFalse((self.startup/SHIM_NAME).exists())
        with self.store.operation():
            with self.store.marker():
                for result in (second.install(),second.uninstall()): self.assertEqual(result['status'],'error',result)
                self.assertFalse((self.startup/SHIM_NAME).exists())
        result=self.controller.install();self.assertEqual(result['status'],'ok',result)
        result=self.controller.uninstall();self.assertEqual(result['status'],'ok',result)

    def test_metadata_junction_ancestors_and_reparse_artifact_leaves_are_preserved(self):
        target=self.root/'junction-owned-target';target.mkdir()
        sentinel=target/'sentinel';sentinel.write_bytes(b'untouched')
        paths=(self.root/'metadata-junction',self.metadata/MANIFEST_NAME,self.startup/SHIM_NAME)
        for junction in paths:
            if junction==paths[2]:
                result=self.controller.install();self.assertEqual(result['status'],'ok',result)
                (self.startup/SHIM_NAME).unlink()  # Replace only the owned fixture shim.
                original_marker=(self.metadata/MANIFEST_NAME).read_bytes()
            command=[os.path.join(os.environ['SystemRoot'],'System32','cmd.exe'),'/d','/c','mklink','/J',str(junction),str(target)]
            result=subprocess.run(command,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            try:
                if junction==paths[0]:
                    bad=WindowsAutostartStore(self.startup,junction,WindowsAuthority())
                    with self.assertRaises(ValueError):
                        with bad.operation(): self.fail('Metadata junction accepted')
                else:
                    for result in (self.controller.install(),self.controller.uninstall()):
                        self.assertEqual(result['status'],'error',result)
                self.assertEqual(sentinel.read_bytes(),b'untouched')
                self.assertTrue(junction.exists())
                if junction==paths[2]:
                    self.assertEqual((self.metadata/MANIFEST_NAME).read_bytes(),original_marker)
            finally: junction.rmdir()

    def test_missing_directory_is_not_created(self):
        missing=self.root/'missing'
        store=WindowsAutostartStore(missing,self.metadata,WindowsAuthority())
        with self.assertRaises((OSError,ValueError)):
            with store.operation(): store.create_new(SHIM_NAME,b'owned')
        self.assertFalse(missing.exists())

class AutostartBootstrapTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('owned_autostart_entry',ROOT/'pcucp-next/python/legacy_helper_autostart_entry.py')
        self.entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.entry)
        self.temp=tempfile.TemporaryDirectory(prefix='cucp autostart bootstrap owned ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.package=self.root/'package'
        self.runtime=Mock();self.runtime.client.start.return_value=dict(status='ok',reused=False)
        self.factory=Mock(return_value=self.runtime)

    def test_fixed_staged_lock_and_single_detached_start_request(self):
        with patch.object(self.entry,'validate_package') as check:
            result=self.entry.start_once(28800000,False,temp_root=self.root,package=self.package,runtime_factory=self.factory)
        self.assertEqual(result,dict(status='ok',reused=False))
        check.assert_called_once_with(self.package)
        self.factory.assert_called_once_with(self.package,self.root/'computer-use-control-plane/helper-staged.pid',desktop=False)
        self.runtime.client.start.assert_called_once_with(self.runtime.launcher,idle_timeout_ms=28800000)

    def test_invalid_values_and_failed_package_do_not_create_runtime_or_lock_directory(self):
        for idle in (0,-1,True,1.5):
            with self.assertRaises(ValueError): self.entry.start_once(idle,False,temp_root=self.root,package=self.package,runtime_factory=self.factory)
        with patch.object(self.entry,'validate_package',side_effect=ValueError('missing package')):
            with self.assertRaises(ValueError): self.entry.start_once(1000,False,temp_root=self.root,package=self.package,runtime_factory=self.factory)
        self.factory.assert_not_called();self.assertEqual(list(self.root.iterdir()),[])

    def test_launch_failure_has_no_retry_and_no_authority_from_environment(self):
        self.runtime.client.start.side_effect=OSError('uncertain owned launch')
        with patch.object(self.entry,'validate_package'),patch.dict(os.environ,{'CUCP_STAGED_HELPER_READONLY_DESKTOP':'1'}):
            with self.assertRaises(OSError): self.entry.start_once(1000,False,temp_root=self.root,package=self.package,runtime_factory=self.factory)
        self.factory.assert_called_once_with(self.package,self.root/'computer-use-control-plane/helper-staged.pid',desktop=False)
        self.assertEqual(self.runtime.client.start.call_count,1)


class AutostartBridgeDispatchTests(unittest.TestCase):
    """Real closed bridge dispatch/controller, with only owned acquisition replaced."""
    def setUp(self):
        import io
        self.io=io
        spec=importlib.util.spec_from_file_location('owned_autostart_bridge',ROOT/'pcucp-next/python/legacy_helper_bridge.py')
        self.bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.bridge)
        self.temp=tempfile.TemporaryDirectory(prefix='cucp autostart bridge owned ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.startup=self.root/'startup';self.metadata=self.root/'state'
        self.startup.mkdir();self.metadata.mkdir();self.store=OwnedFixtureStore(self.startup,self.metadata)
        self.validation=Mock()

    def invoke(self,operation,arguments,*,allow=False,extra=()):
        argv=['--staged-unqualified','--lock-file',str(self.root/'unused.pid'),
              '--startup-directory',str(self.startup),'--metadata-directory',str(self.metadata)]
        if allow: argv+=['--allow-autostart-change']
        argv+=list(extra)
        raw=json.dumps(dict(operation=operation,arguments=arguments)).encode()
        stdout=self.io.BytesIO()
        with patch.object(self.bridge.sys,'stdin',Mock(buffer=self.io.BytesIO(raw))), \
             patch.object(self.bridge.sys,'stdout',Mock(buffer=stdout)), \
             patch.object(self.bridge,'WindowsAuthority') as authority, \
             patch.object(self.bridge,'WindowsAutostartStore',return_value=self.store) as factory, \
             patch.object(self.bridge,'validate_package',self.validation):
            code=self.bridge.main(argv)
        return code,json.loads(stdout.getvalue()),factory

    def test_real_bridge_preserves_public_data_and_missing_package_cleanup(self):
        code,reply,factory=self.invoke('autostart-install',{'idle_timeout_ms':12345},allow=True)
        self.assertEqual(code,0,reply);self.assertEqual(reply['status'],'ok')
        self.assertEqual(reply['data']['status'],'ok',reply)
        self.assertEqual(reply['data']['idle_timeout_ms'],12345)
        self.assertEqual(factory.call_args.args[:2],(self.startup,self.metadata))
        marker=json.loads((self.metadata/MANIFEST_NAME).read_bytes())
        self.assertEqual(marker['python_exe'],str(Path(sys.executable).absolute()))
        self.assertEqual(marker['bootstrap'],str(ROOT/'pcucp-next/python/legacy_helper_autostart_entry.py'))
        self.validation.reset_mock();self.validation.side_effect=ValueError('missing package')
        code,reply,_=self.invoke('autostart-status',{})
        self.assertEqual(code,0,reply)
        self.assertEqual(reply['data'],dict(status='ok',installed=True,shim_path=str(self.startup/SHIM_NAME)))
        code,reply,_=self.invoke('autostart-uninstall',{},allow=True)
        self.assertEqual(code,0,reply)
        self.assertEqual(reply['data'],dict(status='ok',action='uninstall-autostart',shim_path=str(self.startup/SHIM_NAME),removed=True))
        self.validation.assert_not_called()

    def test_json_and_environment_cannot_grant_change_authority(self):
        with patch.dict(os.environ,{'AllowLiveControl':'1','CUCP_STAGED_HELPER_READONLY_DESKTOP':'1'}):
            for operation,args in (('autostart-install',{'idle_timeout_ms':12345}),('autostart-uninstall',{})):
                code,reply,_=self.invoke(operation,args)
                self.assertEqual(code,1,reply);self.assertIn('requires -AllowLiveControl',reply['reason'])
            code,reply,_=self.invoke('autostart-install',{'idle_timeout_ms':12345,'allow_change':True})
            self.assertEqual(code,1);self.assertEqual(reply['reason'],'invalid_autostart_request')
        self.validation.assert_not_called();self.assertEqual(self.store.calls,[])
        self.assertEqual(list(self.startup.iterdir()),[]);self.assertEqual(list(self.metadata.iterdir()),[])

    def test_autostart_context_is_rejected_for_other_operations(self):
        with patch.object(self.bridge,'StagedHelperRuntime') as service:
            code,reply,_=self.invoke('start',{'idle_timeout_ms':12345},allow=True)
        self.assertEqual(code,1);self.assertEqual(reply['reason'],'unexpected_autostart_bootstrap_context')
        service.assert_not_called();self.validation.assert_not_called()


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_REQUIRE_STAGED_AUTOSTART')=='1',
                     'Requires owned Windows autostart bridge gate')
class AutostartWindowsBridgeTests(unittest.TestCase):
    def test_actual_adapter_delegates_capture_authority_once_and_use_owned_paths(self):
        from helper_process_evidence import run_evidence,require_success
        with tempfile.TemporaryDirectory(prefix='cucp autostart authority owned ') as temporary:
            root=Path(temporary)
            (root/'.autostart-authority-fixture').write_text('owned-temporary-autostart-authority/v1',encoding='ascii')
            result=run_evidence(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(ROOT/'tests/fixtures/legacy-helper-autostart-authority.ps1'),'-SourceRoot',str(ROOT),'-OwnedRoot',str(root)],
                directory=os.environ.get('CUCP_HELPER_EVIDENCE_DIR',root/'evidence'),label='autostart-authority',timeout=45)
            require_success(result)
            reply=json.loads(result['stdout'])
            self.assertEqual(reply['status'],'ok');self.assertEqual(len(reply['results']),2)
            self.assertEqual([r['captured'] for r in reply['results']],[False,True])

    def test_actual_bridge_owned_lifecycle_and_missing_package_status_uninstall(self):
        import shutil
        from helper_process_evidence import run_evidence,require_success
        with tempfile.TemporaryDirectory(prefix='cucp autostart bridge native owned ') as temporary:
            root=Path(temporary);startup=root/'startup';state=root/'state'
            startup.mkdir();state.mkdir()
            source=root/'pcucp-next/python'
            shutil.copytree(ROOT/'pcucp-next/python',source,ignore=shutil.ignore_patterns('__pycache__'))
            package=root/'pcucp-next/bin/legacy-helper'
            shutil.copytree(ROOT/'pcucp-next/bin/legacy-helper',package)
            bridge=source/'legacy_helper_bridge.py'
            def invoke(operation,arguments,allow=False,expected=0):
                command=[sys.executable,'-E','-s',str(bridge),'--staged-unqualified','--lock-file',str(root/'unused.pid'),
                         '--startup-directory',str(startup),'--metadata-directory',str(state)]
                if allow: command+=['--allow-autostart-change']
                result=run_evidence(command,input_bytes=json.dumps(dict(operation=operation,arguments=arguments)).encode(),
                    directory=os.environ.get('CUCP_HELPER_EVIDENCE_DIR',root/'evidence'),label=operation,timeout=15)
                require_success(result,expected_exit=expected)
                return json.loads(result['stdout'])
            denied=invoke('autostart-install',dict(idle_timeout_ms=12345),expected=1)
            self.assertIn('requires -AllowLiveControl',denied['reason'])
            self.assertEqual(list(startup.iterdir()),[]);self.assertEqual(list(state.iterdir()),[])
            installed=invoke('autostart-install',dict(idle_timeout_ms=12345),True)
            self.assertEqual(installed['data']['status'],'ok',installed)
            self.assertEqual(set(installed['data']),{'status','action','shim_path','idle_timeout_ms','note'})
            original=(startup/SHIM_NAME).read_bytes(),(state/MANIFEST_NAME).read_bytes()
            again=invoke('autostart-install',dict(idle_timeout_ms=12345),True)
            self.assertEqual(again,installed)
            changed=invoke('autostart-install',dict(idle_timeout_ms=12346),True)
            self.assertEqual(changed['data']['reason'],'shim_write_failed',changed)
            self.assertEqual(((startup/SHIM_NAME).read_bytes(),(state/MANIFEST_NAME).read_bytes()),original)
            # Only the owned package fixture disappears; source/bootstrap remain.
            shutil.rmtree(package)
            status=invoke('autostart-status',{})
            self.assertEqual(status['data'],dict(status='ok',installed=True,shim_path=str(startup/SHIM_NAME)))
            removed=invoke('autostart-uninstall',{},True)
            self.assertEqual(removed['data'],dict(status='ok',action='uninstall-autostart',removed=True,shim_path=str(startup/SHIM_NAME)))
            self.assertEqual(list(startup.iterdir()),[]);self.assertEqual(list(state.iterdir()),[])
