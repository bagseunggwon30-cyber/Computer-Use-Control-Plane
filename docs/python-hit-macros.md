# Hit macro Python preparation and reporting

`hit-test` and `hit-scan` now use the production Python native macro
prepare/report boundary. The default wrapper retains its existing native helper
pipe and hot-cache acquisition. Fast hit uses the existing readonly coordinate
builder, bypasses UIA and the desktop helper, and preserves its distinct output,
elapsed-time field and partial exit. The staged owner connects both macros
without adding live authority: 64 working macros are connected and 37 remain
unconnected, separate from seven original placeholders.

Original coordinate/inset/radius/step conversions and parse order, target flags,
UIA-refinement suffix, missing-helper/raw output, empty JSON-object truth,
unknown-status handling and brief lines are compared with immutable main commit
`3916e00a43639a64a38883fc99401e25b77d82db`. The independent test invokes the
old functions with inert acquisitions, then the actual new wrapper functions,
and the Python runtime. Elapsed time alone is excluded for fast reads.
Malformed options and forged completion fields must fail before any acquisition
or write. Actual owner reads exercise fast, no-UIA and radius-zero scan without
input; these checks do not prove live clicks or arbitrary application behavior.

The historical direct-native macro corpus remains intact and now includes both
non-fast macros as well. Dispatch names, order, safety classification and startup
consent remain unchanged. This checkpoint removes 3,862 actual PowerShell bytes;
765,637 tracked PowerShell bytes remain. It is not completion of the 0% goal.
