"""Publish the retained desktop acquisition/input backend without PowerShell."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FILES = ('PcuCp.LegacyDesktop.exe', 'PcuCp.LegacyDesktop.exe.config', 'PcuCp.LegacyInterop.dll',
         'PcuCp.LegacyObservation.dll', 'PcuCp.LegacyImages.dll')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, default=ROOT / 'pcucp-next/bin/legacy-desktop')
    args = parser.parse_args(argv)
    dotnet = shutil.which('dotnet')
    if dotnet is None:
        parser.error('Install the .NET SDK before explicitly building the desktop package.')
    project = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyDesktop/PcuCp.LegacyDesktop.csproj'
    subprocess.run([dotnet, 'build', str(project), '-c', 'Release', '-warnaserror', '--nologo'], check=True, shell=False)
    source = project.parent / 'bin/Release/net48'
    output = args.output.resolve()
    if output.is_symlink():
        parser.error('Desktop output cannot be a reparse/symlink directory.')
    output.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in output.iterdir()}
    if existing - set(FILES) - {'manifest.json'}:
        parser.error('Desktop output must be a dedicated package directory.')
    entries = {}
    for name in FILES:
        raw = (source / name).read_bytes()
        (output / name).write_bytes(raw)
        entries[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest = dict(schema='cucp.legacy-desktop-package/v1', status='staged', runtime='net48', entrypoint=FILES[0], files=entries)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Published the staged legacy desktop backend: ' + str(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
