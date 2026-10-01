# Legacy workflow planning candidate

Status: **not qualified to replace the PowerShell parser**. Keep
`_Parse-WorkflowStepTokens`, `_Read-WorkflowStepSpecs` and `_Build-WorkflowPlan`
until strict Windows differential qualification is complete. This change adds
no agent tool, performs no live command, and does not register the candidate
in the production compatibility dispatcher.

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
