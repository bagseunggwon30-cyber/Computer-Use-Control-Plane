"""Observed binding defects never turn generic failures into qualification."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helper_binding_observation import (
    MESSAGE, OBSERVATION, OBSERVED_SHA256, _probe, classify_binding_probe,
    classify_original_actions, retained_binding_observation,
)
from test_legacy_helper_source import expected_type_seam, published_source


class HelperBindingObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'published.ps1'
        self.raw = published_source('scripts/cucp-helper-server.ps1', self.root)
        self.source.write_bytes(self.raw)
        self.probe = retained_binding_observation()
        self.case = dict(requests=[dict(id=17, action='health', args={}),
                                   dict(action='shutdown', args={})])
        self.actions = dict(oracle_mode='exact-original', args_seam=None,
                            oracle_seam=expected_type_seam(self.raw), calls=[], effects=[], request_count=0,
                            responses=[dict(id=r.get('id'), exit_code=1, result=None, error=MESSAGE)
                                       for r in self.case['requests']])

    def record(self, data, *, raw=None, stderr=b''):
        stdout = raw if raw is not None else json.dumps(data, ensure_ascii=True).encode()
        result = dict(running=False, exit_code=0, launch_error=None, timed_out=False, kill_error=None,
                      drain_incomplete=False, stdin_error=None, read_errors={},
                      truncated={'stdout': False, 'stderr': False}, stdout=stdout, stderr=stderr,
                      bytes_observed={'stdout': len(stdout), 'stderr': len(stderr)},
                      evidence_path=str(self.root / 'retained.json'))
        for stream in ('stdout', 'stderr'):
            Path(result['evidence_path']).with_suffix('.' + stream + '.bin').write_bytes(result[stream])
        return result

    def classify(self, data=None):
        return classify_original_actions(self.record(self.actions if data is None else data),
                                         case=self.case, source=self.source)

    def test_retained_raw_probe_has_exact_provenance_and_failed_originals(self):
        self.assertEqual(hashlib.sha256(OBSERVATION.read_bytes()).hexdigest(), OBSERVED_SHA256)
        self.assertEqual(len(OBSERVATION.read_bytes()), 34021)
        _probe(self.probe)
        originals = [o for o in self.probe['observations'] if o['target'].startswith('original-')]
        self.assertEqual(len(originals), 20)
        self.assertTrue(all(o['request_count'] == 0 and o['result'] is None for o in originals))
        result = classify_binding_probe(self.record(self.probe), source=self.source)
        self.assertEqual(result['raw_oracle_status'], 'failed')
        self.assertFalse(result['original_dispatch_qualified'])
        self.assertEqual(result['observed_requests'], 20)

    def test_original_action_failures_remain_failed_and_unqualified(self):
        value = self.classify()
        self.assertEqual(value['status'], 'baseline-argument-binding-defect')
        self.assertEqual(value['raw_oracle_status'], 'failed')
        self.assertFalse(value['original_dispatch_qualified'])
        self.assertEqual(value['observed_requests'], 2)
        self.assertEqual(value['dispatch_count'], 0)
        self.assertEqual(value['acquisition_count'], 0)

    def test_infrastructure_incomplete_or_changed_raw_evidence_never_classifies(self):
        for field, value in [('running', True), ('exit_code', 1), ('timed_out', True),
                             ('launch_error', 'missing'), ('kill_error', 'unknown'),
                             ('drain_incomplete', True), ('stdin_error', 'broken'),
                             ('read_errors', {'stderr': 'failed'}),
                             ('truncated', {'stdout': True, 'stderr': False})]:
            with self.subTest(field=field):
                result = self.record(self.actions)
                result[field] = value
                with self.assertRaises(AssertionError):
                    classify_original_actions(result, case=self.case, source=self.source)
        result = self.record(self.actions)
        result['bytes_observed']['stdout'] += 1
        with self.assertRaises(AssertionError):
            classify_original_actions(result, case=self.case, source=self.source)
        result = self.record(self.actions)
        Path(result['evidence_path']).with_suffix('.stdout.bin').write_bytes(result['stdout'][:-1])
        with self.assertRaises(AssertionError):
            classify_original_actions(result, case=self.case, source=self.source)
        with self.assertRaises(AssertionError):
            classify_original_actions(self.record(self.actions, stderr=b'unexpected'), case=self.case, source=self.source)

    def test_changed_source_pin_or_retained_evidence_never_classifies(self):
        self.source.write_bytes(self.raw + b'\n')
        with self.assertRaises(AssertionError):
            self.classify()
        self.source.write_bytes(self.raw)
        wrong = self.root / 'altered-observation.bin'
        wrong.write_bytes(OBSERVATION.read_bytes() + b'\n')
        with patch('helper_binding_observation.OBSERVATION', wrong), self.assertRaises(AssertionError):
            self.classify()

    def test_corrected_or_changed_original_action_results_are_not_baseline(self):
        for field, value in [('oracle_mode', 'corrected-intent'), ('args_seam', {}),
                             ('calls', {}), ('calls', [{'op': 'win32.ensure', 'args': []}]),
                             ('effects', ['ensure_win32']), ('request_count', 1), ('request_count', False),
                             ('responses', []), ('oracle_seam', {})]:
            with self.subTest(field=field), self.assertRaises((AssertionError, KeyError)):
                self.classify(dict(self.actions, **{field: value}))
        for field, value in [('exit_code', 0), ('exit_code', True), ('result', {}),
                             ('error', None), ('error', MESSAGE + ' extra'), ('id', 18)]:
            changed = copy.deepcopy(self.actions)
            changed['responses'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.classify(changed)
        changed = copy.deepcopy(self.actions)
        changed['oracle_seam']['functions'][0]['original_sha256'] = 'changed'
        with self.assertRaises(AssertionError):
            self.classify(changed)
        with self.assertRaises(AssertionError):
            classify_original_actions(self.record(dict(self.actions, responses=[])),
                                      case=dict(requests=[]), source=self.source)

    def test_probe_requires_all_inputs_controls_error_types_and_zero_effects(self):
        variants = []
        for field, value in [('powershell_version', '7.0'), ('source_sha256', 'changed'),
                             ('functions', []), ('observations', self.probe['observations'][:-1])]:
            variants.append(dict(self.probe, **{field: value}))
        duplicate = copy.deepcopy(self.probe)
        duplicate['observations'][1] = duplicate['observations'][0]
        variants.append(duplicate)
        for field, value in [('input_type', 'System.Object[]'), ('input_value', []), ('request_count', 1),
                             ('request_count', False), ('body_entered', 1), ('result', {})]:
            changed = copy.deepcopy(self.probe)
            changed['observations'][0][field] = value
            variants.append(changed)
        for field, value in [('message', MESSAGE + ' extra'), ('exception_type', 'System.Exception'),
                             ('fully_qualified_error_id', 'GenericFailure'), ('category', 'NotSpecified'),
                             ('script_stack_trace', ''), ('inner_exception_type', 'System.Exception')]:
            changed = copy.deepcopy(self.probe)
            changed['observations'][0]['error'][field] = value
            variants.append(changed)
        control = copy.deepcopy(self.probe)
        next(o for o in control['observations'] if o['target'] == 'synthetic-named')['result'] = None
        variants.append(control)
        input_type = copy.deepcopy(self.probe)
        next(o for o in input_type['observations'] if o['input'] == 'direct-values')['input_value']['Flag'] = 0
        variants.append(input_type)
        for number, value in enumerate(variants):
            with self.subTest(variant=number), self.assertRaises(AssertionError):
                classify_binding_probe(self.record(value), source=self.source)

    def test_duplicate_or_nonfinite_json_is_never_original_evidence(self):
        for raw in (b'{"request_count":0,"request_count":0}', b'{"value":NaN}',
                    b'{"value":1e309}', b'{"nested":{"value":-1e309}}'):
            with self.subTest(raw=raw), self.assertRaises(AssertionError):
                classify_binding_probe(self.record(None, raw=raw), source=self.source)
