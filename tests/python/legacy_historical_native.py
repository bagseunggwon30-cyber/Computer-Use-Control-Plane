"""Pinned historical native oracle, materialized only in owned qualification folders.

Production never imports this module. Git history supplies the old implementation;
the current native runtime is Python/C#. This is an oracle, not an installed backup.
"""
import argparse
import atexit
import hashlib
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REF = '8d41b3456f538ae3984f969cb26a882a792d2b8f'
PINS = {'scripts/cucp-native-helper.ps1': 'a1dfc5abd17a1cbea3f126117790df24b9894d808dfa5868713144503ad0dab8',
        'scripts/cucp.ps1': '0e07bb70a02ccce8436deb958ac9367c7d64fdc658f3d9cfcdfd9f2cdff673ad'}
_temporary = None


def read(path):
    if path not in PINS and path not in ('scripts/cucp-legacy-cdp-adapter.ps1', 'scripts/cucp-legacy-observation-adapter.ps1',
            'scripts/cucp-legacy-interaction-adapter.ps1', 'scripts/cucp-legacy-diagnostic-adapter.ps1',
            'scripts/cucp-staged-helper-adapter.ps1', 'scripts/cucp-helper-server.ps1'):
        raise ValueError('Unknown historical native qualification source')
    raw = subprocess.check_output(['git', 'show', REF + ':' + path], cwd=ROOT, timeout=15)
    if path in PINS and hashlib.sha256(raw).hexdigest() != PINS[path]:
        raise ValueError('Historical native qualification source hash drift')
    return raw


def materialize(directory):
    directory = Path(directory)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError('Historical oracle needs an absolute owned temporary directory')
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('cucp-native-helper.ps1', 'cucp.ps1', 'cucp-legacy-cdp-adapter.ps1', 'cucp-legacy-observation-adapter.ps1',
            'cucp-legacy-interaction-adapter.ps1', 'cucp-legacy-diagnostic-adapter.ps1', 'cucp-staged-helper-adapter.ps1', 'cucp-helper-server.ps1'):
        destination = directory / name
        # Never overwrite an unowned or edited oracle file.
        raw = read('scripts/' + name)
        if destination.is_symlink() or destination.exists() and destination.read_bytes() != raw:
            raise ValueError('Historical oracle destination collision')
        destination.write_bytes(raw)
    return directory


def scripts():
    global _temporary
    if _temporary is None:
        _temporary = tempfile.TemporaryDirectory(prefix='CUCP-historical-native-')
        atexit.register(_temporary.cleanup)
        materialize(Path(_temporary.name).resolve() / 'scripts')
    return Path(_temporary.name).resolve() / 'scripts'


def helper():
    return scripts() / 'cucp-native-helper.ps1'


def wrapper():
    return scripts() / 'cucp.ps1'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    arguments = parser.parse_args()
    print(materialize(arguments.directory) / 'cucp-native-helper.ps1')
