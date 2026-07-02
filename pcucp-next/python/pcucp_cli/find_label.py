from __future__ import annotations

from typing import Any

from .native_host import run_native


def _score_window(label: str, window: dict[str, Any]) -> int:
    needle = label.casefold()
    title = str(window.get("title", window.get("Title", ""))).casefold()
    process = str(window.get("process_name", window.get("ProcessName", ""))).casefold()
    if not needle:
        return 0
    if title == needle:
        return 100
    if needle in title:
        return 85
    if process == needle:
        return 70
    if needle in process:
        return 60
    return 0


def find_label(label: str, limit: int = 10) -> tuple[int, dict[str, Any]]:
    code, observation, error = run_native("windows")
    if observation is None:
        return code, {
            "schema": "pcucp.find-label/v1",
            "status": "error",
            "query": {"label": label},
            "route": {
                "primary": "python-router",
                "observation": "dotnet-native-host",
                "fallback": "legacy-powershell",
            },
            "candidates": [],
            "errors": [error],
        }

    windows = observation.get("data", {}).get("windows", [])
    candidates: list[dict[str, Any]] = []
    for window in windows:
        score = _score_window(label, window)
        if score <= 0:
            continue
        candidates.append(
            {
                "kind": "window",
                "score": score,
                "label": window.get("title", window.get("Title", "")),
                "title": window.get("title", window.get("Title", "")),
                "process": window.get("process_name", window.get("ProcessName", "")),
                "pid": window.get("process_id", window.get("ProcessId")),
                "hwnd": window.get("hwnd", window.get("Hwnd")),
                "source": "dotnet-native-host/windows",
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    status = "ok" if candidates else "not_found"
    return (0 if candidates else 2), {
        "schema": "pcucp.find-label/v1",
        "status": status,
        "query": {"label": label},
        "route": {
            "primary": "python-router",
            "observation": "dotnet-native-host",
            "fallback": "legacy-powershell",
        },
        "candidates": candidates[: max(1, limit)],
        "observation_count": observation.get("data", {}).get("count", 0),
        "errors": [] if candidates else ["no matching window title or process name found"],
    }
