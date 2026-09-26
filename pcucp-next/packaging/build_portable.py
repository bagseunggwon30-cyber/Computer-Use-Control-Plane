"""Build the complete Windows x64 portable distribution without PowerShell.

Run on Windows with x64 Python 3.12, the pinned build requirements, and .NET 8
SDK installed. Refuses to overwrite previous distributions. Source mode remains
available for developers; this bundle does not contain the legacy scripts.
"""
from __future__ import annotations
import argparse
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pcucp-next" / "python"))
from pcucp_cli import __version__


def run(argv, **kwargs):
    subprocess.run([str(item) for item in argv], cwd=ROOT, check=True, **kwargs)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def collect_licenses(bundle: Path, dotnet: str):
    licenses = bundle / "licenses"
    licenses.mkdir()
    shutil.copy2(ROOT / "LICENSE", licenses / "CUCP-LICENSE.txt")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python runtime license is missing: {python_license}")
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    dist = distribution("pyinstaller")
    files = [f for f in dist.files or [] if str(f).endswith("COPYING.txt")]
    if not files:
        raise RuntimeError("PyInstaller license is missing")
    shutil.copy2(dist.locate_file(files[0]), licenses / "PyInstaller-COPYING.txt")
    # Publishing does not consistently copy runtime notices; retain those shipped
    # with the SDK used to publish, plus the Windows Desktop SDK's license.
    dotnet_root = Path(dotnet).resolve().parent
    for name in ("LICENSE.txt", "ThirdPartyNotices.txt"):
        source = dotnet_root / name
        if not source.is_file():
            raise RuntimeError(f".NET distribution notice is missing: {source}")
        shutil.copy2(source, licenses / f"dotnet-{name}")
    desktop = sorted(dotnet_root.glob("sdk/8.*/Sdks/Microsoft.NET.Sdk.WindowsDesktop/LICENSE.TXT"))
    if not desktop:
        raise RuntimeError("Windows Desktop SDK license is missing")
    shutil.copy2(desktop[-1], licenses / "WindowsDesktop-LICENSE.txt")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"} or sys.maxsize <= 2**32:
        parser.error("This release requires native Windows x64 Python. Cross-compiling PyInstaller is unsupported.")
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12 x64 for this tested distribution.")
    if version("pyinstaller") != "6.22.3":
        parser.error("Install the pinned packaging/requirements-build.txt first.")
    dotnet = shutil.which("dotnet")
    if not dotnet:
        parser.error("Building requires the .NET 8 SDK; end users do not need it.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f"CUCP-{__version__}-win-x64"
    destination, archive = output / name, output / f"{name}.zip"
    if destination.exists() or archive.exists() or archive.with_suffix(".zip.sha256").exists():
        parser.error(f"Existing distribution would be overwritten: {destination}. Select another --output folder.")
    with tempfile.TemporaryDirectory(prefix="cucp-build-", dir=output) as work:
        work = Path(work)
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
             "--noupx", "--name", "CUCP", "--distpath", work / "dist", "--workpath", work / "build",
             "--specpath", work, "--paths", ROOT / "pcucp-next" / "python", PACKAGING / "entry.py"])
        bundle = work / "dist" / "CUCP"
        run([dotnet, "publish", ROOT / "pcucp-next/dotnet/PcuCp.NativeHost/PcuCp.NativeHost.csproj",
             "-c", "Release", "-r", "win-x64", "--self-contained", "true", "-p:UseAppHost=true",
             "-p:PublishTrimmed=false", "-o", bundle / "native"])
        adapter = bundle / "integrations" / "pi"
        shutil.copytree(ROOT / "integrations/pi/src", adapter / "src")
        shutil.copy2(ROOT / "integrations/pi/package.json", adapter / "package.json")
        shutil.copy2(ROOT / "integrations/pi/README.md", adapter / "README.md")
        shutil.copy2(PACKAGING / "PORTABLE.md", bundle / "README.md")
        shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
        collect_licenses(bundle, dotnet)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = {"schema": "cucp.distribution/v1", "version": __version__, "git_commit": commit,
                    "platform": "win-x64", "python": platform.python_version(),
                    "pyinstaller": version("pyinstaller"), "native_self_contained": True,
                    "dotnet_sdk": subprocess.check_output([dotnet, "--version"], cwd=ROOT, text=True).strip(),
                    "entrypoint": "CUCP.exe", "legacy_included": False,
                    "separate_cucp_runtime_installation": [], "pi_host_included": False}
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        checksums = [f"{digest(f)}  {f.relative_to(bundle).as_posix()}" for f in sorted(bundle.rglob("*")) if f.is_file()]
        (bundle / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
        # Test relocated binaries with Python, Node and dotnet removed from child PATH.
        run([sys.executable, PACKAGING / "smoke_portable.py", "--bundle", bundle])
        shutil.move(str(bundle), str(destination))
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=output, base_dir=name)
    archive.with_suffix(".zip.sha256").write_text(f"{digest(archive)}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"bundle": str(destination), "archive": str(archive)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
