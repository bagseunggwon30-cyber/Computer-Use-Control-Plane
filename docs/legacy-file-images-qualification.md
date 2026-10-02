# File images and OCR qualification candidate

This candidate owns only supplied image files and managed OCR conversion. It does
not capture screens, inspect UI Automation, move input, use the clipboard/IME,
call a model, or read real user images. The original production functions remain
in `scripts/cucp-native-helper.ps1` until the actual adapter gates pass.

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
adapter preserves their names, parameter types, script engine/error/cache fields,
raw WinRT return objects, and exception messages. These functions must stay
retained if their helper-level gates fail even when file-action JSON passes.
The existing `_Emit` retains timing and action insertion. Its body also exactly
matches the pinned baseline; the fixture supplies a fixed `Get-Date` seam and
asserts the real emitter's `elapsed_ms = 125`, action and output formatting.

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
55-case Windows qualification. The new draft routes all 55 through the actual
function and original emitter as an additional gate.

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
Before promotion, both suites require the exact draft at
`tests/fixtures/legacy-file-images-adapter.ps1`. Its loader honors
`CUCP_LEGACY_IMAGES_DLL` and defaults to the existing package location. The
integrator owns manifest/workflow/package changes, source retirement, final source
accounting and the bundled full regression. Draft bytes are counted until removed.

## Evidence status

On the dot Linux computer, the new net48 DLL builds with zero warnings/errors,
the 47 managed contracts pass, and three Python source contracts pass. Windows
parity and OS recognition are **pending**. New adapter coverage is not yet a
retirement result, and no net PowerShell reduction is claimed.
