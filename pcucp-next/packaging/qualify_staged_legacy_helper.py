"""Explicit production-route staging gate. Not action or promotion qualification.

Windows mode builds the fixed package, then executes only owned denied-desktop
runtime and real-wrapper lifecycle fixtures. It never installs/registers anything.
Use the separate legacy helper action/oracle gate and full regression as well.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/python'))
from helper_process_evidence import run_evidence, require_success


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows',action='store_true')
    parser.add_argument('--log-dir',type=Path,default=ROOT/'.migration-logs/staged-helper')
    args=parser.parse_args(argv)
    if args.windows and sys.platform!='win32': parser.error('--windows requires actual Windows')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'pcucp-next/python'),PYTHONIOENCODING='utf-8',CUCP_HELPER_EVIDENCE_DIR=str(args.log_dir.resolve()))
    if args.windows: env['CUCP_REQUIRE_STAGED_HELPER']='1'
    def run(argv,label):
        evidence=run_evidence([str(a) for a in argv],directory=args.log_dir,label=label,cwd=ROOT,env=env,timeout=300,limit=2*1024*1024)
        print(evidence['evidence_path'],flush=True)
        print(evidence['stdout'].decode('utf-8',errors='replace')[-16384:],end='')
        print(evidence['stderr'].decode('utf-8',errors='replace')[-16384:],end='',file=sys.stderr)
        require_success(evidence)
    if args.windows:
        # Refuse stale/reused artifacts; publisher refuses existing output. Use a
        # clean checkout or explicitly review/remove a previous owned build first.
        run([sys.executable,ROOT/'pcucp-next/packaging/publish_legacy_helper.py'],'package')
    for pattern in ('test_legacy_helper_package.py','test_legacy_helper_runtime.py','test_legacy_helper_client.py'):
        run([sys.executable,'-m','unittest','discover','-s','tests/python','-p',pattern,'-v'],pattern)
    return 0

if __name__=='__main__': raise SystemExit(main())
