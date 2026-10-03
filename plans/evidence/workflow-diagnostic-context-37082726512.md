# Observed workflow diagnostic-context correction

## Immutable evidence

- [Windows run 37082726512](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37082726512)
  tested `9f6a2038e21bc90c0dcb9a3dcce7053af1bbb60c`.
- The complete 101-case capture is stored byte-for-byte as
  `tests/fixtures/legacy-workflow-ps51-raw-diagnostics-37082726512.json`.
- SHA256: `6c5602b3839565d43b34bcd1111c09f063b8d86d2e08f6c8082fd04b7976b97c`.
- Verified artifact ZIP SHA256:
  `38bc0f865489c573fea0c3b664fd8378fab4417108cf8db3b0fe8c74ab491a77`.
- Captured engine: Windows PowerShell `5.1.26100.33438`, Desktop edition,
  `en-US` current/UI culture. Original source and six helper hashes are retained
  inside the unchanged capture. `comparison_completed` is true.

The historical candidate results, raw parsed results, individual error messages,
first unsupported token types, and complete original plans are all preserved.
No concatenated earlier capture has been treated as individual observations.
A path-specific `-text` Git attribute preserves the captured terminal CRLF and
prevents checkout line-ending normalization from changing its SHA256. A
path-specific `cr-at-eol` whitespace rule permits that original terminal CR in
diff checks. Tests verify both worktree and Git-index blob hashes against the
original artifact hash; no canonicalized structure hash substitutes for it.

## Bounded rules corrected

1. In the pinned PSParser.Tokenize observation, block comments close at the
   first `#>`. A second `<#` inside a comment is
   ordinary comment text. The observed nested-looking comment therefore exposes
   its later unmatched `)` and yields `parse_error`.
2. Named-block keywords (`begin`, `process`, `end`, `dynamicparam`) are distinct
   from ordinary statement keywords. The incomplete-named-block check is bounded
   to the initial qualified script-head context. After an ordinary statement,
   `process` may be a command name. `macro windows; process` remains rejected for
   its unsupported `StatementSeparator`, not a fabricated parse error.
3. Parenthesized pipelines are expression contexts. A bare `if` within one is
   not classified as an incomplete if-statement. `macro windows (if)` remains
   rejected for its unsupported `GroupStart`.

The context distinction is also supported by the official language specification:
[grouping parentheses contain a pipeline](https://learn.microsoft.com/en-us/powershell/scripting/lang-spec/chapter-07#711-grouping-parentheses),
while [script-block bodies choose named blocks or a statement list](https://learn.microsoft.com/en-us/powershell/scripting/lang-spec/chapter-15#b22-statements).
The specification is supporting grammar context; the three pinned PS5.1 outputs
are the version-specific observations.

These changes are rejection-only. The preflight still cannot return tokens or
accept a construct. More elaborate named-block/scriptblock context remains
unqualified. No per-input or fixture-ID exception is used in the classifier.

## Replay and qualification

`legacy-workflow-diagnostic-repair-37082726512.json` identifies the exact three
repair targets and 23 separately labeled inferred adversarial neighbors.
The three formerly inferred predictions now carry observed provenance.
The original raw capture is never rewritten.

Managed checks require exact `ok`/error-code/token equality for all three targets,
and exact original-plan preservation when the captured parsed result is passed
through the retained parsed-plan assembly path. This does not claim that the
candidate synthesizes the original localized diagnostic wording.

Local verification:

- .NET build: zero warnings/errors; 1,372 managed checks passed.
- Focused workflow Python suite: 34 passed, 12 Windows-only skips.
- Full Python suite: 390 passed, 160 platform-gated skips; no failures.
- All 101 captured cases replayed against the current candidate: exactly the
  three requested normalized results changed; zero new accepted cases.
- Current managed replay has 8 normalized differences and 84 exact differences.
  This is historical replay, not a new Windows qualification run.

The immutable historical capture has 84 exact parsed/plan differences: 73 are
text-only after dropping `detail`/`message`, and 11 also differ after that
normalization. These categories overlap other literal/boundary corpora; they
must not be added to those gap totals. Exact diagnostic wording, the remaining
normalized differences, and the new inferred neighbors still block full parity.

The next raw capture appends the 23 neighbors to the original 101 inputs,
producing 124 records within the existing 128-case bound. Original case IDs,
steps, ordering, and the checked-in historical capture remain unchanged; fresh
neighbor results retain complete version/culture/source provenance even after
an assertion failure. Fresh Windows tests continue to require the three
observed code/token results and all 23 inferred neighbor rejection results to
match the pinned PS5.1 oracle.
No production parser, NativeHost inclusion, original helper, or CI configuration
is changed by this repair.
