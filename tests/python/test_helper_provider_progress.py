"""Portable progress-verdict regressions; never instantiate desktop providers."""
from __future__ import annotations

import copy
import json
import unittest

from helper_provider_expectations import GROUPS
from helper_provider_progress import EXPECTED_GROUPS, MAX_BYTES, MAX_RECORDS, SCHEMA, validate_progress


def record(group, request, phase, operation=None, index=0):
    return dict(schema=SCHEMA, sequence=0, group=group, request=request,
                phase=phase, operation=operation, index=index,
                elapsed_ticks=0, request_ticks=0, provider_ticks=0,
                diagnostic_ticks=0, write_ticks=0, frequency=10_000_000)


def order(rows):
    request_index = 0
    request_offset = 0
    for sequence, row in enumerate(rows, 1):
        if row['phase'] == 'request.start':
            request_index = 0
            request_offset = sequence * 1000 - 10
        row.update(sequence=sequence, elapsed_ticks=sequence * 1000,
                   write_ticks=sequence - 1)
        row['request_ticks'] = row['elapsed_ticks'] - request_offset if row['request'] is not None else 0
        for key, scale in (('provider_ticks', 10), ('diagnostic_ticks', 2)):
            row[key] = request_index * scale if row['request'] is not None else 0
        request_index += 1
    return rows


def complete(group='ocr-owned', inner=None):
    rows = [record(group, None, 'group.start')]
    for name in EXPECTED_GROUPS[group]:
        for phase in ('request.start', 'dispatch.start'):
            rows.append(record(group, name, phase))
        markers = inner
        if markers is None:
            markers = UIA_INNER if group in {'uia', 'uia-cold'} and name not in {'uia-missing', 'health-uia'} else ()
            if group == 'uia-cold':
                markers = tuple(item for item in markers if not item[0].startswith('diagnostics.'))
        for phase, operation, index in markers:
            rows.append(record(group, name, phase, operation, index))
        for phase in ('dispatch.end', 'serialize.start', 'serialize.end',
                      'write.start', 'write.end', 'request.end'):
            rows.append(record(group, name, phase))
            if group == 'uia-cold' and phase == 'dispatch.end':
                for item in UIA_INNER:
                    if item[0].startswith('diagnostics.'):
                        rows.append(record(group, name, *item))
    rows.append(record(group, None, 'group.end'))
    return order(rows)


def encode(rows):
    return b''.join((json.dumps(row, ensure_ascii=False, separators=(',', ':'))
                     + '\n').encode('utf-8') for row in rows)


INNER = (
    ('acquire.start', 'uia.subtree', 0),
    ('acquire.end', 'uia.subtree', 0),
    ('evidence.start', 'uia.subtree', 0),
    ('evidence.end', 'uia.subtree', 0),
    ('diagnostics.start', 'uia.subtree', 0),
    ('diagnostics.progress', 'uia.subtree', 128),
    ('diagnostics.end', 'uia.subtree', 129),
    ('scan.progress', 'uia.name', 128),
)
UIA_INNER = (
    ('acquire.start', 'uia.root', 0), ('acquire.end', 'uia.root', 0),
    ('acquire.start', 'uia.children', 0), ('acquire.end', 'uia.children', 0),
) + INNER


class ProgressValidationTests(unittest.TestCase):
    def assert_invalid(self, rows, message=None, group='ocr-owned'):
        with self.assertRaisesRegex(AssertionError, message or 'Invalid helper-provider progress'):
            validate_progress(encode(rows), group)

    def test_all_complete_groups_return_exact_records(self):
        for group in EXPECTED_GROUPS:
            with self.subTest(group=group):
                rows = complete(group)
                self.assertEqual(validate_progress(encode(rows), group), rows)

    def test_coarse_intervals_and_progress_pass(self):
        rows = complete('uia')
        self.assertEqual(validate_progress(encode(rows), 'uia'), rows)

    def test_substantive_uia_requests_cannot_omit_instrumentation(self):
        self.assert_invalid(complete('uia', ()), 'required UIA', group='uia')

    def test_substantive_uia_requires_each_coarse_pair(self):
        for category, operation in (('acquire', 'uia.root'), ('acquire', 'uia.children'),
                                    ('acquire', 'uia.subtree'), ('evidence', 'uia.subtree'),
                                    ('diagnostics', 'uia.subtree')):
            inner = tuple(item for item in UIA_INNER
                          if not (item[0].split('.')[0] == category and item[1] == operation))
            with self.subTest(category=category, operation=operation):
                self.assert_invalid(complete('uia', inner), 'required UIA', group='uia')

    def test_substantive_uia_rejects_duplicate_coarse_pairs(self):
        for category, operation in (('acquire', 'uia.root'), ('acquire', 'uia.children'),
                                    ('acquire', 'uia.subtree'), ('evidence', 'uia.subtree'),
                                    ('diagnostics', 'uia.subtree')):
            extra = ((category + '.start', operation, 0), (category + '.end', operation, 0))
            with self.subTest(category=category, operation=operation):
                self.assert_invalid(complete('uia', UIA_INNER + extra), 'required UIA', group='uia')

    def test_uia_acquisition_order_cannot_change(self):
        inner = UIA_INNER[2:4] + UIA_INNER[:2] + UIA_INNER[4:]
        self.assert_invalid(complete('uia', inner), 'required UIA', group='uia')

    def test_uia_diagnostics_must_follow_subtree_evidence(self):
        inner = UIA_INNER[:6] + UIA_INNER[8:11] + UIA_INNER[6:8] + UIA_INNER[11:]
        self.assert_invalid(complete('uia', inner), 'required UIA', group='uia')

    def test_uia_required_intervals_cannot_nest(self):
        inner = UIA_INNER[:5] + UIA_INNER[8:11] + UIA_INNER[5:8] + UIA_INNER[11:]
        self.assert_invalid(complete('uia', inner), 'required UIA', group='uia')

    def test_uia_missing_and_health_need_no_provider_markers(self):
        rows = complete('uia')
        for name in ('uia-missing', 'health-uia'):
            self.assertEqual(sum(row['request'] == name for row in rows), 8)
        validate_progress(encode(rows), 'uia')

    def test_every_substantive_uia_case_requires_markers(self):
        for name in GROUPS['uia'][1:-1]:
            rows = complete('uia')
            rows = [row for row in rows if row['request'] != name or
                    row['phase'].split('.')[0] in {'request', 'dispatch', 'serialize', 'write'}]
            with self.subTest(name=name):
                self.assert_invalid(order(rows), 'required UIA', group='uia')

    def test_cold_group_does_not_modify_original_groups(self):
        self.assertNotIn('uia-cold', GROUPS)
        self.assertEqual(sum(map(len, GROUPS.values())), 31)
        self.assertEqual(EXPECTED_GROUPS['uia-cold'], ['uia-run'])

    def test_cold_group_diagnostics_follow_dispatch_before_serialize(self):
        rows = complete('uia-cold')
        phases = [row['phase'] for row in rows]
        self.assertLess(phases.index('dispatch.end'), phases.index('diagnostics.start'))
        self.assertLess(phases.index('diagnostics.end'), phases.index('serialize.start'))
        self.assertEqual(validate_progress(encode(rows), 'uia-cold'), rows)

    def test_cold_diagnostics_inside_dispatch_rejected(self):
        self.assert_invalid(complete('uia-cold', UIA_INNER), 'cold diagnostics must follow', group='uia-cold')

    def test_cold_missing_post_dispatch_diagnostics_rejected(self):
        rows = [row for row in complete('uia-cold') if not row['phase'].startswith('diagnostics.')]
        self.assert_invalid(order(rows), 'requires post-dispatch diagnostics', group='uia-cold')

    def test_cold_diagnostics_after_serialization_rejected(self):
        rows = complete('uia-cold')
        diagnostic = [row for row in rows if row['phase'].startswith('diagnostics.')]
        rows = [row for row in rows if not row['phase'].startswith('diagnostics.')]
        at = next(index for index, row in enumerate(rows) if row['phase'] == 'serialize.end') + 1
        rows[at:at] = diagnostic
        self.assert_invalid(order(rows), 'requires post-dispatch diagnostics', group='uia-cold')

    def test_cold_duplicate_post_dispatch_diagnostics_rejected(self):
        rows = complete('uia-cold')
        diagnostic = [row for row in rows if row['phase'].startswith('diagnostics.')]
        at = next(index for index, row in enumerate(rows) if row['phase'] == 'serialize.start')
        rows[at:at] = copy.deepcopy(diagnostic)
        self.assert_invalid(order(rows), 'expected serialize.start', group='uia-cold')

    def test_cold_diagnostics_require_matching_subtree_operation(self):
        for phase in ('diagnostics.start', 'diagnostics.end'):
            rows = complete('uia-cold')
            next(row for row in rows if row['phase'] == phase)['operation'] = 'uia.children'
            with self.subTest(phase=phase):
                self.assert_invalid(rows, group='uia-cold')

    def test_cold_diagnostics_require_end_and_forbid_other_phases(self):
        for phase in ('scan.progress', 'acquire.start', 'diagnostics.start', 'serialize.start'):
            rows = complete('uia-cold')
            next(row for row in rows if row['phase'] == 'diagnostics.end')['phase'] = phase
            with self.subTest(phase=phase):
                self.assert_invalid(rows, 'inside cold diagnostics interval', group='uia-cold')

    def test_normal_uia_diagnostics_cannot_move_after_dispatch(self):
        rows = complete('uia')
        diagnostic = [row for row in rows if row['request'] == 'uia-run' and row['phase'].startswith('diagnostics.')]
        rows = [row for row in rows if row not in diagnostic]
        at = next(index for index, row in enumerate(rows)
                  if row['request'] == 'uia-run' and row['phase'] == 'dispatch.end') + 1
        rows[at:at] = diagnostic
        self.assert_invalid(order(rows), 'expected serialize.start', group='uia')

    def test_cold_wrong_request_population_rejected(self):
        for name in ('uia-missing', 'uia-run-reused', 'health-uia', None):
            rows = complete('uia-cold')
            for row in rows[1:-1]:
                row['request'] = name
            with self.subTest(name=name):
                self.assert_invalid(rows, 'request order/name mismatch', group='uia-cold')
        rows = complete('uia-cold')
        rows[-1:-1] = copy.deepcopy(rows[1:-1])
        self.assert_invalid(order(rows), 'extra request', group='uia-cold')

    def test_cold_requires_all_pre_dispatch_uia_markers(self):
        for operation in ('uia.root', 'uia.children', 'uia.subtree'):
            rows = [row for row in complete('uia-cold')
                    if not (row['phase'].startswith('acquire.') and row['operation'] == operation)]
            with self.subTest(operation=operation):
                self.assert_invalid(order(rows), 'required UIA', group='uia-cold')

    def test_nested_intervals_match_stack_order(self):
        rows = complete(inner=(('evidence.start', 'uia.subtree', 0),
                               ('diagnostics.start', 'uia.subtree', 0),
                               ('diagnostics.progress', 'uia.subtree', 128),
                               ('diagnostics.end', 'uia.subtree', 129),
                               ('evidence.end', 'uia.subtree', 0)))
        self.assertEqual(validate_progress(encode(rows), 'ocr-owned'), rows)

    def test_null_coarse_operation_is_preserved(self):
        rows = complete(inner=(('acquire.start', None, 0), ('acquire.end', None, 0)))
        self.assertEqual(validate_progress(encode(rows), 'ocr-owned'), rows)

    def test_crlf_and_unicode_are_valid(self):
        rows = complete(inner=(('acquire.start', '한글', 0), ('acquire.end', '한글', 0)))
        self.assertEqual(validate_progress(encode(rows).replace(b'\n', b'\r\n'), 'ocr-owned'), rows)

    def test_equal_tick_counters_are_valid(self):
        rows = complete()
        for row in rows:
            for key in ('elapsed_ticks', 'request_ticks', 'provider_ticks',
                        'diagnostic_ticks', 'write_ticks'):
                row[key] = 0
        self.assertEqual(validate_progress(encode(rows), 'ocr-owned'), rows)

    def test_request_counters_reset_at_next_request(self):
        rows = complete()
        starts = [row for row in rows if row['phase'] == 'request.start']
        self.assertEqual(len(starts), 2)
        self.assertEqual([row['request_ticks'] for row in starts], [10, 10])
        validate_progress(encode(rows), 'ocr-owned')

    def test_group_end_may_reset_request_counters(self):
        rows = complete()
        self.assertGreater(rows[-2]['provider_ticks'], 0)
        self.assertEqual(rows[-1]['provider_ticks'], 0)
        validate_progress(encode(rows), 'ocr-owned')

    def test_write_ticks_need_not_equal_elapsed_ticks(self):
        rows = complete()
        self.assertNotEqual(rows[-1]['elapsed_ticks'], rows[-1]['write_ticks'])
        validate_progress(encode(rows), 'ocr-owned')

    def test_missing_or_nonbytes_input_rejected(self):
        for raw in (b'', None, '', [], bytearray(b'{}\n')):
            with self.subTest(raw=raw), self.assertRaises(AssertionError):
                validate_progress(raw, 'ocr-owned')

    def test_unknown_or_wrong_type_expected_group_rejected(self):
        for group in ('unknown', None, [], True):
            with self.subTest(group=group), self.assertRaises(AssertionError):
                validate_progress(encode(complete()), group)

    def test_missing_final_newline_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'unterminated'):
            validate_progress(encode(complete()).rstrip(b'\n'), 'ocr-owned')

    def test_partial_json_record_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'malformed JSON'):
            validate_progress(encode(complete()) + b'{"schema":\n', 'ocr-owned')

    def test_non_utf8_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'non-UTF-8'):
            validate_progress(b'\xff\n', 'ocr-owned')

    def test_utf8_bom_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'malformed JSON'):
            validate_progress(b'\xef\xbb\xbf' + encode(complete()), 'ocr-owned')

    def test_blank_records_rejected(self):
        raw = encode(complete())
        for bad in (b'\n' + raw, raw + b'\n', raw.replace(b'\n', b'\n \t\r\n', 1)):
            with self.subTest(raw=bad[:10]), self.assertRaisesRegex(AssertionError, 'blank record'):
                validate_progress(bad, 'ocr-owned')

    def test_duplicate_json_keys_rejected(self):
        raw = encode(complete()).replace(b'"sequence":1,', b'"sequence":1,"sequence":1,', 1)
        with self.assertRaisesRegex(AssertionError, 'duplicate JSON key'):
            validate_progress(raw, 'ocr-owned')

    def test_nested_duplicate_json_keys_rejected(self):
        raw = encode(complete()).replace(b'"operation":null', b'"operation":{"x":1,"x":2}', 1)
        with self.assertRaisesRegex(AssertionError, 'duplicate JSON key'):
            validate_progress(raw, 'ocr-owned')

    def test_nonfinite_numbers_rejected(self):
        for value in (b'NaN', b'Infinity', b'-Infinity'):
            raw = encode(complete()).replace(b'"index":0', b'"index":' + value, 1)
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, 'nonfinite'):
                validate_progress(raw, 'ocr-owned')

    def test_nonobject_record_rejected(self):
        for value in (None, [], 1, 'record', True):
            rows = complete()
            rows[0] = value
            self.assert_invalid(rows, 'wrong exact schema')

    def test_missing_field_rejected(self):
        for field in complete()[0]:
            rows = complete()
            del rows[3][field]
            with self.subTest(field=field):
                self.assert_invalid(rows, 'wrong exact schema')

    def test_extra_field_rejected(self):
        rows = complete()
        rows[3]['extra'] = 'ignored?'
        self.assert_invalid(rows, 'wrong exact schema')

    def test_wrong_schema_version_rejected(self):
        rows = complete()
        rows[0]['schema'] = 'cucp.helper-provider-progress/v2'
        self.assert_invalid(rows, 'wrong schema version')

    def test_wrong_record_group_rejected(self):
        rows = complete()
        rows[5]['group'] = 'native'
        self.assert_invalid(rows, 'wrong group')

    def test_invalid_request_and_operation_types_rejected(self):
        for field in ('request', 'operation'):
            for value in (False, 1, [], {}):
                rows = complete()
                rows[2][field] = value
                with self.subTest(field=field, value=value):
                    self.assert_invalid(rows, 'wrong ' + field + ' type')

    def test_unknown_and_wrong_type_phases_rejected(self):
        for phase in ('request.done', '', None, 1, []):
            rows = complete()
            rows[2]['phase'] = phase
            with self.subTest(phase=phase):
                self.assert_invalid(rows, 'unknown phase')

    def test_numeric_fields_reject_booleans_floats_strings_and_negative(self):
        for field in ('sequence', 'index', 'elapsed_ticks', 'request_ticks',
                      'provider_ticks', 'diagnostic_ticks', 'write_ticks', 'frequency'):
            for value in (True, 1.0, '1', -1, None):
                rows = complete()
                rows[2][field] = value
                with self.subTest(field=field, value=value):
                    self.assert_invalid(rows, 'nonnegative integer')

    def test_sequence_must_start_at_one_and_be_contiguous(self):
        for position, sequence in ((0, 0), (0, 2), (3, 3), (3, 5)):
            rows = complete()
            rows[position]['sequence'] = sequence
            with self.subTest(position=position, sequence=sequence):
                self.assert_invalid(rows, 'sequence mismatch')

    def test_frequency_zero_and_change_rejected(self):
        rows = complete()
        rows[0]['frequency'] = 0
        self.assert_invalid(rows, 'frequency must be positive')
        rows = complete()
        rows[2]['frequency'] += 1
        self.assert_invalid(rows, 'frequency changed')

    def test_elapsed_ticks_cannot_decrease_across_requests(self):
        rows = complete()
        rows[9]['elapsed_ticks'] = 1
        self.assert_invalid(rows, 'elapsed_ticks decreased')

    def test_write_ticks_cannot_reset_across_requests(self):
        rows = complete()
        rows[9]['write_ticks'] = 0
        self.assert_invalid(rows, 'write_ticks decreased')

    def test_request_ticks_cannot_exceed_group_elapsed(self):
        rows = complete()
        rows[2]['request_ticks'] = rows[2]['elapsed_ticks'] + 1
        self.assert_invalid(rows, 'request_ticks exceeds elapsed_ticks')

    def test_request_counters_cannot_decrease_inside_request(self):
        for field in ('request_ticks', 'provider_ticks', 'diagnostic_ticks'):
            rows = complete()
            rows[4][field] = rows[3][field] - 1
            with self.subTest(field=field):
                self.assert_invalid(rows, field + ' decreased within request')

    def test_provider_and_diagnostic_total_cannot_exceed_request_ticks(self):
        for provider, diagnostic in ((0, 999999999), (999999999, 0), (600, 600)):
            rows = complete()
            rows[2].update(provider_ticks=provider, diagnostic_ticks=diagnostic)
            with self.subTest(provider=provider, diagnostic=diagnostic):
                self.assert_invalid(rows, 'total exceeds request_ticks')

    def test_write_ticks_cannot_exceed_elapsed_ticks(self):
        rows = complete()
        rows[-1]['write_ticks'] = rows[-1]['elapsed_ticks'] + 1
        self.assert_invalid(rows, 'write_ticks exceeds elapsed_ticks')

    def test_provider_and_diagnostic_counters_start_at_zero(self):
        for phase in ('group.start', 'group.end', 'request.start'):
            for field in ('provider_ticks', 'diagnostic_ticks'):
                rows = complete()
                target = next(row for row in rows if row['phase'] == phase)
                if phase.startswith('group.'):
                    target['request_ticks'] = 10
                target[field] = 1
                with self.subTest(phase=phase, field=field):
                    self.assert_invalid(rows, 'must start/reset at zero')

    def test_request_elapsed_offset_must_be_constant(self):
        for field in ('elapsed_ticks', 'request_ticks'):
            rows = complete()
            rows[4][field] += 1
            with self.subTest(field=field):
                self.assert_invalid(rows, 'request clock offset changed')

    def test_request_start_overhead_may_be_nonzero(self):
        rows = complete()
        self.assertGreater(rows[1]['request_ticks'], 0)
        validate_progress(encode(rows), 'ocr-owned')

    def test_cold_post_dispatch_timing_is_still_request_bounded(self):
        rows = complete('uia-cold')
        target = next(row for row in rows if row['phase'] == 'diagnostics.end')
        target['diagnostic_ticks'] = target['request_ticks']
        self.assert_invalid(rows, 'total exceeds request_ticks', group='uia-cold')

    def test_first_and_last_group_markers_required(self):
        rows = complete()
        self.assert_invalid(order(rows[1:]), 'first record')
        rows = complete()
        self.assert_invalid(order(rows[:-1]), 'last record')

    def test_group_boundaries_must_have_null_request(self):
        for position in (0, -1):
            rows = complete()
            rows[position]['request'] = GROUPS['ocr-owned'][0]
            with self.subTest(position=position):
                self.assert_invalid(rows, 'without a request')

    def test_group_markers_cannot_appear_inside_request(self):
        for phase in ('group.start', 'group.end'):
            rows = complete()
            rows[3]['phase'] = phase
            for row in rows:
                row.update(provider_ticks=0, diagnostic_ticks=0)
            with self.subTest(phase=phase):
                self.assert_invalid(rows, 'unexpected dispatch phase')

    def test_empty_group_cannot_qualify(self):
        rows = complete()
        self.assert_invalid(order([rows[0], rows[-1]]), 'all required requests')

    def test_each_incomplete_prefix_rejected(self):
        rows = complete(inner=INNER)
        for end in range(1, len(rows)):
            with self.subTest(end=end):
                self.assert_invalid(rows[:end])

    def test_early_group_end_cannot_qualify(self):
        rows = complete()
        for end in range(1, len(rows) - 1):
            with self.subTest(end=end):
                self.assert_invalid(order(copy.deepcopy(rows[:end] + [rows[-1]])))

    def test_reordered_or_unknown_request_rejected(self):
        for name in ('wrong', GROUPS['ocr-owned'][1]):
            rows = complete()
            for row in rows[1:9]:
                row['request'] = name
            with self.subTest(name=name):
                self.assert_invalid(rows, 'request order/name mismatch')

    def test_request_cannot_change_or_be_null_midflight(self):
        for name in (None, GROUPS['ocr-owned'][1]):
            rows = complete()
            rows[3]['request'] = name
            with self.subTest(name=name):
                self.assert_invalid(rows, 'request changed')

    def test_extra_duplicate_request_rejected(self):
        rows = complete()
        rows[-1:-1] = copy.deepcopy(rows[1:9])
        self.assert_invalid(order(rows), 'extra request')

    def test_missing_or_reordered_required_outer_phase_rejected(self):
        for position in range(1, 9):
            rows = complete()
            del rows[position]
            with self.subTest(missing_position=position):
                self.assert_invalid(order(rows))
        for position in range(1, 8):
            rows = complete()
            rows[position], rows[position + 1] = rows[position + 1], rows[position]
            with self.subTest(swapped_position=position):
                self.assert_invalid(order(rows))

    def test_coarse_markers_outside_dispatch_rejected(self):
        for phase in ('acquire.start', 'evidence.start', 'diagnostics.start'):
            rows = complete()
            rows[5:5] = [record('ocr-owned', rows[5]['request'], phase)]
            with self.subTest(phase=phase):
                self.assert_invalid(order(rows))

    def test_coarse_end_requires_start(self):
        for category in ('acquire', 'evidence', 'diagnostics'):
            with self.subTest(category=category):
                self.assert_invalid(complete(inner=((category + '.end', 'uia.subtree', 0),)), 'does not match')

    def test_coarse_pairs_require_matching_category_and_operation(self):
        for end in (('evidence.end', 'uia.subtree', 0),
                    ('acquire.end', 'uia.children', 0),
                    ('acquire.end', None, 0)):
            with self.subTest(end=end):
                self.assert_invalid(complete(inner=(('acquire.start', 'uia.subtree', 0), end)), 'does not match')

    def test_crossed_coarse_intervals_rejected(self):
        self.assert_invalid(complete(inner=(('acquire.start', 'uia.subtree', 0),
                                            ('evidence.start', 'uia.subtree', 0),
                                            ('acquire.end', 'uia.subtree', 0),
                                            ('evidence.end', 'uia.subtree', 0))), 'does not match')

    def test_open_coarse_interval_cannot_end_dispatch(self):
        for category in ('acquire', 'evidence', 'diagnostics'):
            with self.subTest(category=category):
                self.assert_invalid(complete(inner=((category + '.start', 'uia.subtree', 0),)), 'open coarse interval')

    def test_diagnostic_progress_requires_diagnostic_interval(self):
        self.assert_invalid(complete(inner=(('diagnostics.progress', 'uia.subtree', 128),)), 'outside diagnostics interval')

    def test_scan_progress_forbidden_during_acquire_or_diagnostics(self):
        for category in ('acquire', 'diagnostics'):
            inner = ((category + '.start', 'uia.subtree', 0),
                     ('scan.progress', 'uia.name', 128),
                     (category + '.end', 'uia.subtree', 0))
            with self.subTest(category=category):
                self.assert_invalid(complete(inner=inner), 'during acquisition or diagnostics')

    def test_scan_and_diagnostic_progress_outside_dispatch_rejected(self):
        for phase in ('scan.progress', 'diagnostics.progress'):
            rows = complete()
            rows[5:5] = [record('ocr-owned', rows[5]['request'], phase)]
            with self.subTest(phase=phase):
                self.assert_invalid(order(rows))

    def test_records_after_group_end_rejected(self):
        rows = complete()
        rows.append(copy.deepcopy(rows[-1]))
        self.assert_invalid(order(rows))

    def test_exact_record_limit_passes(self):
        rows = complete()
        rows[3:3] = [record('ocr-owned', GROUPS['ocr-owned'][0], 'scan.progress', 'uia.name', index)
                     for index in range(MAX_RECORDS - len(rows))]
        order(rows)
        self.assertEqual(len(validate_progress(encode(rows), 'ocr-owned')), MAX_RECORDS)

    def test_record_limit_plus_one_rejected(self):
        rows = complete()
        rows[3:3] = [record('ocr-owned', GROUPS['ocr-owned'][0], 'scan.progress')
                     for _ in range(MAX_RECORDS + 1 - len(rows))]
        self.assert_invalid(order(rows), 'record limit exceeded')

    def test_exact_byte_limit_passes(self):
        rows = complete()
        rows[0]['operation'] = ''
        padding = MAX_BYTES - len(encode(rows))
        rows[0]['operation'] = 'x' * padding
        raw = encode(rows)
        self.assertEqual(len(raw), MAX_BYTES)
        self.assertEqual(len(validate_progress(raw, 'ocr-owned')), len(rows))

    def test_byte_limit_plus_one_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'byte limit exceeded'):
            validate_progress(b' ' * MAX_BYTES + b'\n', 'ocr-owned')


if __name__ == '__main__':
    unittest.main()
