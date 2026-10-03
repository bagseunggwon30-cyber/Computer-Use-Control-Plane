"""Bounded inferred neighbors of the Windows 37090071710 diagnostic failures."""
import copy
import json


def cases():
    result = []
    def baseline(identity, value, field='p50_ms', culture='en-US'):
        other = 'p95_ms' if field == 'p50_ms' else 'p50_ms'
        raw = '{"results":[{"name":"windows","' + field + '":' + value + ',"' + other + '":100}]}'
        result.append(dict(case_id='neighbor/baseline/' + identity, operation='benchmark',
            rest=['--iters', '1', '--baseline', r'C:\fixture\baseline.json'], culture=culture,
            replies=[dict(exit=0, json=dict(status='ok'))] * 4 + [True, raw]))
    def audit(identity, raw, culture='en-US'):
        result.append(dict(case_id='neighbor/audit/' + identity, operation='audit-summary',
            rest=[], culture=culture, replies=[True,
                [dict(full_name=r'C:\fixture\audit\trajectory-neighbor.ndjson', last_write_time='2026-10-02T00:00:00Z')], [raw]]))
    for token in ('true', 'false', '"True"', '"False"'):
        baseline('boolean/' + token, token)
    for token in ('true', 'false'):
        baseline('boolean-p95/' + token, token, field='p95_ms')
    for text in ('0x10', '0x0', '0xFFFFFFFF', '1e2', '1,000', ' 1 ', '\t+2 ', '+1', '-1', '0', '-0', '', ' ', '0.5', '0.6'):
        baseline('numeric-string/' + repr(text), json.dumps(text))
    for text in ('1,5', '1.5'):
        baseline('numeric-string/de-DE/' + text, json.dumps(text), culture='de-DE')
    for identity, value in (
        ('nested', '{"nested":{"value":1}}'),
        ('mixed', '{"fraction":1.5,"flag":true,"missing":null}'),
        ('date', r'{"date":"\/Date(0)\/"}'),
        ('array-empty', '{"items":[]}'),
        ('array-nested', '{"items":[[1,2],{}]}'),
    ):
        baseline('object/' + identity, value)
    baseline('object/current-culture-fraction', '{"value":1.5}', culture='de-DE')
    baseline('object/current-culture-date', r'{"date":"\/Date(0)\/"}', culture='ko-KR')
    for value in ('[true]', '[{}]', '[[1]]', '[null]'):
        baseline('array/' + value, value)
    for identity, raw in (
        ('empty-fallback', '{"macro":{},"action":"fallback","exit_code":{}}'),
        ('nested', '{"macro":{"nested":{"value":1},"items":[1,2]},"ts":{}}'),
        ('array-objects', '{"macro":[{}, {"value":1}],"action":"fallback"}'),
        ('array-nested', '{"macro":[[1,2],[],null,0]}'),
        ('array-mixed', '{"macro":["x",true,1.5,{"value":1},[2]]}'),
        ('scalar-members', '{"macro":{"truth":true,"falsehood":false,"missing":null,"number":1.5}}'),
        ('empty-ts', '{"macro":"clock","ts":{}}'),
        ('invariant-date-member', r'{"macro":{"fraction":1.5,"date":"\/Date(0)\/"}}'),
    ):
        audit('object/' + identity, raw, culture='de-DE' if identity == 'invariant-date-member' else 'en-US')
    for culture in ('en-US', 'ko-KR', 'de-DE', 'fr-FR'):
        for token in ('NaN', 'Infinity', '-Infinity'):
            baseline('nonfinite/' + culture + '/' + token, token, culture=culture)
    for culture in ('en-US', 'ko-KR'):
        for token in ('"Infinity"', '"∞"'):
            baseline('text-nonfinite/' + culture + '/' + token, token, culture=culture)
    for culture in ('en-US', 'ko-KR', 'de-DE', 'fr-FR', 'ja-JP'):
        for milliseconds in (-1000, 946730096000):
            baseline('date/' + culture + '/' + str(milliseconds),
                '"\\/Date(' + str(milliseconds) + ')\\/"', culture=culture)
    for milliseconds in (-62135596800000, 253402300799000):
        baseline('date-p95/all-years/' + str(milliseconds),
            '"\\/Date(' + str(milliseconds) + ')\\/"', field='p95_ms', culture='ko-KR')
    for fixture in copy.deepcopy(result):
        fixture['case_id'] += '/brief-json-only'
        fixture['brief'] = True
        fixture['rest'].append('--json-only')
        result.append(fixture)
    return result
