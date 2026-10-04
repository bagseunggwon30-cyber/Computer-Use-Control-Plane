using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage.Streams;

internal static class OcrWindowObserver
{
    internal static async Task<NativeResult> ObserveAsync(CommandOptions options)
    {
        var request = OcrWindowRequest.Parse(options);
        var target = WindowTarget.Read(options, false);
        var screenshot = ScreenshotObserver.CaptureWindow(target, request.MaximumWidth, request.MaximumHeight);
        // This is exactly the PNG returned to the caller, not a recapture or saved file.
        using var stream = new InMemoryRandomAccessStream();
        using (var writer = new DataWriter(stream))
        {
            writer.WriteBytes(Convert.FromBase64String(screenshot.Image.Data));
            await writer.StoreAsync();
            await writer.FlushAsync();
            writer.DetachStream();
        }
        stream.Seek(0);
        var decoder = await BitmapDecoder.CreateAsync(stream);
        OcrWindowRequest.ValidateBitmap(decoder.PixelWidth, decoder.PixelHeight, OcrEngine.MaxImageDimension);
        var engine = CreateEngine(request.Language);
        using var bitmap = await decoder.GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Ignore);
        var recognized = await engine.RecognizeAsync(bitmap);
        // Slow OCR must not return a fresh-looking observation for a moved/replaced target.
        target.Validate(false);
        if (screenshot.WindowGeometry != target.Rect())
            throw new NativeFailure("geometry_changed", "Window moved during OCR; capture a fresh observation.");
        var payload = OcrImageObserver.ConvertResult(string.Empty, engine, recognized, maxWords: 10000, maxCharacters: 262144);
        return NativeResult.Ok("ocr-window", new
        {
            image = screenshot.Image, target = screenshot.Target, geometry = screenshot.Geometry,
            window_geometry = screenshot.WindowGeometry, captured_at = screenshot.CapturedAt,
            coordinate_space = screenshot.CoordinateSpace, capture_semantics = screenshot.CaptureSemantics,
            target_foreground = screenshot.TargetForeground, cursor_included = screenshot.CursorIncluded,
            ocr = new { text = payload.Text, lines = payload.Lines, words = payload.Words,
                line_count = payload.LineCount, word_count = payload.WordCount, engine_language = payload.EngineLanguage,
                coordinate_space = "image_pixels", source = "returned_capture", recognition_semantics = "text_estimate_not_authoritative" }
        });
    }

    private static OcrEngine CreateEngine(string? language)
    {
        if (language is not null)
        {
            try
            {
                return OcrEngine.TryCreateFromLanguage(new Windows.Globalization.Language(language)) ??
                    throw new NativeFailure("ocr_language_unavailable", "Requested OCR language is not installed or supported.");
            }
            catch (ArgumentException) { throw new NativeFailure("ocr_language_unavailable", "Requested OCR language tag is invalid."); }
        }
        var engine = OcrEngine.TryCreateFromUserProfileLanguages();
        if (engine is not null) return engine;
        var languages = OcrEngine.AvailableRecognizerLanguages;
        return (languages.Count > 0 ? OcrEngine.TryCreateFromLanguage(languages[0]) : null) ??
            throw new NativeFailure("ocr_unavailable", "No installed OCR language is available.");
    }
}
