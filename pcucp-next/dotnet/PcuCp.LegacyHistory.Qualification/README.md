# History reducer qualification candidate

Status: **candidate-only; no Windows parity observed; no production cutover**.
This executable is intentionally not referenced by NativeHost, packaging, the
Python CLI or the production PowerShell wrapper. Existing helpers, callers,
`_History-Append`, `_AppStrategy-Append`, trajectory writes and recorder replay
are unchanged. This is a qualification kernel, not a new native operation.

## Scope and source identity

Four retained functions from `scripts/cucp.ps1` in published, qualified Git tree
`d4c9660d40c7e909f18afb166a8e846798f63b1d` are identified by metadata only in
`tests/fixtures/history-reducers/original-functions.json`. This manifest contains
no executable source. Each exact UTF-8 function byte span has its own SHA-256;
the full original blob (410892 bytes, SHA-256
`8a3140745701a828628b13c4741b30063119babbcbd74e5230caae2d49591c4c`)
and the whole manifest are independently verified by the runner and oracle:

| Function | Original source bytes |
| --- | ---: |
| `_History-PickBestStrategy` | 1789 |
| `_History-Stats` | 991 |
| `_AppStrategy-Read` | 522 |
| `_AppStrategy-LastGood` | 349 |
| Total | **3651** |

The Python loader retrieves this exact published Git tree with `git show` into
an exclusively created, owned temporary `.ps1` file. It verifies the complete
source bytes and every pinned span before passing its path to the oracle. There
is no current-file fallback, local-only revision, external download or renamed
source container. The oracle verifies the source again, parses the full source
as data, and loads only the four whitelisted and independently hashed AST
function extents. It never dot-sources or executes the complete wrapper. It acquires only synthetic files
created in a fresh, owned temporary directory and deletes only that directory.
It does not inspect user history, call a provider, launch an app or exercise GUI
control. Its module-independent SHA-256 implementation uses .NET byte APIs.

New test-only PowerShell source debt is exactly the full UTF-8 byte length of
`tests/fixtures/history-reducers/oracle.ps1`, a tracked `.ps1` that the canonical
inventory can count. The gate records this exact value on every run. Duplicated
original source bytes are **0**: the four original functions remain only in
their existing production `.ps1` Git blob. No source is embedded in JSON or
another container. No production PowerShell bytes have been removed.

## Captured-data boundary

The kernel accepts a captured file-existence Boolean and physical UTF-8-decoded
lines. There are no path, filesystem, provider or write capabilities. File
encoding/BOM decoding, access errors and changes during acquisition remain a
separate boundary; they have not been silently moved into this kernel.

Candidate stdin is a raw byte pipe read through `Console.OpenStandardInput`,
limited to 16 MiB before full buffering/decoding. Strict UTF-8 rejects malformed
sequences; no replacement or ambient-codepage fallback exists. Stdout uses an
explicit BOM-free UTF-8 writer. Neither changes inherited console code pages.
A separate Windows test creates a new hidden child console, verifies that only
the child owns it, then tests Unicode under CP 949 input/CP 1252 output. It
restores that isolated console's settings; it never changes the user's/shared
console or any global/user/system codepage.

Qualification input is a strict `cucp.history-reducer-input/v1` object containing
`fixtures`. Each fixture has an ID, one of `pick`, `stats`, `app-read`,
`last-good`, an explicit process culture and captured lines. Optional arguments
are `label`, `match`, Int32 `lookback`, and `app_key`. Unknown fields, duplicate
IDs/members, path/operation injection, inconsistent missing-file captures and
unbounded inputs are rejected. The limits (4096 lines, 1 Mi characters per line,
4 Mi characters per capture, 2048 fixtures) bound this inert test surface; they
are not claimed restrictions of the legacy production helper.

## Local inferred checks

From the repository root with a .NET SDK/runtime available:

```text
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyHistory.Qualification -- --self-test
python tests/python/test_legacy_history_reducers.py -v
```

The initial batch contains **66 inferred C# contracts, 30 Python tests and 465
synthetic cases executed under each of two candidate parser profiles**. The
owned-console transport test requires Windows and is skipped on Linux. These
are code-derived expectations and transport/guard checks, never fabricated
Windows observations. The full corpus is generated visibly by `fixtures()`.

Coverage includes reverse physical-file lookback, failed records consuming the
window, malformed/nonmatching records not consuming it, recent successful ties,
case-preserved merged strategy keys, success coercion, array/object interpolation,
blank/null/scalar/array/malformed rows, missing/empty files, midpoint-to-even
rounding, Hashtable resizing/order, original full records, timestamp type/offset
sorting, equal/missing timestamps at 2..100 rows and five cultures.

`HistoryJson.cs` contains a qualification-local copy of the existing PS5
Framework diagnostic reader at the pinned revision. It retains CLR DateTime and
numeric values here rather than using the diagnostic output's interpolated
strings. It neither edits nor depends on the concurrently changing production
diagnostic parser. Its separate PS7 candidate reader is an approximation of the
JSON.NET cmdlet and must pass the actual PS7 gate before any claim of parity.

## Actual Windows differential gate

Run on Windows with both explicit host paths and `dotnet` available, using a new
or empty report directory (existing evidence is never overwritten):

```text
python tests/python/test_legacy_history_reducers.py --differential --ps51 C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe --ps7 "C:\Program Files\PowerShell\7\pwsh.exe" --report-dir C:\owned-test-output\history-reducers
```

This requires actual Windows PowerShell **5.1** and PowerShell **7**; Linux
cannot satisfy it. The harness uses a validated object envelope for the fixture
array, avoiding PS5's root-array single-pipeline-object trap and PS7 singleton
collapse. It tests a singleton batch and the full batch, and repeats full runs
in fresh processes. Every case count, ID, operation, result field, manifest/source hash,
input hash and runtime identity is checked before comparing.

Artifacts include exact candidate/oracle stdout bytes, their SHA-256 hashes,
input bytes, runtime identities, candidate source hashes, full mismatches and
`report.json`. Every launched build/source/candidate/oracle process first records
bounded `.stdout.bin`, `.stderr.bin` and `.process.json` artifacts, including
nonzero exit, timeout, launch failure and truncation status. Original Git source
stdout is explicitly named `.stdout.ps1`, never disguised as a data/source
container; this generated evidence is not a new tracked source copy. Both pipes are read
concurrently with size limits during acquisition; failures retain their first
output rather than discarding it. A timeout or exceeded bound fails the gate.
The no-skip Windows contract mode also assigns a unique evidence prefix to
every inner child, including the owned-console process and its nested managed
candidates, before parsing or assertions. Available pipe bytes are retained
incrementally with `read1`; if a descendant holds a pipe open past the shared
drain deadline, the immutable retained prefix is saved and marked incomplete.
Infrastructure failures cannot satisfy expected-rejection tests. CI requires
the inner-process count, raw files/hashes and a clean actual CP 949/1252 capture.
The oracle checks manifest/source/input file sizes before `ReadAllBytes` and
validates required/unknown fixture fields, IDs, optional strings, Int32 lookback
and aggregate line bounds. It is an internal oracle for the canonical Python
fixture generator, not a public arbitrary-JSON parser API: duplicate raw keys
already collapsed by PowerShell's JSON cmdlet cannot be recovered there. The
candidate's strict arbitrary-input guards remain independently tested. Values are encoded with ordered property/Hashtable entry arrays,
array boundaries and scalar CLR types. Real `ConvertTo-Json -Compress` strings
and captured Console strings are compared exactly. There is no sorting of
Hashtable entries, whitespace normalization, canonical JSON acceptance, rounding
tolerance or ignored mismatch class. Schema/provenance failures block the run.
The two full repetitions expose process-seeded ordering; they are not retries
that can hide a first mismatch.

Even `passed-candidate-parity` means only that these captured runs matched. The
report always says `production_cutover: false`. No wrappers, dispatch tables or
production operations are changed by this runner.

## Required evidence and architectural limits

The following are **open gates**, not observed passes:

- Hashtable key merging is ordinal-ignore-case while PowerShell string `-eq`
  and `-contains` are invariant linguistic comparisons. Composed/decomposed
  Unicode, Turkish I and related pairs must stay distinct where the original
  does. OS NLS versus .NET ICU behavior must be recorded on real Windows.
- Hashtable enumeration depends on runtime implementation/hash behavior. The
  candidate deliberately exposes its actual Hashtable order. A data-only map
  cannot promise byte-identical downstream Console JSON without establishing
  this serialization contract; no acceptance normalization conceals it.
- PowerShell 5 and 7 JSON parsers differ in accepted syntax, root-array pipeline
  behavior, numeric types, empty/colliding properties and DateTime handling.
  Nested-array comparisons/interpolation and nonstandard JSON require the
  pinned real cmdlet observations; the PS7 candidate parser is not JSON.NET.
- `Sort-Object ts -Descending` does not mean parse-to-UTC, latest-file-row, or
  stable-tie selection. The candidate uses culture-aware string comparison,
  typed dates/numbers and an unstable `List.Sort`; Framework/Core equal-key
  permutations, mixed-type coercions and missing-property behavior remain to
  be reconciled against observations. Chosen records preserve all fields and
  nested values rather than projecting a reduced schema.
- File acquisition remains separately owned. Missing and empty files are
  represented and exercised; unreadable/partial/changing files and encoding
  issues need a separately qualified acquisition adapter if production
  migration is later authorized.

Do not replace the retained helpers or reinterpret green SmartPlan,
execution/app-profile stub tests as reduction parity. Those consumers currently
substitute already-reduced values and do not execute these original policies.


## Explicit CI integration

Use `python pcucp-next/packaging/migration_qualification.py run --family
history-candidate --log-dir .migration-logs/history-candidate` on Windows, or
select `history-candidate` in the focused workflow. This separate candidate-only
job installs .NET 8 with full Git history, verifies actual PS5.1/PS7 engines,
runs the managed self-test and no-skip Windows contracts, then requires all six
exact differential executions and their complete artifacts. Default production
family/full scope selection is unchanged. See `docs/migration-batch-workflow.md`.
