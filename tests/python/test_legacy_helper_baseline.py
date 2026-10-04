"""The baseline exception is narrow; infrastructure and changed effects fail."""
import copy
import tempfile
from pathlib import Path
import unittest

from helper_baseline_observation import OBSERVATION, _diagnostic, classify_original_startup
from test_legacy_helper_source import published_source


class HelperBaselineObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'published-server.ps1'
        self.source.write_bytes(published_source('scripts/cucp-helper-server.ps1', self.root))
        self.lock = self.root / 'owned.pid'
        old_path, _ = _diagnostic(OBSERVATION.read_bytes())
        stderr = OBSERVATION.read_bytes().replace(old_path.encode(), str(self.source).encode(), 1)
        self.result = dict(running=False, exit_code=1, launch_error=None, timed_out=False, kill_error=None,
                           drain_incomplete=False, stdin_error=None, read_errors={},
                           truncated={'stdout':False,'stderr':False}, stdout=b'', stderr=stderr,
                           bytes_observed={'stdout':0, 'stderr':len(stderr)},
                           evidence_path=str(self.root / 'already-retained.json'))
        Path(self.result['evidence_path']).with_suffix('.stdout.bin').write_bytes(b'')
        Path(self.result['evidence_path']).with_suffix('.stderr.bin').write_bytes(stderr)

    def classify(self, result=None, returncode=1):
        return classify_original_startup(result or self.result, source=self.source, lock=self.lock, process_returncode=returncode)

    def test_exact_observed_defect_stays_failed_and_unqualified(self):
        result = self.classify()
        self.assertEqual(result['status'], 'baseline-startup-defect')
        self.assertEqual(result['raw_oracle_status'], 'failed')
        self.assertFalse(result['original_startup_qualified'])
        self.assertEqual(result['source_line'], 534)

    def test_infrastructure_flags_exit_and_incomplete_evidence_never_classify(self):
        for key, value in [('running',True),('exit_code',0),('launch_error','no executable'),('timed_out',True),
                           ('kill_error','unknown'),('drain_incomplete',True),('stdin_error','broken'),
                           ('read_errors',{'stderr':'failure'}),('truncated',{'stdout':False,'stderr':True})]:
            with self.subTest(field=key):
                changed = copy.deepcopy(self.result); changed[key] = value
                with self.assertRaises(AssertionError): self.classify(changed)
        for returncode in (None,0,2):
            with self.assertRaises(AssertionError): self.classify(returncode=returncode)

    def test_different_diagnostic_source_or_side_effects_never_classify(self):
        for stderr in (b'', self.result['stderr']+b'Unexpected extra failure\n',
                       self.result['stderr'].replace(b"'try'", b"'other'"),
                       self.result['stderr'].replace(b'CommandNotFoundException', b'UnauthorizedAccessException')):
            changed = dict(self.result, stderr=stderr)
            changed['bytes_observed'] = {'stdout':0, 'stderr':len(stderr)}
            Path(changed['evidence_path']).with_suffix('.stderr.bin').write_bytes(stderr)
            with self.assertRaises(AssertionError): self.classify(changed)
        Path(self.result['evidence_path']).with_suffix('.stderr.bin').write_bytes(self.result['stderr'])
        with self.assertRaises(AssertionError): self.classify(dict(self.result, stdout=b'unexpected'))
        self.lock.write_bytes(b'partial lock')
        with self.assertRaises(AssertionError): self.classify()
        self.lock.unlink()
        self.source.write_bytes(self.source.read_bytes()+b'\n')
        with self.assertRaises(AssertionError): self.classify()

    def test_raw_prefix_or_count_mismatch_never_classifies(self):
        changed = copy.deepcopy(self.result)
        changed['bytes_observed']['stderr'] += 1
        with self.assertRaises(AssertionError): self.classify(changed)
        Path(self.result['evidence_path']).with_suffix('.stderr.bin').write_bytes(self.result['stderr'][:-1])
        with self.assertRaises(AssertionError): self.classify()
