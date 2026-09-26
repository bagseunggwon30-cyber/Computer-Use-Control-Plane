"""Exercise relocated Windows binaries without a runtime on their PATH. No GUI input."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def isolated_environment():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CUCP_", "PYTHON", "DOTNET"))}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    # Simulate stale development settings; frozen asset lookup must ignore them.
    env["CUCP_ROOT"] = str(Path(tempfile.gettempdir()) / "missing-cucp-source")
    env["PYTHONPATH"] = env["CUCP_ROOT"]
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    env["DOTNET_ROOT"] = env["CUCP_ROOT"]
    return env


def smoke(bundle: Path):
    with tempfile.TemporaryDirectory(prefix="CUCP 한글 relocated ") as temp:
        temp = Path(temp)
        relocated = temp / "program with spaces"
        shutil.copytree(bundle, relocated)
        cwd = temp / "unrelated cwd"
        cwd.mkdir()
        for line in (relocated / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
            digest, name = line.split("  ", 1)
            check(hashlib.sha256((relocated / name).read_bytes()).hexdigest() == digest, f"Checksum mismatch: {name}")
        check(not list(relocated.rglob("*.ps1")), "PowerShell script leaked into the portable bundle")
        env = isolated_environment()
        exe = relocated / "CUCP.exe"

        def invoke(argv, source=None, expected=0):
            result = subprocess.run([str(a) for a in argv], input=source, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, encoding="utf-8", cwd=cwd, env=env, timeout=45)
            check(result.returncode == expected, f"{argv}: exit {result.returncode}: {result.stdout}\n{result.stderr}")
            return result.stdout

        info = json.loads(invoke([exe, "version", "--json"]))
        check(info["distribution"] == "portable", "Executable did not use frozen mode")
        diagnostic = json.loads(invoke([exe, "doctor", "--json"]))
        check(diagnostic["status"] == "ok" and diagnostic["desktop_verified"] is False, str(diagnostic))
        # Windows TEMP can use an 8.3 alias (RUNNER~1), while resolve() returns
        # its long name. Compare file identity instead of textual path prefixes.
        expected_native = relocated / "native" / "PcuCp.NativeHost.exe"
        check(Path(diagnostic["native_command"][0]).samefile(expected_native),
              f"Native path did not follow relocated executable: {diagnostic['native_command']}")
        requests = [
            {"schema": "cucp.request/v1", "id": "caps-한글", "command": "capabilities", "args": {}},
            {"schema": "cucp.request/v1", "id": "no-input", "command": "click", "args": {"observation_id": "bad", "x": 0, "y": 0}},
        ]
        source = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)
        responses = [json.loads(line) for line in invoke([exe, "serve"], source).splitlines()]
        check(len(responses) == 2 and responses[0]["id"] == "caps-한글", "JSONL UTF-8 response failed")
        check(responses[0]["data"]["native_host_configured"] is True, "Bundled native worker missing")
        check(responses[1]["status"] == "blocked", "Read-only engine accepted input")
        check(responses[1]["errors"][0]["code"] == "live_control_required", "Incorrect gate error")
        live = [json.loads(line) for line in invoke([exe, "serve", "--allow-live-control"], source).splitlines()]
        check(live[0]["data"]["allow_live_control"] is True, "Startup authority flag was lost")
        check(live[1]["errors"][0]["code"] == "stale_observation", "Live mode accepted an unobserved target")
        # Prove the published worker starts twice on one connection, with its own .NET runtime.
        native = relocated / "native" / "PcuCp.NativeHost.exe"
        wire = "".join(json.dumps({"schema": "pcucp.native.request/v1", "id": i, "command": "version", "args": []}) + "\n" for i in (1, 2))
        responses = [json.loads(line) for line in invoke([native, "serve"], wire).splitlines()]
        check(len(responses) == 2 and all(r["exit_code"] == 0 for r in responses), "Native resident protocol failed")
        check(responses[0]["payload"]["data"]["process"] == responses[1]["payload"]["data"]["process"], "Native worker was not reused")
        invoke([exe, "legacy", "version"], expected=2)
        print("Portable smoke passed: checksums, relocation, Unicode paths, no runtime PATH, doctor, JSONL, authority gates, resident native worker, legacy exclusion.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    smoke(parser.parse_args().bundle.resolve())
