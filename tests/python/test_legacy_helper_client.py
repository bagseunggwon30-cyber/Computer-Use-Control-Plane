"""Candidate-only helper reducers, closed routing, identity and race regressions.

All portable acquisitions are injected. Optional PS5 comparisons load exact
published AST extents into a counted safe driver; no original script top level,
real desktop, PID kill, auto-start or modern session is exercised.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_helper_client import (
    MAX_FRAME_BYTES, MAX_LOCK_BYTES, ChildResult, HelperClientError, HotCache,
    LegacyHelperClient, LegacyHelperRouter, LockSnapshot, child_envelope,
    frame_request, inspect_lock, legacy_environment_truth, parse_response,
    plan_route, read_lock_safely,
)

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def lock_bytes(**overrides):
    values = dict(pid=321, pipe_name='cucp-helper-321', started_at=NOW.isoformat(),
                  helper_version='2.0.0', owner_user='FixtureUser')
    values.update(overrides)
    return json.dumps(values).encode()


class FakeClock:
    def __init__(self):
        self.seconds = 0.0
        self.on_sleep = None
        self.sleeps = []

    def utcnow(self): return NOW + timedelta(seconds=self.seconds)
    def monotonic(self): return self.seconds
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.seconds += seconds
        if self.on_sleep:
            self.on_sleep(self.seconds)


class MemoryStore:
    """Atomic single-threaded fake; tests explicitly inject replacement races."""
    def __init__(self, raw=None):
        self.serial = 0
        self.snapshot = None
        self.deletes = []
        self.read_count = 0
        self.on_read = None
        self.before_delete = None
        if raw is not None:
            self.replace(raw)

    def replace(self, raw):
        self.serial += 1
        self.snapshot = LockSnapshot(raw, self.serial)

    def read(self):
        self.read_count += 1
        if self.on_read:
            self.on_read(self.read_count)
        return self.snapshot

    def compare_delete(self, expected):
        if self.before_delete:
            callback, self.before_delete = self.before_delete, None
            callback()
        self.deletes.append(expected)
        if self.snapshot == expected:
            self.snapshot = None
            return True
        return False


class FakeTransport:
    def __init__(self, response=None):
        self.calls = []
        self.response = response
        self.on_exchange = None

    def exchange(self, pipe_name, request, **timeouts):
        self.calls.append((pipe_name, request, timeouts))
        value = json.loads(request)
        if self.on_exchange:
            self.on_exchange()
        if isinstance(self.response, Exception):
            raise self.response
        if callable(self.response):
            return self.response(value)
        if self.response is not None:
            return self.response
        return json.dumps(dict(id=value['id'], exit_code=0,
                               result=dict(status='ok', uptime_s=7, request_count=11))).encode() + b'\n'


class OwnedFake:
    def __init__(self, pid=500):
        self.pid = pid
        self.kills = 0
    def terminate_owned(self): self.kills += 1


class Launcher:
    def __init__(self, pid=500):
        self.process = OwnedFake(pid)
        self.calls = []
    def launch(self, **kwargs):
        self.calls.append(kwargs)
        return self.process


class HelperChecks(unittest.TestCase):
    def client(self, *, raw=..., response=None, alive=True):
        store = MemoryStore(lock_bytes() if raw is ... else raw)
        clock, transport = FakeClock(), FakeTransport(response)
        probes = []
        def process_alive(pid):
            probes.append(pid)
            if isinstance(alive, Exception): raise alive
            return alive
        client = LegacyHelperClient(store=store, transport=transport, clock=clock,
                                    process_alive=process_alive, owner_user='FixtureUser')
        client.test_probes = probes
        return client

    def assert_code(self, code, callback):
        with self.assertRaises(HelperClientError) as context:
            callback()
        self.assertEqual(context.exception.code, code)


class LockReducerTests(HelperChecks):
    def test_missing_blank_malformed_nonobject_duplicate_oversize_and_unicode(self):
        for raw in (b'', b' ', b'{', b'null', b'[]', b'1', b'"x"', b'\xff',
                    b'{"pid":1,"pid":2}', b'x' * (MAX_LOCK_BYTES + 1)):
            with self.subTest(raw=raw[:30]):
                snapshot = LockSnapshot(raw, 1)
                self.assertIsNone(read_lock_safely(snapshot))
                self.assertEqual(self.client(raw=raw).state().kind, 'malformed')
        self.assertIsNone(read_lock_safely(None))
        self.assertEqual(self.client(raw=None).state().kind, 'missing')
        self.assertEqual(read_lock_safely(LockSnapshot(b'\xef\xbb\xbf' + lock_bytes(), 1))['pid'], 321)

    def test_valid_absent_owner_and_case_insensitive_legacy_owner_and_pipe(self):
        for owner in (None, '', 'FixtureUser', 'fixtureuser'):
            client = self.client(raw=lock_bytes(owner_user=owner, pipe_name='CUCP-HELPER-321'))
            self.assertTrue(client.state().usable)
            self.assertEqual(client.test_probes, [321])

    def test_foreign_owner_never_probes_pid_contacts_pipe_or_deletes(self):
        for owner in ('OtherUser', {'name': 'FixtureUser'}, 1, False):
            client = self.client(raw=lock_bytes(owner_user=owner))
            self.assertEqual(client.state().kind, 'foreign')
            self.assertFalse(client.status()['alive'])
            self.assertEqual(client.stop(force=True)['reason'], 'foreign_lock_ignored')
            launcher = Launcher()
            self.assertEqual(client.start(launcher)['reason'], 'foreign_lock_ignored')
            self.assertEqual(client.test_probes, [])
            self.assertEqual(client.store.deletes, [])
            self.assertEqual(client.transport.calls, [])
            self.assertEqual(launcher.calls, [])

    def test_strict_pid_invalid_names_dates_versions_are_fail_closed(self):
        values = [('pid', value) for value in (None, False, 0, -1, 1.2, '321', 2147483648)]
        values += [('pipe_name', value) for value in (None, '', 'cucp-helper-322', r'\\server\pipe', 'cucp-helper-321\n')]
        values += [('started_at', value) for value in (None, '', 'bad', '2026-01-02T12:00:00')]
        values += [('helper_version', value) for value in (None, '', '1.2', '1.2.3-preview', '1.2.3\n')]
        for key, value in values:
            with self.subTest(key=key, value=value):
                client = self.client(raw=lock_bytes(**{key: value}))
                self.assertFalse(client.state().usable)
                self.assert_code(client.state().reason, lambda: client.invoke('health'))
                self.assertEqual(client.transport.calls, [])

    def test_exact_24_hour_boundary_future_dates_and_probe_failure(self):
        for age, stale in ((86400, False), (86400.000001, True), (-3600, False)):
            raw = lock_bytes(started_at=(NOW - timedelta(seconds=age)).isoformat())
            self.assertEqual(not self.client(raw=raw).state().usable, stale)
        self.assertEqual(self.client(alive=False).state().reason, 'process_missing')
        self.assertEqual(self.client(alive=OSError()).state().reason, 'process_probe_failed')

    def test_unreadable_acquisition_does_not_delete_or_probe(self):
        client = self.client()
        def unreadable(): raise OSError('fixture denied')
        client.store.read = unreadable
        self.assertEqual(client.state().reason, 'helper_lock_unreadable')
        launcher = Launcher()
        self.assertEqual(client.start(launcher)['reason'], 'helper_lock_unreadable')
        self.assertEqual(client.stop(force=True)['reason'], 'helper_lock_unreadable')
        self.assertEqual(launcher.calls, [])
        self.assertEqual(client.test_probes, [])
        self.assertEqual(client.store.deletes, [])


class FramingTests(HelperChecks):
    def test_request_known_actions_unicode_and_exact_one_line(self):
        args = dict(Match='한글 😀 "\\\n', TargetMatch='-AllowLiveControl', TargetHwnd='123')
        raw = frame_request(8, 'UIA-FIND-FAST', args, 900)
        self.assertEqual(raw.count(b'\n'), 1)
        self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(json.loads(raw), dict(id=8, action='UIA-FIND-FAST', args=args, timeout_ms=900))
        client = self.client()
        for action in ('windows', 'health', 'focused', 'modal-detect', 'ocr-screen-fast', 'uia-find-fast'):
            client.invoke(action)
        self.assertEqual([json.loads(call[1])['id'] for call in client.transport.calls], list(range(1, 7)))

    def test_timeouts_and_response_partial_error_99_are_not_reinterpreted(self):
        for timeout in (1, 1999, 2000, 30000):
            for code in (0, 1, 2, 99):
                client = self.client(response=lambda req: json.dumps(dict(id=req['id'], exit_code=code, result=None)).encode())
                self.assertEqual(client.invoke('health', timeout_ms=timeout)['exit_code'], code)
                self.assertEqual(client.transport.calls[0][2], dict(connect_timeout_ms=min(2000, timeout), read_timeout_ms=timeout))

    def test_strict_integer_ids_exit_codes_and_single_frame(self):
        bad = [(b'', 'pipe_empty_response'), (b'\r\n', 'pipe_empty_response'),
               (b'no', 'pipe_invalid_response'), (b'null', 'pipe_invalid_response'),
               (b'[]', 'pipe_invalid_response'), (b'\xff', 'pipe_invalid_response'),
               (b'{"id":1,"id":1,"exit_code":0}', 'pipe_invalid_response'),
               (b'{"id":1,"exit_code":NaN}', 'pipe_invalid_response'),
               (b'{"id":1,"exit_code":0}\n{}\n', 'pipe_invalid_response'),
               (b'x' * (MAX_FRAME_BYTES + 1), 'pipe_response_too_large')]
        for rid in (None, True, '1', 1.0, 2):
            bad.append((json.dumps(dict(id=rid, exit_code=0)).encode(), 'pipe_id_mismatch'))
        for code in (None, True, '0', 0.0, 2147483648):
            bad.append((json.dumps(dict(id=1, exit_code=code)).encode(), 'pipe_invalid_exit_code'))
        for raw, code in bad:
            with self.subTest(code=code, raw=raw[:50]):
                self.assert_code(code, lambda: parse_response(raw, 1))
        self.assertEqual(parse_response(b'\xef\xbb\xbf{"id":1,"exit_code":0}\r\n', 1)['id'], 1)

    def test_no_arbitrary_command_input_mutation_or_shutdown_args(self):
        client = self.client()
        for action in ('click', 'type', 'powershell', 'exec', 'cdp-eval', '', '../health'):
            self.assert_code('unsupported_helper_action', lambda: client.invoke(action))
        for key in ('executable', 'script', 'expression', 'argv', 'text', 'Input'):
            self.assert_code('unsupported_helper_argument', lambda: client.invoke('windows', {key: 'inert'}))
        self.assert_code('unexpected_helper_argument', lambda: client.invoke('shutdown', {'Match': 'inert'}))
        self.assertEqual(client.store.read_count, 0)
        self.assertEqual(client.transport.calls, [])
        for value in (True, 0, -1, 1.5, '100', 2147483648):
            with self.assertRaises(ValueError): client.invoke('health', timeout_ms=value)

    def test_disconnect_timeout_and_malformed_response_are_never_replayed(self):
        for response, code in ((OSError('closed'), 'pipe_transport_error'),
                               (TimeoutError(), 'pipe_read_timeout'), (b'{', 'pipe_invalid_response')):
            client = self.client(response=response)
            self.assert_code(code, lambda: client.invoke('shutdown'))
            self.assertEqual(len(client.transport.calls), 1)
            self.assertEqual(client.store.deletes, [])

    def test_replaced_lock_even_identical_bytes_is_not_contacted(self):
        client = self.client()
        expected = client.state()
        client.store.replace(expected.snapshot.raw)
        self.assert_code('helper_lock_changed', lambda: client.invoke('shutdown', expected=expected))
        self.assertEqual(client.transport.calls, [])

    def test_failed_frame_consumes_id_and_request_counter_stays_correlated(self):
        client = self.client(response=b'{')
        self.assert_code('pipe_invalid_response', lambda: client.invoke('health'))
        client.transport.response = None
        self.assertEqual(client.invoke('health')['id'], 2)
        self.assertEqual([json.loads(call[1])['id'] for call in client.transport.calls], [1, 2])
        client._request_id = 2147483647
        self.assertEqual(client.invoke('health')['id'], 1)
        # Explicit candidate deviation: the transport combines connect/write,
        # so even a pre-write connection failure consumes the allocated ID.
        connect_failed = self.client(response=OSError('connection unavailable'))
        self.assert_code('pipe_transport_error', lambda: connect_failed.invoke('health'))
        connect_failed.transport.response = None
        self.assertEqual(connect_failed.invoke('health')['id'], 2)

    def test_nonfinite_exponents_are_rejected_at_every_response_depth(self):
        for payload in ('1e309', '-1e309', '{"x":1e309}', '[0,{"x":-1e309}]'):
            raw = ('{"id":1,"exit_code":0,"result":' + payload + ',"error":null}\n').encode()
            self.assert_code('pipe_invalid_response', lambda: parse_response(raw, 1))
            client = self.client(response=raw)
            self.assert_code('pipe_invalid_response', lambda: client.invoke('health'))
        normal = parse_response(b'{"id":1,"exit_code":0,"result":{"x":1e308}}\n', 1)
        self.assertEqual(normal['result']['x'], 1e308)

    def test_request_and_nonfinite_argument_bounds(self):
        self.assert_code('pipe_request_too_large', lambda: frame_request(1, 'windows', {'Match': 'x' * MAX_FRAME_BYTES}, 1))
        self.assert_code('invalid_helper_args', lambda: frame_request(1, 'windows', {'X': float('nan')}, 1))


class LifecycleTests(HelperChecks):
    def test_status_down_and_up_with_health_failed_is_legacy_lock_liveness(self):
        expected = dict(schema='cucp.helper-status/v1', alive=False, pid=None, pipe_name=None,
                        started_at=None, uptime_s=0, request_count=0, helper_version=None)
        self.assertEqual(self.client(raw=None).status(), expected)
        for response in (OSError('closed'), b'\n', b'{"id":1,"exit_code":1,"result":{"uptime_s":9}}'):
            status = self.client(response=response).status()
            self.assertTrue(status['alive'])
            self.assertEqual(status['pid'], 321)
            self.assertEqual(status['uptime_s'], 0)
        status = self.client().status()
        self.assertEqual((status['uptime_s'], status['request_count']), (7, 11))

    def test_status_lock_replacement_does_not_ping_new_server(self):
        client = self.client()
        client.store.on_read = lambda n: client.store.replace(lock_bytes()) if n == 2 else None
        self.assertTrue(client.status()['alive'])
        self.assertEqual(client.transport.calls, [])

    def test_start_reuses_without_ping_or_launch(self):
        client, launcher = self.client(), Launcher()
        value = client.start(launcher)
        self.assertTrue(value['reused'])
        self.assertEqual(value['pid'], 321)
        self.assertEqual(launcher.calls, [])
        self.assertEqual(client.transport.calls, [])

    def test_start_accepts_only_launched_pid_and_does_not_own_successful_service(self):
        client, launcher = self.client(raw=None), Launcher()
        def appear(seconds):
            client.store.replace(lock_bytes(pid=999 if seconds < .1 else 500,
                                            pipe_name='cucp-helper-999' if seconds < .1 else 'cucp-helper-500'))
        client.clock.on_sleep = appear
        value = client.start(launcher, idle_timeout_ms=1234)
        self.assertEqual(value['pid'], 500)
        self.assertFalse(value['reused'])
        self.assertEqual(launcher.calls, [dict(idle_timeout_ms=1234)])
        self.assertEqual(launcher.process.kills, 0)
        self.assertEqual(client.clock.seconds, .1)
        self.assertEqual(client.store.deletes, [])

    def test_start_timeout_terminates_owned_handle_only_and_preserves_replacement(self):
        for raw in (lock_bytes(pid=777, pipe_name='cucp-helper-777'), lock_bytes(owner_user='OtherUser'), b'{'):
            client, launcher = self.client(raw=None), Launcher()
            client.clock.on_sleep = lambda _seconds: client.store.replace(raw)
            self.assertEqual(client.start(launcher)['reason'], 'server_start_timeout')
            self.assertAlmostEqual(client.clock.seconds, 3)
            self.assertTrue(all(0 < n <= .05 for n in client.clock.sleeps))
            self.assertEqual(launcher.process.kills, 1)
            self.assertEqual(client.store.deletes, [])
            self.assertEqual(client.store.snapshot.raw, raw)
            self.assertEqual(client.transport.calls, [])

    def test_start_ready_at_deadline_and_after_deadline_are_distinct(self):
        for ready_at, success in ((3.0, True), (3.05, False)):
            client, launcher = self.client(raw=None), Launcher()
            def appear(seconds):
                if seconds >= ready_at:
                    client.store.replace(lock_bytes(pid=500, pipe_name='cucp-helper-500'))
            client.clock.on_sleep = appear
            self.assertEqual(client.start(launcher)['status'] == 'ok', success)
            self.assertEqual(launcher.process.kills, 0 if success else 1)
            self.assertAlmostEqual(client.clock.seconds, 3.0)

    def test_start_invalid_or_stale_same_pid_never_counts_as_ready(self):
        client, launcher = self.client(raw=None), Launcher()
        client.clock.on_sleep = lambda _: client.store.replace(lock_bytes(pid=500, pipe_name='bad'))
        self.assertEqual(client.start(launcher)['reason'], 'server_start_timeout')
        self.assertEqual(launcher.process.kills, 1)
        self.assertEqual(client.store.deletes, [])

    def test_start_stale_compare_delete_race_does_not_launch_or_delete_replacement(self):
        client, launcher = self.client(alive=False), Launcher()
        client.store.before_delete = lambda: client.store.replace(lock_bytes())
        value = client.start(launcher)
        self.assertEqual(value['reason'], 'helper_lock_changed_or_not_removable')
        self.assertEqual(launcher.calls, [])
        self.assertIsNotNone(client.store.snapshot)

    def test_start_malformed_lock_and_launch_failure_are_not_retried(self):
        client, launcher = self.client(raw=b'{'), Launcher()
        self.assertEqual(client.start(launcher)['reason'], 'helper_lock_malformed')
        self.assertEqual(launcher.calls, [])
        client = self.client(raw=None)
        def fail(**_): raise OSError('owned launcher failure')
        launcher.launch = fail
        with self.assertRaisesRegex(OSError, 'owned launcher failure'): client.start(launcher)
        self.assertEqual(client.store.deletes, [])

    def test_stop_missing_stale_never_contacts_and_force_never_kills_pid(self):
        for force in (False, True):
            client = self.client(raw=None)
            self.assertEqual(client.stop(force=force), dict(status='ok', reason='no_helper_running'))
            client = self.client(alive=False)
            self.assertEqual(client.stop(force=force), dict(status='ok', reason='stale_lock_removed', stopped_pid=None, forced=False))
            self.assertEqual(client.transport.calls, [])
            self.assertIsNone(client.store.snapshot)

    def test_stop_shutdown_ack_and_compare_delete_preserves_replacement(self):
        for replace in (False, True):
            client = self.client()
            if replace:
                # Even identical bytes from a replacement must survive cleanup.
                client.transport.on_exchange = lambda: client.store.replace(lock_bytes())
            result = client.stop(force=True)
            self.assertEqual(result, dict(status='ok', reason='shutdown_requested', stopped_pid=321, forced=False))
            self.assertEqual(len(client.transport.calls), 1)
            self.assertEqual(json.loads(client.transport.calls[0][1])['action'], 'shutdown')
            self.assertEqual(client.store.snapshot is not None, replace)

    def test_stop_failed_shutdown_never_deletes_kills_or_retries(self):
        responses = (b'', b' ', b'{', b'{"id":2,"exit_code":0}', OSError('disconnect'), TimeoutError())
        responses += tuple(json.dumps(dict(id=1, exit_code=code)).encode() for code in (1, 2, 99))
        for response in responses:
            client = self.client(response=response)
            result = client.stop(force=True)
            self.assertEqual(result['reason'], 'shutdown_not_acknowledged_no_pid_kill')
            self.assertFalse(result['forced'])
            self.assertIsNone(result['stopped_pid'])
            self.assertEqual(len(client.transport.calls), 1)
            self.assertEqual(client.store.deletes, [])


class RoutingTests(HelperChecks):
    def router(self, client=None, child=None):
        client = client or self.client(raw=None)
        calls = []
        def read(plan):
            calls.append(plan)
            return child or ChildResult(0, '{"status":"ok","windows":[]}', 'fixture-stderr', 9)
        router = LegacyHelperRouter(client, read)
        router.test_calls = calls
        return router

    def test_force_child_env_nonempty_string_truth_and_preserved_forwarding_omissions(self):
        argv = ['-action', 'UIA-FIND-FAST', '-Match', 'first', '-MATCH', 'second',
                '-TargetMatch', 'target', '-TargetHwnd', '7', '-Label', 'label',
                '-X', '10', '-Y', '20', '-W', '30', '-H', '40']
        for env in (None, '', '0', 'false', '1', ' '):
            plan = plan_route(argv, force_child_env=env)
            self.assertEqual(plan.pipe_eligible, not bool(env))
            self.assertEqual(plan.forwarded_args, dict(Match='first', TargetMatch='target', TargetHwnd='7'))
            self.assertIsNone(plan.hot_key)
            self.assertEqual(plan.argv, tuple(argv))
        self.assertFalse(plan_route(argv, force_child=True).pipe_eligible)
        self.assertTrue(legacy_environment_truth('0'))

    def test_missing_native_helper_returns_before_server_or_child_acquisition(self):
        router = self.router(self.client())
        self.assertEqual(router.invoke(['-Action', 'health'], native_helper_available=False),
                         dict(ExitCode=1, Json=None, Raw='', Err='native_helper_missing', ElapsedMs=0))
        self.assertEqual(router.client.store.read_count, 0)
        self.assertEqual(router.client.transport.calls, [])
        self.assertEqual(router.test_calls, [])

    def test_direct_pipe_keeps_label_crop_fields_while_wrapper_omits_them(self):
        client = self.client()
        args = dict(Match='app', Label='찾기 😀', X=1, Y=2, W=3, H=4)
        client.invoke('ocr-screen-fast', args)
        self.assertEqual(json.loads(client.transport.calls[0][1])['args'], args)
        router = self.router(client)
        router.invoke(['-Action', 'ocr-screen-fast', '-Match', 'app', '-Label', '찾기 😀',
                       '-X', '1', '-Y', '2', '-W', '3', '-H', '4'])
        self.assertEqual(json.loads(client.transport.calls[1][1])['args'], dict(Match='app'))

    def test_pipe_failure_removes_only_same_acquisition_when_now_stale(self):
        client = self.client(response=OSError('disconnected'))
        client.transport.on_exchange = lambda: setattr(client, 'process_alive', lambda _pid: False)
        router = self.router(client)
        self.assertEqual(router.invoke(['-Action', 'windows'])['Route'], 'child')
        self.assertEqual(len(client.store.deletes), 1)
        self.assertIsNone(client.store.snapshot)
        client = self.client(response=OSError('disconnected'))
        def replaced():
            client.store.replace(lock_bytes())
            client.process_alive = lambda _pid: False
        client.transport.on_exchange = replaced
        router = self.router(client)
        self.assertEqual(router.invoke(['-Action', 'windows'])['Route'], 'child')
        self.assertEqual(client.store.deletes, [])
        self.assertIsNotNone(client.store.snapshot)

    def test_route_invalid_argv_and_mutations_never_execute(self):
        router = self.router()
        for argv in (None, [], ['-Action'], ['windows', 'x'], ['-Action', ''], ['-Action', 1]):
            with self.assertRaises(ValueError): plan_route(argv)
        for action in ('shutdown', 'type', 'exec', 'cdp-eval'):
            plan = plan_route(['-Action', action])
            self.assertFalse(plan.pipe_eligible)
            self.assert_code('unsupported_read_acquisition', lambda: router.invoke(['-Action', action]))
        self.assertEqual(router.test_calls, [])
        self.assertEqual(router.client.transport.calls, [])

    def test_nonfinite_pipe_result_is_read_failure_not_uncaught_serializer_error(self):
        client = self.client(response=b'{"id":1,"exit_code":0,"result":{"x":1e309}}\n')
        router = self.router(client)
        result = router.invoke(['-Action', 'health'])
        self.assertEqual(result['Route'], 'child')
        self.assertEqual(len(router.test_calls), 1)

    def test_pipe_precedes_hot_cache_and_pipe_response_is_not_cached(self):
        router = self.router(self.client())
        for _ in range(2):
            self.assertEqual(router.invoke(['-Action', 'windows'])['Route'], 'pipe')
        self.assertEqual(len(router.client.transport.calls), 2)
        self.assertEqual(router.test_calls, [])
        self.assertEqual(router.cache.entries, {})
        router.client.store.snapshot = None
        self.assertEqual(router.invoke(['-Action', 'windows'])['Route'], 'child')
        router.client.store.replace(lock_bytes())
        self.assertEqual(router.invoke(['-Action', 'windows'])['Route'], 'pipe')

    def test_99_falls_back_but_partial_and_error_return_pipe_without_child(self):
        for code in (0, 1, 2, 99):
            client = self.client(response=lambda req: json.dumps(dict(id=req['id'], exit_code=code,
                result=dict(status='partial'), error='fixture')).encode())
            router = self.router(client)
            result = router.invoke(['-Action', 'windows'])
            if code == 99:
                self.assertEqual(result['Route'], 'child')
                self.assertEqual(len(router.test_calls), 1)
            else:
                self.assertEqual((result['ExitCode'], result['Route'], result['Err']), (code, 'pipe', 'fixture'))
                self.assertEqual(router.test_calls, [])

    def test_pipe_failure_read_fallback_once_and_replacement_never_deleted(self):
        for response in (b'', b'{', b'{"id":9,"exit_code":0}', OSError('disconnect'), TimeoutError()):
            client = self.client(response=response)
            client.transport.on_exchange = lambda: client.store.replace(lock_bytes(owner_user='OtherUser'))
            router = self.router(client)
            self.assertEqual(router.invoke(['-Action', 'windows'])['Route'], 'child')
            self.assertEqual(len(router.test_calls), 1)
            self.assertEqual(client.store.deletes, [])

    def test_force_child_still_uses_hot_cache_and_nonempty_disable_env_disables(self):
        router = self.router(self.client())
        self.assertEqual(router.invoke(['-Action', 'health'], force_child=True)['Route'], 'child')
        self.assertEqual(router.invoke(['-Action', 'health'], force_child=True)['Route'], 'hot-cache')
        self.assertEqual(router.client.transport.calls, [])
        for env in ('0', 'false', '1'):
            self.assertEqual(router.invoke(['-Action', 'health'], force_child=True, hot_cache_disable_env=env)['Route'], 'child')
        self.assertEqual(router.invoke(['-Action', 'health'], force_child=True, cache_seconds=0)['Route'], 'child')

    def test_hot_ttl_boundary_case_insensitive_keys_stats_and_limit(self):
        router = self.router()
        first = router.invoke(['-Action', 'windows', '-Match', 'Editor'])
        router.client.clock.seconds = .499
        hit = router.invoke(['-Action', 'WINDOWS', '-MATCH', 'EDITOR'])
        self.assertEqual(hit, dict(first, Err=None, ElapsedMs=0, FromHotCache=True, Route='hot-cache'))
        router.client.clock.seconds = .5
        self.assertEqual(router.invoke(['-Action', 'windows', '-Match', 'editor'])['Route'], 'child')
        self.assertEqual((router.cache.hits, router.cache.misses, router.cache.evictions), (1, 2, 1))
        for n in range(17):
            router.client.clock.seconds += .001
            router.invoke(['-Action', 'windows', '-Match', str(n)])
        self.assertEqual(len(router.cache.entries), 16)
        self.assertNotIn('windows|-match=0|', router.cache.entries)

    def test_child_partial_error_and_explicit_nonzero_omissions_timeout_launch(self):
        for raw, exit_code, expected in (('{"status":"partial"}', 0, 2), ('{"status":"ERROR"}', 0, 1),
                                         ('{"status":"partial"}', 37, 37), ('{', 0, 0), ('', 0, 0)):
            child = ChildResult(exit_code, raw, 'raw stderr', 3)
            router = self.router(child=child)
            result = router.invoke(['-Action', 'windows'])
            self.assertEqual(result['ExitCode'], expected)
            self.assertEqual(result['Raw'], raw)
            self.assertEqual(result['Err'], 'raw stderr')
            self.assertEqual(router.cache.entries, {})
        result = child_envelope(ChildResult(0, 'partial stdout', 'TIMEOUT after 4ms', 4, timed_out=True))
        self.assertEqual(result, dict(ExitCode=124, Json=None, Raw='', Err='TIMEOUT after 4ms', ElapsedMs=4))
        result = child_envelope(ChildResult(0, '', launch_error='fixture launch failed'))
        self.assertEqual(result['Route'], 'child-error')

    def test_cache_powershell_object_and_array_truthiness(self):
        for value, cached in (({}, True), ([], False), ([0], False), ([None], False), ([{}], True), ([0, 0], True), (False, False)):
            cache = HotCache()
            cache.put('fixture', 0, dict(ExitCode=0, Json=value))
            self.assertEqual(bool(cache.entries), cached, value)

    def test_timeout_defaults_and_no_ocr_uia_hot_cache(self):
        for timeout, expected in ((-1, 99), (0, 99), (23, 23)):
            self.assertEqual(plan_route(['-Action', 'windows'], timeout_ms=timeout, default_timeout_ms=99).timeout_ms, expected)
        for action in ('ocr-screen-fast', 'uia-find-fast'):
            router = self.router()
            self.assertEqual(router.invoke(['-Action', action])['Route'], 'child')
            self.assertEqual(router.invoke(['-Action', action])['Route'], 'child')
            self.assertEqual(len(router.test_calls), 2)


@unittest.skipUnless(sys.platform == 'win32', 'Original wrapper oracle requires Windows PowerShell 5.1')
class OriginalHelperClientOracleTests(unittest.TestCase):
    def test_original_wrapper_routes_and_lock_reducers(self):
        from helper_process_evidence import run_evidence, require_success
        from test_legacy_helper_source import published_source
        powershell = shutil.which('powershell.exe')
        self.assertIsNotNone(powershell, 'PS5 oracle qualification requires powershell.exe')
        with tempfile.TemporaryDirectory(prefix='CUCP helper wrapper oracle ') as temporary:
            root = Path(temporary)
            logs = Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR', root / 'evidence'))
            source = root / 'published-wrapper.ps1'
            source.write_bytes(published_source('scripts/cucp.ps1', logs))
            fixtures = oracle_cases()
            inputs = root / 'inputs.json'
            inputs.write_text(json.dumps(fixtures), encoding='utf-8-sig')
            result = run_evidence([powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                   '-File', str(ROOT / 'tests/fixtures/legacy-helper-client-oracle.ps1'),
                                   '-Source', str(source), '-Manifest', str(ROOT / 'tests/fixtures/legacy-helper/source-manifest.json'),
                                   '-Inputs', str(inputs), '-Work', str(root)], cwd=root,
                                  directory=logs, label='original-client-oracle', timeout=60)
            require_success(result)
            rows = json.loads(result['stdout'].decode('utf-8-sig'))
            self.assertEqual(len(rows), len(fixtures))
            for fixture, row in zip(fixtures, rows):
                with self.subTest(case=fixture['id']):
                    self.assertEqual(row, fixture['expected'])
                    self.assertEqual(row, candidate_oracle_case(fixture))


def oracle_cases():
    """Exact legacy compatibility subset; corrections are tested separately above."""
    cases = []
    for force in (False, True):
        for env in ('', '0', 'false'):
            for code in (0, 1, 2, 99):
                pipe = not force and not env and code != 99
                args = ['-Action', 'uia-find-fast', '-Match', 'first', '-Match', 'second',
                        '-TargetMatch', 'target', '-TargetHwnd', '7', '-Label', 'omitted', '-X', '1', '-Y', '2', '-W', '3', '-H', '4']
                cases.append(dict(id=f'route-{force}-{env}-{code}', mode='route', argv=args,
                                  force_child=force, force_env=env, hot_disable='', cache_seconds=2,
                                  response=dict(exit_code=code, result=dict(status='partial'), error='fixture'),
                                  child_raw='{"status":"partial"}', child_exit=0,
                                  expected=dict(route='pipe' if pipe else 'child', exit_code=code if pipe else 2,
                                                pipe_calls=1 if not force and not env else 0,
                                                child_calls=0 if pipe else 1,
                                                forwarded=dict(Match='first', TargetMatch='target', TargetHwnd='7') if not force and not env else None)))
    for raw, stale in ((None, True), (json.loads(lock_bytes(owner_user=None)), False),
                       (json.loads(lock_bytes(owner_user='DifferentUser')), True),
                       (json.loads(lock_bytes(pipe_name='wrong')), True),
                       (json.loads(lock_bytes(helper_version='1.2')), True),
                       (json.loads(lock_bytes(started_at=(NOW - timedelta(days=2)).isoformat())), True)):
        cases.append(dict(id=f'lock-{len(cases)}', mode='lock', lock=raw,
                          expected=dict(stale=stale)))
    valid = json.loads(lock_bytes(owner_user=None))
    valid['started_at'] = '2026-01-02T12:00:00Z'
    down = dict(schema='cucp.helper-status/v1', alive=False, pid=None, pipe_name=None,
                started_at=None, uptime_s=0, request_count=0, helper_version=None)
    up = dict(down, alive=True, pid=321, pipe_name='cucp-helper-321',
              started_at=valid['started_at'], helper_version='2.0.0')
    for current, response, expected in ((None, None, down), (valid, dict(exit_code=1), up),
            (valid, dict(exit_code=0, result=dict(uptime_s=7, request_count=11)), dict(up, uptime_s=7, request_count=11))):
        cases.append(dict(id=f'status-{len(cases)}', mode='status', lock=current, response=response, expected=expected))
    for current, alive, pipe_error, response, expected in (
        (None, True, False, None, dict(status='ok', reason='no_helper_running')),
        (valid, False, False, None, dict(status='ok', reason='stale_lock_removed', stopped_pid=None, forced=False)),
        (valid, True, False, dict(exit_code=0), dict(status='ok', reason='shutdown_requested', stopped_pid=321, forced=False)),
        (valid, True, True, None, dict(status='error', reason='shutdown_not_acknowledged_no_pid_kill', stopped_pid=None, forced=False)),
        (valid, True, False, dict(exit_code=99), dict(status='error', reason='shutdown_not_acknowledged_no_pid_kill', stopped_pid=None, forced=False))):
        cases.append(dict(id=f'stop-{len(cases)}', mode='stop', lock=current, alive=alive,
                          force=True, pipe_error=pipe_error, response=response, expected=expected))
    for reused in (False, True):
        ready = dict(valid, pid=500, pipe_name='cucp-helper-500')
        result = dict(status='ok', reused=reused, pid=321 if reused else 500,
                      pipe_name='cucp-helper-321' if reused else 'cucp-helper-500', started_at=valid['started_at'])
        cases.append(dict(id=f'start-{reused}', mode='start', lock=valid if reused else None,
                          ready_lock=ready, appear_tick=2, expected=dict(result=result, launches=0 if reused else 1, owned_kills=0)))
    return cases


def candidate_oracle_case(fixture):
    if fixture['mode'] == 'lock':
        raw = None if fixture['lock'] is None else json.dumps(fixture['lock']).encode()
        client = HelperChecks().client(raw=raw)
        return dict(stale=not client.state().usable)
    if fixture['mode'] in {'status', 'stop', 'start'}:
        raw = None if fixture['lock'] is None else json.dumps(fixture['lock']).encode()
        response = OSError('fixture pipe failure') if fixture.get('pipe_error') else lambda request: json.dumps(dict(fixture['response'] or {}, id=request['id'])).encode()
        client = HelperChecks().client(raw=raw, alive=fixture.get('alive', True), response=response)
        if fixture['mode'] == 'status': return client.status()
        if fixture['mode'] == 'stop': return client.stop(force=fixture['force'])
        launcher = Launcher()
        def appear(_seconds):
            if len(client.clock.sleeps) >= fixture['appear_tick']:
                client.store.replace(json.dumps(fixture['ready_lock']).encode())
        client.clock.on_sleep = appear
        result = client.start(launcher, idle_timeout_ms=1234)
        return dict(result=result, launches=len(launcher.calls), owned_kills=launcher.process.kills)
    client = HelperChecks().client(response=lambda request: json.dumps(dict(fixture['response'], id=request['id'])).encode())
    calls = []
    def child(plan):
        calls.append(plan)
        return ChildResult(fixture['child_exit'], fixture['child_raw'])
    router = LegacyHelperRouter(client, child)
    result = router.invoke(fixture['argv'], force_child=fixture['force_child'], force_child_env=fixture['force_env'],
                           hot_cache_disable_env=fixture['hot_disable'], cache_seconds=fixture['cache_seconds'], timeout_ms=1000)
    forwarded = json.loads(client.transport.calls[0][1])['args'] if client.transport.calls else None
    return dict(route=result['Route'], exit_code=result['ExitCode'], pipe_calls=len(client.transport.calls),
                child_calls=len(calls), forwarded=forwarded)


class CandidateOracleCorpusTests(unittest.TestCase):
    def test_all_original_driver_vectors_also_exercise_candidate(self):
        for fixture in oracle_cases():
            with self.subTest(case=fixture['id']):
                self.assertEqual(candidate_oracle_case(fixture), fixture['expected'])


if __name__ == '__main__':
    unittest.main()
