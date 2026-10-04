"""Provider-neutral MCP tools over local stdio, with no model SDK or network listener.

One pending tool call, no queue/retry. Cancellation is terminal for the computer
session because an interrupted OS input may already have been delivered.
"""
from __future__ import annotations
import json
import hashlib
import signal
import sys
import threading
from collections import deque
from . import __version__
from .registry import COMMANDS
from .engine import ComputerSession, KEYS
from .native_session import NativeSession
from .server import MAX_REQUEST_BYTES

VERSIONS = ('2025-11-25', '2025-06-18', '2024-11-05')


def obj(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False}


def number(lo, hi):
    return {'type': 'integer', 'minimum': lo, 'maximum': hi}


STRING = {'type': 'string', 'minLength': 1}
HWND = {'type': 'string', 'description': 'Exact HWND returned by cucp_windows'}
TOKEN = {'type': 'string', 'description': 'Latest single-use observation_id; latest is only for later batch steps'}
SCHEMAS = {
    'capabilities': obj(), 'history': obj(), 'windows': obj(),
    'privileges': obj({'pid': number(1, 2**31-1)}),
    'observe': obj({'hwnd': HWND, 'pid': number(1, 2**31-1), 'include_ui': {'type': 'boolean'},
                    'max_width': number(200, 2000), 'max_height': number(200, 2000)}, ['hwnd']),
    'uia-tree': obj({'hwnd': HWND, 'max_depth': number(0, 4), 'max_nodes': number(1, 1000)}, ['hwnd']),
    'wait-window': obj({'title': {'type': 'string', 'minLength': 1, 'maxLength': 256}, 'pid': number(1, 2**31-1),
                        'timeout_ms': number(100, 10000), 'poll_ms': number(100, 1000)}, ['title']),
    'focus': obj({'hwnd': HWND, 'pid': number(1, 2**31-1)}, ['hwnd', 'pid']),
    'click': obj({'observation_id': TOKEN, 'x': number(0, 1999), 'y': number(0, 1999),
                  'button': {'enum': ['left', 'right', 'middle']}, 'count': number(1, 2)}, ['observation_id', 'x', 'y']),
    'drag': obj({'observation_id': TOKEN, 'x': number(0, 1999), 'y': number(0, 1999),
                 'to_x': number(0, 1999), 'to_y': number(0, 1999), 'steps': number(1, 64)}, ['observation_id', 'x', 'y', 'to_x', 'to_y']),
    'type': obj({'observation_id': TOKEN, 'text': {'type': 'string', 'minLength': 1, 'maxLength': 4096}}, ['observation_id', 'text']),
    'key': obj({'observation_id': TOKEN, 'keys': {'type': 'string', 'enum': sorted(KEYS)}}, ['observation_id', 'keys']),
    'scroll': obj({'observation_id': TOKEN, 'direction': {'enum': ['up', 'down', 'left', 'right']},
                   'amount': number(1, 20)}, ['observation_id', 'direction', 'amount']),
    'uia-find': obj({'observation_id': TOKEN, 'name': STRING, 'automation_id': STRING, 'control_type': STRING}, ['observation_id']),
    'uia-invoke': obj({'observation_id': TOKEN, 'element_ref': STRING}, ['observation_id', 'element_ref']),
    'uia-set-value': obj({'observation_id': TOKEN, 'element_ref': STRING, 'text': {'type': 'string', 'maxLength': 4096}}, ['observation_id', 'element_ref', 'text']),
    'app-close': obj({'observation_id': TOKEN, 'timeout_ms': number(0, 10000)}, ['observation_id']),
    'app-launch': obj({'path': {'type': 'string', 'description': 'Absolute existing Windows .exe path; no shell, script, URL or PATH lookup'},
                       'arguments': {'type': 'array', 'maxItems': 64, 'items': {'type': 'string', 'maxLength': 4096}}}, ['path']),
}

SCHEMAS.update({
    'uia-toggle': obj({'observation_id': TOKEN, 'element_ref': STRING}, ['observation_id', 'element_ref']),
    'uia-select': obj({'observation_id': TOKEN, 'element_ref': STRING, 'selection_mode': {'enum': ['replace', 'add', 'remove']}}, ['observation_id', 'element_ref']),
    'uia-expand-collapse': obj({'observation_id': TOKEN, 'element_ref': STRING, 'state': {'enum': ['expanded', 'collapsed']}}, ['observation_id', 'element_ref', 'state']),
    'uia-scroll': obj({'observation_id': TOKEN, 'element_ref': STRING,
        'horizontal': {'enum': ['none', 'small-increment', 'large-increment', 'small-decrement', 'large-decrement']},
        'vertical': {'enum': ['none', 'small-increment', 'large-increment', 'small-decrement', 'large-decrement']}}, ['observation_id', 'element_ref']),
})
CDP_SNAPSHOT = {'type': 'string', 'minLength': 1, 'maxLength': 128}
CDP_ELEMENT = {'type': 'string', 'minLength': 1, 'maxLength': 128}
CDP_FIND = obj({'snapshot_id': CDP_SNAPSHOT, 'text': {'type': 'string', 'minLength': 1, 'maxLength': 1024},
    'action': {'enum': ['click', 'type']}, 'limit': number(1, 100)}, ['snapshot_id', 'text'])
CDP_TYPE = obj({'snapshot_id': CDP_SNAPSHOT, 'element_ref': CDP_ELEMENT, 'text': {'type': 'string', 'maxLength': 16384},
    'clear': {'type': 'boolean'}, 'press_enter': {'type': 'boolean'}}, ['snapshot_id', 'element_ref'])
SCHEMAS.update({
    'cdp-detect': obj(),
    'cdp-observe': obj({'target_id': {'type': 'string', 'minLength': 1, 'maxLength': 256}, 'max_depth': number(1, 24), 'max_nodes': number(1, 2000)}, ['target_id']),
    'cdp-query': obj({'snapshot_id': CDP_SNAPSHOT, 'selector': {'type': 'string', 'minLength': 1, 'maxLength': 2048}, 'limit': number(1, 100)}, ['snapshot_id', 'selector']),
    'cdp-smart-find': CDP_FIND, 'cdp-deep-find': CDP_FIND,
    'cdp-smart-type-find': obj({k:v for k,v in CDP_FIND['properties'].items() if k != 'action'}, ['snapshot_id', 'text']),
    'cdp-click': obj({'snapshot_id': CDP_SNAPSHOT, 'element_ref': CDP_ELEMENT}, ['snapshot_id', 'element_ref']),
    'cdp-smart-click': obj({'snapshot_id': CDP_SNAPSHOT, 'element_ref': CDP_ELEMENT}, ['snapshot_id', 'element_ref']),
    'cdp-type': CDP_TYPE, 'cdp-smart-type': CDP_TYPE,
    'cdp-prosemirror-insert': obj({**CDP_TYPE['properties'], 'text': {'type': 'string', 'minLength': 1, 'maxLength': 16384}}, ['snapshot_id', 'element_ref', 'text']),
    'cdp-eval': obj({'snapshot_id': CDP_SNAPSHOT, 'expression': {'type': 'string', 'minLength': 1, 'maxLength': 32768}}, ['snapshot_id', 'expression']),
})
SCHEMAS['screenshot'] = SCHEMAS['observe']
SCHEMAS['ocr-window'] = obj({**SCHEMAS['observe']['properties'], 'language': {'type': 'string', 'minLength': 2, 'maxLength': 64}}, ['hwnd'])
OCR_QUERY = obj({'observation_id': TOKEN, 'text': {'type': 'string', 'minLength': 1, 'maxLength': 1024},
    'match': {'enum': ['exact', 'prefix', 'contains', 'fuzzy']}, 'min_score': number(0, 100), 'max_candidates': number(1, 50)}, ['observation_id', 'text'])
SCHEMAS['ocr-find'] = OCR_QUERY
SCHEMAS['ocr-uia-fuse'] = OCR_QUERY
RECTANGLE = obj({'x': number(0, 1999), 'y': number(0, 1999), 'width': number(1, 2000), 'height': number(1, 2000)}, ['x', 'y', 'width', 'height'])
SCHEMAS['screenshot-diff'] = obj({'before_id': STRING, 'after_id': STRING, 'threshold': number(0, 255),
    'region': RECTANGLE, 'ignore_regions': {'type': 'array', 'maxItems': 32, 'items': RECTANGLE}}, ['before_id', 'after_id'])

SCHEMAS['batch'] = obj({'actions': {'type': 'array', 'minItems': 1, 'maxItems': 12,
    'items': {'oneOf': [obj({'command': {'const': name}, 'args': schema}, ['command', 'args'])
                         for name, schema in SCHEMAS.items() if name not in {'capabilities', 'history'}]}},
    'observe_after': {'const': True}}, ['actions'])
LEAF_SCHEMAS = dict(SCHEMAS)
STEP = obj({'id': {'type': 'string', 'minLength': 1, 'maxLength': 48}, 'command': {'type': 'string', 'enum': [k for k in LEAF_SCHEMAS if k not in {'capabilities', 'history', 'batch'}]},
    'args': {'type': 'object'}, 'assert': {'type': 'object'}}, ['command', 'args'])
WORKFLOW = obj({'schema': {'const': 'cucp.workflow/v2'}, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
    'steps': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': STEP}, 'timeout_ms': number(100, 60000),
    'settle_ms': number(0, 2000), 'read_retries': number(0, 3)}, ['steps'])
SELECTOR = obj({'name': STRING, 'automation_id': STRING, 'control_type': STRING})
FORM = obj({'hwnd': HWND, 'pid': number(1, 2**31-1), 'fields': {'type': 'array', 'minItems': 1, 'maxItems': 15,
    'items': obj({'selector': SELECTOR, 'text': {'type': 'string', 'maxLength': 4096}}, ['selector', 'text'])},
    'submit': SELECTOR, 'timeout_ms': number(100, 60000)}, ['hwnd', 'fields'])
TASK = obj({'name': STRING, 'target': obj({'hwnd': HWND, 'pid': number(1, 2**31-1)}, ['hwnd', 'pid']),
    'launch': SCHEMAS['app-launch'], 'wait': SCHEMAS['wait-window'], 'focus': {'type': 'boolean'},
    'fields': FORM['properties']['fields'], 'text': SCHEMAS['type']['properties']['text'],
    'keys': {'type': 'array', 'maxItems': 8, 'items': SCHEMAS['key']['properties']['keys']},
    'submit': SELECTOR, 'timeout_ms': number(100, 60000)})
SCHEMAS.update({
    'task-build': TASK, 'task-run': TASK,
    'workflow-plan': obj({'workflow': WORKFLOW}, ['workflow']),
    'workflow-run': obj({'workflow': WORKFLOW, 'dry_run': {'type': 'boolean'}}, ['workflow']),
    'form-plan': FORM, 'form-run': FORM,
    'watch': obj({'command': {'type': 'string', 'enum': [k for k in LEAF_SCHEMAS if k not in {'batch', 'capabilities', 'history'} and COMMANDS[k].effect == 'read']},
                  'args': {'type': 'object'}, 'until': {'type': 'object'}, 'interval_ms': number(100, 5000), 'max_cycles': number(1, 100)}, ['command', 'args']),
    'app-profile': obj({'observation_id': TOKEN}, ['observation_id']),
    'recovery-plan': obj({'failed_reason': {'type': 'string', 'maxLength': 256}}),
    'record-start': obj(), 'record-stop': obj(), 'record-read': obj(),
})
DESCRIPTIONS = {
    'capabilities': 'Read capabilities, current human-selected live mode, limits and keys.',
    'history': 'Read bounded session metadata only; no typed text or screenshots are persisted.',
    'windows': 'List visible Windows HWND and PID targets. Read-only.',
    'observe': 'Observe exact window, PNG and optional UIA. Use returned image pixel dimensions for coordinates.',
    'screenshot': 'Capture exact visible window region. May include occluding windows. Returns single-use observation ID.',
    'uia-tree': 'Read bounded UIA tree. References require the matching screenshot observation from cucp_observe; standalone tree cannot authorize actions.',
    'privileges': 'Read privilege diagnostics; never elevate or bypass secure desktop.',
    'wait-window': 'Wait up to ten seconds for one matching window. Multiple matches are an error.',
    'focus': 'Focus explicit HWND/PID and observe. Requires operator-enabled live mode.',
    'click': 'Click returned image coordinates, latest observation required. Input is not retried.',
    'drag': 'Single bounded left-button drag inside observed window, image pixel coordinates. No dwell or cross-window drag; application recognition must be verified.',
    'type': 'Send Unicode text to current focused control in observed window, then observe. Does not prove application saved it.',
    'key': 'Send an allowlisted key/chord to observed window, then observe. No automatic retry.',
    'scroll': 'Scroll only when pointer is inside observed target. Then observe.',
    'uia-find': 'Find exact matches within latest observed UIA elements. Returns all matches; never chooses the first silently.',
    'uia-invoke': 'Invoke a fresh observed UIA element. Can trigger consequential application actions: host approval remains required. Never retries or falls back to a click.',
    'uia-set-value': 'Set a fresh observed writable UIA element value, including empty text. Password controls rejected; host must approve data and destination.',
    'app-close': 'Request graceful close of observed HWND/PID once. Never force kill; unsaved prompts may keep it open.',
    'app-launch': 'Launch explicit .exe with an argument vector. Can execute programs: host must approve executable and purpose. No shell expansion; launch is not app readiness.',
    'batch': 'Run at most 12 sequential operations. First failure stops all later steps; no rollback or input retry.',
}
DESCRIPTIONS.update({
    'uia-toggle': 'Toggle exactly once on a fresh visible UIA element; never retries.',
    'uia-select': 'Select, add or remove a fresh visible UIA selection item.',
    'uia-expand-collapse': 'Explicitly expand or collapse a fresh visible UIA element.',
    'uia-scroll': 'Scroll a fresh visible UIA container with bounded pattern amounts.',
    'ocr-window': 'Capture selected visible window and recognize its exact returned pixels in memory. OCR coordinates are image pixels. May contain occluding windows; language must be installed.',
    'ocr-find': 'Rank OCR words, lines and 2/3-word phrases from the current OCR observation. Fuzzy matching is explicit and never authorizes an action.',
    'ocr-uia-fuse': 'Correlate current OCR and same-target UIA geometry; ranked candidates only, no automatic click or invoke.',
    'screenshot-diff': 'Compare two retained same-target/same-geometry PNG observations with optional region/masks. Pixel change is not task success.',
    'task-build': 'Compile explicit executable/target, wait, form, text and key intentions into a reviewable workflow. Does not execute it.',
    'task-run': 'Run a compiled task. Launch wait is bound to the newly created PID; exact selectors and fresh observations are mandatory. No automatic input retry.',
    'workflow-plan': 'Validate a bounded declarative plan. Planning grants no authority.',
    'workflow-run': 'Run up to 64 declarative leaf steps, stopping on failure. Never retries mutations; host approval is required for consequences.',
    'form-plan': 'Build a form workflow with exact selectors and a fresh observation before each value or explicit submit.',
    'form-run': 'Run explicit form fields through fresh unique UIA matches. No coordinate fallback; submit only if supplied and authorized by host.',
    'watch': 'Poll a read-only leaf command within bounded cycles/deadline; no background process.',
    'app-profile': 'Summarize patterns and roles from the current observation; no model or CDP probing.',
    'recovery-plan': 'Recommend re-observation after failure; never dismisses dialogs or retries input automatically.',
    'record-start': 'Start bounded memory-only audit metadata recording. No values, images, titles or replay.',
    'record-stop': 'Stop audit metadata recording and return its bounded summary.',
    'record-read': 'Read bounded audit metadata recording for this session.',
})
for _name in SCHEMAS:
    if _name.startswith('cdp-'):
        DESCRIPTIONS[_name] = ('Optional explicitly configured loopback browser adapter. ' +
            ('Requires human-started live mode and fresh browser snapshot/reference; never retries; host approval is required for consequences.' if COMMANDS[_name].effect == 'write' else
             'Read-only DOM protocol observation/search; never evaluates page JavaScript or enables debug access.'))
WRITES = {name for name, spec in COMMANDS.items() if spec.effect != 'read' and spec.available_in_engine}


def tool_list():
    return [{'name': 'cucp_' + name.replace('-', '_'), 'description': DESCRIPTIONS[name], 'inputSchema': schema,
             'annotations': {'readOnlyHint': name not in WRITES, 'destructiveHint': name in WRITES,
                             'idempotentHint': False, 'openWorldHint': name in WRITES}}
            for name, schema in SCHEMAS.items()]


def tool_result(response):
    # Keep coordinate/target metadata as text, image bytes only in MCP ImageContent.
    data = dict(response['data'])
    image = data.pop('image', None)
    if image:
        data['image'] = {k: v for k, v in image.items() if k != 'data'}
    content = [{'type': 'text', 'text': json.dumps({**response, 'data': data}, ensure_ascii=False, allow_nan=False)}]
    if image and image.get('mime_type') == 'image/png' and isinstance(image.get('data'), str):
        content.append({'type': 'image', 'mimeType': 'image/png', 'data': image['data']})
    return {'content': content, 'isError': response['status'] != 'ok'}


class McpServer:
    def __init__(self, session, sink, close_native=lambda: None):
        self.session, self.sink, self.close_native = session, sink, close_native
        self.lock = threading.RLock()
        self.initialized = False
        self.ready = False
        self.closed = False
        self.active = None
        self.worker = None
        self.seen, self.order = set(), deque()

    def send(self, value):
        with self.lock:
            if not self.closed:
                self.sink.write(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
                self.sink.flush()

    def error(self, rid, code, message):
        self.send({'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}})

    def close(self):
        with self.lock:
            self.closed = True
            self.active = None
            self.session.cancel()
        self.close_native()

    def receive(self, request):
        if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
            self.error(None, -32600, 'Expected JSON-RPC 2.0 request object')
            return
        method, params = request['method'], request.get('params', {})
        rid = request.get('id')
        if 'id' not in request:
            if not isinstance(params, dict):
                return
            if method == 'notifications/initialized' and self.initialized:
                self.ready = True
            elif method == 'notifications/cancelled':
                # Invalid, unrelated, and completed cancellation notifications are ignored.
                with self.lock:
                    cancel_id = params.get('requestId')
                    valid = type(cancel_id) in (str, int)
                    cancel = valid and self.active is not None and (type(cancel_id), cancel_id) == self.active
                    if cancel:
                        self.active = None
                        self.session.cancel()
                if cancel:
                    self.close_native()
            return
        if type(rid) not in (str, int) or (isinstance(rid, str) and not 1 <= len(rid) <= 128):
            self.error(None, -32600, 'Request ID must be an integer or 1..128 character string')
            return
        if not isinstance(params, dict):
            self.error(rid, -32602, 'params must be an object')
            return
        key = (type(rid), rid)
        with self.lock:
            if key in self.seen:
                self.error(rid, -32600, 'Duplicate request ID; no action replay')
                return
            self.seen.add(key)
            self.order.append(key)
            if len(self.order) > 1024:
                self.seen.discard(self.order.popleft())
        if method == 'initialize':
            if self.initialized:
                self.error(rid, -32600, 'Already initialized')
                return
            if (not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict)
                or not isinstance(params.get('clientInfo'), dict)):
                self.error(rid, -32602, 'initialize requires protocolVersion, capabilities and clientInfo')
                return
            self.initialized = True
            version = params['protocolVersion'] if params['protocolVersion'] in VERSIONS else VERSIONS[0]
            self.send({'jsonrpc': '2.0', 'id': rid, 'result': {'protocolVersion': version,
                'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'cucp', 'version': __version__},
                'instructions': 'Local Windows computer use. Live control is human-selected at launch, off by default. '
                    'Never auto-retry input. Cancellation ends computer control until process restart. '
                    'Read image dimensions, use fresh observation IDs, verify results. Host must enforce user permissions.'}})
        elif method == 'ping':
            self.send({'jsonrpc': '2.0', 'id': rid, 'result': {}})
        elif not self.ready:
            self.error(rid, -32000, 'Complete initialize and notifications/initialized first')
        elif method == 'tools/list':
            if set(params) - {'_meta'}:
                self.error(rid, -32602, 'This server has one unpaginated tools list')
            else:
                self.send({'jsonrpc': '2.0', 'id': rid, 'result': {'tools': tool_list()}})
        elif method == 'tools/call':
            name, arguments = params.get('name'), params.get('arguments', {})
            names = {'cucp_' + n.replace('-', '_'): n for n in SCHEMAS}
            if set(params) - {'name', 'arguments', '_meta'} or not isinstance(name, str) or name not in names or not isinstance(arguments, dict):
                self.error(rid, -32602, 'Unknown tool or invalid tool arguments')
                return
            with self.lock:
                if self.active is not None or (self.worker is not None and self.worker.is_alive()):
                    self.error(rid, -32000, 'A tool call is in progress; no queued or replayed actions')
                    return
                self.active = key
                self.worker = threading.Thread(target=self._call, args=(key, names[name], arguments), daemon=True)
                self.worker.start()
        else:
            self.error(rid, -32601, 'Method not supported')

    def _call(self, key, command, args):
        try:
            response = self.session.handle({'schema': 'cucp.request/v1', 'id': hashlib.sha256((('i:' if key[0] is int else 's:') + str(key[1])).encode()).hexdigest(),
                                            'command': command, 'args': args})
            with self.lock:
                if self.active == key:
                    self.send({'jsonrpc': '2.0', 'id': key[1], 'result': tool_result(response)})
                    self.active = None
        except (BrokenPipeError, OSError):
            self.close()
        except Exception:
            with self.lock:
                if self.active == key:
                    self.error(key[1], -32603, 'Internal error; restart session, do not replay input')
                    self.active = None
                    self.session.cancel()
            self.close_native()


def serve_mcp(*, allow_live_control=False, source=None, sink=None, cdp_endpoint=None):
    source = source if source is not None else sys.stdin.buffer
    sink = sink if sink is not None else sys.stdout
    with NativeSession(allow_live_control=allow_live_control) as native:
        session = ComputerSession(allow_live_control=allow_live_control, native=native,
                                  native_transport='persistent subprocess (stdio-jsonl)', cdp_endpoint=cdp_endpoint)
        server = McpServer(session, sink, native.close)
        old = {}
        if threading.current_thread() is threading.main_thread():
            def stop(signum, frame):
                server.close()
                raise SystemExit(128 + signum)
            old = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            while not server.closed:
                line = source.readline(MAX_REQUEST_BYTES + 1)
                if not line:
                    return 0
                if len(line) > MAX_REQUEST_BYTES:
                    server.error(None, -32600, 'Maximum frame is 256 KiB; session closed')
                    return 2
                try:
                    request = json.loads(line.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                except (ValueError, UnicodeError, RecursionError):
                    server.error(None, -32700, 'Invalid JSON')
                else:
                    server.receive(request)
        except (BrokenPipeError, OSError):
            return 1
        finally:
            server.close()
            if server.worker:
                server.worker.join(timeout=2)
            for sig, handler in old.items():
                signal.signal(sig, handler)


def run_mcp(*, allow_live_control=False, cdp_endpoint=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    return serve_mcp(allow_live_control=allow_live_control, cdp_endpoint=cdp_endpoint)
