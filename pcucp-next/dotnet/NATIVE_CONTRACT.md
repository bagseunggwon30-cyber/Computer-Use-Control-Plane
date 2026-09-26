# Native desktop runtime

The native host supports one-command execution and a persistent `serve` mode.
Python `serve` owns one native worker and imposes a hard request timeout.
See [the resident session contract](../../docs/resident-native-session.md).
Standalone commands retain one JSON document on stdout. Publish once with
`./publish-native.ps1`; normal operations invoke the published executable, never
`dotnet run`.

## Commands

| Command | Arguments |
| --- | --- |
| `version` | None |
| `serve` | Optional startup `--allow-live-control`; inherited JSONL stdin/stdout |
| `windows` | None |
| `uia-tree` | Optional `--hwnd 0xHEX --pid INT`, `--max-depth 0..12` (1), `--max-nodes 1..2000` (200), `--deadline-ms 50..10000` (1500) |
| `ocr-image` | `--path FILE`, optional `--language TAG`; existing OCR payload retained |
| `screenshot` | `--hwnd 0xHEX`, optional `--pid INT`, `--max-width 64..4096` (1600), `--max-height 64..4096` (1000) |
| `privileges` | Optional `--pid INT` |
| `focus` | Action target and authority arguments below |
| `click` | Action arguments, `--x INT --y INT`, optional `--button left/right/middle` (left) |
| `type` | Action arguments, `--text-b64 BASE64_UTF8` |
| `key` | Action arguments, `--key SHORTCUT` |
| `scroll` | Action arguments, `--direction up/down/left/right`, optional `--amount 1..20` (3) |

All actions require `--hwnd 0xHEX --pid INT --allow-live-control`. The target must
be a top-level window. Optional `--expected-x`, `--expected-y`,
`--expected-width`, `--expected-height` must appear together and represent the
**full window rectangle**, not the clipped screenshot rectangle. `focus` rejects
geometry constraints before any effect because restoring a window changes its
rectangle; observe again after focusing. Unknown,
duplicate, missing or malformed arguments fail. There is no implicit authority
through an environment variable or an automatic fallback executor.

Allowed shortcuts are case-insensitive: ENTER, TAB, ESC/ESCAPE, BACKSPACE, DELETE,
SPACE, LEFT, RIGHT, UP, DOWN, HOME, END, PAGEUP, PAGEDOWN, F1..F12,
CTRL+A/C/V/X/Z/Y/S/F/L/HOME/END, ALT+F4 and SHIFT+TAB. Text is 1..8192 UTF-16
units, valid UTF-8 before base64 encoding, with no NUL. Unicode SendInput avoids
clipboard modification; individual applications may still reject or reinterpret it.

`scroll` uses the current pointer position and verifies that it belongs to the
target. It does not move the pointer or click implicitly.

## Responses and results

New commands return:

```json
{"schema":"pcucp.native/v1","status":"ok","kind":"click","data":{"target":{"hwnd":"0x1234","pid":123},"verification":"not_verified","dispatched":true},"errors":[]}
```

`status` is `ok`, `partial` or `error`. Exit codes are 0 for `ok`, 1 for provider
errors/partial observations, and 2 for invalid arguments/unknown commands.
Errors contain `{code,message}`. `windows` retains `pcucp.observation/v1` and
`uia-tree` retains `pcucp.uia-tree/v1`; `ocr-image` retains its original top-level
`pcucp.ocr-image/v1` payload and string errors.

Input delivery is **not application success**. Successful input responses use
`verification: "not_verified"`; the caller must observe the resulting state.
Focus alone uses `verification: "foreground_confirmed"` after checking the
foreground HWND/PID. A failed SendInput can still have delivered part of the
sequence; the error says so, releases any accepted but unreleased keys/buttons
best-effort, and must not be blindly retried.

## Coordinates and capture

All OS-facing positions use physical virtual-desktop pixels, including zero and
negative coordinates. The executable declares PerMonitorV2 awareness and enables
it programmatically. A screenshot is an in-memory PNG and returns:

- `image: {mime_type, data, width, height}`; `data` is base64.
- `geometry: {x,y,width,height,image_width,image_height}` for mapping image pixels
  into the clipped desktop capture rectangle.
- `window_geometry: {x,y,width,height}` for checking unchanged window geometry.
- `target: {hwnd,pid}`, `captured_at`, `target_foreground`, `cursor_included: false`.
- `capture_semantics: "visible_desktop_crop_may_include_occluding_windows"`.

This is a visible-desktop crop, **not** a hidden-window render. It can include
occluding windows, screen gaps or protected black regions. Hidden/minimized
targets are rejected. Captures are clipped to the virtual desktop, preserve aspect
ratio, never upscale, and are bounded to 32 million source pixels and 24 MiB PNG.
No screenshot file is written.

## Input guards and privilege limits

Each live action checks target ownership, current/target token integrity, and the
interactive desktop. Every SendInput call checks target PID, HWND, optional
geometry, and foreground immediately before dispatch. Click additionally checks
the target at the point, moves the pointer, rechecks occlusion, and checks the
actual pointer position before sending a button press. Held user modifiers or
buttons cause `input_busy` rather than being released by automation.

These checks reduce races; Win32 global input is not atomically bound to a target,
and external focus changes can occur between checking and dispatching. Input
guards do not replace a post-action observation.

The executable is `asInvoker`, with `uiAccess=false`. Higher-integrity target
input returns `elevation_required`; inability to inspect tokens returns
`privilege_unknown`. SYSTEM/protected integrity is always rejected with
`unsupported_protected_target`, regardless of UIAccess. The approved host session can be launched normally through
Windows UAC to interact with ordinary elevated applications. The runtime never
requests SYSTEM, bypasses UIPI, switches desktops or automates UAC consent.
Only the Default input desktop is accepted. Token preflight success does not
guarantee a target application's input acceptance.

## UIA limits and tests

UIA traversal has depth, node and best-effort wall-clock budgets. Provider errors
and truncation produce `partial` with explicit errors. A single blocking COM
provider call can exceed the observation deadline, so the Python process timeout
remains the hard limit.

Run the platform-independent contracts with:

```text
dotnet run --project PcuCp.NativeHost.ContractTests
```

They check Win32 INPUT layout, every pixel in representative negative-origin
multi-monitor coordinate maps, malformed authority arguments, and machine-readable
error serialization. They execute no desktop input. Windows publishing, live
UIA/capture/input behavior, IME, DPI changes, UAC and application-specific input
acceptance require testing on a Windows interactive desktop.
