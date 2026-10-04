"""Source-derived finite-Double display probes; Windows outcomes are not assumed."""
import copy

TOKENS = (
    '1.2345678901234567e0', '-1.2345678901234567e0', '1e14', '1e15', '1e16',
    '1e-4', '1e-5', '0e0', '-0e0', '123456789012344.5e0',
    '-123456789012344.5e0', '123456789012345.5e0', '999999999999999.5e0',
    '123456789012344.484375e0', '123456789012344.515625e0',
    '5e-324', '-5e-324', '2.2250738585072014e-308', '1.7976931348623157e308',
)


def cases():
    result = []
    def audit(identity, lines):
        result.append(dict(case_id='number/audit/' + identity, operation='audit-summary', rest=[],
            replies=[True, [dict(full_name=r'C:\fixture\audit\trajectory-number.ndjson',
                last_write_time='2026-10-02T00:00:00Z')], lines]))
    for token in TOKENS:
        audit('scalar/' + token, ['{"macro":' + token + ',"exit_code":' + token + ',"ts":' + token + '}'])
        audit('object/' + token, ['{"macro":{"value":' + token + '}}'])
        audit('array/' + token, ['{"macro":[' + token + ',"typed"]}'])
        for culture in ('en-US', 'de-DE'):
            result.append(dict(case_id='number/baseline/object/' + culture + '/' + token,
                operation='benchmark', culture=culture,
                rest=['--iters', '1', '--baseline', r'C:\fixture\baseline.json'],
                replies=[dict(exit=0, json=dict(status='ok'))] * 4 + [True,
                    '{"results":[{"name":"windows","p50_ms":{"value":' + token + '},"p95_ms":100}]}']))
    audit('key-collision', ['{"macro":1.234567890123456e0}', '{"macro":1.234567890123457e0}'])
    audit('string-control', ['{"macro":"1e16","exit_code":"-0e0","ts":"1.2345678901234567e0"}'])
    audit('decimal-control', ['{"macro":1.2345678901234567,"exit_code":0.00}'])
    for fixture in copy.deepcopy(result):
        fixture['case_id'] += '/brief-json-only'
        fixture['brief'] = True
        fixture['rest'].append('--json-only')
        result.append(fixture)
    return result
