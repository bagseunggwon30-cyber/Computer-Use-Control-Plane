#!/usr/bin/env python3
"""Publish the C# native host with argv-only invocation. No PowerShell required."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def publish_command(dotnet, runtime, output):
    if runtime not in {'win-x64', 'win-arm64'}:
        raise ValueError('runtime must be win-x64 or win-arm64')
    return [str(dotnet), 'publish', str(ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/PcuCp.NativeHost.csproj'),
            '-c', 'Release', '-r', runtime, '--self-contained', 'true', '-o', str(Path(output).resolve())]

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', '-Runtime', choices=['win-x64', 'win-arm64'], default='win-x64')
    parser.add_argument('--output', '-OutputDirectory', type=Path, default=ROOT / 'pcucp-next/bin/native')
    parser.add_argument('--dotnet', default='dotnet', help='SDK executable name or path')
    args = parser.parse_args(argv)
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        parser.error('dotnet SDK executable not found; install the SDK separately')
    result = subprocess.run(publish_command(dotnet, args.runtime, args.output), cwd=ROOT, shell=False)
    if result.returncode == 0:
        print(f'Published PcuCp.NativeHost.exe to {args.output.resolve()}')
    return result.returncode

if __name__ == '__main__':
    raise SystemExit(main())
