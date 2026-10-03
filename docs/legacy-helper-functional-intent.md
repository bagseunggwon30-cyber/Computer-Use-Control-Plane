# Helper functional-intent qualification, candidate only

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

Windows execution of this new tier, its refusal paths and distinct-geometry cases
is still required. Portable validation cannot qualify those runtime observations,
authorize production activation or earn source retirement.

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
