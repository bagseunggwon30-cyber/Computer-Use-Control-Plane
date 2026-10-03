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

These are canonical Git blob bytes for tracked `.ps1`, `.psm1` and `.psd1`
files, including comments and tests. They are not GitHub Linguist percentages,
a functional completion percentage, or an exhaustive all-language source count.
Moving script text into another extension, a string or an encoded payload does
not retire it and cannot earn credit toward the final goal.

## Latest automated checkpoint

The latest full automated checkpoint is `f09e5200`, with all 14 active jobs
successful in [run 37086869922](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37086869922).
A single pinned-original image-process timeout was retried on the same commit;
its 15-second limit and assertions were unchanged. Seven orphaned private helpers
were removed while retaining their qualified public replacements and old oracles.
The 27 tracked PS files total **870,201 bytes**, including **610,258 runtime
bytes**. Net reduction from baseline is **143,277 bytes**. Temporary parser and
boundary fixtures explain why total source exceeds the earlier 823,078-byte
milestone despite lower runtime source. They remain fully counted.

The parser candidate's expanded focused Windows gate passed at `1e3d534a`, but
known conservative syntax and exact diagnostic differences still block its
promotion. It remains excluded from NativeHost. The required interactive Windows
matrix and all zero-dependency final gates below remain open. New benchmark/audit
and history candidates do not earn retirement credit before their exact gates.

The explicit history-candidate gate subsequently adds one 10,672-byte, openly
tracked PowerShell oracle. The integrated candidate tree therefore has 880,873
extension-counted bytes in 28 files, including the unchanged 610,258 runtime
bytes. This is a temporary qualification cost, not new retirement credit or a
new full-green checkpoint. Its four retained production function bodies remain.

The extension count has a concrete known limitation: `test_legacy_interop.py`
still contains two inline PowerShell test drivers executed with
`-EncodedCommand`. Those scripts remain dependencies even though they are not
included in the extension-based byte figure. This finding is not an exhaustive
audit of all embedded drivers; the final checks below cover every source form.

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
- A repository-wide source audit finds no inline, encoded, concatenated or
  dynamically materialized PowerShell programs in Python, C#, JavaScript,
  templates, resources, fixtures or other renamed containers. Script snippets
  still required to execute tests count as dependencies; inert captured input
  and expected-output data must be distinguished explicitly
- Runtime, install, launcher, packaging and CI paths contain no required
  PowerShell executable, PowerShell SDK, encoded bootstrap or hidden fallback
- CI commands, installers, launchers, subprocess builders and test-driver
  generation paths are reviewed together. `-Command`, `-EncodedCommand`,
  temporary `.ps1` materialization and reflective engine loading cannot conceal
  a remaining execution path behind an extension-only scan
- Every retained public capability has a tested Python/C# implementation or an
  explicitly resolved compatibility decision; no unported operation was dropped
- Supported fresh and upgraded Windows installations work without PowerShell on
  the execution path, and process-level evidence shows no implicit shell fallback
- Current automated tests and packaged execution run with PowerShell unavailable;
  process-level evidence includes child processes and generated temporary
  drivers. Historical originals may remain reachable in normal Git history for
  recovery, without becoming a dependency of final shipping code or its tests
- All current-commit automated checks and the required interactive Windows matrix
  pass, with unperformed checks reported explicitly
- Published blobs match the reviewed tree, and release/merge claims refer to that
  exact verified commit

A green incremental checkpoint establishes only its documented coverage. The
zero-PowerShell goal is not complete while any of these final gates remains open.

The staged interaction/diagnostic/file-image batch still retains original bodies.
Its adapter and oracle scaffolding is fully counted (934,772 current staged PS
bytes). The temporary diagnostic guard was reduced by 31,109 PS bytes through a
real Python case/assertion/fixture-I/O port, not an embedded or renamed PS
program. Remaining fixed PS boundary drivers are explicit temporary dependencies
and are subject to the same final zero-execution requirement.
