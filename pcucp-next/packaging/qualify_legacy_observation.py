#!/usr/bin/env python3
"""Candidate-only geometry/UIA qualification; never activates defaults or sends input.

Windows mode requires an owned WinForms desktop fixture and real provider entry.
A missing desktop is a failure, never a synthetic substitute or passing skip.
All subprocess evidence is retained before verdicts. Only measured elapsed_ms
fields are excluded from equality, at explicit schema paths; raw evidence stays.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
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


def source_bytes():
    manifest = json.loads((FIXTURES / 'source-manifest.json').read_text())
    raw = subprocess.check_output(['git', 'cat-file', 'blob', manifest['git_blob']], cwd=ROOT)
    if hashlib.sha256(raw).hexdigest() != manifest['raw_sha256']:
        raise AssertionError('Pinned immutable source blob hash mismatch')
    normalized = raw.decode('utf-8-sig').replace('\r\n', '\n')
    if hashlib.sha256(normalized.encode()).hexdigest() != manifest['normalized_sha256']:
        raise AssertionError('Pinned normalized source mismatch')
    return raw, manifest


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
    summary = {'schema': 'cucp.observation-qualification/v1', 'status': 'running', 'retirement_credit': 0,
               'oracle_pairs': 0, 'oracle_pairs_attempted': 0, 'acquisition_calls': 0, 'actual_entry_pairs': 0, 'actual_entry_pairs_attempted': 0, 'records': records, 'failures': failures,
               'windows_required': args.windows}
    try:
        raw, manifest = source_bytes()
        (logs / 'source-manifest.json').write_text(json.dumps(manifest, indent=2))
        (logs / 'driver-hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT / 'tests/fixtures/legacy-observation-oracle.ps1', ROOT / 'tests/fixtures/legacy-observation-wrapper.ps1', ROOT / 'tests/fixtures/legacy-observation-provider-diagnostic.ps1',
                      ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification/ScriptedObservation.cs']}, indent=2))
        build('pcucp-next/dotnet/PcuCp.LegacyObservation.ContractTests')
        run('portable-contracts', [args.dotnet, str(ROOT / 'pcucp-next/dotnet/PcuCp.LegacyObservation.ContractTests/bin/Release/net8.0/PcuCp.LegacyObservation.ContractTests.dll')])
        structural = run('python-structural', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/python', '-p', 'test_legacy_observation.py', '-v'])
        test_count = re.search(rb'Ran (\d+) tests?', structural['stderr'])
        if not test_count or int(test_count.group(1)) < 24:
            raise AssertionError('Required structural test discovery did not execute all 24 tests')
        if not args.windows:
            summary['status'] = 'portable-only-windows-unqualified'
            return 0
        ps = shutil.which('powershell.exe')
        if not ps:
            raise RuntimeError('Windows PowerShell 5.1 unavailable; refusing substitute')
        build('pcucp-next/dotnet/PcuCp.LegacyObservation.Qualification')
        build('tests/fixtures/legacy-observation-owned-window')
        build('tests/fixtures/legacy-observation-provider-probe')
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
            original_scripts = temp / 'original/scripts'; shutil.copytree(ROOT / 'scripts', original_scripts)
            original_source = original_scripts / 'cucp-native-helper.ps1'; original_source.write_bytes(raw)
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
                    result = run('candidate-route-' + probe, [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'scripts/cucp-native-helper.ps1'), '-Action', 'hit-test', '-X', x, '-Y', y, '-SkipUia'], process_env=probe_env, accepted=(1,))
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
                            scripts = original_scripts if mode == 'original' else ROOT / 'scripts'
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
        summary['status'] = 'passed' if not failures else 'failed'
        return 1 if failures else 0
    except Exception as error:
        summary['status'] = 'failed'; failures.append({'case': 'gate', 'error': str(error)})
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (logs / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in summary.items() if k != 'records'}, ensure_ascii=False))

if __name__ == '__main__':
    raise SystemExit(main())
