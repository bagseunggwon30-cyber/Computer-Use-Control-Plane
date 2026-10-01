# Legacy image comparison qualification candidate

`PcuCp.LegacyImages` is an independent net48/AnyCPU assembly. It does not change
the separate legacy Win32 interop assembly's public API. Build it with
`python pcucp-next/packaging/publish_legacy_images.py`.

`ScreenshotDiff.Compare(before, after, x, y, width, height, threshold, ignoreRegions)`
returns `DiffResult { ExitCode, Data }`. Data has the legacy ordered result fields.
The future adapter supplies action/elapsed metadata and invokes the existing emitter.
No GUI acquisition or input is present. The method reads only explicitly supplied
paths, does not write images, and disposes both image decoders in finally.

The candidate deliberately retains .NET Framework System.Drawing.FromFile and
32bpp ARGB LockBits rather than narrowing the existing decoder to PNG. The RGB
sum excludes alpha; change uses strict greater-than threshold and ratio > .001
before six-place ToEven rounding. Mask overlaps count once. The legacy first
image stride is reused for both arrays, including PowerShell negative array-index
semantics. This behavior is not claimed safe or repaired without separate evidence.

The original 5,556-byte/135-line PowerShell algorithm remains authoritative until
Windows differential qualification passes. Generated PNG, BMP, JPEG, GIF, TIFF,
crops, dimensions, masks, thresholds, alpha, corrupt/missing/directory inputs and
full error envelopes are compared against the pinned original function. Tests
use temporary fixtures only. No real screenshots or user images are inspected.

Run with CUCP_LEGACY_IMAGES_TEST_DLL pointing to the compiled DLL:
`python -m unittest discover -s tests/python -p test_legacy_images.py -v`.
PowerShell integer conversion and localized invocation error strings remain
explicit parity risks; do not retire the old body on a build-only result.

Initial Windows qualification on 2687ec4/job110497834309 passed 36 of 37
complete comparisons, including all decoder formats and error envelopes. The
sole failure was a decimal mask coordinate: PS accepts "1.5" and rounds to 2.
The candidate now falls back from integer syntax to invariant double parsing
and ToEven conversion, with additional half-rounding/exponent/overflow-boundary
fixtures. Mask intermediate arithmetic uses Int64 to preserve PS promotion.
Requalification is required before retirement.

The 55-case matrix also includes whitespace, signed integers, signed/uppercase
hex, `1kb`, NaN/Infinity and the immediate Int32 boundaries. These are exact
differential probes, not claims that every form is accepted. Candidate failures
remain failures until their full envelopes agree with the pinned PS baseline.
