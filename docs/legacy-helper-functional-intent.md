# Helper functional-intent qualification, candidate only

## Generated assembly-name observation at 76df5068

Windows run `37118214314` at `76df50689a3ad2f6315063f1bec7f0a5cb6a524d`
reported one historical Args-only classifier failure: the actual PS5-generated
assembly name was `0txnh5uz`. The classifier had incorrectly required an initial
letter/underscore as though the assembly name were a C# source identifier. The
complete Task-to-Type error, both responses, paths, acquisition/effect trace and
source seams were otherwise unchanged. No functional comparison failed in that
run, but the overall gate remains failed and requires fresh qualification.

The raw 21,879-byte observation is retained separately as
`tests/fixtures/legacy-helper/observed-args-only/ocr-digit-assembly-37118214314.stdout.bin`,
SHA-256 `3c5eed183dff3c150a7e452d4b8f12db08f52ec9861e51e7c30b7fb7f92487bb`.
It came from artifact `11272089122`, archive SHA-256
`d8d1921f7fc8352fa0bdcc75d2a8f2dba77627f2ea2f9c928aeb4d7976065b41`.
The original 18-record manifest and every original raw record remain unchanged.

Only the generated assembly token now permits an ASCII digit in its first
position, retaining the existing 1–128-character alphanumeric/underscore bound,
the exact surrounding error, and one shared name across both responses. Tests
replay the exact raw observation and cover each initial digit, length boundaries,
invalid/control/Unicode separators and inconsistent names. No runtime/provider,
functional output, diagnostic text outside that token, or qualification rule is
relaxed. This classifier still labels the original OCR failure unqualified.

This step corrects the oracle's intended working behavior after observing further
defects in the published PowerShell bodies. It changes no runtime candidate,
production caller, launcher, registration, user computer or original source.
There is no source retirement or production activation in this patch.

## Evidence and three distinct tiers

Source extraction remains pinned to public commit
[`3e892ab02395bdc916a5814e39d4154efd1f6249`](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/commit/3e892ab02395bdc916a5814e39d4154efd1f6249),
verified tree `e36329b2a6b07539faacd070d661bc0e3819140d`.
All original function and facade hashes remain unchanged.

| Driver mode | Permitted body changes | Meaning |
| --- | --- | --- |
| Default `exact-original` | Existing 52 acquisition type names only | Retains and classifies the observed original Args binding failure; original dispatch stays failed/unqualified |
| `-CorrectedIntent` / `corrected-intent` | Same type seam plus 34 Args names | Historical Args-only tier, retaining its OCR and score-sort defects; never substitutes for the working contract |
| Both `-CorrectedIntent -FunctionalIntent` / `functional-intent` | Those seams plus four explicitly verified sites | Intentional functional bug correction with numeric ranking and stable acquisition-order ties; never exact-original parity |

[Windows run 37107497042](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37107497042)
at `bb98df41d120cde6c6a2a18628e385d7ad432709` observed six failed Args-only cases.
All 18 oracle processes completed with bounded, complete evidence. Four cases
failed the independent contract before candidate replay. Fourteen reached the
candidate; 12 compared exactly, and two exposed order/selection differences.

- Both OCR success requests stopped after `ocr.loadFile` with a Task-to-System.Type
  conversion error, followed by `ocr.removeTemp`. Initialization was cached once.
  In the verified nested helper, typed `$T` and assigned `$t` refer to the same
  case-insensitive variable. This was observed with inert acquisition, not real
  WinRT capture. No candidate process ran for the failed OCR comparison.
- All three UIA culture cases returned scores `[50,80,100]` and selected
  `resave` / 50 instead of `Save` / 100. Their query/effect sequences were exact.
  The hashtable sort does not establish descending score order on PS5; Microsoft
  documents [key-value sorting as starting in PowerShell 6](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/sort-object?view=powershell-6).
- The modal tie case returned the same 32 typed records and `wait`, but started
  with `small 21` rather than `small 0`. The UIA tie case returned the same first
  16 acquired records, but selected `Save 10` rather than `Save 0`. These are
  observable ordering/selection differences, not numeric representation changes.

All 18 complete Args-only stdout streams, totaling 416,593 bytes, are retained
under `tests/fixtures/legacy-helper/observed-args-only/`. Their manifest pins
case inputs, raw sizes/hashes, successful process/evidence flags, public commit,
run and archive SHA-256
`e44a60abfc64f21db097b033dc52f0a06e03bb91347f12ef232534e514278741`.
These files contain observed JSON data and hashes, not executable source bodies;
they are never evaluated. The unchanged original binding evidence is also retained.

## Four-site correction and guard boundary

The functional tier renames exactly two uppercase `$T` variable AST extents in
the verified nested `_AsyncWait` to `$ResultType`: its parameter declaration and
the argument to MakeGenericMethod. All lowercase `$t` task references remain
unchanged. The original async call sequence, error paths and cleanup are retained.

Exactly two full `Sort-Object -Property score -Descending` command extents are
replaced by a call to `_Oracle-StableScore`. That helper is a literal counted
PowerShell function with a pinned source hash. It performs a numeric descending
insertion sort, moves only strictly lower scores, and emits each original record
with WriteObject(item,false). Equal scores retain acquisition order; dictionaries
are neither decorated nor mutated, and no new acquisition occurs.

The driver verifies original absolute UTF-16 extents, AST kinds, literal text,
owning/nested functions and closed invocation shapes. Original, type-only,
Args-only and functional hashes are separate. The union of edit sites must be
disjoint and reconstruct the same single function definition. Python independently
reassembles unchanged byte intervals and checks the final hashes. The functional
seam is four sites, separate from the unchanged 34-name and 52-type seams; all
23 emitted acquisition types still face the original assembly identity guard.
Duplicate, changed-text and wrong-replacement plans fail before facade compilation
or action import. Prior source/facade/type/Args refusals remain mandatory in the
new tier. No caller-supplied replacement or generic script execution is added.

## Historical observations do not define the working contract

Each historical case still runs the original and Args-only modes before the
functional comparison. Their classifications and raw streams are separate.
Nested subtests allow a failed baseline check to retain its failure while the
same case still collects functional evidence. Infrastructure failures remain
test failures and cannot be accepted as a baseline observation.

The Args-only observer first checks complete raw evidence, exact input/source/
edit provenance and all typed fields against the pinned snapshot. Only two
generated OCR filename identities and one generated assembly name inside the
complete known Task-to-Type diagnostic may vary. Paths must have the exact
generated filename shape, contain no control characters, fit 32,767 UTF-16 code
units, have distinct generated IDs and normalized lexical Windows paths, share
one normalized directory, and retain one-to-one
capture/load/cleanup uses. Both errors must reference the same bounded assembly
identifier. No other diagnostic text is trimmed or normalized; raw bytes remain
unchanged on disk.
No native-file identity, link or short-name resolution is claimed: these inert
fixtures do not create the image files.

A typed candidate permutation with best/score or modal recommendation still
coupled to its actual first record is recorded as `changed-baseline-observation`.
It remains `not-functional-qualification`, with raw order preserved. Membership,
caps, identity, types, acquisitions and all unrelated fields must remain exact;
any other divergence fails. This diagnostic distinction avoids treating an
unstable broken permutation as the functional release goal. It never normalizes
the new functional tier or the candidate's response.

The functional tier requires full exact response fields/types, numeric descending
ranking, acquisition-order ties, and best equal to the exact first highest-scoring
record. Candidate replay must match that full order and selection and exhaust all
provider calls with exact arguments. Independent fixtures cover all six actions,
cultures, OCR retry/cache/truthiness, scan/result caps, root-child selection, and
two additional tie cases with different names, handles and geometry. Those new
cases have no historical Args-only baseline and make no claim about one. They
run original binding observation and the strict functional qualification.

## Deliberate compatibility impact

The candidate already implements the intended numeric/stable behavior; this patch
does not change it. Future activation would make OCR complete beyond the original
type-variable failure and would select the highest-scoring result. Equal scores
would select the first acquired candidate instead of PS5's incidental permutation.
Those changes are intentional functional corrections, not original parity.

Ordering is consumed. In the pinned published source,
`LegacyExecutionWatchRecovery.cs:33` selects modal_candidates.FirstOrDefault;
lines 38–50 use its score/is_modal/title/class, and lines 59 and 83 embed complete
modal evidence. Recovery routes are reachable through `scripts/cucp.ps1:7947`
and `:7955`. The command reference explicitly promises sorted modal candidates
and recommendation thresholds. Ranking can therefore change a recovery category,
and tied order can change selected evidence. Existing live-control/confirmation
guards remain essential and unchanged.

UIA-fast emits best, score, ordered candidates and click_point as a public direct
pipe API. Both fast actions are advertised in the published changelog even though
no production literal callers were located. Ordinary wrapper OCR/UIA macros use
different actions. Wrapper forwarding still omits Label/X/Y/W/H; that limitation
is neither repaired nor used to drop direct-pipe coverage. Interactive acquisition,
real OCR capture, focus/input, mixed DPI and elevation remain unqualified.

The Windows fixture qualification below covers this tier, its refusal paths and
distinct-geometry cases. It does not qualify real acquisition, authorize production
activation or earn source retirement.

## Windows fixture qualification at 89aa36fd

[Run 37110868531](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37110868531)
passed at public commit
[`89aa36fdae7b11f901fc1d1332b2391ef226c436`](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/commit/89aa36fdae7b11f901fc1d1332b2391ef226c436),
tree `e12363426425f3ebe8c355775b757d6748d04155`. The helper suite recorded
165 methods: 157 passed, eight individually skipped, zero failures/errors and
no class-setup skips. The skips were one Linux refusal control and seven separately
gated staged lifecycle methods. Verbose raw outcomes establish these counts;
one passing diagnostic method prints its description on a separate line.
The same run passed 117 action contracts, 45 wire contracts and six raw-process
evidence tests. The portable host, net48 service/transport and inert facade builds
completed with zero warnings/errors.

The retained [artifact 11269787440](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37110868531/artifacts/11269787440)
contains 1,099 files. Its archive SHA-256 is
`15bb68b4da10c36ecd066f5fc57d2cb42ac9aa38efd7a1e68aa6a0f98a08e35a`.
The helper-suite evidence is `06-gate-34c463488f31.json`; its 30,233-byte raw
stderr has SHA-256
`f1ea4d8602360168cfd4778054c947bf65e456398422843752ac4d0edc2b72e5`.
Reinspection verified all 20 PowerShell 5.1.26100.33438 oracle/net48 candidate
fixture pairs, covering 47 requests and 1,449 ordered acquisition calls across
all six actions. Every one of the 40 processes exited zero with
complete bounded raw streams, empty stderr and no timeout, truncation, launch,
read, stdin or drain error. Full typed responses, array order, score/best/click
selection, acquisition arguments/order and cache/clock/request state match the
independent functional expectations and candidate replay. No functional order or
selection normalization was applied.

All pairs retain the published source pin above and the exact 52 type-name,
34 Args-name and four functional-site censuses, including all 23 guarded types,
eight function hash records and the pinned stable-sort helper. Extracted server
bytes retain raw SHA-256
`31742c3a48c3305f26751ea9c3b8b8db5592a0aa5f192ccdfea5795252731e81`
and normalized SHA-256
`173c5cde4c9ef282835d5add1e3e11fbf9f0756a7aed359750b00030f32ab7a8`.
Source/facade/type/Args/functional edit refusals and the distinct-geometry tie
checks passed on Windows. No guard or original body changed for this result.

All 18 historical Args-only classifications recorded `exact_recorded_match=true`
and `args_only_qualified=false`. Only the OCR success-history case used the
explicitly bounded two-path and one diagnostic-assembly-name normalization;
its original raw streams remain intact. None needed the changed-permutation
classification. Original startup and dispatch observations still say failed and
unqualified, including the unchanged startup exit 1 and zero-dispatch binding
failure. A passing observation classifier does not qualify those original bodies.

This qualifies the intended action semantics under inert acquisition fixtures
on Windows, together with the run's owned pipe/lock/process contracts. It does
not qualify desktop enumeration, interactive UIA, actual WinRT OCR capture,
focus/input, IME/clipboard, mixed DPI, elevation or cross-principal access.
The independent [staged lifecycle run 37110868522](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37110868522)
at the same commit failed: concrete detached startup returned an error, direct
service boundary probes exited `3762504530`, and the wrapper start process
exited 1. That production startup/bridge boundary remains unqualified; successful
fixture service tests cannot substitute for it. No production promotion or helper
retirement follows from this qualification. This record changes documentation only.

## Local validation

The core patch's portable host passed 117 action and 45 wire contracts. All 20 independent
action fixtures also passed that actual host with exact response types, order,
selection, acquisition arguments and cache/clock/request state. The helper gate
reported 107 methods: 81 passed, 26 individually skipped, zero failures/errors and
no setup skips; five raw-evidence tests passed separately. Full Python discovery
reported 775 methods: 622 passed, 153 individually skipped, zero failures/errors,
plus two class-setup skips. These counts come from verbose outcomes, rather than
subtracting the combined printed skip count. The net48 facade build had zero
warnings/errors. No local PowerShell engine or Windows execution is claimed.

A review follow-up tightened only the diagnostic generated-path boundary and
added slash-alias, NUL and overlong-directory regressions. Its helper rerun
reported 108 methods: 82 passed, 26 individually skipped, zero failures/errors
and no setup skips; 117 action, 45 wire and five raw-evidence checks also passed.
The full-suite result above belongs to the core patch; unrelated suites were
not rerun for this diagnostic-only follow-up.

The counted oracle adds 11,387 PowerShell bytes. Canonical total is 926,481 bytes
across 31 `.ps1` files on this isolated base, with runtime PowerShell unchanged at
607,665 bytes. Raw JSON observation files are non-executable evidence and do not
replace or hide a driver. No source retirement is credited.


## Separate actual-provider qualification

The [owned provider gate](legacy-helper-provider-qualification.md) extends
qualification beyond the inert acquisition fixtures, with explicit candidate-only
working-control expectations and actual WinRT OCR. It does not change the four
functional correction sites, weaken original evidence or normalize the separate
original/compiled UIA provider-identity discrepancy. Windows execution must pass
before this new actual-provider layer is qualified.
