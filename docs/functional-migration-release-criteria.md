# Functional migration release criteria

The migration must preserve supported commands and functionality while removing
PowerShell source and execution dependencies. Byte-for-byte reproduction of an
incidental runtime diagnostic is not an independent product requirement.
This document defines a bounded decision rule; it does **not** change existing
assertions, erase exact mismatches, or declare a candidate qualified.

## Required functional contracts

- Preserve accepted/rejected supported inputs, validation precedence where it
  changes a result, machine-readable status/reason/schema fields, exact numeric
  values, selected strategies and records, array order/cardinality, and the
  distinction between absent output, null, and empty/singleton arrays.
- Preserve effects and their order, authorized scope, no-retry after uncertain
  mutation, ownership/ACL checks, malformed-envelope refusal, bounded resource
  use, and supported command behavior. A runtime replacement is not permission
  to broaden access or silently discard behavior.
- Preserve strings used as keys, grouping values, selected strategy names,
  timestamps exposed as data, or inputs to another operation. Numeric display
  that changes an audit aggregation key is a functional mismatch.
- Retain exact raw observations, source/corpus hashes, runtime identity and
  repeat-run evidence. Any separately named functional result must list its
  precise allowances and remaining failures beside the raw exact result.

## History: justified allowances and remaining blockers

At public commit `df200f0792a83698c95ed2672999b2d9081f734c`,
[Windows run 37096050477](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37096050477)
completed both singleton checks and four full 465-input comparisons. Per full
run, PS5.1 has 299 exact matches, 118 representation-only differences and 48
functional differences. PS7 has 281 exact matches, 115 representation-only
differences, 19 data/selection/shape differences and 50 additional exposed date
string differences. Thus 117 of 930 runtime/input combinations remain blocked;
this is not a count of unique inputs across runtimes. Repeats overlap.

Only these allowances are supported by current caller evidence:

1. Oracle-only numeric CLR tags may differ when the exact mathematical value
   agrees. Do not coerce strings/booleans or compare through binary floating
   point. JSON numeric spellings may differ only if their exact values agree.
2. JSON escape spelling may differ when the decoded string is identical.
3. The `_History-Stats` strategy-count map may enumerate in a different order.
   Its only direct product caller is `scripts/cucp.ps1:5874`; brief rendering
   explicitly sorts keys at lines 5876–5879, while JSON rendering emits the map
   at line 5881. Keys, casing/codepoints, counts, cardinality and brief output
   remain exact. PS7's two original runs themselves reorder this map in 41/465
   inputs (123 raw field differences) with equal values and array ordering.

Do not extend the map exception to arbitrary records or nested objects.
Object interpolation can consume their order. `_History-PickBestStrategy`
feeds smart-plan and execution at `scripts/cucp.ps1:6010,6335`; smart-click uses
the chosen strategy to select stages and fallback in
`LegacyExecutionSmartClick.cs:19–21,63,172–189`. `_AppStrategy-LastGood` feeds
app-profile at `scripts/cucp.ps1:6672`; `LegacyAppProfileKernel.cs:406–419,439`
uses its strategy for scoring and retains the full record in public evidence.
Date strings cross serialization at `scripts/cucp.ps1:2442` and are preserved
by `LegacyAppProfileKernel.cs:213,263,414,439`. Equal typed DateTime values do
not establish identical public strings. A caller-roundtrip check or a repair
is required for the 50 PS7 timestamp cases.

Remaining fixes concern comparison/key merging, parsed data and exact numbers,
empty-object interpolation, LastGood pipeline array shape and sorting, and
caller-visible date serialization. The large-integer case is not spelling-only:
`9.223372036854776E+18` and `9223372036854775808` differ by 192. All security,
strict decoding, bounds, provenance, no-retry and side-effect tests remain
required. Qualification needs both actual hosts, all six fresh-process runs,
and caller-level stats/planning/execution/app-profile evidence checks.

## Diagnostic prose versus diagnostic data

For benchmark baseline failures, `scripts/cucp.ps1:8074–8078` emits the stable
`baseline_load_failed` error and an exception-message `detail`. The brief
renderer checks the error's presence, not the sentence (`:8094–8099`). The
candidate mirrors this in `LegacyDiagnosticPerformance.cs:148–152`. No product
consumer of that specific prose was found in the repository. Its localized
runtime wording may be characterized without being a release blocker, provided
the same input fails at the same effect boundary with the same schema/error,
no leaked data, no extra effect or retry, and a useful bounded diagnostic.
This is a scoped prose allowance, not a general exemption for `detail` fields.

Audit `by_macro`/`by_exit_code` keys and earliest/latest timestamp strings are
data. Finite-Double formatting can merge or split those keys; the 668-input
candidate repair must receive fresh Windows evidence before audit retirement.
The exact historical diagnostic gate and all of its inputs remain intact.

## Helper: intended working contract and observed startup defect

The unmodified hash-pinned original server in
[run 37096050336](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37096050336)
exits 1 with `CommandNotFoundException` at its `owner_sid = (try { ... })`
expression before publishing the owned lock. Matching that crash is not the
replacement's objective. Preserve it as an independently observed baseline
defect with complete raw bytes, exact source identity, and absence of a live
owned service/lock. Other exits, incomplete evidence, timeout, truncation or
unexpected effects must not be accepted as this known defect.

The replacement must positively qualify health/start/shutdown, supported
actions and response schemas, counters, detached shared lifetime, identity and
lock ownership, pipe framing, ACL behavior, bounded exchange and cleanup.
Original-startup evidence is not a passing service test. The user-visible
correction is a reachable documented service instead of pre-lock termination.
Any stronger deadline or lock policy requires its own compatibility-impact
record; it must not be described as exact parity. Production cutover still
requires caller integration and independent Windows verification.

## Priority and final removal

The highest-leverage current candidate is the helper service/client family
(35,505 original runtime bytes). Audit-summary is a smaller nearer cutover
(2,728-byte original body), after its real grouping-number repair qualifies.
Neither candidate earns retirement credit before actual production routing,
negative tests and full regression pass. Parser diagnostic sentences and
other incidental representations must not displace functional blockers.

Final zero-PowerShell verification includes inline/encoded/generated scripts,
CI/install/launch commands, engine/SDK/reflection references and process-level
execution evidence, not only extension-counted bytes. Historical originals
may remain reachable in Git history, not as a final shipping dependency.
