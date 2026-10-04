# Legacy workflow planning candidate

Status: **not qualified to replace the PowerShell parser**. The parsed-result
assembly path below can be qualified independently; keep the exact
`_Parse-WorkflowStepTokens` and `_Read-WorkflowStepSpecs` adapters. Replace the
large `_Build-WorkflowPlan` construction body only after its independent Windows
proof passes. This change adds no agent tool and performs no live command.

## Independent parsed-result assembly

`LegacyWorkflowKernel.PlanFromParsed(JsonElement)` accepts:

```json
{
  "rest": ["--step", "macro windows"],
  "parsed_steps": [{"ok": true, "error": "", "detail": "", "tokens": ["macro", "windows"]}]
}
```

The retained PowerShell adapter obtains each result by calling the exact
original parser on each `_Read-WorkflowStepSpecs` string. C# derives the same
raw specifications and name from `rest`, requires one parsed result per
specification, then assembles the plan. It does not call or reference the
candidate lexer. Raw text, token text and original parse diagnostics are data;
none are evaluated or interpolated.

Validation rejects duplicate/unknown fields, missing fields, wrong types,
count mismatches, unknown parser error codes and inconsistent success/failure
shapes. Successful results require nonempty string tokens and empty error/detail;
failed results require an empty token array and one of `parse_error`,
`unsupported_token` or `empty_step`. The original error detail is preserved
exactly, including Unicode, quoting and newlines. Parsed NUL characters remain
literal data rather than being reinterpreted or discarded.

Bounds are 4,096 rest items, 262,144 total rest UTF-16 units, 256 derived
steps, 4,096 tokens per parsed step, 65,536 units per token or diagnostic,
and 262,144 total units across all parsed tokens/errors/details. Existing
safety-classifier input limits also apply. These are explicit compatibility
boundaries, not additional authority to run the plan.

The shared assembler provides both parsed-result planning and the standalone
lexer candidate; there is only one allowlist, safety and result-construction
implementation. `LegacyWorkflowKernel.cs` contains only the parsed-input API
and shared policy/assembly. The unqualified lexer and its `Plan(rest)` entry
live separately in `LegacyWorkflowLiteralParser.cs`. A production build can
compile the former and exclude the latter entirely.

The pinned `_Build-WorkflowPlan` function occupies 114 non-trailing-blank
lines and 5,307 UTF-8 bytes including its following separator. Its 34-line
tokenizer and 20-line step reader can remain while the roughly 5.3 KB builder
becomes a small parsed-data forwarding adapter. This does not remove the
remaining PowerShell parser dependency or change its accepted language.

## Standalone literal-parser candidate

`LegacyWorkflowKernel.Plan(JsonElement)` accepts `{ "rest": ["--step", "macro windows"] }`
and constructs the legacy `cucp.workflow-plan/v1` result. The policy portion
retains the pinned read-only/live macro allowlists, recursive-workflow blocks,
session subaction restrictions, sensitive-confirmation annotations, original
step indices, errors and aggregate counts. Classification uses the migrated
`LegacySafetyKernel`; a `safe_to_run` plan is still only a plan, never permission
to execute its live or sensitive steps.

The source baseline is commit `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`,
tree `bf895d3120dd5e145f360cb1c41e1d79a061d048`. Python source checks compare
the actual workflow function's allowlists against that immutable tree.

## Why parser retirement is gated

The old function uses `PSParser.Tokenize`, which parses complete PowerShell
syntax and then permits only `Command`, `CommandArgument`, `String` and
`Number` token classes. It ignores `NewLine` and `LineContinuation` tokens
and drops empty string values. It does not merely split shell-style words.

The C# candidate contains a bounded, literal-only scanner with no PowerShell
SDK, parser dependency, variable expansion, command substitution or evaluator.
It implements ordinary command words, double-dash arguments, literal quoting,
the PowerShell 5.1 backtick escape set, doubled quotes, empty-string removal,
and ordinary whitespace/line-continuation handling. It rejects execution
constructs and single-dash parameter tokens.

Full language compatibility is not established. Concrete gaps requiring
Windows PowerShell 5.1 differential evidence include:

- Expandable strings and embedded variable/subexpression token reporting
- Literal and expandable here-strings
- Adjacent-token backtick/newline sequences
- Leading expression, reserved-keyword and dot-sourcing token contexts
- Stop-parsing markers, malformed grouping and parse-error precedence
- Non-ASCII unquoted whitespace and context-dependent parameter tokenization

The candidate fails closed for these uncertain cases rather than interpreting
them as executable syntax. That can reject input the original accepts; it is
not feature-equivalent merely because common cases pass. Parse diagnostics
are intentionally stable native text rather than localized PowerShell wording.
Strict qualification compares the error codes and blocked behavior, excluding
only the human-readable `message` and `detail` fields.

The new wire boundary also imposes explicit resource limits: 4,096 `rest`
items, 262,144 total UTF-16 input units, 256 steps and 65,536 UTF-16 units per
literal step. The safety classifier's existing limits continue to apply.
NUL in the JSON `rest` input is rejected. These bounded-input differences must
be included in any eventual migration decision.

## Tests

Run the independent managed candidate checks without a desktop:

```text
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyWorkflow.ContractTests -c Release
python -m unittest discover -s tests/python -p test_legacy_workflow_parity.py -v
```

The managed project links only the pure kernel, safety classifier and error
contracts. It has no native desktop dispatcher and never runs a planned argv.
Its test-only `--fixtures` mode accepts a bounded JSON array on stdin so all
comparison cases can be evaluated without spawning a process per case.

On Windows the Python suite builds this independent runner, imports only six
pure planning/safety definitions from the pinned PowerShell AST, and compares
their output. It does not invoke the original script entry point or
`workflow-run`. The ordinary corpus covers all allowlist entries, blocked
recursive/session actions, safety categories, argument grouping, literal
quoting and escape behavior. The broad syntax probe must never permit a
sequence rejected by the baseline or change the tokens of an accepted one.

Before retirement, set `CUCP_REQUIRE_WORKFLOW_PARSER_PARITY=1` and run that
Windows suite. The strict gate fails on every remaining broad-probe mismatch,
including conservative rejections. Without that variable, unresolved probe
differences are explicitly printed as `WORKFLOW PARSER NOT QUALIFIED`;
ordinary test success must not be advertised as full parser parity.

Neither Linux-only checks nor a passing non-strict probe authorizes replacing
the old parser. Additional real-world literal fixtures may be needed even
after this bounded corpus passes.

### Separate proof for parsed-result assembly

`test_actual_psparser_results_preserve_complete_original_plans` takes all
199 literal/policy fixtures plus all 55 broad syntax probes through the actual
retained PowerShell tokenizer. It supplies those exact parsed results to C#
and compares complete plans against original `_Build-WorkflowPlan` output,
including original diagnostic messages. It does not call the candidate lexer
or relax comparisons because of the candidate's unresolved grammar gaps.

This test can qualify plan construction independently. Its success cannot
qualify the standalone C# lexer, and until it actually runs on Windows its
presence alone is not evidence of .NET Framework/PowerShell parity.

When `CUCP_NATIVE_TEST_HOST` is configured, the same test additionally checks
eight representative parsed-fed cases through the actual `legacy-compat`
`workflow-plan-from-parsed` operation: read-only success, sensitive live plan,
recursive-workflow block, parser error, quoted variable text, here-string,
Unicode and NUL-containing literal data. It compares complete original plans,
including error messages. These real-dispatch checks supplement the full
independent 254-case assembler comparison; they do not replace it.

### Observed candidate qualification

The Windows run for checkpoint `b6a29f05ec270f49172bafb06b91fac82710a004`
passed all 199 ordinary literal/policy fixtures. Its broad non-relaxation probe
found one defect: unquoted standalone `--` was accepted by the candidate even
though PSParser rejected it. The candidate now rejects that operator form;
quoted and backtick-escaped `--` remain literal. Assertions were not relaxed.
The fix and new parsed-feed path require a subsequent Windows run.

The same run confirmed the separately reported conservative grammar gaps.
The candidate remains excluded from production and is still not a qualified
replacement for the PowerShell parser.

## Qualified plan-body retirement

Checkpoint `2d8443d789a319f232ea5e28c53522f9eb551527`, run `36898932493`, passed all four jobs. The complete 254-case original-PSParser-fed assembly comparison and eight actual native dispatcher cases passed. The retained `_Build-WorkflowPlan` now only tokenizes with the original parser and forwards parsed data to the qualified assembler. No candidate grammar is shipped or substituted. This removes a net **4,541 further PS bytes**, including operation-routing overhead. The same suite now exercises this actual PS adapter across the whole corpus; its next-commit qualification remains required.
