# Pure legacy task-preset recipes and retained query adapter

`PcuCp.LegacyTaskPreset/LegacyTaskPresetKernel.cs` separates deterministic
recipes and result assembly from the retained planner-query adapter. Independent
Windows qualification passed at `b4ee39a6d5b545c4ee477e44912717e5a87df0ed`.
The current `Invoke-MacroTaskPreset` is a 2,990-byte adapter, replacing the original
17,082-byte recipe body. It calls `task-preset-prepare` and `task-preset-complete`
through the existing native stdin bridge. The adapter and operation integration
still require the full current-function differential before this change is
considered qualified for release.

The immutable reference is tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048` (published baseline commit
`9ffa354b9904235835a7bc6eb78ed8d3d76317c8`), `scripts/cucp.ps1`:
`Invoke-MacroTaskPreset`, its nested recipe helpers, `_TaskPlan-QuoteToken`,
`_TaskPlan-StepString`, `_TaskPlan-UnwrapCommand`, and the three option readers.
`Invoke-MacroTaskPreset` is 17,082 UTF-8 bytes (291 lines including the following separator); it is **not entirely
pure** because document/mail invoke a child task-plan process. That query remains
in the PowerShell adapter until a separately qualified replacement exists.

## Contract

`PreparePreset({rest: string[]})` reconstructs the original six preset families
and aliases, preserving the original alias in `kind`:

- document
- mail
- form / form-submit
- upload / file-upload
- download / file-download
- settings / app-settings

It returns `cucp.task-preset-preparation/v1` with `kind`, `mode`, `queries`,
`workflow_steps`, `extra_commands`, and `notes`. `queries` contains exactly one
ordered descriptor:

- task mode: `{kind: "task_plan", argv: ["-Quiet", "macro", "task-plan", ...,
  "--json-only"], rest: null}`
- workflow mode: `{kind: "workflow_plan", argv: null, rest: ["--name", ...,
  "--step", ...]}`

These arrays are data. The kernel does not invoke them, parse them as a language,
look up windows, read paths, contact services, or use the candidate workflow lexer.
The retained adapter alone obtains the corresponding planning result.

`CompletePreset({rest, captured_query_result, elapsed_ms})` independently rebuilds
the same recipe; it does not trust caller-supplied prepared argv or metadata.

- task capture: `{exit: Int32, raw: string, json: object | null}`
- workflow capture: `{workflow_plan: object | null}`
- elapsed time: a nonnegative Int32 in milliseconds

The return value is the original `cucp.task-preset/v1` payload. Task mode retains
its absence of a `mode` field. Workflow mode retains elapsed time zero and all
original null fields. Captured plan objects, accumulated errors, and safety data
are retained without filtering. The original status rule depends on
`safe_to_run`, independently of child exit code. A true status is only a planning
status; it grants no input authority or sensitive-action approval.

The wrapper retains original brief/JSON formatting and derives exit code 0 for
`status == "ok"`, otherwise 2. Stopwatch measurement remains around the task
query only. The adapter validates the preparation schema, single-query count,
mode, argv types, and exact `-Quiet macro task-plan ... --json-only` prefix/suffix
before obtaining the task result. Workflow mode only calls `_Build-WorkflowPlan`.
The opt-in `PreserveInvalidArguments` bridge switch preserves original native
argument-error text; it never changes an error into success. Query errors
propagate before completion.

Strict transport validation rejects unknown/duplicate fields, non-string rest
items, more than 4096 rest items or 262144 UTF-16 input units, a captured result
over 1048576 JSON characters, scalar/array plan roots, and invalid timing/exit
types. The old internal function had no such transport contract. These are
explicit fail-closed boundary limits; do not describe them as unlimited legacy
behavior. JSON objects are the supported task/workflow plan shape.

## Preserved recipe details

Options are read in the original case-insensitive order, including first-value
wins, all-values scanning, switches appearing as values, and empty-value rules.
Duplicate forwarded flags are intentionally retained. Only the original specific
flags are forwarded; no new live or sensitive confirmation is added. Document
replacement/save shortcuts, mail CDP defaults, form dry-run extras, upload dialog
sequence, optional download verification, settings field parsing and click order
all have fixture coverage.

Literal step quoting retains the original allowed-character regex, doubled
apostrophes, and empty-string representation. Generated strings are not executed.
The JSON-only `CommandHelpers` test seam covers original one-level argv
flattening and one-layer command unwrapping for scalar/array fixture data, with
bounded depth/count/size. Preset recipes only construct strings. This seam does
not claim compatibility with arbitrary PowerShell objects or custom IEnumerable
implementations and is not a production operation.

## Qualification

Run the independent managed checks (no desktop or child queries):

```
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyTaskPreset.ContractTests -c Release
python -m unittest discover -s tests/python -p test_legacy_task_preset_parity.py -v
```

On Windows, the Python suite imports only selected definitions from the pinned
PowerShell 5.1 AST. It replaces exactly the nested `_PresetInvokeJson` definition
with a recorded-argv/captured-result stub and asserts no child-process call
remains in that function. Workflow mode uses the original pure parser, policy,
and plan builder, or an explicit captured-result fixture. Console JSON is
captured directly; the original script entry point and generated commands never
run. Only nondeterministic stopwatch time is supplied through the elapsed-time
seam. Original exception messages, preparation data, and complete payloads are
compared exactly, without dropping errors or diagnostic text.

The corpus currently has 285 preset cases plus 28 helper cases. It covers every family/alias, option precedence and forwarding,
malformed required arguments/settings fields, special quoting, Unicode/NUL,
empty/null/nested argv helpers, successful and partial captured plans, absent
JSON with raw diagnostics, nonzero child exits, and retained safety/error data.
At [Windows run 36901958763, job 110503026946](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36901958763/job/110503026946),
86 managed checks, 538 exact preparation/payload comparisons from 277 preset
cases, and 28 exact helper comparisons passed without skips. That run predates
the retained-adapter replacement. The job subsequently failed in the separate
image suite; it was not a complete green Windows job.

With `CUCP_NATIVE_TEST_HOST` set, the suite additionally imports the entire current
`Invoke-MacroTaskPreset`, current bridge, and current workflow adapter. Only the
nested task-planning acquisition is intercepted. All 285 cases compare exact
payloads, preparation/query data, captured errors, and return codes against the
pinned original. Another 16 cases check brief output and `--json-only` precedence
across successful/partial task and workflow plans. Only stopwatch time is supplied
through the explicit deterministic seam. Keep this actual-adapter gate enabled
in Windows CI; local Linux checks cannot establish it.


## Actual Windows child-argument repair

Run `36908857566` reproduced the original flaw: a data value `-AllowLiveControl` became a script switch. It also proved that adding `--` to native `powershell -File` does not fix this boundary. The adapter now uses a fixed, encoded bootstrap with no interpolated user code; script path and argv travel as bounded JSON on stdin, and the bootstrap invokes the same script with fixed `-Quiet` and a named `[string[]]` `-CucpArgs` value. Both streams are drained, the original planning exit is captured, and an unfinished owned child is cleaned up. The regression keeps the original live=True reproduction and requires exact argv plus live=False/brief=False for every repaired case. The adapter harness imports only currently retained functions; it no longer requests the retired truncation helper. These repairs require a new exact-commit Windows pass.
