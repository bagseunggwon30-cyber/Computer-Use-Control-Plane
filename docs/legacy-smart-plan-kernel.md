# SmartPlan captured-reply migration

The isolated source `pcucp-next/dotnet/PcuCp.LegacySmartPlan/LegacySmartPlanKernel.cs`
is outside NativeHost's compile wildcard. Its independent net8 harness is
`pcucp-next/dotnet/PcuCp.LegacySmartPlan.ContractTests`. It has no PowerShell SDK,
process, filesystem, network, desktop or model dependency. The 201-case Windows
oracle and captured-prefix checks passed at a03d2788 / run 36938195037. NativeHost
now explicitly links the kernel and registers smart-plan-advance. The feature
branch adapter preserves read-only acquisition and passed all 201 exact
actual-adapter cases at aadbc58 / run 36957910828. Later source changes still
require their own current-commit qualification.

`Advance({rest, cache_seconds, brief, elapsed_ms, captured_replies})` deterministically
replays a bounded planning sequence. A missing capture returns
`{state:"query",query:{kind,argv},queries}`. A completed replay returns
`{state:"complete",payload,exit,brief,queries}`; `brief` is null in JSON mode.
Elapsed milliseconds come from the adapter. Derived source errors return
`{state:"error",error,queries}` in the harness.

Each reply must contain the exact derived `kind` and `argv`, and exactly one
`result` (including explicit null) or `error` string. Missing, wrong-order and extra
captures are not interchangeable with a failed probe. The query kinds are:

- history: label, match-or-empty, lookback `5`; a captured history exception is swallowed
- cdp_port: port, timeout `120`; only when the original CDP option gate permits it
- native: exact original `Invoke-NativeHelper` arguments for CDP, then UIA, then optional OCR

Descriptors are data. The retained adapter keeps these existing read-only
acquisition boundaries and never runs arbitrary descriptor commands. Precision
planning only constructs target-validation/click commands; it performs no query.
A replay recomputes all earlier choices from the original rest and captures, so it
cannot introduce an unrequested extra probe or treat a null result as a retry.

Candidate order follows the historical median-pivot unstable rank sort, including
equal-rank swaps. The first candidate controls the recommendation; a stable sort
would be a behavior change. Original status quirks are retained: for example an
`ok` CDP JSON reply can produce a planning candidate even with a nonzero helper
exit. `safe_to_act` remains original plan metadata, not permission to perform
input. The authorization warning and all generated command flags remain intact.

Qualification extracts the exact pinned functions from tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`, stubbing only external history/port/helper
acquisition. Full deterministic payload, errors, query order/argv, exit and brief
output are compared; only measured elapsed time is normalized. Each captured
prefix independently checks the next requested query. Brief output is compared
as emitted rather than fabricating a payload the original did not serialize.

Run `dotnet run --project pcucp-next/dotnet/PcuCp.LegacySmartPlan.ContractTests
-c Release -- --self-test` for pure boundary checks. On Windows, run
`python -m unittest discover -s tests/python -p test_legacy_smart_plan_parity.py -v`.
The Windows test builds the isolated harness and uses generated reply fixtures
only. It never loads user windows or starts authenticated applications.

No Linux build or fixture-source check establishes PowerShell semantic parity.
The original 17,025-byte/334-line builder has an independently qualified C#
equivalent. Full replacement qualification additionally requires the actual
retained-adapter comparison. Numeric conversion,
PowerShell object/string coercion and tied first-candidate selection remain
explicit qualification concerns.

The capture boundary rejects non-string/coerced kind values, unknown keys,
duplicate keys and result/error conflicts. Six additional managed cases cover
those envelopes. The Windows matrix now has 197 cases, including 50 score-boundary
cases across CDP, UIA pattern/value/precision and OCR, plus 20 fractional/malformed
option cases. Score arithmetic is promoted before the nested helper's Int32 bind;
rank remains wide because the original rank expression has no Int32 cast.
Exact numeric exception text remains subject to the strict Windows oracle; no
assertion is narrowed to accommodate a candidate exception.

First Windows qualification (3af7ada/job110617296559) matched 188/197 complete
cases. Eight out-of-Int32 captured numeric scores lacked PowerShell's conversion
error wrapper; one history array lacked the PS5 serialized `value`/`Count` ETS
shape. Both candidate boundaries are corrected without changing expected output.
Four additional empty/singleton/nested history-array cases bring the matrix to
201; these new shapes still require the Windows oracle. Promoted rank values,
Score parameter overflow binding, fractional options and tied selection matched
in that first run. The original PS implementation remains authoritative.

Actual retained-adapter qualification is additionally gated by
`CUCP_SMART_PLAN_TEST_HOST`, the absolute matching NativeHost DLL or EXE path.
The test imports current `_Invoke-LegacyCompatibility`, option/quoting readers,
and `Invoke-MacroSmartPlan`; only history/port/native acquisition is stubbed.
All 201 cases compare complete emitted payload/error/exit, exact acquisition trace
and the actual Console output captured in a StringWriter, including CRLF,
indentation, JSON property order and serialization depth. Console output is never
reconstructed from a parsed payload.

The single test seam inserts elapsed=0 immediately before each implementation's
existing Brief/JSON formatting branch, updating original `$payload.elapsed_ms`
or retained `$state.payload.elapsed_ms` as applicable. No other field or emitted
text is normalized. Original 201 isolated-kernel and prefix checks remain.
Semantic errors before any query (missing label, invalid numeric options) exercise
the production evaluation wrapper as well as replay-time errors. This adapter
suite must pass before claiming equivalence of the source replacement.

The registered evaluation wrapper preserves the harness semantic-error boundary before replay. The adapter independently validates exact query order and argv, permits at most five probes and six pure replay calls, and checks completion status/boolean/exit consistency. It never executes recommended commands.

First actual-adapter comparison (6331f361/job110680307239) passed 131/201
cases. All 70 differences were the same raw JSON field-order issue: UIA pattern
evidence placed invoke_pattern after rect/click_point, while the original places
it before those fields. The candidate now inserts it in the original position.
Two managed contracts check both best and candidate evidence order. Full Console
comparisons and all 201 fixtures remain unchanged for requalification.

## Qualified retained adapter

Commit `aadbc58aa9dcc2254a3361cf8963429197859f22` passed exact
[CI run 36957910828](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36957910828)
with all four jobs successful. Windows job `110684909869` explicitly recorded:

- 23 isolated managed SmartPlan captured-reply contracts passed
- All 201 pinned-kernel payload/error/exit cases and every captured-prefix query check passed
- All 201 actual retained-adapter comparisons passed, including untouched Console text,
  complete deterministic payload/errors/exits and exact read-only acquisition traces

The actual adapter test completed at 2026-10-02 03:08:51 UTC; the combined
SmartPlan step completed at 03:08:58 UTC. Assertions and original oracle output
were retained through the field-order correction. Only elapsed time was zeroed
at the documented pre-format seam. This qualifies captured-reply planning and
adapter behavior; it does not constitute interactive Windows GUI validation.
