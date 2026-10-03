# Portable distribution — 0.5.0

On Windows with Python 3.12 x64 and .NET 8 SDK, install the pinned build dependencies and build explicitly:

```text
python -m pip install -r pcucp-next/packaging/requirements-build.txt
python pcucp-next/packaging/build_portable.py
```

The output is dist/CUCP-0.5.0-win-x64.zip plus its SHA256 file. Keep the entire extracted folder. It contains CUCP.exe, Python assets, self-contained native C# worker, optional Pi adapter, a manifest and runtime licenses. It contains no PowerShell scripts or legacy runtime.

The build refuses to overwrite an existing distribution. Choose another --output folder for a rebuild. It verifies checksums, Korean/space-path relocation, startup, UTF-8 JSONL, native process reuse and read-only rejection with runtimes absent from child PATH. `verify_pi_portable.py --bundle <folder>` additionally checks Pi using native Node already installed for the optional host.

Windows x64 preview only: no signing, automatic updater or interactive acceptance claim. Old 0.4.0 downloads do not contain this source change. See [CI](../.github/workflows/core.yml) and [verification](core-validation.md).
