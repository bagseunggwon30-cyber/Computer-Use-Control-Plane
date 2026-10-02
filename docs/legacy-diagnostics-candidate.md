# Diagnostic and reporting assembly candidate

This isolated candidate moves nine report/orchestration bodies into
`PcuCp.LegacyDiagnostics/LegacyDiagnosticCoordinator`. Production PowerShell,
startup routing, portable publication and retirement are unchanged. It is **not**
a qualified adapter or a claim that PowerShell has been eliminated.

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
pins each body's SHA-256 and byte count. No original body is removed; fixture
PowerShell remains counted source. Cleanup is excluded: its deletion/process
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

There is no second PowerShell bridge or new chunk/framing implementation. Shared
`LegacyExecutionWire` preserves true arrays and ordinary `{value,Count}` objects.
The trusted host can use its new session factory to construct this coordinator;
external startup registration remains closed until qualification.

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
| Processes | empty / null | snapshot array `{id,name,private_bytes,started_at,cpu_ms,priority}`; individually inaccessible properties omitted |
| ProcessorCount | empty / null | processor count |
| Windows | empty / null | captured Win32 window rows |
| Sleep | empty / requested sample ms | ignored |
| EnsureWin32, EnsureUia, HelperUp | empty / null | original truth value |
| FindCodex | empty / null | original path or null; empty string is still non-null |
| AssertAuthorized | empty / null; one of two fixed self-test argument arrays | success or captured exception, never an input dispatch |
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
`AuditProbe`, `ClearAppshotCache`, and every `Appshot` (a warm cache read can miss).
It must also conservatively include `Macro` suboperations `health-quick` and
`find-label`, and `Cli` argv starting `observe appshot` or `observe screenshot`:
these nested calls can create owned probe/cache/capture artifacts. This is
separate from desktop-live permission. Pre-dispatch validation/serialization is
known-unmodified; a lost or malformed reply, terminal assembly failure or stream
failure after dispatch is uncertain and must retain `automatic_retry:false`.
An explicit, trustworthy proof that a request did not dispatch can retain the
original caught acquisition-failure behavior. The host owns this classification;
request/reply data cannot supply a permission or clear a recorded dispatch.

## Compatibility decisions

- Option lookup is first occurrence, case insensitive; switch lookup retains the
  legacy all-arguments behavior. Integer conversion reuses the existing kernel
- Perf's cold and warm targets both run N iterations, despite the old comment
  claiming a single iteration. Clearing occurs once, before the pair
- Benchmark uses nearest-rank p50/p95 over successful samples, banker-rounded
  average, inclusive SLO boundaries and the accepted all-samples-success rule
- Lag uses T0, sleep, T1, then date/CPU acquisition; negative CPU deltas clamp to
  zero and CPU percentage uses requested sampling time, not measured elapsed
- Individual inaccessible process properties preserve other partial process data.
  Singleton PID lists preserve the original scalar shape
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

Local managed compilation uses warnings as errors. The portable suite runs 303
finite cases, including 100 reached captured exceptions, all nine operations,
brief/JSON-only modes, typed owned-path descriptors, option errors, exact source
hashes, sample math, partial results and all-samples SLO protection. Fourteen
additional managed contracts cover representative report and codec behavior.
The targeted local suite has six passing tests plus one explicitly skipped
Windows-only test. No live acquisition is used.

The Windows test extracts the nine definitions and required pure helpers from
accepted Git source, replacing exact bounded acquisition seams before invocation.
Two isolated oracle fixture scripts preserve raw reports and Console output.
The gate compares full unformatted payloads, every effect and its order, reply
consumption, exact errors, exits and raw Console bytes. Every injected failure
must be reached; exhausting a fixture fails the portable gate. The original
source is parsed, never dot-sourced as a whole.

Windows PowerShell 5.1 differential execution is **pending**, not passed. The
oracles have static seam checks but cannot run on this cloud Linux environment.
Malformed baseline JSON currently exposes System.Text.Json parser-detail wording;
matching the PS5.1 ConvertFrom-Json detail is a known pending compatibility repair.
The corpus also characterizes exact/case-folded duplicate audit keys, whose legacy
parser acceptance and last-key behavior must be reconciled before promotion.
These cases remain full equality assertions in the Windows gate, not exclusions.
A real, retained adapter has not been implemented or qualified. Production
routing, host acquisition checks, exact adapter tests, portable packaging and the
integrator's bundled full regression must pass before retirement/publication.
Interactive Windows qualification and eventual tests with PowerShell absent
remain separate acceptance requirements.
