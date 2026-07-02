from __future__ import annotations

import argparse
from typing import Sequence

from .find_label import find_label
from .legacy import run_legacy
from .native_host import emit_native_error, run_native
from .ocr import ocr_find_text
from .planner import plan_command
from .protocol import emit, version_payload
from .task_plan import create_task_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcucp")
    sub = parser.add_subparsers(dest="verb")

    version = sub.add_parser("version", help="show PCUCP component versions")
    version.add_argument("--json", action="store_true", help="emit JSON")

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
    ocr_find.add_argument("--match", default="contains", choices=["contains", "exact", "prefix"], help="text matching mode")
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

    legacy = sub.add_parser("legacy", help="delegate to the existing PowerShell CUCP wrapper")
    legacy.add_argument("args", nargs=argparse.REMAINDER)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)

    if ns.verb == "version":
        emit(version_payload(), as_json=bool(ns.json))
        return 0

    if ns.verb == "plan":
        emit(plan_command(ns.target_command, ns.arg), as_json=bool(ns.json))
        return 0

    if ns.verb == "windows":
        code, payload, error = run_native("windows")
        if payload is None:
            return emit_native_error("windows", code, error)
        emit(payload, as_json=bool(ns.json))
        return 0

    if ns.verb == "uia-tree":
        code, payload, error = run_native("uia-tree", ["--max-depth", str(ns.max_depth)])
        if payload is None:
            return emit_native_error("uia-tree", code, error)
        emit(payload, as_json=bool(ns.json))
        return 0

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

    if ns.verb == "legacy":
        args = list(ns.args)
        if args and args[0] == "--":
            args = args[1:]
        return run_legacy(args)

    parser.print_help()
    return 2
