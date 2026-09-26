from __future__ import annotations
from typing import Any
from .registry import COMMANDS, normalize_command


def plan_command(command: str, args: list[str] | None = None) -> dict[str, Any]:
    normalized = normalize_command(command)
    spec = COMMANDS.get(normalized)
    live = spec is None or spec.effect != 'read'
    return {
        'schema': 'pcucp.plan/v1', 'status': 'ok' if spec else 'blocked',
        'command': normalized, 'args': args or [],
        'route': {'primary': spec.route if spec else 'blocked', 'fallback': 'none',
                  'rationale': 'registered command' if spec else 'unknown command must be registered before execution'},
        'safety': {'live_control_required': live, 'confirm_sensitive_required': live,
                   'default_allow_live_control': False},
        'errors': [] if spec else ['unknown_command'],
    }
