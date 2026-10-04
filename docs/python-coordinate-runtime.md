# Production coordinate runtime

`coord-profile`, `coord-map`, and `hit-test-batch` now delegate to Python in the
default wrapper and are connected in the staged preserved owner. The Win32
hit/profile/map builders delegate as well, so their callers use the same
read-only Python/C# implementation. The staged owner now connects 62 working
macros; 39 existing working macros remain unconnected, separate from the seven
original placeholders. This is not a complete wrapper or 0% migration.

Python owns acquisition order, target fallback, risk warnings, relative points,
reports, and batch sequencing. C# retains fixed Win32 reads, the existing pixel
mapping kernel, .NET argv conversions, and point-specification regex semantics.
The added target-monitor read does not reacquire the complete layout. A batch
uses one read-only native worker for all valid points, rather than starting
one process per point. No input or shell operation is available at this boundary.

PS5.1 and PS7 window selection differ: PS5 uses Windows NLS and unstable equal
ranks, while PS7 uses its modern linguistic comparisons and stable equal
ranks. The wrapper supplies the actual runtime dialect and culture at startup;
JSON cannot choose them or grant live authority. The pure selection kernel
reuses the already qualified NLS/Framework ordering utilities. Acquisition is
single-attempt and bounded by one invocation deadline; a failed worker is not
restarted. Large target handles retain Int64, while the legacy point-hit Int32
conversion failure remains optional inside profile acquisition.

`test_coordinate_production.py` compares 84 captured scenarios per actual
Windows shell against immutable main commit
`b1a5641f129c039afdc8cbe969c3d365e5539740`. They cover point edges, negative
origins, multi-monitor/mixed DPI risk, missing/oversized handles, equal-rank
windows, option aliases, invalid numbers, Unicode digits, point-spec errors,
brief/JSON output, and unavailable Win32. Elapsed time is the only excluded
runtime field. Actual wrapper/owner reads and 50-point single-worker reuse are
separate checks; they do not prove real multi-monitor hardware or user input.

The previous PS/C# math facade remains a hash-addressed Git oracle only in
`test_legacy_coordinate_parity.py`; the production runtime has no historical
script fallback. Dispatch order, the 109 clauses, 108 names, and the safety
digest remain unchanged. Source counts include all tracked `.ps1` files,
without Linguist exclusions; see `legacy-function-inventory.json`.
