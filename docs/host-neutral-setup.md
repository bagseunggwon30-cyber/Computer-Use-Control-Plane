# Host-neutral computer use (local, unreleased modernization)

CUCP supplies Windows observation and action tools to an AI **host** that can launch a local MCP server or bridge the JSONL protocol. Pi is one optional adapter. A closed chat application without local tool/plugin support cannot gain computer use simply by installing CUCP. No model API, provider account, API key, Pi installation, or Node server is required by the core.

## Responsibilities and trust boundary

- Python: protocol schemas, human-selected live mode, session/observation state, serial workflow, cancellation, bounded metadata history, deployment orchestration
- C#: Windows capture/UIA/input, target identity/geometry/privilege validation, explicit process creation, graceful window close
- Host: model selection, image interpretation, user consent and per-task authorization, goals and result verification
- PowerShell: optional compatibility launch shim, plus the **retained, not yet migrated legacy implementation**

The default is read-only. An operator may start a separate process with `--allow-live-control` after choosing to grant that session control. No tool or request argument can enable control. Restart to change permission, and discard all observation IDs after restart. This is an application-level gate, not a sandbox for the host's other tools. Anyone able to run local executables as the user already has that user's OS privileges.

There is no HTTP listener, remote daemon, network authentication token, saved model credential, or auto-start installation in this path. Local subprocess ownership is the transport boundary. Do not expose stdin/stdout through an unauthenticated network bridge. Existing optional legacy vision-provider execution is separate from this core.

## Source setup without PowerShell

On Windows with Python 3.10+ and .NET 8 SDK, from repository root:

```text
python pcucp-next/packaging/publish_native.py
python -m pip install -e pcucp-next/python
cucp doctor --json
cucp mcp
```

Publishing is an explicit developer build, never an action-time rebuild. For ARM64, add `--runtime win-arm64` (not verified in this change). `--dotnet` selects an SDK executable; `--output` selects a publish folder. The old `publish-native.ps1` is a compatibility shim delegating to this Python command. A future newly built portable bundle can use `CUCP.exe mcp`; existing 0.4.0 published downloads do **not** contain these uncommitted changes.

## Generic local MCP configuration

Many MCP-capable hosts accept an object shaped like this; consult that host's configuration UI and use your actual absolute paths. This is an example, not a claim of tested compatibility with every client:

```json
{
  "mcpServers": {
    "cucp": {
      "command": "C:\\Python312\\python.exe",
      "args": ["-u", "-m", "pcucp_cli", "mcp"],
      "env": {
        "PYTHONPATH": "C:\\tools\\Computer-Use-Control-Plane\\pcucp-next\\python",
        "CUCP_NATIVE_HOST": "C:\\tools\\Computer-Use-Control-Plane\\pcucp-next\\bin\\native\\PcuCp.NativeHost.exe"
      }
    }
  }
}
```

Start with read-only access and inspect the exposed tools. For an explicitly authorized live session the **human host configuration** appends `--allow-live-control` to `args`. Do not let the model rewrite this configuration or persist broader permission. Read-only screenshots/UIA can still contain private information: the host must obtain consent before sending them to its chosen model provider.

## MCP contract

The dependency-free stdio adapter implements JSON-RPC newline frames, `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`, and `notifications/cancelled`. Supported versions: 2025-11-25, 2025-06-18 and 2024-11-05. An unsupported version gets the latest supported version; the client must disconnect if it cannot use it. No resources, prompts, sampling, HTTP transport, tasks or JSON-RPC batches are advertised. The 2025-03-26 batched protocol version is not selected.

- Tool names are `cucp_` plus the engine command with hyphens replaced by underscores, for example `cucp_uia_tree` and `cucp_app_close`
- `tools/list` gives explicit argument schemas. Python engine validation remains authoritative; unknown arguments/commands fail closed
- Screenshot bytes are MCP `image` content blocks (`mimeType: image/png`), while text content retains dimensions, target, coordinate mapping, observation ID and errors. They are not just base64 dumped into prose
- One pending tool call; a second is rejected as busy, not queued. Clients should serialize calls
- Request IDs must not be reused. The most recent 1,024 are retained for duplicate rejection, matching the bounded engine policy; this is not persistent exactly-once delivery
- Cancel the active request with its exact ID. The pending response is suppressed, the native process is closed, and the computer session becomes terminal. Restart and re-observe; **never replay input automatically**. Cancellation may occur after input already reached Windows
- EOF, SIGINT, SIGTERM and broken output close the native session. Windows parent-crash containment now uses an inherited parent-handle watchdog; this native OS path still needs real Windows acceptance testing (see below)
- Frames are bounded to 256 KiB. Stdout is protocol-only. History stores up to 200 result metadata events without text or screenshots

The implementation was checked against the official [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [cancellation](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation), [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), and [tool content](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) contracts. Isolated and actual subprocess protocol tests do not replace testing an external MCP host.

## JSONL / custom tool-calling hosts

Existing `python -u -m pcucp_cli serve` remains a provider-neutral alternative. A bridge sends `cucp.request/v1` and receives `cucp.response/v1`. See [the existing engine contract](core-modernization.md#현재-연결-계약). A host using its own function-calling API can map the same schemas and image metadata rather than adopting Pi. Keep one owning process/session and preserve input cancellation and retry rules.

Typical sequence: `windows` → choose exact HWND/PID → `observe` → an authorized action using `observation_id` → inspect the new image/state. Returned images use their own pixel dimensions, not the model's resized thumbnail. Tokens expire after 60 seconds, are replaced on new observation and consumed before mutation. A batch stops at first non-ok result and marks remaining steps skipped.

## New process lifecycle operations

- `app-launch`: `path` is an absolute existing Windows `.exe`, `arguments` a string list (at most 64, each up to 4,096 characters at Python boundary; tighter total Windows command-line bound also applies). C# uses explicit process creation with no shell dispatch, no inherited protocol handles and no automatic elevation. Launch success does not prove a window exists or is ready. Programs such as `cmd.exe` are still executable programs, so **host approval of executable, arguments and purpose is necessary**; argv separation is not an application sandbox
- `app-close`: requires the latest observation ID, optional `timeout_ms` 0–10,000. C# rechecks HWND/PID and expected geometry, queues one targeted WM_CLOSE, waits within the bound and returns `app_still_open` if necessary. It never kills. `window_closed` verifies only the selected HWND/PID disappeared, not that all process windows closed or data saved
- Lifecycle changes consume observation state. Call `windows`/`observe` afterward. Neither operation retries on timeout or in a later batch step after failure

Pi's existing six-tool surface is deliberately unchanged in this stage; lifecycle operations are available through JSONL/MCP. No provider's model is invoked to decide or execute a lifecycle action.

## Verification limits

See [migration matrix](migration-matrix.md). Linux tests use native fakes and exact C# contracts; they never operate a real desktop or call model accounts. Actual Windows GUI capture, clicks, Korean IME, mixed DPI/multi-monitor, UAC/secure desktop, external MCP client compatibility, and newly built portable distributions require separate verification. No claim that those operations were tested is made here.

## Observation-bound UIA and input additions (local stage two)

This feature branch exposes 40 tools over stdio MCP and JSONL. The existing Pi extension
retains its earlier explicit tool subset; no claim is made that its schemas gained
these new operations. A host can use MCP or map the JSONL contract without Pi.

1. Call `observe` on an exact HWND/PID with `include_ui: true`
2. Keep its `observation_id`; eligible UIA nodes contain opaque `element_ref` strings
3. Optionally call `uia-find` with that observation and an exact, case-sensitive
   `name`, `automation_id`, and/or `control_type`. All matches are returned; multiple
   matches are explicitly marked ambiguous. No implicit first-match action occurs
4. Call `uia-invoke` with one selected reference, or `uia-set-value` with `text`
   (empty is allowed). These are live mutations and can trigger consequential app
   actions; the AI host must obtain any approval required for the actual effect
5. Re-observe with `include_ui: true` before another UIA action. Automatic post-action
   capture returns a fresh screenshot but does **not** acquire another UIA reference

References expire after 60 seconds in the native process and are consumed as a
whole generation on an action attempt. New screenshots/trees invalidate native
references. Standalone `uia-tree` clears Python's actionable reference set too.
UIA actions require the same worker session; a per-command executable cannot reuse
references. Native execution checks HWND/PID, runtime ID, ancestry, observed
identity/geometry, enabled/onscreen/non-password state, foreground, hit testing,
input desktop and integrity access. Provider errors can still happen between
checks; invocation is not a transaction or proof of application success. There is
no raw-runtime-ID action, search-and-click fallback, automatic retry or elevation.

`drag` accepts `x`, `y`, `to_x`, `to_y` in returned screenshot image pixels, plus
optional `steps` (1–64; default 16). It is a left-button, straight-line, same-window
operation. Every sampled point is checked before dispatch. Down, motion and up are
one bounded SendInput batch with best-effort release after reported partial delivery.
There is no timed dwell, cross-window drag, held-button API or guaranteed cleanup
after an OS/process crash. Some apps require timed drag gestures; verify visually.

`type` emits Unicode SendInput packets, not physical Korean IME key composition.
`uia-set-value` uses ValuePattern and avoids focus-dependent typing when supported.
Both accept at most 4096 UTF-16 units, reject NUL/unpaired surrogates, and leave the
clipboard unchanged. Unicode packets may be ignored by games, terminals, custom
editors, password fields or controls relying on IME composition; no success claim
is made without observing the final application value. Password UIA actions are
explicitly rejected. Clipboard paste/IME mode switching remain legacy-only.

Coordinates are physical virtual-desktop pixels natively, screenshot image pixels
at the host boundary. Negative monitor origins and image scaling are covered by
pure mapping tests. Per-monitor DPI awareness and window geometry are rechecked;
real 125%/150% mixed-DPI monitor movement remains a Windows acceptance test.

## Worker lifetime and cancellation

The Python launcher on Windows inherits one explicit SYNCHRONIZE-only parent
process handle into its native worker. A native watchdog waits on that kernel
object independently of UIA dispatch. An invalid/already-signalled handle fails
before dispatch; parent death or a wait failure exits **only the control worker**.
There is no PID reuse lookup, JobObject membership, descendant kill, remote
listener or persistent service. User apps launched through `app-launch` have
handle inheritance disabled and are not owned by the watchdog.

Cancellation and timeout use the original Popen process handle on Windows.
`taskkill /T` is deliberately absent: launched apps may contain unsaved user work.
An interrupted input may already have acted. Termination is terminal for that
session, with no retry, restart or target-app close implied. An inherited outer
job imposed by the user's host is outside this project's ownership; we cannot
promise how an unrelated supervisor manages its entire process tree.

Publish the matching C# source before using these Python changes. Older published
0.4.0 native binaries do not implement the parent-handle startup contract, even
though the unreleased source still uses the same version number. `doctor` reports
missing guard support as a feature mismatch when a version response is available.
The parent-liveness contract itself still needs real Windows handle/parent-crash
validation; Linux tests only verify parsing and adapter wiring.


## Expanded Python/C# feature branch

See [workflow migration](workflow-migration.md) for 64-step workflows, PID-bound tasks, fresh-selector forms, bounded read-only watches and memory-only audits. New UIA patterns and exact-pixel window OCR require a native binary built from the same commit. `doctor` checks feature markers as well as the version label. No model API, Pi account, persistent service, PowerShell runtime or shell adapter is required by these tools.
