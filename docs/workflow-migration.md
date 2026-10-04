# Declarative Python workflows, tasks, forms, watches and recording

This feature branch expands the existing Python/C# runtime. It does **not** retire all legacy PowerShell features. No PowerShell or model SDK is invoked by any command on this page. Pi is optional; the same tools are available to MCP and JSONL hosts.

## Tools and entry points

- `workflow-plan` validates and describes a `cucp.workflow/v2` specification
- `workflow-run` executes it, or reports a `dry_run` without launching native code
- `task-build` compiles explicit launch/wait/target/field/text/key/submit intent into a reviewable workflow; `task-run` runs that workflow
- `form-plan` and `form-run` use exact UIA selectors; every field has its own fresh observation and a unique-match assertion
- `watch` polls only a supported read-only leaf command, with bounded cycles and optional JSON result condition
- `record-start`, `record-read`, `record-stop` keep up to 1,000 metadata events in memory; no typed values, request IDs, screenshots, titles, disk log or replay
- `app-profile` summarizes roles and patterns actually present in a current observation
- `recovery-plan` recommends re-observation; it never implicitly dismisses a modal or repeats an input

Source CLI examples:

```text
cucp workflow-plan --file examples/workflows/inspect-window.json --json
cucp workflow-run --file examples/workflows/inspect-window.json --json
cucp workflow-run --file my-approved-plan.json --dry-run --json
cucp workflow-run --file my-approved-plan.json --allow-live-control --json
cucp form-plan --file my-form.json --json
cucp task-build --file my-task.json --json
```

The form template contains placeholders on purpose and must be populated from current observations. It does not submit anything by default.

## Workflow format

```json
{
  "schema": "cucp.workflow/v2",
  "name": "Inspect a setting",
  "timeout_ms": 10000,
  "steps": [
    {"id": "seen", "command": "observe", "args": {"hwnd": "0x123", "include_ui": true}},
    {"id": "found", "command": "uia-find", "args": {
      "observation_id": {"$ref": "/seen/observation_id"}, "automation_id": "settingCheckbox"
    }, "assert": {"path": "/count", "equals": 1}}
  ]
}
```

Replace `0x123` and the automation ID with actual current values. Planning alone does not prove an app exposes that element.

A reference is an entire object with the sole key `$ref`. Its JSON pointer starts with an earlier step ID and then descends into that step's result data. No string interpolation, shell tokenization, expressions, dynamic command names, loops, recursive workflows or evaluation occurs. Assertions support exactly one of `equals`, `count`, `exists`. Equality preserves JSON value types recursively, so booleans cannot equal integers inside containers.

A task accepts exactly one of `target:{hwnd,pid}` or `wait:{title,...}`. Optional `launch:{path,arguments}` requires a wait selector, and the wait PID is bound to the newly launched process. Delegating launch to another existing process may therefore require a separate host decision. Optional `focus:true` is explicit. `fields`, `text`, `keys` and `submit` compile to ordinary guarded operations. Friendly executable names, URLs and shell associations are not resolved.

A form accepts `hwnd`, optional `pid`, and 1–15 `{selector,text}` fields. A selector has at least one exact `name`, `automation_id`, or `control_type`. Zero or multiple matches stop before the corresponding input. Password/unsupported/read-only controls are rejected by the native contract. `submit` is an optional exact selector and only invokes when explicitly included. A successful dispatch does not prove the app accepted or saved the value. There is no silent fallback to keyboard, coordinates, clipboard or a browser adapter.

## Bounds and failure semantics

- At most 64 leaf operations, 60 seconds per request, and a 256 KiB input specification
- At most 2 MiB retained result metadata plus the latest available image; large results stop execution
- All step schemas and the aggregate live requirement are checked before execution; resolved references are checked again before their leaf operation
- Startup live-control authority cannot be granted or changed by a plan, step or request
- Every native mutation still consumes its observation/reference and revalidates native target identity
- The first error, blocked/partial operation, failed assertion or cancellation stops later steps
- Failed mutations are never retried or rolled back. Explicit `read_retries` (0–3, default 0) only concerns bounded transient read errors
- A successful mutation followed by failed observation/settling, or any subsequent workflow failure, can return `partial` with `may_have_acted:true`. Step `operation_status` preserves the original result where known
- Cancellation is terminal for the session. A stalled Windows provider still relies on the existing owned-worker timeout boundary
- Watch uses 1–100 cycles and 100–5,000 ms intervals within the request deadline. It is not a persistent daemon
- `record-*` describes session request metadata, not physical OS input recording or replayable macros

The host remains responsible for user approval of consequential actions and data destinations. This runtime's live-mode flag is a technical dispatch boundary, not universal permission.

## Explicit legacy compatibility limits

Legacy command-string workflows, arbitrary macro composition, continue-on-error, live retries, persisted strategy history, recorder replay/export, app-specific form/CDP fallbacks, indefinite background watching and modal-dismiss recovery remain in the retained PowerShell source. The JSON v2 format is an intentional explicit core interface, not a claim of byte-for-byte legacy CLI compatibility. Old implementations are not deleted until their replacements and necessary Windows acceptance are validated.

## Verification

`test_workflow_runtime.py` covers reference resolution, exact-match ambiguity, Unicode values, dry runs, preflight/live gates, partial mutation outcomes, cancellation, deadline, schema parity, task PID binding, no automatic mutation retries and audit bounds. `test_workflow_transport.py` exercises the same form through actual MCP and JSONL adapters with an injected native fixture, plus CLI planning with an unavailable native executable. These tests do not certify a live model provider or interactive Windows application.
