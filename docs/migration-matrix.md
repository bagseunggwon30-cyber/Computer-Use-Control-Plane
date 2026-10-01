# Python/C# migration matrix

This is a staged source patch against `8a8426ae5319e71fd9a3655e04a99ef291fbb51e`, not a complete PowerShell rewrite or a newly published release. Existing PowerShell sources remain visible and usable where safe. No Linguist exclusions or file hiding are used to change language percentages.

## Implemented in this stage

| Capability | Python responsibility | C# responsibility | Compatibility / parity status |
|---|---|---|---|
| Provider-neutral host connection | New stdio MCP lifecycle, tool schemas, image mapping, cancellation; existing JSONL retained | Existing resident stdio native worker | Pi optional and unchanged; external MCP client smoke still needed |
| Process launch | Validation, live gate, argv JSON, observation invalidation, errors/no retry | Explicit `.exe` process creation, Windows argv quoting, handle isolation, desktop/privilege check | New bounded subset; legacy friendly app names, URLs, scripts and shell associations not migrated |
| App close | Latest single-use observation, bounded timeout, stop-on-failure | Exact target/geometry/privilege, one WM_CLOSE, bounded wait, no implicit kill | Graceful selected-window close migrated; forced/multi-process close deliberately not in core |
| Native build/publish | New `packaging/publish_native.py` builds native executable with argv-only subprocess | Existing .NET self-contained publish | Old PS entrypoint is now a small compatibility shim; source Python prerequisite made explicit |
| Windows enumeration/capture/UIA tree/privileges | Existing contract, state, bounded queries | Existing native implementations | Retained, not newly claimed migration |
| Click/double/right click/type/keys/scroll/focus | Existing session/TTL/token mapping/batch safety | Existing Win32 input and target validation | Retained safety tests; real GUI still unverified locally |
| Bounded workflows and history | Existing batch/wait-window/history plus terminal cancellation | Existing actions | Only short declarative batches, not arbitrary legacy workflow equivalence |

## Retained legacy families and next work

[Machine-readable function inventory](legacy-function-inventory.json) enumerates all 298 retained top-level PowerShell functions across the three runtime scripts, with source locations. It is a navigation inventory, not a claim every helper is an externally exposed feature. Embedded C# and helper-server dispatch remain in those files until migrated and verified.

| Legacy family | Current route | Missing before parity / next ownership |
|---|---|---|
| UIA label lookup/invoke/set-value/toggle/element IDs | Some read lookup already Python/C#; action macros stay PS | C# observation-generation-bound element references and supported patterns; Python ambiguity/policy; stale-reference tests |
| OCR search/click, OCR/UIA fusion, screenshot diffs, icon targeting | C# image OCR + Python search exists; combined workflows stay PS | Python deterministic fusion/diff and C# capture, coordinate identity, image fixture tests |
| Drag, held keys, multi-select/edit, IME clipboard workflows | PS compatibility | C# carefully scoped primitives; Python state and cleanup; real Windows IME/clipboard validation |
| CDP discovery/query/eval/type | PS compatibility, explicit mutation classification | Optional separate browser adapter; never enable arbitrary eval as a read tool |
| Long workflow/task/form/profile/recovery/recorder/watch | PS compatibility, new short core batch is not equivalent | Python declarative plan/state/log with explicit failure/stop conditions; preserved fixtures and workload parity |
| Helper daemon/autostart, process/registry/clipboard/system macros | PS compatibility | Python lifecycle/config plus scoped C# APIs; no always-on remote control or broad credentials |
| Model-assisted vision | Optional legacy provider adapter only | Host-side vision/tool call adapter, no universal-core model/account dependency |
| Installer and optional Pi elevation launcher | PS installer/launcher retained | Python packaging/setup where useful; keep normal human-controlled UAC boundary |

## Safety fixes in retained legacy code

1. `app-close` without `--force` no longer escalates a two-second wait into process termination. If an application ignores close or asks to save, it stays open and close does not report a completed kill
2. Helper shutdown no longer kills any PID read from a lock. Stale locks are discarded safely; valid helpers receive a pipe shutdown request. Even `--force` does not override missing process identity. A nonresponsive helper requires human diagnosis rather than risking another process
3. Legacy vision execution no longer evaluates a command string through `cmd.exe`. Native executable arguments are individually Windows-quoted. **`.cmd`/`.bat` provider wrappers are rejected**, including typical npm wrapper-only installations; supply a trusted native executable or keep vision in the host. This is an explicit compatibility restriction, not full provider-launch parity
4. Workflow `session` is no longer classified wholesale as read-only. Only `info`, `helper-status` and `autostart-status` are accepted in a read-only workflow. Direct install/uninstall-autostart requires explicit live mode. Persistence is not added to the new core

## What “done” means here

Done: local reviewable source patch, generic protocol path, priority process lifecycle migration, Python publishing, retained-source safety repairs and isolated regression tests. Not done: all roughly 20,000 lines of retained PS runtime sources rewritten, every legacy feature ported, Windows interactive validation, deployment, signing, new release artifacts, commits, pushes or PRs.

Next migration order: UIA action references → Python workflow/recorder state → OCR/diff/fusion → IME/input peripherals → optional CDP/provider adapters → legacy retirement only after parity evidence. Keep each legacy implementation until its replacement passes equivalent fixtures and Windows tests; do not delete features to make language counts look better.

## Stage-two additions (cumulative local patch)

| Capability | Implemented core subset | Retained / unverified |
|---|---|---|
| UIA element actions | Opaque per-observation references, exact local find, InvokePattern, writable ValuePattern, identity/ancestry/geometry guards | Toggle/selection/legacy label macros retained; actual Windows providers unverified |
| Parent-crash lifecycle | Explicit inherited parent kernel-handle watchdog, Windows worker-only cancellation, target apps never tree-killed | Windows inheritance/crash/nested-host acceptance still manual; no JobObject guarantees claimed |
| Drag | Bounded same-window left-button single-batch gesture with partial-input release | Timed/cross-window/multiselect/held-key gestures remain legacy |
| Unicode contract | UTF-16-unit budget, surrogate rejection, Korean/emoji adapter fixtures, no clipboard modification | Actual IME composition and clipboard workflows not migrated |
| Generic host workflows | Same observe/find/set-value/stale rejection tested through MCP and JSONL adapters | No live model, external MCP-client or Windows GUI test in Linux |

The earlier “next work” table describes remaining legacy parity, not a claim these
new subsets are absent. No PowerShell implementation was removed in this stage.
