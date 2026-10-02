"""Bounded legacy transport on the same numeric-loopback boundary as modern CDP.

Only the framing implementation is shared. Legacy envelopes and request authority
are separate; this module does not broaden CdpAdapter's public protocol surface.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import threading
import time

from .cdp import CdpError, _WebSocket, _Wire, _http_json, _url


@dataclass(frozen=True)
class _Configuration:
    origin: object
    allow_live_control: bool
    timeout_s: float


class LegacyCdpTransport:
    def __init__(self, endpoint: str, *, allow_live_control=False, timeout_s=8):
        origin, path = _url(endpoint, 'http')
        if path != '/': raise CdpError('invalid_endpoint', 'Startup endpoint must be an origin')
        if type(allow_live_control) is not bool: raise ValueError('live authority must be boolean')
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not .05 <= timeout_s <= 30:
            raise ValueError('timeout_s must be finite and between .05 and 30')
        self._configuration = _Configuration(origin, allow_live_control, float(timeout_s))
        self._cancelled = threading.Event()
        self._wire_lock = threading.Lock()
        self._wires = set()
        self._epoch = 0
        self._operation_epoch = None
        self.mutation_started = False
        self.lock = threading.Lock()

    @property
    def origin(self): return self._configuration.origin
    @property
    def endpoint(self): return self.origin.url
    @property
    def allow_live_control(self): return self._configuration.allow_live_control
    @property
    def timeout_s(self): return self._configuration.timeout_s

    def _check_open(self):
        if self._cancelled.is_set(): raise CdpError('adapter_closed', 'Adapter is closed', status='blocked')

    def _check_operation(self):
        self._check_open()
        if self._operation_epoch is not None and self._operation_epoch != self._epoch:
            raise CdpError('stale_operation', 'Another control route invalidated CDP', status='blocked')

    def _register_wire(self, wire):
        with self._wire_lock:
            self._check_open()
            self._wires.add(wire)

    def _unregister_wire(self, wire):
        with self._wire_lock: self._wires.discard(wire)

    def invalidate_snapshot(self):
        with self._wire_lock: self._epoch += 1

    def close(self):
        self._cancelled.set()
        with self._wire_lock: active = tuple(self._wires)
        for wire in active: wire.cancel()

    def port_open(self, deadline):
        wire = None
        try:
            self._check_operation()
            wire = _Wire(self.origin, min(deadline, time.monotonic() + .12), self)
            return True
        except (OSError, CdpError):
            self._check_operation()
            return False
        finally:
            if wire: wire.close()

    def http_json(self, path, deadline):
        if path not in ('/json/version', '/json/list'): raise ValueError('unsupported discovery path')
        return _http_json(self.origin, path, deadline, self)

    def page_path(self, page):
        target_id = page.get('id')
        if not isinstance(target_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,256}', target_id):
            raise CdpError('invalid_discovery', 'Invalid page target id')
        origin, path = _url(page.get('ws_url'), 'ws')
        if origin != self.origin or path != '/devtools/page/' + target_id:
            raise CdpError('endpoint_escape', 'WebSocket must match the exact configured loopback origin and page id', status='blocked')
        if page.get('type') not in ('page', 'webview'):
            raise CdpError('unsupported_target_type', 'Only page/webview targets may be controlled', status='blocked')
        return path

    def call(self, page, method, params, deadline, *, live=False, audited_read=False):
        """Preserve the full correlated CDP response, including protocol errors."""
        self._check_operation()
        if live:
            if not self.allow_live_control:
                raise CdpError('live_control_required', 'Live control must be enabled at startup', status='blocked')
            if method not in ('Runtime.evaluate', 'Input.insertText', 'DOM.enable', 'Runtime.enable', 'Input.enable'):
                raise CdpError('unsupported_method', 'Unsupported legacy live operation', status='blocked')
        elif not (audited_read and method == 'Runtime.evaluate' and params.get('throwOnSideEffect') is True
                  and params.get('awaitPromise') is False):
            raise CdpError('unsupported_method', 'Only fixed audited read evaluation is permitted', status='blocked')
        ws = _WebSocket(self.origin, self.page_path(page), deadline, self)
        try:
            self._check_operation()
            if live: self.mutation_started = True
            ws.send_frame(json.dumps(dict(id=1, method=method, params=params), ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode('utf-8'))
            for _ in range(100):
                response = ws.message()
                if not isinstance(response, dict): raise CdpError('invalid_protocol_response', 'CDP response must be an object')
                if type(response.get('id')) is not int or response['id'] != 1: continue
                if 'error' not in response and not isinstance(response.get('result'), dict):
                    raise CdpError('invalid_protocol_response', 'CDP result must be an object')
                self._check_operation()
                return response
            raise CdpError('response_limit', 'Too many unrelated CDP messages')
        finally:
            ws.close()
