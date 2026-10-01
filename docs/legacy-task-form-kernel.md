# Pure legacy task/form planning candidate

`PcuCp.LegacyTaskForm/LegacyTaskFormKernel.cs` extracts deterministic task/form
recipe and result assembly. It is outside the NativeHost wildcard compile and
is linked only by the independent `PcuCp.LegacyTaskForm.ContractTests` project.
This is a qualification candidate: original `Invoke-MacroTaskPlan` and
`Invoke-MacroFormPlan` bodies must remain until exact Windows differential and
actual retained-adapter tests qualify their replacements. No query, child
process, generated command, GUI action, or desktop API runs in the kernel.

The immutable oracle is tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`, `scripts/cucp.ps1`. That tree contains
the original task/form bodies, option readers, argv helpers, tokenizer, workflow
builder, and safety classifier. Tests never use already migrated current safety
or workflow implementations as their original reference.

## Staged contract

All operations accept JSON data. They do not accept callbacks, executable code,
prepared state to trust, or authority to run generated commands.

- `PrepareTask({rest})` returns
  `{schema:"cucp.task-plan-preparation/v1",queries:[...]}`
- `PrepareForm({rest})` returns
  `{schema:"cucp.form-plan-preparation/v1",queries:[...]}`
- Each ordered descriptor is `{kind,argv}`. `kind` is `form_plan` or `smart_plan`;
  `argv` is the original exact `-Quiet macro ... --json-only` string array.
  Nullable input Rest members normalize to empty strings before assembly,
  matching the observed original PS5.1 parameter binder
- A captured reply is `{kind,argv,exit,raw,json}`. Its kind and argv must echo
  the corresponding rebuilt descriptor exactly; exit is Int32, raw is a string,
  and json is an object or null. Capture count, kind, argv, and order must all
  match. Child nonzero exits remain data. Acquisition exceptions must propagate
  from the adapter and abort; they are never converted into ordinary replies
- `AssembleTask({rest,captured_query_results})` returns
  `cucp.task-plan-assembly/v1` with `workflow_required`, `workflow_rest`, `items`,
  `errors`, and `form_plan`. `workflow_rest` is passed unchanged to the original
  retained tokenizer/plan builder only when `workflow_required` is true. The
  kernel does not use the unqualified candidate workflow tokenizer
- `CompleteTask({rest,captured_query_results,captured_workflow_plan,elapsed_ms})`
  independently rebuilds assembly and returns the original `cucp.task-plan/v1`
  payload. `captured_workflow_plan` is an object or null; it must be null when
  no workflow query was required
- `CompleteForm({rest,captured_query_results,elapsed_ms})` independently rebuilds
  the recipe and returns the original `cucp.form-plan/v1` payload

Elapsed milliseconds are a nonnegative Int32 supplied by the acquisition
adapter. This is the only nondeterministic comparison seam. The original brief
format, JSON serialization depth (task 18, form 16), and return-code boundary
remain in the adapter initially: status `ok` returns 0, otherwise 2. The
candidate returns planning status only; it grants no live-control permission
or sensitive-action approval.

## Preserved behavior

Options retain original case-insensitive scanning, first-value precedence,
all-values order, duplicate flags, switches appearing as values, aliases, and
null/empty distinctions. Task timeout casts occur before required-input checks,
even when their values are unused. Nonpositive timeouts default to 8000/3000;
fractional spellings round to even and numeric parsing is invariant. Empty
numeric strings become zero, but whitespace-only strings throw the original
index-bound error. If the floating fallback fails, including overflow, PS5.1
retains the first integer-format failure; integer overflow retains its distinct
overflow error. These exact error strings are tested across four cultures.

Task steps preserve app/wait, pre-shortcuts, type text, form, clicks,
post-shortcuts, and verification order. All `--shortcut` values precede all
`--keys` values regardless of their argument interleaving. An empty `--type-text`
still wins over `--text`; only the first unguarded type receives `--clear`.
Unsafe or unparseable form results accumulate errors without suppressing later
click queries. Safe empty form commands are skipped; safe empty click commands
still add an empty workflow step. Embedded safety/errors and unknown plan
metadata are retained.

Form field indices advance for malformed fields and valid later fields still
query. Field values preserve everything after the first equals sign, including
empty values, further equals signs and UTF-16 length. Field typing only forwards
its original flags: OCR, precision, radius, step, and cache settings are sent
to the final send query, but not field queries. The send query follows all
fields. `command_plan` retains unsafe commands and `unsafe_steps` retains their
original index, label, route and exit. A nonzero child exit does not override a
truthy `safe_to_act`. The original form's conditional property output collapses
one-element route/command arrays to a scalar and serializes empty output as
`{}`. This transformation affects copied step/command fields; the embedded
captured plan retains its original arrays.

The linked, already-qualified `LegacyTaskPresetKernel` provides literal quoting
and JSON argv helpers. No shared helper changes are required. Captured task
commands use its `CommandHelpers` first for one-layer unwrapping, then again
for one-level flattening/`StepString`. Reusing the first call's `step` would
reverse the required original helper order for nested commands.

## Fail-closed transport limits

The new boundary rejects unknown/duplicate operation fields, a non-array rest,
rest values other than strings/null, more than 4096 arguments, and more than 262144 UTF-16
argument units. Captured collections and plans are bounded to 1048576 JSON
characters, 65536 nodes, and depth 32; case-insensitive duplicate object keys
and nonfinite numbers are rejected. Captured argv must exactly match the
prepared descriptor. Plan roots are object or null, never scalar/array.

Captured commands support JSON scalar/array argv, with the qualified helper's
depth 8, 4096 items per array and 262144 JSON character bounds. Arbitrary
PowerShell objects/custom enumerables are outside this transport. Workflow
counts support scalar JSON values convertible to Int32. These are explicit
fail-closed boundary limits, not a claim of unlimited PowerShell object parity.

## Qualification

Run the independent checks without a desktop:

```
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyTaskForm.ContractTests -c Release
python -m unittest discover -s tests/python -p test_legacy_task_form_parity.py -v
```

The current local result is 105 passing managed checks and three passing Python
source/corpus checks. The Windows PowerShell 5.1 differential is skipped on
Linux and remains required. The corpus has 367 cases covering both families,
all query/step phases, malformed input, exact order, accumulated errors,
truth conversions, nested commands, quoting/Unicode/NUL, null/empty options,
nonzero child exits, numeric boundaries, and en-US/ko-KR/tr-TR/invariant cultures.

On Windows the harness imports only selected definitions from the pinned AST.
It replaces exactly each nested acquisition function at its AST extent and
asserts no child invocation survives. Captured replies are data; no generated
command executes. The original pure tokenizer, workflow builder and safety
classifier remain the workflow oracle. It compares exact preparation,
assembly, full payloads, error strings, return codes, brief output and PS5.1
JSON presentation, retaining every error and diagnostic field. Acquisition
exception fixtures verify immediate abort without querying later steps.
The oracle also records the exact bound `[string[]] Rest`, including fixtures
with literal null members. Windows run
[36936314485, job 110617296559](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36936314485/job/110617296559)
established that all 11 null-member fixtures become empty strings at the
original `[string[]] Rest` parameter binder, before option readers run. Every
emitted descriptor argv member was a string. The kernel applies the same
normalization; capture argv validation remains string-only. The oracle asserts
the observed bound array and tests preparation from both raw nullable input
and bound input.

That first Windows checkpoint compared 725 staged results from 317 cases and
reported 26 failed assertions: empty observe-match preservation, three numeric
edge cases in four cultures, conditional form command output, and repeated
console mismatches. The corresponding repairs and 50 added boundary cases
require a new exact-commit Windows pass. No original task/form body is retired
on that failed candidate run.

After the candidate is registered and adapters are implemented,
`CUCP_TASK_FORM_TEST_HOST` enables the separate actual-adapter comparison using
the current native bridge. It imports the entire current task/form functions
and intercepts only their nested acquisition helpers. The helpers must retain
their `_InvokeTaskChildJson` and `_InvokeChildSmartPlanJson` contracts; the
independently qualified fixed stdin/bootstrap transport belongs beneath that
boundary. Child-script switch binding and transport are separate adapter
qualification requirements, not proven by captured-query fixtures.
