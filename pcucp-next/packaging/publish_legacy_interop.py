#!/usr/bin/env python3
"""Build the legacy Win32 interop DLL for Windows PowerShell 5.1 (no PowerShell compilation)."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ASSEMBLY = "PcuCp.LegacyInterop.dll"


def build_command(dotnet, output):
    """Use argv-only build; net48 is framework-dependent and architecture-neutral."""
    return [str(dotnet), "build", str(ROOT / "pcucp-next/dotnet/PcuCp.LegacyInterop/PcuCp.LegacyInterop.csproj"),
            "-c", "Release", "--output", str(Path(output).resolve())]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "pcucp-next/bin/legacy")
    parser.add_argument("--dotnet", default="dotnet", help="SDK executable name or path")
    args = parser.parse_args(argv)
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        parser.error("dotnet SDK executable not found; install the SDK separately")
    result = subprocess.run(build_command(dotnet, args.output), cwd=ROOT, shell=False)
    if result.returncode:
        return result.returncode
    artifact = args.output.resolve() / ASSEMBLY
    if not artifact.is_file():
        parser.error(f"build succeeded but the expected artifact is missing: {artifact}")
    print(f"Built Windows PowerShell 5.1 interop: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
