from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .find_label import find_label
from .native_host import emit_native_error, run_native
from .ocr import ocr_find_text
from .planner import plan_command
from .protocol import emit, version_payload
from .task_plan import create_task_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cucp")
    sub = parser.add_subparsers(dest="verb")

    server = sub.add_parser("serve", help="serve local JSONL computer-use requests")
    server.add_argument("--allow-live-control", action="store_true", help="operator opt-in for this process")
    mcp = sub.add_parser("mcp", help="provider-neutral MCP server over local stdio")
    mcp.add_argument("--allow-live-control", action="store_true", help="human operator opt-in for this process")
    for transport in (server, mcp):
        transport.add_argument("--cdp-endpoint", help="human-approved existing numeric-loopback HTTP debug endpoint; never auto-enabled")
    caps = sub.add_parser("capabilities", help="show engine tool contract")
    caps.add_argument("--json", action="store_true")
    privileges = sub.add_parser("privileges", help="diagnose Windows input privilege boundaries")
    privileges.add_argument("--pid", type=int)
    privileges.add_argument("--json", action="store_true")

    version = sub.add_parser("version", help="show PCUCP component versions")
    version.add_argument("--json", action="store_true", help="emit JSON")

    doctor = sub.add_parser("doctor", help="check engine and native runtime without desktop input")
    doctor.add_argument("--json", action="store_true")

    plan = sub.add_parser("plan", help="plan route and safety for a CUCP command")
    plan.add_argument("--command", dest="target_command", required=True, help="CUCP command or macro name")
    plan.add_argument("--arg", action="append", default=[], help="optional command argument for planning")
    plan.add_argument("--json", action="store_true", help="emit JSON")

    windows = sub.add_parser("windows", help="observe visible top-level Windows through the native host")
    windows.add_argument("--json", action="store_true", help="emit JSON")

    uia_tree = sub.add_parser("uia-tree", help="observe a bounded UI Automation tree through the native host")
    uia_tree.add_argument("--max-depth", default="1", help="maximum UIA child depth, capped by native host")
    uia_tree.add_argument("--json", action="store_true", help="emit JSON")

    ocr_image = sub.add_parser("ocr-image", help="run OCR on an image file through the native host")
    ocr_image.add_argument("--path", required=True, help="path to an image file")
    ocr_image.add_argument("--language", help="optional OCR language tag such as en-US or ko")
    ocr_image.add_argument("--json", action="store_true", help="emit JSON")

    ocr_find = sub.add_parser("ocr-find-text", help="find text in an OCR image result")
    ocr_find.add_argument("--path", required=True, help="path to an image file")
    ocr_find.add_argument("--text", required=True, help="text to find")
    ocr_find.add_argument("--match", default="contains", choices=["contains", "exact", "prefix", "fuzzy"], help="text matching mode")
    ocr_find.add_argument("--language", help="optional OCR language tag such as en-US or ko")
    ocr_find.add_argument("--json", action="store_true", help="emit JSON")

    find = sub.add_parser("find-label", help="find top-level labels using native observations")
    find.add_argument("--label", required=True, help="label text to find")
    find.add_argument("--limit", type=int, default=10, help="maximum candidates to return")
    find.add_argument("--json", action="store_true", help="emit JSON")

    task_plan = sub.add_parser("task-plan", help="create a Python task plan without live execution")
    task_plan.add_argument("--app", help="application name to launch or focus")
    task_plan.add_argument("--wait-title", help="window title to wait for")
    task_plan.add_argument("--field", action="append", default=[], help="field assignment in Label=Value form")
    task_plan.add_argument("--type-text", help="text to type in a live step")
    task_plan.add_argument("--shortcut", action="append", default=[], help="shortcut keys such as ctrl+s")
    task_plan.add_argument("--click-label", help="label to click as a live step")
    task_plan.add_argument("--json", action="store_true", help="emit JSON")

    for verb in ('workflow-plan', 'workflow-run', 'task-build', 'task-run', 'form-plan', 'form-run'):
        entry = sub.add_parser(verb, help='declarative Python workflow/form, no PowerShell')
        entry.add_argument('--file', required=True, help='UTF-8 JSON workflow or form specification')
        entry.add_argument('--cdp-endpoint', help='optional human-approved existing numeric-loopback debug endpoint')
        entry.add_argument('--allow-live-control', action='store_true', help='human operator opt-in for this process')
        entry.add_argument('--json', action='store_true')
        if verb == 'workflow-run':
            entry.add_argument('--dry-run', action='store_true')

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    original_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    ns = parser.parse_args(original_argv)
    if getattr(ns, "cdp_endpoint", None):
        from .cdp import CdpAdapter, CdpError
        try:
            CdpAdapter(ns.cdp_endpoint).close()  # validates only; never connects
        except CdpError as exc:
            parser.error(str(exc))

    if ns.verb in {'workflow-plan', 'workflow-run', 'task-build', 'task-run', 'form-plan', 'form-run'}:
        import json
        from pathlib import Path
        from .engine import ComputerSession
        from .native_session import NativeSession
        try:
            with Path(ns.file).open('rb') as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError('Specification exceeds 256 KiB')
            spec = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            parser.error(f'Cannot read specification: {exc}')
        args = {'workflow': spec} if ns.verb.startswith('workflow-') else spec
        if ns.verb == 'workflow-run':
            args['dry_run'] = ns.dry_run
        with NativeSession(allow_live_control=ns.allow_live_control) as native:
            session = ComputerSession(allow_live_control=ns.allow_live_control, native=native,
                                      native_transport='persistent subprocess (stdio-jsonl)', cdp_endpoint=ns.cdp_endpoint)
            try:
                payload = session.handle({'schema': 'cucp.request/v1', 'id': 'cli-workflow', 'command': ns.verb, 'args': args})
            finally:
                session.cancel()
        emit(payload, as_json=bool(ns.json))
        return 0 if payload['status'] == 'ok' else 2

    if ns.verb == "doctor":
        from .doctor import diagnose
        payload = diagnose()
        emit(payload, as_json=bool(ns.json))
        return 0 if payload["status"] == "ok" else 2

    if ns.verb == "mcp":
        from .mcp_server import run_mcp
        return run_mcp(allow_live_control=ns.allow_live_control, cdp_endpoint=ns.cdp_endpoint)

    if ns.verb == "serve":
        from .server import run_server
        return run_server(allow_live_control=ns.allow_live_control, cdp_endpoint=ns.cdp_endpoint)

    if ns.verb in {"capabilities", "privileges"}:
        from .engine import ComputerSession
        args = {"pid": ns.pid} if ns.verb == "privileges" and ns.pid is not None else {}
        payload = ComputerSession().handle({"schema": "cucp.request/v1", "id": "cli", "command": ns.verb, "args": args})
        emit(payload, as_json=bool(ns.json))
        return 0 if payload["status"] == "ok" else 2

    if ns.verb == "version":
        emit(version_payload(), as_json=bool(ns.json))
        return 0

    if ns.verb == "plan":
        payload = plan_command(ns.target_command, ns.arg)
        emit(payload, as_json=bool(ns.json))
        return 0 if payload["status"] == "ok" else 2

    if ns.verb == "windows":
        code, payload, error = run_native("windows")
        if payload is None:
            return emit_native_error("windows", code, error)
        emit(payload, as_json=bool(ns.json))
        return code

    if ns.verb == "uia-tree":
        code, payload, error = run_native("uia-tree", ["--max-depth", str(ns.max_depth)])
        if payload is None:
            return emit_native_error("uia-tree", code, error)
        emit(payload, as_json=bool(ns.json))
        return code

    if ns.verb == "ocr-image":
        native_args = ["--path", ns.path]
        if ns.language:
            native_args += ["--language", ns.language]
        code, payload, error = run_native("ocr-image", native_args)
        if payload is None:
            return emit_native_error("ocr-image", code, error)
        emit(payload, as_json=bool(ns.json))
        return code

    if ns.verb == "ocr-find-text":
        code, payload = ocr_find_text(ns.path, ns.text, ns.match, ns.language)
        emit(payload, as_json=bool(ns.json))
        return code

    if ns.verb == "find-label":
        code, payload = find_label(ns.label, ns.limit)
        emit(payload, as_json=bool(ns.json))
        return code

    if ns.verb == "task-plan":
        payload = create_task_plan(
            app=ns.app,
            wait_title=ns.wait_title,
            fields=ns.field,
            type_text=ns.type_text,
            shortcuts=ns.shortcut,
            click_label=ns.click_label,
        )
        emit(payload, as_json=bool(ns.json))
        return 0 if payload["status"] == "ok" else 2

    parser.print_help()
    return 2
