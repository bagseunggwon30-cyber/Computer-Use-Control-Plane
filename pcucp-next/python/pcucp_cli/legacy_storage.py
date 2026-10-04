"""Owned UTF-8 trajectory storage shared by the preserved Python entry."""
import json
import os
from pathlib import Path
from .legacy_diagnostic_provider import owned_path, read_regular, timestamp
from .legacy_host import _read_lines


def append_trajectory(directory, kind, payload):
    # Audit remains best effort, as in the wrapper. A changed reparse path is
    # rejected by owned_path before any write and cannot redirect the audit.
    try:
        root = owned_path(str(directory))
        root.mkdir(parents=True, exist_ok=True)
        path = owned_path(str(root / 'trajectory.ndjson'))
        entry = {'ts': timestamp(), 'kind': kind, **payload}
        raw = (json.dumps(entry, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\r\n').encode('utf-8')
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o600)
        with os.fdopen(descriptor, 'ab') as stream:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'\xef\xbb\xbf')
            stream.write(raw)
        if path.stat().st_size > 1024 * 1024:
            content, _ = read_regular(path)
            lines = _read_lines(content.decode('utf-8-sig', errors='replace'))
            if len(lines) > 200:
                path.write_bytes(('\r\n'.join(lines[-200:]) + '\r\n').encode('utf-8-sig'))
    except (OSError, ValueError, RuntimeError):
        pass
