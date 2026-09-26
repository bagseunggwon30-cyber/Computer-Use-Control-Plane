"""Bounded, cancellable transport to the explicitly published native host.

This module never builds a project, invokes a shell, retries input, or falls back
into the legacy implementation. Native stdout is exclusively a JSON protocol.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
from typing import Any

from .protocol import repo_root

MAX_STDOUT_BYTES = 32 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
_PROCESS_LOCK = threading.RLock()  # SIGINT/SIGTERM cleanup may re-enter on the owner thread.
_PROCESSES: set[subprocess.Popen[bytes]] = set()


def native_project_path() -> Path:
    """Retained for diagnostic callers; execution never uses the project."""
    return repo_root() / "pcucp-next" / "dotnet" / "PcuCp.NativeHost" / "PcuCp.NativeHost.csproj"


def _native_argv() -> tuple[list[str] | None, str]:
    configured = os.environ.get("CUCP_NATIVE_HOST")
    path = Path(configured) if configured else repo_root() / "pcucp-next" / "bin" / "native" / "PcuCp.NativeHost.exe"
    if not path.is_absolute():
        return None, "CUCP_NATIVE_HOST must be an absolute executable or DLL path"
    if not path.is_file():
        return None, f"published native host not found: {path}; publish it first or set CUCP_NATIVE_HOST"
    if path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        return None, "CUCP_NATIVE_HOST must be an executable or DLL, not a shell script"
    if path.suffix.lower() == ".dll":
        dotnet = shutil.which("dotnet")
        if not dotnet:
            return None, "dotnet executable not found on PATH for configured native host DLL"
        return [dotnet, str(path)], ""
    return [str(path)], ""


def native_host_available() -> bool:
    command, _ = _native_argv()
    return command is not None


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    # Children may still hold pipes after the immediate parent exits.
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False, timeout=3.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def cancel_all_native() -> None:
    """Cancel active native requests; cancellation never resubmits an action."""
    with _PROCESS_LOCK:
        processes = list(_PROCESSES)
    for process in processes:
        _terminate_process_tree(process)


def _capture(command: list[str], timeout_s: float) -> tuple[int, bytes, bytes, str]:
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **kwargs,
        )
    except (OSError, ValueError) as exc:
        return 2, b"", b"", f"native host launch failed: {exc}"
    with _PROCESS_LOCK:
        _PROCESSES.add(process)
    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()

    def read_pipe(pipe: Any, target: bytearray, cap: int) -> None:
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    return
                remaining = cap - len(target)
                target.extend(chunk[:max(0, remaining)])
                if len(chunk) > remaining:
                    overflow.set()
                    _terminate_process_tree(process)
                    return
        finally:
            pipe.close()

    readers = [
        threading.Thread(target=read_pipe, args=(process.stdout, stdout, MAX_STDOUT_BYTES), daemon=True),
        threading.Thread(target=read_pipe, args=(process.stderr, stderr, MAX_STDERR_BYTES), daemon=True),
    ]
    for reader in readers:
        reader.start()
    transport_error = ""
    code = 1
    try:
        try:
            code = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            transport_error = f"native host timed out after {timeout_s:g}s; process tree terminated; action not retried"
            _terminate_process_tree(process)
            code = 124
        except BaseException:
            _terminate_process_tree(process)
            raise
        # A host must not leave descendants holding its protocol streams open.
        for reader in readers:
            reader.join(timeout=0.25)
        if any(reader.is_alive() for reader in readers):
            _terminate_process_tree(process)
            for reader in readers:
                reader.join(timeout=0.5)
            if not transport_error:
                code = 1
                transport_error = "native host left protocol streams open; process tree terminated"
        if overflow.is_set():
            code = 1
            transport_error = "native host output exceeded transport size limit; process tree terminated"
    finally:
        with _PROCESS_LOCK:
            _PROCESSES.discard(process)
        if process.poll() is None:
            _terminate_process_tree(process)
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
    return code, bytes(stdout), bytes(stderr), transport_error


def _list_of_objects(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _validate_payload(command: str, payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "response must be a JSON object"
    schemas = {
        "windows": {"pcucp.observation/v1", "pcucp.native/v1"},
        "uia-tree": {"pcucp.uia-tree/v1", "pcucp.native/v1"},
        "ocr-image": {"pcucp.ocr-image/v1", "pcucp.native/v1"},
        "version": {"pcucp.native.version/v1", "pcucp.native/v1"},
    }
    if not isinstance(payload.get("schema"), str) or payload["schema"] not in schemas.get(command, {"pcucp.native/v1"}):
        return "unrecognized response schema for command"
    if not isinstance(payload.get("status"), str) or payload["status"] not in {"ok", "partial", "error", "not_found"}:
        return "response status must be ok, partial, error, or not_found"
    if command != "version" and payload.get("kind") != command:
        return "response kind does not match requested command"
    errors = payload.get("errors", [])
    if not isinstance(errors, list) or not all(
        isinstance(error, str) or (
            isinstance(error, dict) and isinstance(error.get("code"), str)
            and isinstance(error.get("message"), str)
        ) for error in errors
    ):
        return "response errors must be a list of strings or code/message objects"
    if "route" in payload and not isinstance(payload["route"], dict):
        return "response route must be an object"
    if command == "version" and payload["schema"] == "pcucp.native.version/v1":
        return None
    if payload["schema"] != "pcucp.ocr-image/v1" and not isinstance(payload.get("data"), dict):
        return "response data must be an object"
    if payload["status"] == "error":
        return None
    if command == "windows" and not _list_of_objects(payload["data"].get("windows")):
        return "windows data must contain a list of window objects"
    if command == "uia-tree":
        nodes = payload["data"].get("nodes")
        if not _list_of_objects(nodes):
            return "UIA data must contain a list of node objects"
        pending = list(nodes)
        count = 0
        while pending:
            node = pending.pop()
            count += 1
            if count > 10000:
                return "UIA response exceeds 10000-node limit"
            children = node.get("children", [])
            if not _list_of_objects(children):
                return "UIA node children must be a list of objects"
            pending.extend(children)
    if command == "ocr-image" and payload["schema"] == "pcucp.ocr-image/v1":
        if not _list_of_objects(payload.get("words")) or not _list_of_objects(payload.get("lines")):
            return "OCR words and lines must be lists of objects"
        words = list(payload["words"])
        for line in payload["lines"]:
            if not isinstance(line.get("text"), str) or not _list_of_objects(line.get("words")):
                return "OCR lines require text and word objects"
            words.extend(line["words"])
        for word in words:
            if not isinstance(word.get("text"), str):
                return "OCR word text must be a string"
            for key in ("x", "y", "width", "height", "cx", "cy"):
                value = word.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                    return f"OCR word {key} must be a finite number"
    return None


def run_native(command: str, args: list[str] | None = None, *, timeout_s: float = 15.0) -> tuple[int, dict[str, Any] | None, str]:
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or timeout_s <= 0:
        return 2, None, "native timeout must be a positive finite number"
    if not isinstance(command, str) or not command or "\0" in command:
        return 2, None, "native command must be a nonempty string without NUL characters"
    if args is not None and (not isinstance(args, list) or any(not isinstance(arg, str) or "\0" in arg for arg in args)):
        return 2, None, "native arguments must be a list of strings without NUL characters"
    argv, error = _native_argv()
    if argv is None:
        return 2, None, error
    code, stdout, stderr, error = _capture([*argv, command, *(args or [])], timeout_s)
    diagnostic = stderr.decode("utf-8", errors="replace").strip()
    if error:
        return code or 1, None, error + (f"; stderr: {diagnostic}" if diagnostic else "")
    try:
        payload = json.loads(stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        return code or 1, None, f"native host returned invalid JSON: {exc}" + (f"; stderr: {diagnostic}" if diagnostic else "")
    validation_error = _validate_payload(command, payload)
    if validation_error:
        return code or 1, None, f"native host protocol error: {validation_error}"
    payload.setdefault("route", {}).update({
        "primary": "dotnet-native-host", "fallback": None, "invoked_by": "python-router",
    })
    if code != 0 and payload["status"] == "ok":
        payload["status"] = "error"
        payload.setdefault("errors", []).append({
            "code": "native_exit_status_mismatch",
            "message": f"native host exited {code} despite reporting ok",
        })
    if code == 0 and payload["status"] != "ok":
        code = 3 if payload["status"] == "partial" else 1
    return code, payload, diagnostic


def emit_native_error(command: str, exit_code: int, error: str) -> int:
    print(json.dumps({
        "schema": "pcucp.native/v1", "status": "error", "kind": command,
        "data": {}, "route": {
            "primary": "dotnet-native-host", "fallback": None, "invoked_by": "python-router",
        }, "errors": [{"code": "native_transport_error", "message": error}],
    }, ensure_ascii=False, indent=2))
    return exit_code or 1
