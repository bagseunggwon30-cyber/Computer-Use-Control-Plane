# PCUCP Next

`pcucp-next` is the staged multi-runtime split for CUCP. It keeps the existing
PowerShell CUCP wrapper as a compatibility path while moving new orchestration
and native Windows work into smaller, testable components.

Target architecture:

```text
PowerShell 15-25%  thin launcher, install flow, safety wrapper, command shim
Python     35-45%  planner, orchestrator, task graph, diagnostics, tests
C#/.NET    20-30%  Win32/UIA/OCR/capture bridge and local native host
Config/DB   5-10%  schemas, profiles, policies, run history, target maps
Rust/C++    0-10%  optional hot-path acceleration only when justified
```

This directory is intentionally additive. The legacy `scripts/cucp.ps1` runtime
remains available while verified commands move behind the Python router and
C# native host one at a time.

## Migrated Commands

- `windows`: Python CLI invokes `PcuCp.NativeHost` and returns
  `pcucp.observation/v1`.
- `uia-tree`: Python CLI invokes `PcuCp.NativeHost` and returns a bounded
  `pcucp.uia-tree/v1` UI Automation tree with supported pattern metadata.
- `find-label`: Python searches native top-level window observations and the
  bounded UIA tree, including UIA pattern metadata. This is not yet the full OCR
  label resolver.
- `task-plan`: Python emits a safe plan envelope with live-control metadata. It
  does not execute live actions.

Remaining migration targets include OCR text recognition, deeper text-range
label matching, and live action execution parity.

## Layout

```text
pcucp-next/
  powershell/          thin user-facing launcher
  python/              Python CLI, planner, protocol models
  dotnet/              C# native host project
  schemas/             JSON command and observation contracts
  config/              runtime profile and language split target
```

## Fast Checks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Pester .\tests\pcucp-next.Fast.Tests.ps1"
```
