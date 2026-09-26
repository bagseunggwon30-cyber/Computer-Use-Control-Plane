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


def find_label(
    label: str, limit: int = 10, *, hwnd: str | None = None,
    pid: int | None = None, max_depth: int = 2, max_nodes: int = 500,
    timeout_s: float = 15.0,
) -> tuple[int, dict[str, Any]]:
    """Search bounded observations without disguising failed providers as no match."""
    if not isinstance(label, str) or not label.strip():
        return 2, {"schema": "pcucp.find-label/v1", "status": "error",
                   "query": {"label": label}, "candidates": [],
                   "errors": ["label must be a nonempty string"]}
    if not 1 <= limit <= 100 or not 0 <= max_depth <= 8 or not 1 <= max_nodes <= 10000:
        return 2, {"schema": "pcucp.find-label/v1", "status": "error",
                   "query": {"label": label}, "candidates": [],
                   "errors": ["limit, max_depth, or max_nodes is outside its bounded range"]}
    native_args = ["--max-depth", str(max_depth), "--max-nodes", str(max_nodes)]
    if hwnd is not None:
        native_args += ["--hwnd", str(hwnd)]
    if pid is not None:
        native_args += ["--pid", str(pid)]
    window_code, window_observation, window_error = run_native("windows", timeout_s=timeout_s)
    uia_code, uia_observation, uia_error = run_native("uia-tree", native_args, timeout_s=timeout_s)
    raw_providers = [
        ("windows", window_code, window_observation, window_error),
        ("uia-tree", uia_code, uia_observation, uia_error),
    ]
    providers: list[dict[str, Any]] = []
    errors: list[Any] = []
    usable: dict[str, dict[str, Any]] = {}
    incomplete = False
    for name, code, observation, transport_error in raw_providers:
        status = observation.get("status", "error") if observation else "error"
        provider_errors = list(observation.get("errors", [])) if observation else []
        if transport_error:
            provider_errors.append({"code": "provider_transport_error", "message": transport_error})
        complete = observation is not None and status == "ok" and code == 0
        incomplete |= not complete
        if not complete and not provider_errors:
            provider_errors.append({"code": "provider_incomplete", "message": f"{name}: status={status}, exit_code={code}"})
        providers.append({"provider": name, "status": status, "exit_code": code, "errors": provider_errors})
        errors.extend({"provider": name, "detail": error} for error in provider_errors)
        if observation is not None and status in {"ok", "partial"} and (code == 0 or status == "partial"):
            usable[name] = observation.get("data", {})

    windows = usable.get("windows", {}).get("windows", [])
    if hwnd is not None:
        def same_handle(value: Any) -> bool:
            try:
                return int(str(value), 16) == int(str(hwnd), 16)
            except (ValueError, TypeError):
                return str(value).casefold() == str(hwnd).casefold()
        windows = [window for window in windows if same_handle(window.get("hwnd", window.get("Hwnd")))]
    if pid is not None:
        windows = [window for window in windows if window.get("process_id", window.get("ProcessId")) == pid]
    uia_nodes = _walk_uia(usable.get("uia-tree", {}).get("nodes", []))
    candidates: list[dict[str, Any]] = []
    for window in windows:
        score = _score_window(label, window)
        if score <= 0:
            continue
        candidates.append({
            "kind": "window", "score": score,
            "label": window.get("title", window.get("Title", "")),
            "title": window.get("title", window.get("Title", "")),
            "process": window.get("process_name", window.get("ProcessName", "")),
            "pid": window.get("process_id", window.get("ProcessId")),
            "hwnd": window.get("hwnd", window.get("Hwnd")),
            "source": "dotnet-native-host/windows",
        })
    for node in uia_nodes:
        score = _score_uia_node(label, node)
        if score <= 0:
            continue
        candidates.append({
            "kind": "uia", "score": score, "label": node.get("name", ""),
            "name": node.get("name", ""), "control_type": node.get("control_type", ""),
            "automation_id": node.get("automation_id", ""), "class_name": node.get("class_name", ""),
            "pid": node.get("process_id"), "hwnd": node.get("native_window_handle"),
            "bounding_rectangle": node.get("bounding_rectangle"), "patterns": node.get("patterns", []),
            "source": "dotnet-native-host/uia-tree",
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not usable:
        status, code = "error", next((c for _, c, _, _ in raw_providers if c != 0), 1)
    elif incomplete:
        status, code = "partial", 3
    elif candidates:
        status, code = "ok", 0
    else:
        status, code = "not_found", 2
        errors.append("no matching window title, process name, or UIA node found")
    return code, {
        "schema": "pcucp.find-label/v1", "status": status,
        "query": {"label": label, "hwnd": hwnd, "pid": pid},
        "route": {"primary": "python-router", "observations": [
            "dotnet-native-host/windows", "dotnet-native-host/uia-tree"], "fallback": None},
        "candidates": candidates[:limit], "providers": providers,
        "observation_count": len(windows), "uia_node_count": len(uia_nodes), "errors": errors,
    }
