# Legacy precision family candidate

This candidate moves the cohesive coordinate-anchor, point-plan, target-validate,
anchor-history scoring, point-cache identity, and validation calculations into
`pcucp-next/dotnet/PcuCp.LegacyPrecision`. The differential oracle is the immutable
Git tree `bf895d3120dd5e145f360cb1c41e1d79a061d048`, `scripts/cucp.ps1`.

No existing PowerShell implementation is removed by this candidate. Production
registration, the actual retained adapters, and their Windows gate must qualify
before retirement. A successful Linux build does not qualify Windows PowerShell
semantics or desktop behavior.

## Interfaces and authority

`LegacyPrecisionKernel.Advance(operation, args)` is a deterministic captured-reply
oracle interface. Its operations are `coord-anchor`, `point-plan`,
`target-validate`, `history-read`, `history-distance`, `history-score`,
`cache-key`, `confidence-rank`, `size-class`, `edge-distance`, and
`child-plan-envelope`.

The macro operations accept the original `rest` tokens plus explicit
`cache_seconds`, `brief`, `elapsed_ms`, `now`, `history_file`, `history_max`,
`cache_dir`, and `captured_replies` seams. Replies require exactly `kind`, `args`,
and one of `result` or `error`; duplicated/unknown fields, reordered observations,
changed argument values, and unused replies fail closed. Arrays stay actual JSON
arrays. An object containing `value` and `Count` is not an array wrapper.

`LegacyPrecisionKernel.Execute(operation, args, IPrecisionReadEffects)` runs the
same algorithms in one process. Its seven fixed read interfaces acquire a
coordinate map, hit test, coordinate profile, hit scan, child point plan, history
lines, or cache entry. Typed point/scan/child-plan records carry only the parameters
for those operations. The interface has no generic command, shell, macro, or input
actuation method. The coordinate-map provider should call the already qualified
`LegacyCoordinateKernel.Map` after acquiring its snapshot; this candidate does not
change that kernel's API. Casing and command-token rules use `LegacyTextKernel`.

The production transport is `LegacyPrecisionSession`, exposed through the dedicated
`legacy-precision-session` host command. `ReadStartup` reads a maximum of 4,194,304
characters before parsing; the caller must not call an unbounded `ReadLine` first.
One leading U+FEFF is accepted only at the beginning of this startup line for
Framework's redirected-input encoder. Repeated/embedded BOMs and BOMs in later
reply frames are rejected; the same character bound still applies.
The startup schema is `cucp.precision-session/v1` with exactly `schema`, `operation`,
`args` (tagged wire value), and `culture`. Planner arguments are exactly `rest`,
`cache_seconds`, `brief`, `now`, `history_file`, `history_max`, `cache_dir`, and
`elapsed_ms`. The same command permits the eight pure helper operations listed
above; those immediately complete without filesystem/read effects. The 500-record
helper fixture exceeds 1MiB but remains below the explicit startup limit. Larger
startup values fail before any persistence; no truncation or fallback occurs.

Effect replies use independent 48KiB byte chunks and the shared
`LegacyExecutionWire` scalar/array/object tags. The precision session imports no
execution authority, coordinator, or actuator. Sequence, frame shape, and tagged
value types are validated. Large history observations are acquired once and are
not resent; a tested history reply exceeds 2MiB.

The complete result contains `payload`, `exit`, `brief`, `json_depth`, `queries`,
and zero or one terminal `effects`. `cache-write` binds to the retained complete
payload. `history-append` binds its boolean outcome to
`payload.reuse_history.recorded`. The session owns a single Stopwatch, stops it after acquisition/assembly, and
updates the retained elapsed field and brief token before projection/rendering.
For legacy depth cutoffs it walks the exact retained write value at depth 10/14;
only cutoff subtrees request the fixed invariant `LanguagePrimitives.ConvertTo`
string conversion. Every other field, value, array, and property must match the
prepared serialized JSON recursively. The caller renders the complete Console,
including both history-success/failure variants, before requesting persistence.
A SHA-256 receipt binds the exact serialized bytes; the terminal acknowledgement
cannot alter the record, key, or destination. All possible bounded commit frames
are serialized before writing. A broken stream after persistence produces an
uncertain outcome and never a retry or newly assembled report.
The in-process interface avoids repeated large frames entirely. The legacy bridge
has a smaller transport budget than the candidate's 4MiB fixture input budget;
large production observations must use the in-process coordinator.

`LegacyPrecisionStorage` is separate from the pure registry. Its constructor fixes
the history file, cache directory, and clock. It permits only those files and
32-character lowercase MD5 cache keys. It implements missing/corrupt-cache misses,
TTL boundary/future-clock behavior, UTF-8 BOM/newline writing, history append and
tail trimming, and legacy suppressed write failures. The separate `legacy-precision-storage` command calls `RunStorage`, with schema
`cucp.precision-storage/v1`. Its exact allowlist is `history-lines`,
`history-file-read`, `history-file-score`, `history-append`, `cache-read`,
`cache-path`, and `cache-write`. The planner/helper command rejects these storage
operations. Paths and configuration are fixed by the validated startup, and its
write replies are prebuilt before persistence. Serialization is supplied as
an explicit boundary: staged adapters retain PS5 `ConvertTo-Json` depth/formatting
until a standalone serializer has its own qualification. Storage operations must
not be added to the pure compatibility dispatcher.

## Behavior retained

- Source screen points must be positive, while mapping snapshots retain negative
  desktop/window origins and visible clipping. Anchor normalization uses six-digit
  midpoint-to-even rounding and preserves the selected window's original geometry
- Point-plan performs hit-test, then coordinate profile, then cache lookup when
  the precheck permits it, then hit-scan on a miss. A specified mismatching target
  prevents both scan and cache write. Cache identity includes current root HWND,
  title, process, and coordinate signature
- Point-plan keeps its legacy permissive `safe_to_act` result. Target-validate
  applies the stronger target guard, confidence, high-coordinate-risk, tiny/large
  element, and inside-rectangle checks. An edge warning alone remains advisory
- History score uses exact and normalized-near matches, legacy duplicate handling,
  recent signature comparison, safety ratio, score clamp, and original advice.
  History writes occur only for explicit record/learn flags and are suppressed by
  `--no-history`; disabled history does not query the file
- All planners retain commands as data. None executes `recommended_command`, moves
  the pointer, clicks, types, opens an authenticated service, or changes permissions
- PS5 no-output acquisition values remain false during planning and serialize as
  empty objects when retained as evidence. Ordinary JSON nulls inside returned
  objects remain null. Object-property array stringification uses `System.Object[]`,
  and a replaced history `recorded` property moves to the end in raw Console JSON

## Qualification

Run the isolated contracts with an installed SDK:

```text
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyPrecision.ContractTests -c Release -- --self-test
python -m unittest discover -s tests/python -p "test_legacy_precision*.py" -v
```

The contract runner also consumes a JSON array of `{operation,args}` requests on
stdin. `CUCP_PRECISION_DOTNET` can select the SDK executable used by Python tests.
The test-only `storage-fixture` operation is restricted to explicitly named system
temporary directories and is absent from the production kernel.

The Windows candidate suite extracts the actual functions from the pinned tree,
stubs only external acquisition, and compares full unformatted payloads, ordered
queries, every query prefix, errors, exits, brief text, and raw Console output.
The Console comparison independently reuses PS5's retained serializer: a depth
truncated Console value never substitutes for the full payload oracle. Only
explicit elapsed and fixed clock seams are normalized. Separate helper tests
cover history scoring, confidence thresholds, geometry edges, and cache keys.
Filesystem fixtures compare generated bytes, BOMs/newlines, timestamps/TTL,
trimming, and failed cache writes against the original functions.

`CUCP_PRECISION_TEST_HOST` enables the additional actual-adapter gate against the
matching native host. The focused runner uses the exact real PowerShell fixture
`tests/fixtures/legacy-precision-adapter.ps1` before production promotion, selected
with `CUCP_PRECISION_ADAPTER_DRAFT`. This retains the pinned acquisition oracle
while qualifying the session and separate storage command in the same Windows run.
No pure compatibility registry addition is required. A skipped adapter test is not
evidence that an adapter qualified. The fixture is counted in the PS inventory
and is removed when its glue is promoted; current production bodies are retained.

The suite does not operate a live desktop. Real mixed-DPI/window-race and UIA
provider behavior remain responsibilities of the acquisition layer and later
Windows acceptance tests. The candidate's successful unit tests do not replace
that evidence.

The first combined Windows run at commit
`120b64a605bece965da4637e6510afcbd46fe871` passed 494 isolated contracts, helper
differentials, and all 11 transport tests. It exposed three candidate payload
differences and twelve raw Console differences; the no-output, object-string,
and property-order fixes above address those exact differences. Actual adapters
rejected their first startup output, and the retained filesystem oracle exceeded
its 90-second limit. The next gate keeps exact comparisons and adds a bounded
initial-frame diagnostic, a Framework child-input byte characterization, and
noninteractive storage-oracle stage diagnostics. These repairs remain unqualified
until that Windows run passes.

At repaired commit `a7bffa18b8325fe06f00459324c1f3631f2c896a`, all 174 planner
cases now pass the candidate payload, Console, error, exit, ordered-query, and
query-prefix comparisons. Helper differentials, 507 C# assertions, and all 13
transport tests also pass on Windows. Actual adapters still fail before the first
acquisition: their native startup error reports byte `0xE2`, because incoming
UTF-8 is being decoded through the inherited console code page. The production
entry therefore needs one strict UTF-8 reader shared by startup and replies;
the new ingress fixture tests CP437 and UTF-8 parents with and without BOMs.
The storage oracle completed every file operation and timed out while serializing
test-only `Get-Content` provider metadata. Its line inspection now uses plain
`File.ReadAllLines` values; exact generated-byte comparisons remain unchanged.
Actual-adapter and filesystem qualification are still pending the next gate.

At `f2333bebd53e28e59a05795abfeb90275dc67d09`, UTF-8 startup and all three native
console-code-page cases pass. Candidate/helper comparisons remain green, and the
filesystem oracle completes with seven of eight cases passing. The remaining
adapter failures expose PS5 `Write-Output -NoEnumerate` array decoration at the
tagged decoder boundary; terminal semantic equality correctly rejects affected
cache writes. Decoder returns now preserve a single true value with unary comma,
with a 14-value Windows codec test covering empty, singleton-null, nested arrays,
Unicode, scalars, and genuine objects named `value`/`Count`. No object-shaped
wrapper inference is used. The remaining filesystem fix drops out-of-range
negative multi-index selections for a configured maximum of one, preserving the
legacy repeated valid indices. These repairs await the next actual Windows gate.
