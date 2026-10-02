# App-profile captured-reply candidate

`pcucp-next/dotnet/PcuCp.LegacyAppProfile/LegacyAppProfileKernel.cs` is an isolated
qualification candidate. NativeHost does not compile or register it. The
15,623-byte original `Invoke-MacroAppProfile` remains authoritative. Nothing in
this stage retires PowerShell, enumerates a real window, probes a browser/UIA
provider, launches an application, or reads/writes history.

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
computed confidence is medium/high. A future acquisition adapter must
independently check these gates and the descriptor's score/recommendation before
calling the original append function. It must retain original append behavior,
including timestamp generation, the 400-record tail, failure reply and exact
history destination. Captured fixtures return a fixed record and never write it.

The future adapter must retain actual acquisition and console serialization. It
must not execute arbitrary descriptor commands or generated probe/task commands.
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
The full payload, query sequence/argv, error, exit and actual original Console
text are compared. Candidate output is rendered through the same legacy
PowerShell JSON/Brief formatting boundary. Every captured prefix must request
exactly the next original query. This is candidate qualification, not an
actual-adapter test; a later source replacement needs its own real bridge test.

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
No production link, dispatcher operation, adapter change or inventory retirement
is included. After strict Windows proof, central integration would require the
NativeHost compile link/closed registry operation, a bounded acquisition adapter,
its independent validation, an actual-adapter differential, and the inventory
and migration-matrix update. Main-branch merge remains a separate approval.

At `96f1f2a4` / run `36959747063`, the independent Windows job passed all 296
Unicode alias score comparisons and 29 managed app-profile contracts. The first
app-profile oracle exposed a capture-harness variable collision: PowerShell
`$brief` output text overwrote the case-insensitive `$Brief` boolean before the
candidate arguments were serialized. The harness now uses a distinct text
variable and records the original fixture's explicitly cast boolean. All payload,
error, Console and query assertions remain unchanged. Full app-profile parity
still awaits the corrected Windows run; the original implementation is retained.


At `015de0e2` / run `36960182124`, 454 of 496 complete cases matched; the 42
remaining cases exposed first-seen UIA group order, NLS versus ICU invariant
casing, wildcard casing, case-insensitive bare-token quoting, and an oracle
batching issue. The captured-prefix assertion also stopped at the first culture
mismatch. The assertions remain exact.

The original public script dispatches one top-level macro and exits; it never
changes `CurrentCulture`. The initial fixture alone mixed cultures in one
PowerShell process. The inherited [PowerShell regex cache implementation](https://raw.githubusercontent.com/PowerShell/PowerShell/v6.0.0/src/System.Management.Automation/engine/lang/parserutils.cs)
keys case-insensitive patterns without culture. A new explicit fresh/warmed
characterization runs before the complete comparison and asserts the observed
cache difference. The complete suite then retains all cases, grouped into fresh
per-culture oracle processes, matching the public call boundary. No failing case
or assertion is removed. Original output is still captured twice to verify
Console determinism.

The candidate now retains first-seen role-group order before Count sorting.
Its invariant casing is shared with strategy normalization through Windows NLS
`LCMapStringEx`; a direct .NET Framework comparison covers Kelvin sign, long s,
dotted/dotless I, sigma, combining sequences and supplementary letters under
four cultures, for whole strings and individual UTF-16 characters. That direct
comparison must pass before claiming casing parity. The shared TaskPreset
quoter now preserves original case-insensitive, current-culture `-match`; a
separate exact original QuoteToken/StepString comparison covers the same corpus.
The existing task/preset/form/SmartPlan assertions are unchanged. All shared
changes still require their next exact-commit Windows qualification.
