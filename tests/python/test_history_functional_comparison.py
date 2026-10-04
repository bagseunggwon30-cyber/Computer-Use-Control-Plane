"""Strict, caller-backed allowances; these tests never run original PowerShell."""
import copy
import contextlib
import io
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


functional = load('history_functional_tests_target', ROOT/'pcucp-next/packaging/history_functional_comparison.py')
gate_tests = load('history_functional_evidence_fixtures', ROOT/'tests/python/test_history_candidate_qualification.py')
history = gate_tests.history


def scalar(value, tag='String'):
    return dict(kind='scalar', type=tag, value=value)


def record(wire, text, operation='pick'):
    return dict(id='owned-case', operation=operation, wire=wire, compact_json=text,
                compact_json_items=[] if text is None else [text], console='', errors=[])


def obj(properties, kind='object'):
    return dict(kind=kind, properties=[dict(name=name, value=value) for name, value in properties])


class FunctionalValueTests(unittest.TestCase):
    def assert_category(self, left, right, expected):
        result = functional.compare_result(left, right)
        self.assertEqual(result['category'], expected)
        self.assertEqual(bool(result['functional_fields']), expected not in ('exact', 'allowed-representation'))
        return result

    def test_numeric_clr_tags_are_only_ignored_at_equal_values(self):
        self.assert_category(record(scalar(100, 'Double'), '100.0'), record(scalar(100, 'Decimal'), '1e2'), 'allowed-representation')
        self.assert_category(record(scalar(1, 'Int32'), '1'), record(scalar(2, 'Int64'), '2'), 'data-selection-or-shape')

    def test_decimal_equality_is_exact_without_context_rounding(self):
        self.assertTrue(functional.equal_json(functional.parse_json('1.000000000000000000000000000000000000'), 1, 'pick'))
        self.assertFalse(functional.equal_json(functional.parse_json('1.000000000000000000000000000000000001'), 1, 'pick'))
        self.assertFalse(functional.equal_json(functional.parse_json('1e400'), functional.parse_json('1e401'), 'pick'))

    def test_192_unit_difference_cannot_disappear(self):
        a, b = functional.parse_json('9.223372036854776E+18'), functional.parse_json('9223372036854775808')
        self.assertEqual(a - b, 192)
        self.assert_category(record(scalar(a, 'Double'), '9.223372036854776E+18'),
                             record(scalar(b, 'BigInteger'), '9223372036854775808'), 'data-selection-or-shape')

    def test_json_escapes_decode_without_changing_string_values(self):
        self.assert_category(record(scalar('한글😀'), '"한글\\uD83D\\uDE00"'),
                             record(scalar('한글😀'), '"한글😀"'), 'allowed-representation')
        self.assert_category(record(scalar('é'), '"é"'), record(scalar('e\u0301'), '"é"'), 'data-selection-or-shape')

    def test_only_stats_strategy_count_map_order_is_unordered(self):
        pairs = [('a', scalar(1, 'Int32')), ('b', scalar(2, 'Int32'))]
        left = record(obj([('strategies', obj(pairs, 'hashtable'))]), '{"strategies":{"a":1,"b":2}}', 'stats')
        right = record(obj([('strategies', obj(pairs[::-1], 'hashtable'))]), '{"strategies":{"b":2,"a":1}}', 'stats')
        self.assert_category(left, right, 'allowed-representation')
        for operation in ('pick', 'last-good', 'app-read'):
            self.assert_category(dict(left, operation=operation), dict(right, operation=operation), 'data-selection-or-shape')
        changed = copy.deepcopy(right); changed['wire']['properties'][0]['value']['properties'][0]['name'] = 'B'
        self.assert_category(left, changed, 'data-selection-or-shape')

    def test_stats_map_exception_requires_actual_nonnegative_integer_counts(self):
        for invalid in (True, -1, Decimal('0.5'), '1', {}, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                functional.equal_json({'strategies': {'a': invalid}}, {'strategies': {'a': invalid}}, 'stats')
        bad = obj([('strategies', obj([('a', scalar(True, 'Boolean'))], 'hashtable'))])
        with self.assertRaises(ValueError):functional.wire_value(bad, 'stats')

    def test_object_order_elsewhere_and_extra_fields_are_preserved(self):
        a, b = obj([('a', scalar(1, 'Int32')), ('b', scalar(2, 'Int32'))]), obj([('b', scalar(2, 'Int32')), ('a', scalar(1, 'Int32'))])
        self.assert_category(record(a, '{"a":1,"b":2}', 'stats'), record(b, '{"b":2,"a":1}', 'stats'), 'data-selection-or-shape')
        self.assertFalse(functional.equal_json({'nested': {'a': 1, 'b': 2}}, {'nested': {'b': 2, 'a': 1}}, 'stats'))
        self.assertFalse(functional.equal_json({'a': 1}, {'a': 1, 'extra': None}, 'last-good'))

    def test_date_string_projection_remains_blocked_with_equal_typed_value(self):
        wire = scalar('2026-01-01T00:00:00.0000000Z', 'DateTime')
        self.assert_category(record(wire, '"2026-01-01T00:00:00.0000000Z"', 'last-good'),
                             record(wire, '"2026-01-01T00:00:00Z"', 'last-good'), 'caller-visible-serialization')
        self.assert_category(record(wire, '"2026-01-01T00:00:00Z"'),
                             record(scalar(wire['value']), '"2026-01-01T00:00:00Z"'), 'data-selection-or-shape')

    def test_boolean_number_string_and_null_do_not_coalesce(self):
        for a, b in ((True, 1), (False, 0), ('1', 1), (None, []), ([], [None])):
            self.assertFalse(functional.equal_json(a, b, 'pick'))
        self.assert_category(record(scalar(True, 'Boolean'), 'true'), record(scalar(1, 'Int32'), '1'), 'data-selection-or-shape')

    def test_array_order_cardinality_and_missing_output_are_preserved(self):
        self.assertFalse(functional.equal_json([1, 2], [2, 1], 'stats'))
        self.assertFalse(functional.equal_json([1], [[1]], 'last-good'))
        self.assert_category(record({'kind': 'null'}, None), record({'kind': 'null'}, 'null'), 'caller-visible-serialization')
        self.assert_category(record({'kind': 'array', 'items': []}, '[]'),
                             record({'kind': 'array', 'items': [{'kind': 'null'}]}, '[null]'), 'data-selection-or-shape')

    def test_diagnostic_errors_console_and_error_outcome_are_not_ignored(self):
        left = record(None, None);left['errors'] = ['owned error']
        self.assert_category(left, copy.deepcopy(left), 'exact')
        self.assert_category(left, dict(left, errors=['different error']), 'console-or-error')
        right = record({'kind': 'null'}, None)
        self.assert_category(left, right, 'data-selection-or-shape')
        self.assert_category(right, dict(right, console='output'), 'console-or-error')

    def test_duplicate_and_unknown_wire_members_fail_closed(self):
        bad = [obj([('x', scalar(1, 'Int32')), ('x', scalar(2, 'Int32'))]),
               scalar('1', 'Int32'), scalar(True, 'Int32'), scalar(1, 'Unrecognized'),
               {'kind': 'null', 'extra': True}, {'kind': 'array', 'items': None}]
        for wire in bad:
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                functional.compare_result(record(wire, 'null'), record(wire, 'null'))
        with self.assertRaises(ValueError): functional.parse_json('{"x":1,"x":2}')
        with self.assertRaises(UnicodeDecodeError): functional.parse_json(b'"\xff"')

    def test_malformed_converter_and_result_id_shapes_fail_closed(self):
        left = record({'kind': 'null'}, 'null')
        for changes in ({'id': 'other'}, {'operation': 'append'}, {'extra': True},
                        {'compact_json_items': 'null'}, {'compact_json_items': ['null', 'null']},
                        {'compact_json_items': []}, {'compact_json': '{"a":1,"a":2}', 'compact_json_items': ['{"a":1,"a":2}']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                functional.compare_result(left, dict(left, **changes))
        with self.assertRaises(ValueError):functional.compare_reports({'results': [left]}, {'results': []})
        with self.assertRaises(ValueError):functional.compare_reports({'results': [left, left]}, {'results': [left, left]})

    def test_nonfinite_tokens_do_not_become_strings(self):
        self.assertFalse(functional.equal_json(functional.parse_json('NaN'), 'NaN', 'app-read'))
        self.assertFalse(functional.equal_json(functional.parse_json('NaN'), functional.parse_json('Infinity'), 'app-read'))
        with self.assertRaises(ValueError): functional.wire_value(scalar('NaN', 'BigInteger'), 'pick')


class FunctionalEvidenceTests(unittest.TestCase):
    def make_evidence(self, root):
        fixture = gate_tests.HistoryRequiredArtifactTests()
        fixture.cases = history.fixtures()
        report = fixture.make_evidence(root)
        with tempfile.TemporaryDirectory(prefix='functional-original-') as owned:
            (root/'original-git-source.stdout.ps1').write_bytes(history.materialize_original(owned).read_bytes())
        return report

    def test_complete_evidence_adds_a_report_without_touching_exact_files(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned); self.make_evidence(root)
            hashes = {p.name: functional.sha256(p.read_bytes()) for p in root.iterdir()}
            result = functional.write_report(root, root/'functional-report.json', history)
            self.assertEqual(result['status'], 'passed-functional-candidate-only')
            self.assertFalse(result['caller_roundtrip_qualified'])
            self.assertEqual(len(result['runs']), 6)
            self.assertEqual(hashes, {p.name: functional.sha256(p.read_bytes()) for p in root.iterdir() if p.name in hashes})
            with self.assertRaises(FileExistsError):functional.write_report(root, root/'report.json', history)
            self.assertEqual(functional.sha256((root/'report.json').read_bytes()), hashes['report.json'])

    def test_partial_missing_changed_or_timeout_evidence_never_passes(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned); original = self.make_evidence(root)
            report_path = root/'report.json'; raw = report_path.read_bytes()
            for changes in ({'status': 'blocked'}, {'status': 'failed-parity'}, {'runs': original['runs'][:-1]},
                            {'runs': original['runs'][:1]*6}, {'source_sha256': 'x'}, {'errors': ['failure']}):
                report_path.write_bytes(json.dumps(dict(original, **changes)).encode('utf-8'))
                with self.assertRaises(ValueError):functional.analyze(root, history)
            report_path.write_bytes(raw)
            for name in ('input.json', 'original-git-source.stdout.ps1', 'ps51-many-0-candidate.raw.json',
                         'ps7-many-1-observed.stdout.bin', 'ps51-many-0-mismatches.json'):
                path = root/name; data = path.read_bytes();path.unlink()
                with self.assertRaises(OSError):functional.analyze(root, history)
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):functional.analyze(root, history)
                path.write_bytes(data)
            path = root/'ps51-many-0-candidate.process.json';metadata = json.loads(path.read_bytes())
            for changes in ({'timed_out': True}, {'exit_code': None}, {'exit_code': False}, {'stdout_truncated': True}):
                path.write_bytes(json.dumps(dict(metadata, **changes)).encode('utf-8'))
                with self.assertRaises(ValueError):functional.analyze(root, history)
            changed = dict(metadata);changed.pop('launch_error');path.write_bytes(json.dumps(changed).encode('utf-8'))
            with self.assertRaises(ValueError):functional.analyze(root, history)

    def test_allowed_representation_preserves_failed_exact_status_and_exit(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned); report = self.make_evidence(root)
            run = report['runs'][0]
            prefix = f"{run['runtime']}-{run['batch']}-{run['repeat']}"
            loaded = {}
            for kind, tag, text in (('candidate', 'Int32', '1.0'), ('observed', 'Int64', '1')):
                path = root/f'{prefix}-{kind}.raw.json'
                value = json.loads(path.read_bytes())
                row = value['results'][0]
                row.update(wire=scalar(1, tag), compact_json=text, compact_json_items=[text])
                raw = history.dumps(value).encode('utf-8')
                path.write_bytes(raw); (root/f'{prefix}-{kind}.stdout.bin').write_bytes(raw)
                capture = root/f'{prefix}-{kind}.process.json'
                metadata = json.loads(capture.read_bytes())
                metadata.update(stdout_bytes=len(raw), stdout_sha256=functional.sha256(raw))
                capture.write_bytes(json.dumps(metadata).encode('utf-8'))
                run[kind+'_sha256'] = functional.sha256(raw)
                loaded[kind] = value
            mismatches = history.compare_reports(loaded['candidate'], loaded['observed'])
            (root/f'{prefix}-mismatches.json').write_bytes(json.dumps(mismatches).encode('utf-8'))
            run['mismatch_count'] = len(mismatches); report['status'] = 'failed-parity'
            exact = json.dumps(report).encode('utf-8'); (root/'report.json').write_bytes(exact)
            result = functional.write_report(root, root/'functional-report.json', history)
            self.assertEqual(result['status'], 'passed-functional-candidate-only')
            self.assertEqual(result['exact_status'], 'failed-parity')
            self.assertEqual((root/'report.json').read_bytes(), exact)
            # The integrated differential still requires its original exact pass.
            import ast
            tree = ast.parse((ROOT/'tests/python/test_legacy_history_reducers.py').read_text(encoding='utf-8', errors='strict'))
            method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'differential')
            final_return = next(node for node in reversed(method.body) if isinstance(node, ast.Return))
            self.assertIsInstance(final_return.value.test, ast.BoolOp)
            self.assertIn("report['status'] == 'passed-candidate-parity'", ast.unparse(final_return))

    def test_differential_writes_both_blocked_reports_when_hosts_are_missing(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)/'reports'
            args = SimpleNamespace(report_dir=str(root), ps51=None, ps7=None)
            with mock.patch.dict(sys.modules, {history.__name__: history}), \
                 mock.patch.object(history, 'dotnet_command', return_value=None), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(history.differential(args), 1)
            exact = json.loads((root/'report.json').read_bytes())
            extra = json.loads((root/'functional-report.json').read_bytes())
            self.assertEqual(exact['status'], 'blocked')
            self.assertEqual(extra['status'], 'blocked')
            self.assertEqual(exact['runs'], [])
            self.assertFalse(extra['production_cutover'])

    def test_validation_failure_retains_blocked_additional_report(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            result = functional.write_report(root, root/'functional-report.json', history)
            self.assertEqual(result['status'], 'blocked')
            self.assertIn('error', json.loads((root/'functional-report.json').read_bytes()))

    def test_huge_decimal_exponent_retains_blocked_report_and_input_bytes(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            raw = b'{"oversized_exponent":1e999999999999999999999999999999999999999}'
            source = root/'report.json';source.write_bytes(raw)
            result = functional.write_report(root, root/'functional-report.json', history)
            self.assertEqual(result['status'], 'blocked')
            self.assertFalse(result['production_cutover'])
            self.assertIn('error', json.loads((root/'functional-report.json').read_bytes()))
            self.assertEqual(source.read_bytes(), raw)

    def test_stat_bound_precedes_full_read(self):
        with tempfile.TemporaryDirectory() as owned:
            path = Path(owned)/'owned';path.write_bytes(b'12345')
            with self.assertRaises(ValueError):functional.read_bounded(path, 4)


class RecordedTaxonomyTests(unittest.TestCase):
    def test_saved_run_has_disjoint_complete_categories_and_original_provenance(self):
        path = ROOT/'docs/qualification/history-functional-df200f07.json'
        report = json.loads(path.read_bytes())
        self.assertEqual(report['status'], 'failed-functional-parity')
        self.assertEqual(report['exact_status'], 'failed-parity')
        self.assertEqual(report['source_sha256'], history.SOURCE_SHA256)
        self.assertEqual(report['manifest_sha256'], history.ORIGINAL_SHA256)
        self.assertFalse(report['production_cutover'])
        self.assertFalse(report['caller_roundtrip_qualified'])
        for name in ('comparator_sha256', 'analysis_harness_sha256', 'exact_report_sha256'):
            self.assertRegex(report[name], r'^[0-9a-f]{64}$')
        for run in report['runs']:
            self.assertEqual(len({row['id'] for row in run['cases']}), run['count'])
            self.assertEqual(functional.counts(run['cases']), run['counts'])
            if run['batch'] == 'singleton':
                self.assertEqual(run['counts']['exact'], 1)
            elif run['runtime'] == 'ps51':
                self.assertEqual([run['counts'][key] for key in functional.CATEGORIES], [299,118,48,0,0])
                self.assertEqual(run['raw_mismatch_count'], 484)
            else:
                self.assertEqual([run['counts'][key] for key in functional.CATEGORIES], [281,115,19,50,0])
                self.assertEqual(run['raw_mismatch_count'], 354 if run['repeat'] == 0 else 330)
        self.assertEqual([r['counts']['allowed-representation'] for r in report['original_repeats']], [0,41])


if __name__ == '__main__':
    unittest.main()
