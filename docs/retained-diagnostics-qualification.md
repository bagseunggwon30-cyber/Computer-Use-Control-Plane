# Retained benchmark and audit-summary qualification

This is a candidate-only continuation. `Invoke-MacroBenchmark` (5,389 UTF-8
AST bytes) and `Invoke-MacroAuditSummary` (2,728 bytes) remain byte-for-byte
unchanged in `scripts/cucp.ps1`. `RETAINED_DIAGNOSTICS` still contains both
operations. There is no production cutover or permission expansion.

## Independent gate

`tests/python/test_legacy_diagnostics_retained.py` adds a separate gate for all
66 existing retained-operation fixtures plus 236 JSON adversarial inputs and
30 subtraction-boundary probes (332 total). The first 302 cases are unchanged
and protected by a canonical full-corpus SHA-256 assertion. The original
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
reference sources below; exact Windows PowerShell 5.1 execution of the new cases
has **not** been observed in this environment.

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

Two concrete source-inferred gaps remain: object numeric casts still use the
shared scalar kernel's generic error, and audit interpolation of empty/nested
objects differs from PSObject's shallow display. The new `{}`, nonempty-object
baseline casts and audit object-value probes remain mandatory exact comparisons;
they are expected to block Windows qualification until repaired, not accepted
exceptions. Locale-specific Framework versus modern-runtime display, and the
full new JSON/property corpus, also need Windows evidence. No green portable
pass retires either original body.

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
