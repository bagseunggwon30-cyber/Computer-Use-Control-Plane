#!/usr/bin/env python3
"""Build the separate unqualified net48 observation candidate; never activate it."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
ROOT = Path(__file__).resolve().parents[2]

def build_command(dotnet, output):
    return [str(dotnet), 'build', str(ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation/PcuCp.LegacyObservation.csproj'),
            '-c', 'Release', '--output', str(Path(output).resolve())]

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'pcucp-next/bin/legacy-observation')
    parser.add_argument('--dotnet',default='dotnet')
    args=parser.parse_args(argv)
    dotnet=shutil.which(args.dotnet)
    if not dotnet:parser.error('dotnet SDK not found; install the SDK separately')
    result=subprocess.run(build_command(dotnet,args.output),cwd=ROOT,shell=False)
    if result.returncode:return result.returncode
    for name in ('PcuCp.LegacyObservation.dll','PcuCp.LegacyInterop.dll'):
        if not (args.output.resolve()/name).is_file():parser.error('Missing candidate build artifact: '+name)
    print('Built unqualified observation candidate; no routing/default was changed: '+str(args.output.resolve()))
    return 0
if __name__=='__main__':raise SystemExit(main())
