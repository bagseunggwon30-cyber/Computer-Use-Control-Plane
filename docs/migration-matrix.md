# PowerShell retirement proposal — 0.5.0

This is a **generic-core cutover**, not full legacy feature or output parity. Do not merge if preserving every historical macro is required. Complete compatibility work remains on `migration/python-csharp-runtime`; its Windows gate repairs are separate.

Baseline main: `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`. The proposal removes all 13 PowerShell files (1,013,478 Git blob bytes), without Linguist exclusions, renamed archives or PowerShell subprocess bridges. Original source stays in ordinary Git history. Installer, source launcher and Pi/UAC entry are Python. CI uses Bash/Python/.NET/Node, with no PowerShell or Pester.

## Supported replacements and limits

| Responsibility | Replacement | Compatibility limit |
| --- | --- | --- |
| Install/bootstrap | install.py, run_source.py, publish_native.py, start_pi.py | New flags; explicit install apply; old owned launchers can be safely uninstalled |
| Observe/input | Python session + C# worker | Current HWND/PID and observation IDs; no macro aliases, held-input or multi-window gestures |
| UIA | Find/invoke/value/toggle/select/expand-collapse/scroll | Single-use references; providers need manual acceptance |
| OCR/fusion/diff | Same-pixel C# OCR + bounded Python processing | New contracts, not old scoring/serialization parity |
| Workflow/task/form | Typed JSON in Python | Bounded validated steps; old command strings/presets retired |
| Browser CDP | Optional Python adapter | Existing explicit loopback endpoint; no browser launch or port scanning |
| Helper/daemon | Session-owned resident workers | No detached helper, autostart or old sentinel protocol |
| History/record/profile/recovery | Bounded memory metadata/current plans | No persistent legacy history, executable replay or automatic modal dismissal |
| Elevation | Python ShellExecuteExW with explicit --elevated | Pi and all its tools elevated; actual UAC acceptance unverified |

## Retired without full replacement

Clipboard/IME paste and restoration, held-input/multi-window gestures, friendly-name app launch, forced multi-process close, model/vision/goal automation, app-specific presets, automatic recovery execution, persistent strategies/history/cache, detached helper/autostart, old recorder/replay/export, and old benchmark/audit/log/cleanup/release-notes outputs are not preserved. Some were already unavailable or outside the generic-core direction. Removal does not mean implementation.

Old `cucp macro ...` and `cucp legacy ...` fail explicitly. These breaking changes are why this is a draft pending scope selection. Rollback is an ordinary Git revert or use of the old release/branch; no runtime archive is embedded.

## Evidence boundary

Builds, unit/protocol contracts, Windows argv fixtures, resident native process tests and relocated portable smoke do not prove real GUI, Korean IME, clipboard, mixed-DPI or UAC behavior. See [verification](core-validation.md). GitHub main language percentages change only after integration and cached reindexing.
