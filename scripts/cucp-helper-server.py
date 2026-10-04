"""Persistent read-only CUCP helper. Python startup; compiled C# pipe service."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_helper_runtime import validate_package, REQUIRED_FILES

HELPER_VERSION = '2.0.0'


def command(package, *, pipe_name=None, lock_file=None, idle_timeout_ms=60000, debug_log=False):
    if type(idle_timeout_ms) is not int or not 0 <= idle_timeout_ms <= 2147483647:
        raise ValueError('Idle timeout must be a nonnegative Int32')
    validate_package(package)
    lock_file = Path(lock_file or Path(tempfile.gettempdir()) / 'computer-use-control-plane/helper.pid').absolute()
    if pipe_name:
        argv = [str(Path(package) / REQUIRED_FILES[0]), 'serve-direct', '--pipe-name', pipe_name]
    else:
        argv = [str(Path(package) / REQUIRED_FILES[0]), 'serve']
    argv += ['--lock-file', str(lock_file), '--idle-timeout-ms', str(idle_timeout_ms), '--allow-readonly-desktop']
    if debug_log: argv.append('--debug-log')
    return argv, lock_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipe-name', '-PipeName')
    parser.add_argument('--idle-timeout-ms', '-IdleTimeoutMs', type=int, default=60000)
    parser.add_argument('--lock-file', '-LockFile', type=Path)
    parser.add_argument('--debug-log', '-DebugLog', action='store_true')
    parser.add_argument('--package', type=Path, default=ROOT / 'pcucp-next/bin/legacy-helper', help='Explicit trusted startup package')
    args = parser.parse_args(argv)
    try:
        if os.name != 'nt': raise ValueError('Persistent helper requires Windows')
        arguments, lock_file = command(args.package, pipe_name=args.pipe_name,
            lock_file=args.lock_file, idle_timeout_ms=args.idle_timeout_ms, debug_log=args.debug_log)
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        return subprocess.run(arguments, shell=False, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
            creationflags=subprocess.CREATE_NO_WINDOW).returncode
    except (OSError, ValueError) as error:
        print('CUCP helper server: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
