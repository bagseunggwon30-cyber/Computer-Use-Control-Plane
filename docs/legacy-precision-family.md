# Legacy precision family runtime

Coordinate-anchor, point-plan, target-validate, anchor-history scoring, cache
identity, and validation calculations run in
`pcucp-next/dotnet/PcuCp.LegacyPrecision`. The 15 original PowerShell function
bodies in `scripts/cucp.ps1` have been replaced by the qualified adapters, with
14 shared precision transport functions inserted once. The duplicate adapter
fixture has been removed, and `.github/migration-adapters.json` selects the
production source for precision qualification.

PowerShell still supplies retained window/UIA acquisition and exact legacy JSON
formatting. The planners do not actuate input. The immutable differential oracle
remains tree `bf895d3120dd5e145f360cb1c41e1d79a061d048`, `scripts/cucp.ps1`.

## Runtime and authority

`LegacyPrecisionKernel.Execute(operation, args, IPrecisionReadEffects)` runs one
complete planner invocation in-process. Its seven fixed read interfaces acquire
a coordinate map, hit test, coordinate profile, hit scan, child point plan,
history lines, or cache entry. Typed point, scan, and child-plan records carry
only those parameters. There is no generic command, shell, or input effect.
Acquisition retains `_Build-CoordMap`, `_Native-HitTestPoint`,
`_Build-CoordProfile`, and `Invoke-NativeHelper`. Casing and command-token rules
use the qualified `LegacyTextKernel`; the `LegacyCoordinateKernel` API remains
unchanged. Child point-plan acquisition calls the planner directly and captures
Console output, without a PowerShell child launcher.

The NativeHost command `legacy-precision-session` accepts no additional CLI
arguments. One strict UTF-8 reader serves startup and replies independently of
the inherited console code page. `ReadStartup` bounds input to 4,194,304 characters
before parsing. Exactly one initial U+FEFF is permitted for Framework's redirected
input encoder; repeated, embedded, and later-frame BOMs are rejected.

Startup schema `cucp.precision-session/v1` requires exactly `schema`, `operation`,
`args` (a tagged wire value), and `culture`. Planner operations are `coord-anchor`,
`point-plan`, and `target-validate`. Their arguments are exactly `rest`,
`cache_seconds`, `brief`, `now`, `history_file`, `history_max`, `cache_dir`, and
`elapsed_ms`. Eight pure helpers also use this command: `history-read`,
`history-distance`, `history-score`, `cache-key`, `confidence-rank`, `size-class`,
`edge-distance`, and `child-plan-envelope`. Helpers complete without read or
filesystem effects. The 500-record helper fixture exceeds 1MiB and stays below
the startup limit; larger inputs fail rather than being truncated.

Effect replies use independent 48KiB byte chunks and the shared
`LegacyExecutionWire` scalar, array, and object tags. Precision imports no execution
authority or coordinator. Frame fields, sequence, and tagged types are checked.
PowerShell returns preserve real arrays, including empty, singleton-null, and
nested arrays. Objects with `value` and `Count` properties remain objects.
History observations are acquired once; a tested reply exceeds 2MiB without
replaying earlier replies or echoing history in the result.

## Persistence boundary

Completion contains `payload`, `exit`, `brief`, `json_depth`, `queries`, and zero
or one terminal `effects`. A cache write binds to the complete payload; a history
append binds its result to `payload.reuse_history.recorded`. Initial script
configuration fixes the history path, maximum, and cache directory. Terminal
messages cannot replace those destinations or request new effects.

The session owns one Stopwatch, stopping it after acquisition and assembly. It
sets elapsed fields before projection and rendering. Legacy depth cutoffs use
depth 10 for history and 14 for cache; only cutoff subtrees request the fixed
invariant `LanguagePrimitives.ConvertTo` string conversion. All remaining
properties, arrays, values, and types must match the prepared JSON.

The adapter renders all final Console variants before persistence, including
history success and failure. A SHA-256 receipt binds the exact serialized bytes.
Every possible bounded commit reply is serialized before writing. After a write,
the session emits only the prebuilt outcome; a broken stream produces an uncertain
outcome without retrying persistence or assembling a new report.

`LegacyPrecisionStorage` is separate from the pure registry. Its constructor fixes
the history file, cache directory, and clock. Cache keys must be 32 lowercase MD5
characters. It preserves cache TTL and future timestamps, UTF-8 BOMs and newlines,
history trimming, and suppressed legacy write failures.

The separate `legacy-precision-storage` command calls `RunStorage` with schema
`cucp.precision-storage/v1`. It permits only `history-lines`, `history-file-read`,
`history-file-score`, `history-append`, `cache-read`, `cache-path`, and `cache-write`.
The planner command rejects those storage operations. Storage replies are also
prepared before writing. Retained PowerShell `ConvertTo-Json` supplies exact
legacy file formatting. Precision planners and filesystem operations are not
registered under `legacy-compat`.

## Behavior retained

- Source screen points must be positive. Acquired geometry retains negative
  desktop origins and clipping; anchor normalization rounds to six digits using
  midpoint-to-even rounding
- Point-plan acquires hit-test, coordinate profile, eligible cache lookup, then
  hit-scan on a miss. A specified mismatching target prevents scan and cache write
- Cache identity includes root HWND, title, process, and coordinate signature.
  Legacy cache payloads keep their schema, including no schema. The adapter accepts
  that completion only after its matching observed cache read, with the same key,
  boolean `from_cache=true`, and no terminal effects
- Target-validate applies guards, confidence, coordinate risk, target size, and
  inside-rectangle checks. An edge warning remains advisory; point-plan retains
  its original more permissive `safe_to_act` result
- History scoring preserves exact/near overlap, duplicates, signature checks,
  safety ratios, score clamps, and advice. Explicit record/learn flags authorize
  history writes; `--no-history` suppresses both reading and recording
- History trimming preserves negative-index wrapping and drops out-of-range
  indices, including repeated valid indices produced by a maximum of one
- PS5 no-output acquisition is false during planning and renders as an empty
  object when retained as evidence. JSON null properties stay null. Object-member
  arrays stringify as `System.Object[]`; replacing `recorded` moves it to the end
- Recommended commands remain data. No planner clicks, types, or moves the pointer

## Qualification and integrated gate

The exact family passed Windows qualification at commit
`e9e015c6bc7b39d52999dccccf6bb4316a6c8dfe` in
[run 37007340738, precision job 110838651637](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738/job/110838651637):

- 509 isolated C# assertions and 21 Python tests, with no skips
- 174 candidate planner cases and 174 exact actual-adapter cases
- 138 helper cases and eight byte-for-byte filesystem cases
- 14 tagged codec values and three native parent-code-page cases
- Ordered observations, every query prefix, full payloads, errors, exits, brief
  output, and raw Console comparisons; only elapsed/clock seams are normalized
- Large history, malformed transport, rejected precommit changes, write failure,
  and bounded terminal persistence checks

Artifact `11226236687` contains logs and the normalized source map. All 235
production and 29 draft function extents were independently rehashed before
promotion. The 29 promoted precision bodies match the qualified draft exactly
and occur once. The codec test follows the promotion manifest, so it checks
`scripts/cucp.ps1` after precision is enabled.

That family result qualifies the exact runtime and adapters before integration.
The promoted source must still pass the production precision gate and the bundled
full regression on the exact integrated commit. Neither local Linux checks nor
the earlier family result establishes that integrated result.

Run isolated checks with an installed SDK:

```text
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyPrecision.ContractTests -c Release -- --self-test
python -m unittest discover -s tests/python -p "test_legacy_precision*.py" -v
```

On Windows, run `python pcucp-next/packaging/migration_qualification.py run --family precision`.
The runner builds the matching host and enables production checks through
`CUCP_PRECISION_TEST_HOST`. `CUCP_PRECISION_DOTNET` optionally selects the SDK used
by Python tests. A skipped Windows or adapter test is not qualification evidence.

`LegacyPrecisionKernel.Advance` remains the deterministic captured-reply oracle.
Replies require exactly `kind`, `args`, and one of `result` or `error`; unknown or
duplicate fields, changed arguments, reordered observations, and unused replies
fail closed. The contract runner accepts JSON request arrays on stdin. Its
`storage-fixture` operation is restricted to named temporary directories and is
absent from production.

The suite stubs external acquisition and does not operate a live desktop.
Mixed-DPI/window-race and provider behavior remain responsibilities of the
acquisition layer and later Windows acceptance tests.
