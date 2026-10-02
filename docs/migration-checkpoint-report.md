# Python/C# migration milestone

## Result and limit

This is a **partial, parity-tested migration**, not completion of the request to
reach zero PowerShell source and execution. The work is
on `migration/python-csharp-runtime`; `main` has not been merged or replaced.

The provider-neutral core runs through Python and C# without PowerShell. Its 52
MCP/JSONL tools do not require Pi or an authenticated model provider. The broader
legacy command surface still enters through PowerShell compatibility adapters.
Keeping those two scopes distinct avoids claiming that the new core already
replaces every old macro.

## Reproducible source retirement

The baseline is published commit `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`, tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`.

| Canonical tracked PS source | Baseline | Accepted checkpoint `27400c98` |
| --- | ---: | ---: |
| All `.ps1` source and tests | 1,013,478 bytes | 921,614 bytes |
| Three legacy runtime scripts | 858,937 bytes | 770,805 bytes |
| Actual all-source reduction | — | **91,864 bytes (9.06%)** |

The earlier 78,544-byte planner reduction is qualified at aadbc58 / run
36957910828. The additional 13,320-byte app-profile replacement passed its 523-case actual-bridge
suite at `27400c98`, with all five jobs green in
[run 36973181910](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36973181910).
The next candidate batch retains the originals while qualifying three exact
adapters as real `.ps1` fixtures. Its current inventory is 985,215 bytes, including
63,601 bytes of temporary fixture/guard overhead above the accepted checkpoint.
No new family retirement is claimed until those fixtures pass and are promoted.

There are still 291 top-level legacy function entries. Function count is not a
feature-completion percentage: several retained functions are now thin adapters,
and many large functions contain multiple capabilities.

Run `python pcucp-next/packaging/check_migration_inventory.py` to check the exact
Git-tracked blob totals, retained locations, and retirement records. The check
uses canonical index blobs, so Windows checkout line endings do not alter the
metric. Review and stage PS edits before using `--update` to refresh the inventory.
Original implementations remain in normal Git history, not a renamed archive or
embedded copy. No Linguist exclusion or language-statistics padding is used.

## What was actually replaced

- **OCR matching:** four private PS algorithms were retired; the retained matcher
  delegates to C#. Exact Windows NLS, UTF-16 and legacy tied-candidate ordering
  were preserved after differential tests exposed real incompatibilities
- **Win32 declarations:** three runtime-compiled C# definitions moved into a
  compiled net48 interop library. All 301 public API/PInvoke/marshalling/ABI entries
  and actual PowerShell 5.1 loaders are checked. This is not a desktop-input test
- **Safety classification:** rules, category ordering, risk scores, confirmation
  flags and UTF-16 preview behavior moved into a closed C# operation. Failure
  remains failure; a missing or malformed runtime reply cannot classify an action
  as safe
- **Coordinate math:** clipping, rounding and mapping moved into C#. Original
  window/hit-test/profile acquisition remains in a small PS adapter
- **Workflow plan assembly:** allowlists, policy and result construction moved to
  C#. The exact original PS tokenizer remains. An incomplete literal-parser
  candidate is excluded from the shipped host
- **Task presets:** the 17,082-byte builder became an adapter after its
  recipe and payload comparison passed. Its typed child-query transport is shared
  with task/form planning. It retains one read-only planning query,
  timing, errors, formatting and exit behavior. Central bridge overhead is included
  in the aggregate reduction above
- **App-profile assembly:** target selection, strategy scoring, probe command
  construction and report assembly moved into C#. A thin adapter retains the
  original acquisitions and optional history append. Its pure controller checks
  the full target/score and explicit record request before one append, then
  preserves the original record fields without further transport. The 523-case
  actual-bridge release gate
  covers exact payloads, errors, exits, Console output and acquisition order
- **User installer:** implementation moved to Python. The small PS compatibility
  entry preserves the legacy default and original flags. Explicit core/portable
  launchers invoke no PowerShell

## Core architecture and evidence

Python owns transport/schema validation, bounded workflows, target selection,
observations, memory-only audit metadata, cancellation and the optional CDP client.
C# owns Windows UIA, OCR, guarded input, app lifecycle and the pure compatibility
kernels. Live authority is fixed at startup; failed or uncertain mutations are
not automatically retried. Retained compatibility calls carry the caller's culture across their process boundary and restore native request-local culture afterward; this changes no OS locale setting. Read-only task/form/smart planning queries send JSON to a fixed bootstrap and binds a named string array, so control-like values remain data. Windows proved that native `-File` binding and a literal `--` do not provide this boundary. The bootstrap suppresses only its progress stream so first-use module loading cannot corrupt the JSON reply; genuine errors remain captured. Both boundaries have Windows fixtures. CDP requires one explicitly configured numeric-loopback
endpoint and fresh target/document/element references.

Required CI covers Linux contracts, Windows native/protocol contracts, relocated
portable packaging, and seven real fresh-profile sandboxed Chrome fixture tests.
It includes 56 OCR, 57 safety and 115 coordinate kernel cases plus actual retained
adapters; 254 complete original-tokenizer-fed workflow plans; and eight actual
native parsed-plan dispatch cases. Preset qualification includes 554 exact
recipe/payload comparisons from 285 inputs, 28 argv/quoting cases, and a new actual
adapter/formatting comparison. **The current commit's complete CI must pass**;
an earlier green run is not a substitute. The Pester regression suite loads the actual compatibility bridge and needs `CUCP_NATIVE_HOST` set to the matching Release native DLL; CI builds and sets it explicitly. Its workflow safety assertions run against the real migrated kernel.

Two candidates remain deliberately unretired: strategy ranking (including
cross-culture comparisons) and a net48 image-diff library with 55 generated-file
and error cases across PNG/BMP/JPEG/GIF/TIFF. Explicit strategy culture currently
controls its comparers. The next isolated candidate also scopes alias regex
normalization to the requested culture; its new Unicode differential must pass
before strategy retirement.

## Planning integration

Task/form plan assembly (22,380 bytes in the pinned baseline) and smart-plan
composition (17,025 bytes) passed independent Windows qualification and now use C# builders with retained
read-only PowerShell acquisition adapters. Local managed checks cover 105 task/form contracts and 23
smart-plan contracts; Windows corpora contain 367 task/form cases and 201
smart-plan cases, plus each captured-prefix query trace. Exact numeric errors,
null binding, ordered queries, unsafe-child accumulation, and full outputs remain
qualification gates. The pure operations are explicitly registered in the production host. Strengthened
actual-adapter checks compare real Console output, exact query traces and the current
workflow bridge, not reconstructed output from a test payload. At
[aadbc58 / run 36957910828](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36957910828),
all four CI jobs passed, including all 367 task/form and 201 SmartPlan actual
adapter cases. The prior 70 SmartPlan raw JSON field-order mismatches were fixed
by restoring the original property order; every oracle assertion remained intact.

## What still prevents full completion

Roughly 0.935 MB of PS remains. Major callable groups include smart-click and live
fallback routing; app/profile/probe acquisition; task/form/workflow execution;
persistent history/recording; legacy CDP/vision adapters; IME/clipboard/drag and
multi-edit; helper lifecycle, UAC/autostart, and system/process/registry macros.

Hosted protocol and generated-data tests do **not** establish real interactive
Windows acceptance. Outstanding checks include Korean IME composition, clipboard
restoration, focus/modal races, held-input cleanup, mixed-DPI/multi-monitor
coordinates, cross-integrity/UAC behavior, helper restart/crash handling, and
application-specific task success. No user desktop, account-connected model, or
personal documents were used to claim these checks.

The next isolated candidate is app-profile assembly and its strategy helpers,
with 496 captured-reply cases and 344 Unicode/culture comparisons awaiting
Windows qualification. Its original PowerShell body remains. These pure and
noninteractive slices can continue in cloud CI. Full retirement of the remaining
live input and lifecycle boundaries additionally needs an authorized, isolated
interactive Windows fixture environment. Until those boundaries are proved,
retiring them merely to change language percentages would drop behavior. This
milestone is a reviewable foundation, not a completed rewrite or signed release.
