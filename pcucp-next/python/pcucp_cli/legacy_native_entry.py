"""Classic native helper CLI implemented by Python and the compiled C# worker."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from .legacy_execution_runtime import ExecutionRuntime
from .legacy_host_protocol import Authority, LegacyHostError, require


def startup(argv):
    """Startup switches precede classic helper argv; option-looking text is data."""
    arguments, live, timeout = list(argv), False, 30.0
    seen = set()
    while arguments and arguments[0] in ('--allow-live-control', '--timeout-s'):
        name = arguments.pop(0)
        require(name not in seen, 'Duplicate native startup switch.')
        seen.add(name)
        if name == '--allow-live-control':
            live = True
        else:
            require(bool(arguments), 'Missing native timeout.')
            timeout = float(arguments.pop(0))
            require(math.isfinite(timeout) and timeout > 0, 'Native timeout must be finite and positive.')
    return arguments, Authority(live), timeout


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    started = time.monotonic()
    runtime = None
    action = ''
    try:
        arguments, authority, timeout = startup(sys.argv[1:] if argv is None else argv)
        require(len(arguments) >= 2 and arguments[0].casefold() == '-action', 'Native helper requires -Action first.')
        arguments[0], arguments[1] = '-Action', arguments[1].casefold()
        action = arguments[1]
        deadline, cancelled = time.monotonic() + timeout, threading.Event()
        class Scope:
            def remaining(self):
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'Native helper timed out; action not retried.')
                return remaining
        scope = Scope()
        scope.cancelled = cancelled
        audit = Path(tempfile.gettempdir()) / 'computer-use-control-plane'
        runtime = ExecutionRuntime(audit_directory=str(audit), cache_directory=str(audit / 'wrapper-cache'),
            authority=authority, timeout_s=timeout, parent_deadline=deadline, parent_cancelled=cancelled)
        reply = runtime.native(arguments, authority, scope)
        sys.stdout.write(reply['Raw'])
        return reply['ExitCode']
    except (ValueError, OSError, LegacyHostError) as error:
        blocked = 'authority' in str(error).casefold() or 'live control' in str(error).casefold()
        payload = dict(status='blocked' if blocked else 'error', action=action, reason=str(error),
            elapsed_ms=round((time.monotonic() - started) * 1000))
        if getattr(error, 'uncertain', False):
            payload.update(mutation_may_have_occurred=True, automatic_retry=False)
        sys.stdout.write(json.dumps(payload, ensure_ascii=True, allow_nan=False) + '\n')
        return 3 if blocked else 1
    finally:
        if runtime is not None: runtime.close()


if __name__ == '__main__':
    raise SystemExit(main())
