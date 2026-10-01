# Pure coordinate-math compatibility kernel

`LegacyCoordinateKernel.Map(args)` performs no desktop acquisition or input. It takes
an already captured `virtual_screen` and resolved `selected_window` (or null), with
`from`, `x`, `y`, `norm_x`, `norm_y`, `has_norm`, optional target selectors and optional
`coordinate_profile`. The shared `legacy-compat` dispatcher exposes operation
`coord-map` under `cucp.legacy-compat/v1`.

`virtual_screen` requires integer x/y/width/height/right/bottom/monitor_count;
right/bottom must agree with dimensions. The selected window contains hwnd, title,
process, class and a rectangle with x/y/width/height. Fields use the same names and
coordinates as the original Win32 acquisition adapter. Width/height are nonnegative;
finite numeric and 32-bit mapped-coordinate checks fail closed on malformed input.

Returned data retains `cucp.coord-map/v1`, selected-window metadata, clipping,
physical/window/visible-window points, normalized point, inside flags, warning order,
profile, partial reasons and next-step text. `elapsed_ms` is zero in the pure kernel;
the adapter may supply its own measured end-to-end acquisition/mapping time.

Compatibility details intentionally retained:

- Midpoint rounding is .NET ToEven, including negative halves
- Rectangles have exclusive right/bottom edges; normalized 1 maps to that outside
  edge and produces warnings, never an invented in-bounds clamp
- `visible-normalized` retains the legacy clip-relative fraction in the field named
  `normalized_window_point`; it is not reinterpreted as whole-window normalized data
- Missing target precedes unsupported-mode reporting
- Screen/window modes preserve zero-sized clip metadata; visible modes return partial
- Existing profile high-risk warnings are appended in original order

The kernel does not discover or select a window, hit-test, build a live coordinate
profile or assert freshness. Those read-only acquisition steps stay in the existing
adapter. A computed point and an `ok` report never authorize input or bypass target,
observation, foreground, privilege or confirmation gates.

Windows differential fixtures extract the original `_CoordMap-Rect`,
`_CoordMap-ClipRect`, `_CoordMap-MakePoint` and `_Build-CoordMap` from pinned tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`. Only acquisition helpers are replaced with
fixed fixture snapshots. Every deterministic field is compared; only top-level
elapsed_ms is excluded. Coverage includes negative monitor origins, partial/offscreen
windows, zero dimensions, all five modes, exclusive edges, half-pixel rounding,
explicit normalization, missing targets and high-risk profiles. No real OS input or
window enumeration is performed. Do not retire the original arithmetic before these
Windows comparisons pass.
