"""Actual PS5/PS7 parser and production-host completion validation; inert effects."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_legacy_execution_parity import ROOT, adapter_source, built_candidate
from test_legacy_execution_startup import startup_wire
from test_legacy_execution_transport import wire

RUNNER = ROOT / 'tests/fixtures/legacy-execution-completion.ps1'
INT_MIN, INT_MAX = -(2 ** 31), 2 ** 31 - 1


def completion_cases():
    rows = []

    def add(family, label, accepted=True, after_write=False, **changes):
        envelope = dict(payload=wire('fixture'), exit=0, json_depth=1, brief=None, emit_json=True)
        envelope.update(changes)
        rows.append(dict(case=f'{family}:{label}', family=family, accepted=accepted,
                         after_write=after_write, completion=json.dumps(envelope, separators=(',', ':')),
                         process_exit=envelope['exit'] if accepted else 0))

    for family in ('execution', 'interaction', 'diagnostics'):
        for exit_code, depth in ((0, 0), (1, 1), (2, 100), (3, 1)):
            add(family, f'valid-{exit_code}-{depth}', exit=exit_code, json_depth=depth)
        add(family, 'brief', emit_json=False, brief='completion fixture')
        for field in ('exit', 'json_depth'):
            for label, value in (('null', None), ('false', False), ('true', True), ('string', '0'),
                                 ('integral-float', 0.0), ('fraction', 0.5), ('array', []), ('object', {})):
                add(family, f'{field}-{label}', False, **{field: value})
        for value in (INT_MIN - 1, INT_MAX + 1, -(2 ** 63), 2 ** 63 - 1):
            add(family, f'exit-range-{value}', False, exit=value)
        for value in (-1, 101, INT_MAX + 1):
            add(family, f'depth-range-{value}', False, json_depth=value)
        if family != 'interaction':
            for value in (-1, 4):
                add(family, f'family-exit-{value}', False, exit=value)
    for value in (INT_MIN, -1, 7, INT_MAX):
        add('interaction', f'signed-exit-{value}', exit=value)
    # The same malformed bytes are consumed after an acknowledged, captured
    # production TrajectoryAppend dispatch. No file/history provider is loaded.
    for row in list(rows):
        if row['family'] == 'execution' and not row['accepted']:
            rows.append(dict(row, case=row['case'] + ':after-write', after_write=True))
    add('execution', 'valid-after-write', after_write=True)
    return rows


def fixture_environment(root, path):
    env = dict(os.environ, CUCP_COMPLETION_FIXTURE=str(path), CUCP_EXECUTION_DIAGNOSTICS='0')
    env.update(TEMP=str(root), TMP=str(root), TMPDIR=str(root))
    return env


class CompletionFixtureTests(unittest.TestCase):
    def test_existing_session_fixture_preserves_uncoerced_completion_bytes_and_write_ack(self):
        dotnet, host = built_candidate()
        selected = [r for r in completion_cases() if r['case'] in
                    ('execution:exit-integral-float', 'execution:json_depth-false:after-write')]
        self.assertEqual(len(selected), 2)
        with tempfile.TemporaryDirectory(prefix='CUCP completion stream ') as temp:
            root = Path(temp)
            for index, row in enumerate(selected):
                with self.subTest(case=row['case']):
                    path, log = root / f'{index}.json', root / f'{index}.log'
                    path.write_text(json.dumps(dict(row, log=str(log))), encoding='utf-8')
                    stdin = startup_wire(dict(operation='workflow-run'))
                    if row['after_write']:
                        data = json.dumps(dict(state='ok', value=wire(None))).encode()
                        stdin += json.dumps(dict(kind='part', id=1, data=base64.b64encode(data).decode())) + '\n'
                        stdin += '{"kind":"end","id":1}\n'
                    process = subprocess.run([dotnet, str(host), 'legacy-execution-session'],
                                             input=stdin, text=True, encoding='utf-8', capture_output=True,
                                             env=fixture_environment(root, path), timeout=30)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    messages, parts = [], bytearray()
                    for line in process.stdout.splitlines():
                        frame = json.loads(line)
                        if frame['kind'] == 'part':
                            parts.extend(base64.b64decode(frame['data']))
                        else:
                            messages.append((frame['target'], frame['id'], bytes(parts)))
                            parts.clear()
                    self.assertEqual(messages[-1], ('complete', 2 if row['after_write'] else 1,
                                                     row['completion'].encode()))
                    self.assertEqual(len(messages), 2 if row['after_write'] else 1)
                    if row['after_write']:
                        effect = json.loads(messages[0][2])
                        self.assertEqual((effect['kind'], effect['name']), ('TrajectoryAppend', 'workflow-run'))
                        self.assertFalse(effect['live'])
                    self.assertEqual(log.read_text().splitlines(),
                                     ['start', 'startup'] + (['write-acknowledged'] if row['after_write'] else []))


@unittest.skipUnless(sys.platform == 'win32', 'Requires both Windows PowerShell 5.1 and PowerShell 7')
class CompletionParserHostTests(unittest.TestCase):
    def run_parser(self, executable, major):
        shell = shutil.which(executable)
        self.assertIsNotNone(shell, f'Required completion regression runtime missing: {executable}')
        self.assertIsNotNone(os.environ.get('DOTNET') or shutil.which('dotnet'), 'Required dotnet SDK missing')
        _, host = built_candidate()
        cases = completion_cases()
        with tempfile.TemporaryDirectory(prefix=f'CUCP completion PS{major} ') as temp:
            root = Path(temp)
            inputs = []
            for index, row in enumerate(cases):
                path, log = root / f'{index}.json', root / f'{index}.log'
                path.write_text(json.dumps(dict(row, log=str(log))), encoding='utf-8')
                inputs.append(dict(case=row['case'], family=row['family'], fixture=str(path)))
            source = root / 'cases.json'
            source.write_text(json.dumps(inputs), encoding='utf-8')
            process = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(RUNNER),
                                      '-Source', str(adapter_source()), '-DiagnosticSource',
                                      str(ROOT / 'scripts/cucp-legacy-diagnostic-adapter.ps1'),
                                      '-InputPath', str(source), '-HostPath', str(host), '-ExpectedMajor', str(major)],
                                     capture_output=True, env=fixture_environment(root, root / 'unused.json'), timeout=180)
            self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
            result = json.loads(process.stdout.decode('utf-8-sig'))
            self.assertEqual(result['major'], major)
            self.assertEqual(len(result['rows']), len(cases))
            for index, (case, actual) in enumerate(zip(cases, result['rows'])):
                with self.subTest(runtime=executable, case=case['case']):
                    self.assertEqual(actual['case'], case['case'])
                    self.assertEqual(actual['dispatches'], int(case['after_write']))
                    self.assertEqual(actual['state_effect_seen'], case['after_write'])
                    self.assertFalse(actual['live_effect_seen'])
                    self.assertEqual(actual['phase'], 'validate-completion')
                    self.assertEqual((root / f'{index}.log').read_text().splitlines(),
                                     ['start', 'startup'] + (['write-acknowledged'] if case['after_write'] else []))
                    if case['accepted']:
                        self.assertIsNone(actual['error'])
                        buffered = ['buffered pipeline fixture'] if case['family'] == 'interaction' else []
                        self.assertEqual(actual['pipeline'], buffered + [case['process_exit']])
                        self.assertEqual(actual['exit_type'], 'System.Int32' if major == 5 else 'System.Int64')
                        self.assertEqual(actual['depth_type'], 'System.Int32' if major == 5 else 'System.Int64')
                        if json.loads(case['completion'])['emit_json']:
                            self.assertEqual(json.loads(actual['console']), 'fixture')
                        else:
                            self.assertEqual(actual['console'], 'completion fixture\r\n')
                    else:
                        prefix = 'mutation_may_have_occurred=true; automatic_retry=false; ' if case['after_write'] else ''
                        self.assertEqual(actual['error'], prefix + 'Invalid execution completion envelope.')
                        self.assertEqual(actual['pipeline'], [])
                        self.assertEqual(actual['console'], '')

    def test_windows_powershell_51_completion_parser_and_host(self):
        self.run_parser('powershell.exe', 5)

    def test_powershell_7_completion_parser_and_host(self):
        self.run_parser('pwsh', 7)
