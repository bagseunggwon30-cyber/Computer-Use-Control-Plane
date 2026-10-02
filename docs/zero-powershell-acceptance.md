# Zero-PowerShell completion gates

The approved final target is zero tracked PowerShell source and zero required
PowerShell execution, including installation, launchers, tests and CI. This is
stronger than reducing the language percentage. Work remains on the migration
feature branch; merging into main needs separate approval.

At the qualified planner checkpoint `aadbc58aa9dcc2254a3361cf8963429197859f22`,
78,544 of the original 1,013,478 tracked PowerShell bytes were actually retired.
That checkpoint left 934,934 bytes. The current app-profile source replacement
removes another 13,662 bytes, bringing the total reduction to 92,206 bytes and
remaining source to 921,272 bytes. Its exact-commit actual-adapter CI gate is
required before claiming that replacement qualified. Current source groups are:

| Remaining source group | Bytes |
| --- | ---: |
| Main legacy wrapper and macros, `scripts/cucp.ps1` | 577,143 |
| Native helper, `scripts/cucp-native-helper.ps1` | 165,893 |
| Resident helper server | 27,427 |
| Four PowerShell test files | 135,171 |
| Audit and verification references | 10,586 |
| Installer, launchers and publisher shims | 5,052 |

These are canonical Git blob bytes, including comments and tests. They are not
GitHub Linguist percentages or a functional completion percentage. No source is
excluded, renamed, embedded elsewhere or padded to change the metric.

## Ordered implementation families

1. **Deterministic planning and observations.** Qualify the current app-profile
   acquisition adapter and removed sole-use score helper. Continue image
   comparison, history scoring, profiles and recorder/recovery report assembly.
   Use captured queries and generated files for exact Windows comparisons. The
   current app-profile replacement must pass full payload, error, query, exit and
   actual output checks before it is considered qualified.
2. **Execution coordination.** Migrate workflow, task, form, watch, recovery and
   replay state machines into Python/C#. Preserve startup authority, target
   binding, confirmation gates, cancellation, partial outcomes, time budgets and
   the distinction between a failed observation and an uncertain mutation. Test
   captured executor sequences before connecting actual Windows actions.
3. **Windows acquisition and input.** Replace the native helper and resident
   server, including UIA/OCR/window metadata and authenticated local IPC. Existing
   C# facilities cover part of this surface. Preserve legacy callable operations
   only after their equivalents are qualified. Live input, IME/clipboard, focus
   races, mixed DPI, helper crashes and elevation require an authorized isolated
   interactive Windows fixture environment; mocks do not close those gates.
4. **Remaining adapters and lifecycle.** Finish legacy CDP/vision routes,
   diagnostics, system/process/registry macros, helper lifecycle and optional
   integrations. Keep the host/provider neutral. Tests use owned browser pages,
   captured provider replies and disposable fixture data. They do not require a
   user's authenticated model account or broaden persistent access.
5. **Entry points and verification.** Replace the remaining installer/launcher
   shims, port the Pester and reference checks, and remove PowerShell shells from
   CI. Then run complete source and packaged installations with PowerShell
   unavailable, including the optional Pi adapter. Reproduce every advertised
   command family through the replacement entry point.

The groups describe acceptance boundaries, not fixed deadlines. Public behavior
is the parity target; unused private helpers should disappear with their last
qualified caller instead of acquiring unnecessary compatibility wrappers.

## Ending the differential-oracle dependency

PowerShell differential tests are temporary migration tools. Before the final
zero-execution gate, preserve qualified expected results as reviewable fixtures
with the exact original source commit, input, culture, expected output/error,
query trace and normalization rules. Replace each live PowerShell oracle with
native/Python contract and integration tests over those fixtures. Keep independent
behavioral assertions so tests do more than restate the implementation. The old
source remains in normal Git history, not a copied runtime archive.

The retained workflow tokenizer needs a genuine compatible replacement; linking
System.Management.Automation or spawning PowerShell is not a zero-dependency
solution. Its accepted syntax and error behavior remain a separate release gate.

## Final evidence required

- Git-tracked `.ps1`, `.psm1` and `.psd1` runtime/test source count is zero
- Runtime, install, launcher, packaging and CI paths contain no required
  PowerShell executable, PowerShell SDK, encoded bootstrap or hidden fallback
- Every retained public capability has a tested Python/C# implementation or an
  explicitly resolved compatibility decision; no unported operation was dropped
- Supported fresh and upgraded Windows installations work without PowerShell on
  the execution path, and process-level evidence shows no implicit shell fallback
- All current-commit automated checks and the required interactive Windows matrix
  pass, with unperformed checks reported explicitly
- Published blobs match the reviewed tree, and release/merge claims refer to that
  exact verified commit

A green incremental checkpoint establishes only its documented coverage. The
zero-PowerShell goal is not complete while any of these final gates remains open.
