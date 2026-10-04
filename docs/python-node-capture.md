# Production Node capture in Python

The default `Invoke-Cucp -CaptureJson` path now invokes a fixed Python entry.
Python owns literal argv, UTF8 stdout/stderr artifacts, real process exit,
timeout reporting and the owned process handle. The old in-process JSON parser
remains a thin compatibility step, preserving both PS5 and PS7 JSON shapes.
Streaming retains its existing default path; the new Python runtime additionally
supports an inherited streaming deadline for the pending complete root.

The optional external `cli.mjs` is not copied or replaced. Its fixed startup
path remains optional, and missing CLI still produces the original envelope.
Request JSON contains argv only and cannot choose paths, executable or timeout.
Raw and stderr text use base64 transport because PS7 automatically recognizes
date-shaped JSON strings. Input is never replayed after timeout/cancellation,
and cancellation never kills user application descendants.

Actual owned Node fixtures cover quoted/trailing-slash/empty/Unicode arguments,
non-JSON and nonzero exit, partial timeout, missing CLI, cancellation, inherited
budget and serial scope. Original/current production comparisons cover 13 cases
per actual PS5.1/PS7 shell against immutable `500246d`, including JSON arrays,
singletons, scalars, null, UTF8 BOM, date-like stderr and timeout 0/-1.
Timing, command GUIDs and random artifact spelling are runtime-only fields.

Three PS5 exit-handle failures are explicitly pinned rather than declared exact:
old non-JSON exit2 and error exit3 replies incorrectly report0, and empty success
reports null. Python reports the real2/3/0. This fixes failure propagation without
changing the CLI's raw content, parsed payload or supported modes.

This candidate removes 1,572 actual PowerShell bytes, from 761,043 to 759,471.
Seven owned runtime tests and26 production cases passed, as did28 frozen
source/inventory/order guards. No user-app input was performed. Whole root
cutover, remaining macros/tests and the 0% goal remain unfinished.
