# Actual interaction adapter qualification

`tests/python/test_legacy_interaction_adapters.py` exercises the real interaction
hooks, shared execution transport, and compiled NativeHost interaction session.
It imports the existing **870 ordinary** and **12 explicit boundary** cases from
`test_legacy_interaction_parity.py` without editing or replacing that corpus.

The small `legacy-interaction-adapter-oracle.ps1` runner reuses
`legacy-interaction-oracle.ps1`. It AST-loads the actual shared transport and
interaction hook functions into the original captured-leaf harness. It does not
copy a process bridge, dot-source the production script, execute GUI/model/native
leaves, or change any production routing.

The only seams replace wall-clock/observation-ID nondeterminism and observe raw
console and pipeline output. Raw `Console.Write` remains distinct from final
line output. Buffered pipeline strings are checked in order and must precede the
final integer exit result. Compressed transport/startup JSON cannot replace the
captured user-facing payload.

## Run on Windows PowerShell 5.1

Set `CUCP_INTERACTION_TEST_HOST` to the compiled `PcuCp.NativeHost.exe` or DLL,
then run:

```powershell
$env:CUCP_INTERACTION_TEST_HOST = 'C:\build\PcuCp.NativeHost.exe'
python -m unittest discover -s tests/python -p test_legacy_interaction_adapters.py -v
```

`CUCP_INTERACTION_POWERSHELL` may select a specific Windows PowerShell 5.1
executable. DLL hosts also require the runtime command expected by the shared
transport. An explicitly selected missing host or interpreter fails the test;
it never produces a passing skip. Without an explicit host, actual-host tests
are intentionally skipped. PS5.1 remains required for source/console parity.

For supplemental decoded descriptor checks on PowerShell 7, set
`CUCP_INTERACTION_PORTABLE_DESCRIPTORS=1` and run only
`InteractionDecodedDescriptorTests`. This does not establish Windows parity.

## Exact source comparisons and uncertainty

Every ordinary case is compared. Cases without a reached throw during an owned
state dispatch or at/after live input retain exact payload, console, pipeline, exit/error, consumed
reply count, and effect comparisons against the pinned accepted source.

A reached throw after live input, or in a potentially writing owned effect, belongs
to an explicit conservative-uncertainty partition. Its trace must equal the exact
original prefix through the throwing effect; no later effect is allowed. Its
reply count must stop at that boundary. A failed live dispatch requires a partial
receipt with `mutation_may_have_occurred=true` and `automatic_retry=false`; a failed
read/owned-state effect requires the corresponding terminal uncertainty error.
Unused throw replies and ordinary read failures before live input remain exact
source comparisons, including a caught read failure after a successful appshot.
There are no blanket exclusions by operation or error label.

Every `Native` effect is potentially an owned-state write, including non-live
`windows`, OCR and hit-scan actions. The retained `Invoke-NativeHelper` uses
redirected cache files for child requests and may write timeout logs or delete
stale helper locks. There is no proven retry-safe ephemeral boundary. This
classification does not grant live authority or change the kernel oracle: a
throw in the current native call is uncertain, while a later ordinary direct
UIA/Win32 read failure after a successful non-live native call remains an exact
comparison. A terminal uncaught error remembers the earlier native state effect.

A third, narrower partition covers an original terminal planner error after a
reached live/owned-state effect when no earlier callback uncertainty boundary
applies. The complete original trace, consumed count, console, pipeline, and
payload presence remain exact. Only the error is changed, to the fixed
uncertainty prefix followed by the unchanged original error text. This accounts
for terminal errors such as a failed label resolution after an appshot that may
already have written owned files. This partition is counted separately.

The unchanged 12 boundary rows separately cover explicit uncertain live results,
thrown live results, and post-click readback loss.

## Closed descriptors

Negative fixtures cover forged live/sensitive flags, unknown kinds/actions,
cross-operation capabilities, unknown or duplicate options, missing fields,
invalid arity and typed data. They run against both the decoded family hook and
the shared validator's decode-once path. Every rejection must leave the captured
leaf trace empty and consume zero replies. Positive controls prove the harness
can dispatch and preserve control-looking text values as inert native arguments.
Well-shaped but unowned/mismatched observation IDs, screenshot paths, cache keys,
and scored anchor records are rejected before leaf dispatch too.

## Caller argv isolation

The same inert runner AST-loads `_Invoke-LegacyInteractionFamily`,
`_Invoke-LegacyExecutionFamily` and `_Diagnostic-NewState` for a bounded check. One inert host seam
mutates every element of `State.rest` after startup construction, then returns a
fixed exit. Eighteen cases cover the three constructors with null argv, empty arrays,
null/empty elements, singleton arrays and ordinary/control-looking tokens.
The assertions require a distinct array, actual state mutation, unchanged caller
argv and unchanged serialized startup. Expected shape and runtime array type
come independently from a typed-parameter helper containing the original
`rest=@($Rest)` expression. This preserves null/empty elements without requiring
a new string-array conversion. This check executes no process
or acquisition and does not claim that malformed startup argv is accepted by
NativeHost. It leaves the 870 source cases and 12 uncertainty cases intact.
The clone-only disposable PowerShell process fixes the global sensitive ceiling
to Constant=false and places a throwing guard at the compatibility subprocess
boundary. It requires zero compatibility calls and false live/sensitive state;
the existing confirmation gate itself is retained.

Run `37058066571` at remote `031bff14` passed all 870 actual-adapter comparisons
and 12 uncertainty cases, but the first null-argv clone fixture failed at the
added string-array cast/Clone expression. The repair materializes the original
array-subexpression result, then clones existing storage without a string-array
cast or null normalization. The same one-line correction applies to all three
constructors; the next Windows gate must verify the expanded boundary check.


## Manifest-selected public delegates

The existing `.github/migration-adapters.json` manifest explicitly selects the
public loader: without `interaction`, its eight draft delegates come from the
support module; with `interaction`, they come from `scripts/cucp.ps1`. The family
hooks continue to come from the support module. A promoted support module that
still defines any of the public delegates is rejected, as are missing/duplicate
selected definitions. There is no inferred fallback from missing main delegates.

The loader compiles each selected public definition with its original filename
using the Windows PowerShell 5.1 `Parser.ParseInput` filename overload, preserving
`PSCommandPath`. Eight inert host checks assert each operation and ScriptPath;
after promotion the path must be the main `scripts/cucp.ps1` wrapper. The source
entry points are never executed. Draft support, all 870 ordinary comparisons,
all 12 uncertainty cases, exact Console comparisons and descriptor guards remain.

The 18-case null/empty/literal argv ownership matrix is required under both
Windows PowerShell 5.1 and PowerShell 7 in the Windows lane. The supplemental PS7
case explicitly resolves `pwsh`; it cannot silently substitute PS5.1.

The ownership fixture records raw JSON input and its typed caller separately.
PS7 can bind a null array element to an empty string before the constructor runs;
that conversion is not caller mutation. Both snapshots must remain unchanged.
The independent original-expression helper may return null under PS5, so null
state has no mutable storage and needs no array type or element mutation claim.
Non-null state still requires the exact original array CLR type, independently
owned storage, every element mutated by the inert host, and unchanged startup.
All 18 ownership cases and eight public-delegate checks remain in the gate.

Null snapshots use the explicit JSON text `null`; every snapshot field must be
a string before Python decodes it. This avoids PS5's observed non-string null
snapshot representation without changing caller data, production conversion or
non-null array semantics. Both raw/bound before/after and expected/actual state
comparisons remain exact.
