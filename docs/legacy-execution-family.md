# Legacy execution coordination candidate

The first published combined gate (`120b64a605bece965da4637e6510afcbd46fe871`,
Actions run `36997186053`) reached terminal failure in the execution Windows job.
The job-log connector repeatedly returned `Transport closed`, and the run had no
downloadable artifacts. This is not parity qualification. The next gate retains
every comparison and includes bounded fixture diagnostics: the adapter can emit
up to four protocol-failure records when `CUCP_EXECUTION_DIAGNOSTICS=1`, containing
phase/expected ID, the first 16 codepoints and 256 characters of the last frame,
process exit state, and at most 1,024 stderr characters. Normal execution leaves
that diagnostic option unset. The harness reports a compact first difference and
bounds only displayed unittest diffs; it does not remove cases or assertions.
A separate inert Windows child characterizes the .NET Framework redirected-input
writer's initial UTF-8 BOM, even when the subsequent explicit writer uses no BOM.

The next published gate (`a7bffa18b8325fe06f00459324c1f3631f2c896a`, run
`37000162419`) made the complete execution log downloadable. The 359 execution
contracts, 52 startup contracts, typed-child/ceiling tests, byte characterization,
and uncertainty tests passed. All actual-adapter cases stopped before any effect
because startup used the inherited Windows console decoder; the central entry
now has a separate strict UTF-8 reader fix awaiting qualification. Four pure
oracle mismatches identified two specific report/command behaviors: missing
task/form error properties must appear as `[null]` in direct report arrays, and a
singleton-null task command must stop as `missing_recommended_command` without a
second child or trajectory write. The candidate fixes these with 11 added
contracts while leaving every differential assertion intact. The actual harness
also captures a dedicated Escape helper before testing recovery execution; no
fixture can reach `SendKeys` through the retained dispatch body.

The execution family migrates the coordination bodies of `workflow-run`,
`task-run`, `form-run`, `smart-click`, `watch`, `recovery-plan`, and `recovery-run`
as one qualification unit. The oracle is the original `scripts/cucp.ps1` blob in
Git tree `bf895d3120dd5e145f360cb1c41e1d79a061d048`. The original implementations
remain in production until the Windows candidate and actual-adapter gates pass.
This candidate is not an interactive Windows qualification or a completed
zero-PowerShell migration.

## State and effects

`LegacyExecutionCoordinator` holds the current run in one process. A synchronous
`ILegacyExecutionEffects` callback separates planning, child invocation, native
acquisition/input, local macro calls, port probes, history, trajectory, sleep,
clocks, timestamps, owned capture paths/cleanup, console lines, and Escape input.
The coordinator itself has no process, filesystem, network, desktop, or shell API.
The closed effect enum does not accept arbitrary callable names or code.

`LegacyExecutionAuthority` is immutable constructor context. A plan or effect
reply cannot alter it. Live descriptors are checked against that context before
calling the effect adapter. Sensitive confirmation requires a standalone original flag
and trusted startup confirmation. `LegacyExecutionConsent` skips known option
values when deriving that flag; a label/text value equal to the flag is not consent. Adapters must independently enforce both
ceilings; classifier or plan booleans are never authority.

Each child descriptor has separate `argv`, `live`, `quiet`, `brief`, and
`confirm_sensitive` fields. User strings such as `-AllowLiveControl`, `-Brief`,
`-CucpArgs`, or `--confirm-sensitive` remain data in the named argument array.
The temporary legacy adapter must bind `-CucpArgs ([string[]]$request.argv)`
in-process and pass trusted switches separately. Native `powershell -File ...
@argv` is expressly forbidden for this transport. The child bootstrap requires support marker `cucp.execution-sensitive-ceiling/v1`
and installs constant Boolean `CUCP_EXECUTION_SENSITIVE_CEILING`. The common switch
reader rejects sensitive confirmation under a false, malformed, or mutable ceiling.
The existing read-only planner
transport stays read-only and is not reused for actuator descriptors.

Report state is retained once, locally, including all 256 steps and six attempts
per step. No previous replies are retransmitted. `LegacyExecutionSession` offers
an optional streaming callback adapter for a dedicated NativeHost
`legacy-execution-session` mode. It is not part of the per-call pure compatibility
registry. The host supplies operation, initial argv, authority, render mode,
cache duration, and provider availability before entering the session.

Each session effect/report is split into 48 KiB UTF-8 chunks represented as
base64 JSONL `part` frames and an `end` frame. Replies use the outstanding sequence
ID and the same chunk scheme. Wrong IDs, duplicate fields, unknown fields,
malformed tagged values, disconnection, or oversized individual chunks fail the
session without retrying an effect. There is no aggregate transcript limit or
new workflow cap. A chunk limit requires splitting the same payload, not dropping
results. The session currently accumulates one incoming reply and the final
report in memory; it does not claim constant-memory report assembly.

Runtime arrays use explicit `scalar`, `array`, and `object` wire tags. Objects
carry named property pairs and arrays carry item lists. An ordinary
`{"value": [...], "Count": 1}` object remains an object. No shape-based
unwrapping is permitted. The full report object and original depth-limited
Console serialization remain separate assertions.

## Preserved behavior

- Workflow gating precedes execution, including dry-run, plan safety, live
  authority, and sensitive confirmation; verification windows/labels and option
  aliases retain their original order and numeric coercion
- At most five requested retries yield at most six attempts; live retries require
  `--retry-live-steps`; failed command/verification reports remain partial,
  with exact attempt records and first-failure guidance
- Task planning, chosen dry-run/recommended commands, propagation of run options,
  child status mapping, and trajectory placement remain distinct from form runs
- Form command validation, independent safety classification, per-step blocking,
  continuation, and original lack of implicit input retry are retained
- SmartClick retains CDP, UIA invoke, precision points, coordinate fallback, icon,
  fusion, OCR, and optional vision stages; history hints, low-confidence stopping,
  label verification, explicit screen-change retries, early-return cleanup and
  history behavior are preserved, including historical quirks
- Watch retains each observation and emits brief cycle output before its sleep
- Recovery planning never executes a recommended command; recovery execution
  allows only the closed Escape effect after both required startup gates

The candidate preserves explicit original fallbacks and explicit retry options.
It does not add automatic retries after failed/disconnected effect transports.
Callback exceptions that the original catches remain catchable effect failures;
protocol/authority failures cannot be swallowed into a fallback.

## Qualification

`PcuCp.LegacyExecution.ContractTests --self-test` exercises the whole family and
tagged streaming boundary without a live executor. Python portable checks cover
462 captured fixtures, control-like argument data, unchanged runtime object
shape, and a 256-step/six-attempt workflow whose report exceeds the former 1 MiB
compatibility bridge.

On Windows, `test_legacy_execution_parity.py` loads only selected AST definitions
from the pinned Git blob and replaces every executable, input, sleep, clock,
file, native, and persistence effect before invoking them. It compares the full
unformatted object, exact effect order and descriptors, exceptions, exits, and
original Console output. Timing is fixed at the effect boundary. The original
function source is read from history at test time, not copied into runtime files.
All inputs and replies are inert fixtures. No authenticated model or live desktop
input is used.

The actual temporary PowerShell adapter requires separate qualification using
`CUCP_EXECUTION_TEST_HOST`. It is not enabled by a pure-candidate pass. A final
zero-PowerShell release will replace the temporary effect implementation with
Python/C# and freeze reviewed oracle fixtures, then test with PowerShell absent.

## Integrated startup contract (awaiting actual-adapter gate)

`legacy-execution-session` is a separate NativeHost entry. Only its fixed process
switches `--allow-live-control` and `--confirm-sensitive` establish upper bounds.
Original arguments, operation, formatting flags and culture arrive through id-zero
startup chunks, followed by the effect stream beginning at id one. Replies cannot
change startup authority. Sensitive permission also requires an arity-aware
standalone flag in original arguments; a label or text value spelling that flag
does not grant consent. The direct macro safety gate uses the same pure check.

Each startup chunk is at most 48 KiB, each line at most 66,000 characters, and the
startup request at most 32 MiB. This limit is independent of the accumulated report
and permits the tested request larger than 1 MiB. Schema keys are exact and unique;
unknown operations, forged authority fields, implicit boolean conversion and
duplicate process switches fail before any effect. Forty-six portable startup
checks pass. Windows inert-child/top-level gate checks are release requirements;
the production body replacements remain pending the joint batch gate.

## Uncertain mutation correction and retained adapter

The new native/CDP boundary can report `mutation_may_have_occurred: true` inside
its captured JSON. SmartClick now stops immediately with a partial outcome when
that metadata is present, including an otherwise successful status/exit. It does
not try UIA/OCR fallback or append success history. Workflow records the uncertain
attempt, skips requested retries and later steps, and explains the uncertainty in
its failure summary; form and task results remain partial. The separate original
characterization test demonstrates the old CDP-to-UIA fallthrough rather than
changing its expected result. Ordinary captured failures retain strict original
parity assertions.

A live effect exception whose adapter cannot establish a pre-dispatch failure
uses the same conservative uncertainty metadata. A malformed protocol or broken
session is still a terminal transport error, never an action retry. The adapter
marks its own live effect failures conservatively; captured fixtures can identify
known pre-dispatch exceptions separately.

The retained-adapter candidate now has complete closed dispatch, strict descriptor
validation, process startup/lifetime management, owned screenshot paths, no-BOM
chunked stdin, and seven thin public wrappers. Child sensitive authority is the
intersection of the original invocation ceiling and that particular typed effect's
sensitive grant. Old children lacking the exact ceiling support marker are refused
before launch. Direct SmartClick script calls use a distinct child mode so their
Console output remains observable before the final SmartClick result.

Actual-adapter tests run the real chunked session, descriptor validation, dispatcher,
wrappers and Console formatter against captured native/helper/history effects. A
separate disposable child fixture exercises the actual named-argv bootstrap. No
Windows interactive input is used by either qualification. The complete temporary
adapter remains an external integration draft until these gates pass; it is not a
new hidden runtime dependency or a claim that PowerShell has been retired.

Session-level transport loss is independently covered: once a live effect has
been sent, a closed reply stream, wrong sequence, or malformed JSON produces a
terminal error with `mutation_may_have_occurred: true` and
`automatic_retry: false`. The retained adapter also keeps its own live-dispatch
record, so an abrupt host exit or malformed host frame cannot lose that warning.
The three disposable-process regression variants verify only one live effect
was sent. This evidence is separate from successful parsing of a child's result.

The effect-reply reader also bounds each line before JSON allocation and rejects
non-numeric sequence identifiers before conversion. Any reply or result assembly
exception after a live dispatch remains an execution-phase uncertain outcome; it
cannot fall through as a startup refusal. Portable process tests cover EOF, wrong
sequence, string sequence, malformed JSON and an oversized line after one live
effect, and assert that no second live effect is sent. The test runner rebuilds
its contract assembly once per process so an old DLL cannot mask source edits.

The actual-session differential now runs every one of the 462 fixtures, including
all 54 fixtures containing injected exceptions. Failure classification comes from
the original captured effect identity and its dispatch prefix, not from startup
live permission or the presence of a `throw` field alone. The portable capture
partition contains 32 failures before any live dispatch and six injected failures
that are never reached; all 38 retain complete exact original comparisons. The
remaining 14 failures at live effects and two read failures after a live dispatch
have explicit uncertainty assertions, exact trace-prefix and consumption checks,
and no subsequent action; only partial-result trajectory recording may follow.
Together with the 408 ordinary cases, that is 446 exact comparisons and 16
intentional safety-correction comparisons. The independent original-kernel oracle
assertions remain unchanged.
