"""Strict, bounded validation of test-only owned-provider progress JSONL.

A retained prefix is useful diagnosis, never qualification. Completion of every
required request and its dispatch/serialization/write lifecycle is mandatory.
These records do not replace provider evidence or certify provider correctness.
"""
from __future__ import annotations

import json

from helper_provider_expectations import GROUPS

SCHEMA = 'cucp.helper-provider-progress/v1'
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 2048
EXPECTED_GROUPS = {**GROUPS, 'uia-cold': ['uia-run']}

_FIELDS = frozenset({
    'schema', 'sequence', 'group', 'request', 'phase', 'operation', 'index',
    'elapsed_ticks', 'request_ticks', 'provider_ticks', 'diagnostic_ticks',
    'write_ticks', 'frequency',
})
_INTEGER_FIELDS = (
    'sequence', 'index', 'elapsed_ticks', 'request_ticks', 'provider_ticks',
    'diagnostic_ticks', 'write_ticks', 'frequency',
)
_REQUEST_TICKS = ('request_ticks', 'provider_ticks', 'diagnostic_ticks')
_COARSE = frozenset({'acquire', 'evidence', 'diagnostics'})
_UIA_INTERVALS = (
    ('acquire', 'uia.root'), ('acquire', 'uia.children'),
    ('acquire', 'uia.subtree'), ('evidence', 'uia.subtree'),
    ('diagnostics', 'uia.subtree'),
)
_UIA_MARKERS = tuple((category + '.' + edge, operation)
                     for category, operation in _UIA_INTERVALS
                     for edge in ('start', 'end'))
_PHASES = frozenset(
    f'{name}.{edge}'
    for name in ('group', 'request', 'dispatch', 'acquire', 'evidence',
                 'diagnostics', 'serialize', 'write')
    for edge in ('start', 'end')
) | {'diagnostics.progress', 'scan.progress'}


def _require(condition, message):
    if not condition:
        raise AssertionError('Invalid helper-provider progress: ' + message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _reject_constant(value):
    raise AssertionError('Invalid helper-provider progress: nonfinite JSON number ' + value)


def validate_progress(raw: bytes, group: str) -> list[dict]:
    """Return complete ordered records, or raise AssertionError (including limits).

    The current record's write cost is not yet in ``write_ticks``. Therefore
    group elapsed/write counters are checked for monotonicity, not equality.
    Request counters may reset only when a new request starts; group boundary
    records have no active request and are excluded from request monotonicity.
    """
    _require(type(group) is str and group in EXPECTED_GROUPS, 'unknown expected group')
    _require(type(raw) is bytes and bool(raw), 'missing bytes')
    _require(len(raw) <= MAX_BYTES, 'byte limit exceeded')
    _require(raw.endswith(b'\n'), 'truncated or unterminated final record')
    try:
        contents = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise AssertionError('Invalid helper-provider progress: non-UTF-8 bytes') from error
    lines = contents.split('\n')[:-1]
    _require(len(lines) <= MAX_RECORDS, 'record limit exceeded')
    records = []
    frequency = None
    elapsed = write_ticks = 0
    for number, line in enumerate(lines, 1):
        _require(bool(line.strip()), f'blank record at line {number}')
        try:
            row = json.loads(line, object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
        except (ValueError, RecursionError) as error:
            raise AssertionError(f'Invalid helper-provider progress: malformed JSON at line {number}') from error
        _require(type(row) is dict and set(row) == _FIELDS,
                 f'wrong exact schema at line {number}')
        _require(row['schema'] == SCHEMA, f'wrong schema version at line {number}')
        _require(row['group'] == group, f'wrong group at line {number}')
        _require(row['request'] is None or type(row['request']) is str,
                 f'wrong request type at line {number}')
        _require(type(row['phase']) is str and row['phase'] in _PHASES,
                 f'unknown phase at line {number}')
        _require(row['operation'] is None or type(row['operation']) is str,
                 f'wrong operation type at line {number}')
        for key in _INTEGER_FIELDS:
            _require(type(row[key]) is int and row[key] >= 0,
                     f'{key} must be a nonnegative integer at line {number}')
        _require(row['sequence'] == number, f'sequence mismatch at line {number}')
        _require(row['frequency'] > 0, f'frequency must be positive at line {number}')
        if frequency is None:
            frequency = row['frequency']
        _require(row['frequency'] == frequency, f'frequency changed at line {number}')
        _require(row['elapsed_ticks'] >= elapsed, f'elapsed_ticks decreased at line {number}')
        _require(row['write_ticks'] >= write_ticks, f'write_ticks decreased at line {number}')
        _require(row['request_ticks'] <= row['elapsed_ticks'],
                 f'request_ticks exceeds elapsed_ticks at line {number}')
        _require(row['write_ticks'] <= row['elapsed_ticks'],
                 f'write_ticks exceeds elapsed_ticks at line {number}')
        _require(row['provider_ticks'] + row['diagnostic_ticks'] <= row['request_ticks'],
                 f'provider/diagnostic total exceeds request_ticks at line {number}')
        if row['phase'] in {'group.start', 'group.end', 'request.start'}:
            _require(row['provider_ticks'] == row['diagnostic_ticks'] == 0,
                     f'provider/diagnostic counters must start/reset at zero at line {number}')
        elapsed, write_ticks = row['elapsed_ticks'], row['write_ticks']
        records.append(row)

    _require(records[0]['phase'] == 'group.start' and records[0]['request'] is None,
             'first record must be group.start without a request')
    _require(records[-1]['phase'] == 'group.end' and records[-1]['request'] is None,
             'last record must be group.end without a request')
    required = EXPECTED_GROUPS[group]
    completed = 0
    current = None
    state = 'request.start'
    coarse = []
    uia_markers = []
    previous_ticks = None
    request_offset = None
    for row in records[1:-1]:
        phase = row['phase']
        if state == 'request.start':
            _require(phase == state, f'expected request.start, got {phase}')
            _require(completed < len(required), 'extra request after required group')
            _require(row['request'] == required[completed], 'request order/name mismatch')
            current = row['request']
            previous_ticks = {key: row[key] for key in _REQUEST_TICKS}
            request_offset = row['elapsed_ticks'] - row['request_ticks']
            uia_markers = []
            state = 'dispatch.start'
            continue

        _require(row['request'] == current, 'request changed before request.end')
        for key in _REQUEST_TICKS:
            _require(row[key] >= previous_ticks[key], f'{key} decreased within request {current}')
        _require(row['elapsed_ticks'] - row['request_ticks'] == request_offset,
                 f'request clock offset changed within request {current}')
        previous_ticks = {key: row[key] for key in _REQUEST_TICKS}
        if state == 'dispatch':
            category, edge = phase.split('.')
            _require(group != 'uia-cold' or category != 'diagnostics',
                     'cold diagnostics must follow dispatch.end')
            if (category, row['operation']) in _UIA_INTERVALS and edge in {'start', 'end'}:
                uia_markers.append((phase, row['operation']))
            if category in _COARSE and edge == 'start':
                coarse.append((category, row['operation']))
            elif category in _COARSE and edge == 'end':
                _require(bool(coarse) and coarse[-1] == (category, row['operation']),
                         'coarse phase end does not match its start/operation')
                coarse.pop()
            elif phase == 'diagnostics.progress':
                _require(any(item[0] == 'diagnostics' for item in coarse),
                         'diagnostics.progress outside diagnostics interval')
            elif phase == 'scan.progress':
                _require(not any(item[0] in {'acquire', 'diagnostics'} for item in coarse),
                         'scan.progress during acquisition or diagnostics')
            elif phase == 'dispatch.end':
                _require(not coarse, 'dispatch ended with an open coarse interval')
                state = 'diagnostics.start' if group == 'uia-cold' else 'serialize.start'
            else:
                raise AssertionError('Invalid helper-provider progress: unexpected dispatch phase ' + phase)
            continue

        if state == 'diagnostics':
            _require(phase in {'diagnostics.progress', 'diagnostics.end'},
                     'unexpected phase inside cold diagnostics interval')
            if phase == 'diagnostics.end':
                _require(row['operation'] == 'uia.subtree',
                         'cold diagnostics end does not match its start/operation')
                uia_markers.append((phase, row['operation']))
                state = 'serialize.start'
            continue

        if state == 'diagnostics.start':
            _require(phase == state and row['operation'] == 'uia.subtree',
                     'cold request requires post-dispatch diagnostics.start for uia.subtree')
            uia_markers.append((phase, row['operation']))
            state = 'diagnostics'
            continue

        _require(phase == state, f'expected {state}, got {phase}')
        following = {
            'dispatch.start': 'dispatch',
            'serialize.start': 'serialize.end',
            'serialize.end': 'write.start',
            'write.start': 'write.end',
            'write.end': 'request.end',
            'request.end': 'request.start',
        }
        state = following[state]
        if phase == 'request.end':
            if group in {'uia', 'uia-cold'} and current not in {'uia-missing', 'health-uia'}:
                _require(tuple(uia_markers) == _UIA_MARKERS,
                         'required UIA acquisition/evidence/diagnostics markers missing, repeated, or out of order')
            completed += 1
            current = None
            previous_ticks = None

    _require(state == 'request.start' and current is None and not coarse,
             'group ended during an incomplete request')
    _require(completed == len(required), 'group did not complete all required requests')
    return records
