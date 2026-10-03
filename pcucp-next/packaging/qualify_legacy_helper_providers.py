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
from helper_provider_expectations import GROUPS, validate_group, same


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true')
    parser.add_argument('--log-dir', type=Path, default=ROOT / '.migration-logs/helper-provider')
    args = parser.parse_args(argv)
    if args.windows and sys.platform != 'win32':
        parser.error('--windows requires Windows; actual providers cannot be replaced with skips')
    logs = args.log_dir.resolve(); logs.mkdir(parents=True, exist_ok=True)
    records, failures = [], []
    summary = dict(schema='cucp.helper-provider-qualification/v1', status='running', windows_required=args.windows,
                   retirement_credit=0, platform=platform.platform(), python_version=sys.version, original_provider_parity='unqualified-not-compared', records=records, failures=failures,
                   groups_required=list(GROUPS), cases_required=sum(map(len,GROUPS.values())), cases_validated=0)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    def run(label, command, timeout=180, creationflags=0):
        result = run_evidence(command, cwd=ROOT, env=env, directory=logs, label=label, timeout=timeout, limit=16*1024*1024, creationflags=creationflags)
        records.append(dict(label=label,evidence=result['evidence_path']))
        require_success(result)
        return result
    try:
        sources = ['tests/fixtures/legacy-helper-provider-probe/Program.cs', 'tests/fixtures/legacy-helper-provider-probe/LegacyHelperProviderProbe.csproj',
                   'tests/fixtures/legacy-observation-owned-window/Program.cs', 'tests/python/helper_provider_expectations.py',
                   'tests/python/test_legacy_helper_providers.py', 'pcucp-next/packaging/qualify_legacy_helper_providers.py',
                   'pcucp-next/dotnet/PcuCp.LegacyHelper/LegacyHelperActions.cs', 'pcucp-next/dotnet/PcuCp.LegacyHelper/LegacyHelperProviders.cs']
        (logs/'source-hashes.json').write_text(json.dumps({name:dict(bytes=len((ROOT/name).read_bytes()),sha256=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()) for name in sources},indent=2))
        regressions=run('expectation-regressions',[sys.executable,'-m','unittest','discover','-s','tests/python','-p','test_legacy_helper_providers.py','-v'])
        require_regressions(regressions,sys.platform=='win32')
        if not args.windows:
            summary['status']='portable-only-windows-unqualified'
            return 0
        for project in ('tests/fixtures/legacy-helper-provider-probe','tests/fixtures/legacy-observation-owned-window'):
            run('build-'+Path(project).name,['dotnet','build',str(ROOT/project),'-c','Release','-warnaserror','-m:1','-p:UseSharedCompilation=false'],timeout=300)
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
                for group in GROUPS:
                    try:
                        result=run('actual-'+group,[probe_exe,group,ready_path,str(fixture.process.pid)],timeout=90,creationflags=0x08000000)
                        if result['stderr']: raise AssertionError('Probe emitted stderr; raw evidence retained')
                        rows=[json.loads(line) for line in result['stdout'].decode('utf-8-sig').splitlines()]
                        verify_images(rows,fixture_dir,group)
                        errors=validate_group(group,rows,ready)
                        failures.extend(dict(group=group,**error) for error in errors)
                        summary['cases_validated']+=len(rows)-len(errors)
                    except Exception as error: failures.append(dict(group=group,error=str(error)))
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
