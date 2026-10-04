"""Explicitly publish the read-only Windows workflow syntax adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FILES = ('PcuCp.LegacySyntax.exe', 'PcuCp.LegacySyntax.exe.config')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, default=ROOT / 'pcucp-next/bin/legacy-syntax')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
    from pcucp_cli.legacy_diagnostic_provider import owned_path
    output = owned_path(str(args.output.absolute()))
    dotnet = shutil.which('dotnet')
    if dotnet is None:
        parser.error('Install the Windows .NET SDK before explicitly publishing syntax compatibility.')
    project = ROOT / 'pcucp-next/dotnet/PcuCp.LegacySyntax/PcuCp.LegacySyntax.csproj'
    subprocess.run([dotnet, 'build', str(project), '-c', 'Release', '-warnaserror', '--nologo'], check=True, shell=False)
    source = project.parent / 'bin/Release/net48'
    output.mkdir(parents=True, exist_ok=True)
    if {path.name for path in output.iterdir()} - set(FILES) - {'manifest.json'}:
        parser.error('Syntax output must be a dedicated package directory.')
    entries = {}
    for name in FILES:
        raw = (source / name).read_bytes()
        owned_path(str(output / name)).write_bytes(raw)
        entries[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest = dict(schema='cucp.legacy-syntax-package/v1', status='staged', runtime='net48',
        entrypoint=FILES[0], files=entries, system_dependencies=['Windows PowerShell 5.1 read-only PSParser API'])
    owned_path(str(output / 'manifest.json')).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Published read-only syntax compatibility: ' + str(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
