# Bounded mode-aware embedded string validation

This candidate-only batch is based on real Windows PS5.1 run
[37079778520](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37079778520),
commit `0e6e6748f475ee1526b82f3751f11da8ba42e64a`. It changes no native
production inclusion, dispatch, or input execution. Every input remains inert.

## Immutable evidence and accounting

`tests/fixtures/legacy-workflow-ps51-mode-observed-37079778520.json` preserves all
94 original literal-gap rows, including their exact before/after values. The
fixture records the source log, SHA-256
`1c43ee04c706b02e83d7c4363c80a06c22fdb1f37945f0220ee1d5353da1a61c`, line 273,
tested commit and baseline tree. Python checks pin a normalized hash of all rows.

The batch resolves 72 rows exactly: 24 valid spellings and 48 parse-error codes.
The managed harness enforces exact recovery for those IDs and non-relaxation for
all 94 rows. The remaining 22 are checked as explicit rejected gaps:

- 2 invalid numeric increment expressions still report unsupported_token
- 2 large numeric spellings and 2 over-limit nesting spellings remain bounded out
- 2 statement bodies, 2 pipelines and 2 multi-statement bodies remain unsupported
- 2 escaped braced variable names remain unsupported
- 4 physical-NUL quoted forms remain unsupported
- 4 static-member forms remain unsupported

This accounting is historical replay, not fresh Windows qualification. Earlier
observed fixtures remain unchanged. The existing candidate fixture has exactly
72 updated expectations and adds 54 separate `modes_batch_` inferred neighbors.
Those new neighbors go through the existing Windows non-relaxation suite; none
is labeled as a Windows observation.

## Bounded two-pass implementation

The outer string scanner and embedded expression grammar have separate roles:

1. Scan the original source with raw parenthesis depth, including parentheses in
   quoted text. Keep the existing 64-level bound.
2. For ordinary expandable strings, collapse a backtick/double-quote immediately
   followed by a double-quote. Here-strings preserve the pair.
3. Validate the resulting body with the existing bounded inert grammar. Require
   complete consumption. Never evaluate values or dispatch commands.
4. Append the original source slice to the outer token, including all original
   quotes, backticks, spacing and variable spelling.

This is the mechanism in the official
[early PowerShell tokenizer](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/parser/tokenizer.cs),
`ScanSubExpression`, now backed by both-context PS5.1 observations. It replaces
blanket quote-adjacency rejection; it does not remove syntax validation.

`DollarScanContext` distinguishes ordinary expandable strings, here-strings and
an expression that has already passed through outer extraction. An actual quoted
string inside a parsed body starts its own ordinary-string context. This avoids
both repeated transformation of expression bodies and accidental propagation of
here-string mode through nested ordinary strings.

Special variables `$$`, `$?` and `$^` terminate after one character. Expression
adjacency is diagnosed separately from ordinary string suffix text. A missing
static member expression is a parse error; other static-member forms remain
explicit grammar debt. Bounded command arguments scan all joined bare/variable/
quoted fragments so an unclosed quote cannot hide behind an unsupported boundary.

## Scope and verification

The nullable `ReadDollarText` result API remains intact, with an optional context
argument. The here-string caller and two diagnostic-preflight context hooks are
updated. The outer main token-emission loop is unchanged.

Local managed validation passes 1,216 checks, including 100/100 earlier embedded
observations, 72/94 new observations and 442 candidate literal contracts. These
checks do not replace Windows execution of the pinned parser oracle. Production
NativeHost still excludes the candidate lexer and its diagnostic preflight.

Isolated-worktree Python discovery ran 533 tests: 377 passed and 156 were
platform skips. The final integrated, SDK-enabled checkpoint is recorded in the
migration checkpoint report. A seeded
8,192-case inert mutation pass found no exceptions or invalid result shapes;
this robustness check is not a parser-equivalence or Windows-parity claim.
