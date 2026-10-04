# Deterministic observation processing migration

This migration moves the following legacy algorithms from
`scripts/cucp-native-helper.ps1` into the pure Python module
`pcucp-next/python/pcucp_cli/observation_processing.py`:

| Legacy function | Python function | Preserved behavior |
| --- | --- | --- |
| `_Normalize-OcrText` | `normalize_ocr_text` | NFKC, invariant-style lowercase, letters/decimal digits, punctuation-to-space, whitespace collapse |
| `_Score-OcrText` | `score_ocr_text` | Exact, prefix, contains, opt-in Levenshtein fuzzy scores |
| `_Match-OcrCandidates` | `match_ocr_candidates` | Line/word candidates, same-line adjacent 2/3-word n-grams for multiword queries, stable score/scope/area ranking |
| `_Resolve-OcrUiaFusionCandidate` | `fuse_ocr_uia` | Smallest containing UIA node, up to six parent edges, advertised Invoke/Toggle/SelectionItem patterns, role/state/depth score |
| `_Action-ScreenshotDiff` | `screenshot_diff` | Per-pixel RGB absolute-distance sum, strict threshold, intersection/crop, ignored regions, effective-pixel ratio |

No module function captures a screen, opens a file, starts a process, calls a
model, invokes a UIA pattern, clicks, or types. The module has only standard
library dependencies. Windows capture and OCR recognition remain C# work.
The transport/engine owner is responsible for checking provider results,
observation freshness and authorization before calling these pure functions.

## OCR API

```python
report = match_ocr_candidates(
    body, "Save As", "contains", min_score=70, limit=50,
)
```

`body` accepts a native `{words, lines}` payload or `{ocr: {words, lines}}`.
Each word contains `text`, `x`, `y`, and either `width,height` or legacy `w,h`.
Native lines derive their rectangle from their `words`. Legacy lines with an
explicit rectangle also work. N-grams never cross line boundaries. Flat words
that duplicate words inside lines are deduplicated. Text without geometry is
not sufficient for a grounded candidate.

The result contains `status`, `top`, `candidates`, `candidate_count`, `ambiguous`,
`truncated`, `source_incomplete`, `coordinate_space`, and `actionable: false`.
Candidates expose both rectangle dimension spellings for compatibility; their
centers are recomputed from geometry, without trusting supplied `cx,cy`.
The candidate coordinate space is `image_pixels`. Passing a payload labeled with
another coordinate space is rejected rather than silently offsetting it.

A top candidate is a ranking suggestion, never an authorized action. Different
rectangles whose scores differ by less than eight points remain ambiguous, even
when `limit=1`. Duplicate line/word evidence for the same rectangle does not
create false spatial ambiguity. Ambiguity is evaluated before output limiting.
The top remains visible for inspection and `status` is `partial` when ambiguous
or when an input is explicitly marked incomplete. No-match is `not_found`.

Legacy scores remain:

- Normalized equality: 100 in every mode
- Prefix: 80 for a non-equal prefix
- Contains: 50 plus floor(length-ratio × 30), plus 10 for a leading match
- Fuzzy: rounded normalized Levenshtein similarity, optionally raised by the
  legacy contains floor `55 + floor(length-ratio × 30)`

Fuzzy matching is never automatic. Normalization deliberately uses `lower()`,
not case-folding that would change legacy matches such as German `ß`.
Python edit distance uses Unicode code points; the old .NET implementation used
UTF-16 code units. Supplementary-plane character edit distances may therefore
differ. BMP/Korean normalization and scoring fixtures are covered.

## OCR/UIA fusion API and geometry contract

```python
fused = fuse_ocr_uia(
    report, uia_nodes,
    geometry={"x": -1920, "y": -200, "width": 1920, "height": 1080,
              "image_width": 960, "image_height": 540},
    target={"hwnd": "0x20", "pid": 42},
    uia_target={"hwnd": "0x20", "pid": 42},
    limit=8,
)
```

Pass the full OCR report to preserve its ambiguity/incompleteness flags.
A candidate list is also accepted when the caller manages those flags separately.
Geometry describes the physical captured region and dimensions of the exact
image OCR recognized. It must not describe a resized or different screenshot.
A point maps as follows:

```text
screen_x = geometry.x + image_x * geometry.width / geometry.image_width
screen_y = geometry.y + image_y * geometry.height / geometry.image_height
```

Negative desktop origins and independent X/Y scales are supported. No DPI guess
or assumption of a primary-monitor origin is made. OCR rectangles outside the
image, non-finite geometry, or a missing mapping are rejected. HWND and PID
must both match between the OCR and UIA snapshots. Matching identities does not
prove snapshot freshness or prove that a window has not moved: the engine must
collect fresh same-target evidence and enforce its existing observation rules.

`uia_nodes` accepts a bounded tree whose nodes use `bounding_rectangle`, `rect`,
or `geometry` and nested `children`. The parent chain is explicit; it is never
inferred from overlapping rectangles. Flat nodes also work, but cannot support
parent climbing. Preserve the raw tree if parent-climb parity is required.
Native `patterns`, alternative `supported_patterns`, and legacy `invoke_pattern`
are accepted. Opaque `element_ref` values are returned as evidence when present.
Known mismatched node process IDs are excluded.

The returned candidate `point` contains `image_x,image_y`, `screen_x,screen_y`,
and `x,y` aliases for the **physical screen** point. Both the point and top-level
report explicitly declare `physical_screen_pixels`. Nested OCR evidence remains
labeled `image_pixels`.

Unlike the legacy helper, fusion preserves equal-area overlapping alternatives,
returns ranked candidates, and does not automatically invoke the first result.
`can_invoke` means a supported pattern was advertised, not that invoking it is
safe, enabled, authorized, or still valid. Missing enabled/offscreen state stays
unknown. Every result says `actionable: false` and requires a fresh observation
before downstream action. A host must choose an exact target through normal
live-control and element-reference validation; fusion never does so itself.

## PNG and screenshot difference API

```python
image = decode_png(png_bytes)  # {width, height, rgba: bytes}
result = screenshot_diff(before_png_bytes, after_png_bytes, threshold=16,
    region={"x": 10, "y": 20, "width": 300, "height": 200},
    ignore_regions=[{"x": 20, "y": 20, "width": 10, "height": 10}])
```

`screenshot_diff` accepts PNG byte strings or already decoded
`{width, height, rgba}` buffers. It does not accept filesystem paths.
The decoder supports noninterlaced 8-bit RGB and RGBA PNGs, all five PNG filters,
consecutive split IDAT chunks, CRC validation and bounded decompression. It
rejects palette/grayscale/16-bit/interlaced PNGs, tRNS transparency, animation,
unknown critical chunks, malformed streams and trailing data. Unsupported files
must be explicitly converted outside this module; there is no hidden fallback.

Regions and ignore masks use absolute image-pixel coordinates. Overlapping masks
count once. Differences are computed only over the image intersection/crop;
unequal image dimensions are explicitly `partial`. Alpha is ignored, matching
legacy RGB semantics. A pixel changes only when its RGB-distance sum is strictly
greater than `threshold`. `changed` is true only when the unrounded changed
fraction exceeds 0.001. A wholly masked comparison is `partial` and inconclusive.
A pixel change does not prove that the user's task succeeded.

## Resource limits and validation

Invalid inputs or exceeded budgets raise `ValueError`; the caller should return
an error, not run another provider or select a partial best candidate.

- OCR source plus generated candidates: 10,000 processed items and 262,144 text
  characters; individual strings and normalized strings at most 4,096 characters
- Fuzzy matching: at most 10,000,000 edit-distance cells per request
- OCR result limit: 1–1,000; fusion limit: 1–100 (the host can impose lower limits)
- UIA input: 10,000 nodes and 64 levels; cyclic or repeated-node graph objects
  are rejected, and parent climbing is limited to six edges
- PNG input: 64 MiB, 10,000 chunks, at most 10,000 pixels per dimension and
  16,777,216 total pixels; decompressed length must exactly match the header
- Pixel diff: at most 64 ignore rectangles and an integer RGB threshold 0–765

## Verification and remaining work

Run fixture tests without a desktop:

```text
python -m unittest discover -s tests/python -p test_observation_processing.py -v
```

Tests cover legacy scores, Korean/full-width normalization, n-grams, bounds,
ambiguity under limiting, coordinate translation/scaling, target mismatch,
parent climbing, cycles, all PNG filters, CRC/deflate corruption, decompression
limits, crop/mask semantics and alpha behavior.

These deterministic fixtures do not establish Windows OCR recognition quality,
real UIA parent/pattern correctness, mixed-DPI desktop behavior, IME behavior,
or application compatibility. Those require separate authorized Windows
verification. No GUI verification is claimed by this migration.
