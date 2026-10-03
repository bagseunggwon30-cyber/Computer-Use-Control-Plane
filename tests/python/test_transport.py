"""Executable transport contract tests; no Windows GUI or PowerShell required."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pcucp-next" / "python"))
from pcucp_cli import native_host


def observation(**overrides):
    result = {"schema": "pcucp.observation/v1", "kind": "windows", "status": "ok",
              "data": {"windows": [], "count": 0}, "errors": []}
    result.update(overrides)
    return result


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = Path(self.temp.name) / "host.py"

    def run_host(self, source, **kwargs):
        self.host.write_text(source, encoding="utf-8")
        with patch.object(native_host, "_native_argv", return_value=([sys.executable, str(self.host)], "")):
            return native_host.run_native("windows", **kwargs)

    def test_direct_binary_resolution(self):
        executable = Path(self.temp.name) / "native.exe"
        executable.touch()
        with patch.dict(os.environ, {"CUCP_NATIVE_HOST": str(executable)}):
            self.assertEqual(native_host._native_argv(), ([str(executable)], ""))

    def test_default_path_matches_publish_layout(self):
        root = Path(self.temp.name)
        published = root / "pcucp-next" / "bin" / "native" / "PcuCp.NativeHost.exe"
        published.parent.mkdir(parents=True)
        published.touch()
        with patch.dict(os.environ, {"CUCP_NATIVE_HOST": ""}), patch.object(native_host, "repo_root", return_value=root):
            self.assertEqual(native_host._native_argv(), ([str(published)], ""))

    def test_dll_resolution_never_builds(self):
        dll = Path(self.temp.name) / "native.dll"
        dll.touch()
        with patch.dict(os.environ, {"CUCP_NATIVE_HOST": str(dll)}), patch.object(native_host.shutil, "which", return_value="/bin/dotnet"):
            self.assertEqual(native_host._native_argv()[0], ["/bin/dotnet", str(dll)])

    def test_missing_host_does_not_fallback(self):
        with patch.dict(os.environ, {"CUCP_NATIVE_HOST": str(Path(self.temp.name) / "missing.exe")}):
            code, payload, error = native_host.run_native("windows")
        self.assertNotEqual(code, 0)
        self.assertIsNone(payload)
        self.assertIn("published native host not found", error)

    def test_relative_path_rejected(self):
        with patch.dict(os.environ, {"CUCP_NATIVE_HOST": "host.exe"}):
            self.assertIn("absolute", native_host._native_argv()[1])

    def test_launch_failure_is_structured(self):
        with patch.object(native_host, "_native_argv", return_value=(["/nonexistent/host"], "")):
            code, payload, error = native_host.run_native("windows")
        self.assertEqual(code, 2)
        self.assertIsNone(payload)
        self.assertIn("launch failed", error)

    def test_valid_utf8_and_stderr(self):
        body = observation(data={"windows": [{"title": "메모장"}]})
        code, payload, error = self.run_host(f"import sys\nsys.stdout.reconfigure(encoding='utf-8')\nprint({json.dumps(body, ensure_ascii=False)!r})\nprint('diagnostic', file=sys.stderr)")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["windows"][0]["title"], "메모장")
        self.assertIsNone(payload["route"]["fallback"])
        self.assertEqual(error, "diagnostic")

    def test_malformed_shapes(self):
        bodies = [[], None, "text", {}, observation(data=[]), observation(status=[]),
                  observation(schema={}), observation(errors={}), observation(route=[]),
                  observation(kind="click"), observation(data={"windows": ["bad"]})]
        for body in bodies:
            with self.subTest(body=body):
                code, payload, error = self.run_host(f"print({json.dumps(body)!r})")
                self.assertNotEqual(code, 0)
                self.assertIsNone(payload)
                self.assertIn("protocol error", error)

    def test_polluted_stdout_rejected(self):
        code, payload, error = self.run_host(f"print('building...')\nprint({json.dumps(observation())!r})")
        self.assertNotEqual(code, 0)
        self.assertIsNone(payload)
        self.assertIn("invalid JSON", error)

    def test_error_payload_never_exit_zero(self):
        code, payload, _ = self.run_host(f"print({json.dumps(observation(status='error', errors=['access denied']))!r})")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["errors"], ["access denied"])

    def test_partial_payload_preserved(self):
        code, payload, _ = self.run_host(f"print({json.dumps(observation(status='partial', errors=['timeout']))!r})")
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "partial")

    def test_native_nonzero_not_masked(self):
        code, payload, _ = self.run_host(f"import sys\nprint({json.dumps(observation())!r})\nsys.exit(5)")
        self.assertEqual(code, 5)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["errors"][-1]["code"], "native_exit_status_mismatch")

    def test_timeout_and_no_retry(self):
        calls = Path(self.temp.name) / "calls"
        code, payload, error = self.run_host(f"from pathlib import Path\nimport time\np=Path({str(calls)!r})\np.write_text(p.read_text()+'x' if p.exists() else 'x')\ntime.sleep(10)", timeout_s=0.15)
        self.assertEqual(code, 124)
        self.assertIsNone(payload)
        self.assertIn("not retried", error)
        self.assertEqual(calls.read_text(), "x")

    @unittest.skipIf(os.name == "nt", "POSIX process-group assertion; Windows taskkill requires target validation")
    def test_timeout_kills_descendant(self):
        pidfile = Path(self.temp.name) / "child.pid"
        source = f"import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\nPath({str(pidfile)!r}).write_text(str(p.pid))\ntime.sleep(30)"
        code, _, _ = self.run_host(source, timeout_s=0.2)
        self.assertEqual(code, 124)
        child = int(pidfile.read_text())
        proc = Path(f"/proc/{child}/stat")
        self.assertTrue(not proc.exists() or proc.read_text().split()[2] == "Z", "descendant remains running")

    def test_output_limit(self):
        with patch.object(native_host, "MAX_STDOUT_BYTES", 128):
            code, payload, error = self.run_host("print('x'*10000)")
        self.assertNotEqual(code, 0)
        self.assertIsNone(payload)
        self.assertIn("size limit", error)

    def test_cancel_all_terminates_request(self):
        started = Path(self.temp.name) / "started"
        self.host.write_text(f"from pathlib import Path\nimport time\nPath({str(started)!r}).touch()\ntime.sleep(30)")
        result = []
        with patch.object(native_host, "_native_argv", return_value=([sys.executable, str(self.host)], "")):
            worker = threading.Thread(target=lambda: result.append(native_host.run_native("windows")))
            worker.start()
            deadline = time.monotonic() + 2
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.exists())
            native_host.cancel_all_native()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertNotEqual(result[0][0], 0)

    def test_invalid_timeout(self):
        for timeout in (0, -1, float('nan'), float('inf'), True):
            self.assertEqual(native_host.run_native('windows', timeout_s=timeout)[0], 2)

    def test_invalid_argv(self):
        self.assertEqual(native_host.run_native("windows", ["bad\0argument"])[0], 2)
        self.assertEqual(native_host.run_native("windows", "--string-not-list")[0], 2)
        self.assertEqual(native_host.run_native("")[0], 2)



if __name__ == "__main__":
    unittest.main()
