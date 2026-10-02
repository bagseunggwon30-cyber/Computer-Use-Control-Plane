# CDP host adapter draft (not activated)

The executable candidate is the real, counted PowerShell source
`tests/fixtures/legacy-cdp-adapter.ps1`. Tests AST-load its exact functions solely
to qualify the actual process/adapter boundary. No old function
body is replaced until integration is activated and the adapter manifest is enabled.
The implementation remains in Python/JS; the retained host owns acquisition,
logging, its Console serializer, and its startup permission state.

## Shared process bridge

Promote the candidate to one shared retained source, such as
`scripts/cucp-legacy-cdp-adapter.ps1`, and load it from each retained host.
Initialize `$Script:LegacyCdpSourceRoot` once from the trusted repository root.
`CUCP_LEGACY_CDP_HOST`, if configured, names an existing CUCP executable with the
closed `legacy-cdp-bridge` command. Otherwise `CUCP_LEGACY_CDP_PYTHON` names an
existing source-mode Python executable. Both are host startup configuration,
never page content or tool arguments. Portable support remains unqualified until
the bundle tests exercise the same bridge. In source-mode tests,
`CUCP_LEGACY_CDP_TEST_PYTHON` supplies this executable. There is no install step.
The child runs only the fixed module, with Python environment variables ignored.

Executable source: `tests/fixtures/legacy-cdp-adapter.ps1`, region `cdp-process-bridge`.

## Public macro delegate

The existing public macro names each delegate to `_Invoke-LegacyCdpMacro` with
its fixed action name. Existing `Test-CdpPortQuick` remains shared with SmartPlan,
HealthDetail and SmartClick until those callers also migrate. Its exact port
query, native argv, raw output, Console rendering and trajectory seam are retained.
A timeout or failed bridge is never retried or routed back to old implementation.
If completion framing, logging, or output fails after a possible live dispatch,
the delegate emits a small fixed partial result with
`mutation_may_have_occurred:true`, `automatic_retry:false`, and exit 2. It does
not depend on the failed serializer. Uncertainty is derived from the fixed live
action family and startup permission; read-only bridge failures remain read-only
even when startup live permission is enabled. If stdout itself fails, it attempts stderr
once; closed output channels can still prevent reporting, but no action is retried.

Executable source: `tests/fixtures/legacy-cdp-adapter.ps1`, region `cdp-macro-delegate`.

## Native interception and typed native-helper delegate

Intercept CDP in `Invoke-NativeHelper` before its raw `powershell -File` route or
any server fallback. Do not append an authority switch to that raw argv: a text
value that looks like a switch could otherwise rebind startup permission.
The interceptor's pure parser consumes every known value once, rejects unknown
or authority parameters, and returns typed data. The outer wrapper's existing
`AllowLiveControl` is passed separately in the fixed Python startup arguments.
Only existing numeric loopback port data becomes the child startup endpoint.

Executable source: `tests/fixtures/legacy-cdp-adapter.ps1`, region `cdp-native-intercept`.

All migrated wrapper queries begin with the fixed `-Action`, exact action pair.
Route this pair to `_Invoke-LegacyCdpNativeArgv -ArgList $ArgList
-LiveAuthority:([bool]$AllowLiveControl)` before old helper loading. Do not select
this route by searching for `-Action` inside an arbitrary text value. Unexpected
CDP arg layouts must be parsed by the closed parser before any old `-File` route,
or rejected; never fall through to the untyped child path after parser failure.

For retained standalone native-helper action names, add a typed optional
`[hashtable]$CdpStartup` parameter, not a boolean argv switch. The native delegate
accepts only exactly `{allow_live_control = <actual bool>}`. A raw `-File` text
argument cannot become that hashtable; malformed startup data fails closed.
Normal public wrapper/daemon calls use the direct interceptor above and never
serialize authority into native helper argv. A human making a standalone live
call must use typed PowerShell invocation with that explicit startup object, or
the Python bridge's explicit startup live flag. No authority is inferred from
an action name, page data, or a native reply.

Executable source: `tests/fixtures/legacy-cdp-adapter.ps1`, region `cdp-native-delegate`.

## Required integration safeguards

- In `Invoke-NativeHelper`, intercept CDP before the existing raw child route.
  Pass live authority separately from outer startup state. The daemon already
  reaches this same path through `Invoke-Macro`; no persistent-helper CDP route
  is currently enabled. Do not add one merely for this migration.
- `Invoke-MacroSmartClick` currently swallows stage-zero errors before UIA/OCR
  fallback. Stop that cascade on `mutation_may_have_occurred`. A bridge transport
  failure after live dispatch is equally uncertain; do not fall back or retry.
- Keep original bodies until focused Windows and browser tests pass. Then replace
  only qualified functions, retain shared `Test-CdpPortQuick` until all users have
  migrated, update the static inventory from measured source function spans, and
  run the bundled full regression before claiming the family retired.
- The exact host JSON serializer remains a shared dependency. This draft does not
  claim it has been migrated or remove it behind a renamed wrapper.

## Measured retirement proposal

Current old CDP-named function bodies occupy 64,988 UTF-8 bytes (function extents
only, excluding surrounding comments). Retaining the shared 1,307-byte
`Test-CdpPortQuick` and counting every draft block as future PowerShell, including
one shared 4,820-byte process bridge, gives 11,540 executable code bytes. Counting
the complete 11,939-byte `.ps1` fixture, including headers/regions/BOM, gives a
candidate reduction of **51,742 bytes** when one shared bridge source is used. The staged fixture
adds real `.ps1` bytes temporarily; no executable code is hidden in Markdown and
this is not a language-percentage claim.
Initializer/dispatch glue is additional and must be included in the final staged
inventory. The original broader 72,323-byte family estimate includes surrounding
source; no comments-only reduction is needed to establish meaningful retirement.

No bytes have been retired by this draft. Recompute actual staged `.ps1` blobs
with `check_migration_inventory.py` after integration and qualification. Keep the
original body if any required Windows/browser/actual-adapter gate fails.

Qualification: `test_legacy_cdp_bridge.py` exercises the actual Python process
locally. `test_legacy_cdp_adapters.py` is opt-in with
`CUCP_LEGACY_CDP_TEST_PYTHON` on Windows. Before promotion it loads exact
functions from the `.ps1` fixture; after `cdp` is enabled in
`.github/migration-adapters.json`, it requires and loads the current production
function bodies instead. `CUCP_LEGACY_CDP_ADAPTER_MODE=draft|production` explicitly
selects a mode for focused manual qualification. It tests
macro Console/query/trajectory results, startup-authority-looking data values,
standalone typed delegation, process output/deadline bounds, and large successful
live replies or failed logging after dispatch. The production mode also tests
`Invoke-NativeHelper` interception before the old runtime lookup. These are draft
adapter checks, not a claim that the central host is already switched.

The first exact Windows gate (`120b64a`, run `36997186053`) failed. Its repair
candidate suppresses Framework's `VoidTaskResult` pipeline value, drains ready
stdout/stderr without a per-buffer wait, and accepts a single UTF-8 prefix BOM
from Framework's automatically initialized stdin writer. The same strict JSON
field/duplicate/size checks remain in force. A fixed-data raw-byte round-trip
fixture independently diagnoses the actual host framing. Source/frozen launch,
the original Console differential, authority-looking values, and post-dispatch
uncertainty still require a successful Windows gate before promotion.
