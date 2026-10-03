"""Historical permutations are observations; functional order remains strict."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from helper_args_only_observation import args_only_case_ids, classify_args_only_actions, retained_args_only
from test_legacy_helper_parity import cases
from test_legacy_helper_source import published_source


class HelperArgsOnlyObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'published.ps1'
        self.source.write_bytes(published_source('scripts/cucp-helper-server.ps1', self.root))
        self.cases = {case['id']: case for case in cases()}

    def record(self, data):
        raw = json.dumps(data, ensure_ascii=True).encode()
        result = dict(running=False, exit_code=0, launch_error=None, timed_out=False, kill_error=None,
                      drain_incomplete=False, stdin_error=None, read_errors={},
                      truncated={'stdout': False, 'stderr': False}, stdout=raw, stderr=b'',
                      bytes_observed={'stdout': len(raw), 'stderr': 0}, evidence_path=str(self.root / 'retained.json'))
        Path(result['evidence_path']).with_suffix('.stdout.bin').write_bytes(raw)
        Path(result['evidence_path']).with_suffix('.stderr.bin').write_bytes(b'')
        return result

    def classify(self, case_id, data=None):
        case = self.cases[case_id]
        if data is None:
            data = retained_args_only(case)[0]
        result = self.record(data)
        before = result['stdout']
        value = classify_args_only_actions(result, case=case, source=self.source)
        self.assertEqual(result['stdout'], before)
        self.assertEqual(Path(result['evidence_path']).with_suffix('.stdout.bin').read_bytes(), before)
        return value

    def test_all_18_retained_typed_observations_match_but_are_not_qualified(self):
        self.assertEqual(len(args_only_case_ids()), 18)
        for case_id in args_only_case_ids():
            with self.subTest(case=case_id):
                value = self.classify(case_id)
                self.assertEqual(value['status'], 'recorded-baseline-observation')
                self.assertTrue(value['exact_recorded_match'])
                self.assertFalse(value['args_only_qualified'])
                self.assertEqual(value['qualification'], 'not-functional-qualification')

    def test_changed_tie_or_rank_order_is_retained_and_labelled_without_qualification(self):
        for case_id in ('uia-caps-ties', 'uia-en-US', 'modal-large-ties', 'modal-en-US'):
            data = retained_args_only(self.cases[case_id])[0]
            result = data['responses'][0]['result']
            key = 'candidates' if case_id.startswith('uia') else 'modal_candidates'
            result[key].reverse()
            if key == 'candidates':
                result['best'] = copy.deepcopy(result[key][0])
                result['score'] = result[key][0]['score']
            else:
                first = result[key][0]
                result['recommended_action'] = ('dismiss_or_confirm' if first['is_modal'] or first['score'] >= 100
                                                else 'confirm_dialog' if first['score'] >= 60 else 'wait')
            with self.subTest(case=case_id):
                value = self.classify(case_id, data)
                self.assertEqual(value['status'], 'changed-baseline-observation')
                self.assertFalse(value['exact_recorded_match'])
                self.assertFalse(value['args_only_qualified'])
                self.assertTrue(value['changed_baseline_fields'])

    def test_changed_types_members_caps_or_uncoupled_selection_are_rejected(self):
        baseline = retained_args_only(self.cases['uia-caps-ties'])[0]
        for field, value in [('best', {}), ('score', 80.0), ('candidate_count', 15), ('match', ''), ('uia_warm', 1)]:
            changed = copy.deepcopy(baseline)
            changed['responses'][0]['result'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.classify('uia-caps-ties', changed)
        for mutation in ('drop', 'duplicate', 'rect', 'float-best', 'float-member'):
            changed = copy.deepcopy(baseline)
            result = changed['responses'][0]['result']
            if mutation == 'drop': result['candidates'].pop()
            if mutation == 'duplicate': result['candidates'].append(result['candidates'][0])
            if mutation == 'rect': result['candidates'][0]['rect']['x'] = 999
            if mutation == 'float-best': result['best']['click_point']['x'] = 50.0
            if mutation == 'float-member': result['candidates'][0]['score'] = 80.0
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.classify('uia-caps-ties', changed)

    def test_changed_acquisition_effects_seams_modes_or_case_inputs_are_rejected(self):
        baseline = retained_args_only(self.cases['uia-en-US'])[0]
        for field, value in [('calls', []), ('effects', []), ('request_count', 3),
                             ('oracle_mode', 'functional-intent'), ('args_seam', {}), ('oracle_seam', {})]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.classify('uia-en-US', dict(baseline, **{field: value}))
        changed = copy.deepcopy(baseline)
        changed['calls'][0], changed['calls'][1] = changed['calls'][1], changed['calls'][0]
        with self.assertRaises(AssertionError): self.classify('uia-en-US', changed)
        case = copy.deepcopy(self.cases['uia-en-US'])
        case['requests'][0]['args']['Label'] = 'Changed'
        with self.assertRaises(AssertionError): retained_args_only(case)
        with self.assertRaises(AssertionError): retained_args_only(dict(id='unobserved-case'))

    def test_only_generated_ocr_paths_and_one_exact_diagnostic_assembly_are_normalized(self):
        case_id = 'ocr-success-truthiness-cache'
        data = retained_args_only(self.cases[case_id])[0]
        paths = [call['value'] for call in data['calls'] if call['op'] == 'ocr.tempPath']
        replacements = {path: 'D:\\Owned fixture\\cucp-srv-ocr-' + letter * 32 + '.png'
                        for path, letter in zip(paths, ('a', 'b'))}
        for call in data['calls']:
            if call['op'] == 'ocr.tempPath': call['value'] = replacements[call['value']]
            if call['op'] in ('ocr.capture', 'ocr.loadFile', 'ocr.removeTemp'):
                call['args'][-1] = replacements[call['args'][-1]]
        from helper_args_only_observation import ASSEMBLY_DIAGNOSTIC
        for response in data['responses']:
            detail = response['result']['detail']
            match = ASSEMBLY_DIAGNOSTIC.fullmatch(detail)
            response['result']['detail'] = detail[:match.start('assembly')] + 'OtherOwned123' + detail[match.end('assembly'):]
        value = self.classify(case_id, data)
        self.assertTrue(value['exact_recorded_match'])
        self.assertEqual(len(value['generated_normalizations']), 2)
        for mutation in ('error', 'assembly', 'path', 'cleanup', 'region'):
            changed = copy.deepcopy(data)
            if mutation == 'error': changed['responses'][0]['result']['detail'] += ' extra'
            if mutation == 'assembly': changed['responses'][0]['result']['detail'] = changed['responses'][0]['result']['detail'].replace('OtherOwned123', 'Different123')
            if mutation == 'path': next(call for call in changed['calls'] if call['op'] == 'ocr.tempPath')['value'] = 'not-a-generated-path'
            if mutation == 'cleanup': changed['calls'] = [call for call in changed['calls'] if call['op'] != 'ocr.removeTemp']
            if mutation == 'region': next(call for call in changed['calls'] if call['op'] == 'ocr.capture')['args'][0] = 1
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.classify(case_id, changed)

    def test_infrastructure_source_and_incomplete_raw_evidence_never_classify(self):
        case = self.cases['focused-partial']
        data = retained_args_only(case)[0]
        for field, value in [('running', True), ('exit_code', 1), ('timed_out', True), ('launch_error', 'missing'),
                             ('kill_error', 'unknown'), ('drain_incomplete', True), ('stdin_error', 'broken'),
                             ('read_errors', {'stderr': 'failed'}), ('truncated', {'stdout': True, 'stderr': False})]:
            record = self.record(data); record[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                classify_args_only_actions(record, case=case, source=self.source)
        record = self.record(data); record['bytes_observed']['stdout'] += 1
        with self.assertRaises(AssertionError): classify_args_only_actions(record, case=case, source=self.source)
        record = self.record(data)
        Path(record['evidence_path']).with_suffix('.stdout.bin').write_bytes(record['stdout'][:-1])
        with self.assertRaises(AssertionError): classify_args_only_actions(record, case=case, source=self.source)
        self.source.write_bytes(self.source.read_bytes() + b'\n')
        with self.assertRaises(AssertionError): self.classify('focused-partial')

    def test_generated_path_alias_controls_and_length_do_not_hide_distinctness(self):
        case_id = 'ocr-success-truthiness-cache'
        baseline = retained_args_only(self.cases[case_id])[0]
        paths = [call['value'] for call in baseline['calls'] if call['op'] == 'ocr.tempPath']
        filenames = [path.rsplit('\\', 1)[1] for path in paths]
        replacements = [
            {paths[0]: paths[0], paths[1]: paths[0].replace('\\', '/')},
            {path: 'C:\\Owned\x00fixture\\' + filename for path, filename in zip(paths, filenames)},
            {path: 'C:\\' + 'a' * 32768 + '\\' + filename for path, filename in zip(paths, filenames)},
        ]
        for index, mapping in enumerate(replacements):
            changed = copy.deepcopy(baseline)
            for call in changed['calls']:
                if call['op'] == 'ocr.tempPath': call['value'] = mapping[call['value']]
                if call['op'] in ('ocr.capture', 'ocr.loadFile', 'ocr.removeTemp'):
                    call['args'][-1] = mapping[call['args'][-1]]
            with self.subTest(mutation=index), self.assertRaises(AssertionError):
                self.classify(case_id, changed)
