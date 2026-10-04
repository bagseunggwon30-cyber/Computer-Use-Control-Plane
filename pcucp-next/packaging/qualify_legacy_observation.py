#!/usr/bin/env python3
"""Historical adapter / C# geometry-UIA regression; never activates defaults or sends input.

The retired PowerShell entry comes from pinned Git history in owned temporary
folders. This report does not qualify the current Python native entrypoint; its
actual Windows checks are test_legacy_native_entry and test_legacy_native_desktop.

Windows mode requires an owned WinForms desktop fixture and real provider entry.
A missing desktop is a failure, never a synthetic substitute or passing skip.
All subprocess evidence is retained before verdicts. Only measured elapsed_ms
fields are excluded from equality, at explicit schema paths; raw evidence stays.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures/legacy-observation'
sys.path.insert(0, str(ROOT / 'tests/python'))
from helper_process_evidence import OwnedProcess, run_evidence, require_success
from legacy_historical_native import helper as historical_native_helper, wrapper as historical_native_wrapper, scripts as historical_native_scripts


def source_bytes():
    manifest = json.loads((FIXTURES / 'source-manifest.json').read_text())
    raw = subprocess.check_output(['git', 'cat-file', 'blob', manifest['git_blob']], cwd=ROOT)
    if hashlib.sha256(raw).hexdigest() != manifest['raw_sha256']:
        raise AssertionError('Pinned immutable source blob hash mismatch')
    normalized = raw.decode('utf-8-sig').replace('\r\n', '\n')
    if hashlib.sha256(normalized.encode()).hexdigest() != manifest['normalized_sha256']:
        raise AssertionError('Pinned normalized source mismatch')
    return raw, manifest


def wrapper_source_bytes():
    manifest = json.loads((FIXTURES / 'wrapper-source-manifest.json').read_text())
    raw = subprocess.check_output(['git','cat-file','blob',manifest['git_blob']],cwd=ROOT)
    if len(raw) != manifest['raw_bytes'] or hashlib.sha256(raw).hexdigest() != manifest['raw_sha256']:
        raise AssertionError('Pinned pre-scalar-correction wrapper blob mismatch')
    windows = raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    if len(windows) != manifest['windows_bytes'] or hashlib.sha256(windows).hexdigest() != manifest['windows_sha256']:
        raise AssertionError('Immutable observed Windows wrapper bytes mismatch')
    return windows,manifest


def strict_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def remove_elapsed(payload, paths):
    """Exclude only declared wall-clock measurements, while validating their type."""
    value = copy.deepcopy(payload)
    for path in paths:
        node = value
        for key in path[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict) and path[-1] in node:
            elapsed = node[path[-1]]
            if type(elapsed) is not int or elapsed < 0:
                raise AssertionError(f'Invalid elapsed measurement at {path}: {elapsed!r}')
            del node[path[-1]]
    return value


def compare_oracle(original, candidate):
    for result in (original, candidate):
        if result.get('schema') != 'cucp.observation-oracle/v1' or result.get('error') is not None:
            raise AssertionError(f'Oracle did not finish cleanly: {result.get("error")}')
    a, b = copy.deepcopy(original), copy.deepcopy(candidate)
    a.pop('mode'); b.pop('mode')
    a = remove_elapsed(a, [('captured', 'payload', 'elapsed_ms')])
    b = remove_elapsed(b, [('captured', 'payload', 'elapsed_ms')])
    if strict_json(a) != strict_json(b):
        raise AssertionError(f'Full payload/status/acquisition mismatch for {a.get("scenario")}')
    name = a['scenario']
    if name == 'scan-maximum-16641' and a['captured']['payload']['sample_count'] != 16641:
        raise AssertionError('Maximum admitted sample count changed')
    if name == 'click-original-mismatch':
        if a['inert_mutations'] != 0 or any(x.startswith('from-point:') for x in a['acquisition']):
            raise AssertionError('Original target mismatch reached refinement or mutation')
    elif name.startswith('click-'):
        if a['inert_mutations'] != 1:
            raise AssertionError('Actual unchanged click must reach exactly one inert boundary')
        if name == 'click-refined-mismatch':
            p = a['captured']['payload']
            if (p['x'], p['y']) != (10, 10) or 'refined_by' in p:
                raise AssertionError('Refined mismatch did not restore original point/clear refinement')
    elif a['inert_mutations'] != 0:
        raise AssertionError('Read-only fixture reached mutation boundary')
    if name.startswith('fusion-') and not all(a['return_value'][k] is True for k in ('element_identity', 'current_identity', 'root_identity')):
        raise AssertionError('Unchanged OCR fusion lost in-process identity')
    if name == 'fusion-root-stop' and (a['return_value']['depth'] != 0 or a['return_value']['pattern'] is not None):
        raise AssertionError('Fusion crossed the original root boundary')
    if name == 'fusion-parent-identity' and a['return_value']['depth'] != 1:
        raise AssertionError('Fusion failed to retain the climbed parent')
    if name in ('find-ambiguity-gap-7', 'find-ambiguity-gap-8'):
        if a['captured']['payload']['ambiguous'] is not name.endswith('-7'):
            raise AssertionError('Ambiguity threshold must be strictly below eight')
    return len(a['acquisition'])


def compare_entry(original, candidate, *, smart_plan=False):
    # _Emit and SmartPlan expose only the root elapsed_ms in these selected
    # schemas. No nested data or diagnostic strings are normalized.
    paths = [('elapsed_ms',)]
    a, b = remove_elapsed(original, paths), remove_elapsed(candidate, paths)
    if strict_json(a) != strict_json(b):
        raise AssertionError('Actual entry payload mismatch (raw evidence retained)')


def with_intended_initialization(source):
    """One counted, fixture-only insertion; all original bytes otherwise survive."""
    marker = b'switch ($Action) {'
    if source.count(marker) != 1:
        raise AssertionError('Expected exactly one original dispatch insertion point')
    hook = (ROOT / 'tests/fixtures/legacy-observation-intended-initialization.ps1').read_bytes()
    if not hook.endswith(b'\n'):
        raise AssertionError('Intended initialization fixture must end in a newline')
    derived = source.replace(marker, hook + marker, 1)
    if derived.replace(hook + marker, marker, 1) != source:
        raise AssertionError('Intended initialization changed original source')
    return derived


def require_intended_identity(payload, ready):
    if payload.get('error') is not None or payload.get('first_chance_dropped') != 0:
        raise AssertionError('Intended provider diagnostic did not finish completely')
    if any('LoadDefaultProxies' in row.get('Stack', '') for row in payload['first_chance_uia']):
        raise AssertionError('Intended initialization repeated original proxy startup failure')
    boundaries = payload.get('owned_object_boundaries', [])
    if [row['control'] for row in boundaries] != ['run', 'edit']:
        raise AssertionError('Original button/edit object boundary evidence missing')
    for row, identity, role, name, pattern in zip(boundaries, ('RunButton','FixtureEdit'), ('button','edit'), ('Run 한글','Fixture value'), ('InvokePattern','ValuePattern')):
        framework = ', UIAutomationClient, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35'
        if row.get('element_type') != 'System.Windows.Automation.AutomationElement' + framework or row.get('current_type') != 'System.Windows.Automation.AutomationElement+AutomationElementInformation' + framework:
            raise AssertionError('Complete real framework AutomationElement/Current type identity is required')
        expected_hwnd = row['expected_hwnd']
        geometry = ready[row['control']]
        if type(expected_hwnd) is not int or expected_hwnd <= 0 or (row['point_x'],row['point_y']) != (geometry['center_x'],geometry['center_y']):
            raise AssertionError('Original object handle did not come from the known owned control center')
        if (row['expected_hwnd'], row['original_hwnd'], row['candidate_hwnd']) != (expected_hwnd,) * 3 or row['automation_identity'] is not True:
            raise AssertionError('Original AutomationElement identity/handle changed across compiled boundary')
        if row['original_pid'] != ready['pid'] or row['candidate_pid'] != ready['pid']:
            raise AssertionError('Original UIA object boundary escaped the owned process')
        match = row['payload']
        if (match['automation_id'], match['role'], match['name']) != (identity, role, name):
            raise AssertionError('Original real Current properties changed across compiled boundary')
        direct = row.get('direct_bounds')
        rect = match.get('rect')
        if not isinstance(direct, dict) or set(direct) != {'X','Y','Width','Height','IsEmpty'} or direct['IsEmpty'] is not False:
            raise AssertionError('Complete nonempty compiled bounds evidence is required')
        if not isinstance(rect, dict) or set(rect) != {'x','y','width','height'}:
            raise AssertionError('Complete payload rectangle evidence is required')
        for public, native in (('x','X'),('y','Y'),('width','Width'),('height','Height')):
            if type(geometry.get(public)) is not int or type(direct[native]) not in (int,float) or not math.isfinite(direct[native]) or type(rect[public]) is not int:
                raise AssertionError('Owned geometry must contain finite, correctly typed numeric evidence')
            if direct[native] != geometry[public] or rect[public] != geometry[public]:
                raise AssertionError('Original Current compiled bounds/payload rectangle differ from independent owned control bounds')
        if geometry['width'] <= 0 or geometry['height'] <= 0:
            raise AssertionError('Owned control bounds must have positive dimensions')
        if row.get('pattern_type') != 'System.Windows.Automation.' + pattern + framework:
            raise AssertionError('Owned control advertised an unexpected real pattern')
        if row['control'] == 'edit' and row['value_readonly'] is not True:
            raise AssertionError('Owned readonly edit lost its ValuePattern readonly contract')


def require_smart_plan_trace(trace_bytes, result, source_hash):
    """Classify only a complete plan or the specifically instrumented replay stall."""
    if result.get('launch_error') or result.get('kill_error') or result.get('drain_incomplete') or result.get('running') or result.get('stdin_error') or result.get('read_errors') or any(result.get('truncated', {}).values()):
        raise AssertionError('SmartPlan phase process evidence is incomplete')
    rows = []
    for line in trace_bytes.decode('utf-8', errors='strict').splitlines():
        fields = line.split('\t')
        if not fields or fields[0] != 'cucp.smart-plan-trace/v1':
            raise AssertionError('Malformed SmartPlan phase record')
        row = {}
        for field in fields[1:]:
            key, separator, value = field.partition('=')
            if not separator or key in row: raise AssertionError('Malformed or duplicate SmartPlan phase field')
            row[key] = value
        required = {'phase','elapsed_ms','captures','raw.type','raw.length','raw.properties','err.type','err.length','err.properties'}
        if not required.issubset(row) or set(row) - required - {'wrapper_sha256'}:
            raise AssertionError('Incomplete SmartPlan phase fields')
        if not re.fullmatch(r'\d+', row['elapsed_ms']) or not re.fullmatch(r'-?\d+', row['captures']):
            raise AssertionError('Invalid SmartPlan phase clock/capture count')
        row['elapsed_ms'], row['captures'] = int(row['elapsed_ms']), int(row['captures'])
        allowed = {'wrapper.sha.before','wrapper.sha.after.install','wrapper.sha.after.invocation','compat.serialize.enter','compat.serialize.done','compat.process.start','compat.process.wait.done','native.call.enter','native.text.read.done','capture.replay','plan.complete'}
        if row['phase'] not in allowed or row['captures'] not in (-1,0,1,2):
            raise AssertionError('Unexpected SmartPlan phase or capture count')
        if rows and row['elapsed_ms'] < rows[-1]['elapsed_ms']:
            raise AssertionError('SmartPlan phase clock moved backward')
        rows.append(row)
    if len(rows) < 2 or [row['phase'] for row in rows[:2]] != ['wrapper.sha.before','wrapper.sha.after.install'] or any(row.get('wrapper_sha256') != source_hash for row in rows[:2]):
        raise AssertionError('SmartPlan trace lacks verified before/installed source hashes')
    expected = []
    for captures in (0,1):
        # PS5 visits this switch-clause line while considering the history
        # query too. Only native.text.read.done proves a completed native read.
        if captures: expected.extend([('native.call.enter',0),('capture.replay',captures)])
        expected.extend((phase,captures) for phase in ('compat.serialize.enter','compat.serialize.done','compat.process.start','compat.process.wait.done'))
    expected.extend([('native.call.enter',1),('native.text.read.done',1),('capture.replay',2),('compat.serialize.enter',2)])
    meaningful = [(row['phase'],row['captures']) for row in rows[2:] if row['captures'] >= 0 and row['phase'] != 'wrapper.sha.after.invocation']
    if meaningful[:len(expected)] != expected:
        raise AssertionError('SmartPlan trace did not reach the third replay after both native capture and earlier completed compatibility calls')
    if result.get('timed_out') is True:
        if meaningful != expected or rows[-1]['phase'] != 'compat.serialize.enter' or rows[-1]['captures'] != 2 or result.get('exit_code') is None or type(result.get('elapsed_ms')) is not int or result['elapsed_ms'] < 60000:
            raise AssertionError('Timeout was outside the bounded expected third-serialization boundary')
        raw = rows[-1]
        if raw['raw.type'] != 'System.String' or not re.fullmatch(r'\d+',raw['raw.length']) or int(raw['raw.length']) <= 0 or not {'PSDrive','PSProvider'}.issubset(raw['raw.properties'].split('|')):
            raise AssertionError('Third-serialization timeout lacks decorated native Raw string evidence')
        return {'status':'captured-expected-serialization-timeout','phase_records':len(rows),'last_phase':rows[-1]['phase'],'captured_replies':2}
    tail = [('compat.serialize.done',2),('compat.process.start',2),('compat.process.wait.done',2),('plan.complete',2)]
    if result.get('timed_out') is not False or meaningful != expected + tail or rows[-1]['phase'] != 'wrapper.sha.after.invocation' or rows[-1].get('wrapper_sha256') != source_hash or result.get('exit_code') not in (0,2):
        raise AssertionError('SmartPlan trace ended early or failed before a complete verified plan')
    output = json.loads(result['stdout'].decode('utf-8-sig'))
    if output.get('schema') != 'cucp.smart-plan/v1' or type(output.get('safe_to_act')) is not bool or (result['exit_code'],output.get('status'),output['safe_to_act']) not in ((0,'ok',True),(2,'partial',False)):
        raise AssertionError('Completed SmartPlan trace has no valid public plan envelope')
    return {'status':'captured-completed-plan','phase_records':len(rows),'last_phase':rows[-1]['phase'],'captured_replies':2}


def require_scalar_capture(payload, source_hash):
    expected = ['missing-both','empty-both','missing-stdout-rich-stderr','empty-stdout-missing-stderr','ok-json-rich-stderr',
                'partial-json','error-json','nonzero-exit-preserved','rich-raw-invalid-json','whitespace-raw','memory-null','memory-empty','memory-lone-surrogates']
    statements = [f'if (${name} -is [string]) {{ ${name} = [string]::new(${name}.ToCharArray()) }}' for name in ('raw','err')]
    if payload.get('schema') != 'cucp.observation-scalar-capture/v1' or payload.get('status') != 'ok' or payload.get('source_unchanged') is not True or payload.get('wrapper_sha256') != source_hash or not str(payload.get('powershell','')).startswith('5.1.') or payload.get('source_statements') != statements:
        raise AssertionError('Scalar proof did not execute the exact production source under PS5.1')
    rows = payload.get('cases',[])
    if [row.get('id') for row in rows] != expected or payload.get('serialized_captures') != 12 or payload.get('decorated_fields') != 11:
        raise AssertionError('Scalar proof coverage is incomplete')
    decorated = 0
    for row in rows:
        for field in ('raw','err'):
            evidence = row[field]; before, after = evidence['before'], evidence['after']
            if evidence.get('exact_utf16') is not True or before.get('is_null') is not after.get('is_null') or before.get('utf16le_base64') != after.get('utf16le_base64') or before.get('utf16_length') != after.get('utf16_length'):
                raise AssertionError('Scalar proof changed null identity or UTF-16 code units')
            if not isinstance(before.get('properties'),list) or not isinstance(after.get('properties'),list) or any(name in after['properties'] for name in ('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider','ReadCount')):
                raise AssertionError('Copied scalar retained filesystem provider metadata')
            if after['is_null'] is True:
                if any(after.get(key) is not None for key in ('utf16_length','utf16le_base64')) or after.get('type') != 'null' or before.get('type') != 'null':
                    raise AssertionError('Null scalar evidence is incomplete')
            else:
                if after['is_null'] is not False or before.get('type') != 'System.String' or after.get('type') != 'System.String' or type(after.get('utf16_length')) is not int or after['utf16_length'] < 0 or not isinstance(after.get('utf16le_base64'),str):
                    raise AssertionError('String scalar evidence is incomplete')
                units = base64.b64decode(after['utf16le_base64'],validate=True)
                if len(units) != 2 * after['utf16_length'] or (units and evidence.get('fresh_reference') is not True):
                    raise AssertionError('Nonempty text was not a fresh exact UTF-16 scalar')
            if evidence.get('provider_expected') is True:
                decorated += 1
                if not {'PSDrive','PSProvider'}.issubset(before['properties']):
                    raise AssertionError('Proof did not begin with a real decorated Get-Content string')
        if row['id'] == 'memory-lone-surrogates':
            if row.get('surrogate_memory_only') is not True or row.get('json_round_trip') is not False or row.get('copied_capture_json') is not None:
                raise AssertionError('Lone-surrogate proof must remain exact in memory')
            for field, expected_units in [('raw',b'A\x00\x00\xd8Z\x00'),('err',b'B\x00\x00\xdcY\x00')]:
                if base64.b64decode(row[field]['after']['utf16le_base64']) != expected_units:
                    raise AssertionError('Lone UTF-16 surrogate was replaced')
            continue
        expected_initial = 1 if row['id']=='missing-stdout-rich-stderr' else 17 if row['id']=='nonzero-exit-preserved' else 0
        expected_exit = {'partial-json':2,'error-json':1}.get(row['id'],expected_initial)
        expected_status = {'ok-json-rich-stderr':'ok','partial-json':'partial','error-json':'error','nonzero-exit-preserved':'partial'}.get(row['id'])
        if type(row.get('initial_exit')) is not int or row['initial_exit'] != expected_initial or type(row.get('exit_code')) is not int or row['exit_code'] != expected_exit or row.get('json_status') != expected_status or row.get('json_present') is not (expected_status is not None):
            raise AssertionError('Production parse/status/exit behavior changed during scalar proof')
        if row.get('json_round_trip') is not True or row.get('surrogate_memory_only') is not False:
            raise AssertionError('Copied scalar did not complete the actual depth-24 capture serialization')
        capture = json.loads(row['copied_capture_json'])['args']['captured_replies'][0]['result']
        for field in ('raw','err'):
            value = capture[field.capitalize()]
            expected_units = row[field]['after']['utf16le_base64']
            if expected_units is None:
                if value is not None: raise AssertionError('Capture JSON changed null to a scalar')
            elif type(value) is not str or base64.b64encode(value.encode('utf-16le',errors='surrogatepass')).decode() != expected_units:
                raise AssertionError('Capture JSON did not preserve exact Raw/Err string data')
        if type(capture.get('ExitCode')) is not int or capture['ExitCode'] != row['exit_code'] or (capture.get('Json') is not None) != row['json_present']:
            raise AssertionError('Scalar copy changed captured exit/JSON envelope')
        if row['json_present'] and strict_json(capture['Json']) != strict_json(json.loads(capture['Raw'])):
            raise AssertionError('Scalar correction changed parsed JSON data')
    if decorated != 11:
        raise AssertionError('Decorated Raw and Err leaf coverage is incomplete')
    rich = next(row for row in rows if row['id']=='rich-raw-invalid-json')
    for field in ('raw','err'):
        units = base64.b64decode(rich[field]['after']['utf16le_base64'])
        if any(value not in units for value in (b'\r\x00\n\x00',b'\x00\x00','한글'.encode('utf-16le'),'😀'.encode('utf-16le'))):
            raise AssertionError('Scalar proof lost required CRLF/NUL/Unicode/surrogate-pair coverage')
    nonstrings = payload.get('non_string_cases',[])
    if [row.get('id') for row in nonstrings] != ['int-and-bool','long-and-double','object-and-array']:
        raise AssertionError('Non-string identity coverage missing')
    for row, types, values in zip(nonstrings,[('System.Int32','System.Boolean'),('System.Int64','System.Double'),('System.Management.Automation.PSCustomObject','System.Object[]')],[(17,True),(9007199254740993,2.5),(None,None)]):
        for field, clr_type, value in zip(('raw','err'),types,values):
            evidence = row[field]
            if evidence.get('before_type') != clr_type or evidence.get('after_type') != clr_type or evidence.get('value_preserved') is not True:
                raise AssertionError('Non-string value was coerced')
            if value is None:
                if evidence.get('same_reference') is not True: raise AssertionError('Non-string object identity changed')
            elif type(evidence.get('scalar_value')) is not type(value) or evidence['scalar_value'] != value:
                raise AssertionError('Non-string scalar value changed')


def require_entry_outcome(label, payload, exit_code, ready):
    expected = {
        'helper-hit-mismatch': (2, 'partial'), 'helper-hit-missing': (1, 'error'),
        'helper-tree-no-match': (2, 'partial'), 'helper-find-duplicate': (2, 'partial'),
        'helper-find-offscreen': (2, 'partial'),
    }.get(label, (0, 'ok'))
    if (exit_code, payload.get('status')) != expected:
        raise AssertionError(f'{label} did not reach its expected owned-fixture outcome: {exit_code}, {payload.get("status")}')
    if label == 'helper-hit-missing' and payload.get('reason') != 'missing_coords':
        raise AssertionError('Missing-coordinate entry failed for an unrelated reason')
    if label == 'helper-tree-no-match' and payload.get('reason') != 'no_matching_window':
        raise AssertionError('Unmatched title fell back or failed for an unrelated reason')
    if label == 'helper-hit-mismatch':
        if payload.get('root_hwnd') != ready['hwnd'] or payload.get('process_id') != ready['pid'] or payload.get('matched') is not False or payload.get('match_reason') != 'title_mismatch':
            raise AssertionError('Negative target query did not reach the owned window title guard')
    if label in ('helper-hit', 'helper-hit-skip', 'wrapper-hit'):
        if payload.get('root_hwnd') != ready['hwnd'] or payload.get('process_id') != ready['pid']:
            raise AssertionError('Actual entry did not observe owned fixture PID/HWND')
        if payload.get('matched') is not True: raise AssertionError('Owned HWND was not matched')
    if label == 'helper-tree':
        if payload.get('target_hwnd') != ready['hwnd'] or payload.get('affordance_count', 0) <= 0:
            raise AssertionError('Actual UIA descendants did not observe owned controls')
        texts = [x.get('text') for x in payload.get('affordances', [])]
        if 'Run 한글' not in texts or texts.count('Duplicate') < 2 or 'Disabled' not in texts or 'Offscreen' in texts:
            raise AssertionError('Owned descendants/duplicates/disabled/offscreen contract failed')
    if label in ('helper-scan', 'wrapper-scan'):
        point = payload.get('recommended_point', {})
        r = ready['run']
        if not (r['x'] <= point.get('x', -1) <= r['x']+r['width'] and r['y'] <= point.get('y', -1) <= r['y']+r['height']):
            raise AssertionError('Scan did not refine into owned Run control')
        if payload.get('sample_count') != 1 or payload.get('candidate_count') != 1:
            raise AssertionError('Radius-zero owned scan did not acquire one candidate')
    if label == 'helper-find':
        if payload.get('top', {}).get('text') != 'Run 한글' or payload.get('ambiguous') is not False:
            raise AssertionError('Owned unique Unicode UIA label was not resolved')
    if label == 'helper-find-duplicate' and payload.get('ambiguous') is not True:
        raise AssertionError('Owned duplicate controls were not ambiguous')
    if label == 'helper-find-disabled' and payload.get('top', {}).get('text') != 'Disabled':
        raise AssertionError('Disabled control was incorrectly filtered out')
    if label == 'helper-find-offscreen' and payload.get('reason') != 'no_match':
        raise AssertionError('Offscreen control was not excluded')
    if label in ('helper-find-id','helper-find-role','helper-find-edit'):
        top = payload.get('top', {})
        expected = ('FixtureEdit','edit','Fixture value') if label == 'helper-find-edit' else ('RunButton','button','Run 한글')
        if (top.get('automation_id'),top.get('role'),top.get('text')) != expected or payload.get('ambiguous') is not False:
            raise AssertionError('Owned intended ID/role query did not resolve its exact control')
        if label == 'helper-find-edit':
            if top.get('value_pattern') is not True or top.get('value_readonly') is not True:
                raise AssertionError('Owned readonly edit did not expose readonly ValuePattern')
        elif top.get('invoke_pattern') != 'InvokePattern':
            raise AssertionError('Owned button did not expose InvokePattern')
    if label == 'wrapper-smart-plan':
        if payload.get('schema') != 'cucp.smart-plan/v1' or payload.get('safe_to_act') is not True or payload.get('best_route') != 'uia_pattern':
            raise AssertionError('SmartPlan did not reach the real UIA pattern planning route')
        # The plan is inspected only. Its recommended command is never executed.
        if payload.get('best', {}).get('mouse_moved') is not False:
            raise AssertionError('Owned SmartPlan was not a read-only UIA plan')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true')
    parser.add_argument('--log-dir', type=Path, default=ROOT / '.migration-logs/observation-candidate')
    parser.add_argument('--dotnet', default='dotnet')
    args = parser.parse_args(argv)
    if args.windows and sys.platform != 'win32':
        parser.error('--windows requires Windows; no synthetic substitution is allowed')
    logs = args.log_dir.resolve(); logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONPATH=str(ROOT / 'pcucp-next/python'))
    env.pop('CUCP_LEGACY_OBSERVATION_CANDIDATE', None)
    records, failures = [], []
    def run(label, command, *, process_env=None, timeout=180, accepted=(0,)):
        result = run_evidence(command, cwd=ROOT, env=process_env or env, directory=logs, label=f'{len(records)+1:03d}-' + re.sub(r'[^A-Za-z0-9_-]', '-', label),
                              timeout=timeout, limit=128 * 1024 * 1024)
        records.append({'label': label, 'evidence': result['evidence_path']})
        require_success(result, expected_exit=result['exit_code'] if result['exit_code'] in accepted else accepted[0])
        return result
    def build(project):
        return run('build-' + Path(project).name, [args.dotnet, 'build', str(ROOT / project), '-c', 'Release',
                   '-warnaserror', '-m:1', '-p:UseSharedCompilation=false'], timeout=300)
    summary = {'qualification_scope': 'historical-PowerShell-adapter-and-current-CSharp-library-regression', 'current_native_runtime_qualified_by_this_report': False, 'schema': 'cucp.observation-qualification/v1', 'status': 'running', 'retirement_credit': 0,
               'oracle_pairs': 0, 'oracle_pairs_attempted': 0, 'acquisition_calls': 0, 'actual_entry_pairs': 0, 'actual_entry_pairs_attempted': 0, 'records': records, 'failures': failures,
               'windows_required': args.windows}
    intended = {'status': 'not-run', 'correction': 'fixed-public-compiled-FromHandle-before-unchanged-original-helper-dispatch-plus-wrapper-Raw-Err-fresh-scalar-copy',
                'entry_pairs': 0, 'entry_pairs_attempted': 0, 'identity_checks': 0, 'failures': [],
                'blocked': ['wrapper-smart-plan: scalar proof and actual completed cold/warm route pending'], 'retirement_credit': 0}
    summary['intended_initialization'] = intended
    try:
        raw, manifest = source_bytes()
        wrapper_raw, wrapper_manifest = wrapper_source_bytes()
        (logs / 'source-manifest.json').write_text(json.dumps(manifest, indent=2))
        (logs / 'wrapper-source-manifest.json').write_text(json.dumps(wrapper_manifest, indent=2))
        (logs / 'driver-hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT / 'tests/fixtures/legacy-observation-oracle.ps1', ROOT / 'tests/fixtures/legacy-observation-wrapper.ps1', ROOT / 'tests/fixtures/legacy-observation-smart-plan-trace.ps1',
                      ROOT / 'tests/fixtures/legacy-observation-provider-diagnostic.ps1', ROOT / 'tests/fixtures/legacy-observation-provider-probe/ProviderLoadProbe.cs',
                      ROOT / 'tests/fixtures/legacy-observation-intended-initialization.ps1', ROOT / 'tests/fixtures/legacy-observation-intended-provider/PublicUiaInitialization.cs',
                      ROOT / 'tests/fixtures/legacy-observation-scalar-capture.ps1',
                      ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification/ScriptedObservation.cs']}, indent=2))
        build('pcucp-next/dotnet/PcuCp.LegacyObservation.ContractTests')
        run('portable-contracts', [args.dotnet, str(ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation.ContractTests/bin/Release/net8.0/PcuCp.LegacyObservation.ContractTests.dll')])
        structural = run('python-structural', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/python', '-p', 'test_legacy_observation.py', '-v'])
        test_count = re.search(rb'Ran (\d+) tests?', structural['stderr'])
        if not test_count or int(test_count.group(1)) < 41:
            raise AssertionError('Required structural test discovery did not execute all 41 tests')
        if not args.windows:
            summary['status'] = 'portable-only-windows-unqualified'
            return 0
        ps = shutil.which('powershell.exe')
        if not ps:
            raise RuntimeError('Windows PowerShell 5.1 unavailable; refusing substitute')
        build('pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification')
        build('tests/fixtures/legacy-observation-owned-window')
        build('tests/fixtures/legacy-observation-provider-probe')
        build('tests/fixtures/legacy-observation-intended-provider')
        build('pcucp-next/dotnet/PcuCp.NativeHost')
        qualification = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification/bin/Release/net48'
        env['CUCP_LEGACY_INTEROP_DLL'] = str(qualification / 'PcuCp.LegacyInterop.dll')
        env['CUCP_LEGACY_OBSERVATION_DLL'] = str(qualification / 'PcuCp.LegacyObservation.dll')
        env['CUCP_NATIVE_HOST'] = str(ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/bin/Release/net8.0-windows10.0.19041.0/PcuCp.NativeHost.dll')
        env['CUCP_FORCE_CHILD'] = '1'; env['CUCP_HOT_CACHE_DISABLE'] = '1'
        with tempfile.TemporaryDirectory(prefix='cucp-observation-owned-') as temporary:
            temp = Path(temporary)
            owned_temp = temp / 'runtime-temp'; owned_temp.mkdir()
            env['TEMP'] = str(owned_temp); env['TMP'] = str(owned_temp)
            owned_profile = temp / 'owned-profile'; owned_profile.mkdir()
            env['USERPROFILE'] = str(owned_profile)
            env.pop('CUCP_CLI_PATH', None)
            try:
                result = run('native-scalar-capture-proof',[ps,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
                    str(ROOT / 'tests/fixtures/legacy-observation-scalar-capture.ps1'),'-WrapperPath',str(historical_native_wrapper())],timeout=60)
                require_scalar_capture(json.loads(result['stdout'].decode('utf-8-sig')),hashlib.sha256((historical_native_wrapper()).read_bytes()).hexdigest())
                intended['scalar_capture_proof'] = 'passed'
            except Exception as error:
                intended['scalar_capture_proof'] = 'failed'
                intended['failures'].append({'case':'scalar-capture-proof','error':str(error)})
            try:
                smart_env = dict(env,CUCP_SMART_PLAN_TEST_HOST=env['CUCP_NATIVE_HOST'])
                result = run('smart-plan-captured-parity',[sys.executable,'-m','unittest','discover','-s','tests/python','-p','test_legacy_smart_plan_parity.py','-v'],process_env=smart_env,timeout=900)
                if b'Ran 3 tests' not in result['stderr'] or b'skipped' in result['stderr']:
                    raise AssertionError('All captured SmartPlan kernel/adapter tests must execute')
                from test_legacy_smart_plan_parity import fixtures as smart_plan_fixtures
                intended['captured_smart_plan_cases'] = len(smart_plan_fixtures())
                if intended['captured_smart_plan_cases'] < 210:
                    raise AssertionError('Captured SmartPlan corpus shrank')
            except Exception as error:
                intended['failures'].append({'case':'smart-plan-captured-parity','error':str(error)})
            original_scripts = temp / 'original/scripts'; shutil.copytree(historical_native_scripts(), original_scripts)
            original_source = original_scripts / 'cucp-native-helper.ps1'; original_source.write_bytes(raw)
            # Preserve the actually observed pre-fix wrapper timeout independently.
            (original_scripts / 'cucp.ps1').write_bytes(wrapper_raw)
            intended_original_scripts = temp / 'intended-original/scripts'; shutil.copytree(original_scripts, intended_original_scripts)
            # Corrected-intent oracle keeps original helper bodies, while both
            # wrapper callers receive the explicitly recorded scalar correction.
            (intended_original_scripts / 'cucp.ps1').write_bytes((historical_native_wrapper()).read_bytes())
            intended_candidate_scripts = temp / 'intended-candidate/scripts'; shutil.copytree(historical_native_scripts(), intended_candidate_scripts)
            derived_sources = {}
            derived_sources['wrapper'] = {'correction':'Raw-and-Err-fresh-UTF16-string-copy-after-Get-Content',
                'original_sha256':hashlib.sha256(wrapper_raw).hexdigest(),
                'corrected_sha256':hashlib.sha256((historical_native_wrapper()).read_bytes()).hexdigest()}
            for name, scripts, source in [('original', intended_original_scripts, raw), ('candidate-warm', intended_candidate_scripts, (historical_native_helper()).read_bytes())]:
                derived = with_intended_initialization(source)
                (scripts / 'cucp-native-helper.ps1').write_bytes(derived)
                derived_sources[name] = {'source_sha256': hashlib.sha256(source).hexdigest(), 'derived_sha256': hashlib.sha256(derived).hexdigest(), 'insertion_sha256': hashlib.sha256((ROOT / 'tests/fixtures/legacy-observation-intended-initialization.ps1').read_bytes()).hexdigest()}
            (logs / 'intended-source-derivation.json').write_text(json.dumps(derived_sources, indent=2))
            for name in json.loads((FIXTURES / 'cases.json').read_text()):
                try:
                    summary['oracle_pairs_attempted'] += 1
                    processes = []
                    for mode in ('original', 'candidate'):
                        result = run(name + '-' + mode, [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            str(ROOT / 'tests/fixtures/legacy-observation-oracle.ps1'), '-Mode', mode, '-Root', str(ROOT),
                            '-SourcePath', str(original_source), '-ScenarioPath', str(FIXTURES / (name + '.json')),
                            '-AssemblyPath', str(qualification / 'PcuCp.LegacyObservation.Qualification.dll')], timeout=300)
                        processes.append(result)
                    pair = [json.loads(result['stdout'].decode('utf-8-sig')) for result in processes]
                    summary['acquisition_calls'] += compare_oracle(*pair)
                    summary['oracle_pairs'] += 1
                except Exception as error:
                    failures.append({'case': name, 'error': str(error)})
            # Still run real entry if a synthetic case fails: separate evidence must
            # not be replaced or hidden by an earlier oracle disagreement.
            fixture_dir = logs / ('owned-window-' + uuid.uuid4().hex); fixture_dir.mkdir()
            title = 'CUCP observation owned ' + uuid.uuid4().hex
            fixture_exe = ROOT / 'tests/fixtures/legacy-observation-owned-window/bin/Release/net48/ObservationOwnedWindow.exe'
            fixture = OwnedProcess([fixture_exe, fixture_dir, title], cwd=ROOT, env=env, limit=262144)
            try:
                ready_path = fixture_dir / 'ready.json'; deadline = time.monotonic() + 30
                while not ready_path.is_file() and time.monotonic() < deadline:
                    if fixture.process is None or fixture.process.poll() is not None:
                        break
                    time.sleep(.1)
                if not ready_path.is_file():
                    raise RuntimeError('Owned desktop fixture unavailable: readiness never arrived; real-provider gate failed')
                ready = json.loads(ready_path.read_text(encoding='utf-8'))
                if (not ready['desktop_interactive'] or ready['pid'] != fixture.process.pid or ready['hwnd'] <= 0
                        or ready['run']['width'] <= 0 or ready['run']['height'] <= 0 or any(ready[key] != 0 for key in ('input_events','invoke_events','value_events'))):
                    raise RuntimeError('Owned fixture has no usable interactive desktop/geometry; real-provider gate failed')
                x, y = str(ready['run']['center_x']), str(ready['run']['center_y'])
                hwnd = str(ready['hwnd'])
                cases = [
                    ('helper-hit', ['-Action','hit-test','-X',x,'-Y',y,'-TargetHwnd',hwnd]),
                    ('helper-hit-skip', ['-Action','hit-test','-X',x,'-Y',y,'-TargetHwnd',hwnd,'-SkipUia']),
                    ('helper-hit-mismatch', ['-Action','hit-test','-X',x,'-Y',y,'-TargetMatch',title+' absent']),
                    ('helper-hit-missing', ['-Action','hit-test']),
                    ('helper-scan', ['-Action','hit-scan','-X',x,'-Y',y,'-TargetHwnd',hwnd,'-ScanRadius','0']),
                    ('helper-tree', ['-Action','uia-tree','-Match',title]),
                    ('helper-tree-no-match', ['-Action','uia-tree','-Match',title+' absent']),
                    ('helper-find', ['-Action','uia-find','-Match',title,'-Label','Run 한글']),
                    ('helper-find-duplicate', ['-Action','uia-find','-Match',title,'-Label','Duplicate']),
                    ('helper-find-disabled', ['-Action','uia-find','-Match',title,'-Label','Disabled']),
                    ('helper-find-offscreen', ['-Action','uia-find','-Match',title,'-Label','Offscreen']),
                ]
                wrapper_cases = [
                    ('wrapper-hit',['macro','hit-test','--x',x,'--y',y,'--target-hwnd',hwnd]),
                    ('wrapper-scan',['macro','hit-scan','--x',x,'--y',y,'--target-hwnd',hwnd,'--radius','0']),
                    ('wrapper-smart-plan',['macro','smart-plan','--label','Run 한글','--match',title,'--no-cdp','--json-only']),
                ]
                for probe, selector, dll in [('missing-dll', '1', temp / 'missing.dll'), ('invalid-selector', 'invalid', qualification / 'PcuCp.LegacyObservation.dll')]:
                    probe_env = dict(env, CUCP_LEGACY_OBSERVATION_CANDIDATE=selector, CUCP_LEGACY_OBSERVATION_DLL=str(dll))
                    result = run('candidate-route-' + probe, [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(historical_native_helper()), '-Action', 'hit-test', '-X', x, '-Y', y, '-SkipUia'], process_env=probe_env, accepted=(1,))
                    failure = json.loads(result['stdout'].decode('utf-8-sig'))
                    expected_detail = 'Candidate observation DLL missing' if probe == 'missing-dll' else 'Invalid observation candidate selector'
                    if failure.get('reason') != 'native_action_failed' or failure.get('status') != 'error' or expected_detail not in failure.get('detail', ''):
                        raise AssertionError('Candidate route did not fail closed: ' + probe)
                for label, arguments in cases + wrapper_cases:
                    try:
                        summary['actual_entry_pairs_attempted'] += 1
                        processes = []; exits = []
                        for mode in ('original', 'candidate'):
                            child_env = dict(env)
                            if mode == 'candidate': child_env['CUCP_LEGACY_OBSERVATION_CANDIDATE'] = '1'
                            scripts = original_scripts if mode == 'original' else historical_native_scripts()
                            if label.startswith('wrapper-'):
                                argfile = temp / (label + '.json'); argfile.write_text(json.dumps(arguments, ensure_ascii=False), encoding='utf-8')
                                command = [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT / 'tests/fixtures/legacy-observation-wrapper.ps1'),'-WrapperPath',str(scripts / 'cucp.ps1'),'-ArgumentsPath',str(argfile)]
                            else:
                                command = [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts / 'cucp-native-helper.ps1')] + arguments
                            result = run(label+'-'+mode,command,process_env=child_env,accepted=(0,1,2,3),timeout=180)
                            exits.append(result['exit_code']); processes.append(result)
                        pair = [json.loads(result['stdout'].decode('utf-8-sig')) for result in processes]
                        if exits[0] != exits[1]: raise AssertionError('Actual entry exit mismatch')
                        compare_entry(*pair, smart_plan=label=='wrapper-smart-plan')
                        for payload, code in zip(pair, exits): require_entry_outcome(label, payload, code, ready)
                        summary['actual_entry_pairs'] += 1
                    except Exception as error:
                        failures.append({'case': label, 'error': str(error)})
                # Read-only side diagnostics retain exact assembly/type/provider identities.
                # They never replace, normalize, or qualify the unchanged actual entries.
                for mode in ('original', 'candidate', 'shared-current'):
                    try:
                        run('provider-identity-' + mode, [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            str(ROOT / 'tests/fixtures/legacy-observation-provider-diagnostic.ps1'), '-Mode', mode,
                            '-Root', str(ROOT), '-SourcePath', str(original_source), '-ReadinessPath', str(ready_path),
                            '-ProbeAssembly', str(ROOT / 'tests/fixtures/legacy-observation-provider-probe/bin/Release/net48/ObservationProviderProbe.dll')], timeout=120)
                    except Exception as error:
                        failures.append({'case': 'provider-identity-' + mode, 'error': str(error)})
                # Bounded diagnostic only: record exact silent-block boundary,
                # without raising the real 180-second deadline or parity credit.
                summary['smart_plan_diagnostics'] = []
                for mode in ('original','candidate'):
                    scripts = original_scripts if mode == 'original' else historical_native_scripts()
                    wrapper = scripts / 'cucp.ps1'
                    before_hash = hashlib.sha256(wrapper.read_bytes()).hexdigest()
                    trace_path = logs / ('smart-plan-' + mode + '-' + uuid.uuid4().hex + '-phases.log')
                    child_env = dict(env)
                    if mode == 'candidate': child_env['CUCP_LEGACY_OBSERVATION_CANDIDATE'] = '1'
                    argfile = temp / 'wrapper-smart-plan.json'
                    command = [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT / 'tests/fixtures/legacy-observation-wrapper.ps1'),
                               '-WrapperPath',str(wrapper),'-ArgumentsPath',str(argfile),'-TraceSmartPlan','-TracePath',str(trace_path)]
                    label = 'smart-plan-phase-' + mode
                    result = run_evidence(command, cwd=ROOT, env=child_env, directory=logs,
                                          label=f'{len(records)+1:03d}-'+label, timeout=60, limit=128*1024*1024)
                    records.append({'label':label,'evidence':result['evidence_path']})
                    after_hash = hashlib.sha256(wrapper.read_bytes()).hexdigest()
                    trace_bytes = trace_path.read_bytes() if trace_path.is_file() else b''
                    trace_result = {'mode':mode,'wrapper_sha256_before':before_hash,'wrapper_sha256_after_process':after_hash,
                                    'phase_file':trace_path.name,'phase_sha256':hashlib.sha256(trace_bytes).hexdigest(),
                                    'timed_out':result['timed_out'],'exit_code':result['exit_code'],'retirement_credit':0}
                    summary['smart_plan_diagnostics'].append(trace_result)
                    try:
                        if before_hash != after_hash: raise AssertionError('Phase diagnostic changed wrapper source')
                        trace_result.update(require_smart_plan_trace(trace_bytes,result,before_hash))
                        if mode == 'candidate' and trace_result['status'] != 'captured-completed-plan':
                            raise AssertionError('Corrected candidate did not complete the unchanged SmartPlan serialization route')
                    except Exception as error:
                        trace_result.update(status='failed-incomplete-diagnostic',error=str(error))
                        failures.append({'case':label,'error':str(error)})
                # Distinct corrected-intent tier. Cold-original exact failures above
                # remain failed and retain all raw bytes. No raw parity is claimed.
                initializer_dll = ROOT / 'tests/fixtures/legacy-observation-intended-provider/bin/Release/net48/ObservationIntendedProvider.dll'
                initialization_evidence = fixture_dir / 'intended-initialization'; initialization_evidence.mkdir()
                intended_env = dict(env, CUCP_OBSERVATION_INTENDED_DLL=str(initializer_dll),
                                    CUCP_OBSERVATION_INTENDED_READY=str(ready_path),
                                    CUCP_OBSERVATION_INTENDED_EVIDENCE=str(initialization_evidence))
                intended_cases = cases + wrapper_cases + [
                    ('helper-find-id', ['-Action','uia-find','-Match',title,'-Label','RunButton']),
                    ('helper-find-role', ['-Action','uia-find','-Match',title,'-Label','Run 한글','-Role','button']),
                    ('helper-find-edit', ['-Action','uia-find','-Match',title,'-Label','Fixture value']),
                ]
                for temperature in ('cold','warm'):
                    for label, arguments in intended_cases:
                        try:
                            intended['entry_pairs_attempted'] += 1
                            results, errors = [], []
                            for mode in ('original','candidate'):
                                child_env = dict(intended_env)
                                scripts = intended_original_scripts
                                if mode == 'candidate':
                                    child_env['CUCP_LEGACY_OBSERVATION_CANDIDATE'] = '1'
                                    scripts = historical_native_scripts() if temperature == 'cold' else intended_candidate_scripts
                                if label.startswith('wrapper-'):
                                    argfile = temp / ('intended-' + label + '.json'); argfile.write_text(json.dumps(arguments, ensure_ascii=False), encoding='utf-8')
                                    command = [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT / 'tests/fixtures/legacy-observation-wrapper.ps1'),'-WrapperPath',str(scripts / 'cucp.ps1'),'-ArgumentsPath',str(argfile)]
                                else:
                                    command = [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts / 'cucp-native-helper.ps1')] + arguments
                                try:
                                    results.append(run('intended-'+temperature+'-'+label+'-'+mode, command, process_env=child_env, accepted=(0,1,2,3), timeout=180))
                                except Exception as error:
                                    errors.append(mode + ': ' + str(error))
                            if errors: raise AssertionError('; '.join(errors))
                            pair = [json.loads(result['stdout'].decode('utf-8-sig')) for result in results]
                            if results[0]['exit_code'] != results[1]['exit_code']: raise AssertionError('Intended entry exit mismatch')
                            compare_entry(*pair)
                            for payload, result in zip(pair, results): require_entry_outcome(label, payload, result['exit_code'], ready)
                            intended['entry_pairs'] += 1
                        except Exception as error:
                            intended['failures'].append({'case': temperature+'-'+label, 'error': str(error)})
                for mode in ('intended-current','candidate-warm'):
                    try:
                        result = run('provider-identity-' + mode, [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',
                            str(ROOT / 'tests/fixtures/legacy-observation-provider-diagnostic.ps1'),'-Mode',mode,
                            '-Root',str(ROOT),'-SourcePath',str(original_source),'-ReadinessPath',str(ready_path),
                            '-ProbeAssembly',str(ROOT / 'tests/fixtures/legacy-observation-provider-probe/bin/Release/net48/ObservationProviderProbe.dll'),
                            '-InitializerAssembly',str(initializer_dll)], timeout=120)
                        require_intended_identity(json.loads(result['stdout'].decode('utf-8-sig')),ready)
                        intended['identity_checks'] += 1
                    except Exception as error:
                        intended['failures'].append({'case':mode, 'error':str(error)})
                initialization_records = list(initialization_evidence.glob('initialization-*.json'))
                intended['initialization_records'] = len(initialization_records)
                if len(initialization_records) != 3 * len(intended_cases):
                    intended['failures'].append({'case':'initialization-evidence', 'error':'Expected exactly one public owned-HWND initialization per corrected original or warm candidate process'})
                for path in initialization_records:
                    evidence = json.loads(path.read_text(encoding='utf-8'))
                    if (evidence.get('target_pid'),evidence.get('returned_pid')) != (ready['pid'],)*2 or (evidence.get('target_hwnd'),evidence.get('returned_hwnd')) != (ready['hwnd'],)*2 or evidence.get('client_proxies_loaded') is not True:
                        intended['failures'].append({'case':'initialization-evidence', 'error':'Owned HWND/PID or normal public proxy initialization mismatch in '+path.name})
                if not intended['failures'] and intended.get('scalar_capture_proof') == 'passed' and intended['entry_pairs'] == 2 * len(intended_cases) and intended['identity_checks'] == 2:
                    intended['blocked'] = []
                intended['status'] = 'failed' if intended['failures'] else 'passed' if not intended['blocked'] else 'incomplete'
            finally:
                (fixture_dir / 'close.request').write_text('close owned fixture\n')
                result = fixture.finish(logs, 'owned-window-process', timeout=10)
                records.append({'label': 'owned-window-process', 'evidence': result['evidence_path']})
                require_success(result)
                closed = fixture_dir / 'closed.json'
                if not closed.is_file(): raise AssertionError('Owned fixture cleanup/mutation evidence missing')
                counters = json.loads(closed.read_text())
                if any(type(v) is not int or v != 0 for v in counters.values()):
                    raise AssertionError('Owned real-provider fixture observed input/UIA mutation')
        summary['raw_original_entry_status'] = 'passed' if summary['actual_entry_pairs'] == summary['actual_entry_pairs_attempted'] else 'failed'
        summary['status'] = 'passed' if not failures and not intended['failures'] and not intended['blocked'] else 'failed'
        return 0 if summary['status'] == 'passed' else 1
    except Exception as error:
        summary['status'] = 'failed'; failures.append({'case': 'gate', 'error': str(error)})
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (logs / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in summary.items() if k != 'records'}, ensure_ascii=False))

if __name__ == '__main__':
    raise SystemExit(main())
