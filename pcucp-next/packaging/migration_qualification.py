"""Focused migration checks; a completed batch still requires the full gate."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = ("execution", "precision", "cdp")
PROJECTS = {
    "execution": ("PcuCp.LegacyExecution.ContractTests", "PcuCp.LegacyExecution.StartupTests"),
    "precision": ("PcuCp.LegacyPrecision.ContractTests",),
    "cdp": (),
    "foundation": ("PcuCp.LegacyPure.ContractTests", "PcuCp.LegacyTaskForm.ContractTests"),
}
PATTERNS = {
    "execution": "test_legacy_execution*.py",
    "precision": "test_legacy_precision*.py",
    "cdp": "test_legacy_cdp*.py",
    "foundation": "test_migration_inventory.py",
}
ADAPTER_ENV = {
    "execution": "CUCP_EXECUTION_TEST_HOST",
    "precision": "CUCP_PRECISION_TEST_HOST",
    "cdp": "CUCP_LEGACY_CDP_TEST_PYTHON",
}


def select_scope(explicit: str, message: str) -> tuple[list[str], bool]:
    scope = explicit.strip()
    if not scope:
        first_line = message.splitlines()[0] if message else ""
        if "[full regression]" in first_line:
            scope = "full"
        else:
            tags = re.findall(r"\[focus ([^\]]+)\]", first_line)
            if len(tags) > 1:
                raise ValueError("Use one focused scope or the full regression marker.")
            scope = tags[0] if tags else "all"
    if scope not in (*FAMILIES, "foundation", "all", "full"):
        raise ValueError(f"Unknown migration qualification scope: {scope}")
    return list(FAMILIES) if scope in ("all", "full") else [scope], scope == "full"


def enabled_adapters(root: Path = ROOT) -> set[str]:
    data = json.loads((root / ".github/migration-adapters.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"test_adapters"}:
        raise ValueError("Expected the exact migration adapter manifest schema.")
    values = data["test_adapters"]
    if not isinstance(values, list) or any(type(v) is not str or v not in FAMILIES for v in values) or len(values) != len(set(values)):
        raise ValueError("Adapter families must be unique known names.")
    return set(values)


def run_family(family: str, browser: bool = False) -> None:
    if family not in PROJECTS or browser and family != "cdp":
        raise ValueError("Unsupported qualification family/platform combination.")
    pattern = "test_legacy_cdp_browser*.py" if browser else PATTERNS[family]
    tests = sorted((ROOT / "tests/python").glob(pattern))
    if not tests:
        raise ValueError(f"No staged tests for requested family {family}; refusing an empty pass.")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "pcucp-next/python")
    for name in (*ADAPTER_ENV.values(), "CUCP_EXECUTION_STARTUP_TEST_HOST", "CUCP_EXECUTION_ADAPTER_SOURCE",
                 "CUCP_PRECISION_ADAPTER_DRAFT", "CUCP_LEGACY_CDP_ADAPTER_MODE"):
        env.pop(name, None)
    def run(argv: list[str]) -> None:
        subprocess.run(argv, cwd=ROOT, env=env, check=True)
    if browser:
        env["CUCP_CHROME_TEST"] = "1"
        env["CUCP_LEGACY_CDP_BROWSER_TEST"] = "1"
    if not browser:
        native = ROOT / "pcucp-next/dotnet/PcuCp.NativeHost"
        run(["dotnet", "build", str(native), "-c", "Release", "-warnaserror"])
        for project in PROJECTS[family]:
            path = ROOT / "pcucp-next/dotnet" / project
            if not path.is_dir():
                raise ValueError(f"Missing family contract project: {project}")
            command = ["dotnet", "run", "--project", str(path), "-c", "Release"]
            if family != "foundation":
                command += ["--", "--self-test"]
            run(command)
        host = native / "bin/Release/net8.0-windows10.0.19041.0/PcuCp.NativeHost.dll"
        if family == "execution" and (native / "LegacyExecutionStartup.cs").exists():
            env["CUCP_EXECUTION_STARTUP_TEST_HOST"] = str(host)
        if family in FAMILIES:
            env[ADAPTER_ENV[family]] = sys.executable if family == "cdp" else str(host)
            if family in enabled_adapters(ROOT):
                if family == "cdp":
                    env["CUCP_LEGACY_CDP_ADAPTER_MODE"] = "production"
                print(f"Running candidate and promoted {family} adapter gates", flush=True)
            else:
                draft = ROOT / "tests/fixtures" / f"legacy-{family}-adapter.ps1"
                if not draft.is_file():
                    raise ValueError(f"Missing exact {family} adapter draft; refusing to skip its gate.")
                if family == "execution":
                    env["CUCP_EXECUTION_ADAPTER_SOURCE"] = str(draft)
                elif family == "precision":
                    env["CUCP_PRECISION_ADAPTER_DRAFT"] = str(draft)
                else:
                    env["CUCP_LEGACY_CDP_ADAPTER_MODE"] = "draft"
                print(f"Running candidate and exact {family} draft adapter gates; production bodies retained", flush=True)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests/python", "-p", pattern, "-v"])


def available_families(root: Path = ROOT) -> list[str]:
    markers = {
        "execution": root / "pcucp-next/dotnet/PcuCp.LegacyExecution",
        "precision": root / "pcucp-next/dotnet/PcuCp.LegacyPrecision",
        "cdp": root / "pcucp-next/python/pcucp_cli/legacy_cdp.py",
    }
    return [family for family in FAMILIES if markers[family].exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("scope")
    sub.add_parser("available")
    run = sub.add_parser("run")
    run.add_argument("--family", required=True, choices=tuple(PROJECTS))
    run.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if args.action == "available":
        output = f"families={json.dumps(available_families())}\n"
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(output)
        print(output, end="")
        return 0
    if args.action == "run":
        run_family(args.family, args.browser)
        return 0
    families, full = select_scope(os.environ.get("MIGRATION_SCOPE", ""), os.environ.get("MIGRATION_COMMIT_MESSAGE", ""))
    outputs = f"families={json.dumps(families)}\nfull={str(full).lower()}\n"
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(outputs)
    summary = f"Selected families: {', '.join(families)}. Full regression: {'required in this run' if full else 'not run; required before batch retirement is claimed'}.\n"
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(summary)
    print(outputs + summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
