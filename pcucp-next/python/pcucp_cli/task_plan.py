from __future__ import annotations

from typing import Any


def _field_step(spec: str) -> dict[str, Any]:
    if "=" not in spec:
        return {
            "kind": "field",
            "mode": "live",
            "status": "invalid",
            "raw": spec,
            "error": "field must be Label=Value",
        }
    label, value = spec.split("=", 1)
    return {
        "kind": "field",
        "mode": "live",
        "label": label.strip(),
        "value": value,
        "requires_live_control": True,
    }


def create_task_plan(
    *,
    app: str | None = None,
    wait_title: str | None = None,
    fields: list[str] | None = None,
    type_text: str | None = None,
    shortcuts: list[str] | None = None,
    click_label: str | None = None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    errors: list[str] = []

    if app:
        steps.append(
            {
                "kind": "app-launch",
                "mode": "read-only-plan",
                "app": app,
                "requires_live_control": False,
            }
        )
    if wait_title:
        steps.append(
            {
                "kind": "wait-window",
                "mode": "read-only",
                "title": wait_title,
                "requires_live_control": False,
            }
        )
    for spec in fields or []:
        step = _field_step(spec)
        if step.get("status") == "invalid":
            errors.append(str(step["error"]))
        steps.append(step)
    if type_text is not None:
        steps.append(
            {
                "kind": "type-text",
                "mode": "live",
                "text": type_text,
                "requires_live_control": True,
            }
        )
    for shortcut in shortcuts or []:
        steps.append(
            {
                "kind": "shortcut",
                "mode": "live",
                "keys": shortcut,
                "requires_live_control": True,
            }
        )
    if click_label:
        steps.append(
            {
                "kind": "click-label",
                "mode": "live",
                "label": click_label,
                "requires_live_control": True,
            }
        )

    live_required = any(bool(step.get("requires_live_control")) for step in steps)
    return {
        "schema": "pcucp.task-plan/v1",
        "status": "ok" if not errors else "partial",
        "route": {
            "primary": "python-router",
            "fallback": "legacy-powershell",
        },
        "safety": {
            "live_control_required": live_required,
            "confirm_sensitive_required": live_required,
            "default_allow_live_control": False,
        },
        "steps": steps,
        "step_count": len(steps),
        "live_step_count": sum(1 for step in steps if step.get("requires_live_control")),
        "errors": errors,
    }
