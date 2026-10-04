import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pcucp_cli import native_host
from pcucp_cli.native_session import NativeSession

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/native_session_host.py'

class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / 'requests.jsonl'

    def start(self, mode='ok', live=False):
        resolver = patch.object(native_host, '_native_argv', return_value=([sys.executable,str(FIXTURE),mode,str(self.log)],''))
        resolver.start()
        self.addCleanup(resolver.stop)
        worker = NativeSession(allow_live_control=live)
        self.addCleanup(worker.close)
        return worker

    def requests(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_lazily_reuses_same_native_process(self):
        worker = self.start()
        self.assertIsNone(worker.pid)
        first = worker('windows')
        second = worker('windows')
        self.assertEqual((first[0], second[0]), (0,0))
        self.assertEqual(first[1]['data']['pid'], second[1]['data']['pid'])
        self.assertEqual(len(self.requests()), 2)
        self.assertEqual(first[1]['route']['transport'], 'persistent-stdio')

    def test_authority_is_fixed_in_startup_arguments(self):
        worker = self.start(live=True)
        worker('windows')
        self.assertTrue(self.requests()[0]['live'])

    def test_concurrent_requests_are_serialized(self):
        worker = self.start('delay')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _:worker('windows'), range(4)))
        self.assertEqual([r[0] for r in results], [0]*4)
        self.assertEqual(len({r['pid'] for r in self.requests()}), 1)

    def test_partial_native_result_preserves_error_and_connection(self):
        worker = self.start('partial')
        a, b = worker('windows'), worker('windows')
        self.assertEqual(a[0], 3)
        self.assertEqual(b[1]['errors'][0]['code'], 'truncated')
        self.assertEqual(len(self.requests()), 2)

    def test_timeout_kills_and_poisons_without_replay(self):
        worker = self.start('hang')
        result = worker('click', ['--allow-live-control'], timeout_s=.2)
        self.assertEqual(result[0], 124)
        self.assertIn('not retried', result[2])
        self.assertIsNone(worker('click')[1])
        self.assertEqual(len(self.requests()), 1)
        self.assertIsNotNone(worker._process.poll())

    def test_protocol_failure_never_restarts(self):
        for mode in ('malformed','mismatch','exit'):
            with self.subTest(mode=mode):
                if self.log.exists(): self.log.unlink()
                worker = self.start(mode)
                self.assertIsNone(worker('windows')[1])
                self.assertIsNone(worker('windows')[1])
                self.assertEqual(len(self.requests()), 1)
                worker.close()

    def test_cancellation_interrupts_active_native_request(self):
        worker = self.start('hang')
        result = []
        thread = threading.Thread(target=lambda:result.append(worker('click', timeout_s=10)))
        thread.start()
        end = time.monotonic() + 2
        while (not self.log.exists() or not self.log.read_bytes().endswith(b'\n')) and time.monotonic() < end: time.sleep(.01)
        self.assertTrue(self.log.exists())
        worker.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(result[0][1])
        self.assertEqual(len(self.requests()), 1)
        self.assertNotIn(worker._process, native_host._PROCESSES)

    def test_global_cancellation_covers_resident_process(self):
        worker = self.start('hang')
        result = []
        thread = threading.Thread(target=lambda:result.append(worker('click', timeout_s=10)))
        thread.start()
        end = time.monotonic() + 2
        while (not self.log.exists() or not self.log.read_bytes().endswith(b'\n')) and time.monotonic() < end: time.sleep(.01)
        native_host.cancel_all_native()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(result[0][1])

    def test_stdout_and_stderr_bounds(self):
        for mode, constant in [('flood','MAX_STDOUT_BYTES'),('stderr','MAX_STDERR_BYTES')]:
            with self.subTest(mode=mode), patch.object(native_host, constant, 1024):
                worker = self.start(mode)
                result = worker('windows', timeout_s=2)
                self.assertIsNone(result[1])
                self.assertIn('size limit', result[2])
                worker.close()

    def test_close_is_idempotent_and_no_late_respawn(self):
        worker = self.start()
        worker('windows')
        worker.close()
        worker.close()
        self.assertIsNone(worker('windows')[1])
        self.assertEqual(len(self.requests()), 1)

    def test_rejects_invalid_request_before_launch(self):
        worker = self.start()
        for command,args,timeout in [('serve',[],1),('windows',['bad\0'],1),('windows',[],float('nan'))]:
            self.assertEqual(worker(command,args,timeout_s=timeout)[0], 2)
        self.assertIsNone(worker.pid)

class RealNativeSessionTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('CUCP_NATIVE_TEST_HOST'), 'Set CUCP_NATIVE_TEST_HOST to built native DLL/exe')
    def test_real_native_version_reuse_and_readonly_authority(self):
        with patch.dict(os.environ, CUCP_NATIVE_HOST=os.environ['CUCP_NATIVE_TEST_HOST']):
            with NativeSession() as worker:
                first, second = worker('version'), worker('version')
                self.assertEqual(first[0], 0, first[2])
                self.assertEqual(second[0], 0, second[2])
                self.assertEqual(first[1]['data']['process'], second[1]['data']['process'])
                # No real input: readonly native preflight must reject before any OS call.
                rejected = worker('click', ['--hwnd','0x1','--pid','1','--allow-live-control'])
                self.assertIsNone(rejected[1])
                self.assertIsNone(worker('version')[1], 'Rejected authority must terminate this connection')
