# Production history migration

`macro history` and the smart-click history helpers now use
`pcucp_cli.legacy_history_bridge` for owned file reads, append/rotation, clear,
statistics, lookback/frequency planning, and reverse physical-file selection.
The default history path and retention limit are process-startup arguments;
JSON cannot redirect a write or change its retention policy. No shell, Node,
native input, or historical script fallback exists in this Python operation.

The current PowerShell JSON dialect remains a compatibility boundary. The
wrapper captures parsed scalar facts, the runtime's Hashtable key identities,
and original records before asking Python to reduce them. Final linguistic
tie comparisons and Console formatting still run in thin wrapper glue. This
preserves PS5.1/PS7 differences in null/blank/array parsing, success coercion,
case-sensitive property collisions, string interpolation, culture, and brief
numeric formatting. A strict Python JSON parser alone failed the wider corpus;
that implementation was replaced before publication. The separate C# history
qualification candidate has not been promoted.

The existing portable `SmartClickHistory.pick/stats` methods remain staged;
their JSON and scalar approximations are not used by this production cutover.
Only its owned append/rotation implementation is reused. Statistics cross the
bridge as typed name/count pairs so empty and reserved strategy names survive,
then recover the original Hashtable and Decimal/Double types in the caller.
Python scales before midpoint-to-even rounding as `Math.Round(Double, 1)` does,
including additional 0.05/0.15/5.65 percent cases that `round(value, 1)` would
handle differently. Integer division retains the original Decimal overload;
fractional division retains Double, and empty statistics retain Double zero.

`tests/python/test_python_history_production.py` compares all 305 existing
pick/stats fixtures against immutable historical functions in each actual
Windows shell. It also compares 120 complete production-wrapper cases per shell,
using the real Python process bridge and exclusively owned temporary files.
These exercise reports, brief output, selection, clear, malformed records,
argument errors, Unicode, large/locked files, append, and the 1 MB rotation rule.
Runtime facts and callback acquisition checks are distinct from full process
comparisons; neither exercises user desktop input.

The 18 core smoke checks formerly in `tests/pcucp-next.Fast.Tests.ps1` are now
`tests/python/test_core_fast_smoke.py`. They use `python/run_source.py` instead
of the already retired launcher. Native checks require a prebuilt host, never
compile on demand, and explicitly skip absent local prerequisites. The Windows
provider CI requires the host and OCR fixture dependencies, so missing
prerequisites fail there. Native reads cover windows, bounded UIA, find-label,
owned PNG OCR, and both module and source-launcher paths; there is no input or
elevation check in this smoke suite.

This is an incremental migration. Six production PowerShell files still remain;
neither the default wrapper nor all historical qualification tests are retired.
The all-tracked `.ps1` measurement remains in `legacy-function-inventory.json`;
GitHub language shares are reported separately from that byte count.
