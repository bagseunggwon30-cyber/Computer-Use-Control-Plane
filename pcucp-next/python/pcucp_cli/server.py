"""Local newline-delimited JSON transport; stdout is reserved for responses."""
from __future__ import annotations
import json
import signal
import sys
from .engine import ComputerSession
from .native_host import cancel_all_native

MAX_REQUEST_BYTES = 256 * 1024

def protocol_error(code, message):
    return {'schema': 'cucp.response/v1', 'id': None, 'command': None,
            'status': 'error', 'data': {}, 'errors': [{'code': code, 'message': message}], 'duration_ms': 0}

def serve(*, allow_live_control=False, source=None, sink=None):
    source = source if source is not None else sys.stdin.buffer
    sink = sink if sink is not None else sys.stdout
    session = ComputerSession(allow_live_control=allow_live_control)
    while True:
        line = source.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return 0
        if len(line) > MAX_REQUEST_BYTES:
            # End the session instead of draining an unbounded hostile frame.
            sink.write(json.dumps(protocol_error('request_too_large', 'maximum frame is 256 KiB')) + '\n')
            sink.flush()
            return 2
        try:
            request = json.loads(line.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError, RecursionError) as exc:
            response = protocol_error('invalid_json', str(exc))
        else:
            response = session.handle(request)
        sink.write(json.dumps(response, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
        sink.flush()

def run_server(*, allow_live_control=False):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    def stop(signum, frame):
        cancel_all_native()
        raise SystemExit(128 + signum)
    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return serve(allow_live_control=allow_live_control)
    except BrokenPipeError:
        return 1
    finally:
        cancel_all_native()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
