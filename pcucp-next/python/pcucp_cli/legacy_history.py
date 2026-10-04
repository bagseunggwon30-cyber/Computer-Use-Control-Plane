"""The wrapper's owned smart-click history, including tie and rotation rules."""
import json
import os
from .legacy_cdp_contract import _ps_equal, ps_string
from .legacy_diagnostic_provider import owned_path, read_regular, timestamp
from .legacy_host import _read_lines


def _field(row, name):
    if type(row) is dict:
        return next((value for key, value in row.items() if _ps_equal(key, name)), None)
    return None


def _successful(value):
    # Preserve the left-operand conversion of the old `$r.success -eq $true`.
    if type(value) is str:
        return _ps_equal(value, 'True')
    if type(value) is list:
        return any(_successful(item) for item in value)
    return type(value) in (bool, int, float) and value == 1


def _records(path):
    path = owned_path(str(path))
    if not path.is_file():
        return []
    raw, _ = read_regular(path)
    rows = []
    for line in _read_lines(raw.decode('utf-8-sig', errors='replace')):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


class SmartClickHistory:
    def __init__(self, audit_directory, maximum=1000):
        self.directory = owned_path(str(audit_directory))
        self.path = owned_path(str(self.directory / 'smart-click-history.ndjson'))
        self.maximum = maximum

    def pick(self, label, match, lookback=5):
        candidates = [row for row in reversed(_records(self.path)) if
            _ps_equal(ps_string(_field(row, 'label')), label) and _ps_equal(ps_string(_field(row, 'match')), match)][:lookback]
        counts = []
        for row in candidates:
            strategy = ps_string(_field(row, 'strategy'))
            if _successful(_field(row, 'success')) and strategy:
                found = next((entry for entry in counts if _ps_equal(entry[0], strategy)), None)
                if found is None:
                    counts.append([strategy, 1])
                else:
                    found[1] += 1
        if not counts:
            return None
        highest = max(entry[1] for entry in counts)
        top = [entry[0] for entry in counts if entry[1] == highest]
        if len(top) == 1:
            return top[0]
        return next(ps_string(_field(row, 'strategy')) for row in candidates if _successful(_field(row, 'success')) and
            any(_ps_equal(ps_string(_field(row, 'strategy')), strategy) for strategy in top))

    def append(self, label, match, strategy, success, elapsed_ms):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = owned_path(str(self.path))
            row = dict(ts=timestamp(), label=label, match=match, strategy=strategy, success=success, elapsed_ms=elapsed_ms)
            raw = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\r\n').encode('utf-8')
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o600)
            with os.fdopen(descriptor, 'ab') as stream:
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b'\xef\xbb\xbf')
                stream.write(raw)
            if path.stat().st_size > 1024 * 1024:
                content, _ = read_regular(path)
                lines = _read_lines(content.decode('utf-8-sig', errors='replace'))
                if len(lines) > self.maximum:
                    keep = round(self.maximum * .8)
                    path.write_bytes(('\r\n'.join(lines[-keep:]) + '\r\n').encode('utf-8-sig'))
        except (OSError, ValueError, RuntimeError):
            pass

    def stats(self):
        rows, strategies, success = _records(self.path), {}, 0
        for row in rows:
            if _successful(_field(row, 'success')):
                success += 1
                key = ps_string(_field(row, 'strategy'))
                spelling = next((name for name in strategies if _ps_equal(name, key)), key)
                strategies[spelling] = strategies.get(spelling, 0) + 1
        return dict(total=len(rows), success=success, success_rate=round(success / len(rows) * 100, 1) if rows else 0.0, strategies=strategies)
