"""Focused migration checks; a completed batch still requires the full gate."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = ("execution", "precision", "cdp", "interaction", "diagnostics", "file-images")
NEXT_BATCH = ("interaction", "diagnostics", "file-images")
# Keep explicit staging support: a kernel-only gate cannot imply adapter parity.
# Both new families now require their actual shared-session draft suites.
CANDIDATE_SCOPES = ("history-candidate",)
CANDIDATE_ONLY: frozenset[str] = frozenset(CANDIDATE_SCOPES)
DRAFT_ADAPTERS = {
    "interaction": "scripts/cucp-legacy-interaction-adapter.ps1",
    "diagnostics": "scripts/cucp-legacy-diagnostic-adapter.ps1",
}
REQUIRED_FOUNDATION_TESTS = (
    "test_legacy_workflow_parity.py", "test_legacy_workflow_boundaries.py",
    "test_legacy_workflow_diagnostics.py", "test_legacy_workflow_embedded_fixtures.py",
    "test_legacy_workflow_observed_diagnostics.py", "test_legacy_workflow_evidence.py",
)
REQUIRED_ADAPTER_TESTS = {
    "interaction": "test_legacy_interaction_adapters.py",
    "diagnostics": "test_legacy_diagnostics_adapters.py",
}
PROJECTS = {
    "execution": ("PcuCp.LegacyExecution.ContractTests", "PcuCp.LegacyExecution.StartupTests"),
    "precision": ("PcuCp.LegacyPrecision.ContractTests",),
    "cdp": (),
    "interaction": ("PcuCp.LegacyInteraction.ContractTests", "PcuCp.LegacyExecution.StartupTests", "PcuCp.LegacyExecution.ContractTests"),
    "diagnostics": ("PcuCp.LegacyDiagnostics.ContractTests", "PcuCp.LegacyExecution.StartupTests", "PcuCp.LegacyExecution.ContractTests"),
    "file-images": ("PcuCp.LegacyFileOcr.ContractTests",),
    "history-candidate": ("PcuCp.LegacyHistory.Qualification",),
    "foundation": ("PcuCp.LegacyPure.ContractTests", "PcuCp.LegacyTaskForm.ContractTests", "PcuCp.LegacyWorkflow.ContractTests"),
}
PATTERNS = {
    "execution": "test_legacy_execution*.py",
    "precision": "test_legacy_precision*.py",
    "cdp": "test_legacy_cdp*.py",
    "interaction": "test_legacy_interaction*.py",
    "diagnostics": "test_legacy_diagnostics*.py",
    "file-images": ("test_legacy_images.py", "test_legacy_file_ocr.py"),
    "history-candidate": "test_legacy_history_reducers.py",
    "foundation": ("test_migration_inventory.py", "test_legacy_workflow*.py"),
}
ADAPTER_ENV = {
    "execution": "CUCP_EXECUTION_TEST_HOST",
    "precision": "CUCP_PRECISION_TEST_HOST",
    "cdp": "CUCP_LEGACY_CDP_TEST_PYTHON",
    "interaction": "CUCP_INTERACTION_TEST_DLL",
    "file-images": "CUCP_LEGACY_IMAGES_TEST_DLL",
    "diagnostics": "CUCP_DIAGNOSTICS_TEST_HOST",
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
    if scope not in (*FAMILIES, *CANDIDATE_SCOPES, "foundation", "next-batch", "all", "full"):
        raise ValueError(f"Unknown migration qualification scope: {scope}")
    if scope == "next-batch":
        return list(NEXT_BATCH), False
    return list(FAMILIES) if scope in ("all", "full") else [scope], scope == "full"


def enabled_adapters(root: Path = ROOT) -> set[str]:
    data = json.loads((root / ".github/migration-adapters.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"test_adapters"}:
        raise ValueError("Expected the exact migration adapter manifest schema.")
    values = data["test_adapters"]
    if not isinstance(values, list) or any(type(v) is not str or v not in (*FAMILIES, *CANDIDATE_SCOPES) for v in values) or len(values) != len(set(values)):
        raise ValueError("Adapter families must be unique known names.")
    if CANDIDATE_ONLY.intersection(values):
        raise ValueError("Candidate-only kernels cannot be marked as promoted adapters.")
    return set(values)


def print_preview(text: str, *, end: str = "\n", flush: bool = False) -> None:
    """Console encoding must never mask the actual command's exit status.

    The artifact retains the exact bytes. On a legacy Windows console, only its
    bounded preview escapes characters the destination cannot represent.
    """
    if encoding := getattr(sys.stdout, "encoding", None):
        text = text.encode(encoding, errors="backslashreplace").decode(encoding)
    print(text, end=end, flush=flush)


def run_logged(argv: list[str], *, cwd: Path, env: dict[str, str], log_path: Path) -> None:
    """Keep the complete command output while bounding its inline CI rendering."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print_preview(f"Running {argv!r}; complete output: {log_path}", flush=True)
    with log_path.open("wb") as stream:
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    with log_path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - 65536))
        tail = stream.read()
    if size > len(tail):
        print_preview(f"[Inline output limited to the last {len(tail)} bytes; full output is in the log artifact]", flush=True)
    print_preview(tail.decode("utf-8", errors="replace"), end="", flush=True)
    result.check_returncode()


def run_family(family: str, browser: bool = False, log_dir: Path | None = None) -> None:
    if family not in PROJECTS or browser and family != "cdp":
        raise ValueError("Unsupported qualification family/platform combination.")
    if family == "history-candidate":
        path = ROOT / "pcucp-next/packaging/history_candidate_qualification.py"
        if not path.is_file():
            raise ValueError("Missing explicit history candidate runner")
        spec = importlib.util.spec_from_file_location("history_candidate_qualification", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run(ROOT, log_dir, check_adapters=enabled_adapters)
        return
    selected = "test_legacy_cdp_browser*.py" if browser else PATTERNS[family]
    patterns = (selected,) if isinstance(selected, str) else selected
    if family == "foundation":
        for name in REQUIRED_FOUNDATION_TESTS:
            if not (ROOT / "tests/python" / name).is_file():
                raise ValueError(f"Missing exact foundation tests: {name}; refusing an incomplete parser gate.")
    for pattern in patterns:
        if not list((ROOT / "tests/python").glob(pattern)):
            raise ValueError(f"Missing staged tests {pattern} for {family}; refusing an incomplete pass.")
    if family in REQUIRED_ADAPTER_TESTS and family not in CANDIDATE_ONLY:
        required = ROOT / "tests/python" / REQUIRED_ADAPTER_TESTS[family]
        if not required.is_file():
            raise ValueError(f"Missing exact adapter tests: {required.name}; kernel parity alone cannot qualify promotion.")
    env = dict(os.environ)
    # In the full Windows job, retain the caller's CUCP_NATIVE_TEST_HOST so
    # workflow parity still exercises the actual native/PowerShell bridge.
    env["PYTHONPATH"] = str(ROOT / "pcucp-next/python")
    # Fixture reports contain Unicode; keep redirected Python stdout/stderr
    # UTF-8 without changing file decoding or PowerShell culture semantics.
    env["PYTHONIOENCODING"] = "utf-8"
    if family == "foundation" and log_dir is not None:
        env["CUCP_WORKFLOW_DIAGNOSTIC_CAPTURE"] = str(log_dir / "workflow-parser-raw-diagnostics.json")
    if family == "diagnostics" and log_dir is not None:
        env["CUCP_DIAGNOSTICS_RETAINED_CAPTURE_DIR"] = str(log_dir / "retained-diagnostics")
    for name in (*ADAPTER_ENV.values(), "CUCP_EXECUTION_STARTUP_TEST_HOST", "CUCP_EXECUTION_ADAPTER_SOURCE",
                 "CUCP_PRECISION_ADAPTER_DRAFT", "CUCP_LEGACY_CDP_ADAPTER_MODE", "CUCP_INTERACTION_TEST_HOST",
                 "CUCP_LEGACY_IMAGES_ADAPTER_SOURCE"):
        env.pop(name, None)
    command_index = 0
    def run(argv: list[str]) -> None:
        nonlocal command_index
        command_index += 1
        if log_dir is None:
            subprocess.run(argv, cwd=ROOT, env=env, check=True)
        else:
            run_logged(argv, cwd=ROOT, env=env, log_path=log_dir / f"{command_index:02d}.log")
    if browser:
        env["CUCP_CHROME_TEST"] = "1"
        env["CUCP_LEGACY_CDP_BROWSER_TEST"] = "1"
    try:
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
            if family == "file-images":
                publisher = ROOT / "pcucp-next/packaging/publish_legacy_images.py"
                if not publisher.is_file():
                    raise ValueError("Missing compiled file-images publisher.")
                run([sys.executable, str(publisher)])
                env[ADAPTER_ENV[family]] = str(ROOT / "pcucp-next/bin/legacy/PcuCp.LegacyImages.dll")
            elif family == "interaction":
                env[ADAPTER_ENV[family]] = str(ROOT / "pcucp-next/dotnet/PcuCp.LegacyInteraction.ContractTests/bin/Release/net8.0/PcuCp.LegacyInteraction.ContractTests.dll")
                env["CUCP_INTERACTION_TEST_HOST"] = str(host)
            elif family in ADAPTER_ENV:
                env[ADAPTER_ENV[family]] = sys.executable if family == "cdp" else str(host)
            if family in FAMILIES:
                promoted = family in enabled_adapters(ROOT)
                if family in CANDIDATE_ONLY:
                    notice = f"CANDIDATE ONLY: {family} kernel/oracle checks; actual adapter and retirement are NOT qualified."
                    print(notice, flush=True)
                    if summary := env.get("GITHUB_STEP_SUMMARY"):
                        with open(summary, "a", encoding="utf-8") as stream:
                            stream.write(notice + "\n")
                elif promoted:
                    if family == "cdp":
                        env["CUCP_LEGACY_CDP_ADAPTER_MODE"] = "production"
                    elif family == "file-images":
                        entry = ROOT / "scripts/cucp-native-helper.py"
                        if not entry.is_file():
                            raise ValueError("Missing migrated file-images Python entrypoint.")
                        # Historical PS adapters remain library differential
                        # oracles. The public native route is Python/C# now.
                        sys.path.insert(0, str(ROOT / 'tests/python'))
                        from legacy_historical_native import helper
                        env["CUCP_LEGACY_IMAGES_ADAPTER_SOURCE"] = str(helper())
                    print(f"Running candidate and promoted {family} adapter gates", flush=True)
                else:
                    draft = ROOT / DRAFT_ADAPTERS.get(family, f"tests/fixtures/legacy-{family}-adapter.ps1")
                    if not draft.is_file():
                        raise ValueError(f"Missing exact {family} adapter draft; refusing to skip its gate.")
                    if family == "execution":
                        env["CUCP_EXECUTION_ADAPTER_SOURCE"] = str(draft)
                    elif family == "precision":
                        env["CUCP_PRECISION_ADAPTER_DRAFT"] = str(draft)
                    elif family == "cdp":
                        env["CUCP_LEGACY_CDP_ADAPTER_MODE"] = "draft"
                    elif family == "file-images":
                        env["CUCP_LEGACY_IMAGES_ADAPTER_SOURCE"] = str(draft)
                    print(f"Running candidate and exact {family} draft adapter gates; production bodies retained", flush=True)
        for pattern in patterns:
            run([sys.executable, "-m", "unittest", "discover", "-s", "tests/python", "-p", pattern, "-v"])
    finally:
        if not browser and log_dir is not None:
            run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                 str(ROOT / "tests/fixtures/migration-source-map.ps1"), "-Root", str(ROOT),
                 "-OutputPath", str(log_dir / "source-map.json")])


def available_families(root: Path = ROOT) -> list[str]:
    markers = {
        "execution": root / "pcucp-next/dotnet/PcuCp.LegacyExecution",
        "precision": root / "pcucp-next/dotnet/PcuCp.LegacyPrecision",
        "cdp": root / "pcucp-next/python/pcucp_cli/legacy_cdp.py",
        "interaction": root / "pcucp-next/dotnet/PcuCp.LegacyInteraction",
        "diagnostics": root / "pcucp-next/dotnet/PcuCp.LegacyDiagnostics",
        "file-images": root / "pcucp-next/dotnet/PcuCp.LegacyImages/FileOcr.cs",
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
    run.add_argument("--log-dir", type=Path, help="Save complete command logs and bound inline CI output.")
    args = parser.parse_args()
    if args.action == "available":
        output = f"families={json.dumps(available_families())}\n"
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(output)
        print(output, end="")
        return 0
    if args.action == "run":
        run_family(args.family, args.browser, args.log_dir)
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
