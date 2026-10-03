"""Inferred candidate contracts and a strict, owned-file PS5/PS7 Windows gate.

No observed Windows results are checked in. Run this file with --differential
for actual immutable-original observations; ordinary unittest is NOT that gate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import signal
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHistory.Qualification'
FIXTURES = ROOT / 'tests/fixtures/history-reducers'
ORIGINAL = FIXTURES / 'original-functions.json'
ORIGINAL_SHA256 = '8cba53d610ec92f31be4a9a3d71b946b14ca8b023cda3f1979cba81fdff7f487'
SOURCE_SHA256 = '8a3140745701a828628b13c4741b30063119babbcbd74e5230caae2d49591c4c'
SCHEMA = 'cucp.history-reducer-qualification/v1'
INPUT_SCHEMA = 'cucp.history-reducer-input/v1'
CONTRACT_CAPTURE_ROOT = None
_CAPTURE_SEQUENCE = 0
_CAPTURE_LOCK = threading.Lock()
KNOWN_GATES = [
    'PS5 Framework and PS7 JSON parsing, root-array pipeline, scalar and DateTime conversion',
    'Hashtable ordinal-ignore-case merging versus invariant linguistic equality',
    'Windows NLS versus ICU comparison and culture-sensitive Sort-Object ordering',
    'Sort-Object unstable equal-key and mixed-type timestamp behavior',
    'Framework/Core Hashtable enumeration and exact compact JSON Console ordering',
    'Full record property order, types, unknown fields and original nested values',
]


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def original_manifest():
    if ORIGINAL.stat().st_size > 65536:
        raise ValueError('Oversized immutable manifest')
    data = ORIGINAL.read_bytes()
    if digest(data) != ORIGINAL_SHA256:
        raise ValueError('Immutable original manifest changed')
    manifest = json.loads(data)
    if set(manifest) != {'source_revision', 'source_path', 'source_sha256', 'source_bytes', 'functions'}:
        raise ValueError('Manifest must contain metadata only')
    if manifest['source_revision'] != 'd4c9660d40c7e909f18afb166a8e846798f63b1d' or manifest['source_path'] != 'scripts/cucp.ps1':
        raise ValueError('Unexpected immutable Git source identity')
    for function in manifest['functions']:
        if set(function) != {'name', 'utf8_bytes', 'sha256', 'byte_start', 'byte_end'}:
            raise ValueError('Function manifest must contain metadata only')
    return manifest


def verify_original_bytes(data, manifest):
    if len(data) > 2 * 1024 * 1024 or len(data) != manifest['source_bytes'] or digest(data) != manifest['source_sha256']:
        raise ValueError('Pinned original Git source bytes changed or exceeded bounds')
    for function in manifest['functions']:
        start, end = function['byte_start'], function['byte_end']
        if not 0 <= start <= end <= len(data) or end-start != function['utf8_bytes'] or digest(data[start:end]) != function['sha256']:
            raise ValueError('Pinned original helper byte span changed')


def materialize_original(owned_directory, artifact_prefix=None):
    manifest = original_manifest()
    # Exact published immutable tree and fixed source path; no branch names,
    # local-only revisions, external download or current-file fallback.
    data = run_bounded(['git', 'show', manifest['source_revision'] + ':' + manifest['source_path']],
                       timeout=30, stdout_limit=2*1024*1024, artifact_prefix=artifact_prefix, stdout_suffix='.stdout.ps1')
    verify_original_bytes(data, manifest)
    destination = Path(owned_directory) / 'original-cucp.ps1'
    with destination.open('xb') as stream:
        stream.write(data)
    return destination


def input_bytes(cases):
    return dumps(dict(schema=INPUT_SCHEMA, fixtures=cases)).encode('utf-8')


def fixtures():
    cases = []
    def add(name, operation, lines=(), **kw):
        value = dict(id=name, operation=operation, culture='en-US', exists=True,
                     lines=[x if isinstance(x, str) else dumps(x) for x in lines])
        value.update(kw)
        cases.append(value)
    def row(strategy='uia', success=True, **kw):
        value = dict(label='Save', match='App', strategy=strategy, success=success,
                     app_key='key', ts='2026-01-01T00:00:00Z')
        value.update(kw)
        return value
    pick = dict(label='Save', match='App')
    for operation in ('pick', 'stats', 'app-read', 'last-good'):
        for exists in (False, True):
            add(f'{operation}-{"empty" if exists else "missing"}', operation, exists=exists, **pick, app_key='key')
    add('pick-most-recent-tie', 'pick', [row('older'), row('recent')], **pick)
    add('pick-frequency-over-recency', 'pick', [row('a'), row('a'), row('b')], **pick)
    add('pick-failed-consumes-lookback', 'pick', [row('yes'), row('no', False)], lookback=1, **pick)
    add('pick-invalid-and-nonmatch-do-not-consume', 'pick', [row('yes'), '{broken', row('no', label='Other')], lookback=1, **pick)
    add('pick-does-not-sort-ts', 'pick', [row('first', ts='9999'), row('last', ts='0000')], **pick)
    for n in (-2147483648, -1, 0, 1, 2, 5, 2147483647):
        add(f'pick-lookback-{n}', 'pick', [row('a'), row('a'), row('b')], lookback=n, **pick)
    for culture in ('', 'en-US', 'ko-KR', 'tr-TR', 'de-DE'):
        for index, pair in enumerate((('UIA', 'uia'), ('é', 'e\u0301'), ('가', '가'), ('I', 'ı'), ('i', 'İ'), ('K', 'K'), ('s', 'ſ'))):
            for operation in ('pick', 'stats'):
                add(f'{operation}-keys-{culture or "invariant"}-{index}', operation,
                    [row(pair[0]), row(pair[1]), row('separate')], culture=culture, **pick)
            add(f'pick-label-compare-{culture or "invariant"}-{index}', 'pick',
                [row('matched', label=pair[0])], culture=culture, label=pair[1], match='APP')
    values = [None, False, True, 0, 1, 2, -1, 1.0, 1.5, '', 'true', 'TRUE', 'false', '1',
              [], [False], [True], [False, False], [False, True], [0, 1], ['true', 'false'],
              [[True]], [None, True], {}, {'value': True}]
    for i, value in enumerate(values):
        for operation in ('pick', 'stats', 'last-good'):
            add(f'{operation}-success-coercion-{i}', operation, [row('a', value)], **pick, app_key='key')
        for operation in ('pick', 'stats', 'last-good'):
            add(f'{operation}-strategy-interpolation-{i}', operation, [row(value)], **pick, app_key='key')
    raw = ['', ' ', '\t', 'null', 'false', 'true', '0', '1', '""', '"value"', '[]', '[false]', '[false,false]',
           '[null]', '{}', '{broken', '{"x":', 'NaN', 'Infinity', "{label:'Save',match:'App',strategy:'single',success:true}",
           '{"label":"Save","match":"App","strategy":"last", "strategy":"replaced","success":true}',
           '{"label":"Save","match":"App","strategy":"lower","Strategy":"upper","success":true}',
           '{"":1,"success":true,"strategy":"empty-name"}',
           '{"success":true,"strategy":"trailing",}', '// comment',
           '{"success":true,"strategy":"comment"/* comment */}',
           '"\\/Date(0)\\/"', '"2020-01-01T00:00:00Z"', '9223372036854775808', '1e400',
           dumps([row('array-row')]), dumps([row('a'), row('b')]), dumps([[row('nested')]]),
           dumps(dict(row(), unknown={'nested': [1, None, {'x': '한글😀'}]}))]
    for i, text in enumerate(raw):
        for operation in ('pick', 'stats', 'app-read', 'last-good'):
            add(f'{operation}-raw-row-{i}', operation, [text], **pick, app_key='key')
    add('pick-null-and-blank-match-empty', 'pick', [row('old', label='', match=''), 'null', ''], label='', match='', lookback=1)
    add('stats-mixed-lines', 'stats', raw)
    add('app-read-mixed-lines', 'app-read', raw)
    for total, successful in ((16, 1), (16, 3), (40, 1), (40, 3), (3, 1), (3, 2), (2000, 1999)):
        add(f'stats-round-{successful}-{total}', 'stats', [row('x', i < successful) for i in range(total)])
    for size in (1, 2, 3, 7, 17, 33, 100):
        add(f'stats-hashtable-order-{size}', 'stats', [row(f'strategy-{i}') for i in range(size)])
    for size in (2, 3, 5, 17, 33, 100):
        add(f'last-good-equal-ts-{size}', 'last-good', [row(f's{i}', ordinal=i) for i in range(size)], app_key='key')
        add(f'last-good-missing-ts-{size}', 'last-good', [{k: v for k, v in row(f's{i}', ordinal=i).items() if k != 'ts'} for i in range(size)], app_key='key')
    timestamps = [None, '', 'a', 'B', 'é', 'e\u0301', '2', '10', 2, 10, True, False, [], ['a'], {},
                  '2020-01-01T00:00:00+09:00', '2019-12-31T20:00:00Z']
    for i, ts in enumerate(timestamps):
        add(f'last-good-ts-{i}', 'last-good', [row('earlier', ts='2020-01-01T00:00:00Z'), row('test', ts=ts, full_record={'keep': [1, 2]})], app_key='key')
    for culture in ('', 'en-US', 'ko-KR', 'tr-TR', 'de-DE'):
        add(f'last-good-sort-culture-{culture or "invariant"}', 'last-good', [row(f's{i}', ts=ts) for i, ts in enumerate(['é', 'e\u0301', 'I', 'i', 'İ', 'ı', 'z'])], app_key='key', culture=culture)
    add('last-good-full-original-record', 'last-good', [row('winner', unrelated=['keep', None, {'x': 7}], extra=False)], app_key='KEY')
    add('last-good-empty-app-key', 'last-good', [row('ignored', app_key='')], app_key='')
    add('last-good-key-filter', 'last-good', [row('good'), row('new-failed', False, ts='9999'), row('wrong-key', app_key='other', ts='9999')], app_key='key')
    return cases


def validate_report(report, cases, runtime, *, observation=False, source_hash=None, manifest_hash=None, input_hash=None):
    required = {'schema', 'runtime', 'kind', 'host', 'results'}
    if observation:
        required |= {'source_sha256', 'manifest_sha256', 'input_sha256'}
    if not isinstance(report, dict) or set(report) != required:
        raise ValueError('Unexpected report envelope fields')
    if report['schema'] != SCHEMA or report['runtime'] != runtime or report['kind'] != ('windows-observation' if observation else 'candidate-inferred'):
        raise ValueError('Report provenance mismatch')
    if observation and (report['source_sha256'] != source_hash or report['manifest_sha256'] != manifest_hash or report['input_sha256'] != input_hash):
        raise ValueError('Source/input hash mismatch')
    if not isinstance(report['host'], dict) or not report['host']:
        raise ValueError('Missing runtime identity')
    results = report['results']
    if not isinstance(results, list) or len(results) != len(cases):
        raise ValueError('Strict fixture count mismatch')
    for case, result in zip(cases, results):
        if not isinstance(result, dict) or set(result) != {'id', 'operation', 'wire', 'compact_json', 'console', 'errors'}:
            raise ValueError('Unexpected result fields')
        if result['id'] != case['id'] or result['operation'] != case['operation']:
            raise ValueError('Fixture identity/order mismatch')
        if not isinstance(result['console'], str) or not isinstance(result['errors'], list) or any(not isinstance(e, str) for e in result['errors']):
            raise ValueError('Malformed output capture')
        if result['compact_json'] is not None and not isinstance(result['compact_json'], str):
            raise ValueError('Malformed exact JSON capture')
    return results


def compare_reports(candidate, observed):
    mismatches = []
    for left, right in zip(candidate['results'], observed['results']):
        for field in ('wire', 'compact_json', 'console', 'errors'):
            if left[field] != right[field]:
                mismatches.append(dict(id=left['id'], field=field, candidate=left[field], observed=right[field]))
    return mismatches


def dotnet_command():
    found = shutil.which('dotnet')
    if not found and os.environ.get('DOTNET_ROOT'):
        name = 'dotnet.exe' if os.name == 'nt' else 'dotnet'
        candidate = Path(os.environ['DOTNET_ROOT']) / name
        if candidate.exists():
            found = str(candidate)
    return found


def build(dotnet, artifact_prefix=None):
    return run_bounded([dotnet, 'build', str(PROJECT), '--nologo', '-v', 'quiet'],
                       timeout=180, artifact_prefix=artifact_prefix)


def candidate_command(dotnet, runtime):
    return [dotnet, str(PROJECT / 'bin/Debug/net8.0/PcuCp.LegacyHistory.Qualification.dll'), '--runtime', runtime]


def automatic_artifact_prefix():
    global _CAPTURE_SEQUENCE
    target = CONTRACT_CAPTURE_ROOT or os.environ.get('CUCP_HISTORY_CONTRACT_CAPTURE_DIR')
    if not target:
        return None
    root=Path(target);root.mkdir(parents=True,exist_ok=True)
    with _CAPTURE_LOCK:
        _CAPTURE_SEQUENCE += 1
        return root/f'process-{os.getpid()}-{_CAPTURE_SEQUENCE:05d}'


def persist_capture(result, prefix, stdout_suffix):
    prefix=str(prefix)
    Path(prefix+stdout_suffix).write_bytes(result['stdout'])
    Path(prefix+'.stderr.bin').write_bytes(result['stderr'])
    metadata={k:v for k,v in result.items() if k not in ('stdout','stderr')}
    metadata.update(stdout_artifact=Path(prefix+stdout_suffix).name,stdout_bytes=len(result['stdout']),stderr_bytes=len(result['stderr']),
                    stdout_sha256=digest(result['stdout']),stderr_sha256=digest(result['stderr']))
    Path(prefix+'.process.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def capture_process(command, data=None, *, timeout=120, stdout_limit=64*1024*1024, stderr_limit=1024*1024,
                    artifact_prefix=None, stdout_suffix='.stdout.bin', creationflags=0, startupinfo=None):
    """Bound both pipes and persist before any caller parsing or assertions."""
    if stdout_suffix not in ('.stdout.bin','.stdout.ps1'):
        raise ValueError('Unsupported evidence stdout suffix')
    prefixes={str(value) for value in (artifact_prefix,automatic_artifact_prefix()) if value is not None}
    def finish(value):
        for prefix in sorted(prefixes):persist_capture(value,prefix,stdout_suffix)
        return value
    capture = dict(command=list(command), exit_code=None, timed_out=False, launch_error=None,
                   stdout=b'', stderr=b'', stdout_truncated=False, stderr_truncated=False)
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,creationflags=creationflags,startupinfo=startupinfo)
    except OSError as error:
        capture['launch_error'] = str(error)
        return finish(capture)
    buffers={'stdout':bytearray(),'stderr':bytearray()}
    truncated={'stdout':False,'stderr':False}
    stream_errors={}
    lock=threading.Lock()
    def read_pipe(name, pipe, limit):
        try:
            while True:
                # read1 returns available bytes rather than waiting to fill an
                # 8192-byte request while a descendant keeps the pipe open.
                block=pipe.read1(8192)
                if not block:break
                with lock:
                    remaining=max(0,limit-len(buffers[name]))
                    buffers[name].extend(block[:remaining])
                    overflow=len(block)>remaining
                    if overflow:truncated[name]=True
                if overflow:
                    try:process.kill()
                    except OSError:pass
                    break
        except OSError as error:
            with lock:stream_errors[name]=str(error)
        finally:
            pipe.close()
    readers = [threading.Thread(target=read_pipe, args=(name, pipe, limit), daemon=True)
               for name, pipe, limit in (('stdout', process.stdout, stdout_limit), ('stderr', process.stderr, stderr_limit))]
    for thread in readers:thread.start()
    def write_input():
        try:
            if data is not None:
                process.stdin.write(data)
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            if process.stdin is not None:
                try: process.stdin.close()
                except OSError: pass
    writer = threading.Thread(target=write_input, daemon=True)
    writer.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        capture['timed_out'] = True
        process.kill()
        process.wait(timeout=10)
    deadline=time.monotonic()+2
    for thread in readers+[writer]:thread.join(timeout=max(0,deadline-time.monotonic()))
    incomplete=any(thread.is_alive() for thread in readers+[writer])
    with lock:
        for index,name in enumerate(('stdout','stderr')):
            capture[name]=bytes(buffers[name])
            capture[name+'_truncated']=truncated[name] or readers[index].is_alive()
        if stream_errors or incomplete:
            capture['launch_error']='Incomplete pipe drain: '+str(stream_errors or 'descendant or writer kept a pipe open')
    capture['exit_code'] = process.returncode
    return finish(capture)


def run_bounded(command, data=None, *, timeout=120, stdout_limit=64*1024*1024, stderr_limit=1024*1024, artifact_prefix=None, stdout_suffix='.stdout.bin'):
    if stdout_suffix not in ('.stdout.bin', '.stdout.ps1'):
        raise ValueError('Unsupported evidence stdout suffix')
    result = capture_process(command, data, timeout=timeout, stdout_limit=stdout_limit, stderr_limit=stderr_limit,
                             artifact_prefix=artifact_prefix, stdout_suffix=stdout_suffix)
    if result['launch_error'] or result['timed_out'] or result['stdout_truncated'] or result['stderr_truncated'] or result['exit_code'] != 0 or result['stderr']:
        raise RuntimeError('Qualification subprocess failed: ' + str({k:v for k,v in result.items() if k not in ('stdout','stderr','command')}) +
                           '; stderr=' + result['stderr'].decode('utf-8','replace')[:4000])
    return result['stdout']



def differential(args):
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if next(report_dir.iterdir(), None) is not None:
        raise RuntimeError('Report directory must be empty; refusing to overwrite earlier qualification evidence.')
    cases = fixtures()
    data = input_bytes(cases)
    (report_dir / 'input.json').write_bytes(data)
    report = dict(schema='cucp.history-reducer-gate/v1', status='blocked', production_cutover=False,
                  fixture_count=len(cases), source_sha256=SOURCE_SHA256, manifest_sha256=digest(ORIGINAL.read_bytes()), input_sha256=digest(data),
                  oracle_source_sha256=digest((FIXTURES/'oracle.ps1').read_bytes()),
                  candidate_source_sha256={p.name: digest(p.read_bytes()) for p in sorted(PROJECT.glob('*')) if p.is_file()},
                  new_tracked_powershell_source_bytes=len((FIXTURES / 'oracle.ps1').read_bytes()), duplicated_original_source_bytes=0,
                  known_qualification_boundaries=KNOWN_GATES, runs=[], errors=[])
    try:
        if report['manifest_sha256'] != ORIGINAL_SHA256:
            raise ValueError('Immutable original manifest changed')
        if os.name != 'nt':
            raise RuntimeError('Real Windows PS5.1/PS7 observation gate is unavailable on this host; inferred Linux tests are not parity evidence.')
        dotnet = dotnet_command()
        if not dotnet or not args.ps51 or not args.ps7:
            raise RuntimeError('Both explicit Windows PS5.1/PS7 executable paths and dotnet are required.')
        build(dotnet, artifact_prefix=report_dir/'build')
        # Exercise both singleton and many-case envelopes independently, then
        # repeat the full suite in fresh processes to reveal Hashtable seeding.
        with tempfile.TemporaryDirectory(prefix='cucp-history-original-') as owned:
            source_path = materialize_original(owned, artifact_prefix=report_dir/'original-git-source')
            for runtime, executable in (('ps51', args.ps51), ('ps7', args.ps7)):
                for label, subset in (('singleton', cases[:1]), ('many', cases)):
                    encoded = input_bytes(subset)
                    synthetic = report_dir / f'{runtime}-{label}-input.json'
                    synthetic.write_bytes(encoded)
                    repetitions = 1 if label == 'singleton' else 2
                    for repeat in range(repetitions):
                        prefix = f'{runtime}-{label}-{repeat}'
                        candidate_bytes = run_bounded(candidate_command(dotnet, runtime), encoded, artifact_prefix=report_dir/(prefix+'-candidate'))
                        observed_bytes = run_bounded([executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(FIXTURES / 'oracle.ps1'), '-InputPath', str(synthetic), '-SourcePath', str(source_path), '-Runtime', runtime], artifact_prefix=report_dir/(prefix+'-observed'))
                        (report_dir / (prefix + '-candidate.raw.json')).write_bytes(candidate_bytes)
                        (report_dir / (prefix + '-observed.raw.json')).write_bytes(observed_bytes)
                        candidate, observed = json.loads(candidate_bytes), json.loads(observed_bytes)
                        validate_report(candidate, subset, runtime)
                        validate_report(observed, subset, runtime, observation=True, source_hash=SOURCE_SHA256, manifest_hash=ORIGINAL_SHA256, input_hash=digest(encoded))
                        mismatches = compare_reports(candidate, observed)
                        (report_dir / (prefix + '-mismatches.json')).write_text(json.dumps(mismatches, ensure_ascii=False, indent=2), encoding='utf-8')
                        report['runs'].append(dict(runtime=runtime, batch=label, repeat=repeat, count=len(subset),
                            candidate_sha256=digest(candidate_bytes), observed_sha256=digest(observed_bytes),
                            mismatch_count=len(mismatches), candidate_host=candidate['host'], observed_host=observed['host']))
        report['status'] = 'failed-parity' if any(run['mismatch_count'] for run in report['runs']) else 'passed-candidate-parity'
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report['errors'].append(str(error))
    (report_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], fixture_count=len(cases), runs=len(report['runs']), report=str(report_dir / 'report.json'))))
    return 0 if report['status'] == 'passed-candidate-parity' else 1


def unicode_transport_cases():
    text = '한글😀 é e\u0301 İ 𐐷'
    row = dict(label=text, match=text, app_key=text, strategy=text, success=True, extra=[text, {'nested':text}])
    return [dict(id='utf8-pick', operation='pick', culture='en-US', exists=True, lines=[dumps(row)], label=text, match=text),
            dict(id='utf8-record', operation='last-good', culture='en-US', exists=True, lines=[dumps(row)], app_key=text)]


def owned_console_utf8_probe():
    if os.name != 'nt':
        raise RuntimeError('Owned console probe requires Windows')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    processes = (wintypes.DWORD * 8)()
    count = kernel.GetConsoleProcessList(processes, 8)
    # Refuse before any setter unless this is an isolated console owned solely
    # by this new child. Never change the parent's/user's shared console.
    if count != 1 or processes[0] != os.getpid():
        raise RuntimeError('Refusing to alter a shared or unverified console')
    old_input, old_output = kernel.GetConsoleCP(), kernel.GetConsoleOutputCP()
    reports = []
    try:
        if not kernel.SetConsoleCP(949) or not kernel.SetConsoleOutputCP(1252):
            raise RuntimeError('Could not set code pages in the owned child console')
        if kernel.GetConsoleCP() != 949 or kernel.GetConsoleOutputCP() != 1252:
            raise RuntimeError('Owned non-65001 code pages not active')
        cases = unicode_transport_cases()
        for runtime in ('ps51', 'ps7'):
            raw = run_bounded(candidate_command(dotnet_command(), runtime), input_bytes(cases))
            parsed = json.loads(raw.decode('utf-8', 'strict'))
            validate_report(parsed, cases, runtime)
            if json.loads(parsed['results'][0]['compact_json']) != cases[0]['label'] or json.loads(parsed['results'][1]['compact_json']) != json.loads(cases[1]['lines'][0]):
                raise RuntimeError('Unicode changed under owned non-65001 console')
            reports.append(parsed)
        result = dict(input_code_page=kernel.GetConsoleCP(), output_code_page=kernel.GetConsoleOutputCP(), reports=reports)
    finally:
        kernel.SetConsoleCP(old_input)
        kernel.SetConsoleOutputCP(old_output)
    sys.stdout.buffer.write(dumps(result).encode('utf-8'))
    return 0


class HistoryEvidenceTests(unittest.TestCase):
    def test_failed_process_preserves_both_pipes_and_exit(self):
        with tempfile.TemporaryDirectory(prefix='history-evidence-') as owned:
            prefix=Path(owned)/'failed'
            command=[sys.executable, '-c', "import sys;sys.stdout.buffer.write(b'first output');sys.stderr.buffer.write(b'first error');sys.exit(7)"]
            with self.assertRaises(RuntimeError): run_bounded(command, artifact_prefix=prefix)
            self.assertEqual(Path(str(prefix)+'.stdout.bin').read_bytes(), b'first output')
            self.assertEqual(Path(str(prefix)+'.stderr.bin').read_bytes(), b'first error')
            metadata=json.loads(Path(str(prefix)+'.process.json').read_text())
            self.assertEqual(metadata['exit_code'], 7)
            self.assertFalse(metadata['timed_out'])
    def test_timeout_preserves_partial_output(self):
        with tempfile.TemporaryDirectory(prefix='history-evidence-') as owned:
            prefix=Path(owned)/'timeout'
            command=[sys.executable, '-c', "import sys,time;sys.stdout.buffer.write(b'before timeout');sys.stdout.flush();time.sleep(5)"]
            with self.assertRaises(RuntimeError): run_bounded(command, timeout=0.5, artifact_prefix=prefix)
            self.assertEqual(Path(str(prefix)+'.stdout.bin').read_bytes(), b'before timeout')
            self.assertTrue(json.loads(Path(str(prefix)+'.process.json').read_text())['timed_out'])
    def test_output_limit_preserves_bounded_prefix_and_failure(self):
        with tempfile.TemporaryDirectory(prefix='history-evidence-') as owned:
            prefix=Path(owned)/'oversize'
            with self.assertRaises(RuntimeError): run_bounded([sys.executable, '-c', "import sys;sys.stdout.buffer.write(b'x'*4096)"], stdout_limit=64, artifact_prefix=prefix)
            self.assertEqual(Path(str(prefix)+'.stdout.bin').read_bytes(), b'x'*64)
            self.assertTrue(json.loads(Path(str(prefix)+'.process.json').read_text())['stdout_truncated'])
    def test_automatic_contract_evidence_survives_parse_and_launch_failures(self):
        global CONTRACT_CAPTURE_ROOT
        old=CONTRACT_CAPTURE_ROOT
        with tempfile.TemporaryDirectory(prefix='history-auto-evidence-') as owned:
            root=old or Path(owned);CONTRACT_CAPTURE_ROOT=root
            before=set(root.glob('*.process.json'))
            try:
                raw=run_bounded([sys.executable,'-c',"import sys;sys.stdout.buffer.write(b'not-json');sys.stdout.flush()"])
                with self.assertRaises(json.JSONDecodeError):json.loads(raw)
                capture_process([str(Path(owned)/'absent')])
                added=set(root.glob('*.process.json'))-before
                self.assertEqual(len(added),2)
                records=[json.loads(path.read_text()) for path in added]
                self.assertTrue(any(record['launch_error'] for record in records))
                self.assertTrue(any((root/record['stdout_artifact']).read_bytes()==b'not-json' for record in records))
            finally:CONTRACT_CAPTURE_ROOT=old
    def test_timeout_retains_prefix_when_descendant_holds_pipes(self):
        child="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(8)']); print(p.pid,flush=True); print('MARKER-BEFORE-TIMEOUT',flush=True); time.sleep(60)"
        result=capture_process([sys.executable,'-c',child],timeout=0.7)
        pid=None
        try:
            lines=result['stdout'].splitlines()
            if lines and lines[0].isdigit():pid=int(lines[0])
            self.assertTrue(result['timed_out'])
            self.assertIn(b'MARKER-BEFORE-TIMEOUT',result['stdout'])
            self.assertTrue(result['stdout_truncated'])
            self.assertIn('Incomplete pipe drain',result['launch_error'])
        finally:
            if pid is not None:
                # Only the descendant created by this exact owned fixture.
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
    def test_launch_failure_has_artifacts(self):
        with tempfile.TemporaryDirectory(prefix='history-evidence-') as owned:
            prefix=Path(owned)/'missing'
            with self.assertRaises(RuntimeError): run_bounded([str(Path(owned)/'absent-executable')], artifact_prefix=prefix)
            self.assertEqual(Path(str(prefix)+'.stdout.bin').read_bytes(), b'')
            self.assertTrue(json.loads(Path(str(prefix)+'.process.json').read_text())['launch_error'])


class HistorySourceTests(unittest.TestCase):
    def test_pinned_function_bytes_and_current_tracked_helpers(self):
        self.assertEqual(digest(ORIGINAL.read_bytes()), ORIGINAL_SHA256)
        manifest = original_manifest()
        # Compare canonical tracked bytes, as the migration inventory does.
        # Windows checkout CRLF is not a source-body change; no oracle input or
        # accepted output is normalized by this check.
        current = run_bounded(['git','show',':'+manifest['source_path']],stdout_limit=2*1024*1024,stdout_suffix='.stdout.ps1')
        with tempfile.TemporaryDirectory(prefix='history-loader-test-') as owned:
            source = materialize_original(owned).read_bytes()
        self.assertEqual(digest(source), SOURCE_SHA256)
        self.assertEqual(sum(f['utf8_bytes'] for f in manifest['functions']), 3651)
        for function in manifest['functions']:
            body = source[function['byte_start']:function['byte_end']]
            self.assertEqual(len(body), function['utf8_bytes'])
            self.assertEqual(digest(body), function['sha256'])
            extracted = re.search(rb'^function ' + re.escape(function['name'].encode()) + rb' \{.*?^\}', current, re.M | re.S).group()
            self.assertEqual(extracted, body)
    def test_original_loader_rejects_corrupt_and_oversized_bytes(self):
        manifest = original_manifest()
        with tempfile.TemporaryDirectory(prefix='history-loader-test-') as owned:
            data = materialize_original(owned).read_bytes()
        for invalid in (data[:-1], b'x'+data[1:], b'x'*(2*1024*1024+1)):
            with self.assertRaises(ValueError): verify_original_bytes(invalid, manifest)
    def test_original_loader_rejects_altered_spans(self):
        manifest = original_manifest()
        with tempfile.TemporaryDirectory(prefix='history-loader-test-') as owned:
            data = materialize_original(owned).read_bytes()
        for start in (-1, len(data), manifest['functions'][0]['byte_start']+1):
            changed = copy.deepcopy(manifest); changed['functions'][0]['byte_start'] = start
            with self.assertRaises(ValueError): verify_original_bytes(data, changed)
    def test_original_loader_never_overwrites_a_destination(self):
        with tempfile.TemporaryDirectory(prefix='history-loader-test-') as owned:
            destination = Path(owned)/'original-cucp.ps1'
            destination.write_bytes(b'preserve-owned-file')
            with self.assertRaises(FileExistsError): materialize_original(owned)
            self.assertEqual(destination.read_bytes(), b'preserve-owned-file')
    def test_manifest_contains_no_executable_source(self):
        manifest = original_manifest()
        self.assertNotIn('function ', ORIGINAL.read_text())
        self.assertTrue(all('source' not in entry for entry in manifest['functions']))
        oracle = (FIXTURES/'oracle.ps1').read_text()
        self.assertIn('. ([scriptblock]::Create($body))', oracle)
        self.assertNotRegex(oracle, r'(?i)scriptblock\]\s*::Create\(\$(?:sourceText|sourceBytes)\)')
        self.assertNotRegex(oracle, r'(?im)^\s*(?:&|\.)\s*\$SourcePath')
    def test_fixture_identity_and_coverage(self):
        cases = fixtures()
        self.assertEqual(len(cases), len({f['id'] for f in cases}))
        self.assertGreater(len(cases), 400)
        self.assertLessEqual(len(cases), 2048)
        self.assertEqual({f['operation'] for f in cases}, {'pick', 'stats', 'app-read', 'last-good'})
        self.assertTrue(all(set(f) <= {'id', 'operation', 'culture', 'exists', 'lines', 'label', 'match', 'lookback', 'app_key'} for f in cases))
        self.assertTrue(all('\n' not in line and '\r' not in line for f in cases for line in f['lines']))
    def test_no_production_reference_or_operation(self):
        for folder in (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost', ROOT / 'pcucp-next/python'):
            for path in folder.rglob('*'):
                if path.suffix in ('.cs', '.csproj', '.py'):
                    self.assertNotIn('PcuCp.LegacyHistory.Qualification', path.read_text())
        for path in PROJECT.glob('*.cs'):
            self.assertNotRegex(path.read_text(), r'\b(?:File|Directory|Process|HttpClient)\.')
    def test_gate_retains_exact_order_and_text(self):
        result = dict(id='x', operation='stats', wire={'kind': 'hashtable', 'properties': [{'name': 'a'}, {'name': 'b'}]}, compact_json='{"a":1,"b":2}', console='', errors=[])
        left = dict(results=[result]); right = copy.deepcopy(left)
        right['results'][0]['wire']['properties'].reverse()
        right['results'][0]['compact_json'] = '{"b":2,"a":1}'
        self.assertEqual([x['field'] for x in compare_reports(left, right)], ['wire', 'compact_json'])
    def test_gate_rejects_missing_count_identity_and_fields(self):
        cases = fixtures()[:2]
        report = dict(schema=SCHEMA, runtime='ps51', kind='candidate-inferred', host={'fixture': True}, results=[dict(id=f['id'], operation=f['operation'], wire={'kind':'null'}, compact_json='null', console='', errors=[]) for f in cases])
        validate_report(report, cases, 'ps51')
        for mutate in (lambda r: r['results'].pop(), lambda r: r['results'].reverse(), lambda r: r['results'][0].pop('wire'), lambda r: r.update(extra=True)):
            changed = copy.deepcopy(report); mutate(changed)
            with self.assertRaises(ValueError): validate_report(changed, cases, 'ps51')
    def test_gate_rejects_provenance_mismatch(self):
        cases = fixtures()[:1]
        report = dict(schema=SCHEMA, runtime='ps51', kind='windows-observation', host={'ps_version': '5.1'}, source_sha256='wrong', manifest_sha256='wrong', input_sha256='wrong', results=[])
        with self.assertRaises(ValueError): validate_report(report, cases, 'ps51', observation=True, source_hash=SOURCE_SHA256, manifest_hash=ORIGINAL_SHA256, input_hash='expected')
    def test_singleton_envelope_remains_an_array(self):
        self.assertEqual(len(json.loads(input_bytes(fixtures()[:1]))['fixtures']), 1)
        self.assertIn('$fixtures=$envelope.fixtures', (FIXTURES / 'oracle.ps1').read_text())
    def test_new_powershell_is_explicitly_counted(self):
        # The only newly tracked executable PowerShell source is oracle.ps1.
        # Original source remains in its existing .ps1 Git blob, not JSON/data.
        files = [p for p in FIXTURES.rglob('*') if p.is_file()]
        self.assertEqual(sorted(p.name for p in files), ['oracle.ps1', 'original-functions.json'])
        self.assertGreater(len((FIXTURES / 'oracle.ps1').read_bytes()), 0)
        self.assertNotIn('"source":', ORIGINAL.read_text())


@unittest.skipUnless(dotnet_command(), 'dotnet SDK/runtime unavailable; no C# candidate claim')
class HistoryCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotnet = dotnet_command()
        build(cls.dotnet)
    def assert_completed_process(self,result,*,success):
        self.assertIs(type(result['exit_code']),int)
        self.assertIsNone(result['launch_error'])
        self.assertFalse(result['timed_out'])
        self.assertFalse(result['stdout_truncated'])
        self.assertFalse(result['stderr_truncated'])
        if success:
            self.assertEqual(result['exit_code'],0)
            self.assertEqual(result['stderr'],b'')
        else:
            self.assertNotEqual(result['exit_code'],0)
    def test_expected_rejection_requires_completed_process(self):
        complete=dict(exit_code=1,launch_error=None,timed_out=False,stdout_truncated=False,stderr_truncated=False,stdout=b'',stderr=b'expected rejection')
        self.assert_completed_process(complete,success=False)
        for changes in ({'exit_code':None},{'exit_code':False},{'exit_code':0},{'launch_error':'missing executable'},{'timed_out':True},{'stdout_truncated':True},{'stderr_truncated':True}):
            with self.assertRaises(AssertionError):self.assert_completed_process(dict(complete,**changes),success=False)
    def run_cases(self, cases, runtime='ps51'):
        raw = run_bounded(candidate_command(self.dotnet, runtime), input_bytes(cases))
        report = json.loads(raw)
        validate_report(report, cases, runtime)
        return report['results']
    def test_inferred_self_tests(self):
        output = run_bounded([self.dotnet, str(PROJECT / 'bin/Debug/net8.0/PcuCp.LegacyHistory.Qualification.dll'), '--self-test'])
        self.assertIn(b'66 inferred history contracts', output)
    def test_both_candidate_profiles_complete_full_corpus(self):
        cases = fixtures()
        for runtime in ('ps51', 'ps7'):
            with self.subTest(runtime=runtime): self.assertEqual(len(self.run_cases(cases, runtime)), len(cases))
    def test_one_and_many_case_transport(self):
        for runtime in ('ps51', 'ps7'):
            for size in (1, 2, 17):
                with self.subTest(runtime=runtime, size=size): self.assertEqual(len(self.run_cases(fixtures()[:size], runtime)), size)
    def test_expected_selection_examples_are_inferences(self):
        cases = [f for f in fixtures() if f['id'] in ('pick-most-recent-tie', 'pick-frequency-over-recency', 'pick-failed-consumes-lookback', 'pick-invalid-and-nonmatch-do-not-consume', 'pick-does-not-sort-ts')]
        results = {r['id']: json.loads(r['compact_json']) for r in self.run_cases(cases)}
        self.assertEqual(results, {'pick-most-recent-tie':'recent', 'pick-frequency-over-recency':'a', 'pick-failed-consumes-lookback':None, 'pick-invalid-and-nonmatch-do-not-consume':'yes', 'pick-does-not-sort-ts':'last'})
    def test_last_good_preserves_unrelated_fields(self):
        case = next(f for f in fixtures() if f['id'] == 'last-good-full-original-record')
        parsed = json.loads(self.run_cases([case])[0]['compact_json'])
        self.assertEqual(parsed, json.loads(case['lines'][0]))
    def test_invalid_authority_and_capture_shapes_rejected(self):
        case = fixtures()[0]
        for update in ({'operation':'append'}, {'path':'C:\\user\\history'}, {'lines':[None]}, {'lines':['{}']}, {'lookback':1.5}, {'exists':'false'}):
            invalid = dict(case, **update)
            result = capture_process(candidate_command(self.dotnet, 'ps51'),input_bytes([invalid]),timeout=30)
            self.assert_completed_process(result,success=False)
    def test_strict_utf8_unicode_transport(self):
        cases=unicode_transport_cases()
        for runtime in ('ps51','ps7'):
            raw=run_bounded(candidate_command(self.dotnet,runtime),input_bytes(cases))
            report=json.loads(raw.decode('utf-8','strict'))
            self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
            self.assertEqual(report['host']['wire_encoding'],'utf-8-strict')
            self.assertEqual(json.loads(report['results'][0]['compact_json']),cases[0]['label'])
            self.assertEqual(json.loads(report['results'][1]['compact_json']),json.loads(cases[1]['lines'][0]))
    def test_malformed_utf8_is_rejected_without_replacement(self):
        valid=input_bytes([dict(fixtures()[0],id='replace-me')])
        for invalid in (b'\xff',b'\xc0\xaf',b'\xed\xa0\x80',b'\xf0\x80\x80\x80',b'\xe2\x82'):
            data=valid.replace(b'replace-me',invalid)
            result=capture_process(candidate_command(self.dotnet,'ps51'),data)
            self.assert_completed_process(result,success=False)
            self.assertEqual(result['stdout'],b'')
            self.assertIn(b'DecoderFallbackException',result['stderr'])
    def test_stdin_byte_limit_precedes_decoding(self):
        result=capture_process(candidate_command(self.dotnet,'ps51'),('한'*(16*1024*1024//3+1)).encode('utf-8'))
        self.assert_completed_process(result,success=False)
        self.assertIn(b'16 MiB',result['stderr'])
        self.assertEqual(result['stdout'],b'')
    @unittest.skipUnless(os.name == 'nt','Owned non-65001 Windows console probe requires Windows')
    def test_owned_windows_non65001_console_transport(self):
        startup=subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow=0
        result=capture_process([sys.executable,str(Path(__file__).resolve()),'--owned-console-utf8-probe'],timeout=120,
                               creationflags=subprocess.CREATE_NEW_CONSOLE,startupinfo=startup)
        self.assert_completed_process(result,success=True)
        evidence=json.loads(result['stdout'].decode('utf-8','strict'))
        self.assertEqual((evidence['input_code_page'],evidence['output_code_page']),(949,1252))
        self.assertEqual(len(evidence['reports']),2)
    def test_duplicate_fixture_ids_rejected(self):
        case = fixtures()[0]
        result = capture_process(candidate_command(self.dotnet, 'ps51'),input_bytes([case,case]),timeout=30)
        self.assert_completed_process(result,success=False)


def windows_contracts(report_path):
    global CONTRACT_CAPTURE_ROOT
    old_root=CONTRACT_CAPTURE_ROOT
    old_env=os.environ.get('CUCP_HISTORY_CONTRACT_CAPTURE_DIR')
    report = dict(schema='cucp.history-windows-contracts/v1', status='blocked', tests_run=0,
                  test_ids=[], skipped=[], failures=[], errors=[], owned_non65001_probe='not-run')
    try:
        if os.name != 'nt' or not dotnet_command():
            raise RuntimeError('Actual Windows and dotnet are required; no skip-only contract pass is accepted')
        CONTRACT_CAPTURE_ROOT=Path(report_path).resolve().parent/'windows-contract-processes'
        CONTRACT_CAPTURE_ROOT.mkdir(parents=True,exist_ok=True)
        os.environ['CUCP_HISTORY_CONTRACT_CAPTURE_DIR']=str(CONTRACT_CAPTURE_ROOT)
        report['process_artifact_directory']=CONTRACT_CAPTURE_ROOT.name
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        def names(value):
            for item in value:
                if isinstance(item, unittest.TestSuite):
                    yield from names(item)
                else:
                    yield item.id()
        report['test_ids'] = list(names(suite))
        required = 'HistoryCandidateTests.test_owned_windows_non65001_console_transport'
        if not report['test_ids'] or not any(name.endswith(required) for name in report['test_ids']):
            raise RuntimeError('Required owned-console test is absent')
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
        report.update(tests_run=result.testsRun, skipped=[(test.id(), reason) for test, reason in result.skipped],
                      failures=[(test.id(), text) for test, text in result.failures], errors=[(test.id(), text) for test, text in result.errors])
        if result.wasSuccessful() and not result.skipped and result.testsRun == len(report['test_ids']):
            report['status']='passed-windows-contracts'
            report['owned_non65001_probe']='passed'
        else:
            report['status']='failed-windows-contracts'
    except (RuntimeError, OSError) as error:
        report['errors'].append(('gate',str(error)))
    if CONTRACT_CAPTURE_ROOT is not None:
        report['process_artifact_count']=len(list(CONTRACT_CAPTURE_ROOT.glob('*.process.json')))
    CONTRACT_CAPTURE_ROOT=old_root
    if old_env is None:os.environ.pop('CUCP_HISTORY_CONTRACT_CAPTURE_DIR',None)
    else:os.environ['CUCP_HISTORY_CONTRACT_CAPTURE_DIR']=old_env
    path=Path(report_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if report['status']=='passed-windows-contracts' else 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--owned-console-utf8-probe']:
        raise SystemExit(owned_console_utf8_probe())
    if '--windows-contracts' in sys.argv:
        parser=argparse.ArgumentParser(description='All real-Windows history contracts; skips are a failure.')
        parser.add_argument('--windows-contracts',action='store_true')
        parser.add_argument('--report-path',required=True)
        raise SystemExit(windows_contracts(parser.parse_args().report_path))
    if '--differential' in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--differential', action='store_true')
        parser.add_argument('--ps51', help='Explicit Windows powershell.exe path')
        parser.add_argument('--ps7', help='Explicit Windows pwsh.exe path')
        parser.add_argument('--report-dir', required=True)
        raise SystemExit(differential(parser.parse_args()))
    unittest.main()
