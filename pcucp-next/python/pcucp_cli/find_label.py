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


def _score_uia_node(label: str, node: dict[str, Any]) -> int:
    needle = label.casefold()
    name = str(node.get("name", "")).casefold()
    automation_id = str(node.get("automation_id", "")).casefold()
    control_type = str(node.get("control_type", "")).casefold()
    class_name = str(node.get("class_name", "")).casefold()
    if not needle:
        return 0
    if name == needle:
        return 98
    if needle in name:
        return 82
    if automation_id == needle:
        return 78
    if needle in automation_id:
        return 68
    if needle in control_type:
        return 45
    if needle in class_name:
        return 40
    return 0


def _walk_uia(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    stack = list(nodes)
    while stack:
        node = stack.pop(0)
        flattened.append(node)
        children = node.get("children", [])
        if isinstance(children, list):
            stack[0:0] = [child for child in children if isinstance(child, dict)]
    return flattened


def find_label(label: str, limit: int = 10) -> tuple[int, dict[str, Any]]:
    window_code, window_observation, window_error = run_native("windows")
    uia_code, uia_observation, uia_error = run_native("uia-tree", ["--max-depth", "1"])
    observations = ["dotnet-native-host/windows", "dotnet-native-host/uia-tree"]

    if window_observation is None and uia_observation is None:
        return max(window_code, uia_code), {
            "schema": "pcucp.find-label/v1",
            "status": "error",
            "query": {"label": label},
            "route": {
                "primary": "python-router",
                "observations": observations,
                "fallback": "legacy-powershell",
            },
            "candidates": [],
            "errors": [error for error in (window_error, uia_error) if error],
        }

    windows = []
    if window_observation is not None:
        windows = window_observation.get("data", {}).get("windows", [])
    uia_nodes: list[dict[str, Any]] = []
    if uia_observation is not None:
        uia_nodes = _walk_uia(uia_observation.get("data", {}).get("nodes", []))

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

    for node in uia_nodes:
        score = _score_uia_node(label, node)
        if score <= 0:
            continue
        candidates.append(
            {
                "kind": "uia",
                "score": score,
                "label": node.get("name", ""),
                "name": node.get("name", ""),
                "control_type": node.get("control_type", ""),
                "automation_id": node.get("automation_id", ""),
                "class_name": node.get("class_name", ""),
                "pid": node.get("process_id"),
                "hwnd": node.get("native_window_handle"),
                "bounding_rectangle": node.get("bounding_rectangle"),
                "patterns": node.get("patterns", []),
                "source": "dotnet-native-host/uia-tree",
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    status = "ok" if candidates else "not_found"
    errors = []
    if window_observation is None and window_error:
        errors.append(window_error)
    if uia_observation is None and uia_error:
        errors.append(uia_error)
    if not candidates:
        errors.append("no matching window title, process name, or UIA node found")
    return (0 if candidates else 2), {
        "schema": "pcucp.find-label/v1",
        "status": status,
        "query": {"label": label},
        "route": {
            "primary": "python-router",
            "observations": observations,
            "fallback": "legacy-powershell",
        },
        "candidates": candidates[: max(1, limit)],
        "observation_count": window_observation.get("data", {}).get("count", 0) if window_observation else 0,
        "uia_node_count": len(uia_nodes),
        "errors": errors,
    }
