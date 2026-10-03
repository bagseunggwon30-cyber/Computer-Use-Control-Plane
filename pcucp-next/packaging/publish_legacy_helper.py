#!/usr/bin/env python3
"""Build a separate, staged-unqualified net48 legacy helper package.

This command neither installs nor publishes the helper and does not change the
portable bundle. Windows and .NET Framework 4.8 are runtime prerequisites; the
SDK is needed only for building. The current helper executable includes the
ScriptedHelperProvider.cs test seam, but fixture assets, contract-test runners,
symbols, and source files are never copied into this package. Packaging is not
Windows transport, privilege, parity, or live-desktop qualification. Manifest
hashes detect changed bytes; they are not a publisher signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "pcucp-next/dotnet/PcuCp.LegacyHelper/PcuCp.LegacyHelper.csproj"
DEFAULT_OUTPUT = ROOT / "pcucp-next/bin/legacy-helper"
MANIFEST_NAME = "manifest.json"
SCHEMA = "cucp.legacy-helper-package/v1"
STATUS = "staged-unqualified"
HELPER_VERSION = "2.0.0"
RUNTIME = "net48"
RUNTIME_DEPENDENCIES = ("Windows", ".NET Framework 4.8")
ENTRYPOINT = "PcuCp.LegacyHelper.exe"
REQUIRED_FILES = (ENTRYPOINT, ENTRYPOINT + ".config", "PcuCp.LegacyInterop.dll")


def build_command(dotnet, output):
    """Return argv only; never interpolate a command into a shell."""
    return [str(dotnet), "build", str(PROJECT), "-c", "Release",
            "--output", str(Path(output).resolve())]


def _metadata():
    return {"schema": SCHEMA, "status": STATUS, "helper_version": HELPER_VERSION,
            "runtime": RUNTIME, "runtime_dependencies": list(RUNTIME_DEPENDENCIES),
            "entrypoint": ENTRYPOINT}


def _regular_file(path):
    # Do not package links to artifacts outside the supplied build directory.
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Required regular file is missing or linked: {path}")


def _file_record(path):
    _regular_file(path)
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
            size += len(chunk)
    return {"sha256": sha.hexdigest(), "bytes": size}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def validate_package(package):
    """Return the verified manifest or raise ValueError for an invalid package.

    v1 has exactly the metadata fields in _metadata() and a files object with
    exactly REQUIRED_FILES as keys. Each file record has exactly sha256 (lowercase
    64-hex) and bytes (a nonnegative JSON integer, never a boolean). The package
    contains exactly those regular files and manifest.json. No paths, timestamps,
    fixture assets, or qualification claims are permitted by this staged schema.
    Validation checks integrity only, never executes or installs the helper.
    """
    package = Path(package).absolute()
    try:
        if package.is_symlink() or not package.is_dir():
            raise ValueError(f"Package directory is missing or linked: {package}")
        manifest_path = package / MANIFEST_NAME
        _regular_file(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                              object_pairs_hook=_unique_object)
        metadata = _metadata()
        if not isinstance(manifest, dict) or set(manifest) != set(metadata) | {"files"}:
            raise ValueError("Manifest fields do not match the legacy helper package schema")
        for key, expected in metadata.items():
            if manifest[key] != expected:
                raise ValueError(f"Unexpected manifest {key}: {manifest[key]!r}")
        files = manifest["files"]
        if not isinstance(files, dict) or set(files) != set(REQUIRED_FILES):
            raise ValueError("Manifest must describe exactly the required helper files")
        if {path.name for path in package.iterdir()} != set(REQUIRED_FILES) | {MANIFEST_NAME}:
            raise ValueError("Package must contain exactly the required helper files and manifest.json")
        for name in REQUIRED_FILES:
            record = files[name]
            if not isinstance(record, dict) or set(record) != {"sha256", "bytes"}:
                raise ValueError(f"Invalid file record: {name}")
            if (not isinstance(record["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
                    or type(record["bytes"]) is not int or record["bytes"] < 0):
                raise ValueError(f"Invalid file hash or size: {name}")
            if _file_record(package / name) != record:
                raise ValueError(f"Package file hash or size mismatch: {name}")
        return manifest
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot validate legacy helper package: {error}") from error


def stage_package(build_output, output):
    """Copy only the three required artifacts into a new non-overwriting folder.

    Build extras are ignored. Incomplete copies are removed on error, and the
    manifest is written last. Even an existing empty directory is not reused.
    """
    source = Path(build_output).resolve()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f"Existing package would be overwritten: {output}")
    for name in REQUIRED_FILES:
        _regular_file(source / name)
    output.parent.mkdir(parents=True, exist_ok=True)
    # mkdir with exist_ok=False prevents concurrent writers from replacing an
    # existing package. Only remove a directory successfully created by us.
    output.mkdir()
    try:
        for name in REQUIRED_FILES:
            with (source / name).open("rb") as src, (output / name).open("xb") as dst:
                shutil.copyfileobj(src, dst)
        manifest = {**_metadata(), "files": {
            name: _file_record(output / name) for name in REQUIRED_FILES}}
        data = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        with (output / MANIFEST_NAME).open("xb") as stream:
            stream.write(data)
        return validate_package(output)
    except BaseException:
        shutil.rmtree(output)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="new package directory; never overwritten")
    parser.add_argument("--dotnet", default="dotnet", help="SDK executable name or path")
    args = parser.parse_args(argv)
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error(f"Existing package would be overwritten: {output}. Select another --output folder.")
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        parser.error("dotnet SDK executable not found; install the SDK separately")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".legacy-helper-build-", dir=output.parent) as work:
            result = subprocess.run(build_command(dotnet, work), cwd=ROOT, shell=False)
            if result.returncode:
                return result.returncode
            manifest = stage_package(work, output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"package": str(output), "status": manifest["status"],
                      "helper_version": manifest["helper_version"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
