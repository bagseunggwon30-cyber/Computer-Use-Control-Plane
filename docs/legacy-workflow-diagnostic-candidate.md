# Workflow parse-error precedence candidate

This is inert qualification work. `LegacyWorkflowParseErrorPreflight.cs` and its
managed fixture checks belong only to `PcuCp.LegacyWorkflow.ContractTests`.
`LegacyWorkflowLiteralParser.cs` remains excluded from NativeHost, and the pinned
private PowerShell helper and production parser path are unchanged.

## What this candidate establishes

The pinned `_Parse-WorkflowStepTokens` first collects **all** PSParser errors. Only
when there are none does it return the first unsupported token type. Returning on
an unsupported argument before examining later syntax gives the wrong error code.

The bounded preflight detects missing/mismatched parentheses and scriptblock
braces, unfinished strings/here-strings/block comments, PS5-invalid `&&`/`||`,
reserved input redirection, and bare statement productions missing required
syntax. It calls the embedded-string candidate scanner to classify the qualified
variable/subexpression subset. Comments, quoted literal data, escapes, and
stop-parsing payloads remain opaque as appropriate. The stop-parsing scanner
preserves double/smart-double quote state for unquoted pipeline/chain boundaries.
Those additional stop-parsing combinations are source-inferred from the
[PowerShell reference tokenizer](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/parser/tokenizer.cs),
not relabeled as observed PS5.1 results.

A classified syntax failure is `parse_error` with no tokens. The explicit
unqualified NUL/stop-parsing boundary instead returns `unsupported_token`, also
with no tokens, so the preflight repair independently remains fail closed.
A null result means
**no error was established**, not general PowerShell syntax validity. The ordinary
candidate still decides token acceptance, with no acceptance expansion from this
helper. An unsupported embedded construct or more than 128 open groups aborts the
bounded scan without claiming validity. The embedded scanner has its own nesting
bound. The overall candidate input-length bound still applies first.

## Evidence boundaries

`legacy-workflow-diagnostic-candidate.json` contains nine normalized top-level
PS5.1 observations from run `37074340659`, commit
`48bb1651499d0857b4886b3f5cd8b2ed04d5e8a0`, log line 223, plus 58 explicitly inferred
precedence/opaque-region contracts. The original log SHA256 is
`d7090be7d8bcb52fd4d2a2b156f862c40a5dc66a66a507374916ca009dabb53e`.
Six of those inferred probes contain a physical NUL adjacent to marker-like
text. Five use actual generic stop-parsing markers and remain explicitly
unsupported, with matching preflight and ordinary-scanner guards. The leading
quoted variant does not activate stop parsing; its later unterminated string is
now an inferred parse error. All six remain capture-only for the unknown exact
Windows result, while still asserting candidate rejection.

Run `37079778520` confirmed that leading single/double-quoted `--%` strings do not
activate stop parsing, while backtick-cooked generic markers do. Preflight now
uses that same distinction. The existing malformed quoted-marker fixture and
seven additional quoted/raw/escaped neighbors remain explicitly inferred; their
exact payloads are not relabeled as observations. No historical oracle row or
existing observed assertion is changed. The existing
`stop_quoted_marker_adjacent_nul` candidate now returns the exact recorded
`["macro", "windows", "--%", "\0raw"]` tokens; its expectation explicitly links
back to the unchanged `37079778520` observation rather than relying on inferred
acceptance.

Thirty observed malformed embedded cases are covered by the separately developed
embedded-string scanner and its observed replay fixture.

The historical comparison stripped `detail` and `message`. Consequently it cannot
establish diagnostic wording, error ordering, localization, or plan-message
parity. Native candidate explanation strings are **not observed PS5.1 text**.
Full grammar, all token categories, adversarial combinations, and exact diagnostic
strings remain unqualified until the corresponding Windows checks pass.

## Raw, read-only Windows capture

Run `python -m unittest discover -s tests/python -p test_legacy_workflow_diagnostics.py -v`
on Windows with .NET and Windows PowerShell 5.1 available. The test:

- Reads `scripts/cucp.ps1` from immutable baseline
  `bf895d3120dd5e145f360cb1c41e1d79a061d048`; verifies its serialized SHA256.
- Imports only the six pinned pure workflow/safety definitions via AST extents.
- Tokenizes at most 128 bounded input strings; never invokes any fixture text,
  workflow step, original entry point, or planned command.
- Captures raw parser details, individual diagnostic messages and token extents,
  first unsupported token type, full original plans, and full candidate output.
- Records engine version/edition, CLR/OS version, current/UI culture, UTC capture
  time, immutable source identity, and each imported helper's SHA256.
- Separately checks inferred error-code/opaque-region contracts against PS5.1 and
  never normalizes raw diagnostic comparisons.

The bounded JSON capture is printed. Set `CUCP_WORKFLOW_DIAGNOSTIC_CAPTURE` to a
local output file to retain it as an ordinary artifact. No artifact is published
or committed automatically. The test reports remaining exact-diagnostic gaps.
Either `CUCP_REQUIRE_WORKFLOW_PARSER_PARITY=1` or
`CUCP_REQUIRE_WORKFLOW_DIAGNOSTIC_PARITY=1` makes **any** raw result/plan difference
fail qualification, even if normalized token/error comparisons are equal.
The focused foundation runner includes this suite and retains the raw capture
with its ordinary qualification artifacts. A focused success does not imply the
strict full-parity flags passed.

The driver is stored explicitly at
`tests/fixtures/legacy-workflow-diagnostics-oracle.ps1` and copied byte-for-byte
into its owned temporary directory. Its PowerShell source is counted in the
migration inventory and must also be retired before the zero-execution gate.
