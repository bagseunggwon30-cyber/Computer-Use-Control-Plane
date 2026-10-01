"""Qualify extracted C# without executing any window/input/clipboard entry point.

Pinned historical source is compared verbatim, excluding newline conventions.
Windows qualification builds those C# literals separately, compares reflected
public API/PInvoke/ABI metadata, then loads the candidate in PowerShell 5.1.
"""
import base64
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
# This exact tree belongs to published commit 9ffa354b9904235835a7bc6eb78ed8d3d76317c8.
# Tree pinning also works in an independently reconstructed identical checkout.
BASELINE_TREE = "bf895d3120dd5e145f360cb1c41e1d79a061d048"
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyInterop"
CONTRACT_PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyInterop.ContractTests"
SOURCES = {
    "CucpNative": "scripts/cucp-native-helper.ps1",
    "CucpWin32": "scripts/cucp.ps1",
    "HelperWin32": "scripts/cucp-helper-server.ps1",
}


def extract_literal(text, class_name):
    """Select a unique double-quoted C# here-string; never execute PowerShell."""
    blocks = re.findall(r'@"\r?\n(.*?)\r?\n"@', text, re.S)
    matches = [block for block in blocks if re.search(
        r"public (?:static )?class " + re.escape(class_name) + r"\s*\{", block)]
    if len(matches) != 1:
        raise ValueError(f"Expected one C# literal defining {class_name}, found {len(matches)}")
    # The three literals contain no PowerShell variable or backtick interpolation.
    # Reject any future interpolation rather than testing a different C# program.
    if "$" in matches[0] or "`" in matches[0]:
        raise ValueError("Interpolated PowerShell here-string requires explicit qualification")
    return matches[0].replace("\r\n", "\n") + "\n"


def baseline_sources():
    return {name: extract_literal(subprocess.check_output(
        ["git", "show", f"{BASELINE_TREE}:{path}"], cwd=ROOT).decode("utf-8-sig"), name)
        for name, path in SOURCES.items()}


def publisher_module():
    spec = importlib.util.spec_from_file_location("publish_legacy_interop", ROOT / "pcucp-next/packaging/publish_legacy_interop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LegacyInteropSourceTests(unittest.TestCase):
    def test_all_three_sources_exactly_match_pinned_history(self):
        for name, original in baseline_sources().items():
            with self.subTest(type=name):
                self.assertEqual((PROJECT / f"{name}.cs").read_text(encoding="utf-8"), original)

    def test_project_targets_framework48_without_runtime_dependencies(self):
        project = ET.parse(PROJECT / "PcuCp.LegacyInterop.csproj").getroot()
        self.assertEqual(project.findtext("PropertyGroup/TargetFramework"), "net48")
        self.assertEqual(project.findtext("PropertyGroup/PlatformTarget"), "AnyCPU")
        refs = project.findall("ItemGroup/PackageReference")
        self.assertEqual([(r.get("Include"), r.get("PrivateAssets")) for r in refs],
                         [("Microsoft.NETFramework.ReferenceAssemblies", "All")])
        self.assertEqual({p.name for p in PROJECT.glob("*.cs")}, {f"{name}.cs" for name in SOURCES})

    def test_extractor_rejects_missing_duplicate_and_interpolated_sources(self):
        for text in ("", '@"\npublic class X {}\n"@\n@"\npublic class X {}\n"@',
                     '@"\npublic class X { /* $value */ }\n"@'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                extract_literal(text, "X")

    def test_publisher_preserves_unicode_and_spaces_in_argv(self):
        module = publisher_module()
        with tempfile.TemporaryDirectory(prefix="CUCP interop 한글 ") as tmp:
            command = module.build_command("C:/SDK folder/dotnet.exe", Path(tmp))
            self.assertEqual(command[0], "C:/SDK folder/dotnet.exe")
            self.assertEqual(command[-1], str(Path(tmp).resolve()))
            self.assertEqual(command[1], "build")
            self.assertNotIn("powershell", " ".join(command).lower())
            self.assertNotIn("--self-contained", command)

    def test_publisher_checks_expected_artifact_and_never_uses_shell(self):
        module = publisher_module()
        with tempfile.TemporaryDirectory() as tmp, patch.object(module.shutil, "which", return_value="dotnet"), \
                patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                module.main(["--output", tmp])
            (Path(tmp) / module.ASSEMBLY).write_bytes(b"test fixture")
            self.assertEqual(module.main(["--output", tmp]), 0)
            self.assertIs(run.call_args.kwargs["shell"], False)


@unittest.skipUnless(os.name == "nt" and os.environ.get("CUCP_LEGACY_INTEROP_TEST_DLL"),
                     "requires Windows and the built net48 interop DLL")
class LegacyInteropWindowsTests(unittest.TestCase):
    def run_checked(self, argv, **kwargs):
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=180, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace") +
                         result.stderr.decode("utf-8", errors="replace"))
        return result.stdout.decode("utf-8-sig", errors="replace")

    def test_framework48_api_abi_and_powershell51_loader_parity(self):
        dotnet = shutil.which("dotnet")
        powershell = shutil.which("powershell.exe")
        self.assertIsNotNone(dotnet, "SDK required for the isolated baseline build")
        self.assertIsNotNone(powershell, "Windows PowerShell 5.1 required to qualify compatibility")
        candidate = Path(os.environ["CUCP_LEGACY_INTEROP_TEST_DLL"]).resolve()
        self.assertTrue(candidate.is_file(), str(candidate))
        with tempfile.TemporaryDirectory(prefix="CUCP interop 한글 ") as tmp:
            root = Path(tmp)
            for name, source in baseline_sources().items():
                (root / f"{name}.cs").write_text(source, encoding="utf-8")
            # Original literals are compiled only in the test fixture, never in a
            # shipped runtime. No full legacy script is copied or invoked.
            project = (PROJECT / "PcuCp.LegacyInterop.csproj").read_text(encoding="utf-8")
            (root / "baseline.csproj").write_text(project.replace("PcuCp.LegacyInterop", "PcuCp.OriginalInterop"), encoding="utf-8")
            output = root / "baseline-output"
            self.run_checked([dotnet, "build", str(root / "baseline.csproj"), "-c", "Release", "-o", str(output)])
            self.run_checked([dotnet, "build", str(CONTRACT_PROJECT / "PcuCp.LegacyInterop.ContractTests.csproj"),
                              "-c", "Release", "-p:LegacyInteropFramework=net48"])
            runner = CONTRACT_PROJECT / "bin/Release/net48/PcuCp.LegacyInterop.ContractTests.exe"
            self.run_checked([str(runner), "--baseline", str(output / "PcuCp.OriginalInterop.dll"), "--candidate", str(candidate)])
            # Exercise actual .NET Framework binding in PS 5.1 from a relocated,
            # Unicode/spaced path. Reflection only; no native API invocation.
            relocated = root / "DLL 폴더" / candidate.name
            relocated.parent.mkdir()
            shutil.copy2(candidate, relocated)
            script = r'''
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'Expected PowerShell 5.1' }
$assembly = [Reflection.Assembly]::LoadFrom($env:CUCP_INTEROP_QUALIFICATION_DLL)
foreach ($name in @('CucpNative','CucpWin32','HelperWin32')) {
  if ($null -eq $assembly.GetType($name, $true)) { throw "Missing type: $name" }
}
$target = $assembly.GetCustomAttributes([Runtime.Versioning.TargetFrameworkAttribute], $false)[0].FrameworkName
if ($target -ne '.NETFramework,Version=v4.8') { throw "Wrong framework: $target" }
[Console]::Out.WriteLine('PASS: PowerShell 5.1 loaded net48 interop; no desktop APIs called.')
'''
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            text = self.run_checked([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                    env={**os.environ, "CUCP_INTEROP_QUALIFICATION_DLL": str(relocated)})
            self.assertIn("PASS: PowerShell 5.1", text)


if __name__ == "__main__":
    unittest.main()
