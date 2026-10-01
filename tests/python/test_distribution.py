"""Frozen executable discovery must survive relocation and stale host settings."""
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pcucp-next/python"))
from pcucp_cli import __version__, cli, doctor, legacy, native_host, protocol


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="CUCP 한글 ")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()

    def test_frozen_root_ignores_source_environment(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.root / "CUCP.exe")), \
             patch.dict(os.environ, {"CUCP_ROOT": str(self.root / "wrong-source"), "CUCP_NATIVE_HOST": ""}):
            host = self.root / "native/PcuCp.NativeHost.exe"
            host.parent.mkdir()
            host.touch()
            self.assertEqual(native_host._native_argv(), ([str(host)], ""))
            self.assertEqual(protocol.repo_root(), self.root)
            self.assertEqual(protocol.version_payload()["distribution"], "portable")

    def test_frozen_missing_native_never_searches_cwd_or_source(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.root / "CUCP.exe")), \
             patch.dict(os.environ, {"CUCP_NATIVE_HOST": ""}):
            self.assertIsNone(native_host._native_argv()[0])

    def test_explicit_native_override_is_not_silently_ignored(self):
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"CUCP_NATIVE_HOST": "relative.exe"}):
            command, error = native_host._native_argv()
            self.assertIsNone(command)
            self.assertIn("absolute", error)

    def test_portable_parser_and_legacy_route_exclude_powershell(self):
        with patch.object(sys, "frozen", True, create=True), patch("sys.stderr", new_callable=io.StringIO):
            self.assertNotIn("legacy", cli.build_parser().format_help())
            with patch.object(legacy.subprocess, "Popen") as launch:
                self.assertEqual(legacy.run_legacy(["version"]), 2)
                launch.assert_not_called()

    def test_doctor_checks_version_without_desktop_claim(self):
        native = {"status": "ok", "data": {"version": __version__, "process": 123, "ocr_window": "same-pixels-memory/v1", "uia_patterns": "explicit-pattern-actions/v1", "parent_lifetime_guard": "inherited-parent-handle/v1"}}
        with patch.object(doctor, "_native_argv", return_value=(["native.exe"], "")), \
             patch.object(doctor, "run_native", return_value=(0, native, "")) as run, patch.object(sys, "platform", "win32"):
            result = doctor.diagnose()
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["desktop_verified"])
            run.assert_called_once_with("version")

    def test_doctor_missing_worker_and_version_mismatch_fail(self):
        with patch.object(doctor, "_native_argv", return_value=(None, "missing")), patch.object(doctor, "run_native") as run:
            self.assertEqual(doctor.diagnose()["status"], "error")
            run.assert_not_called()
        with patch.object(doctor, "_native_argv", return_value=(["native.exe"], "")), \
             patch.object(doctor, "run_native", return_value=(0, {"status": "ok", "data": {"version": "old"}}, "")):
            self.assertIn("version_mismatch", [e["code"] for e in doctor.diagnose()["errors"]])


    def test_doctor_rejects_same_version_without_lifetime_feature(self):
        with patch.object(doctor, "_native_argv", return_value=(["native.exe"], "")), \
             patch.object(doctor, "run_native", return_value=(0, {"status": "ok", "data": {"version": __version__}}, "")):
            self.assertIn("native_feature_mismatch", [e["code"] for e in doctor.diagnose()["errors"]])


if __name__ == "__main__":
    unittest.main()
