# SmartPlan captured-reply qualification candidate

The isolated source `pcucp-next/dotnet/PcuCp.LegacySmartPlan/LegacySmartPlanKernel.cs`
is outside NativeHost's compile wildcard. Its independent net8 harness is
`pcucp-next/dotnet/PcuCp.LegacySmartPlan.ContractTests`. It has no PowerShell SDK,
process, filesystem, network, desktop or model dependency. No production
registration or PowerShell retirement is part of this checkpoint.

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

Descriptors are data. A future adapter must keep these existing read-only
acquisition boundaries and never run arbitrary descriptor commands. Precision
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
Do not retire the original 17,025-byte/334-line function until exact Windows
qualification and the later actual adapter comparison pass. Numeric conversion,
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
