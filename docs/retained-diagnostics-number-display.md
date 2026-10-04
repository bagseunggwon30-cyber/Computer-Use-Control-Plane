# Finite-Double diagnostic display candidate

Current staged tree: [audit-only cutover candidate](audit-summary-staged-cutover.md).
The original-body statements below describe the preceding candidate checkpoint;
new Windows and full-regression acceptance remains pending.

## Decision: keep both original production bodies

The audit-only retirement preflight found a material numeric display gap that
is separate from the benchmark DateTime/current-culture fallback. No production
cutover is made. `Invoke-MacroAuditSummary` remains its original 2,728-byte body,
and `Invoke-MacroBenchmark` remains its original 5,389-byte body. Their accepted
hashes, public routes, both production-oracle selectors, session classification,
public-delegate allowlist, startup corpus, and migration manifest are unchanged.

Windows qualification at `c2b927e3fc5e274869ebd1ff7555ed28245d6425`, run
[37094100246](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37094100246),
proved the existing 472 captured inputs (464 exact and eight preserved owned
write failures). Those inputs did not include finite exponent-Double display
boundaries. That result remains valid for its exact source and corpus, but does
not establish these newly reached values or qualify this repair.

## Concrete gap and evidence distinction

At unmodified local base `bd28a5b310bdd1f362f632764c8fc9ee3bcc1e34`, the pure
candidate produced the following strings from inert `ReadLines` JSON data:

| JSON numeric token | Candidate output before repair | Framework-derived expected interpolation |
| --- | --- | --- |
| `1e16` | `10000000000000000` | `1E+16` |
| `1.2345678901234567e0` | `1.2345678901234567` | `1.23456789012346` |
| `-0e0` | `-0` | `0` |

These are **local candidate observations plus source-derived expectations**,
not newly observed Windows PowerShell outputs. The complete ordinary audit
route reached FileExists, ListFiles and ReadLines in order, consumed three
replies, and completed. The differences affect `by_macro`, `by_exit_code`, and
`earliest_ts`/`latest_ts`. They can change aggregation, not merely presentation:
`1.234567890123456e0` and `1.234567890123457e0` become two modern keys but share
the source-derived 15-digit key.

The source chain is explicit:

- Framework's [JSON reader](https://github.com/microsoft/referencesource/blob/main/System.Web.Extensions/Script/Serialization/JavaScriptObjectDeserializer.cs)
  bypasses Int32/Int64/Decimal parsing for exponent tokens and returns Double.
- PowerShell's [primitive stringifier](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/MshObject.cs)
  calls Double.ToString with the supplied provider. Audit interpolation uses the
  invariant provider; shallow benchmark object errors use current culture.
- Microsoft's [numeric format specification](https://learn.microsoft.com/en-us/dotnet/standard/base-types/standard-numeric-format-strings#general-format-specifier-g)
  distinguishes Framework's default 15-digit Double precision from modern
  shortest-roundtrip output, and Framework midpoint-away from modern tie-even
  rounding.
- The earlier [native numeric formatter](https://github.com/dotnet/coreclr/blob/release/2.0.0/src/classlibnative/bcltype/number.cpp)
  uses Double precision 15, general-format exponent thresholds and an unsigned
  zero result. Its initial conversion delegates to platform `_ecvt` or x86
  assembly. It is supporting historical implementation evidence, not an exact
  source proof for every installed Windows Framework build.

## Bounded candidate repair

`LegacyDiagnosticJson.ScalarDisplay` now routes only finite Double values to a
private formatter. It decomposes binary64 into an exact bounded integer ratio,
rounds to 15 significant decimal digits with midpoint-away semantics, removes
the sign of zero, and renders fixed/scientific text with general-format
thresholds. BigInteger sizes and powers are bounded by binary64, independent of
input text length. Culture affects only the supplied decimal separator and
positive/negative signs; the formatter never mutates culture or settings.

An unconditional modern `G15` call is insufficient: the exactly representable
value `123456789012344.5` exposes midpoint-away versus midpoint-even behavior.
The new candidate models the documented rounding explicitly. The existing
nonfinite, String, Decimal and DateTime paths are retained. No JSON parsing,
protocol integer validation, scalar kernel, effect descriptor, transport,
authority, retry, or provider policy changes are included.

This model does **not** prove equivalence to every historical `_ecvt` result.
Modern `Double.TryParse` remains in the diagnostic reader, so decimal-to-binary
rounding differences may precede display. Current-culture metadata in benchmark
errors still has its separately characterized Framework/NLS versus modern
runtime and name-only transport limits. Neither limit is erased by this
candidate; exact Windows differentials remain blocking evidence.

Independent review also found an existing benchmark-only neighbor outside this
object-display repair: a direct finite Double Int32 overflow still uses modern
JSON text through `LegacyTaskFormKernel.NumericInt`. For example, direct
`p50_ms:1e16` can retain `10000000000000000` in error text rather than the
Framework-derived `1E+16`. The new benchmark probes intentionally exercise the
object-member display path, not that direct conversion path. No blanket
finite-Double error-parity claim is made; benchmark stays original.

## Append-only qualification

The fixed `QUALIFICATION_DIAGNOSTICS` set freezes benchmark/audit corpus
membership independently of future changes to `RETAINED_DIAGNOSTICS`. Existing
66, 302, 332 and 472 prefixes each have canonical SHA-256 assertions. The full
472-prefix digest is
`3ed6f4f492813a682179b5f6231aa57a805f8196aba19e93561b7ff17969b166`.

A separate Python generator appends 196 probes, giving 668 total. Nineteen
finite tokens cover precision, scientific-format thresholds, signed zero,
exact midpoint and adjacent values, carry into a new exponent, subnormals,
minimum normal and maximum finite values. Each token reaches audit scalar,
shallow object and array interpolation, and benchmark object-cast error text
under en-US and de-DE. Extra cases cover key aggregation and literal String/
Decimal controls. Every case also runs Brief plus JSON-only.

All four existing exact routes remain mandatory: pinned accepted original,
current-original, pure candidate, and actual guarded adapter. The original
323-case suite, raw Console and ordered tagged values/effects, negative
assertions, uncertainty partitions, integer validation and no-retry behavior
remain intact. No case is normalized, xfailed, excluded or granted a mismatch
allowlist. Full fixture bytes and generator/managed-source identities are
captured before comparison. Managed checks add 67 source-derived assertions;
they are explicitly distinct from Windows evidence.

## Footprint and acceptance

This repair adds and removes **zero PowerShell bytes**. Original bodies total
8,117 bytes, replacement delegates add zero bytes, and oracle PowerShell changes
are zero bytes. Net runtime and total PowerShell reduction is zero. Canonical
extension-counted source remains **896,443 bytes**, including **610,258 runtime
bytes**. The unchanged inventory verifies those values. Helper-service/history
originals and candidate CI, foundation coverage, and every final inline/encoded
zero-PowerShell requirement remain open and unchanged.

Independent review and local regression precede a fresh exact-source Windows
candidate qualification. Only after resolving the observed new boundaries may
audit promotion be prepared, with separate true production-entry, routing,
startup/authority and full regression gates. This commit is a candidate repair,
not an audit retirement or new accepted production checkpoint.

## Local validation of this repair

- Full SDK-enabled Python discovery: 702 tests, 557 passed and 145 explicit
  platform/environment skips; no failures.
- Diagnostic Python discovery: 41 tests, 34 passed and seven Windows skips.
- Diagnostic managed checks: 14 contracts, 37 accepted benchmark boundary
  assertions, 24 subtraction assertions, 28 observed/source checks on Linux,
  and 67 new source-derived finite-Double display assertions.
- An independent Python Decimal model agrees on 256 deterministic finite
  binary64 inputs, including zero, subnormal and maximum finite values. This
  validates mathematical rounding only, not Framework parsing/CRT parity.
- Shared managed regression: 994 execution checks and 110 startup/authority
  checks pass.
- Matching NativeHost build with `EnableWindowsTargeting=true`: zero warnings,
  zero errors. Canonical inventory and `git diff --check` pass.
- Read-only independent review found no arithmetic/boundedness defect and
  verified all prefix preservation. It retained the `_ecvt`, Double parsing,
  benchmark culture, and direct finite-cast limits above.

Windows PowerShell and actual-adapter execution were unavailable in this Linux
workspace. The new 668-case Windows gate has not run. Portable passes are not a
substitute for that gate or for fresh production-entry qualification after any
future cutover.
