# CUCP - Computer Use Control Plane

CUCP is a Windows computer-use control plane for local AI agents. It provides
one command surface for observing Windows desktop state, planning grounded UI
actions, and running live GUI control only after explicit safety gates are
enabled.

The new core preview in `pcucp-next/` provides a persistent Python session,
a reused C# Windows capture/input process, and a [Pi extension](integrations/pi/README.md).
Start with the [setup guide](pcucp-next/README.md) and
[development direction](docs/core-modernization.md). Development now focuses
on a generic embeddable engine; new application-specific profiles are out of scope.
The older PowerShell command surface remains available separately in `scripts/`.

The core preview supports image/UIA observations, guarded input, bounded batches,
and privilege diagnostics. Input starts off and requires the human operator's
`/computer on`. Windows GUI and elevated-input verification remains a release
gate; see the setup guide for current validation limits.

## Current Status

Stable public core included in this repository:

- PowerShell CLI wrapper: `scripts/cucp.ps1`
- Native helper script for Win32, UI Automation, OCR, screenshot, and CDP-backed
  operations: `scripts/cucp-native-helper.ps1`
- Helper server script for resident/local command handling:
  `scripts/cucp-helper-server.ps1`
- Codex plugin metadata: `.codex-plugin/plugin.json`
- Codex skill entry: `skills/cucp/SKILL.md`
- Command references, troubleshooting notes, install script, and Pester tests

New staged split included under `pcucp-next/`:

- PowerShell thin launcher: `pcucp-next/powershell/cucp-next.ps1`
- Python router/planner package: `pcucp-next/python/pcucp_cli/`
- C#/.NET native host project: `pcucp-next/dotnet/PcuCp.NativeHost/`
- JSON schemas and runtime profile: `pcucp-next/schemas/`,
  `pcucp-next/config/`
- Fast smoke tests: `tests/pcucp-next.Fast.Tests.ps1`

Currently migrated into `pcucp-next`:

- `windows`: Python router calls the C# native host for visible top-level
  window observation.
- `uia-tree`: Python router calls the C# native host for bounded UI Automation
  tree observation, including supported UIA pattern metadata.
- `find-label`: Python searches the native window observation result for
  matching top-level window titles, process names, UIA node metadata, and UIA
  pattern metadata.
- `ocr-image`: Python router calls the C# native host to run Windows OCR on an
  image file.
- `ocr-find-text`: Python matches text over the native OCR image result and
  returns candidate coordinates.
- `task-plan`: Python creates read-only plan JSON with live-control safety
  metadata.

Additional new core commands are exposed through `python -m pcucp_cli serve`:
`observe`, `screenshot`, `focus`, `click`, `type`, `key`, `scroll`, `batch`,
`privileges`, `capabilities`, and `history`. The Pi adapter handles this protocol.

Still on the separate legacy PowerShell path:

- OCR screen capture
- Deep `find-label` across OCR text
- Existing advanced macros and recovery commands

Target language split for future implementation:

```text
PowerShell 15-25%  install, thin launcher, safety wrapper, command shim
Python     35-45%  planner, orchestrator, task graph, diagnostics, tests
C#/.NET    20-30%  Win32/UIA/OCR/capture bridge and native host
Config/DB   5-10%  schemas, profiles, policies, run history, target maps
Rust/C++    0-10%  optional hot-path acceleration only when justified
```

Current status is a staged migration, not full feature parity in the new stack.
The new engine never falls back automatically to legacy commands after a failure.
Use the explicit `legacy` command when compatibility behavior is required.

## What CUCP Does

CUCP helps agents avoid blind coordinate clicking by grounding desktop actions
through Windows and browser automation signals:

- Win32 window enumeration and foreground window checks
- UI Automation control discovery and invocation
- Windows OCR-backed text discovery
- Chromium CDP support for Chromium/Electron applications launched with a local
  debugging port
- Hit-test and target validation before live clicks
- Explicit live-control gate for mouse, keyboard, and text actions
- Redaction helpers for secret-shaped output

CUCP follows this loop:

```text
observe -> plan -> act only with permission -> verify -> recover if needed
```

## Install

```powershell
git clone https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane.git cucp
cd cucp
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The installer is user-scope and does not require administrator privileges. It
creates a local `cucp` command shim and runs a quick health check.

You can also run the wrapper directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\cucp.ps1 -Quiet version
```

Run the staged next-generation router directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 version --json
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 plan --command windows --json
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 windows --json
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 uia-tree --max-depth 1 --json
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 ocr-image --path .\sample.png --json
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 ocr-find-text --path .\sample.png --text "Send" --json
powershell -NoProfile -ExecutionPolicy Bypass -File .\pcucp-next\powershell\cucp-next.ps1 task-plan --type-text "hello" --shortcut "ctrl+s" --json
```

## Quick Start

Read-only commands:

```powershell
cucp macro windows
cucp macro find-label --label "Save" --explain
cucp macro ocr-find-text --text "Save"
cucp macro cdp-detect
```

Live-control commands require `-AllowLiveControl`:

```powershell
cucp -AllowLiveControl macro smart-click --label "Save" --match "Notepad"
cucp -AllowLiveControl macro fill-label --label "Name" --text "Alice"
cucp -AllowLiveControl macro shortcut --keys "ctrl+s"
```

Use read-only planning and dry runs before live control:

```powershell
cucp macro task-plan --app notepad --wait-title Notepad --type-text "hello" --shortcut "ctrl+s"
cucp macro task-run --dry-run --app notepad --wait-title Notepad --type-text "hello" --shortcut "ctrl+s"
```

## Safety Model

CUCP treats live desktop control as a privileged operation.

Safety rules in the current core:

- Live actuation is blocked unless `-AllowLiveControl` is present.
- Sensitive screens and destructive actions are refused or blocked unless the
  exact action has been explicitly approved.
- Coordinate actions can be guarded by target window checks.
- Low-confidence target matches are rejected instead of guessed.
- Logs and release notes redact common secret-shaped values before output.
- Runtime caches, screenshots, logs, local credentials, keys, and tokens are
  excluded by `.gitignore`.

See `SECURITY.md` for the public security policy.

## Repository Layout

```text
cucp/
  .codex-plugin/
    plugin.json
  skills/
    cucp/
      SKILL.md
  scripts/
    cucp.ps1
    cucp-native-helper.ps1
    cucp-helper-server.ps1
    README.md
  pcucp-next/
    powershell/
      cucp-next.ps1
    python/
      pcucp_cli/
    dotnet/
      PcuCp.NativeHost/
    schemas/
      command.schema.json
      observation.schema.json
    config/
      runtime-profile.json
  references/
    command-reference.md
    cdp-setup.md
    troubleshooting.md
    remaining-work.md
  plans/
    notepad-hello-world.json
    README.md
  tests/
    cucp.Fast.Tests.ps1
    cucp.Tests.ps1
    baseline-v1.4.0.json
    baseline-v1.6.0.json
    README.md
  install.ps1
  README.md
  CHANGELOG.md
  SECURITY.md
  DEPENDENCIES.md
  requirements.txt
  LICENSE
```

## Dependencies

Runtime:

- Windows 10 or Windows 11
- Windows PowerShell 5.1 or PowerShell 7+
- Windows UI Automation
- Windows OCR support through `Windows.Media.Ocr`

Optional:

- Python 3.10+ for the staged `pcucp-next` router and planner
- .NET 8 SDK for building the staged C# native host
- Pester for tests
- Chromium/Electron application launched with a local CDP port for CDP commands

The Python runtime uses only the standard library. The Pi integration adds
Pi peer packages and TypeScript development dependencies; see
`integrations/pi/package.json`. See `DEPENDENCIES.md` for legacy dependencies.

## Verification

Core preview validation: 72 Python tests with a configured native test host,
15 Pi tests, TypeScript checking and
the Pi-to-real-Python smoke check pass. Native source compiles against .NET 8,
WPF and Windows SDK reference assemblies, with separate ABI/geometry/argument
checks. [Windows CI](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36216294498)
also passed the .NET build, 12 resident-transport tests and 14 Pester regressions.
Actual Windows GUI behavior and self-contained publishing remain separate gates.

Historical baseline verification recorded before the core preview (not rerun
as evidence for the current changes):

```powershell
# PowerShell parser check for all .ps1 files
# Result: 8 PowerShell files parsed successfully

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\cucp.ps1 -Quiet version
# Result: status ok

powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Pester .\tests\cucp.Fast.Tests.ps1"
# Result: 6 passed, 0 failed

powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Pester .\tests\pcucp-next.Fast.Tests.ps1"
# Result: 20 passed, 0 failed
```

The full legacy Pester suite exists in `tests/cucp.Tests.ps1`, but the fast
smoke suites are the recommended quick validation path for this public package.

## Documentation

- `references/command-reference.md` - command and macro reference
- `references/cdp-setup.md` - CDP setup for Chromium/Electron apps
- `references/troubleshooting.md` - diagnostics and recovery notes
- `SKILL.md` - root skill-style usage notes
- `skills/cucp/SKILL.md` - Codex plugin skill entry
- `SECURITY.md` - safety and disclosure policy
- `DEPENDENCIES.md` - runtime and optional dependency inventory
- `pcucp-next/README.md` - staged Python/C# split details

## Roadmap

Near-term work:

- Verify the new core on an interactive Windows desktop and generic UI fixtures.
- Measure capture/input latency and wrong-target failures before optimizing.
- Harden the resident native worker, then add scoped elevation and UIA element references.
- Add observation events and region zoom with explicit image/coordinate contracts.
- Reuse the execution contract for other agent hosts. See the
  [phased roadmap](docs/core-modernization.md).

## License

MIT. See `LICENSE`.
