# Optional CDP adapter: migration and safety contract

`pcucp-next/python/pcucp_cli/cdp.py` provides a standard-library-only adapter for
an **already running, explicitly authorized** Chromium/Electron debug endpoint.
It does not launch a browser, scan ports, enable remote debugging, change browser
settings, configure persistent access, or connect to a model/account provider.
Construction validates configuration and does not make a network connection.

The legacy `scripts/cucp-native-helper.ps1` implementations remain intact. This is
an independently tested migration slice, not proof of browser compatibility or
full parity with every app-specific PowerShell macro.

## Host integration API

```python
from pcucp_cli.cdp import CdpAdapter, CdpError

# Supplied by the human at host startup, never by model-controlled tool arguments.
cdp = CdpAdapter("http://127.0.0.1:9222", allow_live_control=False,
                 timeout_s=5, snapshot_ttl_s=15)
targets = cdp.execute("cdp-detect", {})
observation = cdp.execute("cdp-observe", {"target_id": "exact-discovered-id"})
result = cdp.execute("cdp-smart-find", {
    "snapshot_id": observation["snapshot_id"], "text": "Save", "limit": 10,
})
# Close alongside the host session. No debug-port settings are changed.
cdp.close()
```

`execute(command, args, timeout_s=None)` returns a plain dictionary with `status` and evidence.
`CdpError` exposes `code`, `status`, and `mutation_may_have_occurred`.
The host must preserve these distinctions in its own response envelope.
`not_found` is a successful read with zero candidates; `partial` is incomplete
or ambiguous evidence, not permission to choose an arbitrary first result.

Supported commands and exact argument names:

| Command | Arguments |
| --- | --- |
| `cdp-detect` | No arguments |
| `cdp-observe` | `target_id`; optional `max_depth` 1–24, `max_nodes` 1–2000 |
| `cdp-query` | `snapshot_id`, CSS `selector`; optional `limit` 1–100 |
| `cdp-smart-find`, `cdp-deep-find` | `snapshot_id`, `text`; optional `action` (`click` or `type`), `limit` |
| `cdp-smart-type-find` | `snapshot_id`, `text`; optional `limit` |
| `cdp-click`, `cdp-smart-click` | `snapshot_id`, exact `element_ref` |
| `cdp-type`, `cdp-smart-type` | `snapshot_id`, `element_ref`; `text`, `clear`, and/or `press_enter` |
| `cdp-prosemirror-insert` | `snapshot_id`, `element_ref`, nonempty `text`; optional `clear`, `press_enter` |
| `cdp-eval` | `snapshot_id`, JavaScript `expression` |

Unknown and missing arguments fail validation. Typing text is limited to 16,384
characters, arbitrary evaluation to 32,768 characters, selectors to 2,048, and
search labels to 1,024. The startup live setting has no request-time setter. The optional per-call
`timeout_s` is a finite positive remaining-time cap: the effective deadline is
the lesser of this duration and the startup timeout, including time waiting for
a concurrent operation's execution slot. It never changes endpoint or permission.

`invalidate_snapshot()` clears browser references without closing the adapter.
Hosts should call it before native GUI mutations, and invalidate native GUI
observation tokens before CDP mutations. A generation check also prevents an
already-running CDP preflight from proceeding to mutation after cross-route
invalidation.

`close()` is terminal and does not wait for the execution lock. It immediately
sets a cancellation event, clears references, and shuts down registered sockets
to interrupt blocked reads. Every request/frame send and post-preflight boundary
checks cancellation. No subsequent action phase is allowed after close; an
already-sent mutation is reported with `mutation_may_have_occurred: true`.
Cancellation cannot roll back JavaScript or input already delivered to a browser.

## Transport boundary

- Startup accepts only an explicit `http://` origin with a numeric loopback IPv4
  address or IPv6 `::1` and an explicit port. DNS names, IPv4 shorthand, mapped
  IPv6 addresses, zones, credentials, non-root paths, query strings and fragments
  are rejected. HTTPS/TLS is not implemented by this adapter.
- Discovery requests only `/json/version` and `/json/list` on that exact origin.
  There is no port scan, default-port probing, proxy support or redirect follow.
- Only `page` and `webview` targets are exposed. Every page WebSocket URL must use
  `ws://` with the same canonical numeric address, same port, and the exact
  `/devtools/page/<discovered-id>` path. Browser-wide WebSockets, other ports,
  DNS hosts, redirects, credentials and query strings are rejected.
- HTTP responses are bounded to 4 MiB, headers to 16 KiB and 100 fields. Bounded
  Content-Length, close-delimited, and chunked responses are supported. Compressed
  HTTP bodies, ambiguous framing, trailers and duplicate headers are rejected.
- WebSocket upgrade validates `Sec-WebSocket-Accept`; no extension or subprotocol
  is requested or accepted. Client frames are masked. Server masking, compression,
  reserved bits, invalid lengths, binary data and invalid fragments are rejected.
  Text fragmentation and ping/pong are supported. Message IDs are correlated.
- Each operation has one absolute network deadline, not a timeout reset for each
  byte. Each WebSocket message is at most 4 MiB; connection-wide receive limits
  are 16 MiB, 2,048 frames and 100 unrelated messages per call. Invalid UTF-8,
  duplicate JSON fields, non-finite numbers and excessively nested JSON fail.

Loopback is a network boundary, not authentication or a sandbox. Other local
processes able to access the debug port can potentially control the browser.
The human must trust the existing endpoint. Configuring the endpoint does not
bind it to only one web origin; pages may themselves display remote content.
The adapter's origin restriction applies to its HTTP/WebSocket connections.

## Read-only observation and grounding

The read path uses only `DOM.getDocument`, `DOM.describeNode`, and
`DOM.querySelectorAll`; there is no arbitrary protocol forwarding and no
`Runtime.evaluate` or page JavaScript on this path. `DOM.resolveNode` is used to
resolve an already checked element for a live action.

A bounded pierced DOM tree supplies text and attributes, including shadow roots
and frame documents actually returned by that page endpoint. Unavailable frame
documents are counted and reported incomplete; the adapter never attaches to
another target or out-of-process frame automatically. CSS query scope is the
main document and does not automatically cross shadow/frame roots. Text/deep
search can inspect the observed nested tree.

Smart matching retains the legacy normalization, exact/prefix/substring scores,
role weighting, associated `<label for=...>` text, and ranked selector hints.
Only inspected attributes and text are used; input `value` is not included in
public observation metadata. SCRIPT, STYLE, NOSCRIPT and TEMPLATE subtrees are
excluded from public text aggregation at every ancestor (including BODY), and
receive no public/actionable element references. Raw source may remain only in
internal semantic fingerprints for change detection. A source-only CSS match
is reported as unobserved rather than exposed as an action target. Password/file/hidden fields are not typing
candidates. Arbitrary browser strings remain untrusted content.

The pure DOM protocol snapshot does not establish rendered visibility or style,
so results explicitly say `visibility: unverified`. Legacy JavaScript's computed
style, rendered geometry/area bonuses, `el.labels`, inherited contenteditable
state and onclick-property scoring are not claimed as migrated. Real visibility,
disabled/read-only/sensitive-field checks occur in the fixed live function before
its action. This distinction avoids hiding page JavaScript in a read-only tool.

Multiple close-scoring candidates remain ambiguous even at `limit=1`. Queries
never call a matching element automatically. The host must present/choose an
exact observed `element_ref` using its normal permission rules. Smart mutation
names are aliases for exact-reference mutation, not “pick first and click.”

## Freshness and mutation semantics

The adapter retains one bounded snapshot. A new observation replaces it, and its
opaque element references belong to that snapshot only. The default TTL is 15
seconds (configurable at startup, at most 60 seconds). Unknown/expired references
are blocked. Exact target id, target URL, target type, WebSocket path, document
backend identity, and document URL are checked again against the live endpoint.
Before element mutation, a bounded semantic subtree fingerprint checks backend
identity, tag/type, attributes, text, frame identity and observed descendants.
An element with an incompletely observed subtree cannot be mutated; observe it
with greater depth first.

Live mode is required at startup for **all** evaluation, clicks, typing,
ProseMirror insertion and keyboard dispatch. Even `document.title` supplied to
`cdp-eval` is classified as arbitrary evaluation. There is no expression heuristic
that claims JavaScript is safe to evaluate read-only. Arbitrary live evaluation
can execute page code, trigger network requests and have significant side effects;
the host still owns approval of each requested operation and information sharing.

Once live dispatch begins, all observation references are consumed. A lost reply
or exception after sending a mutation sets `mutation_may_have_occurred`; it never
causes an automatic retry or another control route. The host must not retry the
same user action merely because no success response arrived.

- Click invokes `.click()` on the resolved exact DOM object after checks
- Input/textarea typing uses the native value setter and `input`/`change` events,
  preserving legacy append/clear behavior. Optional Enter is synthetic page events
- Contenteditable/ProseMirror insertion validates and focuses the exact editor,
  sets its selection, checks focus, and calls browser CDP `Input.insertText` once
  (plus optional Enter key down/up). It does not replace rich text via textContent
- User text is serialized as CDP function arguments, never interpolated into JS
- Password, file and hidden inputs are blocked by the built-in element functions

CDP focus checks and insertion are separate protocol operations. They cannot make
application focus changes atomic; the human/host must still verify the result.
The adapter does not emit editor contents, input text, or before/after field values
in successful mutation reports. A successful report means protocol dispatch, not
proof that an application saved, sent, or accepted the content. It asks for a new
observation. App-specific postconditions remain the host's responsibility.

## Legacy mapping and deliberately retained gaps

| Legacy entry points | New implementation / gap |
| --- | --- |
| `_Cdp-HttpGet`, `_Cdp-WsCall` | Bounded loopback-only HTTP and masked WebSocket transport |
| `_Cdp-PortOpen`, `_Cdp-Detect`, `_Action-CdpDetect` | Explicit-origin discovery only; no scanning or automatic enablement |
| `_Cdp-ScorePages`, `_Cdp-FindPage` | Discovery returns all eligible targets; explicit target id replaces score-based first-page selection |
| `_Cdp-NewDomBridgePlan` | Selector suggestions retained as data; no implicit CDP→UIA→OCR→model fallback |
| `_Action-CdpEval` | Startup-gated arbitrary evaluation; no base64 command alias needed in structured JSON |
| `_Action-CdpClick`, `_Action-CdpType` | Observe/query, choose exact reference, validate, then gated mutation |
| `_Cdp-RunSmartDomAction`, smart-find/type-find/click/type | Read-only deterministic label scoring plus explicit-reference actions; computed-style ranking/automatic candidate actuation excluded |
| `_Action-CdpDeepFind` | Pierced protocol DOM traversal and unavailable-frame reporting; no cross-target/OOPIF attachment |
| `_Action-CdpProseMirrorInsert` | Exact editor selection/focus plus Input.insertText; dispatch metadata only, no unverified before/after success assertion |

Full CDP protocol parity, arbitrary selector queries across every shadow root,
out-of-process frames, all browser versions, every editor's event contract,
transactional focus guarantees and application-specific browser regression testing remain open.
Existing PowerShell functions must not be removed solely because mock tests pass.

## Verification

```text
python -m unittest discover -s tests/python -p test_cdp.py -v
```

The tests create ephemeral local mock HTTP/WebSocket servers only. They cover
startup validation/no constructor connection; redirect/host/port/path escapes;
masked clients, fragmented responses, ping/pong and correlated IDs; malformed and
oversized responses; deadlines; no read-only eval/input; ambiguity; label/shadow
fixtures; stale/replaced references; target/document/subtree changes; exact-object
mutations; quote-safe Unicode text; ProseMirror routing; uncertain mutation replies
and no retry. Multithreaded tests also cancel blocked DOM preflight before any
live send, cancel an already-sent ProseMirror focus before text insertion, exercise
cross-route invalidation, cap time waiting for execution, and ensure API-key-like
script/style/template fixture text cannot leak through ancestor aggregation or
search results while normal visible text remains available. These are transport/contract tests, not actual browser/editor tests.
No model account, browser profile, debug-port setting or persistent access was used.

Protocol references: [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)
and [RFC 6455 WebSocket protocol](https://www.rfc-editor.org/rfc/rfc6455).

### Opt-in ephemeral Chrome fixture verification

```sh
CUCP_CHROME_TEST=1 python -m unittest discover -s tests/python -p test_cdp_browser.py -v
```

Without exactly `CUCP_CHROME_TEST=1`, all seven browser tests are explicitly
skipped and no browser is launched. With the flag set, a missing browser or failed
startup is an error rather than a successful skip. The runner must provide:

- Python's standard library and a preinstalled official Chrome/Chromium on PATH,
  named `google-chrome`, `google-chrome-stable`, `chromium`, or `chromium-browser`
- A non-root execution account, a working browser sandbox, and permission to
  create the browser's normal subprocesses and AF_UNIX sockets; a headless Linux
  CI runner needs the sandbox's usual namespace/setuid support
- Writable temporary storage and permission for loopback HTTP/WebSocket listeners

The suite never installs a browser, accepts an arbitrary executable/endpoint,
or supplies `--no-sandbox`. Each test starts its own process with a new temporary
profile, HOME, XDG config/data/cache directories and TMPDIR. Chrome chooses a
random debug port using `--remote-debugging-port=0`; only that profile's newly
written `DevToolsActivePort` file supplies the endpoint. The listener address is
explicitly `127.0.0.1`, and the fixture HTTP server binds another ephemeral
loopback port. Nothing attaches to an existing browser or desktop.

Only generated local HTML is opened. It contains no external URLs, credentials,
account flows or dependencies. A restrictive fixture CSP blocks network access
from its scripts; browser background networking, extensions, sync, component
updates and proxies are disabled for this process, and non-loopback DNS is
disabled by its host-resolver rule. Teardown terminates only the exact Popen child
it created, closes the local server and adapters, and removes the temporary
directories. It never searches for or kills other browser processes.

The seven tests check actual protocol DOM observation/query, associated-label and
ambiguous matching, source-only text exclusion, one exact button click with a
consumed snapshot, Unicode native input clear/append with input/change events,
trusted browser `Input.insertText` in contenteditable elements, stale snapshot
and cross-snapshot references, a real element attribute change before mutation,
and read-only operations that leave the fixture unchanged and never dispatch
Runtime/Input protocol methods. Fixture output nodes provide postcondition
evidence rather than assuming a successful dispatch implies an edit.

The contenteditable fixture includes a `ProseMirror` class but does **not** load
the ProseMirror library. Passing it establishes browser editing/selection and
event behavior, not parity with that library's schema/plugins or any real app.
The suite is separate from the mock transport tests above and does not replace
app-specific compatibility testing.

Local validation on 2026-10-01 found preinstalled Chromium 151.0.7922.173, but the
restricted execution environment rejected Chrome's process-singleton socket
creation (`socket() failed: Operation not permitted`) before CDP became ready.
The enabled suite therefore failed at setup; no browser assertions ran locally.
The default invocation verified all seven explicit skips. A sandbox-capable CI
runner is required for a genuine browser pass; no sandbox bypass was attempted.


## Engine, MCP and JSONL integration

The same twelve `cdp-*` commands are exposed in the shared 52-tool schema. The optional adapter is off unless a human supplies `--cdp-endpoint` when starting `mcp`, `serve`, or a file-based workflow/task run. Tool arguments cannot set/change the endpoint or live mode. `capabilities.data.cdp` reports whether it is configured. Missing configuration returns `cdp_not_configured` before network work.

Browser mutations clear any prior native-window observation; native mutations invalidate the current browser snapshot. Session cancellation closes both native and browser transports. Each workflow's remaining time caps the CDP operation. An uncertain browser mutation becomes a `partial` response with `may_have_acted:true`; no fallback or retry occurs. Read-only discovery and a referenced browser workflow are covered through the actual engine and both host adapters with local mock sockets.
