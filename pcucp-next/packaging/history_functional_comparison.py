"""Additional history comparison; never replaces the exact gate or changes evidence."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

SCHEMA = 'cucp.history-functional-comparison/v1'
POLICY = 'caller-backed-history-values/v1'
FIELDS = ('wire', 'compact_json', 'compact_json_items', 'console', 'errors')
CATEGORIES = ('exact', 'allowed-representation', 'data-selection-or-shape',
              'caller-visible-serialization', 'console-or-error')
NUMERIC_TYPES = frozenset(('Byte', 'SByte', 'Int16', 'UInt16', 'Int32', 'UInt32',
                           'Int64', 'UInt64', 'BigInteger', 'Decimal', 'Single', 'Double'))
EXPECTED_RUNS = {(runtime, batch, repeat) for runtime in ('ps51', 'ps7')
                 for batch, repeat in (('singleton', 0), ('many', 0), ('many', 1))}


class NonFinite(str):
    """Keep original PS5 non-standard JSON tokens distinct from JSON strings."""


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate JSON member: ' + name)
        result[name] = value
    return result


def parse_json(raw):
    # Never route numbers through binary float or permit replacement decoding.
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'strict')
    return json.loads(raw, parse_float=Decimal, parse_constant=NonFinite,
                      object_pairs_hook=unique_object)


def read_bounded(path, limit=64 * 1024 * 1024):
    if path.stat().st_size > limit:
        raise ValueError('Oversized evidence: ' + path.name)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Evidence grew beyond limit: ' + path.name)
    return raw


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def numeric(value):
    return type(value) in (int, Decimal)


def valid_count(value):
    return numeric(value) and value >= 0 and (type(value) is int or value == value.to_integral_value())


def equal_json(left, right, operation, path=()):
    """Only the stats strategies map is unordered; all other maps stay ordered."""
    if numeric(left) and numeric(right):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if operation == 'stats' and path == ('strategies',):
            if not all(valid_count(value) for value in (*left.values(), *right.values())):
                raise ValueError('Malformed stats strategy-count map')
            if left.keys() != right.keys():
                return False
        elif list(left) != list(right):
            return False
        return all(equal_json(left[key], right[key], operation, path + (key,)) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal_json(a, b, operation, path + (index,))
                                              for index, (a, b) in enumerate(zip(left, right)))
    return left == right


def wire_value(wire, operation, path=()):
    """Validate the diagnostic wire and discard only numeric CLR-width tags."""
    if not isinstance(wire, dict) or 'kind' not in wire:
        raise ValueError('Malformed typed wire')
    kind = wire['kind']
    if kind == 'null' and set(wire) == {'kind'}:
        return ('null',)
    if kind == 'array' and set(wire) == {'kind', 'items'} and isinstance(wire['items'], list):
        return ('array', tuple(wire_value(v, operation, path + (i,)) for i, v in enumerate(wire['items'])))
    if kind in ('object', 'hashtable') and set(wire) == {'kind', 'properties'} and isinstance(wire['properties'], list):
        pairs = []
        for item in wire['properties']:
            if not isinstance(item, dict) or set(item) != {'name', 'value'} or type(item['name']) is not str:
                raise ValueError('Malformed wire property')
            pairs.append((item['name'], wire_value(item['value'], operation, path + (item['name'],))))
        members = unique_object(pairs)
        if operation == 'stats' and path == ('strategies',) and kind == 'hashtable':
            if not all(value[0] == 'number' and valid_count(value[1]) for value in members.values()):
                raise ValueError('Malformed typed stats strategy-count map')
            return (kind, members)
        return (kind, tuple(pairs))
    if kind != 'scalar' or set(wire) != {'kind', 'type', 'value'}:
        raise ValueError('Malformed wire kind/fields')
    tag, value = wire['type'], wire['value']
    if tag in NUMERIC_TYPES:
        if numeric(value):
            return ('number', value)
        if tag in ('Single', 'Double') and type(value) in (str, NonFinite) and value in ('NaN', 'Infinity', '-Infinity'):
            return ('nonfinite-number', str(value))
        raise ValueError('Malformed numeric scalar')
    if tag == 'Boolean' and type(value) is bool:
        return (tag, value)
    if tag in ('String', 'DateTime') and type(value) is str:
        return (tag, value)
    raise ValueError('Unknown or malformed scalar tag')


def emissions(result):
    items = result.get('compact_json_items')
    if not isinstance(items, list) or len(items) > 1 or any(type(item) is not str for item in items):
        raise ValueError('Malformed converter output cardinality')
    if (not items and result.get('compact_json') is not None) or (items and result.get('compact_json') != items[0]):
        raise ValueError('Inconsistent converter output capture')
    return [parse_json(item) for item in items]


def compare_result(left, right):
    """Return disjoint classification plus every retained functional field failure."""
    required = {'id', 'operation', *FIELDS}
    if set(left) != required or set(right) != required or left['id'] != right['id'] or left['operation'] != right['operation']:
        raise ValueError('Result identity/shape mismatch')
    operation = left['operation']
    if operation not in ('pick', 'stats', 'app-read', 'last-good'):
        raise ValueError('Unknown reducer operation')
    for result in (left, right):
        if type(result['id']) is not str or type(result['console']) is not str or not isinstance(result['errors'], list) or any(type(e) is not str for e in result['errors']):
            raise ValueError('Malformed result text/errors')
    failures = []
    def result_wire(result):
        if result['wire'] is None and result['errors']:
            return ('error-no-value',)
        return wire_value(result['wire'], operation)
    if result_wire(left) != result_wire(right):
        failures.append('wire')
    a, b = emissions(left), emissions(right)
    if len(a) != len(b) or any(not equal_json(x, y, operation) for x, y in zip(a, b)):
        failures.extend(('compact_json', 'compact_json_items'))
    for field in ('console', 'errors'):
        if left[field] != right[field]:
            failures.append(field)
    raw = [field for field in FIELDS if left[field] != right[field]]
    category = ('data-selection-or-shape' if 'wire' in failures else
                'caller-visible-serialization' if 'compact_json' in failures else
                'console-or-error' if failures else 'allowed-representation' if raw else 'exact')
    return dict(id=left['id'], operation=operation, category=category,
                functional_fields=failures, raw_fields=raw)


def compare_reports(left, right):
    if not isinstance(left.get('results'), list) or not isinstance(right.get('results'), list) or len(left['results']) != len(right['results']):
        raise ValueError('Mismatched result counts')
    ids = [row.get('id') for row in left['results']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate result IDs')
    return [compare_result(a, b) for a, b in zip(left['results'], right['results'])]


def counts(rows):
    result = {category: sum(row['category'] == category for row in rows) for category in CATEGORIES}
    return dict(total=len(rows), functional_blockers=sum(bool(row['functional_fields']) for row in rows), **result)


def _process(directory, prefix, raw):
    metadata = parse_json(read_bounded(directory / (prefix + '.process.json'), 1024 * 1024))
    stdout = read_bounded(directory / (prefix + '.stdout.bin'))
    stderr = read_bounded(directory / (prefix + '.stderr.bin'), 1024 * 1024)
    expected = {'command', 'exit_code', 'timed_out', 'launch_error', 'stdout_truncated', 'stderr_truncated',
                'stdout_artifact', 'stdout_bytes', 'stderr_bytes', 'stdout_sha256', 'stderr_sha256'}
    if (set(metadata) != expected or not isinstance(metadata['command'], list) or not metadata['command']
            or any(type(arg) is not str for arg in metadata['command']) or type(metadata.get('exit_code')) is not int or metadata['exit_code'] != 0 or metadata.get('launch_error') is not None
            or any(metadata.get(key) is not False for key in ('timed_out', 'stdout_truncated', 'stderr_truncated'))
            or metadata.get('stdout_artifact') != prefix + '.stdout.bin'
            or stdout != raw or stderr or metadata.get('stdout_bytes') != len(stdout) or metadata.get('stderr_bytes') != 0
            or metadata.get('stdout_sha256') != sha256(stdout) or metadata.get('stderr_sha256') != sha256(stderr)):
        raise ValueError('Incomplete or changed process evidence: ' + prefix)


def analyze(directory, history):
    """Read all six existing runs; validation failures cannot become empty passes."""
    raw_report = read_bounded(directory / 'report.json', 1024 * 1024)
    exact = parse_json(raw_report)
    if (exact.get('schema') != 'cucp.history-reducer-gate/v1' or exact.get('status') not in ('failed-parity', 'passed-candidate-parity')
            or exact.get('production_cutover') is not False or exact.get('errors') != [] or exact.get('fixture_count') != 465
            or exact.get('source_sha256') != history.SOURCE_SHA256 or exact.get('manifest_sha256') != history.ORIGINAL_SHA256):
        raise ValueError('Blocked or unrecognized exact source report')
    runs = exact.get('runs', [])
    identities = [(r.get('runtime'), r.get('batch'), r.get('repeat')) for r in runs]
    if len(identities) != 6 or any(type(r.get('repeat')) is not int for r in runs) or set(identities) != EXPECTED_RUNS:
        raise ValueError('All six unique fresh-process runs are required')
    sources = exact.get('candidate_source_sha256')
    if not isinstance(sources, dict) or not sources or any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in sources.values()):
        raise ValueError('Missing candidate source hashes')
    if not re.fullmatch(r'[0-9a-f]{64}', exact.get('oracle_source_sha256', '')):
        raise ValueError('Missing oracle source hash')
    cases = history.fixtures()
    full_input = read_bounded(directory / 'input.json', 16 * 1024 * 1024)
    if len(cases) != 465 or full_input != history.input_bytes(cases) or sha256(full_input) != exact.get('input_sha256'):
        raise ValueError('Changed pinned full input')
    if sha256(read_bounded(directory / 'original-git-source.stdout.ps1', 2 * 1024 * 1024)) != history.SOURCE_SHA256:
        raise ValueError('Changed original source bytes')
    output = dict(schema=SCHEMA, policy=POLICY, status='blocked', production_cutover=False,
                  comparator_sha256=sha256(read_bounded(Path(__file__))),
                  analysis_harness_sha256=sha256(read_bounded(Path(history.__file__))),
                  caller_roundtrip_qualified=False, exact_status=exact['status'], exact_report_sha256=sha256(raw_report),
                  source_sha256=exact['source_sha256'], manifest_sha256=exact['manifest_sha256'], input_sha256=exact['input_sha256'],
                  oracle_source_sha256=exact['oracle_source_sha256'], candidate_source_sha256=sources,
                  categories=list(CATEGORIES), runs=[], original_repeats=[])
    originals = {}
    for run in runs:
        runtime, batch, repeat = run['runtime'], run['batch'], run['repeat']
        prefix = f'{runtime}-{batch}-{repeat}'
        subset = cases[:1] if batch == 'singleton' else cases
        data = read_bounded(directory / f'{runtime}-{batch}-input.json', 16 * 1024 * 1024)
        if data != history.input_bytes(subset) or run.get('count') != len(subset):
            raise ValueError('Changed per-run input/count')
        if not run.get('observed_host', {}).get('ps_version', '').startswith('5.1.' if runtime == 'ps51' else '7.'):
            raise ValueError('Missing actual host identity')
        loaded, raw_loaded = {}, {}
        for kind in ('candidate', 'observed'):
            raw = read_bounded(directory / f'{prefix}-{kind}.raw.json')
            if sha256(raw) != run.get(kind + '_sha256'):
                raise ValueError('Changed raw output hash')
            _process(directory, prefix + '-' + kind, raw)
            loaded[kind] = parse_json(raw)
            # Keep the historical exact comparator and numeric parser untouched.
            raw_loaded[kind] = json.loads(raw)
            history.validate_report(loaded[kind], subset, runtime, observation=kind == 'observed',
                                    source_hash=history.SOURCE_SHA256, manifest_hash=history.ORIGINAL_SHA256, input_hash=sha256(data))
        raw_mismatch_bytes = read_bounded(directory / (prefix + '-mismatches.json'))
        parse_json(raw_mismatch_bytes)  # Reject duplicate members/invalid UTF-8 before historical parsing.
        raw_mismatches = json.loads(raw_mismatch_bytes)
        if raw_mismatches != history.compare_reports(raw_loaded['candidate'], raw_loaded['observed']) or len(raw_mismatches) != run.get('mismatch_count'):
            raise ValueError('Historical raw mismatch evidence changed')
        rows = compare_reports(loaded['candidate'], loaded['observed'])
        output['runs'].append(dict(runtime=runtime, batch=batch, repeat=repeat, count=len(subset),
                                  candidate_sha256=run['candidate_sha256'], observed_sha256=run['observed_sha256'],
                                  raw_mismatches_sha256=sha256(raw_mismatch_bytes), raw_mismatch_count=len(raw_mismatches),
                                  raw_affected_cases=len({m['id'] for m in raw_mismatches}), counts=counts(rows), cases=rows))
        if batch == 'many':
            originals[(runtime, repeat)] = loaded['observed']
    expected_status = 'failed-parity' if any(r['raw_mismatch_count'] for r in output['runs']) else 'passed-candidate-parity'
    if exact['status'] != expected_status:
        raise ValueError('Exact status contradicts its unchanged mismatch evidence')
    for runtime in ('ps51', 'ps7'):
        rows = compare_reports(originals[(runtime, 0)], originals[(runtime, 1)])
        output['original_repeats'].append(dict(runtime=runtime, counts=counts(rows), changed_cases=[r for r in rows if r['raw_fields'] or r['functional_fields']]))
    output['status'] = 'failed-functional-parity' if any(r['counts']['functional_blockers'] for r in output['runs']) else 'passed-functional-candidate-only'
    return output


def write_report(directory, output_path, history):
    # Exclusive creation prevents overwriting either the originals or earlier analysis.
    report = dict(schema=SCHEMA, policy=POLICY, status='blocked', production_cutover=False, caller_roundtrip_qualified=False)
    try:
        report = analyze(Path(directory), history)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ArithmeticError) as error:
        report['error'] = str(error)
    with Path(output_path).open('x', encoding='utf-8', errors='strict') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('history_functional_fixture', root / 'tests/python/test_legacy_history_reducers.py')
    history = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = history
    spec.loader.exec_module(history)
    result = write_report(Path(args.evidence_dir), Path(args.output), history)
    print(json.dumps({key: result[key] for key in ('schema', 'status', 'production_cutover')}))
    return 0 if result['status'] == 'passed-functional-candidate-only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
