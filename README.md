# CUCP - Computer Use Control Plane

CUCP is a PowerShell-first Windows computer-use control plane for local AI
agents. It provides one command surface for observing Windows desktop state,
planning grounded UI actions, and running live GUI control only after explicit
safety gates are enabled.

This repository currently contains the public CUCP core runtime, not a
multi-language full platform. GitHub may therefore show this repository as
PowerShell-only. That is expected for the current release because the executable
runtime in this public package is implemented as PowerShell scripts.

## Current Status

Included in this repository:

- PowerShell CLI wrapper: `scripts/cucp.ps1`
- Native helper script for Win32, UI Automation, OCR, screenshot, and CDP-backed
  operations: `scripts/cucp-native-helper.ps1`
- Helper server script for resident/local command handling:
  `scripts/cucp-helper-server.ps1`
- Codex plugin metadata: `.codex-plugin/plugin.json`
- Codex skill entry: `skills/cucp/SKILL.md`
- Command references, troubleshooting notes, install script, and Pester tests

Not included in this public core:

- A Python planner/runtime package
- A C#/.NET project
- A database-backed state service
- Go or Rust native modules
- Any unfinished domain-specific generator work

The intended current identity of this repo is:

```text
PowerShell-first CUCP public core
```

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

- Pester for tests
- Chromium/Electron application launched with a local CDP port for CDP commands

There are no Python, npm, Go, or Rust runtime dependencies in this public core.
See `DEPENDENCIES.md`.

## Verification

Recent local verification for this public core:

```powershell
# PowerShell parser check for all .ps1 files
# Result: 8 PowerShell files parsed successfully

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\cucp.ps1 -Quiet version
# Result: status ok

powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Pester .\tests\cucp.Fast.Tests.ps1"
# Result: 6 passed, 0 failed
```

The full Pester suite exists in `tests/cucp.Tests.ps1`, but the fast smoke suite
is the recommended quick validation path for this public package.

## Documentation

- `references/command-reference.md` - command and macro reference
- `references/cdp-setup.md` - CDP setup for Chromium/Electron apps
- `references/troubleshooting.md` - diagnostics and recovery notes
- `SKILL.md` - root skill-style usage notes
- `skills/cucp/SKILL.md` - Codex plugin skill entry
- `SECURITY.md` - safety and disclosure policy
- `DEPENDENCIES.md` - runtime and optional dependency inventory

## Roadmap

Near-term public-core work:

- Keep the PowerShell runtime stable and testable.
- Improve documentation around safe live-control usage.
- Split future non-PowerShell modules into separate, real projects only after
  they are implemented and verified.
- Keep unfinished or domain-specific experimental work out of the public core.

## License

MIT. See `LICENSE`.
