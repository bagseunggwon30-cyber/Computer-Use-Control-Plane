# Legacy execution coordination

The coordination bodies of `workflow-run`, `task-run`, `form-run`, `smart-click`,
`watch`, `recovery-plan`, and `recovery-run` now run in C#. Their seven public
PowerShell functions in `scripts/cucp.ps1` are thin wrappers around the qualified
streaming adapter. The duplicate execution adapter fixture has been removed,
and the migration manifest selects the production definitions for qualification.

The kernel and exact retained adapter passed the Windows gate at
`e9e015c6bc7b39d52999dccccf6bb4316a6c8dfe`,
[run 37007340738, execution job 110838651590](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738/job/110838651590):
370 execution contracts, 56 startup contracts, all 35 Python tests, and both
462-case differentials. The source-map artifact matched six file hashes and 382
function extents. The 19 promoted execution wrapper/helper extents were then
verified unchanged and unique in the production source.

The integrated commit still requires its bundled full regression, including
actual-adapter checks against `scripts/cucp.ps1`. The earlier candidate pass is
not a substitute for that gate. Windows acquisition/input and temporary
PowerShell child execution remain; this architecture does not complete the
zero-PowerShell migration or its interactive Windows qualification.

## State and effects

`LegacyExecutionCoordinator` retains the current run in one process. A synchronous
`ILegacyExecutionEffects` callback separates workflow planning, child invocation,
native acquisition/input, local macros, CDP port probes, history, trajectory,
sleep, clocks, timestamps, owned capture paths/cleanup, Console lines and Escape.
The coordinator has no process, filesystem, network, desktop or shell API. Its
closed effect enum does not accept arbitrary callable names or code.

`LegacyExecutionSession` connects the callback to the dedicated NativeHost
`legacy-execution-session` entry. The twelve retained private adapter functions
in `scripts/cucp.ps1` validate descriptors, dispatch closed effects, and own process
startup, streams and cleanup. The separate `_Execution-SendEscape` helper is an
explicit input seam that the actual qualification replaces with a captured effect.

Existing dependencies remain: `_Build-WorkflowPlan` and its compatible tokenizer,
`Invoke-NativeHelper`, `Invoke-MacroClickPoint`, `Invoke-MacroIconFind`,
`Test-CdpPortQuick`, history and trajectory helpers, fixed clock/sleep operations,
and owned screenshot paths. These effect implementations are later migration
work; the retired coordination bodies are not copied into another runtime file.

Report state is retained once, including 256 steps and six attempts per step.
Previous replies are never retransmitted. The session accumulates its current
incoming reply and final report in memory; it does not claim constant-memory
report assembly.

## Immutable authority and typed children

`LegacyExecutionAuthority` is immutable constructor context. Plans, captured
commands and effect replies cannot grant live input or sensitive confirmation.
The coordinator and retained adapter independently enforce the startup ceilings.

Only the NativeHost process switches `--allow-live-control` and
`--confirm-sensitive` establish upper bounds. Sensitive permission also requires
an arity-aware standalone flag in the original invocation. `LegacyExecutionConsent`
skips known option values, so text or a label spelling `--confirm-sensitive` is
not consent. The top-level macro gate uses the same pure check.

Each child descriptor separates `argv`, `live`, `quiet`, `brief`, and
`confirm_sensitive`. Strings such as `-AllowLiveControl`, `-Brief` and `-CucpArgs`
remain data in a named `-CucpArgs ([string[]]$request.argv)` parameter. Trusted
switches are bound separately. Native `powershell -File ... @userArgv` is not used,
and the read-only planning helper has not been widened into an actuator transport.

Before launch, the child adapter requires the exact support marker
`cucp.execution-sensitive-ceiling/v1` in the child switch reader. Its fixed
bootstrap installs constant Boolean `CUCP_EXECUTION_SENSITIVE_CEILING`, intersecting
parent permission with this effect's sensitive grant. The reader rejects a false,
non-Boolean or mutable present ceiling; an old child without support is refused.
Absent ceilings preserve existing direct calls. No failure triggers an automatic
child retry.

## Startup and streaming protocol

The host reads strict UTF-8 directly from standard input, independently of the
Windows console code page. Original arguments, operation, formatting options,
cache duration, provider availability and culture arrive through id-zero startup
chunks. Effects begin at id one; each reply is bound to the outstanding sequence.

Each decoded chunk is at most 48 KiB, each line at most 66,000 characters, and the
startup request at most 32 MiB. Exactly one initial UTF-8 BOM is accepted;
repeated, embedded or later-frame BOMs and malformed UTF-8 are rejected. Duplicate
or unknown keys, wrong types, forged authority fields and duplicate process
switches fail before any effect.

The confirmation preflight uses the closed `legacy-execution-confirmation` entry
with a 32 MiB bound and only the `execution-confirmation` operation. Ordinary pure
compatibility calls retain their 1 MiB budget. Actual Windows wrapper tests cover
Unicode arguments beyond 1 MiB and distinguish literal option values from a
standalone consent flag.

Effect requests, replies and terminal reports use base64 JSONL `part`/`end` frames.
The chunk limit requires splitting the same value, not truncating results. There
is no growing transcript frame, aggregate report cap or new workflow step cap.
Wrong IDs, malformed tags, unexpected fields or disconnection terminate the
session without replaying an effect.

Runtime values have explicit `scalar`, `array` and `object` tags. Object members
are named pairs; arrays are item lists. The PowerShell decoder returns true arrays
using unary-comma preservation, avoiding PS5 pipeline decorations during Console
serialization. Genuine `{value, Count}` objects remain objects. No shape-based
unwrapping is permitted.

## Preserved behavior and uncertainty

- Workflow gates run before execution. Dry runs, plan safety, live permission,
  sensitive confirmation, observations, labels, numeric coercion and option
  aliases preserve their original ordering
- Five requested retries allow six attempts. Live retries require
  `--retry-live-steps`; partial attempts and first-failure guidance remain visible
- Task and form planning retain their distinct validation, child options, report
  shapes and trajectory placement. Direct report arrays preserve missing values
  as `[null]`, while a singleton-null task command is blocked before execution
- SmartClick retains CDP, UIA, precision points, coordinate fallback, icon, fusion,
  OCR and optional vision stages, including history hints, low-confidence stops,
  label/screen verification, explicit screen retries and historical early returns
- Watch emits each brief observation before its captured sleep. Recovery planning
  never executes a recommendation; Escape requires both startup gates

Explicit `mutation_may_have_occurred: true` stops SmartClick before fallback or
success-history writes, even if a reply otherwise reports success. Workflow
records the uncertain attempt and skips retries and later steps; form and task
remain partial. The original CDP fallthrough defect is characterized separately
from ordinary exact-parity cases.

A live effect exception with no trustworthy pre-dispatch failure proof receives
conservative uncertainty metadata. A failed observation after prior live dispatch
is also terminal and cannot enter a legacy read fallback. Lost or malformed
reply streams preserve `mutation_may_have_occurred: true` and
`automatic_retry: false`; the adapter maintains its own dispatch record so abrupt
host exit cannot erase that warning. Ordinary captured failures before live
dispatch retain exact original behavior.

## Qualification and remaining gates

The oracle is the original `scripts/cucp.ps1` blob in Git tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`. Windows tests load selected AST definitions
from Git history and replace every child, input, native, sleep, clock, file and
persistence seam before invocation. They compare complete unformatted objects,
exact Console output, effects and their order, errors and exits. Ordered-dictionary
recovery reports are captured before formatting and are required explicitly.
No authenticated model or live desktop input is used.

All 462 actual-adapter cases remain, including 32 reached exact non-live failures,
six unreached injected failures, and 16 deliberate post-dispatch uncertainty
cases. The unchanged exact-equality path covers 446 cases. Independent contracts
cover typed inert children, immutable ceilings, true-array roundtrips, malformed
streams and the 256-step/six-attempt report exceeding 1 MiB.

`CUCP_EXECUTION_TEST_HOST` selects the matching NativeHost for actual tests.
Diagnostic, codec and Escape-seam readers select an explicit
`CUCP_EXECUTION_ADAPTER_SOURCE` override or the manifest-enabled production source.
Tests rebuild the contract assembly once per process to avoid stale DLL evidence.

Optional `CUCP_EXECUTION_DIAGNOSTICS=1` emits at most four bounded protocol-failure
records: phase, expected ID, first 16 codepoints/256 characters of the last frame,
process exit state, and at most 1,024 stderr characters. It is unset in ordinary
runs and never replaces the original exception or changes protocol decisions.
Complete qualification logs and read-only parser source maps are downloadable CI
artifacts; displayed diffs are bounded without dropping assertions.

The next required evidence is the integrated full gate. The final zero-PowerShell
release additionally needs Python/C# replacements for retained effects and child
entry points, reviewed frozen oracle fixtures, and testing with PowerShell absent.
