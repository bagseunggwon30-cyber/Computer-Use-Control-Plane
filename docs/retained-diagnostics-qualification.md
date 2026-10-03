# Retained benchmark and audit-summary qualification

Current staged tree: [audit-only cutover candidate](audit-summary-staged-cutover.md).
The original-body statements below describe the preceding candidate checkpoint;
new Windows and full-regression acceptance remains pending.

This is a candidate-only continuation. `Invoke-MacroBenchmark` (5,389 UTF-8
AST bytes) and `Invoke-MacroAuditSummary` (2,728 bytes) remain byte-for-byte
unchanged in `scripts/cucp.ps1`. `RETAINED_DIAGNOSTICS` still contains both
operations. There is no production cutover or permission expansion.

## Independent gate

`tests/python/test_legacy_diagnostics_retained.py` adds a separate gate for all
66 existing retained-operation fixtures plus 236 JSON adversarial inputs and
30 subtraction-boundary probes (332 original cases), followed by 140 bounded
JSON/culture/numeric-string neighbors (472 total). Both the 302-case and
332-case prefixes are unchanged and protected by canonical full-corpus SHA-256
assertions. The original
323-case nine-operation suite, production-entry comparisons, 196 adapter guards,
and startup gates remain unchanged.

The new Windows test exercises four routes for each case:

1. Pinned accepted PowerShell body from
   `c0d15371b60ebf62be45bfa68b90282405f07273`.
2. Current retained original public body, using `-ProductionEntry`.
3. Pure managed candidate with captured effect replies.
4. Actual candidate through the existing closed diagnostic adapter and shared
   session transport, deliberately without `-ProductionEntry`.

The fourth route does not consult the migration manifest. It uses the pinned
original as `-Source`, the current diagnostic adapter as `-AdapterSource`, and
the current wrapper as `-BridgeSource`. This prevents a green comparison of
original PowerShell against original PowerShell from qualifying the candidate.
Original helper imports remain pinned; the bridge loads only transport helpers.
This is compatible with the separately proposed unused-helper removal, whose
production-only helper filter does not affect the candidate route.

Every case compares state, effects and order, consumed replies, exits, payload,
errors, and actual-adapter raw Console output. Tagged payload property ordering
is retained in the full adapter comparison. Only the already-established
owned-write uncertainty partition is used: exact prefix and consumed count,
terminal error, empty Console, and no further effects after a failed owned
write. No mutation is retried. Known gaps are not allowlisted or xfailed.

All inputs are inert raw JSON supplied through existing `ReadText` or
`ReadLines` fixture seams. The tests use captured Native replies only. No real
provider, desktop input, account, model, or requested file operation is added.
No new PowerShell oracle, embedded PowerShell source, transport, or effect exists.

## Source-derived repairs

These implementation findings are confirmed by reading the candidate and the
reference sources below. The first 332-case Windows run and its failed
assertion fragments are described in the repair checkpoint below; the current
472-case repaired candidate has not yet received Windows qualification.

- Benchmark previously converted legacy escaped `/Date(...)/` JSON values to
  strings before Int32 conversion. A private parsed-value wrapper now preserves
  the source-created DateTime type through property selection and casting.
  Error display uses current culture; audit interpolation remains invariant.
  Unescaped date-looking JSON strings remain strings and cannot forge a type.
- Framework accepts exactly `NaN`, `Infinity`, and `-Infinity` as JSON numeric
  primitives. They are preserved as typed doubles for reached benchmark casts
  and interpolated for audit text. Modern-runtime overflow saturation and extra
  nonfinite spellings remain rejected. Nonfinite Int32 errors retain the
  Framework overflow message rather than a string-conversion failure.
- Empty property names fail before nested-value validation. `PSTypeNames`
  collides with the existing canonical `pstypenames` property before recursion.
  Reserved `PSBase`, `PSAdapted`, `PSExtended`, and `PSObject` member sets fail
  after their child values have been checked. Exact-duplicate overwrite still
  removes replaced invalid subtrees before these checks.
- JSON arrays retain their Object[] identity for failed Int32 casts, including
  zero- and one-element arrays; no singleton is silently unwrapped.

New probes cover p50 and p95 date casts, unmatched or skipped casts, named
nonfinite values versus overflowing or differently-cased tokens, en-US/ko-KR
date display, empty/reserved/ordinary property names, validation precedence,
`__type` removal and overwrite, scalar/array roots, numeric/container casts,
and Brief plus `--json-only` behavior. Input IDs describe data, not presumed
PowerShell outcomes.

Reference sources:

- [Framework JSON reader](https://github.com/microsoft/referencesource/blob/main/System.Web.Extensions/Script/Serialization/JavaScriptObjectDeserializer.cs)
- [Framework Double parsing](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/double.cs)
- [Desktop PowerShell JSON object conversion](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/Microsoft.PowerShell.Commands.Utility/commands/utility/WebCmdlet/JsonObject.cs)
- [PowerShell scalar conversion](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/LanguagePrimitives.cs)
- [PowerShell member lookup](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/MshMemberInfo.cs)
- [PowerShell argument resources](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/resources/AutomationExceptions.resx)
- [PowerShell type-system resources](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/resources/ExtendedTypeSystem.resx)

## Subtraction boundary continuation

Independent review identified unchecked Int32 subtraction in the candidate's
baseline delta. With current p50=37 and baseline p50=-2147483648, the old C#
expression wrapped to -2147483611, incorrectly selecting `improved`.
[PowerShell IntOps.Sub](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/runtime/Operations/NumericOps.cs#L28-L35)
uses an Int64 intermediate and returns Int32 when representable, otherwise
Double. The candidate now follows those separate return paths: that case yields
Double 2147483685, `regressed`, and delta percentage 0. This is a source-derived
repair, not newly observed Windows PowerShell evidence.

The append-only 30-case continuation includes exact Int32 lower/upper results,
one step inside and outside each limit, ordinary current=37 comparisons,
widest signed differences, p95-only boundary subtraction, and an invalid p95
cast after a wide p50 result. Each runs both normal and Brief/JSON-only forms
through all four existing routes. Negative captured clock values are deliberate
signed-arithmetic probes, not claims about live Stopwatch timing. The p95
conversion/subtraction remains before percentage calculation even though its
result is unused. Baseline Int32 casts, effects, and authority are unchanged.

Managed checks assert both boxed type and exact value, avoiding a numeric
ternary that would unintentionally promote all ordinary results to Double.
Raw PowerShell JSON/Console spelling and exact adapter equality still require
the Windows lane below, with no mismatch allowlist or xfail.

## Validation and limits

Portable checks establish deterministic candidate behavior and unchanged
production body hashes, not parity with an unavailable PowerShell runtime.
The Linux run passes 21 diagnostic Python tests; six Windows-only test/class
checks are explicitly skipped. Managed diagnostic contracts (14) and the
independent benchmark boundary assertions (37) also pass, alongside 24 new
source-derived subtraction value/type assertions. The NativeHost builds
with zero warnings/errors and `EnableWindowsTargeting=true`; all 994 managed
execution-family checks and three inventory checks pass. At the initial
`12d0cc2` candidate base, tracked PowerShell source measured 872,501 bytes.
The later integration below inherits the separately reviewed helper cleanup;
this candidate still contributes no PowerShell source-byte change.

The first Windows run confirmed object-cast and shallow-interpolation gaps.
The repairs below now model those behaviors, with every original exact
comparison retained. Current repaired-route equality and locale neighbors
still require Windows evidence. No green portable pass retires either body.

Run on Windows PowerShell 5.1 with the matching .NET SDK:

```console
python pcucp-next/packaging/migration_qualification.py run --family diagnostics --log-dir .migration-logs/diagnostics
```

That existing family glob includes the new module and configures the matching
`CUCP_DIAGNOSTICS_TEST_HOST`. For an isolated retry after building that host:

```console
python -m unittest discover -s tests/python -p test_legacy_diagnostics_retained.py -v
```

The isolated command also requires `CUCP_DIAGNOSTICS_TEST_HOST` and the normal
Python path setup. Missing host configuration is a Windows failure, never a
silent skip. Exact candidate and actual-adapter results, independent review,
and the integrated full regression gate are required before any later cutover.

## Honest source footprint

This batch adds **zero PowerShell bytes** and removes **zero PowerShell bytes**.
Both production bodies still total **8,117 bytes**. The existing oracle scripts
and their embedded render source remain counted, unchanged. The added Python
qualification and C# repairs are candidate work, not retirement credit.

## Local integration on the reviewed cleanup base

The isolated integration starts at
`6f50d3a13b44a7285d3eac71f3792a6cfe9ad6bf`. Both candidate commits were
cherry-picked without conflicts: `050f3a1` became `1d7e863`, and `ab58db1`
became `cc2b512`. No merge resolution or source selection change was needed.
Parser fixes, raw diagnostic goldens, the seven-helper cleanup, migration
manifest, and both diagnostic `ProductionEntry` helper filters remain exactly
as in that base. All 332 mandatory retained-candidate cases and the pinned
302-case prefix remain intact.

SDK-enabled full local Python validation reports 562 tests and 124 explicit
platform/optional skips, with no failures. The matching NativeHost builds with zero warnings or
errors; diagnostic contracts (14), accepted benchmark assertions (37), new
subtraction type/value assertions (24), execution checks (994), and startup
contracts (110) pass. Inventory and diff checks pass. Tracked PowerShell source
is 870,201 bytes, inherited unchanged from the cleanup base; this integration
adds and removes zero PowerShell bytes.

This is local candidate integration evidence. Windows PowerShell execution,
raw Console/actual-adapter equality, the known object-conversion gaps, and the
final qualification decision remain pending. No publication or production
cutover is performed by this integration.

## Failed Windows checkpoint and bounded repair

[Run 37090071710](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37090071710)
ran remote `7efbf9d21b3916f5789fe1c214a4294127ad0270` and finished at
`2026-10-03T02:40:47Z`. The downloaded artifact archive's verified SHA-256 is
`e93a415dc74d7ca0939a6b752dd53dabda3fced6808c56420185386b5c40f05e`.
Its six complete logs and source map are available; **the full raw route arrays
were not saved by that version**. The committed observed-fragment fixture
labels that distinction and stores only assertions visible in `05.log`.

All 332 current-original comparisons passed. The candidate had 23 failing
route subtests across 12 inputs (11 pure, 12 actual-adapter), followed by the
partition-count assertion. The unchanged older 323-case production gate passed.
Those failures establish these bounded repairs, not retirement approval:

- Nonfinite Int32 error display now uses current culture, preserving `∞` and
  `-∞` observed in the English fixture. Audit interpolation remains invariant;
  textual Infinity is not reclassified as a numeric primitive.
- Boolean baseline p50 already cast correctly to Int32; its percentage divisor
  incorrectly converted the string `True`. Diagnostic parsed-value Double
  conversion now retains the Boolean type. Execution/protocol integer validation
  and the shared scalar kernel are unchanged. Reached numeric-string neighbors
  include hex, scientific, grouping, whitespace, signed and zero values. The
  source-derived Double error wrapper preserves a subtle original distinction:
  a positive hexadecimal string can pass Int32 but fail the later Double cast;
  zero/negative values still skip that divisor cast. These extensions remain
  inferred until their mandatory Windows comparisons run.
- PSObject display is shallow: an empty object prints empty text, nested objects
  have an empty base string, and nested arrays display `System.Object[]`.
  Top-level array interpolation also uses shallow element display. Audit strings
  use invariant scalar formatting; object-cast error members use current culture.
- Object Int32 errors retain the exact inert custom-object display name. The
  source guard exempts exactly one declared literal in `LegacyDiagnosticJson.cs`,
  retains its original forbidden dependencies, and adds negative using/type/
  duplicate-literal/reflection cases. Independent managed assembly-reference and
  type checks reject engine dependencies. There is no engine load or type lookup.

The Korean DateTime error exposed Framework NLS versus modern ICU pattern data.
`LegacyDiagnosticCulture` is a new fixed, read-only locale-data boundary in the
native host: four bounded GetLocaleInfoEx fields, selected culture and override
policy, Win32 pattern reescaping, pattern-derived separators, and a private
DateTimeFormatInfo clone. It neither changes CurrentCulture nor sets a global
runtime switch. It applies only to reached diagnostic DateTime cast-error text.
The supported model is **numeric Gregorian date patterns**. Named months,
weekdays, eras and non-Gregorian calendars still use the prior formatting path
and remain unqualified. No general culture-parity claim is made. Managed
formatting retains years 1–9999; GetDateFormatEx was deliberately avoided because
its documented date floor would truncate the legacy DateTime domain.

The additional 140 inferred cases cover typed versus textual Booleans/nonfinite
values, empty/nested object and array display, current versus invariant member
formatting, five named Gregorian cultures, p50/p95 casts, and year-domain edges.
Every original 332 input remains byte-for-byte equivalent under its pinned
canonical digest; no case is xfailed, normalized, or removed. Complete new
Windows candidate/adapter equality and review are still required.

## Durable failed-route evidence

The qualification-only Python capture writes a unique `run-*` directory under
`CUCP_DIAGNOSTICS_RETAINED_CAPTURE_DIR`. Standalone runs default to
`.migration-logs/diagnostics/retained-diagnostics` within the checkout. The small
family-runner environment hook is a separate integration change; existing CI
artifact paths remain unchanged.

Before checking exit status, decoding, parsing or asserting array length, it
persists exact bounded stdout/stderr, return code or launch/timeout error,
per-route case order, exact stdin bytes/hash, source and executable hashes,
Git identity/status, Python/OS data, .NET runtime information, fixture cultures,
and the inert fixture inputs. Only explicitly allowed runtime environment fields
are recorded. A manifest distinguishes unattempted, failed and completed routes;
no failed route is retried. Comparison failures are recorded before unittest
subTest suppression, and cleanup never turns incomplete/mismatched work into a
qualified pass. Original temporary inputs may be deleted after capture without
losing raw outcomes or pinned source bytes.

Artifacts retain up to 8 MiB of stdout and 1 MiB of stderr per route, and 4 MiB
of stdin. Overflow is an explicit gate failure with original byte count/hash
and a marked retained prefix; truncated output is never parsed as a successful
observation. These are artifact bounds: subprocess.run still buffers child
output before enforcing them. The bounded fixture corpus and existing process
timeouts are unchanged. Capture tests cover nonzero exits, decode/JSON/shape/
count errors, timeout partial bytes, launch errors, output limits, unique paths,
no retry, real-harness partial acquisition, temporary cleanup and suppressed
mismatches. No new PowerShell source or acquisition capability is introduced.

Additional primary references:
- [Framework PSObject display](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/MshObject.cs)
- [Runtime NLS pattern escaping and locale data](https://github.com/dotnet/runtime/blob/v8.0.0/src/libraries/System.Private.CoreLib/src/System/Globalization/CultureData.Nls.cs)
- [Framework DateTimeFormatInfo](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/globalization/datetimeformatinfo.cs)
- [GetDateFormatEx domain](https://learn.microsoft.com/en-us/windows/win32/api/datetimeapi/nf-datetimeapi-getdateformatex)

Local repaired-candidate validation: the SDK-enabled full Python suite reports
578 tests with 125 explicit skips and no failures. The matching NativeHost
builds with zero warnings/errors. Managed checks pass: 14 diagnostic contracts,
37 accepted benchmark assertions, 24 subtraction assertions, 28 observed/source
boundary assertions on Linux, 994 execution checks and 110 startup checks.
Two additional observed NLS assertions run only on Windows. Inventory and diff
checks pass; tracked PowerShell remains 870,201 bytes, with zero byte change in
this repair. Current Windows qualification has not yet been run.

The repair was subsequently integrated on the reviewed parser/history candidate
tree `c57c0c7` without conflicts. The family runner now explicitly routes capture
to its selected log directory, covered by a regression test; existing artifact
paths, history scope and full foundation coverage remain intact. The integrated
Python suite ran 622 tests: 496 passed and 126 explicit environment skips.
Independent review found no blocker to fresh candidate qualification, while
retaining the documented subprocess-buffering and culture-model limitations.
The current integrated extension count is 880,873 PowerShell bytes, unchanged
by this diagnostic repair; the difference from its local 870,201-byte base is
the separately counted history oracle. No production body has been retired.

## Subsequent Windows result

Published commit `c2b927e3fc5e274869ebd1ff7555ed28245d6425` passed
[run 37094100246](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37094100246)
on 2026-10-03 at 03:53:10 UTC. All 43 Windows Python tests passed without skips.
All 472 retained inputs passed original/current-original/pure-candidate/actual
adapter comparisons: 464 exact and eight preserved owned-write failures. The
older 323 production-entry cases also retained their established partition of
287 exact, 26 owned-write failures and ten terminal postdispatch failures.
The managed observed/source checks total 30 on Windows, including both NLS checks.

Artifact SHA256 is
`9a9a5589b278658d42701b22322b4577741c71e8d8b2201d30cae5a7b49cfbcf`.
Its 34 files include complete raw route data. The manifest declares completed
comparison and passed qualification, with no unattempted routes; every stored
route byte count/hash and the input hash were independently verified. Manifest
SHA256 is `3340fba891b678d33d2a3bfb8d009b790db55148416cf46b1786944f39880ce2`.
The only captured Git status entry is the generated evidence directory.

This qualifies the tested candidate routes, not production retirement. The
documented non-Gregorian/textual-date fallback remains reachable but has not yet
been shown to differ; a bounded Windows characterization is the next review
step for benchmark. Audit interpolation is invariant and does not enter that
formatter fallback. Routing, production-entry assertions and complete regression
must still be reviewed before either original body is removed.

## Audit retirement preflight: finite numeric display blocker

A subsequent local audit-only retirement preflight found a separate reachable
finite-Double display gap despite invariant audit interpolation. Exponent JSON
values reach modern shortest-roundtrip formatting; Framework interpolation uses
15-digit general formatting, unsigned zero and legacy rounding. Audit remains
original. The [bounded numeric-display candidate](retained-diagnostics-number-display.md)
adds 196 exact route probes after the unchanged 472, freezes the historical
corpus independently of production selection, and requires new Windows evidence.
The prior passing run remains evidence only for its exact source and inputs.
There is no PowerShell source retirement or production routing change here.
