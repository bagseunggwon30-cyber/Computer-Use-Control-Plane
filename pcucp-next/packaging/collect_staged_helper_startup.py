"""Collect owned Windows startup observations, never label failures as passes.

The exact built package is observed under inherited, no-window, and detached
startup. A distinct tiny probe compares the old console setter with stream
writers. Neither executes desktop providers. Existing runtime assertions remain
separate and mandatory; this collector's success means evidence was captured.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/python'))
sys.path.insert(0,str(ROOT/'pcucp-next/python'))
from helper_process_evidence import run_evidence
from pcucp_cli.legacy_helper_runtime import validate_package


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,default=ROOT/'pcucp-next/bin/legacy-helper')
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--log-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    if sys.platform!='win32': parser.error('actual Windows is required')
    manifest=validate_package(args.package)
    if not args.probe.is_file(): parser.error('compiled startup probe is required')
    args.log_dir.mkdir(parents=True,exist_ok=True)
    observations=[]
    infrastructure=[]
    modes=(('inherited',0),('no-window',subprocess.CREATE_NO_WINDOW),
           ('detached',subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP))
    with tempfile.TemporaryDirectory(prefix='CUCP startup diagnostics 한글 ') as root:
        for mode, flags in modes:
            for idle in (-1,0):
                lock=Path(root)/('owned-'+mode+'-'+str(idle)+'.pid')
                result=run_evidence([args.package/'PcuCp.LegacyHelper.exe','serve','--lock-file',lock,'--idle-timeout-ms',str(idle)],
                    directory=args.log_dir,label='packaged-startup-'+mode+'-'+str(idle),timeout=5,limit=65536,creationflags=flags)
                observations.append(dict(kind='exact-package',mode=mode,idle_timeout_ms=idle,exit_code=result['exit_code'],
                    lock_exists=lock.exists(),evidence=result['evidence_path']))
                infrastructure.append(result)
            for implementation in ('legacy-setter','stream-writers'):
                result=run_evidence([args.probe,implementation],directory=args.log_dir,
                    label='console-probe-'+mode+'-'+implementation,timeout=5,limit=65536,creationflags=flags)
                observations.append(dict(kind='console-boundary-probe',mode=mode,implementation=implementation,
                    exit_code=result['exit_code'],evidence=result['evidence_path']))
                infrastructure.append(result)
    summary=dict(schema='cucp.staged-helper-startup-observations/v1',qualification='not-qualified-observations-only',
        package_manifest=manifest,probe_sha256=hashlib.sha256(args.probe.read_bytes()).hexdigest(),observations=observations)
    path=args.log_dir/'startup-observations.json'
    path.write_text(json.dumps(summary,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
    print(str(path))
    # Crashes are observations, not accepted rejections. Infrastructure failures
    # fail collection; ordinary runtime failures still fail the unchanged tests.
    return 1 if any(r['launch_error'] or r['timed_out'] or r['running'] or r['kill_error'] or r['drain_incomplete']
                    or r['stdin_error'] or r['read_errors'] or any(r['truncated'].values()) for r in infrastructure) else 0

if __name__=='__main__': raise SystemExit(main())
