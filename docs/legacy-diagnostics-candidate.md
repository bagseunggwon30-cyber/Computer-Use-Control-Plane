# Diagnostic and reporting assembly candidate

Current staged source routes all nine diagnostic delegates through the managed
adapter. Audit body retirement is qualified at `3cbbaaad` / required core run
`37103102449`, attempt 2, with all 258 audit production/direct pairs exact.
Benchmark production-entry and full-regression acceptance remain pending; see
[benchmark staging](benchmark-staged-cutover.md). PowerShell wrappers and effect
acquisition remain.

## Previous seven-delegate checkpoint (historical)

The C# implementation covers nine report/orchestration bodies in
`PcuCp.LegacyDiagnostics/LegacyDiagnosticCoordinator`. Seven qualified bodies now
use public delegates in the main wrapper and the closed diagnostic support
module. Benchmark and audit-summary retain their original production bodies:
their unusual JSON conversion behavior is not fully matched. The integrated
production and full-regression gate is pending. PowerShell remains required.

The accepted-source tree is `c0d15371b60ebf62be45bfa68b90282405f07273`, reachable
from remote commit `56be343c786027d27fa3dcb71732157caffc8de0`. The older baseline
`bf895d3120dd5e145f360cb1c41e1d79a061d048` is historical provenance; the benchmark
candidate intentionally retains the accepted correction that requires every
sample to succeed before an SLO passes and includes `failure_count`. Using the
old timing-only SLO result would reintroduce that corrected defect.

## Exact function-body footprint

| Function | UTF-8 bytes |
| --- | ---: |
| Invoke-MacroPerf | 10,249 |
| Invoke-MacroDiagnoseLag | 9,513 |
| Invoke-MacroHealthQuick | 4,713 |
| Invoke-MacroHealthDetail | 3,146 |
| Invoke-MacroLogTail | 6,862 |
| Invoke-MacroBenchmark | 5,389 |
| Invoke-MacroSelfTest | 7,094 |
| Invoke-MacroAuditSummary | 2,728 |
| Invoke-MacroReleaseNotes | 4,359 |
| Total | 54,053 |

These are normalized exact AST function bodies, excluding separators. The
accepted parser source map independently confirms the total. The Python gate
pins each body's SHA-256 and byte count. The seven-body cutover removes 44,965
bytes from the main wrapper, including its new module import; fixture and adapter
PowerShell remain counted source. Cleanup is excluded: its deletion/process
policy is not a read-only acquisition boundary and needs separate qualification.

## Typed effects and retained state

`ILegacyDiagnosticEffects` supplies one closed `LegacyDiagnosticEffect` at a time.
The C# coordinator retains sampling lists, grouped processes, parsed events and
reports in process. It does not call shell, desktop, filesystem, process, registry,
network or authenticated model APIs. Captured replies are never accumulated into
an expanding request transcript. `LegacyDiagnosticExecutionAdapter` maps each
request through the existing `ILegacyExecutionEffects` and qualified tagged
session transport:

- Kind: `Diagnostic`
- Name: exact `LegacyDiagnosticEffectKind` enum name
- Argv: the original typed argument array for the fixed read-only target, else empty
- Data: `{name: <fixed suboperation>, value: <effect-specific data>}`

There is no second process bridge or new chunk/framing implementation. The
new PowerShell adapter contains only closed acquisition/validation hooks and
uses `_Invoke-LegacyExecutionHost` for its process and frame lifecycle. Shared
`LegacyExecutionWire` preserves true arrays and ordinary `{value,Count}` objects.
The trusted host can use its new session factory to construct this coordinator;
the dedicated diagnostic startup schema is independently validated by the
host. The two unqualified conversion-heavy public macros continue to use their
original bodies rather than this candidate route.

## Production integration evidence

At `7fb6c2f68688ef3b414e2edc00a40d700ac15ea2`, [run 37054089596](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37054089596)
passed all 323 candidate and 323 actual-adapter cases plus 196 guards, with no
Windows skips. The adapter partition was 279 exact rows, 34 current owned-write
uncertainty outcomes and ten terminal postdispatch failures. Fourteen managed
checks and 37 independent boundary assertions also passed.

The current integration preserves the seven original public signatures, uses
verified source hashes and AST extents, and keeps benchmark/audit-summary bytes
unchanged. Manifest-selected tests now load current main's public functions.
The retained two still use their existing acquisition seams and require exact
equality; only the seven session-backed routes use the established uncertainty
partition. Fourteen inert delegate probes and the disposable whole-script
startup tests are additional pending acceptance gates. No real desktop input,
model, clipboard or IME validation is implied.

| Diagnostic enum | Suboperation / value | Captured reply |
| --- | --- | --- |
| Clock | start, stop, elapsed / fixed scope | numeric milliseconds; benchmark stops use integer ElapsedMilliseconds, other scopes use PS integer rounding of TotalMilliseconds |
| Timestamp | o / null | original round-trip date string |
| NodeVersion | empty / null | `{exit,output}` with untrimmed output |
| Cli | empty / null; fixed argv | `{exit,json}` |
| Native | empty / null; `-Action` and windows, health, focused or modal-detect | `{exit,json}` |
| Macro | metrics, health-quick, windows or find-label / null; fixed argv | original pipeline return value; Console suppressed by acquisition |
| FileExists, FileStat | empty / requested path | Boolean or `{length}` |
| ListFiles | empty / `{path,recurse,filter,file}` | metadata array `{full_name,length,last_write_time}` |
| ReadLines | empty / path | string array; audit uses UTF-8 and silent per-file read, release uses original default encoding/error behavior |
| ReadText | empty / requested baseline path | raw baseline JSON text |
| ResolvePath | empty / immutable changelog path | resolved path string or null |
| TailBytes | empty / `{path,max_bytes}` | `{total_bytes,tail_bytes,text}` after one bounded read; tail_bytes is allocation/request length, not bytes actually returned |
| Processes | empty / null | stable identity rows `{id,name}`; two lists of native Process objects stay in host state |
| ProcessMetrics | empty / `{current_ordinal,previous_ordinal}` | per-process `{private_bytes,started_at,current_cpu_ms,previous_cpu_ms,priority}`; each inaccessible getter group omitted independently |
| ProcessorCount | empty / null | processor count |
| Windows | empty / null | captured Win32 window rows |
| Sleep | empty / requested sample ms | ignored |
| EnsureWin32, EnsureUia, HelperUp | empty / null | original truth value |
| FindCodex | empty / null | original path or null; empty string is still non-null |
| AssertAuthorized | empty / null; one of two fixed self-test argument arrays | completed Boolean blocked; the host catches the original policy assertion, never invokes input |
| Appshot | empty / `{match,semantic,no_cache,cache_max_seconds}` | original captured self-test appshot value |
| CacheKey | empty / selftest-cache | key string |
| Uia | empty / `{focused_window:"",max_elements:50}` | captured fallback affordances |
| Notice | INFO / original self-test notice | ignored |
| AuditProbe | .health-quick-probe- or .health-probe- / immutable audit directory | success or captured exception |
| ClearAppshotCache | appshot-*.json / immutable cache directory | success or captured exception |

The two owned maintenance capabilities have distinct immutable ceilings:
`AuditProbe` is valid only for the quick/detail health operation and configured
audit directory; `ClearAppshotCache` is valid only for perf with the original
`--include-live-ish` flag and configured cache directory. The host must check
these ceilings independently, generate its own unique owned probe name, avoid
following reparse points outside the owned directory and never accept a broad
write/remove primitive. The self-test's pre-existing appshot cache behavior must
also remain constrained to its configured cache; it is captured, not performed,
in this suite. No diagnostic reply can grant permission to terminate processes,
modify priorities, register autostart or perform live desktop input.

Acquisition failures use `LegacyDiagnosticEffectException` and follow their
original local catch behavior. Protocol failures remain terminal. An execution
reply explicitly reporting mutation uncertainty becomes a terminal protocol
error without retry; no owned write is replayed to recover a lost result.

The shared session's trusted mutation classification must include diagnostic
`AuditProbe`, `ClearAppshotCache`, every `Appshot` (a warm cache read can miss),
`Notice`, and every `Native`/`Cli` call. The retained native/CLI wrappers write
owned log/capture files even for read-only provider operations. It must also
include `Macro` suboperations `health-quick` and `find-label`, which can create
owned probe/cache/capture artifacts. `HelperUp` and only `Macro windows` with
exact argv `["--rich"]` also invoke the retained CLI. `AssertAuthorized` logs a
notice; its original catch-any rejection is represented as a completed Boolean
blocked reply, so an expected policy rejection is not an uncertain error envelope.
A lost reply after that dispatch remains uncertain. This is
separate from desktop-live permission. Pre-dispatch validation/serialization is
known-unmodified; a lost or malformed reply, terminal assembly failure or stream
failure after dispatch is uncertain and must retain `automatic_retry:false`.
An explicit, trustworthy proof that a request did not dispatch can retain the
original caught acquisition-failure behavior. The host owns this classification;
request/reply data cannot supply a permission or clear a recorded dispatch.
A caught read-only acquisition failure after an acknowledged owned write keeps
its original fallback behavior. Cumulative prior owned dispatch matters for an
uncaught terminal/assembly/transport failure; the currently failing owned write
is itself uncertain and stops immediately.

## Compatibility decisions

- Option lookup is first occurrence, case insensitive; switch lookup retains the
  legacy all-arguments behavior. Integer conversion reuses the existing kernel
- Perf's cold and warm targets both run N iterations, despite the old comment
  claiming a single iteration. Clearing occurs once, before the pair
- Benchmark uses nearest-rank p50/p95 over successful samples, banker-rounded
  average, inclusive SLO boundaries and the accepted all-samples-success rule
- Perf's large warning threshold is multiplied with promotion and converted using
  the legacy Int32 compatibility path at the nested FailMs binding boundary,
  after every sample. Three finite boundary cases retain exact error comparison
- Lag uses T0, sleep, T1, then date/CPU acquisition; negative CPU deltas clamp to
  zero and CPU percentage uses requested sampling time, not measured elapsed
- Native memory/start/current CPU/previous CPU/priority getters run only after
  sleep, timestamp and processor-count acquisition, in original grouped process
  order. Strict ordinal references select only the two retained process lists;
  there is no PID reopen. Independent getter failures preserve other fields.
  Singleton PID lists preserve the original scalar shape. Original wall-clock
  DateTime age subtraction is retained across explicit offsets/DST, rather than
  normalizing the two offsets. Retained Process objects are disposed best-effort
  in the family wrapper finally block, without replacing an original outcome
- Lag cache/log statistics retain their original nesting under temp-root existence;
  recent timeout tail acquisition remains independent
- Health pressure and timeout failures are advisory. Optional detail components
  produce `ok_partial_optional` while required failures produce exit 1
- Self-test strict mode can fail with zero failed tests because skipped tests are
  disallowed. Its legacy `@($null)` UIA count is retained
- Log-tail takes the last N lines before errors-only filtering, drops an initial
  truncated line, counts redactions per matching pattern/line, and preserves
  case-sensitive error filtering and exact regex precedence
- Audit processes up to 20 most-recent trajectory files, tolerates malformed lines,
  retains unknown timestamps, and aggregates macro/exit keys case insensitively
- Release version selection preserves the original numeric weighting and inclusive
  since filter. Its bounded secret patterns and heading/bullet quirks are retained
- Self-test, benchmark and release-notes ignore `--json-only` when Brief is enabled,
  as their original functions do

`LegacyDiagnosticResult.HashtablePaths` is a narrow formatting annotation:
audit-summary emits only `by_macro` and `by_exit_code`; diagnose-lag emits only
`processes.*.priority_classes`; every other operation emits an empty list. The
Windows render probe reconstructs precisely those known Hashtable values before
using the original Console serializer. It never converts all objects or skips
property order assertions. A production adapter must carry or derive the same
annotation from its immutable operation.

## Qualification evidence and remaining gates

Local managed compilation uses warnings as errors. The portable suite runs 323
finite cases, including 100 reached captured exceptions, all nine operations,
brief/JSON-only modes, typed owned-path descriptors, option errors, exact source
hashes, sample math, partial results and all-samples SLO protection. Fourteen
additional managed contracts cover representative report and codec behavior.
The repaired local suite has fifteen passing tests plus three explicitly skipped
Windows-only tests. The additional local regression checks retain 37 assertions
for the two accepted benchmark boundary IDs. No live acquisition is used.

The Windows test extracts the nine definitions and required pure helpers from
accepted Git source, replacing exact bounded acquisition seams before invocation.
Two isolated oracle fixture scripts preserve raw reports and Console output.
The gate compares full unformatted payloads, every effect and its order, reply
consumption, exact errors, exits and raw Console bytes. Every injected failure
must be reached; exhausting a fixture fails the portable gate. The original
source is parsed, never dot-sourced as a whole.

Windows PowerShell 5.1 execution at `d8bde03dfa1f1c2b0ab576041521786d1ae62573`
completed in [run 37048150884, diagnostics job 110974667877](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37048150884/job/110974667877).
All 321 actual-adapter cases ran: 273 exact cases, 34 expected current owned-write
uncertainty cases and 10 expected terminal uncertainty cases passed. Four report
mismatches remained, and 195 of the 196 guard checks passed. This failed checkpoint
is evidence, not qualification approval.

The concrete repairs retain every comparison: an explicit array clone fixes the
argv alias caught by guard 42; a diagnostics-only JSON reader preserves PS5's
exact-duplicate overwrite, case-collision rejection and positional syntax errors;
and audit map restoration replays initialization before assignment. That final
step matters because Framework Hashtable expansion occurs before existing-key
lookup, affecting raw enumeration order. See [Microsoft's reference source](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/collections/hashtable.cs).
Candidate rendering uses the same narrow audit restoration; raw Console and
full tagged payload ordering remain exact assertions. These repairs require a
new Windows run; no original body is retired by the local pass.

The reader remains a bounded diagnostic conversion, not a general PSObject/CLR
serializer. Escaped JSON dates now retain a UTC DateTime for audit cutoff math
and use invariant interpolation for the reported timestamp; bare date-like
strings stay strings. Non-null `__type` metadata is removed before case-collision
validation using the desktop resolver's fixed dictionary semantics. No supplied
type name can load or construct a CLR type. The two additional characterizations
await Windows comparison. The [retained diagnostic continuation](retained-diagnostics-qualification.md)
adds source-derived candidate repairs for DateTime-to-number errors, nonfinite
primitives, and PSObject empty/reserved property names, plus an independent
actual-candidate gate. Those new cases have not yet run on Windows; general
container conversion and runtime-specific formatting remain unqualified. Both
original production bodies remain retained until exact parity and review.
The new real adapter is implemented but **not yet Windows-qualified**. Its
actual-adapter test requires `CUCP_DIAGNOSTICS_TEST_HOST` and compares the entire
finite corpus against the pinned source. It preserves full equality for ordinary
cases, and requires exact effect prefixes, exact consumed replies, terminal
uncertainty and no further effects for deliberate owned-write failure corrections.
The guard fixture separately exercises strict decoded descriptor validation,
operation-only Hashtable reconstruction, native getter order/partial failures
and disposable owned-directory probe/cache helpers. All source with non-ASCII
text has an explicit UTF-8 BOM for Windows PowerShell 5.1.

The temporary guard scaffold was genuinely ported to Python: its original
42,879 bytes / 570 PowerShell lines are now an 11,770-byte / 129-line fixed
boundary driver, a reduction of 31,109 PowerShell bytes (72.6%). The old staged
draft is preserved for review as Git blob
`cba1ae30ad482b5271faf7617e95113ea537fcce`; it was not a published runtime
dependency. Python generates the cases, checks raw observations, and creates,
inspects and removes the disposable files. No PowerShell program is embedded in
Python or copied into an alternate source file. This reduces temporary fixture
overhead; it does not retire any original runtime function.

The exact expanded check inventory is unchanged:

| Original check IDs | Checks | Boundary |
| --- | ---: | --- |
| 1–40 | 40 | Accepted decoded descriptors |
| 41–77 | 37 | State copies, authority, envelope and tagged wire |
| 78–122 | 45 | Constrained operation, argument and payload denials |
| 123–135 | 13 | Repetition, iteration limits and retained paths |
| 136–153 | 18 | Retained process ordinals and sample sequencing |
| 154–168 | 15 | Operation-owned Hashtable formatting and identity |
| 169–182 | 14 | Native getter order, caught failures, nulls and timestamps |
| 183–195 | 13 | Captured owned-path acquisition and mutations |
| 196 | 1 | Real disposable files, junctions, probe and cache cleanup |

All 196 IDs/names and the 85 accepted/denied descriptor rows were independently
compared with that blob. The Python gate pins the exact identity-list digest,
checks category counts and requires every check to execute; the former
`checks >= 40` floor is gone. Multiple native calls remain grouped under the same
logical check, including all three path-equality comparisons and every real
filesystem observation. Raw Console/error/exit/effect comparisons for the
original 321 diagnostic adapter cases remain separate and unchanged. Two
additional captured inputs characterize an escaped JSON DateTime audit timestamp
and benchmark dictionary metadata; they append to the corpus without renumbering
existing cases.

The driver accepts only inert JSON and six closed modes. Captured filesystem
leaves are installed at the same script scope as the actual loaded definitions.
A source-helper sentinel probe verifies that lookup resolves those leaves before
write-capable captured cases can run; captured and real owned requests cannot
mix. Real I/O accepts only a marked Python-created root and fixed child paths.
Python unlinks its junction non-recursively before temporary-directory cleanup.
Local validation passes 15 portable tests, 14 original managed checks and the
37 additional benchmark boundary assertions. The rewritten driver has real
Windows execution evidence at the failed checkpoint above, including its owned
filesystem and native-getter cases. Those three repaired Windows gates later
passed at `7fb6c2f6`, as recorded above. The local counts alone were not Windows
parity approval.

The adapter accepts only its configured audit/cache roots. It refuses reparse
ancestors for owned writes and skips directory/reparse entries matching an
appshot filename. This intentional ownership constraint prevents a matching name
from authorizing unrelated deletion. Immediate-parent identity uses normalized
Windows paths with ordinal case-insensitive comparison, including trailing
separators; comparison never becomes an unrestricted prefix match.

Production routing, host acquisition checks, exact adapter tests, portable
packaging and the integrator's bundled full regression must pass before accepting
the integrated retirement.
Interactive Windows qualification and eventual tests with PowerShell absent
remain separate acceptance requirements.

## Enumerated process identity cache

The identity-only DTO is read at enumeration because the .NET Framework
`GetProcesses` constructor receives populated ProcessInfo and stores the ID.
`Id` uses the stored ID; `ProcessName` uses cached processInfo. The latter's
module lookup exception applies only before Windows XP, outside this runtime's
supported Windows platforms. `EnsureState` reloads process information only when
it is absent. No Refresh call is introduced here. Consequently eager ID/name
projection adds no later native query on the supported path; timing-sensitive
getters remain in ProcessMetrics and retained objects are never reopened by PID.
See [Microsoft's .NET Framework reference source](https://github.com/microsoft/referencesource/blob/main/System/services/monitoring/system/diagnosticts/Process.cs).
