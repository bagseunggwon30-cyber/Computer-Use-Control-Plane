# File images and OCR qualification candidate

This candidate owns only supplied image files and managed OCR conversion. It does
not capture screens, inspect UI Automation, move input, use the clipboard/IME,
call a model, or read real user images. The six qualified delegates are now integrated in
`scripts/cucp-native-helper.ps1`; the duplicate draft was removed after the
Windows candidate and actual-adapter gate passed. The integrated full regression
is still pending.

## Exact source boundary

The six function bodies total **10,814 UTF-8 bytes**, excluding surrounding
comments and separators. Their normalized bodies are unchanged from the pinned
`bf895d3120dd5e145f360cb1c41e1d79a061d048` baseline at accepted checkpoint
`56be343c786027d27fa3dcb71732157caffc8de0` (local equivalent `d78ea2bd`).

| Function | Original bytes | Candidate boundary |
| --- | ---: | --- |
| `_Action-ScreenshotDiff` | 5,556 | Existing `ScreenshotDiff.Compare` |
| `_Ensure-OCR` | 1,907 | `FileOcrSession.Ensure`, retaining script state |
| `_Wait-AsyncOp` | 387 | `FileOcr.TryWaitAsyncOperation` |
| `_Load-SoftwareBitmapFromFile` | 563 | `FileOcr.TryLoadSoftwareBitmapFromFile` |
| `_Convert-OcrResult` | 1,396 | `FileOcr.ConvertResult` |
| `_Action-OcrImage` | 1,005 | Path validation, engine ensure, `RecognizeFile` |

The four shared helpers still serve retained screen and fusion callers. The
integrated adapter preserves their names, parameter types, script engine/error/cache fields,
raw WinRT return objects, and exception messages. Their direct helper-level gates passed alongside the file-action JSON gates.
The existing `_Emit` retains timing and action insertion. Its body also exactly
matches the pinned baseline; the fixture supplies a fixed `Get-Date` seam and
asserts the real emitter's `elapsed_ms = 125`, action and output formatting.
The baseline loads `_Emit` from the pinned original; the candidate now loads it
from the current production helper so a later emitter change cannot escape the gate.

## Implementation and compatibility

The existing net48/AnyCPU `PcuCp.LegacyImages` DLL and publisher are reused.
`FileOcr.cs` contains an ordered converter, once-only session and file-only WinRT
backend. It contains no PowerShell dependency, interpreter, subprocess, bridge,
network or desktop API. Reflection resolves the .NET Framework WinRT projections
used by the legacy helper; synchronous waits preserve the legacy `AsTask`,
reflection `Invoke`, and `Task.Wait` exception boundaries. Operation-result
wrappers let the thin adapters rethrow the original detail without adding a new
PowerShell static-method invocation wrapper.

The modern `OcrImageObserver` has useful WinRT acquisition sequencing, but its
output schema, newline construction, rectangle/center rounding and fallback
whitespace behavior differ. Sharing that observer directly would change the
legacy interface. This candidate preserves the same underlying OS decoder and
recognizer API while keeping the compatibility conversion separate.

Specific preserved behavior includes:

- Explicit nonempty language first; failed/invalid explicit selection falls back
  to profile languages, then the first available recognizer; profile exceptions
  stop selection and are cached
- Both successful and failed engine initialization are cached, including the
  original script engine object reused by retained callers
- `Test-Path`-style file/directory distinction; supplied paths stay verbatim and
  relative paths are not normalized into previously accepted absolute paths
- Original `OcrResult.Text`, line/word order, omission of wordless lines, ordered
  dictionary fields and Unicode content
- Rectangle components rounded individually with ToEven before offsets; odd
  centers round before addition; integer overflow promotes as in the legacy
  arithmetic; negative bounds retain the original zero-initialized maximum
- `ocr_unavailable`, `ocr_failed`, path errors and full detail fields
- Software bitmap and input stream ownership now ends after their completed use;
  fixture-owned bitmap return values remain live until their caller disposes them

The existing screenshot-diff kernel remains unchanged: System.Drawing decoder
formats, strict threshold, masking, rounding and full errors keep their existing
55-case Windows qualification. The additional 55 cases route through the selected actual
function and current production emitter.

## Finite gates and commands

Local cross-platform gates:

```
dotnet run --project pcucp-next/dotnet/PcuCp.LegacyFileOcr.ContractTests -c Release
dotnet build pcucp-next/dotnet/PcuCp.LegacyImages -c Release
python -m unittest discover -s tests/python -p test_legacy_images.py -v
python -m unittest discover -s tests/python -p test_legacy_file_ocr.py -v
```

The new pure project currently has 47 assertions covering conversion, ordering,
rounding, overflow, negative-bound quirks, fake backend query order and cached
errors, validation before loading, failure details, and disposable owned data.
It does not call an OS OCR engine.

Windows gate setup reuses the existing publisher and environment variable:

```
python pcucp-next/packaging/publish_legacy_images.py
$env:CUCP_LEGACY_IMAGES_TEST_DLL = (Resolve-Path 'pcucp-next/bin/legacy/PcuCp.LegacyImages.dll').Path
python -m unittest discover -s tests/python -p test_legacy_images.py -v
python -m unittest discover -s tests/python -p test_legacy_file_ocr.py -v
```

There are 167 exact baseline comparisons: 55 diff kernel, 55 diff actual adapter,
11 captured conversions, 3 actual asynchronous waits, 6 actual engine
selection/projection/cache cases, 16 generated-file action cases, 15 direct
bitmap-load cases, one direct load/recognize/convert projection chain, and 5
language-specific action cases. Images are generated
PNG, BMP, JPEG, GIF and TIFF with owned text/blank content, plus Unicode paths,
corrupt data, directory/missing/empty paths and a relative-path probe. Waits cover
success, failure and cancellation. Direct helper checks compare bitmap type,
size, pixel/alpha formats, raw OCR-result type and engine identity/cache fields. Complete dictionaries
and exit codes are compared on every result; ordered successful console output
is compared byte for byte. No arbitrary error detail or output field is removed.

Installed recognizer languages and selected engine language are printed as
explicit evidence. An unavailable engine yields the original unavailable error;
it does not become a fabricated OCR success or a GUI validation claim. Language
selection cases explicitly request English, Korean, an unavailable language, an
invalid tag and whitespace, without installing language packs.

The manifest token `file-images` selects the promoted production functions.
Both suites accept one explicit `CUCP_LEGACY_IMAGES_ADAPTER_SOURCE` override;
without it, the manifest controls source selection. A selected missing source
fails explicitly. The former qualification-only draft is now deleted. The
production loader honors `CUCP_LEGACY_IMAGES_DLL` and defaults to the existing
package location. The integrator owns manifest/workflow/package changes, final
source accounting and the bundled full regression.

## Evidence status

The corrected checkpoint `d8bde03dfa1f1c2b0ab576041521786d1ae62573` passed all
167 exact Windows comparisons and 47 managed contracts in
[run 37048150884](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37048150884),
job `110974667863`. The runner had `en-US` installed. Each owned text image in
PNG, BMP, JPEG, GIF and TIFF, plus the Unicode-path PNG, returned one recognized
line; the five blank images returned zero lines. Korean was not installed: its
request verified fallback to English, not Korean recognition. Cached engine
identity, raw bitmap/OCR-result projections and wait success/fault/cancellation
also matched. This is file-only evidence and proves no screen, input or IME flow.

The preceding `6fc7c882` / run `37037485035` already passed the 110 diff cases
and conversion/generated-file comparisons, but two fixture variable collisions
prevented the complete OCR gate. Distinct fixture variable names repaired it
without changing any runtime/adapter body or removing any assertion.

## Qualified production cutover

The cutover used the successful run's parser-derived UTF-16 ranges. Every whole
source hash and function hash was verified, ranges were converted to UTF-8 byte
positions, and the exact draft extents were spliced into production. The UTF-8
BOM, all surrounding bytes, and the retained `_Emit` body were preserved.

| Source measurement | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| `scripts/cucp-native-helper.ps1` | 122,475 | 113,988 | 8,487 |
| Duplicate qualification draft | 2,411 | 0 | 2,411 |
| Combined family PowerShell bytes | 124,886 | 113,988 | 10,898 |

The six original bodies total 10,814 bytes; the six qualified delegates total
1,863 bytes. The inserted loader is 462 bytes plus two separator bytes. These
are integrated source measurements, pending the bundled full regression and the
integrator's canonical inventory update.

The qualified original helper's normalized SHA-256 is
`719ee14802942bea2acaab3ea5a40ed5e718dacaa8f15ad7405544e93cf42032`;
the qualified draft's is
`fcb1b34c3de4f52a5f10a9040b0702868eff69e000c8f8ec42a7090bdf0f3949`.
The promoted helper's normalized SHA-256 is
`77400e269a26f3616deaf3f9c5b8c33e400246baa37f6b41c4cf0f1ea5f098e6`.
The unchanged `_Emit` body hashes to
`c7ff0c54e52cbadf957bce91bac03ffb47ca790fd8bd0d16b4d1867d5c30c311`.

| Copied delegate | SHA-256 of exact qualified body |
| --- | --- |
| `_Ensure-OCR` | `153e7f1724a2b109ea69f090b486f69a519eb8bbba10dd3515b67687dfd8d5db` |
| `_Wait-AsyncOp` | `6ca99bf69e734959bbee3013755cbf6e820fd31bc50e3c0b0f5336f58ab467b2` |
| `_Load-SoftwareBitmapFromFile` | `0f03e03b140f21231b036ddf1ebd292f15e5a3fccc831ee854f945311e8b2b9c` |
| `_Convert-OcrResult` | `b93836e1aef5f6cb2e13465dcd1c3bdf487d8d5af60046c92554e53a7bc40b82` |
| `_Action-OcrImage` | `3ae3cbdbdee476cab2db54f6c5eb48e52ac0c943940a84255bbc4dc70f47b3d5` |
| `_Action-ScreenshotDiff` | `1dd04987765f863f64a9695a42eb18a359e3214aa3bed50786380f118417918e` |

All 167 differential comparisons and 47 managed checks remain. Four local Python
source checks pass with the explicit production-source override; compiled
runtime sources are unchanged from the qualified checkpoint. The production
cutover still requires its integrated Windows/full-regression gate.
