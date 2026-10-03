"""Fixed logon bootstrap for explicitly installed staged helper launchers.

No registration or arbitrary argv execution. A successful owned service remains
detached. Environment variables cannot elevate its explicit provider authority.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from pcucp_cli.legacy_helper_client import _positive_integer
from pcucp_cli.legacy_helper_runtime import StagedHelperRuntime, validate_package


def start_once(idle_timeout_ms, desktop, *, temp_root, package, runtime_factory=StagedHelperRuntime):
    _positive_integer(idle_timeout_ms,'idle_timeout_ms')
    if type(desktop) is not bool: raise ValueError('invalid_desktop_authority')
    validate_package(package)
    if not temp_root: raise ValueError('TEMP is required for the staged helper lock')
    directory=Path(temp_root)/'computer-use-control-plane'
    directory.mkdir(parents=True,exist_ok=True)
    runtime=runtime_factory(package,directory/'helper-staged.pid',desktop=desktop)
    return runtime.client.start(runtime.launcher,idle_timeout_ms=idle_timeout_ms)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged-unqualified',action='store_true',required=True)
    parser.add_argument('--idle-timeout-ms',type=int,default=28800000)
    parser.add_argument('--allow-readonly-desktop',action='store_true')
    args=parser.parse_args(argv)
    try:
        package=Path(__file__).resolve().parents[1]/'bin/legacy-helper'
        result=start_once(args.idle_timeout_ms,args.allow_readonly_desktop,temp_root=os.environ.get('TEMP'),package=package)
    except Exception as exc:
        result=dict(status='error',reason=str(exc)[:512])
    print(json.dumps(result,ensure_ascii=True,allow_nan=False,separators=(',',':')))
    return 0 if result.get('status')=='ok' else 1

if __name__=='__main__': raise SystemExit(main())
