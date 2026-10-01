"""Reproduce actual tracked PowerShell retirement; never use Linguist percentages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = "docs/legacy-function-inventory.json"
BASELINE_COMMIT = "9ffa354b9904235835a7bc6eb78ed8d3d76317c8"
BASELINE_TREE = "bf895d3120dd5e145f360cb1c41e1d79a061d048"


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def functions(source: bytes) -> dict:
    text = source.decode("utf-8-sig")
    return {
        "lines": len(text.splitlines()),
        "functions": [{"name": match.group(1), "line": text[:match.start()].count("\n") + 1}
                      for match in re.finditer(r"^function\s+([^\s{]+)", text, re.MULTILINE)],
    }


def measure(root: Path = ROOT) -> dict:
    before = git(root, "ls-tree", "-r", "--name-only", "-z", BASELINE_TREE).decode().split("\0")
    current = git(root, "ls-files", "-z").decode().split("\0")
    old_paths = [path for path in before if path.endswith(".ps1")]
    paths = [path for path in current if path.endswith(".ps1")]
    baseline = sum(len(git(root, "show", f"{BASELINE_TREE}:{path}")) for path in old_paths)
    if git(root, "diff", "--name-only", "--", "*.ps1").strip():
        raise ValueError("Stage reviewed PS edits before measuring canonical tracked blobs.")
    total = 0
    for path in paths:
        file = root / path
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"Tracked PS measurement requires an ordinary file: {path}")
        # Index blobs avoid platform checkout CRLF conversion changing the metric.
        total += len(git(root, "show", f":{path}"))
    return {"baseline": baseline, "current": total, "removed": baseline - total,
            "scope": "all tracked .ps1 source and test files; no language exclusions"}


def expected(root: Path, inventory: dict) -> dict:
    result = json.loads(json.dumps(inventory))
    result["baseline_commit"] = BASELINE_COMMIT
    result["baseline_tree"] = BASELINE_TREE
    for entry in result["files"]:
        entry.update(functions((root / entry["path"]).read_bytes()))
    result["power_shell_bytes"] = measure(root)
    retained = {(entry["path"], function["name"]) for entry in result["files"] for function in entry["functions"]}
    seen = set()
    for retired in result["retired_functions"]:
        identity = retired["path"], retired["name"]
        if identity in seen or identity in retained:
            raise ValueError(f"Duplicate or still-present retired function: {identity}")
        seen.add(identity)
        if not (root / retired["replacement"]).is_file() or not retired.get("evidence"):
            raise ValueError(f"Retirement requires an existing replacement and evidence: {identity}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Update counts/locations only; preserve manually reviewed evidence")
    args = parser.parse_args(argv)
    path = ROOT / INVENTORY
    actual = json.loads(path.read_text(encoding="utf-8"))
    wanted = expected(ROOT, actual)
    if args.update:
        path.write_text(json.dumps(wanted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif actual != wanted:
        parser.exit(1, "Migration inventory is stale; review changes then run this script with --update.\n")
    print(json.dumps(wanted["power_shell_bytes"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
