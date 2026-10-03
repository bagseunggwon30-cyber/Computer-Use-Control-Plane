"""Strict framing, ownership and no-replay tests using disposable owned workers."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_host_protocol import (Authority, Effect, LegacyHostError, CHUNK_BYTES,
    completion, frames, parse_json, unwire, wire)
from pcucp_cli.legacy_host_session import LegacyEffectSession, _coordinator_argv


def descriptor(kind='Diagnostic', name='ReadLines', data=None, **kwargs):
    return dict(kind=kind, name=name, argv=[], data=wire(data), live=False, quiet=False,
                brief=False, confirm_sensitive=False, **kwargs)


class CodecTests(unittest.TestCase):
    def test_shapes_are_preserved_without_value_count_unwrapping(self):
        for value in (None, [], [None], [1], [[None]], {}, {'value': [1], 'Count': 1},
                      {'a': [], 'b': [None], 'c': '한글😀'}, False, 0, -1, 1.2):
            with self.subTest(value=value):
                self.assertEqual(unwire(wire(value)), value)

    def test_reject_duplicate_unknown_and_malformed_values(self):
        values = [dict(kind='scalar', value={}, extra=1), dict(kind='array', items={}),
                  dict(kind='object', properties=[dict(name='x', value=wire(1)), dict(name='x', value=wire(2))]),
                  dict(kind='object', properties=[dict(name='x', value=wire(1)), dict(name='X', value=wire(2))]),
                  dict(kind='call', name='arbitrary'), dict(kind='scalar', value=float('inf'))]
        for value in values:
            with self.subTest(value=value), self.assertRaises(LegacyHostError):
                unwire(value)
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '\ufeff{}', '{'):
            with self.subTest(raw=raw), self.assertRaises(LegacyHostError):
                parse_json(raw)

    def test_byte_ingress_accepts_only_strict_utf8_without_bom(self):
        self.assertEqual(parse_json('{"x":"한글"}'.encode('utf-8')), {'x': '한글'})
        for raw in ('{}'.encode('utf-16'), '{}'.encode('utf-32'), '{}'.encode('utf-8-sig'),
                    b'\xff{}', bytearray(b'\xef\xbb\xbf{}')):
            with self.subTest(raw=raw), self.assertRaises(LegacyHostError):
                parse_json(raw)

    def test_chunks_reassemble_utf8_payload_without_truncation(self):
        value = {'large': '한글😀' * 100000}
        encoded = frames(value, 4)
        chunks = [json.loads(line) for line in encoded]
        raw = b''.join(base64.b64decode(part['data']) for part in chunks[:-1])
        self.assertEqual(parse_json(raw), value)
        self.assertTrue(all(len(base64.b64decode(part['data'])) <= CHUNK_BYTES for part in chunks[:-1]))
        self.assertEqual(chunks[-1], {'kind': 'end', 'id': 4})

    def test_authority_immutable_exact_booleans_and_child_intersection(self):
        ceiling = Authority(True, True)
        self.assertEqual(ceiling.restrict(False, False), Authority())
        with self.assertRaises(Exception):
            ceiling.live = False
        for values in ((1, False), (False, 'true'), (None, None)):
            with self.subTest(values=values), self.assertRaises(LegacyHostError):
                Authority(*values)
        for values in ((True, False), (False, True)):
            with self.assertRaises(LegacyHostError):
                Authority().restrict(*values)

    def test_effect_fields_ceiling_and_types_rejected(self):
        effect = descriptor()
        self.assertEqual(Effect.decode(effect, Authority()).argv, ())
        for changes in ({'kind': 'Script'}, {'name': 3}, {'argv': [None]}, {'live': 1},
                        {'live': True}, {'confirm_sensitive': True}, {'extra': None}):
            with self.subTest(changes=changes), self.assertRaises(LegacyHostError):
                Effect.decode({**effect, **changes}, Authority())

    def test_outcome_classification_matches_retained_semantics(self):
        for kind in ('Child', 'Native', 'HistoryAppend', 'TrajectoryAppend', 'RemoveFile', 'PointCacheWrite',
                     'AnchorAppend', 'Appshot', 'Vision', 'Notice', 'Cucp'):
            self.assertTrue(Effect.decode(descriptor(kind=kind), Authority()).may_change_state())
        for name in ('AuditProbe', 'ClearAppshotCache', 'Appshot', 'Notice', 'HelperUp', 'AssertAuthorized', 'Cli', 'Native'):
            self.assertTrue(Effect.decode(descriptor(name=name), Authority()).may_change_state())
        self.assertFalse(Effect.decode(descriptor(kind='LocalMacro', name='icon-find'), Authority()).may_change_state())
        self.assertFalse(Effect.decode(descriptor(), Authority()).may_change_state())

    def test_completion_int32_boolean_and_shape_boundaries(self):
        value = dict(payload=wire({'x': [None]}), exit=0, json_depth=6, brief='ok', emit_json=False)
        self.assertEqual(completion(value, 'diagnostics')['payload'], {'x': [None]})
        for changes in ({'exit': True}, {'exit': 4}, {'json_depth': -1}, {'json_depth': 101},
                        {'emit_json': 0}, {'brief': []}, {'other': 3}):
            with self.subTest(changes=changes), self.assertRaises(LegacyHostError):
                completion({**value, **changes}, 'diagnostics')
        self.assertEqual(completion({**value, 'exit': -5}, 'interaction')['exit'], -5)


class Provider:
    def __init__(self, *, kind='Console', fail=None):
        self.kind, self.calls, self.fail = kind, [], fail

    def validate_startup(self, family, startup, authority):
        pass

    def validate(self, effect):
        if effect.kind != self.kind:
            raise LegacyHostError('unqualified provider')

    def dispatch(self, effect):
        self.calls.append(effect)
        if self.fail:
            raise self.fail
        return {'value': [None], 'Count': 1}

    def validate_completion(self, result):
        pass


FIXTURE = r'''
import base64,json,os,sys,time
mode=sys.argv[1]
def emit(target,id,value):
 data=json.dumps(value,separators=(',',':')).encode()
 print(json.dumps(dict(kind='part',target=target,id=id,data=base64.b64encode(data).decode())),flush=True)
 print(json.dumps(dict(kind='end',target=target,id=id)),flush=True)
def read():
 while True:
  row=json.loads(sys.stdin.readline())
  if row['kind']=='end':return
read()
effect=dict(kind='Child' if mode.startswith('state') else 'Console',name='',argv=[],data=dict(kind='scalar',value=None),live=False,quiet=False,brief=False,confirm_sensitive=False)
if mode=='wrong-id':emit('effect',2,effect);sys.exit(1)
if mode=='forged-live':effect['live']=True
if mode=='unexpected':effect['kind']='WorkflowPlan'
if mode=='duplicate':
 print('{"kind":"part","kind":"part","target":"effect","id":1,"data":"e30="}',flush=True);sys.exit(1)
if mode=='oversize':print('x'*66001,flush=True);sys.exit(1)
if mode=='stderr':sys.stderr.write('x'*70000);sys.stderr.flush();time.sleep(30)
if mode=='truncated':sys.stdout.write('{');sys.stdout.flush();sys.exit(1)
emit('effect',1,effect)
read()
if mode in ('state-exit','exit'):sys.exit(7)
if mode in ('state-timeout','timeout'):time.sleep(30)
if mode=='error':emit('error',2,dict(message='declared error',mutation_may_have_occurred=True,automatic_retry=False));sys.exit(1)
if mode=='bad-retry':emit('error',2,dict(message='declared error',mutation_may_have_occurred=False,automatic_retry=True));sys.exit(1)
if mode=='inherited-pipes':
 import subprocess
 # Disposable controlled descendant. It self-expires; no user app is touched.
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)'],start_new_session=True)
 with open(sys.argv[2],'w') as marker:marker.write(str(child.pid))
emit('complete',2,dict(payload=dict(kind='scalar',value=None),exit=0,json_depth=6,brief='ok',emit_json=False))
if mode=='tail':emit('effect',3,effect)
if mode=='mismatch':sys.exit(4)
'''


class SessionTests(unittest.TestCase):
    def invoke(self, mode, provider=None, timeout=3):
        provider = provider or Provider()
        session = LegacyEffectSession(timeout_s=timeout)
        with tempfile.TemporaryDirectory(prefix='legacy-owned-worker-') as root:
            path = Path(root) / 'worker.py'
            path.write_text(FIXTURE)
            with patch('pcucp_cli.legacy_host_session._coordinator_argv', return_value=[sys.executable, str(path), mode]):
                result = session.run('diagnostics', {}, Authority(), provider)
        return result, session, provider

    def test_fixed_runtime_locator_rejects_shell_or_python_script_override(self):
        for command in (['/bin/bash'], [sys.executable, '/owned/script.py'], ['/owned/run.ps1'],
                        ['dotnet', '/owned/host.dll', 'extra']):
            with self.subTest(command=command), patch('pcucp_cli.legacy_host_session.native_host._native_argv',
                    return_value=(command, '')), self.assertRaisesRegex(LegacyHostError, 'never a script'):
                _coordinator_argv()
        for command in (['/owned/host.exe'], ['dotnet', '/owned/host.dll']):
            with patch('pcucp_cli.legacy_host_session.native_host._native_argv', return_value=(command, '')):
                self.assertEqual(_coordinator_argv(), command)

    def test_owned_process_round_trip_finishes_once(self):
        result, session, provider = self.invoke('normal')
        self.assertEqual(result['brief'], 'ok')
        self.assertEqual(session.dispatched, 1)
        self.assertEqual(len(provider.calls), 1)
        self.assertIsNotNone(session._process.poll())
        with self.assertRaisesRegex(LegacyHostError, 'single-attempt'):
            session.run('diagnostics', {}, Authority(), provider)

    def test_bad_frames_authority_and_policy_never_dispatch(self):
        for mode in ('wrong-id', 'forged-live', 'unexpected', 'duplicate', 'oversize', 'truncated', 'stderr'):
            provider = Provider()
            with self.subTest(mode=mode), self.assertRaises(LegacyHostError):
                self.invoke(mode, provider)
            self.assertEqual(provider.calls, [])

    def test_lost_final_outcome_and_timeout_never_replay(self):
        for mode in ('state-exit', 'state-timeout'):
            provider = Provider(kind='Child')
            with self.subTest(mode=mode), self.assertRaises(LegacyHostError) as failure:
                self.invoke(mode, provider, timeout=.3)
            self.assertTrue(failure.exception.uncertain)
            self.assertEqual(len(provider.calls), 1)

    def test_post_completion_extra_exit_mismatch_and_error_rejected(self):
        for mode in ('tail', 'mismatch', 'error', 'bad-retry', 'exit'):
            provider = Provider()
            with self.subTest(mode=mode), self.assertRaises(LegacyHostError):
                self.invoke(mode, provider)
            self.assertEqual(len(provider.calls), 1)

    @unittest.skipUnless(os.name == 'posix', 'Portable inherited-pipe ownership fixture')
    def test_inherited_pipe_does_not_make_cleanup_wait_for_unowned_descendant(self):
        provider, session = Provider(), LegacyEffectSession(timeout_s=2)
        with tempfile.TemporaryDirectory(prefix='legacy-pipe-owner-') as root:
            path = Path(root) / 'worker.py'; path.write_text(FIXTURE)
            marker = Path(root) / 'descendant.pid'
            started = time.monotonic()
            with patch('pcucp_cli.legacy_host_session._coordinator_argv',
                       return_value=[sys.executable, str(path), 'inherited-pipes', str(marker)]):
                with self.assertRaisesRegex(LegacyHostError, 'streams open'):
                    session.run('diagnostics', {}, Authority(), provider)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 3, 'Buffered close waited for a descendant-held pipe')
            self.assertEqual(len(provider.calls), 1)
            self.assertIsNotNone(session._process.poll())
            descendant = int(marker.read_text())
            # It must still be alive: cleanup may not kill outside its owner.
            os.kill(descendant, 0)
            # Wait only for this fixture's own self-expiring handle holders.
            for thread in session._threads:
                thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in session._threads))

    def test_signal_style_cancellation_keeps_possible_dispatch_metadata(self):
        provider = Provider(kind='Child', fail=KeyboardInterrupt('cancelled'))
        with self.assertRaises(KeyboardInterrupt) as failure:
            self.invoke('state-timeout', provider)
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(len(provider.calls), 1)

    def test_failed_reply_encoding_after_dispatch_preserves_uncertainty(self):
        class BadReply(Provider):
            def dispatch(self, effect):
                self.calls.append(effect)
                return {'bad': object()}
        provider = BadReply(kind='Child')
        with self.assertRaises(LegacyHostError) as failure:
            self.invoke('state-timeout', provider)
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(len(provider.calls), 1)

    def test_cancellation_stops_only_owned_worker_without_restart(self):
        provider, session, errors = Provider(kind='Child'), LegacyEffectSession(timeout_s=10), []
        with tempfile.TemporaryDirectory(prefix='legacy-cancel-') as root:
            path = Path(root) / 'worker.py'; path.write_text(FIXTURE)
            with patch('pcucp_cli.legacy_host_session._coordinator_argv', return_value=[sys.executable, str(path), 'state-timeout']):
                def run():
                    try: session.run('diagnostics', {}, Authority(), provider)
                    except Exception as error: errors.append(error)
                thread = threading.Thread(target=run); thread.start()
                deadline = time.monotonic() + 3
                while not provider.calls and time.monotonic() < deadline: time.sleep(.01)
                self.assertEqual(len(provider.calls), 1)
                session.close(); thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertTrue(errors[0].uncertain)
                self.assertIsNotNone(session._process.poll())
                self.assertEqual(len(provider.calls), 1)


if __name__ == '__main__':
    unittest.main()
