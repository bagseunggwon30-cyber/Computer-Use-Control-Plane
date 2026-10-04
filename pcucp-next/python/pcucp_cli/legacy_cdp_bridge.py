"""Bounded process operations for thin retained native-helper and macro adapters.

``native`` opens CDP; ``desktop-native`` owns the compiled Windows worker.
Pure macro stages return acquisition/effect
plans; they do not launch helpers, write logs, or render legacy Console output.
All authority comes from CLI/host startup, never the JSON request.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from typing import Any

from .cdp import CdpError, _json
from .legacy_cdp import LegacyCdpAdapter
from .legacy_cdp_contract import LegacyCdpResult, native_arguments, prepare_macro, prepare_native
from .legacy_cdp_macro import macro_output, port_closed_output
from .legacy_host_protocol import Authority, LegacyHostError

SCHEMA = 'cucp.legacy-cdp-bridge/v1'
MAX_FRAME = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024


def _fields(value: Any, required: set[str], optional: set[str] | None = None):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise ValueError('invalid bridge object fields')


def _helper_reply(reply: Any) -> tuple[LegacyCdpResult, str | None, bool]:
    _fields(reply, {'ExitCode', 'Json', 'Raw'}, {'Err'})
    if type(reply['ExitCode']) is not int or not -(2**31) <= reply['ExitCode'] < 2**31:
        raise ValueError('helper exit code must be a 32-bit integer')
    payload = reply['Json']
    if payload is not None and not isinstance(payload, dict):
        raise ValueError('helper Json must be an object or null')
    raw = reply['Raw']
    if raw is not None and not isinstance(raw, str):
        raise ValueError('helper Raw must be a string or null')
    return LegacyCdpResult(payload or {}, reply['ExitCode']), raw, payload is not None


def handle(operation: str, request: dict, *, allow_live_control=False, endpoint=None, timeout_s=8,
           cache_directory=None,audit_directory=None,history_file=None,history_maximum=None,
           coordinate_culture=None,coordinate_modern=False) -> dict:
    if type(allow_live_control) is not bool:
        raise ValueError('startup live authority must be boolean')
    if operation == 'coordinates':
        if any(value is not None for value in (cache_directory, audit_directory, endpoint, history_file, history_maximum)):
            raise ValueError('Unexpected coordinate bootstrap values')
        from .legacy_coordinate_runtime import handle as coordinate_handle
        return coordinate_handle(request, timeout_s=timeout_s,
                                 culture=coordinate_culture if coordinate_culture is not None else 'en-US', modern=coordinate_modern)
    if coordinate_culture is not None or coordinate_modern:
        raise ValueError('Unexpected coordinate bootstrap settings')
    if operation == 'history-storage':
        if cache_directory is not None or audit_directory is not None or endpoint is not None:
            raise ValueError('Unexpected history bootstrap values')
        from .legacy_history_bridge import handle as history_handle
        return history_handle(request, history_file=history_file, maximum=history_maximum)
    if history_file is not None or history_maximum is not None:
        raise ValueError('Unexpected history bootstrap destination')
    if operation in ('native-macro-prepare','native-macro-complete'):
        fields={'name','rest'}
        if operation=='native-macro-complete': fields|={'reply','prepared','brief'}
        _fields(request,fields)
        if type(request['name']) is not str or type(request['rest']) is not list or any(type(v) is not str for v in request['rest']):
            raise ValueError('Native macro name and argv must be inert strings')
        if type(cache_directory) is not str or type(audit_directory) is not str:
            raise ValueError('Native macro directories must be supplied at startup')
        from .legacy_native_macros import NativeMacros
        runtime=NativeMacros(None,cache_directory=cache_directory,
            audit_directory=audit_directory,authority=Authority(allow_live_control))
        if operation=='native-macro-prepare': return runtime.prepare(request['name'],request['rest'])
        _fields(request['reply'],{'ExitCode','Json','Raw','Err','ElapsedMs'})
        reply=request['reply']
        if (type(reply['ExitCode']) is not int or not -(2**31)<=reply['ExitCode']<2**31 or
            type(reply['ElapsedMs']) is not int or not 0<=reply['ElapsedMs']<2**31 or
            reply['Json'] is not None and type(reply['Json']) is not dict or
            any(reply[k] is not None and type(reply[k]) is not str for k in ('Raw','Err'))):
            raise ValueError('Invalid native helper reply')
        if type(request['brief']) is not bool: raise ValueError('Native macro brief flag must be boolean')
        return runtime.complete(request['name'],request['rest'],request['reply'],request['prepared'],brief=request['brief'])
    if cache_directory is not None or audit_directory is not None:
        raise ValueError('Unexpected native macro bootstrap directories')
    if operation == 'desktop-native':
        _fields(request, {'argv'})
        from .legacy_native_desktop import DesktopSession
        return DesktopSession(authority=Authority(allow_live_control), timeout_s=timeout_s).run(request['argv'])
    if operation == 'native-prepare':
        _fields(request, {'argv'})
        native = prepare_native(request['argv'])
        return {'action': native.action, 'args': native.args, 'port': native.port}
    if operation == 'native':
        _fields(request, {'action', 'args'})
        if endpoint is None:
            raise ValueError('native bridge requires an explicit startup endpoint')
        adapter = LegacyCdpAdapter(endpoint, allow_live_control=allow_live_control, timeout_s=timeout_s)
        try:
            return asdict(adapter.execute(request['action'], request['args']))
        finally:
            adapter.close()
    if operation not in ('macro-prepare', 'macro-complete'):
        raise ValueError('unsupported bridge operation')
    required = {'action', 'argv'} if operation == 'macro-prepare' else {'action', 'argv', 'port_open', 'reply'}
    _fields(request, required)
    macro = prepare_macro(request['action'], request['argv'], allow_live_control=allow_live_control)
    if operation == 'macro-prepare':
        return {'port': macro.port, 'native_argv': native_arguments(macro),
                'query': {'kind': 'port', 'port': macro.port, 'timeout_ms': 120}}
    if type(request['port_open']) is not bool:
        raise ValueError('port_open must be boolean')
    if not request['port_open']:
        if request['reply'] is not None:
            raise ValueError('closed-port completion must not carry a helper reply')
        output = port_closed_output(macro)
        passthrough, raw = False, None
    else:
        result, raw, present = _helper_reply(request['reply'])
        output = macro_output(macro, result, helper_present=present)
        passthrough = macro.action not in ('cdp-deep-find', 'cdp-prosemirror-insert')
    return {**asdict(output), 'raw_passthrough': passthrough, 'raw': raw}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation', choices=('native', 'desktop-native', 'native-prepare', 'macro-prepare', 'macro-complete',
        'native-macro-prepare','native-macro-complete','history-storage','coordinates'), required=True)
    parser.add_argument('--endpoint')
    parser.add_argument('--allow-live-control', action='store_true')
    parser.add_argument('--timeout-s', type=float, default=8)
    parser.add_argument('--cache-directory')
    parser.add_argument('--audit-directory')
    parser.add_argument('--history-file')
    parser.add_argument('--history-maximum', type=int)
    parser.add_argument('--coordinate-culture')
    parser.add_argument('--coordinate-modern', action='store_true')
    options = parser.parse_args(argv)
    try:
        maximum_input=64*1024*1024 if options.operation in ('native-macro-complete', 'history-storage') else MAX_FRAME
        data = sys.stdin.buffer.readline(maximum_input + 1)
        if len(data) > maximum_input:
            raise ValueError('bridge request exceeds its byte limit')
        # Framework Process starts its stdin StreamWriter with AutoFlush=true;
        # Console.InputEncoding may therefore emit a UTF-8 preamble before the
        # host writes the bounded bytes. Accept one prefix, never relaxed JSON.
        request = _json(data.removeprefix(b'\xef\xbb\xbf'))
        result = handle(options.operation, request, allow_live_control=options.allow_live_control,
                        endpoint=options.endpoint, timeout_s=options.timeout_s,
                        cache_directory=options.cache_directory,audit_directory=options.audit_directory,
                        history_file=options.history_file,history_maximum=options.history_maximum,
                        coordinate_culture=options.coordinate_culture,coordinate_modern=options.coordinate_modern)
        response, exit_code = dict(schema=SCHEMA, status='ok', data=result), 0
    except (ValueError, CdpError, LegacyHostError, OSError, OverflowError) as exc:
        response, exit_code = dict(schema=SCHEMA, status='error', error=dict(
            code=getattr(exc, 'code', 'invalid_arguments'), message=str(exc)[:2048])), 1
    encoded = json.dumps(response, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii') + b'\n'
    maximum = 64*1024*1024 if options.operation in ('native-macro-complete', 'history-storage') else 32 * 1024 * 1024 if options.operation == 'desktop-native' else MAX_RESPONSE
    if len(encoded) > maximum:
        encoded = b'{"schema":"cucp.legacy-cdp-bridge/v1","status":"error","error":{"code":"response_limit","message":"Bridge response exceeds its byte limit"}}\n'
        exit_code = 1
    sys.stdout.buffer.write(encoded)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
