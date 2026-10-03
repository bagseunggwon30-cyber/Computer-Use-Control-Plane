#!/usr/bin/env python3
"""Isolated legacy helper candidate gate. Never promotes adapters or touches a desktop."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/python'))
from helper_process_evidence import run_evidence, require_success


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true', help='Require Windows net48 pipe and PS5 oracle checks')
    parser.add_argument('--log-dir', type=Path, default=ROOT / '.migration-logs/helper-candidate')
    args = parser.parse_args(argv)
    if args.windows and sys.platform != 'win32':
        parser.error('--windows requires Windows; refusing to substitute skipped tests')
    logs = args.log_dir.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'pcucp-next/python'), PYTHONIOENCODING='utf-8', CUCP_HELPER_EVIDENCE_DIR=str(logs))
    index = 0
    def run(command, timeout=120):
        nonlocal index
        index += 1
        result = run_evidence(command, cwd=ROOT, env=env, directory=logs, label=f'{index:02d}-gate', timeout=timeout, limit=2 * 1024 * 1024)
        print(result['evidence_path'], flush=True)
        # Evidence is already persisted even if decoding/printing/assertion fails.
        print(result['stdout'].decode('utf-8', errors='replace')[-16384:], end='', flush=True)
        print(result['stderr'].decode('utf-8', errors='replace')[-16384:], end='', file=sys.stderr, flush=True)
        require_success(result)
    contracts = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHelper.ContractTests'
    run(['dotnet', 'build', str(contracts), '-c', 'Release', '-warnaserror', '-m:1', '-p:UseSharedCompilation=false'])
    env['CUCP_LEGACY_HELPER_CONTRACT_HOST'] = str(contracts / 'bin/Release/net8.0/PcuCp.LegacyHelper.ContractTests.dll')
    run(['dotnet', env['CUCP_LEGACY_HELPER_CONTRACT_HOST'], '--self-test'])
    if args.windows:
        host = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHelper'
        probe = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHelper.TransportTests'
        run(['dotnet', 'build', str(probe), '-c', 'Release', '-warnaserror', '-m:1', '-p:UseSharedCompilation=false'])
        run(['dotnet', 'build', str(ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHelper.OracleFixtures'), '-c', 'Release', '-warnaserror', '-m:1', '-p:UseSharedCompilation=false'])
        env['CUCP_LEGACY_HELPER_TEST_HOST'] = str(host / 'bin/Release/net48/PcuCp.LegacyHelper.exe')
        env['CUCP_LEGACY_HELPER_TRANSPORT_PROBE'] = str(probe / 'bin/Release/net48/PcuCp.LegacyHelper.TransportTests.exe')
        env['CUCP_REQUIRE_HELPER_ORACLE'] = '1'
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/python', '-p', 'test_helper_process_evidence.py', '-v'])
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/python', '-p', 'test_legacy_helper*.py', '-v'], timeout=300)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
