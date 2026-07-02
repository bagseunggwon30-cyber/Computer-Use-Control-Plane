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
