"""Narrow classification of observed original Args-binding failures.

The original source stays failed/unqualified. Corrected-intent action results
are a different evidence stream and cannot be accepted by this classifier.
"""
import hashlib
import json
import math
from pathlib import Path

from helper_process_evidence import require_success
from test_legacy_helper_source import FIXTURES, MANIFEST, expected_type_seam

OBSERVATION = FIXTURES / 'observed-binding.stdout.bin'
OBSERVED_SHA256 = '4d7cfb0b5de6c4d76e0685c6d5ff84d7e0c2d29f90590f79646cb444ad99521f'
PROBE_SHA256 = '624ae0d920be21d9a47dcaf0ff4d35529bc7cab872b744cdea8a8f2361bb0b86'
PIN_SHA256 = 'dde5878288ea0420701344a9169b76fadf382ea36f2daddec09abe01c9aac25b'
MESSAGE = ('Cannot convert the "System.Object[]" value of type "System.Object[]" '
           'to type "System.Collections.Hashtable".')
INPUTS = {
    'direct-empty': {}, 'direct-values': {'Label': 'Save', 'Flag': False},
    'converted-empty': {}, 'converted-values': {'Label': 'Save', 'Flag': False},
    'converted-nested': {'Nested': {'Empty': {}, 'Values': [{'Label': 'Save'}, [], None, False]}},
}
COMMANDS = {
    'synthetic-automatic': 'Invoke-AutomaticArgsProbe',
    'synthetic-named': 'Invoke-NamedParameterProbe',
    'original-health': '_Action-Health',
    'original-dispatch-health': '_Dispatch',
    'original-dispatch-shutdown': '_Dispatch',
    'original-dispatch-unsupported': '_Dispatch',
}


def _json(raw):
    def members(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AssertionError('Duplicate member in original binding evidence')
            result[key] = value
        return result
    def reject(value):
        raise AssertionError('Nonfinite original binding evidence')
    def finite(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            reject(value)
        return parsed
    return json.loads(raw.decode('utf-8-sig', errors='strict'), object_pairs_hook=members,
                      parse_constant=reject, parse_float=finite)


def _same(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _source(source):
    raw = Path(source).read_bytes()
    pin = MANIFEST['files'][0]
    normalized = raw.decode('utf-8-sig').replace('\r\n', '\n').encode()
    if (len(raw) != pin['raw_bytes'] or hashlib.sha256(raw).hexdigest() != pin['raw_sha256']
            or hashlib.sha256(normalized).hexdigest() != pin['normalized_sha256']):
        raise AssertionError('Original binding source pin changed')
    return raw


def _raw(result):
    require_success(result)
    evidence = Path(result['evidence_path'])
    for name in ('stdout', 'stderr'):
        raw = result[name]
        if (result['bytes_observed'][name] != len(raw) or len(raw) > 2 * 1024 * 1024
                or evidence.with_suffix('.' + name + '.bin').read_bytes() != raw):
            raise AssertionError('Original binding raw evidence is incomplete or changed')
    if result['stderr']:
        raise AssertionError('Unexpected original binding stderr')
    return _json(result['stdout'])


def retained_binding_observation():
    raw = OBSERVATION.read_bytes()
    pin_text = (FIXTURES / 'observed-binding.json').read_text(encoding='utf-8')
    pin = json.loads(pin_text)
    probe = (FIXTURES / 'binding-probe.ps1').read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()
    if (hashlib.sha256(pin_text.encode()).hexdigest() != PIN_SHA256
            or len(raw) != 34021 or hashlib.sha256(raw).hexdigest() != OBSERVED_SHA256
            or pin['stdout_bytes'] != len(raw) or pin['stdout_sha256'] != OBSERVED_SHA256
            or pin['probe_normalized_sha256'] != PROBE_SHA256
            or hashlib.sha256(probe).hexdigest() != PROBE_SHA256):
        raise AssertionError('Retained original binding evidence or probe changed')
    return _json(raw)


def _probe(data):
    if (not isinstance(data, dict)
            or set(data) != {'schema', 'powershell_version', 'source_sha256', 'functions', 'observations'}
            or data.get('schema') != 'cucp.helper-binding-probe/v1'
            or not isinstance(data.get('powershell_version'), str)
            or not data['powershell_version'].startswith('5.1.')
            or data.get('source_sha256') != MANIFEST['files'][0]['normalized_sha256']):
        raise AssertionError('Unexpected original binding probe provenance')
    functions = [dict(name=f['name'], sha256=f['sha256']) for f in MANIFEST['files'][0]['functions']
                 if f['name'] in ('_Action-Health', '_Dispatch')]
    if data.get('functions') != functions:
        raise AssertionError('Original binding function pins changed')
    observations = data.get('observations')
    if not isinstance(observations, list) or len(observations) != 30:
        raise AssertionError('Original binding observation count changed')
    seen = set()
    for item in observations:
        if not isinstance(item, dict) or set(item) != {'input', 'input_type', 'input_value', 'target',
                                                       'body_entered', 'request_count', 'result', 'error'}:
            raise AssertionError('Original binding observation fields changed')
        identity = (item.get('input'), item.get('target'))
        if identity in seen or identity[0] not in INPUTS or identity[1] not in COMMANDS:
            raise AssertionError('Original binding observation identity changed')
        seen.add(identity)
        expected = INPUTS[identity[0]]
        if (item.get('input_type') != 'System.Collections.Hashtable' or not _same(item.get('input_value'), expected)
                or type(item.get('request_count')) is not int or item['request_count'] != 0):
            raise AssertionError('Original binding input or dispatch effect changed')
        if identity[1] == 'synthetic-named':
            wanted = dict(received_type='System.Collections.Hashtable', bound_type='System.Collections.Hashtable',
                          count=len(expected), received=expected)
            if (item.get('error') is not None or type(item.get('body_entered')) is not int
                    or item['body_entered'] != 1 or not _same(item.get('result'), wanted)):
                raise AssertionError('Safe named-parameter control did not succeed')
            continue
        error = item.get('error')
        command = COMMANDS[identity[1]]
        if (item.get('result') is not None or type(item.get('body_entered')) is not int
                or item['body_entered'] != 0 or not isinstance(error, dict)
                or set(error) != {'record_type', 'exception_type', 'inner_exception_type',
                                  'fully_qualified_error_id', 'message', 'category', 'target_type',
                                  'invocation', 'script_stack_trace'}
                or error.get('record_type') != 'System.Management.Automation.ErrorRecord'
                or error.get('exception_type') != 'System.Management.Automation.PSInvalidCastException'
                or error.get('inner_exception_type') is not None
                or error.get('fully_qualified_error_id') != 'ConvertToFinalInvalidCastException,' + command
                or error.get('message') != MESSAGE or error.get('category') != 'InvalidArgument'
                or error.get('target_type') is not None):
            raise AssertionError('Unexpected original binding failure')
        invocation = error.get('invocation')
        if (not isinstance(invocation, dict) or set(invocation) != {'command', 'line', 'position', 'script_line', 'offset'}
                or invocation.get('command') != command
                or type(invocation.get('script_line')) is not int or invocation['script_line'] <= 0
                or type(invocation.get('offset')) is not int or invocation['offset'] <= 0):
            raise AssertionError('Original binding invocation evidence changed')
        for value in (invocation.get('line'), invocation.get('position'), error.get('script_stack_trace')):
            if not isinstance(value, str) or not value or len(value.encode('utf-16-le')) > 4096:
                raise AssertionError('Original binding diagnostic text is absent or unbounded')
    return data


def _classification(result, *, kind, requests):
    return dict(schema='cucp.helper-binding-observation/v1', status='baseline-argument-binding-defect',
                raw_oracle_status='failed', original_dispatch_qualified=False, evidence_kind=kind,
                source_raw_sha256=MANIFEST['files'][0]['raw_sha256'],
                observed_binding_sha256=OBSERVED_SHA256, observed_requests=requests,
                observed_exit_code=result['exit_code'], dispatch_count=0, acquisition_count=0,
                stdout_sha256=hashlib.sha256(result['stdout']).hexdigest(), raw_evidence=result['evidence_path'],
                impact='Corrected-intent comparison exercises documented actions that the original Args parameter prevents from entering.')


def classify_binding_probe(result, *, source):
    _source(source)
    _probe(retained_binding_observation())
    _probe(_raw(result))
    return _classification(result, kind='unchanged-original-binding-probe', requests=20)


def classify_original_actions(result, *, case, source):
    raw = _source(source)
    _probe(retained_binding_observation())
    data = _raw(result)
    if (not isinstance(data, dict) or set(data) != {'oracle_mode', 'args_seam', 'oracle_seam',
                                                   'responses', 'calls', 'effects', 'request_count'}):
        raise AssertionError('Original action evidence fields changed')
    seam = data.get('oracle_seam')
    if (not isinstance(seam, dict) or set(seam) != {'schema', 'source_sha256', 'facade_sha256',
                                                   'type_substitutions', 'guarded_types', 'functions'}):
        raise AssertionError('Original action type seam missing')
    try:
        seam = dict(seam, guarded_types=sorted(seam['guarded_types']),
                    type_substitutions=sorted(seam['type_substitutions'], key=lambda s: s['start_utf16']))
    except (KeyError, TypeError):
        raise AssertionError('Malformed original action type seam') from None
    if (seam != expected_type_seam(raw) or data.get('oracle_mode') != 'exact-original'
            or data.get('args_seam') is not None):
        raise AssertionError('Corrected or changed oracle cannot classify as original binding evidence')
    requests = case['requests']
    if (not isinstance(data.get('calls'), list) or data['calls'] != []
            or data.get('effects') != [] or type(data.get('request_count')) is not int or data['request_count'] != 0
            or not isinstance(data.get('responses'), list) or len(data['responses']) != len(requests)
            or not requests):
        raise AssertionError('Original action dispatch/acquisition effects changed')
    for request, response in zip(requests, data['responses']):
        expected = dict(id=request.get('id'), exit_code=1, result=None, error=MESSAGE)
        if not _same(response, expected):
            raise AssertionError('Unexpected original action binding result')
    return _classification(result, kind='type-isolated-original-actions', requests=len(requests))
