# App-profile assembly with retained acquisition

The complete candidate qualification passed at commit `0d5fa6bb87c2b61b2756e2897046fc4dde03e5dd`,
[run 36963644280, job 110702561228](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36963644280/job/110702561228).
That terminal Windows job passed 496 complete app-profile cases, every captured
acquisition prefix, the fresh/warmed culture-cache characterization, 344 complete
strategy scores, 144 direct QuoteToken/StepString pairs, 144 direct .NET Framework
casing triples, and 34 managed boundary checks. Both Python suites reported
three tests OK with no skips. This qualifies the captured kernel and shared text
semantics; a production adapter replacement still needs its independent actual
bridge and exact Console differential before retirement is claimed.

`Invoke-MacroAppProfile` in `scripts/cucp.ps1` is now a thin acquisition/formatting
shim, replacing the original builder and its sole-use private score helper. The pure `LegacyAppProfileController` shares the
kernel's canonical parsing, legacy selection/sort, classification, key derivation,
selected-window projection and record truth/array rules. It validates the closed
acquisition schedule, every exact descriptor/trace, the full target identity,
complete score, route consistency, record result and Brief text. No C# component
performs acquisition or persistence. The shim calls only the original fixed
legacy helpers, retains the three timing seams and Console formatting, and keeps
an independent explicit-record/history/score-threshold/one-Append gate. Its history
destination is the script-owned value captured at entry. Generated commands
remain output data.

At the acquisition-to-JSON boundary, the port reply is explicitly cast to bool,
matching its sole original use as an `if` condition. History is retained as its
actual value; only a runtime `Array` is shallow-cloned to remove PowerShell
`Write-Output -NoEnumerate` wrapper metadata. Literal objects with `value`/`Count`
properties are not unwrapped. A Windows wire characterization covers empty,
singleton, nested and multi-element arrays plus similarly shaped ordinary
objects, null, booleans and strings.

The facade is the same closed `app-profile-advance` operation, now mapped to
`LegacyAppProfileController.Advance`. Original kernel inputs/outputs and direct
oracle remain intact. The facade adds `facade: "cucp.app-profile-controller/v1"`
and `kernel_evaluations` to every response. There are at most seven acquisitions,
seven facade/transport calls and eight kernel evaluations. A pending record query
internally replays a null-result placeholder once to obtain complete score proof;
this performs no acquisition. Only then does that response include
`record_authorization` and a fully validated `record_completion`. Missing or
unsolicited authorization/completion fields fail closed. The shim performs the
one append, assigns only the two existing `strategy_persistence.record` and
`recorded` fields using the original raw value and PowerShell truth expression,
then renders this prepared completion. It never calls the facade after entering
Append, even if Append returns an error object or throws. The original property
order remains intact and elapsed time includes the append.

The receipt has exactly `schema`, `query`, `selected_window`, `app_type`, `app_key`,
`history_file`, `strategy_score`, `strategy_score_sha256` and `context_sha256`.
Its schema is `cucp.app-profile-record-authorization/v1`; `strategy_score` contains
only `recommended_strategy`, `confidence` and `total_score`. A canonical digest
binds the full preflight score, including every losing route and raw evidence.
The context digest binds effective culture, original options and prior captures;
only measured durations and the actual append result are excluded. Digests are
deterministic consistency checks, not credentials or additional authority. The
current target and complete score are recomputed before authorization is issued.
The validated completion fixes the full target and score before persistence;
only the raw record result, its original truth flag and elapsed time change
locally afterward. Shallow score metadata avoids duplicate history in the
response. Pure receipt-replay verification remains covered by the standalone
guard tests, but the production shim never resends a receipt or record result.
The bounded receipt is checked for exact fields and nested duplicates.

`CUCP_APP_PROFILE_TEST_HOST` enables the actual transport/adapter differential.
`CUCP_APP_PROFILE_ADAPTER_SOURCE` optionally selects the external draft; without
it the runner extracts the production macro. Both paths execute the extracted
real `_Invoke-LegacyCompatibility` transport. A transparent counter wrapper
forwards its exact arguments and reply, asserting at most seven facade calls,
eight kernel evaluations and one append. Only the acquisition stubs contribute
to the observed query trace.
The existing 496 cases and all previous comparisons remain, with 24 additional
record-boundary cases in both pure and actual-bridge modes. These force record
result shapes, thrown append, history errors, explicit gates, null/empty history
destinations and the full seven-query/eight-evaluation high-confidence path.
Two additional deep-history cases are preserved. A new near-1-MiB case has a
pre-record frame below the transport limit and an actual record result that
would push a hypothetical final frame above it, for 523 cases. All retain fresh
per-culture oracle processes, exact Console/payload/error/exit comparisons and
elapsed-only normalization. Every recorded case
asserts that the final facade-call counter equals the counter captured when the
Append stub was entered, including returned error objects and thrown failures.
The wrapper also refuses any attempted post-Append transport. These gates passed at `27400c98ea9f460e243240be0f27d39e69ca348c` in
[run 36973181910](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36973181910), with all five jobs green.

The initial kernel qualification was isolated. Central integration now links the
kernel/controller and registers only the closed compatibility operation. The
current shim requires exact-commit Windows qualification before behavioral parity
is claimed. Fixtures never enumerate a real window, probe a browser/UIA provider,
launch an application, or read/write history.

The standalone net8 harness is
`pcucp-next/dotnet/PcuCp.LegacyAppProfile.ContractTests`. It links the existing
pure strategy and command-string helpers. No PowerShell SDK is referenced.

## Captured boundary

`Advance({rest, brief, culture, history_file, elapsed_ms, cdp_elapsed_ms,
uia_elapsed_ms, captured_replies})` replays the original acquisition sequence:

1. `windows`, no arguments, then optional `windows` with `-Match` and the exact
   selected match option. Both replies preserve original enumeration order
2. `cdp_port`, port and timeout `120`, when the original browser/option gates
   request it. A truthy reply requests `native` with the original four arguments
   `-Action cdp-detect -CdpPort <port>`
3. Optional `uia`, with named `-FocusedWindow`, `-MaxElements`, `-MinSize 6` and
   `-Hwnd` arguments, after the CDP probe
4. Optional `history`, with the derived app key; errors at this boundary alone
   are swallowed exactly as the original last-good lookup does
5. Optional `record`, with the original app key, app type, recommendation,
   confidence, integer score, process, class and title parameter values

A missing capture returns `{state:"query", query:{kind,argv}, queries}`. A reply
must bind the exact next kind and string argv and have exactly one `result`
(including explicit null) or string `error`. Duplicate, unknown, mismatched and
unused captures fail. At most seven acquisitions are possible. A null result is
never interpreted as permission to retry.

Completion returns `{state:"complete", payload, exit, brief, json_depth, queries}`.
`brief` is null in JSON mode, including when `--json-only` overrides Brief.
`json_depth` preserves the partial/full `ConvertTo-Json` depth of 12/14. Original
errors return `{state:"error", error, queries}`. The adapter supplies the three
measured durations; the pure kernel does not manufacture wall-clock timings.

The record descriptor is emitted only when `--record-strategy` or
`--remember-strategy` was explicitly supplied, history is enabled, and the
computed confidence is medium/high. The acquisition shim independently checks
these gates and the descriptor's score/recommendation before
calling the original append function. It must retain original append behavior,
including timestamp generation, the 400-record tail, failure reply and exact
history destination. Captured fixtures return a fixed record and never write it.

The shim retains actual acquisition and console serialization. It does not
execute arbitrary descriptor commands or generated probe/task commands.
The advertised task flags and route suggestions remain output data, not live
control authority. This stage does not add a tool or new access.

## Semantics and qualification

The candidate preserves the two enumerations, visible/minimized/foreground truth
conversion, title preference, area ordering, PS5 legacy unstable quicksort ties,
first-ten sample, process/class classification, CDP and UIA gates, role grouping,
label/synonym matching, history and record behavior, command quoting, notes,
payload property order, partial/error exits and Brief text. Captured dictionaries
retain raw geometry, browser metadata and history fields.

`test_legacy_app_profile_parity.py` extracts the exact original functions from
baseline tree `bf895d3120dd5e145f360cb1c41e1d79a061d048`. It substitutes only the
external acquisition functions. Four checked elapsed-expression seams become
zero in the original; no other field, error, or Console output is normalized.
Two checked observation-only assignments also capture the original local payload
immediately before its Console branches. Full unrendered kernel objects compare
to this untruncated original object, while candidate rendered payloads and exact
Console compare separately to the original public depth-limited serialization.
The full payload, query sequence/argv, error, exit and actual original Console
text are compared. Candidate output is rendered through the same legacy
PowerShell JSON/Brief formatting boundary. Every captured prefix must request
exactly the next original query. The separate actual-bridge mode runs the same
523 cases through the retained shim and real native transport, comparing the
original Console text directly; its three timing expressions alone become zero.

The corpus covers option aliases/duplicates/control-like values, no targets,
match/all-window divergence, minimized windows, 2–33-way ties, window/property
truth conversion, malformed/fractional/hex/overflow numeric options and handles,
CDP reply/status/page-count variants, UIA role ties and synonyms, history errors,
explicit recording gates and failures, brief/JSON, and en-US/ko-KR/tr-TR/invariant
culture with Turkish-I, combining accents and Korean normalization variants.
The app-key sanitizer retains PowerShell's default case-insensitive `-replace`
under the requested culture even after invariant lowercasing. Separate Unicode
process/class/title cases exercise exact history-key argv and classification
without assuming regex folding, NLS equality and wildcard matching coincide.
Failures must be preserved and repaired in the candidate; never loosen the
original comparison or replace it with a success-only subset.

The existing strategy score helper's explicit `culture` now also controls alias
regex normalization. Regex case folding is distinct from NLS linguistic equality.
Because the public Regex API has no culture argument, normalization scopes only
its synchronous regex calls to the requested thread culture and restores it in a
`finally` block. It never changes OS culture. Ordinary normalization continues
to use ambient culture. `test_legacy_strategy_culture_alias_parity.py` compares
complete pinned-original scores for Unicode aliases under both ambient culture
and an explicit argument that differs from an en-US harness process. This is an
independent Windows release gate; no inferred Unicode alias table is used.

Local checks:

```
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyAppProfile.ContractTests -c Release -- --self-test
python -m unittest discover -s tests/python -p test_legacy_app_profile_parity.py -v
python -m unittest discover -s tests/python -p test_legacy_strategy_culture_alias_parity.py -v
```

The managed self-tests and source checks are portable. Both strict differential
tests require Windows PowerShell 5.1. A Linux pass does not qualify selection,
NLS/regex, PowerShell conversion/exception strings or Console serialization.
The original isolated stage did not include a production link or retirement.
The controller/shim stage requires its full actual-adapter differential and
inventory/migration-matrix updates. The managed harness now also covers 63
controller guards: exact/missing/unsolicited/duplicate receipts, context/target/
full-score mutations, low or disabled permission, actual record shapes/failures,
Unicode encoding equivalence, 600 KB history without receipt duplication, and
the full prevalidated completion and near-limit request regression. Production
uses at most seven acquisitions/seven facade calls/eight evaluations; the retained
pure replay-only tests also cover the historical nine-evaluation receipt path. Main-branch merge
remains a separate approval.

## Historical qualification findings

The first actual-bridge run, `af9e05e7` / `36970053682`, passed the managed and
culture/text gates but exposed three array-wrapper transport differences (empty
or singleton-false port replies and empty history). Two direct deep-history
comparisons also used inconsistent serialization depths, although their exact
actual-bridge/Console comparisons passed. The typed capture adjustment and
separate raw/public payload observations preserve every existing fixture,
error/exit/query comparison, Console assertion and no-post-Append call check.
Their corrected Windows qualification passed at `27400c98` / run `36973181910`.

Early candidate runs exposed a PowerShell case-insensitive `$Brief` capture-name
collision, first-seen UIA group-order ties, legacy versus modern regex casing,
and culture-contaminated oracle batching. Repairs preserved every assertion.
The public script dispatches one macro and exits; the old [PowerShell regex
cache](https://raw.githubusercontent.com/PowerShell/PowerShell/v6.0.0/src/System.Management.Automation/engine/lang/parserutils.cs)
keys patterns without culture. The suite therefore explicitly characterizes
fresh/warmed behavior and runs each culture in a fresh oracle process.

The `7961bf50` Windows oracle established that invariant NLS casing already
matched, while named cultures needed `LCMAP_LINGUISTIC_CASING`. Kelvin and Turkish
I quoting failures required the [Framework fixed character-class rule](https://raw.githubusercontent.com/microsoft/referencesource/main/System/regex/system/text/regularexpressions/RegexCharClass.cs),
not modern regex equivalence classes. The shared text helper preserves original
valid characters, replacement-run collapsing and terminal-LF anchor behavior;
buffer sizing and casing flags follow the [LCMapStringEx contract](https://learn.microsoft.com/en-us/windows/win32/api/winnls/nf-winnls-lcmapstringex).

The successful `0d5fa6bb` gate covered 496 profiles, 344 scores, 144 quote/step
pairs, 144 casing triples and 34 managed checks. It proves that earlier kernel
checkpoint only. Canonical helper extraction, controller guards, the compact
score-digest receipt, and the retained shim subsequently passed the full 523-case
actual-adapter qualification at `27400c98` / run `36973181910`.
