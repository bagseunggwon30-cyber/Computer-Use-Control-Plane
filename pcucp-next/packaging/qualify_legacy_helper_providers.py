#!/usr/bin/env python3
"""Bounded actual Windows-provider qualification on a newly owned WinForms fixture.

No activation, registration, input, default routing changes, original-provider
normalization, or arbitrary screen capture. This gate does not retire source.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import re
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/python'))
from helper_process_evidence import OwnedProcess, run_evidence, require_success
from helper_provider_expectations import GROUPS, validate_group, validate_case, same
from helper_provider_progress import validate_progress, MAX_BYTES as PROGRESS_MAX_BYTES


def require_regressions(result, windows):
    raw=result['stderr'].decode('utf-8')
    found=re.findall(r'^Ran (\d+) tests? in ',raw,re.M)
    if found!=['43']: raise AssertionError('All 43 independent expectation regression methods must execute')
    skips=[line for line in raw.splitlines() if ' ... skipped ' in line]
    expected=["test_windows_flag_refuses_nonwindows (test_legacy_helper_providers.ProviderExpectationTests.test_windows_flag_refuses_nonwindows) ... skipped 'Non-Windows refusal control'"] if windows else []
    if skips!=expected or 'setUpClass (' in raw: raise AssertionError('Unexpected skipped provider regression')


def verify_images(rows, fixture_dir, group):
    seen=set()
    for row in rows:
        for call in row['calls']:
            if 'image_artifact' not in call: continue
            path=Path(call['image_artifact'])
            if path.parent.resolve()!=fixture_dir.resolve() or not re.fullmatch(re.escape(group)+r'-image-[1-9][0-9]*\.(png|bin)',path.name) or path in seen:
                raise AssertionError('Owned image artifact identity escaped its group or repeated')
            seen.add(path)
            if path.is_symlink() or path.stat().st_size>2*1024*1024: raise AssertionError('Invalid owned image artifact')
            raw=path.read_bytes()
            same(len(raw),call['image_bytes']); same(hashlib.sha256(raw).hexdigest(),call['image_sha256'])


def validate_cold_control(rows, ready):
    same([row['name'] for row in rows],['uia-run'])
    same(rows[0]['state'],dict(request_count=1,win32_loaded=True,uia_loaded=True,ocr_warm=False))
    validate_case(rows[0],ready)
    for operation in ('uia.load','win32.ensure'):
        calls=[call for call in rows[0]['calls'] if call['operation']==operation]
        same(calls,[dict(operation=operation,arguments=[],source='actual-provider',actual_result=None,result=None)])


def retain_assembly_metadata(root, logs):
    records={}
    targets=[('tests/fixtures/legacy-observation-owned-window','ObservationOwnedWindow'),
             ('tests/fixtures/legacy-helper-provider-probe','LegacyHelperProviderProbe'),
             ('pcucp-next/dotnet/PcuCp.LegacyHelper','PcuCp.LegacyHelper'),
             ('pcucp-next/dotnet/PcuCp.LegacyInterop','PcuCp.LegacyInterop')]
    destination=logs/'generated-assembly-metadata';destination.mkdir()
    for project,name in targets:
        source=root/project/'obj/Release/net48'/f'{name}.AssemblyInfo.cs'
        if source.stat().st_size>65536: raise AssertionError('Generated assembly metadata exceeded bound')
        raw=source.read_bytes();text=raw.decode('utf-8-sig')
        informational=re.findall(r'AssemblyInformationalVersionAttribute\("([^"\r\n]+)"\)',text)
        version=re.findall(r'AssemblyVersionAttribute\("([^"\r\n]+)"\)',text)
        if len(informational)!=1 or len(version)!=1: raise AssertionError('Generated assembly version metadata unavailable')
        evidence=destination/f'{name}.AssemblyInfo.cs';evidence.write_bytes(raw)
        revision=re.search(r'(?:\+|\.)([a-f0-9]{40})(?:$|\.)',informational[0])
        records[str(source.relative_to(root))]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
            evidence=str(evidence.relative_to(logs)),informational_version=informational[0],assembly_version=version[0],
            source_revision_suffix=revision[1] if revision else None)
    (logs/'assembly-metadata.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    return records


def progress_snapshot(path):
    # Diagnostic only. Partial bytes never satisfy validate_progress or qualify.
    if not path.is_file(): return dict(path=str(path),available=False)
    if path.stat().st_size>PROGRESS_MAX_BYTES: return dict(path=str(path),available=True,error='progress byte limit exceeded')
    raw=path.read_bytes();complete=[];error=None
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b'\n'): error='incomplete final line';break
        try: complete.append(json.loads(line))
        except (UnicodeError,ValueError): error='invalid JSON line';break
    return dict(path=str(path),available=True,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                complete_records=len(complete),last_marker=complete[-1] if complete else None,parse_error=error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true')
    parser.add_argument('--log-dir', type=Path, default=ROOT / '.migration-logs/helper-provider')
    args = parser.parse_args(argv)
    if args.windows and sys.platform != 'win32':
        parser.error('--windows requires Windows; actual providers cannot be replaced with skips')
    logs = args.log_dir.resolve(); logs.mkdir(parents=True, exist_ok=True)
    records, failures, progress_records = [], [], []
    summary = dict(schema='cucp.helper-provider-qualification/v1', status='running', windows_required=args.windows,
                   retirement_credit=0, platform=platform.platform(), python_version=sys.version, original_provider_parity='unqualified-not-compared', records=records, failures=failures,
                   progress_records=progress_records, cold_control_required=True, cold_control_validated=False, groups_required=list(GROUPS), cases_required=sum(map(len,GROUPS.values())), cases_validated=0)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    def run(label, command, timeout=180, creationflags=0):
        result = run_evidence(command, cwd=ROOT, env=env, directory=logs, label=label, timeout=timeout, limit=16*1024*1024, creationflags=creationflags)
        records.append(dict(label=label,evidence=result['evidence_path']))
        require_success(result)
        return result
    try:
        sources = ['tests/fixtures/legacy-helper-provider-probe/Program.cs', 'tests/fixtures/legacy-helper-provider-probe/OwnedProviderProgress.cs', 'tests/fixtures/legacy-helper-provider-probe/LegacyHelperProviderProbe.csproj',
                   'tests/fixtures/legacy-observation-owned-window/Program.cs', 'tests/python/helper_provider_expectations.py',
                   'tests/python/test_legacy_helper_providers.py', 'tests/python/helper_provider_progress.py', 'tests/python/test_helper_provider_progress.py', 'tests/python/test_helper_provider_progress_integration.py', 'pcucp-next/packaging/qualify_legacy_helper_providers.py',
                   'pcucp-next/dotnet/PcuCp.LegacyHelper/LegacyHelperActions.cs', 'pcucp-next/dotnet/PcuCp.LegacyHelper/LegacyHelperProviders.cs']
        (logs/'source-hashes.json').write_text(json.dumps({name:dict(bytes=len((ROOT/name).read_bytes()),sha256=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()) for name in sources},indent=2))
        regressions=run('expectation-regressions',[sys.executable,'-m','unittest','discover','-s','tests/python','-p','test_legacy_helper_providers.py','-v'],timeout=60)
        require_regressions(regressions,sys.platform=='win32')
        progress_tests=run('progress-regressions',[sys.executable,'-m','unittest','discover','-s','tests/python','-p','test_helper_provider_progress*.py','-v'],timeout=30)
        progress_test_count=re.findall(rb'^Ran (\d+) tests? in ',progress_tests['stderr'],re.M)
        if progress_test_count!=[b'94'] or b' ... skipped ' in progress_tests['stderr'] or b'setUpClass (' in progress_tests['stderr']:
            raise AssertionError('All 94 progress regressions must execute without skips')
        if not args.windows:
            summary['status']='portable-only-windows-unqualified'
            return 0
        for project in ('tests/fixtures/legacy-helper-provider-probe','tests/fixtures/legacy-observation-owned-window'):
            run('build-'+Path(project).name,['dotnet','build',str(ROOT/project),'-c','Release','-warnaserror','-m:1','-p:UseSharedCompilation=false'],timeout=300)
        retain_assembly_metadata(ROOT,logs)
        fixture_exe=ROOT/'tests/fixtures/legacy-observation-owned-window/bin/Release/net48/ObservationOwnedWindow.exe'
        probe_exe=ROOT/'tests/fixtures/legacy-helper-provider-probe/bin/Release/net48/LegacyHelperProviderProbe.exe'
        binaries=[fixture_exe,probe_exe,probe_exe.parent/'PcuCp.LegacyHelper.exe',probe_exe.parent/'PcuCp.LegacyInterop.dll']
        (logs/'binary-hashes.json').write_text(json.dumps({str(path.relative_to(ROOT)):dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in binaries},indent=2))
        fixture_dir=logs/('owned-window-'+uuid.uuid4().hex); fixture_dir.mkdir()
        title='CUCP helper owned '+uuid.uuid4().hex
        # TEMP is dedicated to generated inputs/provider captures, never user's files.
        with tempfile.TemporaryDirectory(prefix='cucp-helper-provider-') as temporary:
            env.update(TEMP=temporary,TMP=temporary)
            fixture=OwnedProcess([fixture_exe,fixture_dir,title,'helper-provider'],cwd=ROOT,env=env,limit=262144)
            try:
                ready_path=fixture_dir/'ready.json';deadline=time.monotonic()+30
                while not ready_path.is_file() and time.monotonic()<deadline:
                    if fixture.process is None or fixture.process.poll() is not None: break
                    time.sleep(.1)
                fixture.snapshot(logs,'fixture-running')
                if not ready_path.is_file(): raise RuntimeError('Owned fixture readiness unavailable; actual provider gate unqualified')
                ready=json.loads(ready_path.read_text(encoding='utf-8'))
                if (not ready['desktop_interactive'] or not ready['helper_provider'] or ready['pid']!=fixture.process.pid or ready['hwnd']<=0 or ready['title']!=title):
                    raise RuntimeError('Owned HWND/PID/desktop/readiness mismatch')
                same({key:ready[key] for key in ('input_events','invoke_events','value_events')},dict(input_events=0,invoke_events=0,value_events=0))
                # Each group remains independent: UIA/provider or OCR failure cannot
                # hide unrelated actual-provider evidence. No process is retried.
                for group in list(GROUPS)+['uia-cold']:
                    try:
                        result=run('actual-'+group,[probe_exe,group,ready_path,str(fixture.process.pid)],timeout=90,creationflags=0x08000000)
                        if result['stderr']: raise AssertionError('Probe emitted stderr; raw evidence retained')
                        rows=[json.loads(line) for line in result['stdout'].decode('utf-8-sig').splitlines()]
                        validate_progress((fixture_dir/(group+'-progress.jsonl')).read_bytes(),group)
                        verify_images(rows,fixture_dir,group)
                        if group=='uia-cold':
                            validate_cold_control(rows,ready)
                            summary['cold_control_validated']=True
                        else:
                            errors=validate_group(group,rows,ready)
                            failures.extend(dict(group=group,**error) for error in errors)
                            summary['cases_validated']+=len(rows)-len(errors)
                    except Exception as error: failures.append(dict(group=group,error=str(error)))
                    finally: progress_records.append(dict(group=group,**progress_snapshot(fixture_dir/(group+'-progress.jsonl'))))
                leftovers=sorted(p.name for p in Path(temporary).iterdir())
                (logs/'owned-temp-after.json').write_text(json.dumps(leftovers))
                if leftovers: failures.append(dict(group='cleanup',error='Owned OCR temporary files remain',files=leftovers))
            finally:
                (fixture_dir/'close.request').write_text('close newly owned fixture')
                terminal=fixture.finish(logs,'fixture-terminal',timeout=10)
                try:
                    require_success(terminal)
                    closed=json.loads((fixture_dir/'closed.json').read_text(encoding='utf-8'))
                    same(closed,dict(input_events=0,invoke_events=0,value_events=0))
                except Exception as error: failures.append(dict(group='fixture-cleanup',error=str(error)))
        summary['status']='passed-actual-candidate-provider-only' if not failures else 'failed-unqualified'
        return 0 if not failures else 1
    except Exception as error:
        failures.append(dict(group='infrastructure',error=str(error)))
        summary['status']='failed-unqualified'
        return 1
    finally:
        (logs/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__': raise SystemExit(main())
