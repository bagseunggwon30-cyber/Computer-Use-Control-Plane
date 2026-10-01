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
| `click` | Action arguments, `--x INT --y INT`, optional `--button left/right/middle` (left), `--count 1/2` (1) |
| `type` | Action arguments, `--text-b64 BASE64_UTF8` |
| `key` | Action arguments, `--key SHORTCUT` |
| `scroll` | Action arguments, `--direction up/down/left/right`, optional `--amount 1..20` (3) |
| `app-launch` | `--path ABSOLUTE_EXE --allow-live-control`, optional `--args-b64 BASE64_UTF8_JSON_ARRAY` (empty argument vector) |
| `app-close` | Action target and authority arguments, optional `--timeout-ms 0..10000` (1500) |

All window-targeted actions require `--hwnd 0xHEX --pid INT --allow-live-control`. The target must
be a top-level window. Optional `--expected-x`, `--expected-y`,
`--expected-width`, `--expected-height` must appear together and represent the
**full window rectangle**, not the clipped screenshot rectangle. `focus` rejects
geometry constraints before any effect because restoring a window changes its
rectangle; observe again after focusing. Unknown,
duplicate, missing or malformed arguments fail. There is no implicit authority
through an environment variable or an automatic fallback executor.

### Application lifecycle

Both lifecycle commands require explicit live-control authority. A native session
started read-only rejects them even if a request omits or supplies its own live
flag. Unknown options, including `--force`, are rejected.

`app-launch` accepts only an existing `.exe` at an absolute drive or UNC path.
Relative paths, PATH/application-name lookup, URLs, `.lnk`, `.cmd`, `.bat`, device
paths and shell command strings are unsupported. Arguments are a JSON array of
at most 128 strings encoded as strict UTF-8 and then base64. Empty strings and
literal quotes, spaces, backslashes and shell punctuation are preserved as
arguments; they are not interpreted by an intermediate shell. Each string is
at most 8192 UTF-16 units without NUL. The fully quoted Windows command line is
limited to 32766 UTF-16 units, excluding its terminating NUL.

Launch calls `CreateProcessW` with the exact executable separately from the
standard Windows-quoted argument vector. Handle inheritance is disabled and
console executables receive a new console, preventing child apps from consuming
requests or writing into the native JSONL protocol streams. GUI apps follow
their normal GUI startup. No shell, automatic UAC elevation, redirected pipes
owned by the short-lived host, or fallback launcher is used. The executable
inherits the host's environment and integrity. Its own argument parser may have
application-specific conventions. The returned `pid` confirms only successful
process creation: `verification: "not_verified"` does not assert a visible
window, completed startup or application readiness. Observe windows afterwards.

`app-close` posts exactly one `WM_CLOSE` to the explicit top-level HWND after
checking PID, optional expected geometry, privileges and the Default input
desktop. It does not focus the window, send global input, or terminate a process.
It polls the original HWND/PID until that window is absent or the bounded timeout
expires. A zero timeout performs one immediate presence check. Closure returns
`closed: true`, `still_open: false`, `verification: "window_closed"`. This
verifies only the selected window, not process exit or any other app windows.
If it remains open, the result is `partial` with `app_still_open`, `closed: false`,
`still_open: true` and `verification: "not_verified"`. Save dialogs, refusal to
close and busy apps are left intact; callers should observe before further
action. Closing is never retried or escalated to a forced kill. HWND/PID checks
reduce targeting races but cannot atomically bind an action to a window lifetime.

Allowed shortcuts are case-insensitive: ENTER, TAB, ESC/ESCAPE, BACKSPACE, DELETE,
SPACE, LEFT, RIGHT, UP, DOWN, HOME, END, PAGEUP, PAGEDOWN, F1..F12,
CTRL+A/C/V/X/Z/Y/S/F/L/HOME/END, ALT+F4 and SHIFT+TAB. Text is 1..8192 UTF-16
units, valid UTF-8 before base64 encoding, with no NUL. Unicode SendInput avoids
clipboard modification; individual applications may still reject or reinterpret it.

`scroll` uses the current pointer position and verifies that it belongs to the
target. It does not move the pointer or click implicitly.

`click --count 2` dispatches down/up/down/up in one bounded SendInput call.
The application decides whether it recognizes this as a double-click; the
engine observes afterwards and does not assert the application's outcome.

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
error serialization. Lifecycle contracts additionally check startup ABI layout,
strict executable/argument validation, argument quoting round-trips, read-only
session rejection, privilege-refusal paths, one-shot close dispatch and bounded
still-open outcomes using fake platform operations and a fake clock. They execute
no desktop input and launch or close no real apps. Windows publishing, live
UIA/capture/input behavior, IME, DPI changes, UAC and application-specific input
acceptance require testing on a Windows interactive desktop.

## Stage-two UIA and lifetime contract

- `uia-tree --hwnd` emits optional `element_ref` capabilities for eligible same-PID,
  non-password elements. A successful bounded observation creates a new generation;
  partial trees invalidate the generation. References are process-local random
  values; no external runtime ID can authorize an action
- `uia-invoke` / `uia-set-value` require live mode, exact target, expected geometry,
  and an issued reference. Set-value additionally takes UTF-8 `--text-b64`, at most
  4096 UTF-16 units (empty accepted). No fallback, toggle, selection or password action
- Before dispatch: reference expiry/consumption, current runtime ID, PID, HWND
  ancestry, identity fields, element rectangle, visibility/enabled/password state,
  center hit-test, foreground, input desktop and integrity checks. Partial provider
  results preserve `may_have_acted`; successful dispatch still needs observation
- `drag` uses start/end physical coordinates and 1–64 straight-line steps, all in
  the same selected window. Down/moves/up are one SendInput call; partial acceptance
  triggers existing pending-input release. There is no sleep while a button is held
- Python may append startup-only `--parent-handle N` to any native invocation.
  It is an explicitly inherited SYNCHRONIZE-only parent kernel handle. The native
  watchdog exits itself on parent death/wait error, including during stalled provider
  calls. It never enumerates/kills descendants. `app-launch` inherits no handles

Required Windows acceptance checks (not executed on Linux):

1. Observe a WinForms/WPF test window; invoke a button and set a Korean/emoji edit
   value. Verify actual control state, no duplicate action, and clipboard unchanged
2. Destroy/recreate the element, change its label/rectangle, move window, reuse HWND,
   select another PID, cover its center or move focus. Old refs must fail without action
3. Exercise read-only, disabled, password, offscreen, cross-process, unsupported-pattern
   and hanging-provider controls. Record partial results and ensure no input fallback
4. Drag in an expendable canvas at 100/125/150% DPI, including negative-origin monitors.
   Verify mouse release after injected partial SendInput and normal cancellation.
   Hard process/OS failures cannot establish unconditional release guarantees
5. Start through Python, launch an expendable target app, abruptly terminate Python
   during idle and a blocked request: worker exits, target app stays alive. Check
   explicit cancellation too, with nested external job environments and x64/ARM64
6. Check invalid/closed/missing inherited handle fails closed before any live action;
   verify targets do not inherit the parent handle. Direct human native CLI without
   `--parent-handle` is intentionally standalone and has no parent-crash guarantee
7. Repeat the observe/find/action/reobserve workflow from a real generic MCP host
   and a JSONL client. Unit fixtures are not evidence of external-host GUI success
