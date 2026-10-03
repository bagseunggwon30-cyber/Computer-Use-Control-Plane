"""Only local mock CDP servers: never connect to a real browser or account."""
from contextlib import contextmanager
import base64
import copy
import hashlib
import json
from pathlib import Path
import socket
import socketserver
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next' / 'python'))
from pcucp_cli.cdp import CdpAdapter, CdpError, MAX_BODY


def text_node(backend, text):
    return {'nodeId': backend, 'backendNodeId': backend, 'nodeType': 3, 'nodeName': '#text', 'nodeValue': text}


def element(backend, tag, attrs=None, children=None):
    return {'nodeId': backend, 'backendNodeId': backend, 'nodeType': 1, 'nodeName': tag,
            'attributes': [v for pair in (attrs or {}).items() for v in pair], 'children': children or [],
            'childNodeCount': len(children or [])}


def document():
    return {'nodeId': 1, 'backendNodeId': 1, 'nodeType': 9, 'nodeName': '#document', 'nodeValue': '',
            'documentURL': 'https://example.test/', 'childNodeCount': 1,
            'children': [element(2, 'BODY', children=[
                element(3, 'BUTTON', {'id': 'save', 'aria-label': 'Save'}, [text_node(4, 'Save')]),
                element(5, 'INPUT', {'id': 'message', 'aria-label': 'Message'}),
                element(6, 'DIV', {'class': 'ProseMirror', 'contenteditable': 'true', 'aria-label': 'Editor'}, [text_node(7, 'hello')]),
                element(8, 'INPUT', {'type': 'password', 'value': 'must-not-be-returned', 'aria-label': 'Password'})]) ]}


def walk(node):
    yield node
    for child in node.get('children', []) + node.get('shadowRoots', []):
        yield from walk(child)
    if node.get('contentDocument'):
        yield from walk(node['contentDocument'])


def at_depth(node, depth):
    if not isinstance(node, dict): return node
    node = copy.deepcopy(node)
    if depth <= 0:
        node.pop('children', None)
        node.pop('shadowRoots', None)
        node.pop('contentDocument', None)
    else:
        for key in ('children', 'shadowRoots'):
            if key in node: node[key] = [at_depth(child, depth - 1) for child in node[key]]
        if 'contentDocument' in node: node['contentDocument'] = at_depth(node['contentDocument'], depth - 1)
    return node


def frame(data, opcode=1, fin=True, mask=False, rsv=0):
    payload = data if isinstance(data, bytes) else json.dumps(data).encode()
    n = len(payload)
    prefix = bytes([(128 if fin else 0) | rsv | opcode, (128 if mask else 0) | n]) if n < 126 else bytes([(128 if fin else 0) | rsv | opcode, (128 if mask else 0) | 126]) + struct.pack('>H', n)
    if mask:
        return prefix + b'abcd' + bytes(v ^ b'abcd'[i % 4] for i, v in enumerate(payload))
    return prefix + payload


class MockState:
    def __init__(self):
        self.root = document()
        self.requests = []
        self.paths = []
        self.client_frames = []
        self.http_mode = ''
        self.ws_mode = ''
        self.fail_method = None
        self.drop_method = None
        self.action_ok = True
        self.target_url = 'https://example.test/'
        self.external_ws = None
        self.target_count = 1
        self.delay = 0
        self.query_ids = [3]
        self.port = 0
        self.pong = threading.Event()
        self.block_method = None
        self.blocked = threading.Event()
        self.release = threading.Event()

    def respond(self, request):
        self.requests.append(request)
        method, params = request['method'], request['params']
        if method == self.block_method:
            self.blocked.set()
            self.release.wait(2)
        if method == self.fail_method:
            return {'error': {'code': -32000, 'message': 'fixture failure'}}
        if method == 'DOM.getDocument':
            return {'result': {'root': at_depth(self.root, params.get('depth', 0))}}
        if method == 'DOM.querySelectorAll': return {'result': {'nodeIds': self.query_ids}}
        if method == 'DOM.describeNode':
            backend = params.get('backendNodeId', params.get('nodeId'))
            node = next(n for n in walk(self.root) if n['backendNodeId'] == backend)
            return {'result': {'node': at_depth(node, params.get('depth', 0))}}
        if method == 'DOM.resolveNode': return {'result': {'object': {'type': 'object', 'objectId': 'object-for-' + str(params['backendNodeId'])}}}
        if method == 'Runtime.evaluate': return {'result': {'result': {'type': 'string', 'value': 'fixture-evaluated'}}}
        if method == 'Runtime.callFunctionOn':
            return {'result': {'result': {'type': 'object', 'value': {'ok': self.action_ok, 'reason': 'fixture_blocked'}}}}
        if method in ('Input.insertText', 'Input.dispatchKeyEvent'): return {'result': {}}
        return {'error': {'code': -1, 'message': 'unexpected method'}}


class MockHandler(socketserver.StreamRequestHandler):
    def handle(self):
        state = self.server.state
        self.connection.settimeout(2)
        try:
            request_line = self.rfile.readline().decode().strip()
            if not request_line: return
            path = request_line.split(' ')[1]
            state.paths.append(path)
            headers = {}
            while True:
                line = self.rfile.readline().decode().strip()
                if not line: break
                key, value = line.split(':', 1)
                headers[key.lower()] = value.strip()
            if path.startswith('/json/'):
                if state.delay: time.sleep(state.delay)
                if state.http_mode == 'redirect':
                    self.wfile.write(b'HTTP/1.1 302 Found\r\nLocation: http://203.0.113.1/\r\nContent-Length: 0\r\n\r\n'); return
                if state.http_mode == 'oversized':
                    self.wfile.write(f'HTTP/1.1 200 OK\r\nContent-Length: {MAX_BODY+1}\r\n\r\n'.encode()); return
                data = {'Browser': 'Mock/1', 'Protocol-Version': '1.3'} if path == '/json/version' else [
                    {'id': f'page-{i}', 'type': 'page', 'title': 'Fixture', 'url': state.target_url,
                     'webSocketDebuggerUrl': state.external_ws or f'ws://127.0.0.1:{state.port}/devtools/page/page-{i}'}
                    for i in range(state.target_count)]
                body = json.dumps(data).encode()
                if state.http_mode == 'chunked':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' + f'{len(body):x}\r\n'.encode() + body + b'\r\n0\r\n\r\n'); return
                if state.http_mode == 'compressed':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\n{}'); return
                self.wfile.write(f'HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body); return
            key = headers['sec-websocket-key']
            accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if state.ws_mode == 'bad_accept': accept = 'bad'
            extra = 'Sec-WebSocket-Extensions: permessage-deflate\r\n' if state.ws_mode == 'extension' else ''
            self.wfile.write(f'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n{extra}\r\n'.encode())
            self.wfile.flush()
            while True:
                first = self.rfile.read(2)
                if not first: return
                a, b = first
                length = b & 127
                if length == 126: length = struct.unpack('>H', self.rfile.read(2))[0]
                elif length == 127: length = struct.unpack('>Q', self.rfile.read(8))[0]
                mask = self.rfile.read(4) if b & 128 else None
                payload = self.rfile.read(length)
                if mask: payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
                state.client_frames.append((a & 15, bool(mask), length))
                if a & 15 == 8: return
                if a & 15 == 10:
                    state.pong.set()
                    continue
                message = json.loads(payload)
                if message['method'] == state.drop_method:
                    state.requests.append(message); return
                response = {'id': message['id'], **state.respond(message)}
                if state.ws_mode == 'oversized':
                    self.wfile.write(bytes([0x81, 127]) + struct.pack('>Q', MAX_BODY + 1)); return
                if state.ws_mode == 'masked': self.wfile.write(frame(response, mask=True)); return
                if state.ws_mode == 'reserved': self.wfile.write(frame(response, rsv=64)); return
                if state.ws_mode == 'binary': self.wfile.write(frame(b'abc', opcode=2)); return
                if state.ws_mode == 'bad_continuation': self.wfile.write(frame(b'{}', opcode=0)); return
                if state.ws_mode == 'duplicate_json': self.wfile.write(frame(b'{"id":1,"id":1,"result":{}}')); return
                if state.ws_mode == 'wrong_ids':
                    for i in range(100): self.wfile.write(frame({'id': 99999, 'result': {}}))
                    return
                if state.ws_mode == 'fragmented':
                    encoded = json.dumps(response, ensure_ascii=False).encode()
                    self.wfile.write(frame({'method': 'DOM.documentUpdated', 'params': {}}))
                    self.wfile.write(frame(encoded[:20], fin=False))
                    self.wfile.write(frame(b'ping', opcode=9))
                    self.wfile.write(frame(encoded[20:], opcode=0))
                else:
                    self.wfile.write(frame(response))
                self.wfile.flush()
        except (ConnectionError, OSError, ValueError, KeyError, StopIteration):
            return


class MockServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@contextmanager
def server():
    instance = MockServer(('127.0.0.1', 0), MockHandler)
    instance.state = MockState()
    instance.state.port = instance.server_address[1]
    thread = threading.Thread(target=instance.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield instance.state, f'http://127.0.0.1:{instance.state.port}'
    finally:
        instance.shutdown(); instance.server_close(); thread.join(timeout=1)


class EndpointTests(unittest.TestCase):
    def test_numeric_loopback_explicit_origin_only(self):
        bad = ['http://localhost:9222', 'http://127.1:9222', 'http://127.0.0.1', 'https://127.0.0.1:9222',
               'http://192.168.1.1:9222', 'http://0.0.0.0:9222', 'http://2130706433:9222', 'http://[::ffff:127.0.0.1]:9222',
               'http://u:p@127.0.0.1:9222', 'http://127.0.0.1:9222/json', 'http://127.0.0.1:9222/?a=1',
               'http://127.0.0.1:9222/#x', ' http://127.0.0.1:9222', 'http://[::1%lo]:9222', 'http://127.0.0.1:99999']
        with patch('socket.socket', side_effect=AssertionError('constructor must not connect')):
            for endpoint in bad:
                with self.subTest(endpoint=endpoint), self.assertRaises(CdpError): CdpAdapter(endpoint)
            self.assertEqual(CdpAdapter('http://[::1]:1234/').endpoint, 'http://[::1]:1234')
            self.assertEqual(CdpAdapter('http://127.0.0.2:1234').endpoint, 'http://127.0.0.2:1234')

    def test_live_flag_not_changeable_by_requests_or_property(self):
        adapter = CdpAdapter('http://127.0.0.1:1')
        with self.assertRaises(AttributeError): adapter.allow_live_control = True
        with self.assertRaises(CdpError): adapter.execute('cdp-detect', {'allow_live_control': True})
        with self.assertRaises(CdpError) as error: adapter.execute('cdp-eval', {'snapshot_id': 'fake', 'expression': '1'})
        self.assertEqual(error.exception.code, 'live_control_required')
        self.assertFalse(error.exception.mutation_may_have_occurred)

    def test_closed_adapter_and_invalid_arguments(self):
        adapter = CdpAdapter('http://127.0.0.1:1')
        for command, args in [('Runtime.evaluate', {}), ('cdp-observe', {}), ('cdp-detect', []), ('cdp-detect', {'endpoint':'other'})]:
            with self.assertRaises(CdpError): adapter.execute(command, args)
        adapter.close()
        with self.assertRaises(CdpError) as error: adapter.execute('cdp-detect')
        self.assertEqual(error.exception.code, 'adapter_closed')


class TransportTests(unittest.TestCase):
    def test_discovery_and_chunked_http(self):
        with server() as (state, endpoint):
            state.http_mode = 'chunked'
            result = CdpAdapter(endpoint).execute('cdp-detect')
            self.assertEqual(result['targets'][0]['id'], 'page-0')
            self.assertEqual(state.paths, ['/json/version', '/json/list'])
            self.assertFalse(result['automatic_enable'])

    def test_http_redirect_oversize_compression_rejected(self):
        with server() as (state, endpoint):
            for mode, code in [('redirect','http_redirect_rejected'), ('oversized','response_limit'), ('compressed','unsupported_encoding')]:
                state.http_mode = mode
                with self.subTest(mode=mode), self.assertRaises(CdpError) as error: CdpAdapter(endpoint).execute('cdp-detect')
                self.assertEqual(error.exception.code, code)

    def test_ws_origin_port_path_and_dns_escape_rejected_before_connect(self):
        with server() as (state, endpoint):
            for value in ('ws://203.0.113.1:1234/devtools/page/page-0', 'ws://localhost:1234/devtools/page/page-0',
                          f'ws://127.0.0.1:{state.port+1}/devtools/page/page-0',
                          f'ws://127.0.0.1:{state.port}/devtools/browser/page-0',
                          f'ws://127.0.0.1:{state.port}/devtools/page/page-0?token=x'):
                state.external_ws = value
                with self.subTest(value=value), self.assertRaises(CdpError): CdpAdapter(endpoint).execute('cdp-observe', {'target_id':'page-0'})
            self.assertFalse(any(path.startswith('/devtools') for path in state.paths))

    def test_masked_client_fragmented_response_ping_and_correlation(self):
        with server() as (state, endpoint):
            state.ws_mode = 'fragmented'
            result = CdpAdapter(endpoint).execute('cdp-observe', {'target_id':'page-0'})
            self.assertGreater(result['node_count'], 0)
            self.assertTrue(all(masked for _, masked, _ in state.client_frames))
            self.assertTrue(state.pong.wait(1))
            self.assertIn(10, [op for op, _, _ in state.client_frames])

    def test_malformed_websocket_rejected(self):
        for mode in ('bad_accept','extension','oversized','masked','reserved','binary','bad_continuation','duplicate_json','wrong_ids'):
            with self.subTest(mode=mode), server() as (state, endpoint):
                state.ws_mode = mode
                with self.assertRaises(CdpError): CdpAdapter(endpoint).execute('cdp-observe', {'target_id':'page-0'})

    def test_absolute_transport_timeout(self):
        with server() as (state, endpoint):
            state.delay = .15
            started = time.monotonic()
            with self.assertRaises(CdpError): CdpAdapter(endpoint, timeout_s=.05).execute('cdp-detect')
            self.assertLess(time.monotonic()-started, .5)

    def test_protocol_errors_not_silently_successful(self):
        with server() as (state, endpoint):
            state.fail_method = 'DOM.getDocument'
            with self.assertRaises(CdpError) as error: CdpAdapter(endpoint).execute('cdp-observe', {'target_id':'page-0'})
            self.assertEqual(error.exception.code, 'cdp_protocol_error')


class ObservationTests(unittest.TestCase):
    def test_read_only_observe_find_query_never_eval_or_input(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint)
            observed = adapter.execute('cdp-observe', {'target_id':'page-0'})
            sid = observed['snapshot_id']
            found = adapter.execute('cdp-smart-find', {'snapshot_id':sid, 'text':'Save'})
            queried = adapter.execute('cdp-query', {'snapshot_id':sid, 'selector':'#save'})
            self.assertEqual(found['top']['attributes']['id'], 'save')
            self.assertEqual(queried['candidate_count'], 1)
            self.assertEqual(found['visibility'], 'unverified')
            self.assertNotIn('must-not-be-returned', json.dumps(observed))
            self.assertTrue(all(r['method'].startswith('DOM.') for r in state.requests))

    def test_ambiguity_limit_one_and_explicit_page_id(self):
        with server() as (state, endpoint):
            state.target_count = 2
            state.root['children'][0]['children'].append(element(10, 'BUTTON', {'aria-label':'Save'}, [text_node(11,'Save')]))
            state.root['children'][0]['childNodeCount'] += 1
            adapter = CdpAdapter(endpoint)
            observed = adapter.execute('cdp-observe', {'target_id':'page-1'})
            result = adapter.execute('cdp-smart-find', {'snapshot_id':observed['snapshot_id'], 'text':'Save', 'limit':1})
            self.assertTrue(result['ambiguous'])
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['target_id'], 'page-1')
            self.assertEqual(len(result['candidates']), 1)

    def test_selector_ambiguity_not_arbitrary_first(self):
        with server() as (state, endpoint):
            state.query_ids = [3,5]
            adapter = CdpAdapter(endpoint)
            sid = adapter.execute('cdp-observe', {'target_id':'page-0'})['snapshot_id']
            result = adapter.execute('cdp-query', {'snapshot_id':sid, 'selector':'input,button', 'limit':1})
            self.assertTrue(result['ambiguous'])
            self.assertEqual(result['candidate_count'], 2)

    def test_shadow_and_frame_traversal_and_inaccessible_report(self):
        with server() as (state, endpoint):
            host = element(10,'CUSTOM-ELEMENT')
            host['shadowRoots'] = [{'nodeId':11,'backendNodeId':11,'nodeType':11,'nodeName':'#document-fragment',
                                    'children':[element(12,'BUTTON', {'aria-label':'Shadow Save'})], 'childNodeCount':1}]
            state.root['children'][0]['children'] += [host, element(13,'IFRAME')]
            state.root['children'][0]['childNodeCount'] += 2
            adapter = CdpAdapter(endpoint)
            observed = adapter.execute('cdp-observe', {'target_id':'page-0'})
            self.assertEqual(observed['traversal']['shadow_roots_seen'],1)
            self.assertEqual(observed['traversal']['inaccessible_frames'],1)
            found = adapter.execute('cdp-deep-find', {'snapshot_id':observed['snapshot_id'],'text':'Shadow Save'})
            self.assertEqual(found['top']['attributes']['aria-label'],'Shadow Save')
            self.assertEqual(found['status'],'partial')

    def test_label_association_and_password_not_type_candidate(self):
        with server() as (state, endpoint):
            state.root['children'][0]['children'].append(element(10,'LABEL',{'for':'message'},[text_node(11,'Write a note')]))
            state.root['children'][0]['childNodeCount'] += 1
            adapter = CdpAdapter(endpoint)
            sid = adapter.execute('cdp-observe', {'target_id':'page-0'})['snapshot_id']
            found = adapter.execute('cdp-smart-type-find', {'snapshot_id':sid,'text':'Write a note'})
            self.assertEqual(found['top']['attributes']['id'],'message')
            self.assertEqual(adapter.execute('cdp-smart-type-find', {'snapshot_id':sid,'text':'Password'})['status'],'not_found')

    def test_malformed_dom_returns_structured_error(self):
        for change in ('count', 'child'):
            with self.subTest(change=change), server() as (state, endpoint):
                if change == 'count': state.root['childNodeCount'] = 'not a count'
                else: state.root['children'] = [None]
                with self.assertRaises(CdpError) as error: CdpAdapter(endpoint).execute('cdp-observe', {'target_id':'page-0'})
                self.assertEqual(error.exception.code,'invalid_dom')

    def test_source_only_subtrees_never_appear_in_public_observation_or_search(self):
        with server() as (state, endpoint):
            secret = 'sk-fixture-not-a-real-api-key-123456'
            body = state.root['children'][0]
            for offset, tag in enumerate(('SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE')):
                base = 20 + offset * 10
                hidden = element(base, tag, {'id': f'source-{offset}'},
                                 [text_node(base+1, f'const token = "{secret}";'),
                                  element(base+2, 'BUTTON', {'aria-label': 'Inert source button'}, [text_node(base+3, secret)])])
                body['children'].append(hidden)
                body['childNodeCount'] += 1
            adapter = CdpAdapter(endpoint)
            observed = adapter.execute('cdp-observe', {'target_id':'page-0'})
            sid = observed['snapshot_id']
            self.assertNotIn(secret, json.dumps(observed))
            self.assertTrue(all(n['tag_name'] not in {'script','style','noscript','template'} for n in observed['nodes']))
            self.assertFalse(any(n['attributes'].get('aria-label') == 'Inert source button' for n in observed['nodes']))
            for command in ('cdp-smart-find', 'cdp-smart-type-find', 'cdp-deep-find'):
                result = adapter.execute(command, {'snapshot_id':sid, 'text':secret})
                self.assertEqual(result['candidate_count'], 0)
                self.assertNotIn(secret, json.dumps(result))
            normal = adapter.execute('cdp-smart-find', {'snapshot_id':sid, 'text':'Save'})
            self.assertEqual(normal['top']['attributes']['id'], 'save')
            self.assertNotIn(secret, json.dumps(normal))
            state.query_ids = [20]
            source_query = adapter.execute('cdp-query', {'snapshot_id':sid, 'selector':'script'})
            self.assertEqual(source_query['candidates'], [])
            self.assertEqual(source_query['unobserved_count'], 1)
            self.assertNotIn(secret, json.dumps(source_query))

    def test_textarea_value_is_private_but_labels_refs_and_freshness_remain(self):
        with server() as (state, endpoint):
            default = 'CANARY-TEXTAREA-DEFAULT-OWNED'
            value = 'CANARY-TEXTAREA-VALUE-OWNED'
            area = element(20, 'TEXTAREA', {'id':'notes', 'value':value}, [text_node(21, default)])
            label = element(22, 'LABEL', {'for':'notes'}, [text_node(23, 'Owned notes')])
            body = state.root['children'][0]
            body['children'].extend([area, label]); body['childNodeCount'] += 2
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            self.addCleanup(adapter.close)
            observed = adapter.execute('cdp-observe', {'target_id':'page-0'})
            sid = observed['snapshot_id']
            public = next(n for n in observed['nodes'] if n['attributes'].get('id') == 'notes')
            self.assertEqual(public['text'], '')
            self.assertNotIn('CANARY-', json.dumps(observed))
            for command in ('cdp-smart-find', 'cdp-smart-type-find', 'cdp-deep-find'):
                found = adapter.execute(command, {'snapshot_id':sid, 'text':default})
                self.assertEqual(found['candidate_count'], 0)
                self.assertNotIn('CANARY-', json.dumps(found))
            labelled = adapter.execute('cdp-smart-type-find', {'snapshot_id':sid, 'text':'Owned notes'})
            self.assertEqual(labelled['top']['element_ref'], public['element_ref'])
            state.query_ids = [20]
            queried = adapter.execute('cdp-query', {'snapshot_id':sid, 'selector':'#notes'})
            self.assertEqual(queried['candidates'][0]['element_ref'], public['element_ref'])
            self.assertNotIn('CANARY-', json.dumps(queried))
            self.assertTrue(all(r['method'].startswith('DOM.') for r in state.requests))
            # Private source still participates in the internal stale-reference
            # check; suppressing output must not discard that safety evidence.
            area['children'][0]['nodeValue'] = 'CHANGED-OWNED-DEFAULT'
            with self.assertRaises(CdpError) as raised:
                adapter.execute('cdp-type', {'snapshot_id':sid, 'element_ref':public['element_ref'],
                                            'text':'owned', 'clear':True})
            self.assertEqual(raised.exception.code, 'element_changed')
            self.assertTrue(all(r['method'].startswith('DOM.') for r in state.requests))

    def test_snapshot_expiry_and_replacement(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, snapshot_ttl_s=.05)
            sid = adapter.execute('cdp-observe', {'target_id':'page-0'})['snapshot_id']
            # Exercise expiry independently of Windows timer granularity.
            before = len(state.requests)
            with patch('pcucp_cli.cdp.time.monotonic', return_value=adapter._snapshot['created'] + .1):
                with self.assertRaises(CdpError) as error:
                    adapter.execute('cdp-smart-find', {'snapshot_id':sid,'text':'Save'})
            self.assertEqual(error.exception.code,'stale_snapshot')
            self.assertEqual(len(state.requests), before)
            sid = adapter.execute('cdp-observe', {'target_id':'page-0'})['snapshot_id']
            adapter.execute('cdp-observe', {'target_id':'page-0'})
            with self.assertRaises(CdpError): adapter.execute('cdp-smart-find', {'snapshot_id':sid,'text':'Save'})

    def test_limits_and_missing_target(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint)
            with self.assertRaises(CdpError): adapter.execute('cdp-observe', {'target_id':'missing'})
            with self.assertRaises(CdpError): adapter.execute('cdp-observe', {'target_id':'page-0','max_depth':25})
            result = adapter.execute('cdp-observe', {'target_id':'page-0','max_nodes':2})
            self.assertTrue(result['truncated'])
            self.assertEqual(result['status'],'partial')


class MutationTests(unittest.TestCase):
    def observe(self, adapter, tag='button'):
        result = adapter.execute('cdp-observe', {'target_id':'page-0'})
        item = next(n for n in result['nodes'] if n['tag_name'] == tag)
        return {'snapshot_id':result['snapshot_id'],'element_ref':item['element_ref']}

    def test_click_exact_reference_consumes_snapshot(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            result = adapter.execute('cdp-click',args)
            self.assertTrue(result['dispatched'])
            self.assertFalse(result['automatic_retry'])
            calls = [r for r in state.requests if r['method']=='Runtime.callFunctionOn']
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['params']['objectId'],'object-for-3')
            self.assertEqual(calls[0]['params']['arguments'][0],{'value':'click'})
            with self.assertRaises(CdpError) as error: adapter.execute('cdp-click',args)
            self.assertEqual(error.exception.code,'stale_snapshot')

    def test_type_text_is_protocol_argument_not_source_interpolation(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter,'input')
            text = '안녕 " ); fetch("evil"); \\ newline\n'
            adapter.execute('cdp-type',dict(args,text=text,clear=True,press_enter=True))
            call = next(r for r in state.requests if r['method']=='Runtime.callFunctionOn')
            self.assertNotIn(text,call['params']['functionDeclaration'])
            self.assertEqual(call['params']['arguments'][1],{'value':text})

    def test_prosemirror_focus_check_insert_and_enter(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter,'div')
            result = adapter.execute('cdp-prosemirror-insert',dict(args,text='새 문장',clear=True,press_enter=True))
            methods = [r['method'] for r in state.requests]
            self.assertEqual(methods.count('Input.insertText'),1)
            self.assertEqual(methods.count('Input.dispatchKeyEvent'),2)
            self.assertEqual(methods.count('Runtime.callFunctionOn'),3)
            self.assertTrue(result['dispatched'])

    def test_read_only_rejects_all_mutation_before_network(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint)
            for command in ('cdp-click','cdp-smart-click','cdp-type','cdp-smart-type','cdp-prosemirror-insert'):
                with self.subTest(command=command), self.assertRaises(CdpError) as error:
                    adapter.execute(command,{'snapshot_id':'s','element_ref':'e'})
                self.assertEqual(error.exception.code,'live_control_required')
            self.assertEqual(state.paths,[])

    def test_target_navigation_document_replacement_or_changed_node_blocks(self):
        for change in ('url','document','node'):
            with self.subTest(change=change), server() as (state, endpoint):
                adapter = CdpAdapter(endpoint, allow_live_control=True)
                args = self.observe(adapter)
                if change=='url': state.target_url='https://changed.test/'
                if change=='document': state.root['backendNodeId']=999
                if change=='node': state.root['children'][0]['children'][0]['attributes']=['id','different']
                with self.assertRaises(CdpError) as error: adapter.execute('cdp-click',args)
                self.assertFalse(error.exception.mutation_may_have_occurred)
                self.assertFalse(any(r['method'].startswith('Runtime.') for r in state.requests))

    def test_lost_mutation_reply_is_uncertain_and_never_retried(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            state.drop_method='Runtime.callFunctionOn'
            with self.assertRaises(CdpError) as error: adapter.execute('cdp-click',args)
            self.assertTrue(error.exception.mutation_may_have_occurred)
            self.assertEqual(sum(r['method']==state.drop_method for r in state.requests),1)
            with self.assertRaises(CdpError) as second: adapter.execute('cdp-click',args)
            self.assertEqual(second.exception.code,'stale_snapshot')

    def test_incomplete_element_ref_cannot_be_mutated(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            result = adapter.execute('cdp-observe', {'target_id':'page-0','max_depth':2})
            button = next(n for n in result['nodes'] if n['tag_name']=='button')
            with self.assertRaises(CdpError) as error:
                adapter.execute('cdp-click', {'snapshot_id':result['snapshot_id'],'element_ref':button['element_ref']})
            self.assertEqual(error.exception.code,'incomplete_element')
            self.assertFalse(any(r['method'].startswith('Runtime.') for r in state.requests))

    def test_long_unicode_type_payload_is_masked_and_not_truncated(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter,'input')
            value = '가' * 16000
            adapter.execute('cdp-type',dict(args,text=value))
            request = next(r for r in state.requests if r['method']=='Runtime.callFunctionOn')
            self.assertEqual(request['params']['arguments'][1]['value'],value)
            self.assertTrue(all(masked for _,masked,_ in state.client_frames))

    def test_empty_type_request_rejected_before_dom_mutation(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter,'input')
            with self.assertRaises(CdpError) as error: adapter.execute('cdp-type',args)
            self.assertEqual(error.exception.code,'invalid_argument')
            self.assertFalse(any(r['method'].startswith('Runtime.') for r in state.requests))

    def test_eval_is_live_gated_and_consumes_snapshot(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            result = adapter.execute('cdp-eval',{'snapshot_id':args['snapshot_id'],'expression':'document.title'})
            self.assertEqual(result['result_value'],'fixture-evaluated')
            with self.assertRaises(CdpError): adapter.execute('cdp-eval',{'snapshot_id':args['snapshot_id'],'expression':'1'})

    def test_element_ref_must_belong_to_exact_snapshot(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            old = self.observe(adapter)
            new = self.observe(adapter)
            with self.assertRaises(CdpError) as error: adapter.execute('cdp-click',dict(new,element_ref=old['element_ref']))
            self.assertEqual(error.exception.code,'unknown_element_reference')

    def test_page_refusal_has_no_success_or_fallback(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            state.action_ok=False
            with self.assertRaises(CdpError) as error: adapter.execute('cdp-click',args)
            self.assertEqual(error.exception.code,'element_action_blocked')
            self.assertEqual(sum(r['method']=='Runtime.callFunctionOn' for r in state.requests),1)


class CancellationTests(unittest.TestCase):
    def start_action(self, adapter, command, args):
        outcome = []
        def run():
            try: outcome.append(adapter.execute(command, args))
            except BaseException as error: outcome.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        return thread, outcome

    def observe(self, adapter, tag='button'):
        result = adapter.execute('cdp-observe', {'target_id':'page-0'})
        element = next(item for item in result['nodes'] if item['tag_name'] == tag)
        return {'snapshot_id':result['snapshot_id'],'element_ref':element['element_ref']}

    def test_close_during_dom_preflight_is_nonblocking_and_no_mutation_follows(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True, timeout_s=5)
            args = self.observe(adapter)
            state.block_method = 'DOM.describeNode'
            thread, outcome = self.start_action(adapter, 'cdp-click', args)
            try:
                self.assertTrue(state.blocked.wait(1))
                started = time.monotonic()
                adapter.close()
                self.assertLess(time.monotonic() - started, .2)
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertIsInstance(outcome[0], CdpError)
                self.assertEqual(outcome[0].code, 'adapter_closed')
                self.assertFalse(outcome[0].mutation_may_have_occurred)
                self.assertFalse(any(r['method'].startswith(('Runtime.', 'Input.')) for r in state.requests))
                with self.assertRaises(CdpError): adapter.execute('cdp-detect')
            finally:
                state.release.set(); thread.join(2)

    def test_close_after_sent_focus_is_uncertain_and_no_insert_or_enter_follows(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True, timeout_s=5)
            args = dict(self.observe(adapter, 'div'), text='insert', press_enter=True)
            state.block_method = 'Runtime.callFunctionOn'
            thread, outcome = self.start_action(adapter, 'cdp-prosemirror-insert', args)
            try:
                self.assertTrue(state.blocked.wait(1))
                adapter.close()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertIsInstance(outcome[0], CdpError)
                self.assertEqual(outcome[0].code, 'adapter_closed')
                self.assertTrue(outcome[0].mutation_may_have_occurred)
                self.assertEqual(sum(r['method'] == 'Runtime.callFunctionOn' for r in state.requests), 1)
                self.assertFalse(any(r['method'].startswith('Input.') for r in state.requests))
            finally:
                state.release.set(); thread.join(2)

    def test_invalidation_during_preflight_is_nonterminal_and_blocks_later_mutation(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            state.block_method = 'DOM.describeNode'
            thread, outcome = self.start_action(adapter, 'cdp-click', args)
            try:
                self.assertTrue(state.blocked.wait(1))
                adapter.invalidate_snapshot()
                state.release.set()
                thread.join(1)
                self.assertIsInstance(outcome[0], CdpError)
                self.assertEqual(outcome[0].code, 'stale_snapshot')
                self.assertFalse(outcome[0].mutation_may_have_occurred)
                self.assertFalse(any(r['method'].startswith('Runtime.') for r in state.requests))
                state.block_method = None
                new_args = self.observe(adapter)
                self.assertNotEqual(new_args['snapshot_id'], args['snapshot_id'])
                self.assertTrue(adapter.execute('cdp-click', new_args)['dispatched'])
            finally:
                state.release.set(); thread.join(2)

    def test_nonterminal_invalidation_clears_existing_refs(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            adapter.invalidate_snapshot()
            with self.assertRaises(CdpError) as error: adapter.execute('cdp-click', args)
            self.assertEqual(error.exception.code, 'stale_snapshot')
            self.assertEqual(adapter.execute('cdp-detect')['status'], 'ok')

    def test_per_call_deadline_includes_waiting_for_execution_slot(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, allow_live_control=True)
            args = self.observe(adapter)
            state.block_method = 'DOM.describeNode'
            thread, outcome = self.start_action(adapter, 'cdp-click', args)
            try:
                self.assertTrue(state.blocked.wait(1))
                started = time.monotonic()
                with self.assertRaises(CdpError) as error:
                    adapter.execute('cdp-detect', timeout_s=.05)
                self.assertEqual(error.exception.code, 'cdp_timeout')
                self.assertLess(time.monotonic() - started, .3)
            finally:
                adapter.close(); state.release.set(); thread.join(2)

    def test_per_call_timeout_is_a_positive_cap(self):
        with server() as (state, endpoint):
            adapter = CdpAdapter(endpoint, timeout_s=5)
            for bad in (0, -1, float('inf'), float('nan'), True, '1', 10**9999):
                with self.assertRaises(CdpError): adapter.execute('cdp-detect', timeout_s=bad)
            self.assertEqual(state.paths, [])
            self.assertEqual(adapter.execute('cdp-detect', timeout_s=100)['status'], 'ok')
            state.delay = .15
            started = time.monotonic()
            with self.assertRaises(CdpError): adapter.execute('cdp-detect', timeout_s=.05)
            self.assertLess(time.monotonic() - started, .3)


if __name__ == '__main__': unittest.main()
