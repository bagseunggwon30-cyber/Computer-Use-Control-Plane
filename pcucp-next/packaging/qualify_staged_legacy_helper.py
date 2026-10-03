"""Explicit production-route staging gate. Not action or promotion qualification.

Windows mode builds the fixed package, then executes only owned denied-desktop
runtime and real-wrapper lifecycle fixtures. Optional autostart fixtures write
only owned temporary directories, never real Startup/LocalAppData registrations.
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
    parser.add_argument('--direct',action='store_true',help='include explicitly owned direct custom-pipe fixtures')
    parser.add_argument('--autostart',action='store_true',help='include owned temporary autostart/launcher fixtures, never real registration')
    parser.add_argument('--log-dir',type=Path,default=ROOT/'.migration-logs/staged-helper')
    args=parser.parse_args(argv)
    if args.windows and sys.platform!='win32': parser.error('--windows requires actual Windows')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'pcucp-next/python'),PYTHONIOENCODING='utf-8',CUCP_HELPER_EVIDENCE_DIR=str(args.log_dir.resolve()))
    env.pop('CUCP_REQUIRE_HELPER_DIRECT',None)
    if args.windows: env['CUCP_REQUIRE_STAGED_HELPER']='1'
    if args.windows and args.autostart: env['CUCP_REQUIRE_STAGED_AUTOSTART']='1'
    def run(argv,label):
        evidence=run_evidence([str(a) for a in argv],directory=args.log_dir,label=label,cwd=ROOT,env=env,timeout=300,limit=2*1024*1024)
        print(evidence['evidence_path'],flush=True)
        print(evidence['stdout'].decode('utf-8',errors='replace')[-16384:],end='')
        print(evidence['stderr'].decode('utf-8',errors='replace')[-16384:],end='',file=sys.stderr)
        require_success(evidence)
    if args.windows:
        # Refuse stale/reused artifacts; publisher refuses existing output. Use a
        # clean checkout or explicitly review/remove a previous owned build first.
        run([sys.executable,ROOT/'pcucp-next/packaging/publish_legacy_helper.py','--evidence-dir',args.log_dir],'package')
        project=ROOT/'tests/fixtures/legacy-helper-startup-probe/LegacyHelperStartupProbe.csproj'
        run(['dotnet','build',project,'-c','Release','-warnaserror','-m:1','-p:UseSharedCompilation=false'],'startup-probe-build')
        run([sys.executable,ROOT/'pcucp-next/packaging/collect_staged_helper_startup.py','--probe',
             project.parent/'bin/Release/net48/LegacyHelperStartupProbe.exe','--log-dir',args.log_dir], 'startup-observations')
    if args.direct:
        project=ROOT/'pcucp-next/dotnet/PcuCp.LegacyHelper.ContractTests'
        run(['dotnet','build',project,'-c','Release','-warnaserror','-m:1','-p:UseSharedCompilation=false'],'direct-contract-build')
        env['CUCP_LEGACY_HELPER_CONTRACT_HOST']=str(project/'bin/Release/net8.0/PcuCp.LegacyHelper.ContractTests.dll')
        if args.windows:
            project=ROOT/'pcucp-next/dotnet/PcuCp.LegacyHelper.TransportTests'
            run(['dotnet','build',project,'-c','Release','-warnaserror','-m:1','-p:UseSharedCompilation=false'],'direct-probe-build')
            env['CUCP_LEGACY_HELPER_TRANSPORT_PROBE']=str(project/'bin/Release/net48/PcuCp.LegacyHelper.TransportTests.exe')
            env['CUCP_REQUIRE_HELPER_DIRECT']='1'
    suites=[('test_helper_process_evidence.py','evidence-collector-tests'),
            ('test_legacy_helper_package.py','helper-package-tests'),
            ('test_legacy_helper_runtime.py','helper-runtime-tests'),
            ('test_legacy_helper_client.py','helper-client-tests')]
    if args.autostart: suites.append(('test_legacy_helper_autostart*.py','helper-autostart-tests'))
    if args.direct: suites.append(('test_legacy_helper_direct.py','helper-direct-tests'))
    for pattern,label in suites:
        run([sys.executable,'-m','unittest','discover','-s','tests/python','-p',pattern,'-v'],label)
    return 0

if __name__=='__main__': raise SystemExit(main())
