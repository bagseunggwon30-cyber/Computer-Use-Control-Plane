"""Explicit staged legacy entry. Never selected by existing legacy launchers.

Run: python -m pcucp_cli.legacy_host_entry --staged-brief-host --brief -- macro ...
Only the documented brief/read-only subset is enabled. Omitted flags do not
silently enter the modern engine or the retained PowerShell wrapper.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import signal
import sys
import time

from .legacy_host import HostOptions, LegacyHost
from .legacy_cdp_contract import _ps_equal
from .legacy_host_protocol import Authority, LegacyHostError, MAX_STARTUP_BYTES, parse_json, require


class _Once(argparse.Action):
    """Trusted startup values are single assignment, including false defaults."""
    def __call__(self, parser, namespace, values, option_string=None):
        seen = getattr(namespace, '_seen_options', set())
        if self.dest in seen:
            parser.error('duplicate startup option: ' + option_string)
        seen.add(self.dest)
        namespace._seen_options = seen
        setattr(namespace, self.dest, self.const if self.nargs == 0 else values)


def _error(error):
    return json.dumps(dict(schema='cucp.legacy-host-error/v1', status='error',
        reason='unqualified_surface' if 'unqualified_surface:' in str(error) else 'legacy_host_failed',
        message=str(error), mutation_may_have_occurred=getattr(error, 'uncertain', False), automatic_retry=False),
        ensure_ascii=True, separators=(',', ':')) + '\n'


def _read_line(stream):
    value = stream.readline(MAX_STARTUP_BYTES + 1)
    require(len(value) <= MAX_STARTUP_BYTES, 'Legacy entry frame exceeds 32 MiB.')
    return value


def _daemon_int32(value):
    # The staged daemon accepts decimal Int32 literals only. Other original PS
    # coercions remain unqualified; do not silently widen to Python big integers.
    if not re.fullmatch(r'[+-]?[0-9]+', value):
        raise argparse.ArgumentTypeError('daemon option requires a decimal Int32 literal')
    result = int(value)
    if not -(2**31) <= result < 2**31:
        raise argparse.ArgumentTypeError('daemon option exceeds Int32')
    return result


def serve(host, rest, *, brief, input_stream, output):
    """Legacy sentinel ownership: one owner and cache for the whole daemon.

    This checkpoint accepts only typed string argv and sentinel-safe scalar IDs.
    Legacy coercion of arbitrary JSON objects and daemon batch remain unqualified.
    ``idle-timeout-ms`` remains informational, as in the retained daemon.
    """
    require(brief, 'unqualified_surface: daemon requires the staged brief output mode.')
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--max-commands', type=_daemon_int32, action=_Once, default=1000)
    parser.add_argument('--idle-timeout-ms', type=_daemon_int32, action=_Once, default=1800000)
    options = parser.parse_args(rest)
    maximum = options.max_commands if options.max_commands > 0 else 1000
    ready = dict(schema='cucp.daemon-serve/v1', status='ready', live=host.authority.live,
                 pid=os.getpid(), max_commands=maximum, protocol='sentinel')
    output.write(json.dumps(ready, separators=(',', ':')) + '\n')
    output.flush()
    served = 0
    while served < maximum:
        raw = _read_line(input_stream)
        if not raw:
            break
        if not raw.strip():
            continue
        try:
            request = parse_json(raw)
        except LegacyHostError:
            output.write('{"schema":"cucp.daemon-serve/v1","status":"error","reason":"bad_json"}\n')
            output.flush()
            continue
        require(type(request) is dict, 'Daemon request must be an object.')
        action = request.get('action')
        if type(action) is str and _ps_equal(action, 'shutdown'):
            output.write(json.dumps(dict(schema='cucp.daemon-serve/v1', status='shutdown', served=served), separators=(',', ':')) + '\n')
            output.flush()
            break
        if type(action) is str and _ps_equal(action, 'ping'):
            output.write(json.dumps(dict(schema='cucp.daemon-serve/v1', action='ping', ok=True,
                live=host.authority.live, served=served), separators=(',', ':')) + '\n')
            output.flush()
            continue
        require(not (set(request) - {'id', 'macro', 'args'}), 'Unqualified daemon request fields or authority override.')
        name = request.get('macro')
        if not name:
            output.write(json.dumps(dict(schema='cucp.daemon-serve/v1', id=request.get('id'), status='error', reason='no_macro'), separators=(',', ':')) + '\n')
            output.flush()
            continue
        require(type(name) is str, 'Daemon macro must be a string.')
        identifier = request.get('id')
        require(identifier is None or type(identifier) in (int, str), 'Daemon ID must be a scalar string or integer.')
        identifier = '' if identifier is None else str(identifier)
        require('\r' not in identifier and '\n' not in identifier and '>>>' not in identifier,
                'Daemon ID could break sentinel framing.')
        argv = request.get('args', [])
        require(type(argv) is list and all(type(item) is str for item in argv), 'Daemon args must be a string array.')
        output.write('<<<CUCP-RESP id=' + identifier + '>>>\n')
        output.flush()
        started = time.monotonic()
        failed = None
        try:
            code, text = host.invoke(['macro', name, *argv], brief=brief)
            if '<<<CUCP-' in text:
                host.close()
                raise LegacyHostError('unqualified_surface: daemon output contains a reserved sentinel prefix.')
            output.write(text)
        except (LegacyHostError, ValueError, OSError) as error:
            code, failed = 1, error
            output.write(_error(error))
        output.flush()
        elapsed = int((time.monotonic() - started) * 1000)
        output.write(f'<<<CUCP-END id={identifier} exit={code} ms={elapsed}>>>\n')
        output.flush()
        served += 1
        # A failed/uncertain coordinator transport poisoned the owning host.
        # Do not consume another queued command or attempt an implicit restart.
        if failed is not None and host.closed:
            return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--staged-brief-host', action=_Once, nargs=0, const=True, default=False, required=True)
    parser.add_argument('--brief', action=_Once, nargs=0, const=True, default=False)
    parser.add_argument('--quiet', action=_Once, nargs=0, const=True, default=False)
    parser.add_argument('--allow-live-control', action=_Once, nargs=0, const=True, default=False)
    parser.add_argument('--confirm-sensitive-ceiling', action=_Once, nargs=0, const=True, default=False)
    parser.add_argument('--typed-child', action=_Once, nargs=0, const=True, default=False)
    parser.add_argument('--changelog', action=_Once, default=str(Path(__file__).resolve().parents[3] / 'CHANGELOG.md'))
    parser.add_argument('--cdp-endpoint', action=_Once, default='http://127.0.0.1:9222')
    parser.add_argument('--timeout-s', action=_Once, type=float, default=30)
    parser.add_argument('--culture', action=_Once, default='en-US')
    parser.add_argument('legacy_argv', nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    host = None
    previous = {}
    try:
        host = LegacyHost(HostOptions(str(Path(options.changelog).absolute()), options.cdp_endpoint,
            options.timeout_s, options.culture), Authority(options.allow_live_control, options.confirm_sensitive_ceiling))
        def cancel(signum, frame):
            # Never synchronously re-enter a CDP/pipe lock on the interrupted
            # thread. Unwind first; the owning finally closes all resources.
            raise KeyboardInterrupt('Legacy host cancelled; action not retried.')
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
        legacy_argv = options.legacy_argv
        if legacy_argv and legacy_argv[0] == '--':
            legacy_argv = legacy_argv[1:]
        if options.typed_child:
            require(not legacy_argv, 'Typed child accepts only one bounded stdin request.')
            raw = sys.stdin.buffer.read(MAX_STARTUP_BYTES + 1)
            require(len(raw) <= MAX_STARTUP_BYTES, 'Typed child request exceeds 32 MiB.')
            code, text = host.typed_child(parse_json(raw))
        elif len(legacy_argv) >= 3 and [part.lower() for part in legacy_argv[:3]] == ['macro', 'daemon', 'serve']:
            return serve(host, legacy_argv[3:], brief=options.brief, input_stream=sys.stdin.buffer, output=sys.stdout)
        else:
            code, text = host.invoke(legacy_argv, brief=options.brief, quiet=options.quiet)
        sys.stdout.write(text)
        sys.stdout.flush()
        return code
    except KeyboardInterrupt as error:
        sys.stderr.write(_error(error))
        return 130
    except (LegacyHostError, OSError, ValueError, OverflowError) as error:
        sys.stderr.write(_error(error))
        return 1
    finally:
        if host is not None:
            host.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict', newline='\n')
    raise SystemExit(main())
