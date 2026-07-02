from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

from .protocol import repo_root


def native_project_path():
    return repo_root() / "pcucp-next" / "dotnet" / "PcuCp.NativeHost" / "PcuCp.NativeHost.csproj"


def native_host_available() -> bool:
    return shutil.which("dotnet") is not None and native_project_path().exists()


def run_native(command: str, args: list[str] | None = None) -> tuple[int, dict[str, Any] | None, str]:
    args = args or []
    dotnet = shutil.which("dotnet")
    project = native_project_path()
    if not dotnet:
        return 2, None, "dotnet executable not found on PATH"
    if not project.exists():
        return 2, None, f"native host project not found: {project}"

    completed = subprocess.run(
        [
            dotnet,
            "run",
            "--project",
            str(project),
            "--",
            command,
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        return int(completed.returncode), None, stderr or completed.stdout.strip()

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return 1, None, f"native host returned invalid JSON: {exc}"

    payload.setdefault("route", {})
    payload["route"].update(
        {
            "primary": "dotnet-native-host",
            "fallback": "legacy-powershell",
            "invoked_by": "python-router",
        }
    )
    return 0, payload, stderr


def emit_native_error(command: str, exit_code: int, error: str) -> int:
    print(
        json.dumps(
            {
                "schema": "pcucp.observation/v1",
                "status": "error",
                "kind": command,
                "data": {},
                "route": {
                    "primary": "dotnet-native-host",
                    "fallback": "legacy-powershell",
                    "invoked_by": "python-router",
                },
                "errors": [error],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code
