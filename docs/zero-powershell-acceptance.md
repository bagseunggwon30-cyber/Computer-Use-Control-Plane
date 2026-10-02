# Zero-PowerShell completion gates

The approved final target is zero tracked PowerShell source and zero required
PowerShell execution, including installation, launchers, tests and CI. This is
stronger than reducing the language percentage. Work remains on the migration
feature branch; merging into main needs separate approval.

At the qualified planner checkpoint `aadbc58aa9dcc2254a3361cf8963429197859f22`,
78,544 of the original 1,013,478 tracked PowerShell bytes were actually retired.
That checkpoint left 934,934 bytes. The accepted app-profile checkpoint `27400c98`
removes another 13,320 bytes, bringing the total reduction to 91,864 bytes and
remaining source to 921,614 bytes. Its exact-commit actual-adapter gate passed in run `36973181910`.
The three-family kernels and exact adapters passed all focused jobs at `e9e015c6`
in run `37007340738`. Their production integration replaces 53 original function
extents and removes duplicate fixtures, leaving **823,078 bytes**: a further
98,536-byte reduction, and 190,400 bytes below the original baseline. This is a
verified source measurement at `56be343c`, with all 11 active jobs green in
[full run 37022764709](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37022764709), including privacy,
production routing and portable packaging. Source groups at that checkpoint are:

| Remaining source group | Bytes |
| --- | ---: |
| Main legacy wrapper and macros, `scripts/cucp.ps1` | 505,923 |
| Native helper, `scripts/cucp-native-helper.ps1` | 122,475 |
| Resident helper server | 27,427 |
| Shared retained CDP host | 11,945 |
| Four PowerShell test files | 137,165 |
| Temporary parser-derived migration source map | 2,505 |
| Audit and verification references | 10,586 |
| Installer, launchers and publisher shims | 5,052 |

These are canonical Git blob bytes, including comments and tests. They are not
GitHub Linguist percentages or a functional completion percentage. No source is
excluded, renamed, embedded elsewhere or padded to change the metric.

## Ordered implementation families

1. **Remaining deterministic planning and observations.** App-profile, task/form,
   workflow-plan, SmartPlan, precision and history/cache logic now have qualified
   replacements. Continue image comparison, remaining profile/recorder logic and
   the original workflow tokenizer. Preserve exact outputs and acquisition order.
2. **Retained execution effects.** The seven workflow/task/form/SmartClick/watch/
   recovery coordinators are now in C#. Their PowerShell child, clock, Console,
   acquisition and leaf-action adapters remain. Move these effect boundaries
   while preserving immutable authority, confirmation, cancellation, time budgets
   and the distinction between observation failure and uncertain mutation.
3. **Windows acquisition and input.** Replace the native helper and resident
   server, including UIA/OCR/window metadata and authenticated local IPC. Existing
   C# facilities cover part of this surface. Preserve legacy callable operations
   only after their equivalents are qualified. Live input, IME/clipboard, focus
   races, mixed DPI, helper crashes and elevation require an authorized isolated
   interactive Windows fixture environment; mocks do not close those gates.
4. **Remaining adapters and lifecycle.** Finish retained CDP host/vision routes,
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
