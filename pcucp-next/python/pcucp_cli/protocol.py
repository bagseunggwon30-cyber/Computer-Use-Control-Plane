from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__


LANGUAGE_ROLES: dict[str, str] = {
    "python": "session, protocol, orchestration, diagnostics, packaging",
    "dotnet": "Windows capture, UIA, OCR, input, privilege diagnostics",
    "typescript": "optional Pi host adapter",
    "powershell": "source-only legacy compatibility and optional developer launchers",
}


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    # Frozen assets belong to this executable, never to the working directory or
    # a stale development CUCP_ROOT inherited from an unrelated host session.
    if frozen():
        return Path(sys.executable).resolve().parent
    configured = os.environ.get("CUCP_ROOT")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[3]


def next_root() -> Path:
    return repo_root() / "pcucp-next"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def component_paths() -> dict[str, str]:
    if frozen():
        return {"engine": str(Path(sys.executable).resolve()),
                "native_host": str(repo_root() / "native" / "PcuCp.NativeHost.exe"),
                "pi_adapter": str(repo_root() / "integrations" / "pi"),
                "legacy_wrapper": "not included"}
    root = repo_root()
    nxt = next_root()
    return {
        "python_cli": rel(nxt / "python" / "pcucp_cli"),
        "native_host_project": rel(nxt / "dotnet" / "PcuCp.NativeHost" / "PcuCp.NativeHost.csproj"),
        "thin_launcher": rel(nxt / "powershell" / "cucp-next.ps1"),
        "legacy_wrapper": rel(root / "scripts" / "cucp.ps1"),
        "runtime_profile": rel(nxt / "config" / "runtime-profile.json"),
    }


def version_payload() -> dict[str, Any]:
    return {
        "schema": "pcucp.version/v1",
        "status": "ok",
        "version": __version__,
        "surface": "python-core+dotnet-native-host",
        "distribution": "portable" if frozen() else "source",
        "language_roles": LANGUAGE_ROLES,
        "components": component_paths(),
    }


def emit(payload: dict[str, Any], as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"{payload.get('status', 'ok')} {payload.get('schema', 'pcucp')}")
