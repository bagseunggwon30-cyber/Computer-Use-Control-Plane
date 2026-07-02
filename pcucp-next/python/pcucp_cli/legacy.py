from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .protocol import repo_root


def legacy_wrapper_path() -> Path:
    return repo_root() / "scripts" / "cucp.ps1"


def run_legacy(args: list[str]) -> int:
    wrapper = legacy_wrapper_path()
    if not wrapper.exists():
        print(f"legacy wrapper not found: {wrapper}", file=sys.stderr)
        return 2
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(wrapper),
        *args,
    ]
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)
