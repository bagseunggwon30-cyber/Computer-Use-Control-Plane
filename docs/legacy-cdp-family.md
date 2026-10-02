# Legacy CDP family and retained host integration

The complete legacy browser family has a Python implementation and used JavaScript
assets under `pcucp-next/python/pcucp_cli/legacy_cdp*`. It is independent of the modern
`CdpAdapter` public contract. Both retained PowerShell hosts now load the single
`scripts/cucp-legacy-cdp-adapter.ps1`; original CDP bodies and the duplicate draft
fixture are removed. Focused candidate qualification passed at `e9e015c6`.
**The integrated production/full regression and Windows bundle gate are the next
required validation; this source cutover is not yet a qualified release.**

## Host interfaces

```python
from pcucp_cli.legacy_cdp import LegacyCdpAdapter
from pcucp_cli.legacy_cdp_contract import prepare_macro, native_arguments
from pcucp_cli.legacy_cdp_macro import execute_macro, LegacyCdpPortCache

# Human/host startup configuration, never page content or model tool arguments.
adapter = LegacyCdpAdapter('http://127.0.0.1:9222', allow_live_control=False)
result = adapter.execute('cdp-smart-find', {'needle': 'Save', 'page_match': 'Editor'})
assert isinstance(result.payload, dict)
exit_code = result.exit_code
adapter.close()

macro = prepare_macro('cdp-smart-find', ['--text', 'Save'], allow_live_control=False)
# Native acquisition argv remains available for a retained host adapter:
argv = native_arguments(macro)
```

`execute(action, args, timeout_s=None)` returns `LegacyCdpResult(payload, exit_code)`.
It includes helper `elapsed_ms` and `action`. Commands/arguments:

| Action | Arguments (all also accept `page_match`) |
| --- | --- |
| `cdp-detect` | none |
| `cdp-eval` | `expression` or `expression_b64` |
| `cdp-click` | `selector` |
| `cdp-type` | `selector`, `text`, `clear`, `enter` |
| `cdp-smart-find`, `cdp-smart-type-find`, `cdp-smart-click` | `needle` |
| `cdp-smart-type` | `needle`, `text`, `clear`, `enter` |
| `cdp-deep-find` | `needle` |
| `cdp-prosemirror-insert` | `selector`, `text` |

The real process entrypoint is `python -m pcucp_cli.legacy_cdp_entry --endpoint
http://127.0.0.1:9222 [--allow-live-control]`. Pass one bounded JSON line containing
exactly `action` and `args` on stdin. Stdout is the helper payload; process exit is
the helper exit. The startup flag is never read from the request. The host must
choose endpoint and permission from its trusted startup state, not task/page data.
The entrypoint's compact JSON is a transport frame, not legacy Console rendering.

`prepare_macro` parses original wrapper argv, with first-option/case-insensitive
matching, command-specific port defaults, and original validation strings.
`native_arguments` generates the exact original native-helper query argv.
`execute_macro(adapter, macro, cache=LegacyCdpPortCache())` preserves wrapper
preflight, one-second endpoint cache, original brief strings, exit remapping,
wrapper schemas and trajectory effects. It returns `LegacyCdpOutput` containing
`payload`, `exit_code`, `brief_line`, `json_depth`, and optional `trajectory`.
A host must execute that trajectory through its existing authorized logging route.

`LegacyCdpOutput.render(brief=True)` gives the original brief line. JSON rendering
requires an injected `json_formatter(payload, depth)`: retaining the shared host's
PS5-compatible formatter preserves depth truncation, property order, whitespace,
raw-helper serialization and Console behavior. No `json.dumps` imitation is
silently substituted. The shared formatter remains in the retained host; the
public CDP macro names now resolve to the shared adapter's fixed delegates.
The wrapper differential uses the same retained serializer on the
independently produced payload and compares exact Console strings as well as
native queries, trajectory payloads and exits.

## Behavior preserved

- Original page scores, reasons, first-eight evidence, page-match miss detection,
  title ordering and Framework's unstable ordering for equal page keys. Windows uses NLS `LCMapStringEx`
  invariant lowercase and `CompareStringEx`, matching the Framework runtime;
  non-Windows mock execution uses a documented portable fallback. Windows remains
  the release oracle for culture-sensitive cases.
- Full bridge plans, with helper-only locator hints and original advisory fallback
  order. Plans are data; they never execute fallback routes.
- Original rendered smart scoring: NFKC/letter-number normalization, exact/prefix/
  substring/weak-prefix scores, label/control association, role/onclick weighting,
  visibility, area bonuses/penalties, disabled penalties, ordering and stable DOM
  ties, selector/locator ranking and five candidate summaries.
- Four-hop shadow/same-origin iframe traversal, 1,200 raw/800 unique smart nodes,
  and deep-find's 25 accumulated matches/eight displayed matches.
- Selector clicks; type's clear/append/events and historical CR removal; smart
  typing's native setter/contenteditable behavior and synthetic Enter events.
  JS source is extracted into used `.js` functions; no PowerShell is evaluated.
- Native helper and wrapper schemas/exits, UTF-16 text lengths, and legacy quirks
  such as successful `cdp-type` trajectory kind `click` and deep-find's misleading
  `ok` brief prefix on helper failure. These quirks are characterized, not cleaned
  up unnoticed.
- Actual arrays remain arrays. Arbitrary `value`/`Count` objects remain objects;
  they are never opportunistically unwrapped into fabricated arrays.

## Explicit safety and corrected-behavior boundaries

1. Transport reuses the modern bounded framing implementation only. Startup is an
   explicit numeric-loopback HTTP origin; each selected socket must have the same
   canonical address/port and `/devtools/page/<discovered-id>` path. There are no
   redirects, proxies, DNS aliases, port scans, browser launches, debug-setting
   changes, browser-target sockets, or implicit attachment to other targets.
   Discovery still exposes original target metadata; selecting a worker/iframe
   is explicitly blocked rather than attaching outside the page boundary.
2. Arbitrary eval, selector/label input, clicks and ProseMirror input require
   immutable explicit live authority. Permission fields in operation args fail
   validation. Failures after live dispatch include
   `mutation_may_have_occurred: true`; there is no retry or fallback. Close cancels
   active sockets; cross-route invalidation prevents later stages from acting.
3. For legacy rendered reads only, fixed audited `smart_read.js` and
   `deep_read.js` execute with mandatory `throwOnSideEffect:true`,
   `awaitPromise:false`, and a bounded V8 timeout. User strings are JSON data
   arguments. `smart_read.js` hardcodes plan-only and has no mutation branch.
   Arbitrary user expressions never use this route. A page getter/proxy or a
   browser unable to prove side-effect freedom produces a partial result; the
   adapter never retries without the guard or switches to live mode. The modern
   `cdp.py` continues to make no evaluation calls on its read path.
4. Legacy deep-find passes the nonexistent `-PageWsUrl` name and reads
   `resp.result.result.value` although `_Cdp-WsCall` returns `resp.response`.
   ProseMirror has the same response-envelope error and historically reaches
   `selector_not_found` even with a real focus reply. New code intentionally fixes
   these defects. Pinned tests characterize the old failures separately; owned
   browser tests qualify the corrected success paths.
5. Corrected ProseMirror also verifies contenteditable state and actual focus
   before `Input.insertText`, stops after domain/focus transport loss, and checks
   the final reply. It preserves old before/after fields and helper's unchanged
   `partial` exit 0 (the wrapper remaps to 2). Browser postconditions still do not
   prove application persistence, and the fixture has a ProseMirror-class editor,
   not the full ProseMirror library.
6. All inserted selectors/text use JSON encoding. Legacy ad hoc quote/newline/
   backslash substitutions that could break or inject JS are intentionally fixed.
   Malformed or oversized discovery/protocol responses fail rather than becoming
   successful empty data. Arbitrary exception strings from the old .NET network
   stack are not reproduced by the Python transport.
7. Public matching now intentionally excludes form `value` attributes/properties
   and SCRIPT/STYLE/NOSCRIPT/TEMPLATE elements and descendants. This applies before
   scoring in smart read, live smart and deep read, so rejected text cannot enter
   `matched_text`, candidate summaries, locator strings, brief output or smart
   trajectory logs. The only value exception is the current rendered caption of a visible
   `input` whose type is `button`, `submit` or `reset`; password/hidden inputs,
   hidden captions, and ordinary filled-field values receive no such exception.
   A stale button value attribute is never used; a property-only current caption
   remains searchable. Descriptive labels and ordinary non-source page text remain readable. This is
   a source-based filter, not a promise to recognize arbitrary secrets deliberately
   displayed as labels or ordinary page text.

   TEXTAREA text is a form value too: its initial/default content can remain in
   `innerText`/`textContent` after the current `.value` changes. Direct extraction
   and ancestor reconstruction therefore skip its text subtree. The textarea
   itself remains an eligible labeled type target: its id, placeholder, descriptive
   metadata, external/wrapping labels and input behavior are retained. Neither
   `.value` nor `.defaultValue` is read as a matching signal. This closes the
   aggregate/default-value alias; it is not a blanket textarea candidate exclusion.

   Source-containing ancestors cannot use aggregate text getters: their text is
   rebuilt by a fixed, read-only walk that skips excluded subtrees. Unaffected
   elements retain their native text strings. The filtered walk preserves text
   order, rendered line/block separators and label association, with at most
   1,200 visited/queued entries; a budget overflow yields no aggregate text and
   never falls back to raw source. More than 128 ancestry links are excluded.
   Mandatory `throwOnSideEffect`, `awaitPromise:false`, timeout, endpoint and
   authority checks are unchanged. New DOM getters require the owned-browser gate.

   Matching solely on a stored value or source text now gives no candidate; mixed
   matches can change scores, ordering, counts and selected targets. These are
   explicit privacy corrections, separate from unchanged ordinary parity. The
   old deep JS also collected these values, but its original broken envelope hid
   the result; correcting the envelope made that exposure publicly reachable.
   Normal parsed `template.content` was never traversed and remains untraversed.
   TEMPLATE fixtures with source text model ordinary DOM children, which can be
   attached programmatically and are now excluded along with that entire subtree.

## Retained host architecture and shared references

Both hosts derive `$Script:LegacyCdpSourceRoot` from their trusted script location
and load the one shared adapter. `Invoke-NativeHelper` validates the leading
`-Action` pair and intercepts every `cdp-` prefix before the old helper lookup,
server, cache or untyped child path. The closed Python parser receives all argv
as data, while live authority comes separately from the outer startup state.
Standalone native-helper calls use the typed optional `[hashtable]$CdpStartup`
with one actual boolean `allow_live_control` value. Public wrapper and daemon
calls use the direct interceptor. See the
[host contract](legacy-cdp-adapter-draft.md) for startup, process bounds and exact
production-route tests.

`Test-CdpPortQuick` remains for SmartPlan, HealthDetail and execution acquisition,
including CDP stage zero. The audit found no references to the old `_Cdp-*`
helpers or `_Js-StringLiteral` outside the migrated native CDP family; those old
implementations are removed with the action bodies. Shared delegates preserve
the ten public macro and ten native action names. The modern `cdp.py` contract
is unchanged. The retained adapter, shared serializer and host initialization
are still PowerShell and count in the source inventory.

## Validation and retirement gates

```text
python -m unittest discover -s tests/python -p "test_legacy_cdp*.py" -v
CUCP_LEGACY_CDP_BROWSER_TEST=1 CUCP_CHROME_TEST=1 python -m unittest discover -s tests/python -p "test_legacy_cdp_browser*.py" -v
```

- Portable captured-socket tests cover exact envelopes, immutable authority,
  redirects/endpoint escapes, guarded reads, exceptions, base64/Unicode quoting,
  cancellation, uncertain delivery, true arrays, ProseMirror focus and no retry.
- A Node-only test harness runs 22 original and migrated DOM algorithms against
  identical owned DOM/layout/event fixtures, comparing complete results and
  effects. This is test-only; production needs no Node interpreter.
- A separate privacy suite characterizes 32 original JS exposures and checks the
  corrected public payload, full/partial result, brief and trajectory boundaries.
  It preserves visible button captions and ordinary labels, exercises traversal
  overflow without fallback, and distinguishes inert template content from
  ordinary TEMPLATE children. Existing ordinary parity assertions are unchanged.
  Eleven additional textarea cases distinguish default/current values and ancestor
  text, while exact labeled textarea read/type fixtures preserve legitimate use.
- Windows PS5 tests extract exact functions from pinned tree
  `bf895d3120dd5e145f360cb1c41e1d79a061d048`, stub only external acquisition, and
  compare helper outputs/exits, ranking and plans. Wrapper cases compare native
  argv, trajectory effects, exit remapping, and both JSON/brief Console output.
  Original deep/ProseMirror defects and click's PS5 `(if ...)` command error on
  the partial branch are asserted separately from their corrected behavior.
- Five opt-in actual Chrome tests reuse the existing owned fresh-profile fixture:
  rendered smart/label ranking, shadow/frame traversal, getter/proxy side-effect
  rejection, live Unicode input/events, trusted editor insertion and failed focus.
  No account, remote page, existing browser profile or desktop is touched.
  One additional bounded diagnostic test records each fixed read primitive's
  guarded acceptance/rejection, including complete smart and deep algorithms;
  it does not relax or replace any of the five behavior assertions. The seventh
  browser test compares 52 CSS identifier strings with the native fixture oracle.
  Four additional privacy tests cover full read/live outputs and prove that
  protected-value and affected ancestor aggregate getters are not invoked. The
  textarea case checks external/wrapping labels, real input, retained private
  defaults and untouched value/default/aggregate getters. The diagnostic test also
  records the new guarded parent/child/text-node getters.

Local 2026-10-02: mock and Node fixture checks passed; Windows tests are explicitly
skipped off Windows. All five enabled browser attempts failed at Chrome startup:
`process_singleton_posix.cc: socket() failed: Operation not permitted`.
No browser assertions ran locally. No sandbox bypass was attempted. Passing
ordinary guarded read tests in sandbox-capable CI remains required. The successful
CI results below establish that qualification without bypassing the local sandbox.

Exact commit `120b64a605bece965da4637e6510afcbd46fe871`, Actions run
`36997186053`, established that all three live-input/getter-protection browser
cases pass, while the rendered and shadow/frame cases fail at guarded smart
evaluation with `EvalError: Possible side-effect in debug-evaluate`. Deep was not
reached by the latter case. Windows also exposed host framing/output defects,
detect's ignored page-match option, unstable equal-page sorting, and the original
click partial-branch command error. Those failures blocked promotion until the
repairs passed the later exact-commit qualification below.

The next exact commit `a7bffa18b8325fe06f00459324c1f3631f2c896a`, run
`37000162419`, passed Windows CDP qualification: 49 tests, 42 passed and seven
explicit browser/production-promotion skips. The browser job still failed the
same two smart-read cases. Its fixed probes show that native `CSS.escape('save')`
alone is rejected, while the complete deep-read algorithm and local scoring
primitives are accepted. Probes using `getElementById` shared that separate
acquisition call, so they do not establish which subsequent getter was rejected.

The narrowly scoped repair replaces `smart_read.js`'s CSS identifier escaping
with fixed pure [CSSOM serialization](https://drafts.csswg.org/cssom/#serialize-an-identifier).
It retains `throwOnSideEffect`, accepts no page-supplied source, and does not call
page replacements for `CSS.escape`. Production live smart behavior is unchanged.
Fifty-two string cases cover empty/leading digits, hyphens, all ASCII controls,
NUL, quotes/backslashes, BMP, supplementary Unicode and isolated surrogates.
The exact production function passes guarded V8 Node evaluation against explicit
expected strings; an owned-browser fixture compares it with native `CSS.escape`
using explicit fixture-only live authority. That browser gate and the original
five functional tests passed at exact commit
`f2333bebd53e28e59a05795abfeb90275dc67d09`, run `37002020097`: seven browser
tests passed, including the diagnostic and 52-string native oracle. The Windows
job passed 43 tests with eight explicit skips. Run `37005163979` at
`ad8790be0301b5e77ca87d841718bf0fac8fb1e9` repeated both green results.

The final pre-cutover candidate was
`e9e015c6bc7b39d52999dccccf6bb4316a6c8dfe`,
[run 37007340738](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738).
Windows CDP again passed 43 of 51 tests with eight explicit skips; the owned
browser passed all seven tests. All focused jobs were green, while the
full-regression job was skipped. This is candidate qualification evidence.
It predates the public-text privacy correction described above. That correction
requires new exact-commit browser/Windows qualification; earlier green results
do not qualify the added traversal or sensitive-output boundary.

Production integration now has a leading `-Action` pair precondition on the central
native route. Its case-insensitive CDP prefix intercept sends the complete argv
to the closed parser with separate outer startup authority, before the old helper
lookup. Production adapter tests assert malformed-prefix rejection and unknown
CDP parser failure without old-route fallback, alongside unchanged exact macro
comparisons. These promoted-host tests, the bundled full regression and Windows
bundle validation are the next required gates. Source removal has occurred
locally; candidate browser and Windows results alone do not establish that the
integrated host or portable release is qualified.

Setuptools package data includes `legacy_cdp_assets/*.js`; the PyInstaller build
collects that data and the bridge imports. `CUCP.exe legacy-cdp-bridge` and
`python -m pcucp_cli legacy-cdp-bridge` share the same fixed bridge implementation.
The Windows bundle smoke gate must validate the packaged assets and startup
refusal without a runtime on PATH. Portable legacy-macro support remains
unqualified until the applicable bundle and retained-host checks pass.
