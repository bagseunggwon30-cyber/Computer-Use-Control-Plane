"""Optional, explicitly configured numeric-loopback CDP adapter.

Read-only discovery/DOM inspection never evaluates page JavaScript. Mutation is
an immutable startup capability and consumes observation references before send.
This module never starts a browser, enables debugging, scans ports, or uses models.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
import re
import secrets
import socket
import struct
import threading
import time
import unicodedata
from typing import Any
from urllib.parse import urlsplit

MAX_BODY = 4 * 1024 * 1024
MAX_HEADER = 16 * 1024
MAX_NODES = 2000
MAX_TEXT = 32768
_SOURCE_ONLY_TAGS = frozenset({"SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"})
_READ_METHODS = frozenset({"DOM.getDocument", "DOM.describeNode", "DOM.querySelectorAll", "DOM.resolveNode"})
_WRITE_METHODS = frozenset({"Runtime.evaluate", "Runtime.callFunctionOn", "Input.insertText", "Input.dispatchKeyEvent"})
_MUTATIONS = frozenset({"cdp-click", "cdp-smart-click", "cdp-type", "cdp-smart-type", "cdp-prosemirror-insert", "cdp-eval"})
_COMMANDS = _MUTATIONS | {"cdp-detect", "cdp-observe", "cdp-query", "cdp-smart-find", "cdp-smart-type-find", "cdp-deep-find"}


class CdpError(ValueError):
    def __init__(self, code: str, message: str, *, status: str = "error", mutation_may_have_occurred: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.mutation_may_have_occurred = mutation_may_have_occurred


def _fail(code: str, message: str, *, blocked=False):
    raise CdpError(code, message, status="blocked" if blocked else "error")


def _text(value: Any, name: str, maximum: int = MAX_TEXT, *, empty=False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        _fail("invalid_argument", f"{name} must be a {'possibly empty ' if empty else 'nonempty '}string of at most {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail("invalid_argument", f"{name} contains invalid Unicode")
    return value


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        _fail("invalid_argument", f"{name} must be an integer in {low}..{high}")
    return value


def _bool(value, name):
    if type(value) is not bool:
        _fail("invalid_argument", f"{name} must be a boolean")
    return value


def _duration(value, name, low, high):
    if type(value) not in (int, float):
        _fail("invalid_argument", f"{name} is outside {low}..{high}")
    try:
        valid = math.isfinite(value) and low <= value <= high
    except OverflowError:
        valid = False
    if not valid:
        _fail("invalid_argument", f"{name} is outside {low}..{high}")
    return float(value)


@dataclass(frozen=True)
class _Origin:
    host: str
    port: int

    @property
    def authority(self):
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"

    @property
    def url(self):
        return "http://" + self.authority


def _url(value: str, scheme: str) -> tuple[_Origin, str]:
    _text(value, "endpoint", 2048)
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value or "%" in value:
        _fail("invalid_endpoint", "Endpoint must not contain whitespace, escapes, or zone identifiers")
    try:
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        _fail("invalid_endpoint", "An explicit numeric loopback host and port are required")
    if parsed.scheme != scheme or not address.is_loopback or getattr(address, "ipv4_mapped", None) is not None or port is None or not 1 <= port <= 65535:
        _fail("invalid_endpoint", f"Only {scheme} with an explicit numeric loopback host and port is supported")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        _fail("invalid_endpoint", "Credentials, query strings, and fragments are not accepted")
    return _Origin(str(address), port), parsed.path or "/"


def _json(data: bytes):
    def no_constant(value):
        raise ValueError("non-finite JSON")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8"), parse_constant=no_constant, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CdpError("invalid_protocol_json", "CDP returned invalid or excessively nested JSON") from exc


class _Wire:
    """Small bounded HTTP/WebSocket byte transport with one absolute deadline."""
    def __init__(self, origin: _Origin, deadline: float, control=None):
        self.control = control
        self.deadline = deadline
        self.buffer = bytearray()
        self.socket = None
        try:
            family = socket.AF_INET6 if ":" in origin.host else socket.AF_INET
            self.socket = socket.socket(family, socket.SOCK_STREAM)
            if self.control is not None:
                self.control._register_wire(self)
            connection = self._socket()
            connection.settimeout(self.remaining())
            connection.connect((origin.host, origin.port))
        except (OSError, CdpError):
            self.close()
            raise

    def remaining(self):
        if self.control is not None:
            self.control._check_operation()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            _fail("cdp_timeout", "CDP operation exceeded its deadline")
        return remaining

    def _socket(self):
        self.remaining()
        connection = self.socket
        if connection is None:
            _fail("connection_closed", "CDP connection was closed")
        return connection

    def send(self, data: bytes):
        connection = self._socket()
        connection.settimeout(self.remaining())
        # Recheck immediately before every HTTP request/WebSocket frame send.
        if self.control is not None:
            self.control._check_operation()
        connection.sendall(data)

    def recv(self):
        connection = self._socket()
        connection.settimeout(self.remaining())
        return connection.recv(65536)

    def take(self, count: int) -> bytes:
        self.remaining()
        while len(self.buffer) < count:
            more = self.recv()
            if not more:
                _fail("connection_closed", "CDP connection closed before a complete response")
            self.buffer.extend(more)
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def line(self, limit=MAX_HEADER):
        self.remaining()
        while True:
            end = self.buffer.find(b"\r\n")
            if end >= 0:
                if end > limit:
                    _fail("response_limit", "Protocol line exceeds limit")
                result = bytes(self.buffer[:end])
                del self.buffer[:end + 2]
                return result
            if len(self.buffer) > limit:
                _fail("response_limit", "Protocol line exceeds limit")
            more = self.recv()
            if not more:
                _fail("connection_closed", "Incomplete HTTP response header")
            self.buffer.extend(more)

    def headers(self):
        status = self.line(512)
        if not re.fullmatch(rb"HTTP/1\.[01] [0-9]{3}(?: [^\r\n]*)?", status):
            _fail("invalid_http", "Invalid HTTP status line")
        fields = {}
        count = len(status)
        for _ in range(100):
            line = self.line()
            count += len(line) + 2
            if count > MAX_HEADER:
                _fail("response_limit", "HTTP header exceeds limit")
            if not line:
                return int(status.split(b" ")[1]), fields
            if b":" not in line or line[:1] in (b" ", b"\t"):
                _fail("invalid_http", "Invalid HTTP header")
            key, value = line.split(b":", 1)
            if not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
                _fail("invalid_http", "Invalid HTTP field name")
            key = key.decode("ascii").lower()
            value = value.strip().decode("latin-1")
            if key in fields:
                _fail("invalid_http", "Duplicate HTTP response field")
            fields[key] = value
        _fail("response_limit", "Too many HTTP headers")

    def cancel(self):
        # shutdown wakes another thread blocked in recv; no execution-lock wait.
        connection = self.socket
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.close()

    def close(self):
        connection = self.socket
        self.socket = None
        if connection is not None:
            connection.close()
        if self.control is not None:
            self.control._unregister_wire(self)


def _http_json(origin: _Origin, path: str, deadline: float, control=None):
    wire = _Wire(origin, deadline, control)
    try:
        wire.send(f"GET {path} HTTP/1.1\r\nHost: {origin.authority}\r\nAccept: application/json\r\nConnection: close\r\n\r\n".encode("ascii"))
        status, headers = wire.headers()
        if status != 200:
            _fail("http_redirect_rejected" if 300 <= status < 400 else "http_error", f"CDP discovery returned HTTP {status}; redirects are never followed")
        if headers.get("content-encoding", "identity").lower() != "identity":
            _fail("unsupported_encoding", "Compressed HTTP discovery responses are not accepted")
        length = headers.get("content-length")
        transfer = headers.get("transfer-encoding")
        if length is not None and transfer is not None:
            _fail("invalid_http", "Ambiguous HTTP message length")
        body = bytearray()
        if transfer is not None:
            if transfer.lower() != "chunked":
                _fail("invalid_http", "Unsupported transfer encoding")
            for _ in range(10000):
                line = wire.line(128)
                if not re.fullmatch(rb"[0-9A-Fa-f]{1,8}", line):
                    _fail("invalid_http", "Invalid chunked encoding")
                size = int(line, 16)
                if size == 0:
                    if wire.line(MAX_HEADER):
                        _fail("invalid_http", "HTTP trailers are not supported")
                    break
                if len(body) + size > MAX_BODY:
                    _fail("response_limit", "HTTP response exceeds byte budget")
                body.extend(wire.take(size))
                if wire.take(2) != b"\r\n":
                    _fail("invalid_http", "Invalid HTTP chunk delimiter")
            else:
                _fail("response_limit", "Too many HTTP chunks")
        elif length is not None:
            if not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > MAX_BODY:
                _fail("response_limit", "HTTP content length exceeds limit")
            body.extend(wire.take(int(length)))
        else:
            body.extend(wire.buffer)
            wire.buffer.clear()
            while True:
                if len(body) > MAX_BODY:
                    _fail("response_limit", "HTTP response exceeds byte budget")
                more = wire.recv()
                if not more:
                    break
                body.extend(more)
        if len(body) > MAX_BODY:
            _fail("response_limit", "HTTP response exceeds byte budget")
        return _json(bytes(body))
    finally:
        wire.close()


class _WebSocket:
    def __init__(self, origin: _Origin, path: str, deadline: float, control=None):
        self.wire = _Wire(origin, deadline, control)
        self.sequence = 0
        self.upgraded = False
        self.frames = self.bytes_read = 0
        try:
            key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
            request = (f"GET {path} HTTP/1.1\r\nHost: {origin.authority}\r\nUpgrade: websocket\r\n"
                       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
            self.wire.send(request.encode("ascii"))
            status, headers = self.wire.headers()
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
            if status != 101 or headers.get("upgrade", "").lower() != "websocket" or "upgrade" not in {x.strip().lower() for x in headers.get("connection", "").split(",")} or headers.get("sec-websocket-accept") != accept:
                _fail("invalid_websocket_handshake", "WebSocket upgrade failed; redirects are never followed")
            if "sec-websocket-extensions" in headers or "sec-websocket-protocol" in headers:
                _fail("invalid_websocket_handshake", "Unrequested WebSocket extensions/subprotocols")
            self.upgraded = True
        except BaseException:
            self.close()
            raise

    def send_frame(self, payload: bytes, opcode=1):
        if len(payload) > MAX_BODY:
            _fail("request_limit", "WebSocket request exceeds byte limit")
        mask = secrets.token_bytes(4)
        n = len(payload)
        header = bytes([0x80 | opcode, 0x80 | n]) if n < 126 else bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
        self.wire.send(header + mask + masked)

    def message(self):
        result = bytearray()
        started = False
        while True:
            self.frames += 1
            if self.frames > 2048:
                _fail("response_limit", "WebSocket frame budget exceeded")
            first, second = self.wire.take(2)
            fin, opcode = bool(first & 128), first & 15
            if first & 112 or second & 128:
                _fail("invalid_websocket_frame", "Reserved/compressed or masked server frame rejected")
            length = second & 127
            if length == 126:
                length = struct.unpack(">H", self.wire.take(2))[0]
                if length < 126:
                    _fail("invalid_websocket_frame", "Noncanonical WebSocket length")
            elif length == 127:
                length = struct.unpack(">Q", self.wire.take(8))[0]
                if length < 65536 or length >> 63:
                    _fail("invalid_websocket_frame", "Invalid WebSocket extended length")
            if opcode >= 8 and (not fin or length > 125):
                _fail("invalid_websocket_frame", "Invalid WebSocket control frame")
            if length > MAX_BODY or len(result) + length > MAX_BODY or self.bytes_read + length > MAX_BODY * 4:
                _fail("response_limit", "WebSocket response exceeds byte budget")
            payload = self.wire.take(length)
            self.bytes_read += length
            if opcode == 8:
                _fail("connection_closed", "CDP WebSocket closed")
            if opcode == 9:
                self.send_frame(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1) or (opcode == 0 and not started) or (opcode == 1 and started):
                _fail("invalid_websocket_frame", "Unsupported or invalid fragmented WebSocket message")
            started = True
            result.extend(payload)
            if fin:
                return _json(bytes(result))

    def call(self, method, params):
        self.sequence += 1
        message_id = self.sequence
        self.send_frame(json.dumps({"id": message_id, "method": method, "params": params}, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
        for _ in range(100):
            response = self.message()
            if not isinstance(response, dict):
                _fail("invalid_protocol_response", "CDP response must be an object")
            if type(response.get("id")) is not int or response["id"] != message_id:
                continue
            if "error" in response:
                _fail("cdp_protocol_error", "CDP command was rejected: " + str(response["error"])[:512])
            if not isinstance(response.get("result"), dict):
                _fail("invalid_protocol_response", "CDP command result must be an object")
            return response["result"]
        _fail("response_limit", "Too many uncorrelated CDP responses/events")

    def close(self):
        if self.upgraded and self.wire.socket is not None:
            try:
                self.send_frame(struct.pack(">H", 1000), 8)
            except (OSError, CdpError):
                pass
        self.upgraded = False
        self.wire.close()


def _attributes(node):
    raw = node.get("attributes", [])
    if not isinstance(raw, list) or len(raw) % 2 or len(raw) > 1024 or any(not isinstance(x, str) or len(x) > MAX_TEXT for x in raw):
        _fail("invalid_dom", "Invalid DOM attributes")
    return dict(zip(raw[::2], raw[1::2]))


def _children(node):
    if not isinstance(node, dict):
        _fail("invalid_dom", "DOM node must be an object")
    children = node.get("children", [])
    shadows = node.get("shadowRoots", [])
    if not isinstance(children, list) or not isinstance(shadows, list) or len(children) + len(shadows) > MAX_NODES:
        _fail("invalid_dom", "Invalid DOM children")
    result = [(x, "child") for x in children] + [(x, "shadow") for x in shadows]
    if "contentDocument" in node:
        result.append((node["contentDocument"], "frame"))
    if any(not isinstance(child, dict) for child, _ in result):
        _fail("invalid_dom", "DOM children must be objects")
    return result


def _fingerprint(node):
    """Semantic subtree identity, excluding connection-specific frontend nodeIds."""
    count = [0]
    def copy(value, depth=0):
        count[0] += 1
        if not isinstance(value, dict) or count[0] > MAX_NODES or depth > 40:
            _fail("dom_limit", "DOM subtree exceeds validation budget")
        return [value.get("backendNodeId"), value.get("nodeType"), value.get("nodeName"),
                value.get("nodeValue", ""), sorted(_attributes(value).items()), value.get("frameId"),
                [(kind, copy(child, depth + 1)) for child, kind in _children(value)]]
    return hashlib.sha256(json.dumps(copy(node), ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _subtree_incomplete(node):
    stack = [node]
    visited = 0
    while stack:
        item = stack.pop()
        visited += 1
        if visited > MAX_NODES:
            return True
        count = item.get("childNodeCount", 0)
        if type(count) is not int or count < 0:
            _fail("invalid_dom", "Invalid DOM child count")
        if count > len(item.get("children", [])):
            return True
        stack.extend(child for child, _ in _children(item))
    return False


def _normalize(value):
    value = unicodedata.normalize("NFKC", value).lower()
    return " ".join("".join(c if unicodedata.category(c)[0] in ("L", "N") or c.isspace() else " " for c in value).split())


def _score(needle, hay):
    hay = _normalize(hay)
    if not hay:
        return 0
    if hay == needle:
        return 100
    if hay.startswith(needle):
        return 88
    if needle in hay:
        return 62 + math.floor(len(needle) / len(hay) * 25)
    if len(needle) >= 2 and needle[:3] in hay:
        return 25
    return 0


def _selector_hints(attrs, tag):
    hints = []
    def quote(value):
        # CSS escaped strings; hints are data only, never evaluated by this module.
        return '"' + ''.join(f"\\{ord(c):x} " if c in '"\\\n\r\f' else c for c in value) + '"'
    for attr, score in (("id", 98), ("data-testid", 96), ("data-test", 96), ("data-cy", 96), ("data-qa", 96), ("aria-label", 90), ("name", 84), ("placeholder", 82), ("role", 62)):
        if attrs.get(attr):
            hints.append({"selector": f"[{attr}={quote(attrs[attr])}]", "score": score, "signal": attr})
    hints.append({"selector": tag, "score": 35, "signal": "tag_fallback"})
    return hints[:8]


# Fixed page functions are only dispatched in startup-authorized live mode.
# Strings/text are CDP arguments; no user content is interpolated into source.
_ACTION_FUNCTION = r'''function(op, text, clear, enter) {
  const el = this;
  if (!el || !el.isConnected || el.nodeType !== 1) return {ok:false,reason:'element_detached'};
  const win = el.ownerDocument.defaultView;
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute('type') || 'text').toLowerCase();
  if (tag === 'input' && /^(password|file|hidden)$/.test(type)) return {ok:false,reason:'sensitive_input_blocked'};
  if (el.disabled || el.getAttribute('aria-disabled') === 'true') return {ok:false,reason:'element_disabled'};
  const style = win.getComputedStyle(el), rect = el.getBoundingClientRect();
  if (!rect.width || !rect.height || style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) === 0) return {ok:false,reason:'element_not_visible'};
  if (op === 'focused') return {ok:el.getRootNode().activeElement === el,reason:'focus_mismatch'};
  if (op === 'click') { el.click(); return {ok:true,dispatched:true}; }
  if (op === 'prosemirror') {
    if (!el.isContentEditable) return {ok:false,reason:'contenteditable_required'};
    el.focus();
    if (el.getRootNode().activeElement !== el) return {ok:false,reason:'focus_mismatch'};
    const range = el.ownerDocument.createRange(); range.selectNodeContents(el);
    if (!clear) range.collapse(false);
    const selection = win.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    return {ok:true,focused:true};
  }
  if (op !== 'type' || !['input','textarea'].includes(tag) || /^(button|submit|reset|checkbox|radio|range|color|image)$/.test(type)) return {ok:false,reason:'native_text_field_required_use_prosemirror_for_contenteditable'};
  if (el.readOnly) return {ok:false,reason:'element_readonly'};
  el.focus();
  if (el.getRootNode().activeElement !== el) return {ok:false,reason:'focus_mismatch'};
  const proto = tag === 'textarea' ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, (clear ? '' : el.value) + text);
  el.dispatchEvent(new win.Event('input', {bubbles:true}));
  el.dispatchEvent(new win.Event('change', {bubbles:true}));
  if (enter) for (const name of ['keydown','keypress','keyup']) el.dispatchEvent(new win.KeyboardEvent(name, {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
  return {ok:true,dispatched:true,text_length:text.length,pressed_enter:enter};
}'''


@dataclass(frozen=True)
class _Config:
    origin: _Origin
    allow_live_control: bool
    timeout_s: float
    snapshot_ttl_s: float


class CdpAdapter:
    def __init__(self, endpoint: str, *, allow_live_control=False, timeout_s=5.0, snapshot_ttl_s=15.0):
        origin, path = _url(endpoint, "http")
        if path != "/":
            _fail("invalid_endpoint", "Startup endpoint must be an HTTP origin with no path")
        self._config = _Config(origin, _bool(allow_live_control, "allow_live_control"),
                               _duration(timeout_s, "timeout_s", .05, 30),
                               _duration(snapshot_ttl_s, "snapshot_ttl_s", .05, 60))
        self._snapshot = None
        self._lock = threading.Lock()
        self._mutation_started = False
        self._cancelled = threading.Event()
        self._wire_lock = threading.Lock()
        self._wires: set[_Wire] = set()
        self._snapshot_epoch = 0
        self._operation_epoch = None

    @property
    def allow_live_control(self):
        return self._config.allow_live_control

    @property
    def endpoint(self):
        return self._config.origin.url

    def _check_open(self):
        if self._cancelled.is_set():
            _fail("adapter_closed", "CDP adapter was closed or cancelled", blocked=True)

    def _check_operation(self):
        self._check_open()
        if self._operation_epoch is not None and self._operation_epoch != self._snapshot_epoch:
            _fail("stale_snapshot", "CDP observation was invalidated by another control route", blocked=True)

    def invalidate_snapshot(self):
        """Nonterminal cross-route invalidation; an active preflight cannot act later."""
        with self._wire_lock:
            self._snapshot_epoch += 1
            self._snapshot = None

    def _register_wire(self, wire):
        with self._wire_lock:
            self._check_open()
            self._wires.add(wire)

    def _unregister_wire(self, wire):
        with self._wire_lock:
            self._wires.discard(wire)

    def close(self):
        # Terminal and nonblocking with respect to execute(). Set the signal
        # first; registration/send checks cannot start a later action phase.
        self._cancelled.set()
        self._snapshot = None
        with self._wire_lock:
            active = tuple(self._wires)
        for wire in active:
            wire.cancel()

    def _call(self, ws, method, params):
        self._check_operation()
        if method not in _READ_METHODS:
            if method not in _WRITE_METHODS:
                _fail("unsupported_method", "This adapter does not expose arbitrary CDP methods", blocked=True)
            if not self.allow_live_control:
                _fail("live_control_required", "Live CDP control must be enabled at startup", blocked=True)
            self._mutation_started = True  # Before send: a transport failure may be ambiguous.
        result = ws.call(method, params)
        self._check_operation()  # Cancellation/invalidation during preflight stops later phases.
        return result

    def _discover(self, deadline):
        version = _http_json(self._config.origin, "/json/version", deadline, self)
        pages = _http_json(self._config.origin, "/json/list", deadline, self)
        if not isinstance(version, dict) or not isinstance(pages, list) or len(pages) > 256:
            _fail("invalid_discovery", "CDP discovery metadata is malformed or exceeds 256 targets")
        targets = []
        ids = set()
        for page in pages:
            if not isinstance(page, dict):
                _fail("invalid_discovery", "Target metadata must be an object")
            if page.get("type") not in ("page", "webview"):
                continue
            target_id = _text(page.get("id"), "target id", 256)
            if not re.fullmatch(r"[A-Za-z0-9._-]+", target_id) or target_id in ids:
                _fail("invalid_discovery", "Invalid or duplicate target id")
            ids.add(target_id)
            origin, path = _url(page.get("webSocketDebuggerUrl"), "ws")
            if origin != self._config.origin or path != "/devtools/page/" + target_id:
                _fail("endpoint_escape", "Target WebSocket must stay on the exact configured loopback origin and page id", blocked=True)
            targets.append({"id": target_id, "title": _text(page.get("title", ""), "title", 4096, empty=True),
                            "url": _text(page.get("url", ""), "page URL", 8192, empty=True), "type": page["type"], "ws_path": path})
        return {"status": "ok", "endpoint": self.endpoint, "targets": targets, "pages": targets,
                "browser": version.get("Browser"), "protocol_version": version.get("Protocol-Version"),
                "allow_live_control": self.allow_live_control, "automatic_enable": False}

    def _target(self, target_id, deadline):
        _text(target_id, "target_id", 256)
        targets = [p for p in self._discover(deadline)["targets"] if p["id"] == target_id]
        if len(targets) != 1:
            _fail("target_not_found", "The exact requested CDP target is unavailable", blocked=True)
        return targets[0]

    def _snapshot_required(self, snapshot_id):
        self._check_open()
        snapshot = self._snapshot
        if snapshot is None or snapshot_id != snapshot["id"] or time.monotonic() - snapshot["created"] > self._config.snapshot_ttl_s:
            _fail("stale_snapshot", "Observe this target again before querying or acting", blocked=True)
        return snapshot

    def _fresh(self, snapshot, deadline):
        target = self._target(snapshot["target"]["id"], deadline)
        if any(target[key] != snapshot["target"][key] for key in ("id", "url", "ws_path", "type")):
            _fail("target_changed", "Observed target navigated or changed identity", blocked=True)
        ws = _WebSocket(self._config.origin, target["ws_path"], deadline, self)
        try:
            root = self._call(ws, "DOM.getDocument", {"depth": 0, "pierce": False}).get("root")
            if not isinstance(root, dict) or type(root.get("nodeId")) is not int or root["nodeId"] <= 0 or type(root.get("backendNodeId")) is not int or root.get("backendNodeId") != snapshot["document_id"] or root.get("documentURL", "") != snapshot["document_url"]:
                _fail("document_changed", "Observed DOM document changed", blocked=True)
            return ws, root
        except BaseException:
            ws.close()
            raise

    def _observe(self, args, deadline):
        target = self._target(args["target_id"], deadline)
        max_depth = _int(args.get("max_depth", 8), "max_depth", 1, 24)
        max_nodes = _int(args.get("max_nodes", 1000), "max_nodes", 1, MAX_NODES)
        ws = _WebSocket(self._config.origin, target["ws_path"], deadline, self)
        self._snapshot = None
        try:
            root = self._call(ws, "DOM.getDocument", {"depth": max_depth, "pierce": True}).get("root")
        finally:
            ws.close()
        if not isinstance(root, dict) or type(root.get("backendNodeId")) is not int or root["backendNodeId"] <= 0 or not isinstance(root.get("documentURL", ""), str):
            _fail("invalid_dom", "DOM response has no document identity")
        entries, by_backend = {}, {}
        nodes = []
        stack = [(root, 0)]
        visited = 0
        incomplete = False
        shadow_count = frame_count = inaccessible_frames = 0
        while stack:
            self._check_open()
            node, depth = stack.pop()
            visited += 1
            if visited > max_nodes:
                incomplete = True
                break
            if not isinstance(node, dict) or depth > 40:
                _fail("invalid_dom", "DOM tree is malformed or exceeds depth budget")
            name = node.get("nodeName", "")
            if not isinstance(name, str):
                _fail("invalid_dom", "DOM node name must be a string")
            # Script/style/template source is not observation text or an action
            # target. Skip the complete public subtree, including inert elements.
            # Ancestor fingerprints may retain it internally, never in reports.
            if name.upper() in _SOURCE_ONLY_TAGS:
                continue
            attrs = _attributes(node)
            children = _children(node)
            child_count = node.get("childNodeCount", 0)
            if type(child_count) is not int or child_count < 0 or not isinstance(node.get("nodeName", ""), str) or not isinstance(node.get("nodeValue", ""), str):
                _fail("invalid_dom", "DOM node has invalid text or child count")
            if child_count > len(node.get("children", [])):
                incomplete = True
            shadow_count += sum(kind == "shadow" for _, kind in children)
            frame_count += int(node.get("nodeName", "").upper() in ("IFRAME", "FRAME"))
            inaccessible_frames += int(node.get("nodeName", "").upper() in ("IFRAME", "FRAME") and "contentDocument" not in node)
            # A textarea's children encode its default field value. Keep the
            # control/reference, but do not expose its value subtree as nodes.
            if name.upper() != "TEXTAREA":
                stack.extend((child, depth + 1) for child, _ in reversed(children))
            if node.get("nodeType") != 1:
                continue
            backend = node.get("backendNodeId")
            if type(backend) is not int or backend <= 0 or backend in by_backend:
                _fail("invalid_dom", "DOM node has an invalid or duplicate backend identity")
            reference = "cdp-el-" + secrets.token_hex(12)
            tag = str(node.get("nodeName", "")).lower()
            raw_text = []
            todo = [node]
            traversed = 0
            while todo and traversed < MAX_NODES and sum(map(len, raw_text)) < 4096:
                part = todo.pop()
                traversed += 1
                name = part.get("nodeName", "")
                if not isinstance(name, str):
                    _fail("invalid_dom", "DOM node name must be a string")
                if name.upper() in _SOURCE_ONLY_TAGS or name.upper() == "TEXTAREA":
                    continue
                if part.get("nodeType") == 3:
                    raw_text.append(str(part.get("nodeValue", ""))[:4096])
                todo.extend(child for child, kind in reversed(_children(part)) if kind == "child")
            text_content = " ".join(raw_text)[:4096]
            public_attrs = {k: v for k, v in attrs.items() if k in {"id", "name", "type", "role", "aria-label", "aria-disabled", "placeholder", "title", "alt", "for", "contenteditable", "disabled", "readonly", "data-testid", "data-test", "data-cy", "data-qa"}}
            item = {"element_ref": reference, "tag_name": tag, "attributes": public_attrs,
                    "text": text_content, "visibility": "unverified", "selector_candidates": _selector_hints(public_attrs, tag)}
            entries[reference] = {"backend": backend, "raw": node, "depth": depth,
                                  "fingerprint": _fingerprint(node), "subtree_incomplete": _subtree_incomplete(node), "public": item}
            by_backend[backend] = reference
            nodes.append(item)
        snapshot_id = "cdp-obs-" + secrets.token_hex(16)
        self._snapshot = {"id": snapshot_id, "created": time.monotonic(), "target": target,
                          "document_id": root["backendNodeId"], "document_url": root.get("documentURL", ""),
                          "entries": entries, "by_backend": by_backend, "max_depth": max_depth,
                          "incomplete": incomplete or inaccessible_frames > 0}
        return {"status": "partial" if self._snapshot["incomplete"] else "ok", "snapshot_id": snapshot_id,
                "target_id": target["id"], "target": target, "nodes": nodes, "node_count": len(nodes),
                "truncated": incomplete, "traversal": {"shadow_roots_seen": shadow_count, "iframes_seen": frame_count,
                "inaccessible_frames": inaccessible_frames, "visited_nodes": visited}, "automatic_action": False}

    def _query(self, args, deadline):
        snapshot = self._snapshot_required(args["snapshot_id"])
        selector = _text(args["selector"], "selector", 2048)
        limit = _int(args.get("limit", 50), "limit", 1, 100)
        ws, root = self._fresh(snapshot, deadline)
        try:
            ids = self._call(ws, "DOM.querySelectorAll", {"nodeId": root["nodeId"], "selector": selector}).get("nodeIds")
            if not isinstance(ids, list) or len(ids) > MAX_NODES or any(type(i) is not int or i <= 0 for i in ids):
                _fail("dom_limit", "Selector returned too many nodes or invalid result")
            matches, unobserved = [], 0
            for node_id in ids[:100]:
                node = self._call(ws, "DOM.describeNode", {"nodeId": node_id, "depth": 0}).get("node", {})
                if not isinstance(node, dict) or type(node.get("backendNodeId")) is not int:
                    _fail("invalid_dom", "Selector node response has no backend identity")
                reference = snapshot["by_backend"].get(node.get("backendNodeId"))
                if reference is None:
                    unobserved += 1
                else:
                    matches.append(snapshot["entries"][reference]["public"])
            partial = snapshot["incomplete"] or len(ids) > 100 or unobserved > 0 or len(ids) > 1
            return {"status": "partial" if partial else "ok" if matches else "not_found", "snapshot_id": snapshot["id"],
                    "target_id": snapshot["target"]["id"], "candidates": matches[:limit], "candidate_count": len(ids),
                    "ambiguous": len(ids) > 1, "unobserved_count": unobserved, "truncated": len(matches) > limit or len(ids) > 100,
                    "selector": selector, "automatic_action": False}
        finally:
            ws.close()

    def _find(self, args, deadline, command):
        snapshot = self._snapshot_required(args["snapshot_id"])
        text = _text(args["text"], "text", 1024)
        needle = _normalize(text)
        if not needle:
            _fail("invalid_argument", "Search text must contain letters or numbers")
        action = args.get("action", "type" if command == "cdp-smart-type-find" else "click")
        if action not in ("click", "type"):
            _fail("invalid_argument", "action must be click or type")
        limit = _int(args.get("limit", 50), "limit", 1, 100)
        ws, _ = self._fresh(snapshot, deadline)
        ws.close()
        candidates = []
        all_public = [entry["public"] for entry in snapshot["entries"].values()]
        label_by_id = {}
        for item in all_public:
            if item["tag_name"] == "label" and item["attributes"].get("for"):
                label_by_id.setdefault(item["attributes"]["for"], []).append(item["text"])
        for item in all_public:
            self._check_open()
            attrs, tag = item["attributes"], item["tag_name"]
            kind = attrs.get("type", "text").lower()
            typeable = (tag in ("textarea", "input") and kind not in {"password", "file", "hidden", "button", "submit", "reset", "checkbox", "radio", "image", "range", "color"}) or attrs.get("contenteditable") == "true"
            if action == "type" and not typeable:
                continue
            parts = [attrs.get(k, "") for k in ("aria-label", "title", "placeholder", "alt", "name", "id")]
            parts += [item["text"]] + label_by_id.get(attrs.get("id"), [])
            scored = [(_score(needle, part), part) for part in parts]
            score, matched = max(scored, key=lambda p: p[0])
            if not score:
                continue
            role = attrs.get("role", "")
            role_bonus = 40 if action == "type" and typeable else 35 if tag in {"button", "a"} or role in {"button", "link", "menuitem", "tab"} else 20 if tag in {"label", "summary"} else 0
            disabled = "disabled" in attrs or attrs.get("aria-disabled") == "true"
            rank = score + role_bonus - (80 if disabled else 0)
            candidates.append({**item, "score": rank, "match_score": score, "matched_text": matched,
                               "disabled": disabled, "typeable": typeable})
        candidates.sort(key=lambda item: -item["score"])
        ambiguous = len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] < 8
        return {"status": "partial" if snapshot["incomplete"] or ambiguous else "ok" if candidates else "not_found",
                "snapshot_id": snapshot["id"], "target_id": snapshot["target"]["id"], "top": candidates[0] if candidates else None,
                "candidates": candidates[:limit], "candidate_count": len(candidates), "ambiguous": ambiguous,
                "truncated": snapshot["incomplete"] or len(candidates) > limit, "visibility": "unverified", "automatic_action": False}

    def _live(self, command, args, deadline):
        if not self.allow_live_control:
            _fail("live_control_required", "CDP mutation and arbitrary JavaScript require startup live control", blocked=True)
        snapshot = self._snapshot_required(args["snapshot_id"])
        if command == "cdp-eval":
            expression = _text(args["expression"], "expression")
            entry = None
        else:
            reference = _text(args["element_ref"], "element_ref", 128)
            entry = snapshot["entries"].get(reference)
            if entry is None:
                _fail("unknown_element_reference", "Choose an element from this exact snapshot", blocked=True)
            if entry["subtree_incomplete"]:
                _fail("incomplete_element", "Observe this element at greater depth before acting", blocked=True)
            text = _text(args.get("text", ""), "text", 16384, empty=command != "cdp-prosemirror-insert")
            clear = _bool(args.get("clear", False), "clear")
            enter = _bool(args.get("press_enter", False), "press_enter")
            if command in ("cdp-type", "cdp-smart-type") and not text and not clear and not enter:
                _fail("invalid_argument", "Typing requires text, clear, or press_enter")
        ws, _ = self._fresh(snapshot, deadline)
        try:
            if entry is not None:
                depth = max(0, snapshot["max_depth"] - entry["depth"])
                current = self._call(ws, "DOM.describeNode", {"backendNodeId": entry["backend"], "depth": depth, "pierce": True}).get("node")
                if not isinstance(current, dict) or _fingerprint(current) != entry["fingerprint"]:
                    _fail("element_changed", "Observed element attributes or subtree changed; observe again", blocked=True)
                resolved = self._call(ws, "DOM.resolveNode", {"backendNodeId": entry["backend"]}).get("object", {})
                object_id = resolved.get("objectId") if isinstance(resolved, dict) else None
                if not isinstance(object_id, str) or not object_id:
                    _fail("element_unavailable", "DOM element cannot be resolved", blocked=True)
            self._snapshot = None  # Every mutation attempt consumes all references, including ambiguous failures.
            if command == "cdp-eval":
                result = self._call(ws, "Runtime.evaluate", {"expression": expression, "returnByValue": True,
                    "awaitPromise": True, "timeout": max(1, int((deadline - time.monotonic()) * 1000)), "silent": True})
                if result.get("exceptionDetails"):
                    _fail("javascript_exception", "Evaluation raised an exception; its side effects may already have occurred")
                value = result.get("result", {})
                if not isinstance(value, dict):
                    _fail("invalid_protocol_response", "Evaluation returned an invalid remote object")
                return {"status": "ok", "target_id": snapshot["target"]["id"], "result_type": value.get("type"),
                        "result_value": value.get("value"), "dispatched": True, "automatic_retry": False}
            op = "click" if command in ("cdp-click", "cdp-smart-click") else "prosemirror" if command == "cdp-prosemirror-insert" else "type"
            def invoke(operation, value="", clear_value=False, enter_value=False):
                response = self._call(ws, "Runtime.callFunctionOn", {"objectId": object_id, "functionDeclaration": _ACTION_FUNCTION,
                    "arguments": [{"value": v} for v in (operation, value, clear_value, enter_value)], "returnByValue": True, "awaitPromise": False})
                if response.get("exceptionDetails"):
                    _fail("javascript_exception", "Element operation raised an exception; side effects may already have occurred")
                remote = response.get("result")
                result = remote.get("value") if isinstance(remote, dict) else None
                if not isinstance(result, dict) or result.get("ok") is not True:
                    _fail("element_action_blocked", "Element action refused: " + str(result.get("reason") if isinstance(result, dict) else "invalid result"), blocked=True)
                return result
            invoke(op, text, clear, enter if op == "type" else False)
            if op == "prosemirror":
                invoke("focused")
                self._call(ws, "Input.insertText", {"text": text})
                if enter:
                    invoke("focused")
                    self._call(ws, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
                    self._call(ws, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            return {"status": "ok", "target_id": snapshot["target"]["id"], "dispatched": True,
                    "operation": op, "text_length": len(text) if op != "click" else 0, "pressed_enter": enter if op != "click" else False,
                    "verification": "protocol_dispatch_not_task_success", "snapshot_consumed": True, "automatic_retry": False,
                    "next_action": "Observe the exact target again to verify the result"}
        finally:
            ws.close()

    @contextmanager
    def _execution_slot(self, timeout_s):
        deadline = time.monotonic() + timeout_s
        if not self._lock.acquire(timeout=timeout_s):
            self._check_open()
            _fail("cdp_timeout", "CDP deadline expired while waiting for the current operation")
        try:
            self._check_open()
            yield deadline
        finally:
            self._lock.release()

    def execute(self, command: str, args: dict[str, Any] | None = None, *, timeout_s: float | None = None) -> dict[str, Any]:
        if not isinstance(command, str) or command not in _COMMANDS:
            _fail("unsupported_command", "Unknown CDP adapter command")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            _fail("invalid_argument", "args must be an object")
        allowed = {
            "cdp-detect": set(), "cdp-observe": {"target_id", "max_depth", "max_nodes"},
            "cdp-query": {"snapshot_id", "selector", "limit"},
            "cdp-smart-find": {"snapshot_id", "text", "action", "limit"},
            "cdp-smart-type-find": {"snapshot_id", "text", "limit"},
            "cdp-deep-find": {"snapshot_id", "text", "action", "limit"},
            "cdp-eval": {"snapshot_id", "expression"},
        }.get(command, {"snapshot_id", "element_ref"} if command in {"cdp-click", "cdp-smart-click"} else {"snapshot_id", "element_ref", "text", "clear", "press_enter"})
        required = {"cdp-detect": set(), "cdp-observe": {"target_id"}, "cdp-query": {"snapshot_id", "selector"},
                    "cdp-eval": {"snapshot_id", "expression"}}.get(command, {"snapshot_id", "element_ref"} if command in _MUTATIONS else {"snapshot_id", "text"})
        if set(args) - allowed or required - set(args):
            _fail("invalid_argument", "CDP command has unknown or missing arguments")
        effective_timeout = self._config.timeout_s
        if timeout_s is not None:
            value = _duration(timeout_s, "timeout_s", 0, math.inf)
            if value <= 0:
                _fail("invalid_argument", "timeout_s must be a finite positive duration")
            effective_timeout = min(effective_timeout, value)
        with self._execution_slot(effective_timeout) as deadline:
            self._check_open()
            self._operation_epoch = self._snapshot_epoch
            self._mutation_started = False
            try:
                if command in _MUTATIONS:
                    result = self._live(command, args, deadline)
                elif command == "cdp-detect":
                    result = self._discover(deadline)
                elif command == "cdp-observe":
                    result = self._observe(args, deadline)
                elif command == "cdp-query":
                    result = self._query(args, deadline)
                else:
                    result = self._find(args, deadline, command)
                self._check_operation()
                return result
            except CdpError as exc:
                if self._operation_epoch != self._snapshot_epoch:
                    self._snapshot = None
                if self._cancelled.is_set():
                    self._snapshot = None
                    raise CdpError("adapter_closed", "CDP operation cancelled; no later phases were dispatched",
                                   status="blocked", mutation_may_have_occurred=self._mutation_started or exc.mutation_may_have_occurred) from exc
                exc.mutation_may_have_occurred |= self._mutation_started
                if self._mutation_started:
                    self._snapshot = None
                raise
            except (OSError, TimeoutError) as exc:
                if self._cancelled.is_set():
                    self._snapshot = None
                    raise CdpError("adapter_closed", "CDP operation cancelled; no later phases were dispatched",
                                   status="blocked", mutation_may_have_occurred=self._mutation_started) from exc
                if self._mutation_started:
                    self._snapshot = None
                raise CdpError("cdp_transport_error", str(exc), mutation_may_have_occurred=self._mutation_started) from exc
