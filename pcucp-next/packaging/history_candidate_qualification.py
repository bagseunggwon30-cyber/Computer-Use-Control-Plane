"""Explicit Windows history candidate gate; never adapter promotion or cutover."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

SCOPE = "history-candidate"
REQUIRED_FILES = (
    "tests/python/test_legacy_history_reducers.py",
    "pcucp-next/packaging/history_functional_comparison.py",
    "tests/fixtures/history-reducers/oracle.ps1",
    "tests/fixtures/history-reducers/original-functions.json",
    "tests/fixtures/history-reducers/windows-ps51-host-37092069983.raw.json",
    "tests/fixtures/history-reducers/windows-ps51-host-37092069983.provenance.json",
    *("pcucp-next/dotnet/PcuCp.LegacyHistory.Qualification/" + name for name in (
        "PcuCp.LegacyHistory.Qualification.csproj", "Program.cs", "HistoryContracts.cs",
        "HistoryJson.cs", "HistoryReducer.cs", "HistoryTransport.cs", "HistoryWire.cs")),
)
CODEPAGE_TEST = "HistoryCandidateTests.test_owned_windows_non65001_console_transport"
EXPECTED_RUNS = {(runtime, batch, repeat) for runtime in ("ps51", "ps7")
                 for batch, repeat in (("singleton", 0), ("many", 0), ("many", 1))}


def windows_host() -> bool:
    return os.name == "nt"


def load_history_tests(root: Path):
    path = root / REQUIRED_FILES[0]
    spec = importlib.util.spec_from_file_location("history_candidate_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def required_files(root: Path) -> None:
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            raise ValueError(f"Missing required history candidate file: {name}")


def resolve_hosts() -> dict[str, Path]:
    system_root = os.environ.get("SystemRoot")
    candidates = {
        "ps51": Path(system_root) / "System32/WindowsPowerShell/v1.0/powershell.exe" if system_root else None,
        "ps7": Path(path) if (path := shutil.which("pwsh.exe")) else None,
        "dotnet": Path(path) if (path := shutil.which("dotnet.exe")) else None,
    }
    result = {}
    for runtime, path in candidates.items():
        if path is None or not path.is_file():
            raise ValueError(f"Missing actual Windows {runtime} executable")
        result[runtime] = path.resolve(strict=True)
    if result["ps51"] == result["ps7"]:
        raise ValueError("PS5.1 and PS7 must be distinct executable paths")
    return result


def validate_contract_report(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("Missing Windows contract/codepage evidence")
    report = json.loads(path.read_text(encoding="utf-8"))
    ids = report.get("test_ids", [])
    if (report.get("schema") != "cucp.history-windows-contracts/v1"
            or report.get("status") != "passed-windows-contracts"
            or report.get("skipped") != [] or report.get("failures") != [] or report.get("errors") != []
            or not ids or len(ids) != len(set(ids)) or report.get("tests_run") != len(ids)
            or not any(name.endswith(CODEPAGE_TEST) for name in ids)
            or report.get("owned_non65001_probe") != "passed"):
        raise ValueError("Incomplete, skipped or blocked Windows contract/codepage evidence")
    if report.get("process_artifact_directory") != "windows-contract-processes":
        raise ValueError("Missing Windows inner-process evidence directory")
    directory=path.parent/"windows-contract-processes"
    captures=sorted(directory.glob("*.process.json"))
    if not captures or type(report.get("process_artifact_count")) is not int or report["process_artifact_count"] != len(captures):
        raise ValueError("Missing or incomplete Windows inner-process evidence count")
    codepage_observed=False
    import hashlib
    for capture in captures:
        metadata=json.loads(capture.read_text(encoding="utf-8"))
        prefix=capture.name.removesuffix(".process.json")
        output=metadata.get("stdout_artifact")
        if output not in (prefix+".stdout.bin",prefix+".stdout.ps1"):
            raise ValueError("Invalid inner-process stdout identity")
        stdout_path=directory/output;stderr_path=directory/(prefix+".stderr.bin")
        if not stdout_path.is_file() or not stderr_path.is_file() or stdout_path.stat().st_size>64*1024*1024 or stderr_path.stat().st_size>1024*1024:
            raise ValueError("Missing or oversized inner-process raw evidence")
        stdout=stdout_path.read_bytes();stderr=stderr_path.read_bytes()
        if (metadata.get("stdout_bytes") != len(stdout) or metadata.get("stderr_bytes") != len(stderr)
                or metadata.get("stdout_sha256") != hashlib.sha256(stdout).hexdigest()
                or metadata.get("stderr_sha256") != hashlib.sha256(stderr).hexdigest()):
            raise ValueError("Inner-process raw evidence hash changed")
        if any(type(metadata.get(key)) is not bool for key in ("timed_out","stdout_truncated","stderr_truncated")):
            raise ValueError("Missing inner-process timeout/truncation state")
        if "--owned-console-utf8-probe" in metadata.get("command",[]):
            if (metadata.get("exit_code") != 0 or metadata.get("launch_error") is not None or stderr
                    or any(metadata[key] for key in ("timed_out","stdout_truncated","stderr_truncated"))):
                raise ValueError("Owned-console process did not complete successfully")
            probe=json.loads(stdout)
            if ((probe.get("input_code_page"),probe.get("output_code_page")) != (949,1252)
                    or [r.get("runtime") for r in probe.get("reports",[])] != ["ps51","ps7"]):
                raise ValueError("Owned-console process raw evidence is incomplete")
            codepage_observed=True
    if not codepage_observed:
        raise ValueError("Missing owned-console process raw evidence")
    return report


def validate_differential(directory: Path, history) -> dict:
    path = directory / "report.json"
    if not path.is_file():
        raise ValueError("Missing history differential report")
    report = json.loads(path.read_text(encoding="utf-8"))
    if (report.get("schema") != "cucp.history-reducer-gate/v1" or report.get("status") != "passed-candidate-parity"
            or report.get("production_cutover") is not False or report.get("errors") != []
            or report.get("fixture_count") != 465 or len(history.fixtures()) != 465
            or report.get("source_sha256") != history.SOURCE_SHA256
            or report.get("manifest_sha256") != history.ORIGINAL_SHA256):
        raise ValueError("History differential is blocked, mismatched or not the pinned 465-case candidate")
    runs = report.get("runs", [])
    identities = [(run.get("runtime"), run.get("batch"), run.get("repeat")) for run in runs]
    if len(runs) != 6 or len(set(identities)) != 6 or set(identities) != EXPECTED_RUNS:
        raise ValueError("History candidate requires all six fresh-process differential runs")
    cases = history.fixtures()
    original_input = directory / "input.json"
    if not original_input.is_file() or original_input.read_bytes() != history.input_bytes(cases):
        raise ValueError("Missing or changed full input artifact")
    expected_sources = {p.name: history.digest(p.read_bytes()) for p in sorted(history.PROJECT.glob('*')) if p.is_file()}
    if report.get("candidate_source_sha256") != expected_sources or report.get("oracle_source_sha256") != history.digest((history.FIXTURES/'oracle.ps1').read_bytes()):
        raise ValueError("Candidate or oracle source identity changed")
    if report.get("input_sha256") != history.digest(history.input_bytes(cases)):
        raise ValueError("Pinned full fixture input changed")
    for run in runs:
        runtime, batch, repeat = run["runtime"], run["batch"], run["repeat"]
        prefix = f"{runtime}-{batch}-{repeat}"
        subset = cases[:1] if batch == "singleton" else cases
        input_path = directory / f"{runtime}-{batch}-input.json"
        if not input_path.is_file() or input_path.read_bytes() != history.input_bytes(subset):
            raise ValueError("Missing or changed per-runtime input artifact")
        if run.get("count") != len(subset) or run.get("mismatch_count") != 0:
            raise ValueError("Missing cases or a nonzero exact mismatch count")
        version = run.get("observed_host", {}).get("ps_version", "")
        if not version.startswith("5.1." if runtime == "ps51" else "7."):
            raise ValueError("Actual PowerShell runtime identity was not established")
        loaded = {}
        for kind in ("candidate", "observed"):
            raw_path = directory / f"{prefix}-{kind}.raw.json"
            if not raw_path.is_file():
                raise ValueError(f"Missing required raw history artifact: {raw_path.name}")
            raw = raw_path.read_bytes()
            if history.digest(raw) != run[kind + "_sha256"]:
                raise ValueError("Raw differential output hash changed")
            loaded[kind] = json.loads(raw)
            history.validate_report(loaded[kind], subset, runtime, observation=kind == "observed",
                                    source_hash=history.SOURCE_SHA256, manifest_hash=history.ORIGINAL_SHA256,
                                    input_hash=history.digest(history.input_bytes(subset)))
            for suffix in (".stdout.bin", ".stderr.bin", ".process.json"):
                if not (directory / f"{prefix}-{kind}{suffix}").is_file():
                    raise ValueError(f"Missing bounded process artifact: {prefix}-{kind}{suffix}")
            metadata = json.loads((directory / f"{prefix}-{kind}.process.json").read_text(encoding="utf-8"))
            expected_metadata = {"command", "exit_code", "timed_out", "launch_error", "stdout_truncated", "stderr_truncated", "stdout_artifact", "stdout_bytes", "stderr_bytes", "stdout_sha256", "stderr_sha256"}
            if (set(metadata) != expected_metadata or type(metadata["exit_code"]) is not int or metadata["exit_code"] != 0
                    or metadata["launch_error"] is not None
                    or any(metadata[key] is not False for key in ("timed_out", "stdout_truncated", "stderr_truncated"))):
                raise ValueError("Failed or incomplete process marked as passing")
            stdout = (directory / f"{prefix}-{kind}.stdout.bin").read_bytes()
            stderr = (directory / f"{prefix}-{kind}.stderr.bin").read_bytes()
            if (stdout != raw or stderr or metadata["stdout_bytes"] != len(stdout) or metadata["stderr_bytes"] != len(stderr)
                    or history.digest(stdout) != metadata.get("stdout_sha256") or history.digest(stderr) != metadata.get("stderr_sha256")):
                raise ValueError("Captured process bytes disagree with accepted raw output")
        mismatch_path = directory / f"{prefix}-mismatches.json"
        if not mismatch_path.is_file() or json.loads(mismatch_path.read_text(encoding="utf-8")) != [] or history.compare_reports(loaded["candidate"], loaded["observed"]):
            raise ValueError("Exact raw-order/type/Console comparison did not pass")
    return report


def run(root: Path, log_dir: Path | None, *, check_adapters) -> None:
    directory = (log_dir or root / ".migration-logs/history-candidate").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if next(directory.iterdir(), None) is not None:
        raise ValueError("History candidate evidence directory must be empty")
    summary = {"schema": "cucp.history-candidate-ci/v1", "scope": SCOPE, "candidate_only": True,
               "production_cutover": False, "status": "blocked", "completed_stages": [], "error": None}
    notice = "CANDIDATE ONLY: history reducers; production adapters, helper retirement and cutover are NOT qualified."
    print(notice, flush=True)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as stream:
            stream.write(notice + "\n")
    try:
        required_files(root)
        check_adapters(root)
        if not windows_host():
            raise ValueError("History candidate CI requires real Windows PS5.1 and PS7; portable tests cannot satisfy it")
        hosts = resolve_hosts()
        summary["resolved_executables"] = {name: str(path) for name, path in hosts.items()}
        history = load_history_tests(root)
        singleton = history.fixtures()[:1]
        data = history.input_bytes(singleton)
        input_path = directory / "host-probe-input.json"
        input_path.write_bytes(data)
        with tempfile.TemporaryDirectory(prefix="history-ci-original-") as owned:
            source = history.materialize_original(owned, artifact_prefix=directory / "original-git-source")
            for runtime in ("ps51", "ps7"):
                raw = history.run_bounded([str(hosts[runtime]), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(root / "tests/fixtures/history-reducers/oracle.ps1"), "-InputPath", str(input_path),
                    "-SourcePath", str(source), "-Runtime", runtime], artifact_prefix=directory / ("host-" + runtime))
                observed = json.loads(raw)
                history.validate_report(observed, singleton, runtime, observation=True,
                    source_hash=history.SOURCE_SHA256, manifest_hash=history.ORIGINAL_SHA256, input_hash=history.digest(data))
                version = observed["host"].get("ps_version", "")
                if not version.startswith("5.1." if runtime == "ps51" else "7."):
                    raise ValueError("Unexpected actual PowerShell engine version")
                summary.setdefault("verified_hosts", {})[runtime] = observed["host"]
        summary["completed_stages"].append("verified-windows-hosts")
        project = root / "pcucp-next/dotnet/PcuCp.LegacyHistory.Qualification"
        history.run_bounded([str(hosts["dotnet"]), "build", str(project), "-c", "Release", "-warnaserror"],
                            timeout=180, artifact_prefix=directory / "managed-build")
        dll = project / "bin/Release/net8.0/PcuCp.LegacyHistory.Qualification.dll"
        if not dll.is_file():
            raise ValueError("History managed build did not produce its required DLL")
        history.run_bounded([str(hosts["dotnet"]), str(dll), "--self-test"], artifact_prefix=directory / "managed-self-test")
        summary["completed_stages"].append("managed-self-test")
        suite = root / REQUIRED_FILES[0]
        contracts = directory / "windows-contracts.json"
        history.run_bounded([sys.executable, str(suite), "--windows-contracts", "--report-path", str(contracts)],
                            timeout=300, artifact_prefix=directory / "windows-python-tests")
        summary["windows_contracts"] = validate_contract_report(contracts)
        summary["completed_stages"].append("all-windows-python-tests-with-owned-codepage-probe")
        differential = directory / "differential"
        history.run_bounded([sys.executable, str(suite), "--differential", "--ps51", str(hosts["ps51"]), "--ps7", str(hosts["ps7"]),
                            "--report-dir", str(differential)], timeout=1200, artifact_prefix=directory / "six-run-differential")
        parity = validate_differential(differential, history)
        summary["completed_stages"].append("six-fresh-process-exact-differentials")
        summary["differential_runs"] = len(parity["runs"])
        summary["status"] = "passed-candidate-only"
    except Exception as error:
        summary["error"] = str(error)
        raise
    finally:
        (directory / "candidate-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
