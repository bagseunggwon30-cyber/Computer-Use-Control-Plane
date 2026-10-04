"""Closed precision acquisition with pure captured replay and terminal writes.

Only calculations are replayed. Each acquisition is appended once. Complete
reports and persistence bytes are serialized before the single terminal write;
no facade evaluation, input or retry follows that boundary.
"""
import json
import re
import time
from .legacy_cdp_contract import _ps_equal, ps_string
from .legacy_diagnostic_provider import option, owned_path, read_regular, timestamp
from .legacy_host import _read_lines
from .legacy_host_protocol import exact, require
from .legacy_native_kernel import precision
from .legacy_values import int32


def project(value, maximum, depth=0):
    if type(value) not in (dict, list):
        return value
    if depth > maximum:
        return ps_string(value)
    if type(value) is list:
        return [project(item, maximum, depth + 1) for item in value]
    return {key: project(item, maximum, depth + 1) for key, item in value.items()}


class PrecisionStorage:
    def __init__(self, audit_directory, cache_directory):
        self.history = owned_path(str(owned_path(str(audit_directory)) / 'coord-anchor-history.ndjson'))
        self.cache = owned_path(str(cache_directory))

    def path(self, key):
        require(type(key) is str and re.fullmatch(r'[a-f0-9]{32}', key), 'Invalid owned precision cache key.')
        return owned_path(str(self.cache / ('point-plan-' + key + '.json')))

    def lines(self):
        try:
            raw, _ = read_regular(self.history)
            return _read_lines(raw.decode('utf-8-sig', errors='replace'))
        except OSError:
            return []

    def read(self, key, maximum_age):
        if not key or maximum_age <= 0:
            return None
        path = self.path(key)
        try:
            age = time.time() - path.stat().st_mtime
            if age > maximum_age:
                return None
            raw, _ = read_regular(path)
            return dict(Json=json.loads(raw.decode('utf-8-sig')), Path=str(path), AgeMs=round(age * 1000))
        except (OSError, ValueError, OverflowError):
            return None

    def write(self, key, serialized):
        path = self.path(key)
        try:
            path.write_bytes((serialized + '\r\n').encode('utf-8-sig'))
        except OSError:
            pass

    def append(self, serialized, maximum=500):
        try:
            self.history.parent.mkdir(parents=True, exist_ok=True)
            path = owned_path(str(self.history))
            # Preserve the old silently suppressed append error/true outcome.
            try:
                import os
                descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o600)
                with os.fdopen(descriptor, 'ab') as stream:
                    if os.fstat(stream.fileno()).st_size == 0:
                        stream.write(b'\xef\xbb\xbf')
                    stream.write((serialized + '\r\n').encode('utf-8'))
            except OSError:
                pass
            rows = self.lines()
            maximum = maximum if maximum > 0 else 500
            if len(rows) > maximum:
                keep = max(50, round(maximum * .8))
                indices = [index if index >= 0 else len(rows) + index for index in range(len(rows) - keep, len(rows))]
                tail = [rows[index] for index in indices if 0 <= index < len(rows)]
                path.write_bytes(('\r\n'.join(tail) + '\r\n').encode('utf-8-sig'))
            return True
        except (OSError, ValueError, RuntimeError):
            return False


class PrecisionRuntime:
    def __init__(self, coordinates, native, *, audit_directory, cache_directory, remaining=lambda: 30, cancelled=None,
                 culture='en-US', cache_seconds=2, child=None, on_persistence=None):
        self.coordinates, self.native, self.child = coordinates, native, child
        self.remaining, self.cancelled, self.culture, self.cache_seconds = remaining, cancelled, culture, cache_seconds
        self.storage = PrecisionStorage(audit_directory, cache_directory)
        self.on_persistence = on_persistence
        self.reads, self.precheck, self.profile, self.cache_key = 0, None, None, None

    def kernel(self, operation, args):
        self.remaining()
        return precision(operation, args, culture=self.culture, timeout_s=self.remaining(), cancelled=self.cancelled)

    def utility(self, operation, args):
        result = self.kernel(operation, args)
        require(result.get('state') == 'complete' and result.get('effects') == [] and result.get('queries') == [], 'Invalid pure precision helper.')
        return result['payload']

    def _read(self, operation, descriptor, rest):
        exact(descriptor, ('kind', 'args'))
        kind, args = descriptor['kind'], descriptor['args']
        require(type(kind) is str and type(args) is dict, 'Invalid precision acquisition descriptor.')
        x, y = int32(option(rest, '--x')), int32(option(rest, '--y'))
        match = option(rest, '--target-match') or option(rest, '--match') or option(rest, '--window') or ''
        # Hwnd is parsed by the qualified kernel. It remains a bounded integer
        # read selector here and cannot name an executable or persistence path.
        hwnd = args.get('target_hwnd', 0)
        if kind in {'coord-map', 'hit-test', 'coord-profile'}:
            fields = ('x', 'y', 'target_hwnd', 'target_match') + (('from', 'norm_x', 'norm_y', 'has_norm') if kind == 'coord-map' else
                ('has_point',) if kind == 'coord-profile' else ())
            exact(args, fields)
            require(args['x'] == x and args['y'] == y and type(hwnd) is int and -(2**63) <= hwnd < 2**63 and args['target_match'] == match,
                'Precision read changed its original target.')
            if kind == 'coord-map':
                require(operation == 'coord-anchor' and self.reads == 0 and args['from'] == 'screen' and args['has_norm'] is False and
                    args['norm_x'] == args['norm_y'] == 0, 'Invalid coordinate mapping order.')
                return self.coordinates.map(x=x, y=y, target_hwnd=hwnd, target_match=match)
            if kind == 'hit-test':
                require(operation == 'point-plan' and self.reads == 0, 'Invalid point precheck order.')
                self.precheck = self.coordinates.hit(x, y, hwnd, match)
                return self.precheck
            require(operation == 'point-plan' and self.reads == 1 and args['has_point'] is True, 'Invalid coordinate profile order.')
            self.profile = self.coordinates.profile(has_point=True, x=x, y=y, target_hwnd=hwnd, target_match=match)
            return self.profile
        if kind == 'history-lines':
            exact(args, ('path',))
            require(operation == 'coord-anchor' and self.reads == 1 and args['path'] == str(self.storage.history) and
                not any(_ps_equal(word, '--no-history') for word in rest), 'Invalid anchor history path/order.')
            return self.storage.lines()
        radius = min(64, max(0, int32(option(rest, '--radius', '6'))))
        step = int32(option(rest, '--step', '2')); step = min(16, step if step > 0 else 2)
        inset = int32(option(rest, '--click-inset')); inset = inset if inset > 0 else 2
        ttl = max(0, int32(option(rest, '--cache-ttl', str(self.cache_seconds))))
        no_cache = any(_ps_equal(word, '--no-cache') for word in rest)
        if no_cache: ttl = 0
        if kind == 'point-plan-child':
            exact(args, ('argv',))
            require(operation == 'target-validate' and self.reads == 0 and self.child is not None, 'Invalid child point planning order.')
            argv = args['argv']
            require(type(argv) is list and all(type(word) is str for word in argv) and argv[:12] ==
                ['--x', str(x), '--y', str(y), '--radius', str(radius), '--step', str(step), '--click-inset', str(inset), '--cache-ttl', str(ttl)],
                'Child planner changed its original numeric options.')
            return self.child(argv)
        require(operation == 'point-plan' and self.reads in (2, 3) and self.precheck is not None and
            (not match and self.precheck['target_hwnd'] <= 0 or self.precheck['matched']), 'Point target guard forbids this acquisition.')
        if kind == 'cache-read':
            exact(args, ('directory', 'key', 'max_age_seconds'))
            require(self.reads == 2 and args['directory'] == str(self.storage.cache) and args['max_age_seconds'] == ttl, 'Invalid point cache selector.')
            key = self.utility('cache-key', dict(x=x, y=y, radius=radius, step=step, click_inset=inset,
                target_hwnd=self.precheck['target_hwnd'], target_match=match, precheck=self.precheck, coord_signature=self.profile['coord_signature']))
            require(args['key'] == key, 'Point cache key changed from acquired target evidence.')
            self.cache_key = key
            return self.storage.read(key, ttl)
        require(kind == 'hit-scan', 'Unknown precision acquisition kind.')
        exact(args, ('argv',))
        expected = ['-Action', 'hit-scan', '-X', str(x), '-Y', str(y), '-ClickInset', str(inset), '-ScanRadius', str(radius), '-ScanStep', str(step)]
        if match: expected += ['-TargetMatch', match]
        target = self.precheck['target_hwnd']
        if target > 0: expected += ['-TargetHwnd', str(target)]
        require(args['argv'] == expected, 'Precision scan changed its original read-only argv.')
        return self.native(expected)

    def run(self, operation, rest, *, brief=False):
        require(operation in {'coord-anchor', 'point-plan', 'target-validate'}, 'Unknown precision planner.')
        started = time.monotonic()
        args = dict(rest=rest, cache_seconds=self.cache_seconds, brief=brief, elapsed_ms=0, now=timestamp(),
            history_file=str(self.storage.history), history_max=500, cache_dir=str(self.storage.cache), captured_replies=[])
        acquired = []
        for index in range(9):
            result = self.kernel(operation, args)
            require(result.get('state') != 'error', result.get('error', 'Precision calculation failed.'))
            if result['state'] == 'complete':
                require(result.get('queries') == [dict(kind=row['kind'], args=row['args']) for row in acquired], 'Precision completion trace changed.')
                return self._complete(operation, rest, result)
            require(index < 8 and result['state'] == 'query' and type(result.get('queries')) is list and
                result['queries'] == [dict(kind=row['kind'], args=row['args']) for row in acquired] + [result.get('query')],
                'Precision acquisition trace or eight-read budget changed.')
            descriptor = result['query']
            row = dict(descriptor)
            try:
                row['result'] = self._read(operation, descriptor, rest)
            except OSError as error:
                row['error'] = str(error)
            self.reads += 1; acquired.append(row)
            args.update(captured_replies=acquired, elapsed_ms=round((time.monotonic() - started) * 1000))
        require(False, 'Precision planner exceeded its original read budget.')

    def _complete(self, operation, rest, result):
        exact(result, ('state', 'payload', 'exit', 'brief', 'json_depth', 'queries', 'effects'))
        require(type(result['payload']) is dict and result['exit'] in {0, 1, 2} and type(result['effects']) is list and
            len(result['effects']) <= 1, 'Invalid complete precision report.')
        effects = result['effects']
        output = dict(payload=result['payload'], exit=result['exit'], brief=result['brief'], json_depth=result['json_depth'],
            emit_json=result['brief'] is None)
        if not effects:
            return output
        effect = effects[0]
        exact(effect, ('kind', 'args', 'bind'))
        if effect['kind'] == 'history-append':
            exact(effect['args'], ('path', 'record', 'max'))
            require(operation == 'coord-anchor' and any(_ps_equal(word, '--record-history') or _ps_equal(word, '--learn-history') for word in rest) and
                not any(_ps_equal(word, '--no-history') for word in rest) and effect['args']['path'] == str(self.storage.history) and
                effect['args']['max'] == 500 and effect['bind'] == 'reuse_history.recorded', 'Unapproved terminal anchor write.')
            serialized = json.dumps(project(effect['args']['record'], 10), ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            # Validate and preflight both possible reports before persistence.
            rendered = {}
            for recorded in (False, True):
                output['payload']['reuse_history']['recorded'] = recorded
                rendered[recorded] = (output['brief'] if output['brief'] is not None else
                    json.dumps(project(output['payload'], output['json_depth']), ensure_ascii=False, allow_nan=False, indent=2)) + '\n'
            self.remaining()
            if self.on_persistence: self.on_persistence()
            recorded = self.storage.append(serialized)
            output['payload']['reuse_history']['recorded'] = recorded
            output['raw'] = rendered[recorded]
        else:
            exact(effect['args'], ('directory', 'key'))
            require(effect['kind'] == 'cache-write' and operation == 'point-plan' and effect['args']['directory'] == str(self.storage.cache) and
                effect['args']['key'] == output['payload']['cache_key'] and effect['bind'] == 'payload' and
                output['payload']['cache_ttl_seconds'] > 0, 'Unapproved terminal point cache write.')
            serialized = json.dumps(project(output['payload'], 14), ensure_ascii=False, allow_nan=False, indent=2)
            output['raw'] = (output['brief'] if output['brief'] is not None else
                json.dumps(project(output['payload'], output['json_depth']), ensure_ascii=False, allow_nan=False, indent=2)) + '\n'
            self.remaining()
            if self.on_persistence: self.on_persistence()
            self.storage.write(effect['args']['key'], serialized)
        return output
