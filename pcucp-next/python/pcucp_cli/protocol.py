from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__


LANGUAGE_TARGETS: dict[str, str] = {
    "powershell": "15-25%",
    "python": "35-45%",
    "dotnet": "20-30%",
    "config_db": "5-10%",
    "rust_cpp_optional": "0-10%",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def next_root() -> Path:
    return repo_root() / "pcucp-next"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def component_paths() -> dict[str, str]:
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
        "surface": "python-router+dotnet-native-host+legacy-powershell",
        "language_targets": LANGUAGE_TARGETS,
        "components": component_paths(),
    }


def emit(payload: dict[str, Any], as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"{payload.get('status', 'ok')} {payload.get('schema', 'pcucp')}")
