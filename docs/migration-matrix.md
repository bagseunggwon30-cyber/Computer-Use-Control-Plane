# Python/C# migration matrix

This feature branch starts from published `9ffa354b9904235835a7bc6eb78ed8d3d76317c8` (exact tree `bf895d3120dd5e145f360cb1c41e1d79a061d048`). It is not a complete PowerShell rewrite or a signed release. The stages below preserve earlier implementation history. Existing PowerShell sources remain visible and usable where safe. No Linguist exclusions or file hiding are used to change language percentages.

## Implemented in this stage

| Capability | Python responsibility | C# responsibility | Compatibility / parity status |
|---|---|---|---|
| Provider-neutral host connection | New stdio MCP lifecycle, tool schemas, image mapping, cancellation; existing JSONL retained | Existing resident stdio native worker | Pi optional and unchanged; external MCP client smoke still needed |
| Process launch | Validation, live gate, argv JSON, observation invalidation, errors/no retry | Explicit `.exe` process creation, Windows argv quoting, handle isolation, desktop/privilege check | New bounded subset; legacy friendly app names, URLs, scripts and shell associations not migrated |
| App close | Latest single-use observation, bounded timeout, stop-on-failure | Exact target/geometry/privilege, one WM_CLOSE, bounded wait, no implicit kill | Graceful selected-window close migrated; forced/multi-process close deliberately not in core |
| Native build/publish | New `packaging/publish_native.py` builds native executable with argv-only subprocess | Existing .NET self-contained publish | Old PS entrypoint is now a small compatibility shim; source Python prerequisite made explicit |
| Windows enumeration/capture/UIA tree/privileges | Existing contract, state, bounded queries | Existing native implementations | Retained, not newly claimed migration |
| Click/double/right click/type/keys/scroll/focus | Existing session/TTL/token mapping/batch safety | Existing Win32 input and target validation | Retained safety tests; real GUI still unverified locally |
| Bounded workflows and history | Existing batch/wait-window/history plus terminal cancellation | Existing actions | Only short declarative batches, not arbitrary legacy workflow equivalence |

## Retained legacy families and next work

[Machine-readable function inventory](legacy-function-inventory.json) enumerates the retained top-level PowerShell functions across the three runtime scripts, with source locations. It is a navigation inventory, not a claim every helper is an externally exposed feature. The inventory also records qualified retirements; remaining helper-server dispatch is still legacy.

| Legacy family | Current route | Missing before parity / next ownership |
|---|---|---|
| UIA label lookup/invoke/set-value/toggle/element IDs | Some read lookup already Python/C#; action macros stay PS | C# observation-generation-bound element references and supported patterns; Python ambiguity/policy; stale-reference tests |
| OCR search/click, OCR/UIA fusion, screenshot diffs, icon targeting | C# image OCR + Python search exists; combined workflows stay PS | Python deterministic fusion/diff and C# capture, coordinate identity, image fixture tests |
| Drag, held keys, multi-select/edit, IME clipboard workflows | PS compatibility | C# carefully scoped primitives; Python state and cleanup; real Windows IME/clipboard validation |
| CDP discovery/query/eval/type | PS compatibility, explicit mutation classification | Optional separate browser adapter; never enable arbitrary eval as a read tool |
| Long workflow/task/form/profile/recovery/recorder/watch | PS compatibility, new short core batch is not equivalent | Python declarative plan/state/log with explicit failure/stop conditions; preserved fixtures and workload parity |
| Helper daemon/autostart, process/registry/clipboard/system macros | PS compatibility | Python lifecycle/config plus scoped C# APIs; no always-on remote control or broad credentials |
| Model-assisted vision | Optional legacy provider adapter only | Host-side vision/tool call adapter, no universal-core model/account dependency |
| Installer and optional Pi elevation launcher | PS installer/launcher retained | Python packaging/setup where useful; keep normal human-controlled UAC boundary |

## Safety fixes in retained legacy code

1. `app-close` without `--force` no longer escalates a two-second wait into process termination. If an application ignores close or asks to save, it stays open and close does not report a completed kill
2. Helper shutdown no longer kills any PID read from a lock. Stale locks are discarded safely; valid helpers receive a pipe shutdown request. Even `--force` does not override missing process identity. A nonresponsive helper requires human diagnosis rather than risking another process
3. Legacy vision execution no longer evaluates a command string through `cmd.exe`. Native executable arguments are individually Windows-quoted. **`.cmd`/`.bat` provider wrappers are rejected**, including typical npm wrapper-only installations; supply a trusted native executable or keep vision in the host. This is an explicit compatibility restriction, not full provider-launch parity
4. Workflow `session` is no longer classified wholesale as read-only. Only `info`, `helper-status` and `autostart-status` are accepted in a read-only workflow. Direct install/uninstall-autostart requires explicit live mode. Persistence is not added to the new core

## What “done” means here

Done: local reviewable source patch, generic protocol path, priority process lifecycle migration, Python publishing, retained-source safety repairs and isolated regression tests. Not done: all roughly 20,000 lines of retained PS runtime sources rewritten, every legacy feature ported, Windows interactive validation, deployment, signing, new release artifacts, commits, pushes or PRs.

Next migration order: UIA action references → Python workflow/recorder state → OCR/diff/fusion → IME/input peripherals → optional CDP/provider adapters → legacy retirement only after parity evidence. Keep each legacy implementation until its replacement passes equivalent fixtures and Windows tests; do not delete features to make language counts look better.

## Stage-two additions (cumulative local patch)

| Capability | Implemented core subset | Retained / unverified |
|---|---|---|
| UIA element actions | Opaque per-observation references, exact local find, InvokePattern, writable ValuePattern, identity/ancestry/geometry guards | Toggle/selection/legacy label macros retained; actual Windows providers unverified |
| Parent-crash lifecycle | Explicit inherited parent kernel-handle watchdog, Windows worker-only cancellation, target apps never tree-killed | Windows inheritance/crash/nested-host acceptance still manual; no JobObject guarantees claimed |
| Drag | Bounded same-window left-button single-batch gesture with partial-input release | Timed/cross-window/multiselect/held-key gestures remain legacy |
| Unicode contract | UTF-16-unit budget, surrogate rejection, Korean/emoji adapter fixtures, no clipboard modification | Actual IME composition and clipboard workflows not migrated |
| Generic host workflows | Same observe/find/set-value/stale rejection tested through MCP and JSONL adapters | No live model, external MCP-client or Windows GUI test in Linux |

The earlier “next work” table describes remaining legacy parity, not a claim these
new subsets are absent. No PowerShell implementation was removed in this stage.


## Stage three: actual orchestration and observation migration

| Family | Python/C# implementation | Legacy parity still outstanding |
|---|---|---|
| Workflow plan/run | Typed JSON data, 64 leaf steps, backward-only output references, JSON conditions, schema preflight, deadlines/cancellation, explicit read retries only, no automatic input retry | Legacy command-string format, continue-on-error and user-requested live retries are not mapped |
| Task and form | PID-bound explicit EXE launch/wait, exact target/focus, fresh observation per field, ambiguity assertion, Unicode/empty ValuePattern, explicit final submit | Friendly app resolution, arbitrary label/coordinate/CDP fallback and app-specific presets |
| Watch and recovery | Bounded read-only condition polling; safe re-observation recovery plan | Background daemon/event watches and approved modal dismissal |
| Recording/profile | Bounded memory-only metadata audit, current-observation role/pattern inventory | Disk history, strategy persistence, recorder replay/export |
| UIA patterns | Toggle exactly once; explicit replace/add/remove SelectionItem; ExpandCollapse state; directional ScrollPattern; observed-state guards and single-use references | Interactive provider conformance, offscreen navigation and long gestures |
| OCR screen/window | Same captured PNG decoded/recognized in memory by Windows OCR, explicit language, image-pixel geometry, fresh observation and optional UIA tree | Full-desktop/unbounded region capture and live OCR accuracy/language acceptance |
| OCR matching/fusion and image diff | Deterministic Python normalization/scoring/n-grams, explicit geometry fusion, bounded PNG/pixel differences | All app-specific targeting heuristics, fuzzy auto-actuation and legacy external image formats |
| Universal host contracts | Same 40 tools over MCP and JSONL, schema-derived preflight, generated checked-in JSON schema, source CLI entry points | Tool-capable host required; this does not retrofit tools into an arbitrary closed chat UI |

At this historical stage the branch had added implementations but removed **zero** legacy functions: all 298 still remained. Later retirement is recorded below. This intentionally avoids presenting an incomplete port as a language-statistics success. The new runtime and portable package do not invoke those files; source-only `legacy` remains an explicit compatibility route. CDP/vision providers, true IME/clipboard workflows, broader process/registry/system macros, autostart/helper compatibility, installer/elevation flows and remaining PowerShell tests must still be migrated and validated before full legacy retirement.

Validation of contracts on Linux does not prove interactive Windows behavior. CI's Windows native/portable tests cover builds and protocol/package execution; manual UIA/OCR/input/IME/mixed-DPI/parent-crash acceptance remains required. See [workflow migration](workflow-migration.md), [observation migration](observation-migration.md) and the native contract for exact semantics.


## Stage four: qualified legacy logic retirement

The five original pure OCR matching helpers were compared on Windows PowerShell 5.1 against a bounded C# kernel using 56 ASCII/Korean/Unicode, fuzzy, phrase and equal-score cases. The first comparison caught real differences in Windows NLS versus modern ICU and pre-.NET4.5 quicksort tie ordering. Those semantics were preserved; the original strict differential assertions passed in run `36885457144` on commit `1eba388f3f8774ac02564fa526307a425bf07f95`. That run's separate installer fixture failed, so the run as a whole was **not** green.

After that proof, `_Normalize-OcrText`, `_Levenshtein-Distance`, `_Similarity-Percent` and `_Score-OcrText` are retired from the current PS helper source. `_Match-OcrCandidates` delegates bounded JSON over stdin to the matching native runtime, with no shell, evaluation, model or desktop call. All geometry keys and candidate order are preserved for legacy callers. The new actual bridge is covered by the same Windows differential suite before merge.

Measured runtime PS reduction at this point: **3,379 bytes**, from `858,937` to `855,558` across the three runtime scripts; current retained top-level functions: **294**. The original algorithms remain only in normal Git history, which the differential test reads temporarily. Nothing is hidden from language statistics.

Legacy OCR callers now require a matching `PcuCp.NativeHost.exe` published to `pcucp-next/bin/native` or an explicit `CUCP_NATIVE_HOST` executable/DLL. A DLL needs .NET available. A missing/old runtime fails closed; the retired algorithms are not silently restored. New MCP/JSONL OCR tools already use Python/C# directly and do not use this compatibility bridge.

Native NLS semantics follow [Microsoft's comparison/search API](https://learn.microsoft.com/en-us/windows/win32/api/winnls/nf-winnls-findnlsstringex); legacy tie ordering follows the [documented runtime compatibility branch in .NET reference source](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/collections/generic/arraysorthelper.cs). This compatibility kernel deliberately does not replace the safer modern matcher’s explicit ambiguity reporting.


The user-scope installer was also migrated to Python after its actual Windows Unicode/argument fixtures passed in run `36886830685` at `fc05aa01a0632b36af930a522efe8c623037300b`. `install.ps1` now only discovers Python and forwards the original flags; its default remains the legacy backend. Core/portable launcher routes do not invoke PowerShell. This removes another **3,857 PS bytes** (5,376 → 1,519). Combined actual source reduction is **7,236 bytes**, before any future retirement. The shim's own forwarding fixture and the OCR bridge BOM handling are checked by the next exact-commit CI.

## Optional browser adapter

The shared interface now has 52 tools, including twelve optional CDP operations. Browser endpoints are configured only by the human at startup, numeric-loopback and exact-origin restricted; no scan or debugging enablement is performed. Read discovery/query/search uses DOM protocol methods; eval/click/type/ProseMirror require immutable live authority and fresh target/document/element references. Cancellation interrupts owned sockets, and native/browser mutations invalidate the other route's snapshots. No browser account or model provider is required.

Local mock-network/adapter tests pass. A separate opt-in CI suite launches an owned fresh headless browser profile against local fixture pages with the sandbox enabled; no existing profile or user desktop is used. The dot Linux workspace's browser launch was blocked by its AF_UNIX restriction before assertions, so no local real-browser pass is claimed. CDP legacy wrappers remain until compatibility and real-browser evidence justify their removal.


## Stage five: compiled interop and safety body retirement

Checkpoint `293464549f93411f02c8f409822157b9a8cd87b7`, run `36890543863`, passed all four jobs: core, Windows native/contracts, relocated portable, and seven fresh-profile sandboxed Chrome fixture tests. This includes exact 57-case safety classifier parity and the compiled interop's 301 public API/PInvoke/marshalling/ABI entries plus PowerShell 5.1 load qualification. No desktop method was invoked by the interop comparison.

After that qualification, all three embedded C# interop definitions move out of the PS runtimes into the compiled `PcuCp.LegacyInterop` net48 library. The remaining PS loader functions preserve surrounding initialization behavior, load only the explicit matching DLL, and reject a previously loaded conflicting definition. This removes **20,786 further PS bytes**. Actual retained wrapper/server loader fixtures are added for the next exact-commit Windows run; interactive DPI/input effects are still not claimed.

The qualified safety classifier body now delegates to the closed native compatibility registry; its private truncation helper is retired. Missing, old, failed or malformed native replies throw rather than classifying an action as safe. An actual retained-PS-bridge differential is added alongside the original 57 kernel cases. The new source legacy route needs the matching native host and compiled interop DLL. Core/portable routes remain direct Python/C#.

Current all-tracked-PS measurement: **29,343 bytes removed**, `1,013,478` → `984,135`. This is actual source replacement, including bridge overhead, not denominator growth. No source is hidden, renamed to influence statistics, or copied into an archive in the current tree. These figures do not imply full feature parity or zero PowerShell.

The next qualification-only candidates are captured-input coordinate math and literal workflow planning. Original coordinate acquisition/math remains until its 115 Windows differential fixtures pass. The workflow candidate is excluded from the shipped native host: broad PowerShell parser-language parity is explicitly unresolved, and its original parser/production dispatcher remain intact. Full parser qualification must pass before any replacement.


At checkpoint `b6a29f0` / run `36897093256`, actual interop loader and safety classifier bridge checks passed, as did all 115 coordinate cases. Core, portable and browser jobs were green; the Windows job failed in two still-unretired strategy/literal-parser candidate qualifications. The qualified coordinate mapping body and three private math helpers are now replaced, retaining original acquisition and risk-profile behavior in a small adapter. Current tracked PS total is **977,889 bytes**, an actual reduction of **35,589 bytes** from baseline. The new retained coordinate adapter awaits its own differential check. Workflow plan assembly is being qualified independently from its original retained tokenizer; the unqualified literal lexer is not shipped.


Checkpoint `2d8443d` / run `36898932493` passed all four jobs, including the actual coordinate adapter and the full parsed-plan assembly proof. The qualified workflow builder is now a small exact-tokenizer adapter, removing another **4,541 PS bytes**. Current all-tracked PS total is **973,348 bytes**, an actual reduction of **40,130 bytes**. Run `python pcucp-next/packaging/check_migration_inventory.py` to reproduce and check canonical Git-tracked blob sizes and retained function locations; `--update` updates counts only after reviewed PS changes are staged. This is independent of GitHub Linguist and checkout line-ending conversion.

Strategy retirement still waits for additional en-US/ko-KR/tr-TR/invariant culture comparisons. Image diff has a separate net48/System.Drawing candidate so legacy PNG/BMP/JPEG/GIF/TIFF decoding is not narrowed to the modern PNG-only API; generated-file and exact error fixtures must pass before its PS body changes.

## Bounded milestone

See [the checkpoint report](migration-checkpoint-report.md) for the coherent
architecture, measured source retirement and explicit remaining acceptance scope.
The qualified preset body is now a thin planning-query adapter; aggregate tracked
PS is 959,852 bytes, down 53,626 bytes from baseline including bridge overhead.
This does not meet the lowest/zero-PowerShell goal. Its actual adapter and output
formatting are required checks in the current commit's Windows CI. Strategy and
image PS bodies remain; no further family is retired on candidate-only evidence.
