# Observed unsupported-token diagnostic repair

## Immutable Windows evidence

[Windows run 37086299736](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37086299736)
tested `1e3d534a1d244bcc9ed6bfd318a1976b95c22eb0` using Windows PowerShell
`5.1.26100.33438`, Desktop edition, `en-US` culture/UI culture. The full 128-row
capture is retained byte-for-byte in
`tests/fixtures/legacy-workflow-ps51-raw-diagnostics-37086299736.json`.

- Raw capture SHA256:
  `c60e8e0a7d975b37090d434d9ced26f6acc37dd85a0a89a5c1ec0668572bfbb8`
- Original foundation artifact ZIP SHA256:
  `baf26d7a36c9fc56c570dbdef5d1434c329ac7b376e82d0e1c5f5de94af14b30`
- Captured original-source and six helper hashes, complete plans, parsed
  detail strings, ordered error records and token types remain unchanged.
- Worktree and Git-index raw bytes are independently hashed. A path-specific
  `-text` attribute prevents line-ending conversions. Existing historical
  captures, expected results and oracles are preserved.

The historical candidate had 106 exact parsed/plan differences: 98 text-only
and eight also different after diagnostic text was removed. These overlapping
corpora must not be added to the separate 55 remaining conservative
literal/boundary rows.

## Rejection-only change

The candidate now emits the observed `unsupported token type '…'` detail for:

- Token-leading `(`/`{` and `@(`/`@{`: `GroupStart`
- Token-leading line comments and block comments: `Comment`
- Semicolons: `StatementSeparator`
- Pipeline/output-redirection punctuation: `Operator`

This changes no acceptance, token content, error code, input bound, execution
behavior or production caller. The whole-step syntax preflight still runs first
and is unchanged. Unsupported tokens are still rejected in encounter order,
so an earlier command parameter retains its existing diagnostic. Other
unqualified punctuation and splatting continue to use their prior candidate
explanations; this is not a complete token-type implementation.

`legacy-workflow-token-kind-repair-37086299736.json` selects exactly 20 observed
raw rows. Managed checks require exact parsed objects and complete generated
plans to equal the original oracle for those rows. All other 108 rows must equal
the historical candidate result, including unchanged raw detail/message text and
existing argument-validation exceptions for plans containing physical NUL.
No dropped text fields or per-input classifier exceptions are used to pass
these exact comparisons.

## Fresh qualification probes and safety guards

The next Windows capture keeps the original 128 IDs, steps and order and appends
24 explicitly inferred rows. Sixteen check exact unsupported-token details and
full plan equality; eight check parse-error precedence with unbalanced groups,
arrays/hashtables, unterminated comments, line-comment/newline transitions,
quoted punctuation and escaped delimiters. Earlier-parameter and later-parameter
neighbors check first-unsupported-token ordering. Quoted and escaped punctuation
must not acquire diagnostic meanings before their actual unquoted boundary.

The finite Python and PowerShell case cap increases from 128 to exactly 152.
The over-limit rejection probe now has 153 rows; all shape, field, duplicate-ID,
UTF-16 length, input/output size and original-source hash checks remain.
The oracle's only change is this three-digit bound, so tracked PowerShell byte
counts are unchanged. Both strict parity environment flags still reject any
remaining exact parsed/detail/plan-message difference. The new probes run inside
the existing mandatory foundation diagnostic gate and retain raw evidence on
assertion failure.

## Local verification and limitations

- 1,755 managed workflow checks passed; .NET build has zero warnings/errors.
- Focused Python workflow suite: 49 tests, 36 passed, 13 Windows-only skips.
- Full Python suite: 567 tests, 443 passed, 124 explicit platform skips. An
  initial run hit the inventory guard for an unstaged oracle-cap edit; staging
  the reviewed equal-length change and rerunning passed without test changes.
- All 128 historical results replayed: only the 20 targeted parsed/plan
  diagnostics change; all 108 other complete candidate results are unchanged.
- Historical replay now has 86 exact gaps: 78 text-only and the same eight
  normalized gaps. No additional inputs became accepted.
- Production still uses PSParser. `LegacyWorkflowLiteralParser.cs` remains
  excluded from NativeHost. No production PowerShell or adapter is changed.
- All tracked PowerShell remains 870,201 bytes: 610,258 runtime and 259,943
  other source/test bytes, with 143,277 bytes removed from the original baseline.

This local batch has not been freshly qualified on Windows or published.
The 24 new expectations remain inferred until the actual PS5.1 run supplies
fresh results. Historical replay does not establish full grammar or localized
parse-error wording parity.

## Next separate bounded candidate

Five observed physical-NUL string rows in
`legacy-workflow-ps51-boundary-observed-37079778520.json` are a coherent next
acceptance/token group: `quoted_nul_unqualified_204` through `_208`.
Their original PS5.1 results preserve physical NUL inside ordinary single/double
quotes and both here-string forms; the recorded double-quoted backtick before
physical NUL is also retained, rather than consumed as a normal escape.
That batch should add terminator-edge, repeated-NUL, escaped-NUL and malformed
quote/dollar neighbors while preserving existing plan argument validation.
It is not implemented here, and stop-parsing-marker NUL boundaries remain a
separate group with their own pipeline/preflight risks.
