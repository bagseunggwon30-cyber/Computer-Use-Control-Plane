from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_ONLY_NATIVE = {
    "windows",
    "uia-tree",
    "screenshot",
    "ocr-find-text",
    "find-label",
}

READ_ONLY_PYTHON = {
    "version",
    "plan",
    "task-plan",
    "diagnose",
}

LIVE_ACTIONS = {
    "click-label",
    "smart-click",
    "fill-label",
    "shortcut",
    "safe-type",
    "cdp-smart-click",
    "task-run",
}


@dataclass(frozen=True)
class Route:
    primary: str
    fallback: str
    rationale: str


def normalize_command(command: str) -> str:
    return command.strip().lower().replace("_", "-")


def plan_command(command: str, args: list[str] | None = None) -> dict[str, Any]:
    normalized = normalize_command(command)
    args = args or []

    live_required = normalized in LIVE_ACTIONS
    if normalized in READ_ONLY_NATIVE:
        route = Route(
            primary="dotnet-native-host",
            fallback="legacy-powershell",
            rationale="read-only Windows observation should move to the native host first",
        )
    elif normalized in READ_ONLY_PYTHON:
        route = Route(
            primary="python-router",
            fallback="legacy-powershell",
            rationale="planning and diagnostics belong in Python before execution",
        )
    elif live_required:
        route = Route(
            primary="legacy-powershell",
            fallback="blocked-unless-explicitly-allowed",
            rationale="live commands stay on the existing safety wrapper until native parity is verified",
        )
    else:
        route = Route(
            primary="legacy-powershell",
            fallback="manual-review",
            rationale="unknown command remains on the compatibility path",
        )

    return {
        "schema": "pcucp.plan/v1",
        "status": "ok",
        "command": normalized,
        "args": args,
        "route": {
            "primary": route.primary,
            "fallback": route.fallback,
            "rationale": route.rationale,
        },
        "safety": {
            "live_control_required": live_required,
            "confirm_sensitive_required": live_required,
            "default_allow_live_control": False,
        },
    }
