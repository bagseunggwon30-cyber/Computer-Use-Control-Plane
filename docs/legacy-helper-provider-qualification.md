# Owned actual helper-provider qualification gate

## Later rerun: current UIA qualification remains blocked

The first 31-case success below is retained historical evidence. At unchanged
provider code in public `ed659953ea358437d99f221c584e16f3704f5999`, later run
`37120186487` validated the other 20 cases but its 11-case UIA process exceeded
the unchanged 90-second bound. It emitted 3,357,209 stdout bytes before owned
termination; raw drain was complete, stderr empty, and output untruncated.
Requests 1–9 completed, including root-fallback request 9; requests 10
(`uia-run-reused`) and 11 (`health-uia`) have no completed records. The evidence
does not yet distinguish cumulative fixture cost from a blocked API. The group
is incomplete and earns no current qualification credit. The historical helper
action/transport suite completed successfully in that same job; the job failed
because of this actual-provider group.

Artifact `11273292125` has archive SHA-256
`6482f3dcf9c38a493eb6ee04794acfc6be040f524ea02ca4b5e767681bde725b`.
The stall boundary and difference from the prior successful group are under
investigation. No deadline increase, automatic retry, provider/output
normalization, activation or retirement is justified by the prior pass.

Candidate only. The owned Windows provider layer passed at `baeed795`; the
complete helper workflow still failed for a separate autostart evidence check.
This gate changes no helper runtime, original PowerShell body,
production route, installation, registration or default. **Retirement credit is
zero.** It covers the owned real-acquisition layer instead of treating inert
fixtures as proof of UIA or WinRT behavior.

## Run and verdict

On an isolated authorized Windows fixture runner:

```text
python pcucp-next/packaging/qualify_legacy_helper_providers.py --windows --log-dir .migration-logs/helper-provider
```

`qualify_legacy_helper.py --windows` runs it automatically, before historical
oracle setup. The two gates collect independent outcomes: provider failure does
not prevent historical startup/Args/functional evidence, and historical build or
comparison failure does not prevent the provider gate. The existing path-triggered
helper workflow includes the owned-window fixture and the new runner. It retains
`contents: read`, bounded job time and always-uploaded evidence.

Without `--windows`, only the independent expectation regressions execute. Its
verdict is `portable-only-windows-unqualified`, with zero actual cases validated.
`--windows` on another OS is a hard refusal. Missing desktop, WinRT, OCR language,
provider or fixture readiness is a failed/unqualified result, never a passing
skip or substitute. The gate does not install languages or change settings.

The Windows gate requires six separate fixed probe groups and all 31 cases.
There are no arbitrary commands, scripted action files or production launch
selectors in the probe. Each group uses the unchanged actual
`WindowsLegacyHelperProvider` and `LegacyHelperActions`; succeeding requests
share one actual provider and reducer in that process. This qualifies provider
behavior/reuse, not a replacement for the separately qualified persistent pipe,
detached launch, client or wrapper tests.

## Independent outcomes, not self-comparison

- Native: exact owned HWND/PID/title/class/outer rectangle through `windows` and
  `focused`, an absent-title query, cold/warm health and request counting, actual
  modal enumeration with the owned non-modal small-window candidate, and the
  closed unsupported-action fallback. Focus is never forced. If normal owned
  form startup does not make it foreground, focused qualification fails.
- UIA: missing label; Unicode unique/prefix/contains labels with numeric scores
  100, 80 and 50; read-only edit and disabled button roles; duplicate labels with
  acquisition-order ties; 24 owned cap buttons yielding the first 16; and an
  existing named control after at least 800 acquired elements that must remain
  outside the scan. Missing-label, owned no-match and unmatched-root fallback
  have their exact distinct schemas. Successful loading is reused once.
- OCR files: generated black text `HELLO 2468`, blank image, zero/truthy default
  arguments producing an owned 800x600 blank image, deliberately invalid PNG,
  then successful reuse. All initialization, language selection, file loading,
  decoding, recognition, resource cleanup and maximum-dimension acquisition are
  actual Windows-provider operations. Only image generation replaces capture.
  Actual invalid bitmap dimensions exercise `screenshot_failed`; the real
  maximum-size query rejects oversized regions before path/capture acquisition.
- OCR screen: twice capture exactly the fixture's 560x70 white text label, with
  actual `CopyFromScreen` and WinRT recognition. No generated-image substitute
  can satisfy these cases. Both responses must have the exact region, text,
  line/word counts and successful warm schema.
- OCR fallback/retry: explicit test-only seams replace an actual profile-query
  result with null, and in the retry group replace an actual language-list result
  with empty. Raw actual results and substituted results are both retained and
  labeled. The fallback uses the real first available language and actual
  `TryCreateFromLanguage`; the retry repeats real initialization and profile
  creation. Recognition must use exactly the retained successful engine identity.
  These are fault-boundary tests with real downstream operations, not claims that
  this machine naturally lacked a profile/language or experienced loader failure.

Expectations check exact fields/types, array order, labels, roles, geometry,
scores, best/click selection, status/reason and acquisition identities. Public
outputs are never trimmed or normalized, including OCR whitespace. Fixture-owned
geometry comes from independent WinForms bounds, including the TextBox's outer
border rather than its client rectangle. Acquired UIA metadata is recorded as a
separate read-only diagnostic; its errors fail qualification but cannot change a
provider return. Changing a pane proxy to a button, changing identities, or
substituting a different best result is not accepted.

Only known owned outcomes are deterministic fixture assertions. Other top-level
windows, foreground records and modal candidates are retained as incidental
whole-desktop observations. Their schemas, numeric/stable ordering and selected
recommendation are checked against complete acquisition evidence; their presence
is not a portable expected desktop population. Root-fallback scanning is bounded
at 800. No arbitrary desktop screenshots are requested.

## Ownership, evidence and bounds

The existing WinForms fixture gets an explicit `helper-provider` mode. Its
ordinary observation mode retains its layout and behavior. The added controls,
labels and images are generated by this test. Readiness requires the retained
fixture process PID, native HWND, exact generated title and interactive desktop.
The probe independently checks native ownership, title, visibility and iconic
state. It neither sends input nor invokes, edits, focuses or registers providers.
Before and after an actual screen capture, every pixel location in the exact
owned rectangle must resolve to the owned root window. Occlusion refuses or
fails the case. This is a bounded race check around the authorized owned-region
capture, not an atomic desktop-ownership guarantee.

Actual-provider operations, arguments, results, errors and process-local object
identities are retained. Explicit seams retain both actual and effective results.
Successful captured/generated images are copied into the owned evidence folder;
Python independently verifies the recorded size/hash and bounded group-specific
path. Invalid generated PNG bytes are retained too. Temporary OCR paths must be
unique generated filenames inside the dedicated test TEMP, and successful decode
cleanup must remove them. Any leftover file fails the gate.

The owned form's readiness and closed records must both have zero key/mouse,
button-invoke and value-change counters. Closure is a test-owned file signal,
with bounded fallback termination only through the retained fixture process
handle. Console probes use `CREATE_NO_WINDOW`, so their console cannot steal
foreground or cover the owned region. No process is discovered or killed by a
lock PID and no group is automatically retried.

Every subprocess saves bounded raw stdout/stderr and complete exit, timeout,
truncation, launch, read and drain evidence before parsing/assertions. One failed
group does not prevent the other five. Each group has a 90-second process budget;
readiness and cleanup have 30/10 seconds. The enclosing 1500-second budget exceeds
the runner's full per-stage budget, leaving cleanup possible. Probe collections,
window counts, call counts, images and raw streams are independently bounded.
The 43 portable expectation-regression methods must be discovered; zero tests
and unexpected skips are failures.

## Relationship to original evidence and next decision

The pinned original startup, Args binding, OCR type-variable and PowerShell score
ordering observations remain intact. The existing functional oracle's only body
corrections remain its separately approved OCR type variables and numeric stable
ranking. This gate neither replaces those streams nor changes their classification.

The one-shot original/compiled UIA binding investigation is separate: original
PowerShell-first acquisition observed HWND/pane proxies, while compiled-first
acquisition observed named button/edit providers. The parent investigation found
an original `ProxyManager.LoadDefaultProxies` failure despite identical assembly
identities. A separately reviewed compiled-initialization corrected-intent oracle
may address that boundary; this gate does not implement it or treat its output as
original parity. These owned expected results intentionally require working
controls. Original-provider parity remains `unqualified-not-compared` here.

A full Windows pass establishes this candidate's owned provider coverage. It does
not alone approve activation or retirement. Any failed identity, role, best,
loader or OCR result must be reported with the retained raw case and reviewed
before a runtime correction. This gate makes the missing evidence and stopping
condition explicit; no indefinite duplicate-runtime retention or premature
retirement is justified by a portable pass.

Mixed DPI, elevation, cross-session/principal access, arbitrary applications,
input/IME/clipboard and environmental no-foreground/loader-failure branches remain
outside the owned proof. Existing inert contracts continue to cover those reducer
error branches without claiming they occurred on a real desktop.

## Initial local verification

Linux compiled both net48 probe and owned WinForms fixture with zero warnings or
errors. The locally available SDK/runtime is 10; net8-targeted portable contracts
run with `DOTNET_ROLL_FORWARD=Major`, not actual net8/Framework execution.
All 43 independent expectation regressions passed. The integrated helper gate
passed 117 action contracts, 45 wire contracts and six bounded raw-evidence tests;
its Python helper suite reported 215 methods with 34 explicit skips. The unchanged
observation structural suite passed 24 methods. Full Python discovery reported
932 methods, `OK (skipped=163)`; that skip report includes class-setup skips and
must not be treated as an executed-method count. Independent review found no
remaining local/static blocker after the geometry, console, timeout and verdict
mutation fixes. The initial `51eb240` base measured 962,188 tracked PowerShell
bytes; the provider gate patch added/removed no PowerShell bytes. Actual Windows/WinRT/UIA
execution was still pending at that local-only checkpoint. The separately
verified Windows result below supersedes that limit for the owned provider layer.


## Verified Windows provider result at baeed795

[Run 37119545970](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37119545970)
executed public commit
[`baeed79529485483428caa58eb550d32b477fcd7`](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/commit/baeed79529485483428caa58eb550d32b477fcd7),
tree `f7bc2719aa0482340d373c0c73d7bee39a3a42d4`. The actual-provider
subgate passed **all 31 required cases**, on Windows Server 2025 build 26100
and Python 3.12.10. Both net48 fixture/probe builds had zero warnings/errors;
43 expectation-regression methods reported 42 passes and the single explicitly
allowed non-Windows refusal-control skip.

The retained [artifact 11272851963](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37119545970/artifacts/11272851963)
contains 1,152 files. Its archive SHA-256 is
`7fa30bd6525857af43ed09e407040d02d75357348bd0a7064d7bddbd428ce522`.
The `actual-providers` directory retains the summary, all six raw JSON-line
streams/process records, source and binary hash manifests, generated/owned
images, and fixture readiness/closure. Independent reinspection re-ran the exact
expected-result checks on every raw case, without response normalization:

| Group | Required cases | Recorded acquisition calls | Raw stdout bytes |
| --- | ---: | ---: | ---: |
| Native | 7 | 241 | 38,333 |
| UIA | 11 | 6,530 | 3,798,087 |
| Generated-file OCR | 7 | 76 | 22,432 |
| Owned-region OCR | 2 | 29 | 7,953 |
| Explicit language fallback | 2 | 31 | 8,447 |
| Explicit initialization retry | 2 | 19 | 5,046 |
| Total | 31 | 6,926 | 3,880,298 |

The 6,926 records include 6,915 actual-provider-tagged operations, eight explicit
generated-image records and three labeled profile/language substitution records.
They are not 6,926 unmodified acquisition operations.

All six actual-provider processes exited zero, with empty stderr, complete
stdout/stderr drains, exact base64/raw-byte agreement, and no timeout, truncation,
launch, read, stdin or cleanup failure. The UIA group took 45,203 ms, below its
90-second bound; the owned form closed cleanly after 50,671 ms. No process retry
was used. These checks apply to the actual-provider subgate, not the overall job.

### What the actual observations establish

- `windows` and `focused` returned the owned fixture's exact HWND 2031736 and
  PID 7164, title, class and 620x570 outer bounds. The absent-title query returned
  zero windows. Native health advanced from request 1/cold Win32 to request
  7/warm Win32; unsupported action 6 retained its explicit fallback schema.
- Actual UIA returned the named `button` and `edit` providers. The Unicode label
  selected `Run 한글` with scores `[100,80,50]`; duplicate labels retained the
  first acquired result at `(328,201,130,40)`. The 24 cap buttons yielded exactly
  the first 16, stopping after 28 subtree name reads. The owned subtree contained
  852 elements; `Beyond scan` existed at zero-based index 846. That request read
  exactly 800 subtree names and returned the precise `partial/no_match` result.
  Successful UIA/Win32 loads were reused, and health counted all 11 UIA-group
  requests. Whole-desktop foreground/modal populations remained incidental data.
- Actual screen OCR twice captured only `(148,591,560,70)` and returned exactly
  `HELLO 2468`, one line and two words, with the same successful engine identity.
  Both retained captures are 2,768-byte PNGs with SHA-256
  `de43af39e3b64b28d9b17937f6052659720d617d8d9a4fab9fbd523ad9026f0f`.
  The source-verified pre/post per-pixel owned-root checks completed on both
  successful calls. This is the documented bounded ownership check, not a claim
  of an atomic capture or a retained per-pixel ownership trace.
- All ten image artifacts were independently rehashed against their recorded
  byte counts: nine readable PNGs and one deliberately invalid PNG byte file.
  Visual inspection of generated text and owned captures confirmed only the
  owned black text on white; both blank images were uniformly white, at 560x70
  and 800x600 respectively. Real WinRT recognized the generated text and blanks,
  rejected the corrupt file with `ocr_failed`, and succeeded again using its
  cached engine. The actual maximum dimension was 10,000; oversized capture was
  rejected before creating a temp path. Negative bitmap width produced the
  separate `screenshot_failed` result without decoding.
- The fallback/retry cases were explicit seams. The real profile call actually
  returned an engine and the machine had one available language. The harness
  substituted null, then used that real language through `createLanguage`; both
  recognition calls reused the newly created engine. The retry additionally
  substituted an empty language list, emitted the exact no-language error, then
  performed a second real initialization/profile call and recognized successfully.
  These results do not establish a naturally missing profile or language pack.
- Readiness and closure each retained zero input, invoke and value-change
  counters. Every successful OCR cleanup recorded the file absent, and the final
  dedicated TEMP inventory was empty. No input, production activation, installation,
  registration, startup setting or production route was changed.

### Source provenance and line endings

The checked-out source hash manifest measures Windows CRLF bytes, whereas the
published Git blobs use LF. Independent reconstruction of each of the eight
recorded sources with only LF-to-CRLF checkout expansion reproduced its exact
recorded byte count and SHA-256. No other source difference was accepted. The
local verified source tree equals the public tree above; binary identities are
recorded in the artifact's separate four-file manifest. The artifact does not
include those executables for an independent binary rehash.

For example, `LegacyHelperProviders.cs` is 12,041 LF Git bytes, versus 12,219
Windows checkout bytes with SHA-256
`52c1fbd9adcaf50554222952cc9f7f280fa787de1e3024d0df7e832a7bcaa8c4`.
The 16,597-byte LF provider probe becomes exactly 16,839 CRLF bytes with SHA-256
`b1a9e2f7a3926b80b3f3817d2c94ed64082b66c13b422b9af7671adede1458e8`.
This reconciliation is exclusively source provenance: every observed response,
diagnostic, image and raw output byte remains unchanged.

### Overall result and remaining limits

The complete helper workflow was **not green**. Its later 269-method helper suite
reported one failure and 28 skips. The sole failure was
`test_original_venv_argument_mismatch_remains_exact_hash_pinned`, whose recorded
autostart manifest CRLF bytes did not match its LF hash pin. That independent
failure does not erase this completed provider evidence or become an expected
provider success; its repair/qualification is tracked separately.

The result qualifies this compiled candidate's owned Windows acquisition/OCR
layer and explicit fallback boundaries. It does not establish original-provider
parity, amend the original failed startup/Args/OCR/ranking observations, authorize
production activation, or retire source. The separate one-shot UIA loader
compatibility decision and the other environmental limits listed above remain.
This documentation update changes no executable or test expectation.

## Bounded diagnostic preparation after the later timeout

The later `ed659953` timeout remains unresolved. Its nine complete UIA responses
end at `uia-root-fallback` (request 9); requests 10 and 11 are absent. The last
retained reducer call is `uia.name` returning `Filler 741`, followed by the complete
879-element diagnostic array. The original post-case-only output cannot identify
whether the next request's acquisition, diagnostic reads, reducer, serialization
or stdout write was active at termination. Nine independently valid responses do
not qualify a timed-out group: the later run remains **20/31, unqualified**.

The original eight source hashes are identical across the passing and timed-out
runs. All four binary hashes differ. A local generated AssemblyInfo inspection
shows that the SDK embeds the Git SourceRevisionId in AssemblyInformationalVersion
(for example `1.0.0+51eb240ff26cd34f62dd0987ee4136a5013ced30`). Its SDK target
explicitly appends that revision. This is a concrete mechanism for binary changes,
not proof that it explains every difference in the previous CI binaries; their
generated AssemblyInfo files and executable bytes were not retained.

This next patch changes only the qualification harness and its portable tests:

- Each owned probe writes a separate `<group>-progress.jsonl` using create-new
  semantics, bounded at 2,048 records and 1 MiB. Every complete record is flushed.
  Normal progress goes neither to stderr nor into the original response schema.
- Monotonic group/request ticks bracket dispatch, selected actual acquisitions,
  subtree evidence materialization, independent diagnostic metadata enumeration,
  response serialization and stdout write/flush. UIA assembly load, root, children
  and subtree acquisition have entry/exit markers. Scan and metadata loops emit
  sparse progress every 128 elements, rather than logging every property getter.
- `provider_ticks` sums actual `Invoke` durations and excludes independent
  diagnostic reads. Native window enumeration has separate inclusive markers,
  avoiding double-counting its nested callbacks. `diagnostic_ticks` measures the
  metadata getter/snapshot work. `write_ticks` measures prior progress-record
  formatting/write/flush cost. Dispatch remains an inclusive wall-clock phase;
  these counters must not be added to it as disjoint work.
- A missing, partial, misordered or contradictory progress stream remains
  unqualified. Valid original UIA requests require actual traversal, evidence and
  metadata intervals. Last complete markers and raw hashes survive a failed
  group for diagnosis; a retained prefix is never completion evidence.
- A separate `uia-cold` process makes one valid `uia-run` request as its first
  helper action. It defers all independent diagnostic `Current` property reads
  until `Dispatch` has returned and its end marker has been flushed. Exact output
  and acquisition checks still apply. Negative validator tests reject diagnostic
  metadata before this cold dispatch returns. This is cold helper/client state,
  not globally cold Windows/UIA server state: the owned fixture/OS may already
  have served other groups. It adds new coverage and does not retroactively
  qualify the earlier first-valid-action result.
- The original six groups, 31 requests, acquisition order and expected responses
  remain unchanged. The separate cold control has its own required/validated
  fields; it cannot turn an incomplete original group into a pass.
- Every process group still has a 90-second deadline, with the unchanged
  1,500-second enclosing deadline. The preflight budgets are now 60 seconds for
  the original expectations and 30 seconds for progress tests; both builds remain
  300 seconds, readiness/closure remain 30/10 seconds. Seven groups plus setup
  total 1,360 seconds. Allowing 13 two-second kill/0.4-second drain tails and an
  additional 30-second orchestration reserve remains below 1,500 seconds. No
  deadline is extended and no automatic rerun is added.
- Before fixture launch, exact generated AssemblyInfo bytes, hashes, assembly
  versions, informational versions and any revision suffix are retained for all
  four built assemblies, alongside their existing binary hash manifest. Source
  revision metadata is recorded without inventing a missing revision or claiming
  that matching source hashes establish executable identity.

The repeated diagnostic reads are a candidate contributor, not a demonstrated
cause. The completed timeout rows contain 6,843 element diagnostics, implying
34,215 additional `Current` getter evaluations from the verified source. This is
a lower bound for that run, not a count of guaranteed cross-process calls. The
previous successful group used the same instrumentation and completed 38,500
such evaluations in 45,203 ms. New phase evidence is needed to distinguish
cumulative harness cost from a slow or stalled production acquisition.

The acquisition gap is a separate production risk. `FindAll(TreeScope.Subtree)`
materializes its full result before the reducer applies its 800-element scan cap.
Whole-desktop fallback returned 884 versus 879 elements across the two runs,
while the owned population remained 852, so it is incidental and nondeterministic.
It completed in both retained traces and is not the proven timeout cause. Before
production activation, acquisition needs either a demonstrated order/selection-
preserving traversal bound or documented, enforced owned-process/deadline
containment. This diagnostic patch implements neither runtime redesign and earns
no activation or retirement credit.

Local diagnostic verification passed both net48/portable builds with zero warnings
or errors, 117 action contracts, 45 wire contracts, 19 real file-writer contracts,
94 progress/metadata regressions and the original 43 expectation regressions.
Actual C# progress files round-tripped through the Python validator (58 native
and 22 cold-control marker records). The integrated portable helper suite reported
270 methods with 52 skips; full Python discovery reported 1,097 methods,
`OK (skipped=181)`, including class-setup skips. Independent review approved this
diagnostic-only patch. No new Windows execution, timeout cause or cold-action
qualification is claimed.
