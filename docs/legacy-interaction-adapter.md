# Interaction retained-adapter candidate

`scripts/cucp-legacy-interaction-adapter.ps1` is a draft hook and wrapper module.
It does not replace or automatically load over the original eight functions.
Its new PowerShell bytes remain part of the migration inventory until the exact
candidate and actual adapter have passed their gates and the integrator promotes
one unique definition per original function.

## Shared transport contract

The module builds immutable invocation context with the existing
`_Read-StandaloneConfirmation` preflight, which already respects the inherited
constant sensitive ceiling. It does not duplicate consent classification.

`_Invoke-LegacyInteractionFamily` passes the existing common startup fields and
two actual Boolean fields (`double`, `right_click`) in
`cucp.interaction-start/v1` to:

```
_Invoke-LegacyExecutionHost -EntryPoint 'legacy-interaction-session' -Startup $startup -State $state
```

The integrator owns that shared lifecycle, frame codec, startup parser and
NativeHost registration. The module includes no child-process bootstrap,
PowerShell process bridge, frame loop or replay transcript.

State includes `family='interaction'`, the original operation/arguments,
immutable live/sensitive ceilings, owned paths, clocks, and an empty
`pipeline_output` ArrayList. The shared validator checks the envelope and ceilings,
then decodes data exactly once before `_Interaction-ValidateEffect`.
The family validator checks decoded shapes, closed operation/kind/action maps,
required option arity, unknown/duplicate options, typed fields and mutation
classification before `_Interaction-Dispatch` reaches any original leaf.

Read-only operations cannot issue input even when a caller's global live ceiling
is true. Native `focus`, `click`, `type` and `shortcut` require `live=true`;
`windows`, `ocr-find-text` and `hit-scan` require false. Core `act click` and
`act right-click` require true. The shared NativeHost and kernel independently
retain their immutable authority checks.

Cache keys are exactly 32 lowercase hexadecimal characters, with absolute string
anchors. Writes keep the existing storage root and use only original
`_PointPlan-WriteCache` / `_AnchorHistory-Append` leaves. Cache writes, anchor
appends, trajectory appends and Notice wrapper-log writes are owned-state
mutation boundaries for the shared uncertainty implementation. All Native
helper calls are potentially owned-state writes too: retained helper execution
uses redirected cache files and may log a timeout or delete a stale lock. This
applies even when the native action itself is read-only; its live-authority bit
still remains false. Acquired data cannot choose an external filename or
an arbitrary callable function through these hooks.

Per-operation receipt lists bind Vision to a screenshot actually returned by
Appshot and core actions to an acquired or explicitly generated observation ID.
The legacy empty string values are recorded without inventing replacement IDs.
Cache writes require the exact queried cache key; anchor appends require the
exact record previously scored. Lists live only for the bounded current operation
and do not create persistent access or authority. Malformed or mismatched
receipts are rejected before the leaf function runs.

## Output and failure behavior

`Console(name='write')` calls `Console.Out.Write`, preserving no trailing newline.
`PipelineOutput` adds to `state.pipeline_output`; it must never become a callback
reply value. The shared host emits buffered strings before the final integer
exit, preserving ClickLabel's original PowerShell pipeline result. Native exit
values retain signed Int32 behavior, including nonstandard fixture failures such
as exit seven.

The shared host owns all transport/dispatch uncertainty receipts. A callback
failure is uncertain when that effect may change state or live input was already
dispatched. An ordinary UIA read failure after a known-successful Appshot keeps
its original fallback. Uncaught or transport/encoding failures remember all
prior state effects, preventing automatic repetition of completed writes. The
actual-adapter fixture keeps ordinary parity and these deliberate corrections
separate, checking the exact pre-failure effect prefix and absence of later actions.

## Qualification

`tests/python/test_legacy_interaction_adapters.py` and its small test-only harness
reuse the existing 870-case accepted-source corpus and 12 explicit uncertainty
cases. They load the exact shared transport and draft adapter via AST definitions,
while capturing every original acquisition/input/vision/storage leaf. No GUI,
clipboard/IME, authenticated model or persistent access is used by the tests.

Windows PowerShell 5.1 actual-adapter parity, strict forged-descriptor rejection,
central startup/production reachability proof and the final bundled regression
are required before retirement. Linux static checks alone do not establish those
gates. The draft module is neither a promoted adapter nor a zero-PowerShell release.
