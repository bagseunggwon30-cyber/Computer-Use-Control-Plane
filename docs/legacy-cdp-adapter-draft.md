# CDP retained host adapter contract

The retained PowerShell glue is the one shared
`scripts/cucp-legacy-cdp-adapter.ps1`; both `scripts/cucp.ps1` and
`scripts/cucp-native-helper.ps1` load this source. The original CDP implementations
and the duplicate `tests/fixtures/legacy-cdp-adapter.ps1` candidate are removed.
Tests AST-load the exact current functions to qualify the actual process/adapter
boundary. The adapter manifest enables `cdp` and selects the production source.
The implementation remains in Python/JS; the retained host owns acquisition,
logging, its Console serializer, and its startup permission state.

## Shared process bridge

Each host initializes `$Script:LegacyCdpSourceRoot` from its trusted repository
root before loading `scripts/cucp-legacy-cdp-adapter.ps1`. Its four regions retain
the process bridge, public macro delegate, central interceptor and typed native
delegate without duplicating the process implementation.
`CUCP_LEGACY_CDP_HOST`, if configured, names an existing CUCP executable with the
closed `legacy-cdp-bridge` command. Otherwise `CUCP_LEGACY_CDP_PYTHON` names an
existing source-mode Python executable. Both are host startup configuration,
never page content or tool arguments. Portable support remains unqualified until
the bundle tests exercise the same bridge. In source-mode tests,
`CUCP_LEGACY_CDP_TEST_PYTHON` supplies this executable. There is no install step.
The child runs only the fixed module, with Python environment variables ignored. Default
application discovery explicitly limits `Get-Command` to the first PATH match:
with `-CommandType Application`, PowerShell can otherwise return several same-name
executables. A duplicate-Python PATH fixture keeps a real first executable and an
inert second file, proves both are discoverable, and requires the unchanged
no-live rejection without a native-helper call. Explicit host/Python overrides
retain their existing behavior.

Executable source: `scripts/cucp-legacy-cdp-adapter.ps1`, region `cdp-process-bridge`.

## Public macro delegate

The existing public macro names each delegate to `_Invoke-LegacyCdpMacro` with
its fixed action name. Existing `Test-CdpPortQuick` remains shared with SmartPlan,
HealthDetail and execution acquisition, including SmartClick's CDP stage. Its exact port
query, native argv, raw output, Console rendering and trajectory seam are retained.
A timeout or failed bridge is never retried or routed back to old implementation.
If completion framing, logging, or output fails after a possible live dispatch,
the delegate emits a small fixed partial result with
`mutation_may_have_occurred:true`, `automatic_retry:false`, and exit 2. It does
not depend on the failed serializer. Uncertainty is derived from the fixed live
action family and startup permission; read-only bridge failures remain read-only
even when startup live permission is enabled. If stdout itself fails, it attempts stderr
once; closed output channels can still prevent reporting, but no action is retried.

Public smart/deep text is filtered in the JS assets before ranking and output
construction. Form value attributes/properties and source-only subtrees cannot
flow into candidate summaries, locator strings, briefs or smart trajectory logs.
Visible input button/submit/reset captions remain eligible. Matching and ordering
that depended on excluded text intentionally change; the exact host serializer
and normal Console format remain unchanged. See the
[privacy boundary](legacy-cdp-family.md#explicit-safety-and-corrected-behavior-boundaries)
for bounded ancestor-text reconstruction and the TEMPLATE distinction.
Textarea default text is excluded through direct and ancestor getters as well;
textarea controls still support descriptive labels and authorized typing.

Executable source: `scripts/cucp-legacy-cdp-adapter.ps1`, region `cdp-macro-delegate`.

## Native interception and typed native-helper delegate

`Invoke-NativeHelper` intercepts CDP before its raw `powershell -File` route or
any server fallback. No authority switch is appended to that raw argv: a text
value that looks like a switch could otherwise rebind startup permission.
The interceptor's pure parser consumes every known value once, rejects unknown
or authority parameters, and returns typed data. The outer wrapper's existing
`AllowLiveControl` is passed separately in the fixed Python startup arguments.
Only existing numeric loopback port data becomes the child startup endpoint.

Executable source: `scripts/cucp-legacy-cdp-adapter.ps1`, region `cdp-native-intercept`.

Every internal `Invoke-NativeHelper` request must begin with a nonempty
`-Action`, action pair; the key comparison is ordinal and case-insensitive.
The host rejects a missing, incomplete, empty, or reordered leading pair before checking
the old native-helper path or accessing any server, cache, or child runtime.
For an action beginning with `cdp-` (ordinal, case-insensitive), it routes the complete
argv to `_Invoke-LegacyCdpNativeArgv -ArgList $ArgList
-LiveAuthority:([bool]$AllowLiveControl)` before old helper loading. Do not select
this route by searching for `-Action` inside an arbitrary text value. An unknown
CDP action still reaches the closed parser and fails there; parser failures never
fall through to the untyped child path. The parser accepts the fixed lowercase
action names emitted by all public wrappers. Uppercase action values are rejected,
including when the case-insensitive prefix intercept recognizes their family.

The call-site audit found that public macros, daemon macro dispatch, SmartPlan's
validated descriptors, precision queries, and benchmark tables all construct this
leading pair. Their argument order remains unchanged. Direct undocumented calls
to the internal function with reordered argv are now rejected. Standalone native
helper PowerShell parameter ordering is a separate interface and is unaffected.

Retained standalone native-helper action names use the typed optional
`[hashtable]$CdpStartup` parameter. The native delegate
accepts only exactly `{allow_live_control = <actual bool>}`. A raw `-File` text
argument cannot become that hashtable; malformed startup data fails closed.
Normal public wrapper/daemon calls use the direct interceptor above and never
serialize authority into native helper argv. A human making a standalone live
call must use typed PowerShell invocation with that explicit startup object, or
the Python bridge's explicit startup live flag. No authority is inferred from
an action name, page data, or a native reply.

Executable source: `scripts/cucp-legacy-cdp-adapter.ps1`, region `cdp-native-delegate`.

## Retained integration safeguards

- `Invoke-NativeHelper` intercepts CDP before the existing raw child route and
  passes live authority separately from outer startup state. The daemon
  reaches this same path through `Invoke-Macro`; no persistent-helper CDP route
  is currently enabled. Do not add one merely for this migration.
- SmartClick's execution coordinator must stop on `mutation_may_have_occurred`
  before UIA/OCR fallback. A bridge transport failure after live dispatch is
  equally uncertain; it must not cause fallback or retry. This cross-family
  boundary remains part of the integrated regression gate.
- The qualified original CDP bodies are removed. Shared `Test-CdpPortQuick`
  remains for other callers. Source retirement is measured from actual tracked
  blobs, including retained glue and tests; the integrated full regression and
  Windows bundle gate are required before declaring this promotion qualified.
- The exact host JSON serializer remains a shared dependency and is still
  PowerShell. This migration does not claim that serializer has been ported.

## Source accounting

Before promotion, old CDP-named function bodies occupied 64,988 UTF-8 bytes
(function extents only), including the retained 1,307-byte `Test-CdpPortQuick`.
The shared adapter now occupies 11,931 UTF-8 bytes including its headers, regions
and BOM. The temporary duplicate fixture is gone. Host initialization, dispatch,
typed startup parameters and every retained `.ps1` test count separately in the
repository-wide inventory; subtracting just those function and adapter sizes is
not the complete net reduction. `check_migration_inventory.py` and
`docs/legacy-function-inventory.json` own that measured total. No executable code
is hidden in Markdown, and the remaining glue is honestly counted as PowerShell.

## Qualification and next gate

Qualification: `test_legacy_cdp_bridge.py` exercises the actual Python process
locally. `test_legacy_cdp_adapters.py` is opt-in with
`CUCP_LEGACY_CDP_TEST_PYTHON` on Windows. Since `cdp` is enabled in
`.github/migration-adapters.json`, it requires and loads the current production
function bodies. `CUCP_LEGACY_CDP_ADAPTER_MODE=production` explicitly selects the
same mode for focused manual qualification; the historical draft mode does not
exercise central integration. It tests
macro Console/query/trajectory results, startup-authority-looking data values,
standalone typed delegation, process output/deadline bounds, and large successful
live replies or failed logging after dispatch. Production mode loads all four
regions from the shared source and the actual `Invoke-NativeHelper` function from
the main host. Its central-route tests cover both startup authority states:
14 malformed-prefix cases fail before Python or the missing old-runtime return;
four unknown-action cases invoke only the real pure parser and never the native
operation; four valid cases preserve live gating, mixed-case parameter keys, and
literal `-Action` expression data. Old server/child sentinels must remain untouched.
The existing 77 exact macro Console/query/trajectory comparisons are unchanged.
These new integration assertions require the promoted Windows gate; portable
collection or an explicit Windows skip does not qualify that boundary.

The first exact Windows gate (`120b64a`, run `36997186053`) failed. The repaired
adapter suppresses Framework's `VoidTaskResult` pipeline value, drains ready
stdout/stderr without a per-buffer wait, and accepts a single UTF-8 prefix BOM
from Framework's automatically initialized stdin writer. The same strict JSON
field/duplicate/size checks remain in force. A fixed-data raw-byte round-trip
fixture independently diagnoses the actual host framing. Source/frozen launch,
the original Console differential, authority-looking values, and post-dispatch
uncertainty passed at `f2333bebd53e28e59a05795abfeb90275dc67d09`, run
`37002020097`: Windows ran 51 tests with 43 passes and eight explicit skips, and
the owned-browser job passed all seven tests.

The final candidate qualification is commit
`e9e015c6bc7b39d52999dccccf6bb4316a6c8dfe`,
[run 37007340738](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738).
Its [Windows CDP job](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738/job/110838651659)
ran 51 tests: 43 passed and eight were explicitly skipped.
Its [owned-browser job](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738/job/110838651552)
passed all seven tests, including the unchanged five behavior cases and guarded
CSS escaping against 52 native-oracle strings. The full-regression job was skipped.
That evidence qualified the candidate before the host source cutover; it does not
qualify the newly integrated production routes or a released portable bundle.
It also predates the public-text privacy correction and its four added browser
cases. The unchanged ordinary comparisons and separate intentional privacy
divergences must both pass with the guard enabled at the next exact commit.

The next required validation is the integrated production/full regression and
Windows bundle gate. Locally, Linux mock/Node tests pass, Windows PS5 assertions
are skipped, and the owned Chrome fixture cannot start within this local sandbox.
No local Windows/browser pass or portable legacy-macro support is claimed.
