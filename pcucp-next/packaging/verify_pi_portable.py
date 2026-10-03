"""Run Pi adapter smoke with only Windows system programs on the child PATH."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args(argv)
    node = shutil.which('node')
    engine = args.bundle.resolve() / 'CUCP.exe'
    if not node or not engine.is_file() or 'SystemRoot' not in os.environ:
        parser.error('Requires Windows, native Node and a complete existing portable bundle')
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(('CUCP_', 'PYTHON', 'DOTNET'))}
    env['CUCP_EXECUTABLE'] = str(engine)
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    return subprocess.run([node, '--import', 'tsx', 'test/engine-smoke.ts'],
                          cwd=ROOT / 'integrations/pi', env=env, shell=False, timeout=120).returncode


if __name__ == '__main__':
    raise SystemExit(main())
