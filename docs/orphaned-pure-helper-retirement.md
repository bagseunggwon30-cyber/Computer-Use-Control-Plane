# Orphaned private pure-helper retirement

This local cleanup removes seven unused private definitions from
`scripts/cucp.ps1`. It does not change a public delegate, the production workflow
parser, an acquisition/action boundary, or the retained
`_AppStrategy-NormalizeRoute` dependency. Publication and the new source/loader
Windows full gate remain pending. This is not a new qualified checkpoint.

This cleanup is now integrated locally onto
`14ccef5ba48e82041599698f809576040d6fc5c0`. All its parser code,
diagnostic fixtures, goldens and `.gitattributes` are preserved byte-for-byte.
The original cleanup commit
`38c7dfa111687ccea821111f50b547684cba5b91`, the earlier integration
`a576440f5e56c3f07df9e274f675b07e5bd7a0a7`, and the current integration base are
local commit identities; none identifies a newly qualified published checkpoint.

## Exact source provenance

The pre-cleanup source at local commit
`ef64b82ca15a244c3395548a6fc58396a915b443` is identical
to the wrapper measured by the Windows AST source map in qualified checkpoint
`c414f0240a6a3fde78719f4ae44baddaf990e92b`,
[full run 37072046282](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37072046282).
Its normalized UTF-8/no-BOM/LF SHA-256 is
`6fa1802661fd935df2c4d643aba8b5300723f8e0f75aac9d8fcf284688c28ba9`.
The actual tracked UTF-8 file includes a three-byte BOM and is 410,892 bytes.

The whole-file hash and every selected function hash were verified before
converting the source map's UTF-16 offsets to UTF-8 offsets. Only the exact AST
function extents below were removed. BOM, line endings, surrounding comments,
separators and every byte outside those ranges were preserved. Offsets are
zero-based, half-open ranges in the pre-cleanup source; UTF-8 offsets include
its BOM. Per-function SHA-256 values are recorded in
[the canonical inventory](legacy-function-inventory.json).

| Removed function | UTF-16 range, no BOM | UTF-8 byte range, with BOM | Bytes |
| --- | --- | --- | ---: |
| `_Iif` | 169543–169638 | 176469–176564 | 95 |
| `_Set-ObjectProperty` | 249762–250023 | 257684–257945 | 261 |
| `_TaskPlan-QuoteToken` | 299266–299484 | 308132–308350 | 218 |
| `_TaskPlan-StepString` | 299486–300028 | 308352–308894 | 542 |
| `_TaskPlan-UnwrapCommand` | 300030–300244 | 308896–309110 | 214 |
| `_AppStrategy-Key` | 300879–301229 | 309745–310095 | 350 |
| `_Cucp-RedactSecrets` | 365367–366138 | 376039–376810 | 771 |
| Total | | | 2,451 |

The resulting wrapper is 408,441 bytes, with tracked-blob SHA-256
`b21a75a9249e9eb38d45d6dd70bc8eff940444894b4482cac81d07fc811844da`.
This is source deletion, not archival, renaming, exclusion from language
accounting, or a replacement embedded in test code.

## Dependency review and replacement evidence

Case-insensitive whole-repository name searches found no remaining production
caller outside the selected definitions. The only edge within the removed set
was `_TaskPlan-StepString` calling `_TaskPlan-QuoteToken`. Searches of the name
families and dynamic invocation mechanisms found no string-built dispatch or
alias referring to these private helpers: production command dispatch uses
explicit public macro names; variable command calls run wrapper/script paths
or executable paths. `Test-Tool` performs prerequisite lookup and
`_Resolve-AppPath` filters application commands, rather than dispatching these
private helpers. No `Invoke-Expression`, generated scriptblock, or alias table
restores a dependency on them.

Existing implementations and unchanged historical checks cover the migrated
public callers:

- Quote/step/unwrapping: `LegacyTaskPresetKernel.QuoteToken`, `StepString` and
  `CommandHelpers`; TaskForm's `Unwrap` and `CommandStep` call the same kernel.
  Pinned task-preset helper, task/form, SmartPlan, app-profile, precision and
  culture/alias comparisons remain.
- App key: `LegacyAppProfileKernel.AppKey` with
  `LegacyTextKernel.SanitizeAppKeyPart`; pinned app-profile actual-adapter and
  culture/alias comparisons remain.
- Release redaction: `LegacyDiagnosticFiles.DiagnosticReleaseRedactors`;
  release-notes payload, exact Console, exit and effect comparisons remain.
- Conditional status: the seven original `_Iif` uses were in self-test;
  `LegacyDiagnosticHealth.SelfTest` contains their conditional status assembly.
  Self-test payload, exact Console, exit and effect comparisons remain.
- Cached point-plan fields: `LegacyPrecisionPlanners.PointPlan` copies the cached
  object and replaces the same eight fields. Precision cache-hit payload,
  exact Console, exit, query and effect comparisons remain.

All these public-caller gates passed at the cited c414 checkpoint. Removing
unused definitions and adjusting test loading still requires fresh validation;
old qualification does not certify the new source tree.

## Fixture loading changes

Pinned-original imports, fixtures, expected data, comparison loops and assertions
are unchanged. Only current-source loading omits unavailable originals:

- App-profile `CurrentBridge`: omit `_AppStrategy-Key`.
- Precision `CurrentBridge`: omit quote, step and object-property helpers.
- SmartPlan `CurrentBridge`: omit quote and step helpers.
- Diagnostic file `ProductionEntry`: omit `_Cucp-RedactSecrets`.
- Diagnostic runtime `ProductionEntry`: omit `_Iif`.

The SmartPlan current-source dependency was found during this cleanup in
addition to the initially identified loaders. Task-preset already used a
separate current-adapter import list. Task/form and culture/alias drivers still
read their private helper definitions exclusively from pinned original source.
New static regression checks preserve the original import lists, verify the
seven extent/hash records against the qualified source, and reject reintroduced
production references while retaining the shared route helper.

## Honest source accounting and acceptance gate

The seven runtime extents remove 2,451 bytes, while the two explicit diagnostic
fixture guards add 151 PowerShell bytes. Net all-source reduction for this
cleanup is therefore **2,300 bytes**, not 2,451: 872,501 before this integration
and 870,201 afterward. The 27 tracked `.ps1` files total
**870,201 bytes**: **610,258 bytes under `scripts/`** and **259,943 bytes in
other tracked PowerShell sources/tests** (including launchers, packaging and
reference scripts). This `scripts/` subtotal uses the prior checkpoint report's
runtime grouping; all sources still count toward the total. The reduction from
the 1,013,478-byte original baseline is **143,277 bytes**. The inventory includes every tracked PowerShell file and all fixture
overhead. These local counts are not newly accepted Windows results.

Before acceptance, rerun the matching NativeHost build and Windows PS5.1
original/current comparisons for task-preset, task/form, SmartPlan, app-profile,
culture/alias, precision, diagnostic runtime/file and actual adapters. Preserve
all payload, Console, error, exit, query/effect-order and authority assertions.
Run the bundled full regression on the coherent integrated commit, including
native/Pester boundary, all six migration families, profile, browser and relocated
portable-package gates. Interactive Windows GUI/IME/clipboard/focus/mixed-DPI
acceptance remains separate. Main has not been changed by this local cleanup.

## Local verification

On 2026-10-03 UTC, integrated Python discovery ran **555 tests: 432 passed and
123 explicitly skipped for platform/host requirements**. The three new source/provenance/import
checks passed. Seven targeted managed contract projects passed **933 checks**:
task-preset 86, task/form 105, SmartPlan 23, app-profile 34 plus 63 controller
guards, diagnostics 14 plus 37 boundary assertions, precision 509, and pure
safety/coordinate/strategy 62. The unchanged workflow candidate separately
passed 1,402 managed checks, for **2,335 managed checks across eight projects**.
Historical replay is not fresh Windows qualification or full parser parity.
No acquisition or desktop input was executed.

This Linux environment provides SDK 10.0.401 and runtime 10.0.12. Local managed
execution used `DOTNET_ROLL_FORWARD=Major` for the net8.0 contract projects;
during the initial cleanup, execution without that setting failed because
.NET 8 was not installed. These results do not replace Windows .NET 8 / PS5.1 qualification.
The source-provenance regression references the immutable qualified Git tree,
`d4c9660d40c7e909f18afb166a8e846798f63b1d`, rather than a local commit alias.
All parser code, diagnostic fixtures/tests, goldens and `.gitattributes` match
the latest integration base byte-for-byte. Benchmark, audit-summary and history
reducer originals remain intact. No parser or parser-fixture changes were made
by this cleanup.

`check_migration_inventory.py` passes against staged canonical blobs, and
`git diff --check` passes. A separate byte-complement comparison confirms that
only the seven verified extents changed in the production wrapper. Each of the
five existing oracle files is byte-identical to its pre-cleanup version outside
the current-source import-selection line, preserving every prior assertion.
