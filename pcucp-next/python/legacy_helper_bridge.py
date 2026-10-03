"""Fixed source-mode bridge. Staged opt-in only; never falls back or retries."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from pcucp_cli.legacy_helper_client import _json
from pcucp_cli.legacy_helper_runtime import StagedHelperRuntime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged-unqualified', action='store_true', required=True)
    parser.add_argument('--lock-file', type=Path, required=True)
    parser.add_argument('--allow-readonly-desktop', action='store_true')
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise ValueError('helper_bridge_request_too_large')
        request = _json(raw)
        # Resolve from this checked-in entry, never CUCP_ROOT/CWD/request/env path.
        package = Path(__file__).resolve().parents[1] / 'bin/legacy-helper'
        runtime = StagedHelperRuntime(package, args.lock_file, desktop=args.allow_readonly_desktop)
        response = dict(schema='cucp.staged-helper-bridge/v1', status='ok', data=runtime.handle(request))
        code = 0
    except Exception as exc:
        # No exception text from arbitrary pipe data is injected into public logs.
        response = dict(schema='cucp.staged-helper-bridge/v1', status='error', reason=str(exc)[:512])
        code = 1
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > 2 * 1024 * 1024:
        encoded = b'{"schema":"cucp.staged-helper-bridge/v1","status":"error","reason":"response_too_large"}'
        code = 1
    sys.stdout.buffer.write(encoded + b'\n')
    return code


if __name__ == '__main__': raise SystemExit(main())
