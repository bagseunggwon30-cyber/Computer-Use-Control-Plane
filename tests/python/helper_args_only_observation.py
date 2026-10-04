"""Retain Args-only observations without qualifying broken sort/OCR behavior.

Only this diagnostic classifier compares candidate-member permutations. The
functional tier and actual candidate comparisons require exact stable order.
"""
from collections import Counter
import copy
import hashlib
import json
import ntpath
import re

from helper_binding_observation import _json, _raw, _same, _source
from test_legacy_helper_source import FIXTURES, expected_args_seam, expected_type_seam

OBSERVATIONS = FIXTURES / 'observed-args-only'
MANIFEST_SHA256 = '8ff93e51791afbcd923648df267a5a7de92c9324f7ff29d8071596b3c370b332'
OCR_CASE = 'ocr-success-truthiness-cache'
ASSEMBLY_DIAGNOSTIC = re.compile(
    r'Cannot convert the "System.Threading.Tasks.Task`1\[CucpFixture.Windows.Storage.StorageFile\]" '
    r'value of type "System.Threading.Tasks.Task`1\[\[CucpFixture.Windows.Storage.StorageFile, '
    r'(?P<assembly>[A-Za-z0-9_]{1,128}), Version=0\.0\.0\.0, Culture=neutral, PublicKeyToken=null\]\]" '
    r'to type "System.Type"\.')


def _manifest():
    text = (OBSERVATIONS / 'manifest.json').read_text(encoding='utf-8')
    if hashlib.sha256(text.encode()).hexdigest() != MANIFEST_SHA256:
        raise AssertionError('Args-only observation manifest changed')
    return json.loads(text)


def args_only_case_ids():
    return frozenset(record['case_id'] for record in _manifest()['files'])


def retained_args_only(case):
    records = [record for record in _manifest()['files'] if record['case_id'] == case['id']]
    digest = hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    if len(records) != 1 or records[0]['case_sha256'] != digest:
        raise AssertionError('Args-only fixture has no unchanged recorded baseline')
    record = records[0]
    raw = (OBSERVATIONS / record['file']).read_bytes()
    if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise AssertionError('Retained Args-only raw evidence changed')
    return _json(raw), record


def _seams(data, raw):
    if (not isinstance(data, dict) or set(data) != {'oracle_mode', 'args_seam', 'oracle_seam',
                                                    'responses', 'calls', 'effects', 'request_count'}
            or data['oracle_mode'] != 'corrected-intent'):
        raise AssertionError('Expected the unchanged Args-only observation mode')
    try:
        typed = copy.deepcopy(data['oracle_seam'])
        typed['guarded_types'].sort()
        typed['type_substitutions'].sort(key=lambda site: site['start_utf16'])
        args = copy.deepcopy(data['args_seam'])
        args['args_substitutions'].sort(key=lambda site: site['start_utf16'])
    except (KeyError, TypeError, AttributeError):
        raise AssertionError('Malformed Args-only source seam') from None
    if not _same(typed, expected_type_seam(raw)) or not _same(args, expected_args_seam(raw)):
        raise AssertionError('Args-only source or edit seam changed')
    data['oracle_seam'], data['args_seam'] = typed, args


def _generated_ocr(data):
    """Normalize only two generated path identities and one diagnostic assembly.

    The raw process streams remain unchanged on disk. All uses of each generated
    filename must correspond to its capture/load/cleanup trace, and the assembly
    substitution is confined to the complete known Task-to-Type error message.
    """
    calls = data.get('calls')
    if not isinstance(calls, list):
        raise AssertionError('Malformed OCR observation trace')
    paths = [call.get('value') for call in calls if isinstance(call, dict) and call.get('op') == 'ocr.tempPath']
    identities, parents, generated_ids = [], [], []
    for path in paths:
        if not isinstance(path, str) or any(ord(char) < 32 or ord(char) == 127 for char in path):
            raise AssertionError('Generated OCR path contains invalid characters')
        try:
            length = len(path.encode('utf-16-le')) // 2
        except UnicodeError:
            raise AssertionError('Generated OCR path is not valid UTF-16') from None
        match = re.fullmatch(r'[A-Za-z]:[\\/].*[\\/]cucp-srv-ocr-([0-9a-f]{32})\.png', path)
        if length > 32767 or match is None:
            raise AssertionError('Generated OCR path is outside the bounded filename shape')
        # Lexical Windows identity only: these inert fixtures create no image
        # file, and no claim about native file IDs, links or short names is made.
        identity = ntpath.normcase(ntpath.normpath(path))
        identities.append(identity)
        parents.append(ntpath.dirname(identity))
        generated_ids.append(match[1])
    if (len(paths) != 2 or len(set(identities)) != 2 or len(set(generated_ids)) != 2
            or len(set(parents)) != 1):
        raise AssertionError('Unexpected generated OCR path identity/count')
    names = {path: '<generated-ocr-path-' + str(index) + '>' for index, path in enumerate(paths)}
    uses = {path: Counter() for path in paths}
    for call in calls:
        op = call.get('op')
        if op == 'ocr.tempPath':
            path = call.get('value')
            uses[path][op] += 1
            call['value'] = names[path]
        elif op in ('ocr.capture', 'ocr.loadFile', 'ocr.removeTemp'):
            args = call.get('args')
            index = 4 if op == 'ocr.capture' else 0
            if not isinstance(args, list) or len(args) != index + 1 or args[index] not in names:
                raise AssertionError('OCR generated path was not used by its captured operation')
            path = args[index]
            uses[path][op] += 1
            args[index] = names[path]
    wanted = Counter({'ocr.tempPath': 1, 'ocr.capture': 1, 'ocr.loadFile': 1, 'ocr.removeTemp': 1})
    if any(counts != wanted for counts in uses.values()):
        raise AssertionError('OCR capture/load/cleanup path identity changed')
    responses = data.get('responses')
    if not isinstance(responses, list) or len(responses) != 2:
        raise AssertionError('OCR recorded response count changed')
    assemblies = set()
    for response in responses:
        result = response.get('result') if isinstance(response, dict) else None
        match = ASSEMBLY_DIAGNOSTIC.fullmatch(result.get('detail', '')) if isinstance(result, dict) else None
        if match is None:
            raise AssertionError('Unexpected Args-only OCR failure diagnostic')
        assemblies.add(match['assembly'])
        start, end = match.span('assembly')
        result['detail'] = result['detail'][:start] + '<generated-assembly>' + result['detail'][end:]
    if len(assemblies) != 1:
        raise AssertionError('OCR diagnostic assembly identity changed within one process')


def _members(values):
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise AssertionError('Args-only candidate list shape changed')
    return Counter(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
                   for value in values)


def _recommendation(values):
    if not values:
        return 'observe'
    first = values[0]
    if first['is_modal'] or first['score'] >= 100:
        return 'dismiss_or_confirm'
    return 'confirm_dialog' if first['score'] >= 60 else 'wait'


def classify_args_only_actions(result, *, case, source):
    raw = _source(source)
    observed = _raw(result)
    retained, record = retained_args_only(case)
    _seams(observed, raw)
    _seams(retained, raw)
    if case['id'] == OCR_CASE:
        _generated_ocr(observed)
        _generated_ocr(retained)
    matched = _same(observed, retained)
    differences = []
    if not matched:
        # A changed permutation is evidence, not a functional pass or a new
        # expected ordering. All typed records, caps, identities, other fields
        # and acquisition effects must still be identical to the pinned run.
        projected = copy.deepcopy(observed)
        if not isinstance(projected.get('responses'), list) or len(projected['responses']) != len(retained['responses']):
            raise AssertionError('Args-only response count changed')
        for index, (current, old) in enumerate(zip(projected['responses'], retained['responses'])):
            got, previous = current.get('result'), old.get('result')
            if not isinstance(got, dict) or not isinstance(previous, dict):
                continue
            schema = previous.get('schema')
            if schema not in ('cucp.modal-detect/v1', 'cucp.uia-find/v1'):
                continue
            key = 'modal_candidates' if schema == 'cucp.modal-detect/v1' else 'candidates'
            if _members(got.get(key)) != _members(previous.get(key)):
                raise AssertionError('Args-only typed candidate membership/cap/identity changed')
            if key == 'candidates' and got[key]:
                if not _same(got.get('best'), got[key][0]) or not _same(got.get('score'), got[key][0].get('score')):
                    raise AssertionError('Args-only best/score is not its exact first candidate')
                got['best'], got['score'] = previous['best'], previous['score']
            elif key == 'modal_candidates':
                if got.get('recommended_action') != _recommendation(got[key]):
                    raise AssertionError('Args-only modal recommendation is not coupled to its first candidate')
                got['recommended_action'] = previous['recommended_action']
            if not _same(got[key], previous[key]):
                differences.append(dict(response_index=index, field=key, kind='typed-permutation-with-first-selection'))
            got[key] = previous[key]
        if not differences or not _same(projected, retained):
            raise AssertionError('Args-only baseline changed beyond candidate ordering/first-selection')
    return dict(schema='cucp.helper-args-only-observation/v1',
                status='recorded-baseline-observation' if matched else 'changed-baseline-observation',
                qualification='not-functional-qualification', args_only_qualified=False,
                exact_recorded_match=matched, changed_baseline_fields=differences,
                generated_normalizations=['two OCR path identities', 'one diagnostic assembly name'] if case['id'] == OCR_CASE else [],
                retained_stdout_sha256=record['sha256'], stdout_sha256=hashlib.sha256(result['stdout']).hexdigest(),
                raw_evidence=result['evidence_path'])
