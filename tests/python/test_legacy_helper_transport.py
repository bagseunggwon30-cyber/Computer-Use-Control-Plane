"""Only newly launched owned detached services; no real desktop acquisition."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

from helper_process_evidence import OwnedProcess, run_evidence, require_success
from test_legacy_helper_source import ROOT, FIXTURES, published_source

HOST = os.environ.get('CUCP_LEGACY_HELPER_TEST_HOST', '')
PROBE = os.environ.get('CUCP_LEGACY_HELPER_TRANSPORT_PROBE', '')
ENABLED = sys.platform == 'win32' and HOST and PROBE


@unittest.skipUnless(ENABLED, 'Requires Windows net48 owned helper service/probe builds')
class HelperTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='CUCP helper owned 한글 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', self.root / 'evidence'))
        self.owned = []
        self.addCleanup(self.cleanup_owned)

    def cleanup_owned(self):
        for process in self.owned:
            # Only retained handles returned by these fixtures. Never a lock PID.
            if process.process and process.process.poll() is None:
                process.process.kill()
            process.finish(self.logs, 'owned-final', timeout=3)

    def start(self, *, idle_ms=4000, original=False, wait=True, fixture=None):
        lock = self.root / f'owned-{len(self.owned)}.pid'
        if original:
            source = self.root / 'published-server.ps1'
            source.write_bytes(published_source('scripts/cucp-helper-server.ps1', self.logs))
            argv = [shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                    '-File', str(source), '-LockFile', str(lock), '-IdleTimeoutMs', str(idle_ms)]
        else:
            argv = [HOST, 'serve', '--lock-file', str(lock), '--idle-timeout-ms', str(idle_ms), '--diagnostic-phases', '--diagnostic-acl']
            if fixture is not None:
                path = self.root / 'server-fixture.json'
                path.write_text(json.dumps(fixture), encoding='utf-8')
                argv += ['--fixture', str(path)]
        owned = OwnedProcess(argv, cwd=self.root)
        self.owned.append(owned)
        owned.snapshot(self.logs, 'server-started')
        if wait:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    data = json.loads(lock.read_text(encoding='utf-8-sig'))
                    if data['pid'] == owned.process.pid:
                        owned.snapshot(self.logs, 'server-ready')
                        return owned, lock, data
                except (OSError, json.JSONDecodeError):
                    pass
                if owned.process is None or owned.process.poll() is not None:
                    break
                time.sleep(.02)
            evidence = owned.finish(self.logs, 'startup-failure', timeout=.1)
            self.fail(f'Owned service did not publish matching lock: {evidence["evidence_path"]}')
        return owned, lock, None

    def probe(self, data, frames, **extra):
        spec = self.root / 'probe.json'
        spec.write_text(json.dumps(dict(pipe=data['pipe_name'], frames=frames, **extra)), encoding='utf-8')
        evidence = run_evidence([PROBE, str(spec)], directory=self.logs, label='probe', cwd=self.root, timeout=10)
        for process in self.owned:
            process.snapshot(self.logs, 'server-after-probe')
        require_success(evidence)
        return json.loads(evidence['stdout'].decode('utf-8-sig'))

    def finish(self, process, label='server'):
        evidence = process.finish(self.logs, label, timeout=6)
        require_success(evidence)
        return evidence

    def test_unmodified_published_original_startup_baseline_defect(self):
        from helper_baseline_observation import classify_original_startup, save_classification
        # Under the reviewed functional criterion, this exact historical crash
        # is a visible failed oracle observation, not a required candidate crash.
        # Any other failure or remaining process/lock is still a gate failure.
        owned, lock, _ = self.start(original=True, wait=False)
        evidence = owned.finish(self.logs, 'published-original-startup-observation', timeout=5)
        value = classify_original_startup(evidence, source=self.root / 'published-server.ps1',
                                          lock=lock, process_returncode=owned.process.poll() if owned.process else None)
        classification_path = save_classification(value, evidence['evidence_path'])
        print(f'Original startup remains failed/unqualified; observed baseline defect: {classification_path}', flush=True)
        self.assertFalse(value['original_startup_qualified'])

    def test_multiple_requests_count_case_unknown_health_shutdown_and_timeout_ignored(self):
        owned, lock, data = self.start()
        frames = [json.dumps(dict(id=n, action=action, args={}, timeout_ms=0))
                  for n, action in enumerate(['HEALTH', 'not-supported', 'health', 'shutdown'], 1)]
        rows = [json.loads(x['response']) for x in self.probe(data, frames)]
        self.assertEqual([r['id'] for r in rows], [1, 2, 3, 4])
        self.assertEqual([r['exit_code'] for r in rows], [0, 99, 0, 0])
        self.assertEqual(rows[0]['result']['request_count'], 1)
        self.assertEqual(rows[2]['result']['request_count'], 3)
        self.assertEqual(rows[0]['result']['pid'], owned.process.pid)
        self.assertFalse(rows[0]['result']['win32_loaded'])
        self.assertTrue(rows[3]['result']['shutting_down'])
        self.finish(owned)
        self.assertFalse(lock.exists())

    def test_actual_scripted_pipe_adapter_emits_error_partial_and_warm_state(self):
        calls = [dict(op='win32.ensure',args=[],result=None),dict(op='win32.foreground',args=[],result=0),
                 dict(op='uia.load',args=[],result=None)]
        owned, lock, data = self.start(fixture=dict(calls=calls))
        frames = [json.dumps(dict(id=n,action=a,args={})) for n,a in enumerate(['focused','uia-find-fast','health','shutdown'],1)]
        rows = [json.loads(x['response']) for x in self.probe(data,frames)]
        self.assertEqual([r['exit_code'] for r in rows],[2,1,0,0])
        self.assertEqual(rows[0]['result']['reason'],'no_foreground')
        self.assertEqual(rows[1]['result']['reason'],'missing_label')
        self.assertTrue(rows[2]['result']['win32_loaded'])
        self.finish(owned)

    def test_malformed_frame_keeps_connection_and_does_not_increment_count(self):
        owned, lock, data = self.start()
        rows = self.probe(data, ['{', '{"id":"한글😀","action":"health"}', '{"action":"shutdown"}'])
        malformed, health, shutdown = [json.loads(x['response']) for x in rows]
        self.assertEqual(malformed['exit_code'], 1)
        self.assertTrue(malformed['error'].startswith('invalid_json: '))
        self.assertIsNone(malformed['result'])
        self.assertEqual(health['id'], '한글😀')
        self.assertEqual(health['result']['request_count'], 1)
        self.assertIsNone(shutdown['id'])
        self.finish(owned)

    def test_blank_disconnect_and_successive_clients_share_detached_server(self):
        owned, lock, data = self.start()
        blank = self.probe(data, [''])
        self.assertIsNone(blank[0]['response'])
        first = self.probe(data, ['{"id":1,"action":"health"}'])
        second = self.probe(data, ['{"id":2,"action":"health"}', '{"action":"shutdown"}'])
        self.assertEqual(json.loads(first[0]['response'])['result']['request_count'], 1)
        self.assertEqual(json.loads(second[0]['response'])['result']['request_count'], 2)
        self.finish(owned)

    def test_idle_deadline_only_while_waiting_for_connection(self):
        owned, lock, data = self.start(idle_ms=1200)
        rows = self.probe(data, ['{"action":"health"}', '{"action":"shutdown"}'], hold_ms=1800)
        self.assertEqual(json.loads(rows[0]['response'])['exit_code'], 0)
        self.finish(owned)
        idle, idle_lock, _ = self.start(idle_ms=150)
        self.finish(idle, 'idle-exit')
        self.assertFalse(idle_lock.exists())

    def test_replacement_lock_survives_cleanup_even_if_pid_reused_in_content(self):
        owned, lock, data = self.start()
        replacement = self.root / 'replacement.pid'
        marker = dict(data, owner_user='owned-fixture-replacement', marker='do not delete')
        replacement.write_text(json.dumps(marker), encoding='utf-8')
        os.replace(replacement, lock)
        self.probe(data, ['{"action":"shutdown"}'])
        self.finish(owned)
        self.assertEqual(json.loads(lock.read_text()), marker)

    def test_existing_lock_is_never_overwritten(self):
        lock = self.root / 'exists.pid'
        lock.write_text('owned marker')
        result = run_evidence([HOST, 'serve', '--lock-file', str(lock)], directory=self.logs, label='existing-lock', timeout=5)
        require_success(result, expected_exit=1)
        self.assertEqual(lock.read_text(), 'owned marker')

    def test_python_client_reaches_actual_candidate_adapter_without_child(self):
        from datetime import datetime, timezone
        from pcucp_cli.legacy_helper_client import LegacyHelperClient, LegacyHelperRouter, LockSnapshot
        owned, lock, data = self.start()
        outer = self
        class Store:
            def read(self):
                try:
                    with lock.open('rb') as stream:
                        raw = stream.read()
                        stat = os.fstat(stream.fileno())
                    return LockSnapshot(raw, (stat.st_dev, stat.st_ino))
                except FileNotFoundError:
                    return None
            def compare_delete(self, expected):
                # Fixture leaves cleanup to the owned service; a pathname unlink
                # would not meet the runtime client's atomic-CAS contract.
                return False
        class Clock:
            def utcnow(self): return datetime.now(timezone.utc)
            def monotonic(self): return time.monotonic()
            def sleep(self, seconds): time.sleep(seconds)
        class Transport:
            def exchange(self, name, request, *, connect_timeout_ms, read_timeout_ms):
                path = outer.root / 'client-request.json'
                path.write_bytes(request)
                evidence = run_evidence([HOST, 'exchange', '--pipe', name, '--request-file', str(path),
                    '--connect-timeout-ms', str(connect_timeout_ms), '--read-timeout-ms', str(read_timeout_ms), '--diagnostic-phases'],
                    directory=outer.logs, label='python-actual-adapter', timeout=10)
                require_success(evidence)
                return evidence['stdout']
        client = LegacyHelperClient(store=Store(), transport=Transport(), clock=Clock(),
                    process_alive=lambda pid: pid == owned.process.pid and owned.process.poll() is None,
                    owner_user=data['owner_user'])
        def forbidden_child(plan): raise AssertionError('unplanned child acquisition')
        router = LegacyHelperRouter(client, forbidden_child)
        response = router.invoke(['-Action', 'health'], timeout_ms=1500)
        self.assertEqual(response['Route'], 'pipe')
        self.assertEqual(response['Json']['pid'], owned.process.pid)
        self.assertEqual(client.stop(force=True)['reason'], 'shutdown_requested')
        self.finish(owned)

    def peer_exchange(self, mode, request=b'{"id":1,"action":"health"}', *, timeout_ms=300, connect_ms=500, expected=0):
        ready = self.root / ('peer-ready-' + str(len(self.owned)) + '.json')
        spec = self.root / ('peer-spec-' + str(len(self.owned)) + '.json')
        spec.write_text(json.dumps(dict(mode=mode, ready=str(ready))), encoding='utf-8')
        peer = OwnedProcess([PROBE, 'peer', str(spec)], cwd=self.root)
        self.owned.append(peer)
        peer.snapshot(self.logs, 'peer-started')
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline and peer.process.poll() is None:
            time.sleep(.01)
        peer.snapshot(self.logs, 'peer-ready')
        self.assertTrue(ready.exists(), 'owned peer startup did not complete')
        data = json.loads(ready.read_text())
        self.assertEqual(data['pipe_name'], f'cucp-helper-{peer.process.pid}')
        path = self.root / 'hostile-peer-request.json'
        path.write_bytes(request)
        started = time.monotonic()
        result = run_evidence([HOST, 'exchange', '--pipe', data['pipe_name'], '--request-file', str(path),
                              '--connect-timeout-ms', str(connect_ms), '--read-timeout-ms', str(timeout_ms)],
                             directory=self.logs, label='hostile-peer-' + mode, timeout=5, limit=2*1024*1024)
        peer.snapshot(self.logs, 'peer-after-exchange')
        require_success(result, expected_exit=expected)
        self.assertLess(time.monotonic() - started, 3, 'adapter deadline did not bound the owned exchange')
        peer_result = peer.finish(self.logs, 'peer-finished', timeout=3)
        require_success(peer_result)
        self.assertLessEqual(peer_result['stdout'].count(b'peer_connected'), 1)
        self.assertLessEqual(peer_result['stdout'].count(b'peer_read_one_request'), 1)
        return result, peer_result

    def test_actual_exchange_write_and_read_deadlines_with_owned_stalled_peers(self):
        for mode, request, reason in [('stall-read', b'x'*(1024*1024-1), b'pipe_write_timeout'),
                                     ('stall-write', b'{}', b'pipe_read_timeout'),
                                     ('slow-drip', b'{}', b'pipe_read_timeout')]:
            with self.subTest(mode=mode):
                result, peer = self.peer_exchange(mode, request, expected=1)
                self.assertIn(reason, result['stderr'])
                self.assertEqual(peer['stdout'].count(b'peer_connected'), 1)

    def test_actual_exchange_oversize_rejects_before_unbounded_line_materialization(self):
        result, _ = self.peer_exchange('oversized', timeout_ms=1500, expected=1)
        self.assertIn(b'pipe_response_too_large', result['stderr'])
        self.assertEqual(result['stdout'], b'')
        for request in (b'x'*(1024*1024), b'x'*(2*1024*1024)):
            result, peer = self.peer_exchange('stall-read', request, expected=1)
            self.assertIn(b'pipe_request_too_large', result['stderr'])
            self.assertNotIn(b'peer_connected', peer['stdout'])

    def test_actual_exchange_utf8_split_exact_bound_and_eof_without_newline(self):
        for mode, expected in [('unicode-split', '한글😀\n'.encode()),
                               ('exact-boundary', b'x'*(1024*1024-1)+b'\n'),
                               ('unterminated', b'tail without newline\n')]:
            result, _ = self.peer_exchange(mode, timeout_ms=1500)
            self.assertEqual(result['stdout'], expected)
        result, _ = self.peer_exchange('invalid-utf8', expected=1)
        self.assertIn(b'DecoderFallbackException', result['stderr'])

    def test_actual_exchange_connect_and_invalid_timeout_bounds(self):
        result, _ = self.peer_exchange('absent', connect_ms=150, expected=1)
        self.assertIn(b'TimeoutException', result['stderr'])
        for connect, io in [(0,100),(-1,100),(100,0),(100,-1)]:
            result, peer = self.peer_exchange('stall-read', connect_ms=connect, timeout_ms=io, expected=1)
            self.assertNotIn(b'peer_connected', peer['stdout'])

    def test_same_file_bom_removal_or_encoding_rewrite_preserves_changed_lock(self):
        for encoding in ('utf-8-no-bom', 'utf-16'):
            with self.subTest(encoding=encoding):
                owned, lock, data = self.start()
                original = lock.read_bytes()
                self.assertTrue(original.startswith(b'\xef\xbb\xbf'))
                before = lock.stat()
                text = original.decode('utf-8-sig')
                changed = text.encode('utf-8') if encoding == 'utf-8-no-bom' else text.encode('utf-16')
                with lock.open('r+b') as stream:
                    stream.seek(0); stream.write(changed); stream.truncate()
                after = lock.stat()
                self.assertEqual((before.st_dev,before.st_ino), (after.st_dev,after.st_ino))
                self.probe(data, ['{"action":"shutdown"}'])
                self.finish(owned)
                self.assertEqual(lock.read_bytes(), changed)

    def test_closed_cli_options_reject_before_lock_creation(self):
        lock = self.root / 'must-not-exist.pid'
        for args in (["unknown"], ["serve", "--lock-file", str(lock), "--pipe-name", "other"],
                     ["serve", "--lock-file", str(lock), "--idle-timeout-ms", "-1"],
                     ["serve", "--lock-file", str(lock), "--lock-file", str(lock)]):
            with self.subTest(args=args):
                evidence = run_evidence([HOST, *args], directory=self.logs, label='closed-cli', timeout=5)
                require_success(evidence, expected_exit=1)
                self.assertFalse(lock.exists())

    def test_direct_invalid_envelopes_are_explicit_candidate_rejections(self):
        owned, lock, data = self.start()
        frames=['null','[]','7','{"id":1,"action":"health","args":[]}','{"id":2,"action":"health"}','{"action":"shutdown"}']
        rows=[json.loads(x['response']) for x in self.probe(data,frames)]
        self.assertEqual([r['exit_code'] for r in rows],[1,1,1,1,0,0])
        self.assertTrue(all(r['error'].startswith('invalid_json: ') for r in rows[:4]))
        self.assertEqual(rows[4]['result']['request_count'],1)
        self.finish(owned)

    def test_actual_candidate_exchange_cli(self):
        owned, lock, data = self.start()
        request = self.root / 'request.json'
        request.write_text('{"id":77,"action":"health","args":{}}')
        evidence = run_evidence([HOST, 'exchange', '--pipe', data['pipe_name'], '--request-file', str(request),
                                '--connect-timeout-ms', '1500', '--read-timeout-ms', '1500', '--diagnostic-phases'],
                                directory=self.logs, label='actual-client-adapter', timeout=8)
        owned.snapshot(self.logs, 'server-after-exchange')
        require_success(evidence)
        self.assertEqual(json.loads(evidence['stdout'].decode('utf-8-sig'))['id'], 77)
        self.probe(data, ['{"action":"shutdown"}'])
        service = self.finish(owned)
        for marker in (b'client.connect.complete', b'client.write.complete', b'client.read.complete'):
            self.assertIn(b'helper_phase=' + marker, evidence['stderr'])
        phases = service['stderr']
        self.assertLess(phases.index(b'helper_phase=request.read.complete'), phases.index(b'helper_phase=response.write.start'))
        self.assertIn(b'helper_phase=lock.cleanup.complete', phases)
        self.assertNotIn(b'ACL failed (continuing)', phases)
        descriptors = [json.loads(line.split('=',1)[1]) for line in phases.decode('utf-8').splitlines()
                       if line.startswith('helper_acl_evidence=')]
        self.assertGreaterEqual(len(descriptors), 1)
        for descriptor in descriptors:
            self.assert_owner_only_descriptor(descriptor, data['owner_sid'])

    def assert_owner_only_descriptor(self, value, owner):
        self.assertEqual(value['evidence_kind'], 'framework-normalized-descriptor')
        self.assertEqual(value['owner_sid'], owner)
        self.assertEqual(value['expected_user_sid'], owner)
        self.assertTrue(value['dacl_present'])
        self.assertFalse(value['dacl_null'])
        self.assertTrue(value['protected'])
        self.assertTrue(value['canonical'])
        self.assertEqual(len(value['aces']), 1)
        ace = value['aces'][0]
        self.assertEqual((ace['sid'], ace['type'], ace['flags']), (owner, 'AccessAllowed', 'None'))
        self.assertFalse(ace['callback'])
        self.assertEqual(ace['opaque_bytes'], 0)

    def test_owned_pipe_effective_acl_and_negative_descriptor_contracts(self):
        result = run_evidence([PROBE, 'acl-contracts'], directory=self.logs, label='owned-acl-contracts',
                              cwd=self.root, timeout=8)
        require_success(result)
        value = json.loads(result['stdout'].decode('utf-8-sig'))
        self.assertEqual(value['status'], 'ok')
        self.assertEqual(value['checks'], 27)
        self.assertEqual([x['kind'] for x in value['observations']],
                         ['legacy_default_read_only', 'candidate_creation_time_verified'])
        candidate = value['observations'][1]
        self.assert_owner_only_descriptor(candidate, value['current_user_sid'])
        self.assertEqual(candidate['aces'][0]['mask'], value['full_control_mask'])
        self.assertEqual(value['normalization_controls'],
                         ['ineffective leaf inheritance flags removed', 'compatible owner ACEs merged'])

    def handshake_pair(self, server_mode, client_mode, buffer_size):
        label = f'handshake-{server_mode}-{client_mode}-{buffer_size}'
        ready = self.root / (label + '-ready.json')
        server_spec = self.root / (label + '-server.json')
        server_spec.write_text(json.dumps(dict(mode=server_mode, buffer_size=buffer_size,
                                              ready=str(ready), connect_timeout_ms=2000)), encoding='utf-8')
        server = OwnedProcess([PROBE, 'handshake-server', str(server_spec)], cwd=self.root)
        self.owned.append(server)
        server.snapshot(self.logs, label + '-server-started')
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline and server.process and server.process.poll() is None:
            time.sleep(.01)
        server.snapshot(self.logs, label + '-server-ready')
        self.assertTrue(ready.exists(), 'owned handshake did not publish readiness')
        metadata = json.loads(ready.read_text(encoding='utf-8'))
        self.assertEqual(metadata['pipe_name'], f'cucp-helper-{server.process.pid}')
        self.assertEqual(metadata['pid'], server.process.pid)
        client_spec = self.root / (label + '-client.json')
        client_spec.write_text(json.dumps(dict(mode=client_mode, pipe=metadata['pipe_name'],
                                              server_pid=server.process.pid, connect_timeout_ms=2000)), encoding='utf-8')
        client = OwnedProcess([PROBE, 'handshake-client', str(client_spec)], cwd=self.root)
        self.owned.append(client)
        client.snapshot(self.logs, label + '-client-started')
        client_result = client.finish(self.logs, label + '-client', timeout=5)
        server_result = server.finish(self.logs, label + '-server', timeout=2)
        # Both terminal raw records exist first. A killed/timed-out process,
        # launch error or incomplete drain can never prove a reproduced stall.
        require_success(client_result)
        require_success(server_result)
        values = []
        for result, process, peer in ((server_result, server, client), (client_result, client, server)):
            value = json.loads(result['stdout'].decode('utf-8-sig'))
            self.assertEqual(value['pid'], process.process.pid)
            states = [json.loads(line.split('=', 1)[1]) for line in result['stderr'].decode('utf-8').splitlines()
                      if line.startswith('helper_handshake_state=')]
            connected = [state for state in states if state['peer_pid']]
            self.assertEqual(len(connected), 1)
            self.assertEqual(connected[0]['peer_pid'], peer.process.pid)
            self.assertTrue(connected[0]['is_async'])
            self.assertGreaterEqual(connected[0]['actual_in_buffer_bytes'], 0)
            self.assertGreaterEqual(connected[0]['actual_out_buffer_bytes'], 0)
            self.assertIn(b'helper_handshake_phase=connect_complete', result['stderr'])
            values.append(value)
        return values

    def test_owned_eager_and_deferred_preamble_handshake_controls(self):
        for server_mode, client_mode, buffers in [('eager','legacy',0), ('eager','bytes',0),
                                                  ('eager','legacy',512), ('lazy','legacy',0),
                                                  ('lazy','bytes',0), ('eager','drain-bom',0)]:
            with self.subTest(server=server_mode, client=client_mode, buffers=buffers):
                server, client = self.handshake_pair(server_mode, client_mode, buffers)
                if server_mode == 'lazy' or buffers == 512 or client_mode == 'drain-bom':
                    self.assertEqual([server['status'], client['status']], ['complete', 'complete'])
                    self.assertEqual([server['verified_frames'], client['verified_frames']], [1,1])
                elif server['status'] == client['status'] == 'complete':
                    # Default kernel buffers can differ. Record a working old
                    # handshake rather than manufacturing a deadlock verdict.
                    self.assertEqual([server['verified_frames'], client['verified_frames']], [1,1])
                else:
                    allowed = {'fixture_cancelled_pending_io', 'fixture_peer_closed_pending_io'}
                    self.assertIn(server['status'], allowed)
                    self.assertIn(client['status'], allowed)
                    self.assertTrue(server['deadline_expired'] or client['deadline_expired'])
                    self.assertEqual(server['pending_phase'], 'autoflush_begin')
                    self.assertIn(client['pending_phase'], {'autoflush_begin', 'request_write_begin', 'request_write_async_returned'})
                    self.assertEqual([server['verified_frames'], client['verified_frames']], [0,0])
