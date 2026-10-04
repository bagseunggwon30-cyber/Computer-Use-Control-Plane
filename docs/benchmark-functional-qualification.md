# Bounded benchmark functional qualification

Current staged source routes benchmark through its managed candidate; fresh
Windows production-entry and full-regression acceptance remain pending. Audit
body retirement is separately qualified at `3cbbaaad` / run `37103102449`
attempt 2. See [benchmark staging](benchmark-staged-cutover.md). The original-body
statements below describe preceding checkpoints.

This work retains the original benchmark and audit public bodies, the complete
668-input exact gate, and all previous raw assertions. It implements the scoped
prose criterion in `functional-migration-release-criteria.md`; it does not grant
an allowance for numeric results, accepted inputs, effects, schema or reasons.

## Calendar-range containment

The previous candidate's `fa-IR` DateTime error display throws outside the
Persian calendar range. In an inert local full-benchmark fixture, the legacy
JSON date for `0001-01-02` (milliseconds `-62135510400000`) produced terminal
`state=error` after six replies, with no benchmark payload or exit code.
`0002-01-01` and `0600-01-01` reproduce the same candidate-side problem.
`0001-01-01` is a misleading control: the runtime supplies a special fallback.

The original's surrounding unconditional catch suggests it should produce the
contained `baseline_load_failed` report, but this is source inference, not an
observed original Windows outcome. The new Windows operation test must observe
that outcome and fails if it does not. It compares the pinned original, pure
managed candidate and actual candidate adapter using the existing inert runtime
oracle and closed captured effects.

The repair catches only `ArgumentOutOfRangeException` from the fallback date
formatter and emits the value in invariant round-trip form. The Int32 cast
still fails. No global culture setting, numeric conversion, shared protocol,
permission or effect dispatch changes. There is no new PowerShell oracle or
unrun all-culture driver.

Sixteen fixed cases cover the first/second days of year 1, p50/p95 placement,
direct/object-member dates, and Brief/full JSON. The failure-only functional
comparison requires exact completion/exit/schema/stable error/path, all other
payload values and types, tagged property/effect order, reply consumption and
Brief output. It permits only `baseline_compare.detail` and the one serialized
JSON Console value containing that same detail. Every Console byte outside that
token is compared unchanged. Detail must remain nonempty useful text bounded to
4,096 characters. It cannot hide an escaped exception, changed result, extra
effect, retry, boolean-for-number conversion or another operation.

All route bytes and raw exact comparison results are saved before functional
assertions. Capture is labeled `qualification_kind=benchmark-functional` under
the existing diagnostic artifact root's `benchmark-calendar-functional/run-*`.
`raw-exact-summary.json` reports exact mismatches separately; it is not rewritten
as an exact pass. The existing 668-case exact gate is unchanged.

## Caller evidence

The benchmark producer catches baseline errors in `scripts/cucp.ps1:8074` and
`LegacyDiagnosticPerformance.cs:148`. Brief rendering checks error presence;
prior reports reused as baselines contribute only results/name/p50/p95.
Workflow, recorder and daemon paths may republish the full report, including
detail. Their decisions use return codes, verification and structured
uncertainty flags, not the sentence. This establishes repository caller
evidence, not the behavior of unknown external consumers.

Shared audit interpolation remains exact because its text becomes aggregation
keys, timestamp data and filtering input. Shared task/form and control-envelope
integer conversion are outside this prose allowance.

## Qualification status

Local diagnostic Python tests and managed checks pass, including the 16 repaired
full-operation cases and three direct calendar-containment checks. Windows
original/pure/actual comparison remains required. Run the existing lane:

```text
python pcucp-next/packaging/migration_qualification.py run --family diagnostics --log-dir .migration-logs/diagnostics
```

No production routing or inventory credit changes. Future benchmark cutover
still requires matching-source Windows functional and exact evidence, actual
production-entry/startup coverage, independent review and full regression.

## Separate Decimal numeric repair

The benchmark's parsed-value wrapper kept Decimal values, but its Int32 method
serialized them to JSON and called the shared `LegacyInt(JsonElement)` path,
which first converts to Double. That intermediary changes real results near
midpoints and range boundaries. Before repair, captured local full-benchmark
observations were:

- `0.5000000000000000000000000001`: baseline p50 became 0, delta 37,
  percentage 0, instead of the source-derived Decimal cast 1.
- `1.4999999999999999999999999999`: p50 became 2, delta 35, instead of 1.
- `2147483647.4999999999999999999`: baseline comparison failed instead of
  accepting the source-derived Int32 maximum.

The original outcomes remain inferred until the new Windows comparison captures
them. The [Framework JSON reader](https://github.com/microsoft/referencesource/blob/main/System.Web.Extensions/Script/Serialization/JavaScriptObjectDeserializer.cs#L199-L235)
selects Decimal for these non-exponent tokens. PowerShell's
[numeric conversion](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/LanguagePrimitives.cs#L2451-L2470)
uses `Convert.ChangeType` on the typed value. The bounded repair therefore calls
`Convert.ToInt32(decimal)` before the existing fallback. It retains the existing
failure wrapper, and changes neither shared task/form conversion nor execution
control integers. Double and string branches stay separate and unchanged.

Eighteen explicit vectors include the three findings, positive/negative exact
midpoints, both Int32 rounding/overflow edges, and exponent-Double/string
controls. Each crosses p50/p95 and Brief/JSON paths, totaling 72 full-operation
cases in a separate gate. Eighteen managed checks independently exercise typed
conversion. The original 668 cases remain untouched. Successful numeric cases
require exact original/actual records and exact pure numeric/data contracts;
only shared rejected-conversion paths may use the already-scoped detail prose
allowance. Windows must confirm the source-derived expected numeric outcomes.

The numeric capture is separately labeled and retained under
`benchmark-decimal-functional/run-*`, with raw exact summaries saved before
functional assertions. Raw kernel summaries also include terminal error text,
so two different escaped failures cannot be reported as an exact match.
Calendar and numeric repairs are separate commits; neither retires a body.

Local validation of the combined isolated tree: 714 SDK-enabled Python tests
pass with 149 platform/availability skips; the diagnostic subset passes 46
tests with nine Windows skips. NativeHost builds with zero warnings/errors.
Managed diagnostic checks pass (14 contracts, 37 accepted boundaries, 24
subtraction, 28 prior observed/source checks, 67 finite-Double checks, three
calendar checks and 18 typed-numeric checks). Execution family checks pass 994 assertions; startup authority/framing passes
110 checks. The existing exact corpus remains 668, with 16 calendar and 72
numeric cases added only in the separately named functional gates. Tracked
PowerShell remains 902,990 bytes on this base: zero source-byte change and no
retirement credit. At that checkpoint, the new original Windows outcomes were pending.

## Saved Windows evidence and Brief harness repair

Run `37103413852` at `fa1c830e` captured all routes, but both new tests failed
during summary construction because `original_contract` tried to decode
`payload=null`. This is the actual Brief rendering contract: the original and
actual adapter print only their brief line, so the oracle's `ConvertTo-Json`
capture hook is never called. The pure coordinator still retains its internal
payload. All 668 historical exact cases, including 258 production audit pairs,
passed that run. The new gates' original manifests remain failed/incomplete.

The verified archive SHA-256 is
`1e54a7c91cf93bdd5c0267e22f53b95e8b98fcdf86eb896d3c3cfdd8891498c2`.
Reassessment with the corrected comparator finds all 72 Decimal public pairs
exact, and all 16 calendar cases functionally equal: 12 public pairs are exact
and four full-JSON pairs differ only in permitted detail prose. All 44 Brief
public pairs preserve `payload=null` and exact Console/state/exit/effects.
The source-inferred Decimal p50 outcomes are now observed in the original:
the three reported values produce 1, 1 and 2147483647, with deltas 36, 36 and
-2147483610 and percentages 7200, 2400 and -100 respectively.

The repair preserves absent payload in raw summaries. Functional comparison
permits that absence only for complete Brief records; non-Brief requires an
intact tagged report. A Brief case must have an adjacent non-Brief observation
whose fixture differs only in rendering mode and case ID. That complete
original/pure/actual comparison is rerun, and the pure Brief data must exactly
match the pure control's full contract. No original Brief payload is invented
or replaced. State, terminal errors, exact effects/consumption, numeric fields,
schema, render flags and public Console remain checked. Missing/null non-Brief
payload, terminal failure, unmatched controls and extra pure errors are negative
regressions, not accepted representations.

`plans/evidence/benchmark-functional-reassessment-37103413852.json` records the
offline assessment, validator source hashes and original artifact route hashes.
Three complete observed pairs, including conversion success and rejection, are
retained in `tests/fixtures/legacy-benchmark-brief-observed-37103413852.json`.
This offline assessment does not turn the failed CI run into a green gate or
qualify a production cutover. Fresh production-entry Windows and full regression
remain required. The 668 historical corpus and runtime implementation are
unchanged by this harness repair.
