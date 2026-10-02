# Qualification-only embedded string scanner

This batch changes the managed candidate only. `LegacyWorkflowLiteralParser.cs`
remains excluded from NativeHost, and the PowerShell parser oracle is retained.
Nothing in this batch executes, expands, interpolates, or evaluates input text.

## Evidence

The replay fixture `tests/fixtures/legacy-workflow-ps51-embedded-observed-37074340659.json`
contains all 100 exact inferred-gap rows from Windows run
[37074340659](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37074340659),
commit `48bb1651499d0857b4886b3f5cd8b2ed04d5e8a0`. The fixture records the source
log name, SHA-256, line 225, immutable baseline tree, and unmodified before/after
results. There are 70 baseline acceptances and 30 baseline parse errors. Managed
contracts now match their `before` results exactly. Historical replay is not a
fresh Windows PowerShell 5.1 qualification run.

The existing inferred fixture gains 80 `strings_batch_` neighboring cases. These
include malformed nesting, Unicode/scoped/question-mark names, bounded braced
names, trailing CR/newline, escaped dollars, literal subexpression source
spelling, and explicit complex/depth/large-number rejections. They remain labeled
inferred and are included in the existing Windows non-relaxation suite.

## Grammar and boundaries

- Here-string CR, LF and CRLF boundaries are physical line boundaries. Only the
  final physical newline before a footer is removed. A footer followed by an
  ordinary word starts a separate token; unsupported punctuation is not merged.
- Dollar scanning returns a nullable structured failure. On success it appends
  the complete original source slice. It never resolves names or computes values.
- Variable names support Unicode letters/digits, underscore and question mark;
  empty scoped names remain malformed. Braced names admit a deliberately bounded
  additional set (space, tab, hyphen and dot). Escaped/special braced names remain
  explicit qualification gaps.
- Supported embedded bodies are empty, a single command with bounded literal
  arguments, or arithmetic syntax over integer/string/variable/subexpression
  operands. Integer spelling is bounded to 18 digits. Nesting is bounded to 64.
- Observed contextual command words such as `public`, `static`, `interface` and
  `default` are accepted in command position. Actual statement/declaration
  keywords retain grammar guards; standalone `if`/`enum` stay parse errors.
- Inner quoted closing parentheses are rejected by a lexical-boundary rule,
  consistent with both observed `$("x)")` failures. Opening parentheses inside
  embedded quoted text remain unqualified. This is not a general balanced-string
  parser or a claim that all nested PowerShell syntax is covered.
- Complex statements, pipelines, multi-statement bodies, comment-bearing bodies,
  unsupported operators, braced escapes and unknown operand families fail closed.

Microsoft's [variable syntax documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_variables?view=powershell-5.1)
and [parsing documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing?view=powershell-5.1)
provide syntax background. They do not replace exact PS5.1 token-content evidence.

## Integration hooks

`ReadDollarText(string step, ref int index, StringBuilder value, int depth = 0)`
expects the caller to have consumed `$`. It returns `null` on success, otherwise
`ParsedStep` with `parse_error` or `unsupported_token`. A failed scan may advance
`index`; callers doing diagnostic preflight should not assume rollback. The
quoted-string and here-string callers return that structured failure directly.
The generic-token caller must use the same nullable API.

Outer-loop edits are limited to the quoted-dollar call and here-string suffix
hook. No workflow dispatch, native inclusion, CI, policy, or execution code is
changed by this batch.


## Source-informed boundary follow-up

A review against the official early open-source
[PowerShell tokenizer](https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/System.Management.Automation/engine/parser/tokenizer.cs)
identified three conservative boundary corrections: a leading question-mark
special variable ends after one character; doubled colons end a variable even
after its initial drive separator; and a backtick does not hide parentheses from
the outer subexpression boundary pass. Unsupported expression adjacency and
escaped inner-string parentheses now fail closed. Ordinary quoted/here-string
suffix text keeps its original spelling.

The 44 `strings_followup_` adversarial and preservation probes are source-informed
inferences, not observed PS5.1 results. They run as managed contracts and through
the existing Windows inferred-case differential suite. The immutable 100-row
historical observed fixture is unchanged.

A further 16 `strings_quote_boundary_` source-inferred probes cover backtick and
doubled double-quotes inside nested quoted operands. The reference outer scanner
transforms these spellings differently in ordinary versus here-string contexts.
They now fail closed until context-sensitive nested scanning is qualified; simple
inner quotes, single-quote doubling and non-quote escapes retain their prior
handling. No recorded observed rows were changed.

The raw-neighbor guard also includes the consumed opening delimiter and quote
characters reached after paired-backtick skipping. A further 46
`strings_raw_quote_boundary_` inferred probes cover empty inner double-quotes,
backtick runs of lengths 1 through 8, smart quotes, argument forms, and preserved
safe neighbors. Empty inner single-quotes, ordinary nonempty strings, and even
backtick runs followed by non-quote text retain their handling. These probes are
not Windows observations; the historical oracle rows remain unchanged.
