from __future__ import annotations

import argparse
from typing import Sequence

from .legacy import run_legacy
from .planner import plan_command
from .protocol import emit, version_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcucp")
    sub = parser.add_subparsers(dest="verb")

    version = sub.add_parser("version", help="show PCUCP component versions")
    version.add_argument("--json", action="store_true", help="emit JSON")

    plan = sub.add_parser("plan", help="plan route and safety for a CUCP command")
    plan.add_argument("--command", dest="target_command", required=True, help="CUCP command or macro name")
    plan.add_argument("--arg", action="append", default=[], help="optional command argument for planning")
    plan.add_argument("--json", action="store_true", help="emit JSON")

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

    if ns.verb == "legacy":
        args = list(ns.args)
        if args and args[0] == "--":
            args = args[1:]
        return run_legacy(args)

    parser.print_help()
    return 2
