from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from .native_host import _terminate_process_tree
from .protocol import repo_root


def legacy_wrapper_path() -> Path:
    return repo_root() / "scripts" / "cucp.ps1"


def run_legacy(args: list[str], *, timeout_s: float = 60.0) -> int:
    """Explicit compatibility route only; no shell construction or automatic retry."""
    import os
    wrapper = legacy_wrapper_path()
    if not wrapper.exists():
        print(f"legacy wrapper not found: {wrapper}", file=sys.stderr)
        return 2
    if not isinstance(timeout_s, (float, int)) or isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or timeout_s <= 0:
        print("legacy timeout must be positive and finite", file=sys.stderr)
        return 2
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(wrapper), *args]
    options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, **options)
    except (OSError, ValueError) as exc:
        print(f"legacy wrapper launch failed: {exc}", file=sys.stderr)
        return 2
    try:
        return int(process.wait(timeout=timeout_s))
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        print(f"legacy wrapper timed out after {timeout_s:g}s; action not retried", file=sys.stderr)
        return 124
    except BaseException:
        _terminate_process_tree(process)
        raise
    finally:
        if process.poll() is None:
            _terminate_process_tree(process)
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
