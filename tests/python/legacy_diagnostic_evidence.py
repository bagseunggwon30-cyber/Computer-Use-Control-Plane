"""Bounded, qualification-only evidence; never used by production dispatch."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

MAX_STDOUT = 8 * 1024 * 1024
MAX_STDERR = 1024 * 1024
MAX_INPUT = 4 * 1024 * 1024
CAPTURE_ENV = 'CUCP_DIAGNOSTICS_RETAINED_CAPTURE_DIR'


def _error(error):
    return dict(type=type(error).__name__, message=str(error)[:16384])


def _bytes(value):
    if value is None:
        return b''
    return value if isinstance(value, bytes) else value.encode('utf-8', errors='backslashreplace')


def file_identity(path):
    if path is None:
        return None
    result = dict(path=str(path))
    try:
        path = Path(path)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk)
        result.update(sha256=digest.hexdigest(), bytes=path.stat().st_size)
    except (OSError, ValueError) as error:
        result['error'] = _error(error)
    return result


class DiagnosticEvidence:
    def __init__(self, root, fixtures, planned_routes):
        encoded = json.dumps(fixtures, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        if len(encoded) > MAX_INPUT or not 1 <= len(fixtures) <= 1024:
            raise ValueError('Retained diagnostic evidence input exceeds its fixed bound')
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='run-', dir=root))
        self.manifest = dict(schema='cucp.retained-diagnostic-evidence/v1',
            started_at_utc=datetime.now(timezone.utc).isoformat(), finished=False,
            comparison_completed=False, qualification_passed=False,
            fixture_count=len(fixtures), case_ids=[f['case_id'] for f in fixtures],
            input_file='fixtures.json', input_sha256=hashlib.sha256(encoded).hexdigest(),
            limits=dict(stdout_bytes=MAX_STDOUT, stderr_bytes=MAX_STDERR, input_bytes=MAX_INPUT),
            planned_routes=list(planned_routes), routes={}, comparisons=[],
            provenance=dict(python_version=sys.version, python_executable=sys.executable,
                platform=sys.platform, os_name=os.name, windows_version=list(platform.win32_ver()),
                environment={name: os.environ[name] for name in (
                    'DOTNET_ROOT', 'DOTNET_ROLL_FORWARD', 'DOTNET_SYSTEM_GLOBALIZATION_USENLS',
                    'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'RUNNER_OS') if name in os.environ}))
        (self.directory / 'fixtures.json').write_bytes(encoded)
        self.save()
        print('Retained diagnostic evidence: ' + str(self.directory), flush=True)

    def save(self):
        # Replace only our own manifest inside a unique test-owned directory.
        temporary = self.directory / 'manifest.json.pending'
        temporary.write_text(json.dumps(self.manifest, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.directory / 'manifest.json')

    def provenance(self, **values):
        self.manifest['provenance'].update(values)
        self.save()

    def _raw(self, name, stream, value, limit):
        value = _bytes(value)
        path = self.directory / (name + '.' + stream)
        path.write_bytes(value[:limit])
        return dict(file=path.name, bytes=len(value), saved_bytes=min(len(value), limit),
                    sha256=hashlib.sha256(value).hexdigest(), truncated=len(value) > limit)

    def run(self, name, argv, *, case_ids=(), metadata=None, timeout, **kwargs):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name) or name in self.manifest['routes']:
            raise ValueError('Evidence route must have a unique fixed filename-safe name; retries are forbidden')
        record = dict(argv=[str(arg) if arg is not None else None for arg in argv],
            case_ids=list(case_ids), metadata=metadata or {}, timeout_seconds=timeout,
            status='launching', returncode=None, automatic_retry=False, validation='not_started')
        self.manifest['routes'][name] = record
        if kwargs.get('input') is not None:
            record['stdin'] = self._raw(name, 'stdin', kwargs['input'], MAX_INPUT)
            if record['stdin']['truncated']:
                record.update(status='input_limit_exceeded', validation='failed')
                self.save()
                raise AssertionError('Retained diagnostic stdin exceeded its evidence bound: ' + name)
        self.save()
        try:
            process = subprocess.run(argv, capture_output=True, timeout=timeout, **kwargs)
        except Exception as error:
            record['status'] = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else (
                'launch_error' if isinstance(error, (OSError, ValueError, TypeError)) else 'runner_error')
            record['error'] = _error(error)
            record['stdout'] = self._raw(name, 'stdout', getattr(error, 'stdout', None) or getattr(error, 'output', None), MAX_STDOUT)
            record['stderr'] = self._raw(name, 'stderr', getattr(error, 'stderr', None), MAX_STDERR)
            self.save()
            raise
        record.update(status='exited', returncode=process.returncode)
        record['stdout'] = self._raw(name, 'stdout', process.stdout, MAX_STDOUT)
        record['stderr'] = self._raw(name, 'stderr', process.stderr, MAX_STDERR)
        # Persist complete bounded bytes and status BEFORE any return-code,
        # decoding, shape, length or comparison assertion can fail.
        self.save()
        if record['stdout']['truncated'] or record['stderr']['truncated']:
            record.update(status='output_limit_exceeded', validation='failed')
            self.save()
            raise AssertionError('Retained diagnostic output exceeded its evidence bound: ' + name)
        return process

    def success(self, test, name, process):
        record = self.manifest['routes'][name]
        try:
            test.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
        except Exception as error:
            record.update(validation='failed', validation_error=_error(error))
            self.save()
            raise
        record['validation'] = 'returncode_passed'
        self.save()

    def rows(self, test, name, process, expected_count):
        record = self.manifest['routes'][name]
        try:
            self.success(test, name, process)
            rows = json.loads(process.stdout.decode('utf-8-sig'))
            test.assertIsInstance(rows, list)
            test.assertEqual(len(rows), expected_count)
        except Exception as error:
            record.update(validation='failed', validation_error=_error(error))
            self.save()
            raise
        record.update(validation='parsed', observed_count=len(rows))
        self.save()
        return rows

    @contextmanager
    def comparison(self, case_id, route):
        record = dict(case_id=case_id, route=route, status='running')
        self.manifest['comparisons'].append(record)
        try:
            yield
        except Exception as error:
            record.update(status='failed', error=_error(error))
            self.save()
            raise
        record['status'] = 'passed'
        # Raw routes are already durable. Flush passing comparisons together at
        # completion/cleanup rather than rewriting the growing manifest 1000x.

    def complete(self):
        self.manifest['comparison_completed'] = True
        self.save()

    def finish(self):
        self.manifest['finished'] = True
        self.manifest['unattempted_routes'] = [name for name in self.manifest['planned_routes']
                                              if name not in self.manifest['routes']]
        self.manifest['qualification_passed'] = (self.manifest['comparison_completed'] and
            not self.manifest['unattempted_routes'] and
            all(r['status'] == 'exited' and r['returncode'] == 0 and r['validation'] in ('parsed', 'returncode_passed')
                for r in self.manifest['routes'].values()) and
            all(c['status'] == 'passed' for c in self.manifest['comparisons']))
        self.save()
