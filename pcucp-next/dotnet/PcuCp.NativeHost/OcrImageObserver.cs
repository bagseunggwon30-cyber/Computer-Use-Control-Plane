using System.IO;
using System.Text.Json.Serialization;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage;
using Windows.Storage.Streams;

internal sealed record OcrWord(
    [property: JsonPropertyName("text")]
    string Text,
    [property: JsonPropertyName("x")]
    double X,
    [property: JsonPropertyName("y")]
    double Y,
    [property: JsonPropertyName("width")]
    double Width,
    [property: JsonPropertyName("height")]
    double Height,
    [property: JsonPropertyName("cx")]
    double CenterX,
    [property: JsonPropertyName("cy")]
    double CenterY
);

internal sealed record OcrLine(
    [property: JsonPropertyName("text")]
    string Text,
    [property: JsonPropertyName("words")]
    IReadOnlyList<OcrWord> Words
);

internal sealed record OcrImagePayload(
    [property: JsonIgnore]
    int ExitCode,
    [property: JsonPropertyName("schema")]
    string Schema,
    [property: JsonPropertyName("status")]
    string Status,
    [property: JsonPropertyName("kind")]
    string Kind,
    [property: JsonPropertyName("source")]
    string Source,
    [property: JsonPropertyName("ocr_path")]
    string OcrPath,
    [property: JsonPropertyName("engine_language")]
    string? EngineLanguage,
    [property: JsonPropertyName("text")]
    string Text,
    [property: JsonPropertyName("line_count")]
    int LineCount,
    [property: JsonPropertyName("word_count")]
    int WordCount,
    [property: JsonPropertyName("lines")]
    IReadOnlyList<OcrLine> Lines,
    [property: JsonPropertyName("words")]
    IReadOnlyList<OcrWord> Words,
    [property: JsonPropertyName("errors")]
    IReadOnlyList<string> Errors
);

internal static class OcrImageObserver
{
    public static async Task<OcrImagePayload> ObserveAsync(string[] args)
    {
        var path = ReadOption(args, "--path") ?? ReadOption(args, "-path");
        var language = ReadOption(args, "--language") ?? ReadOption(args, "-language");
        if (string.IsNullOrWhiteSpace(path))
        {
            return Error("missing_ocr_path", string.Empty);
        }
        if (!File.Exists(path))
        {
            return Error("ocr_path_not_found", path);
        }
        if (!OperatingSystem.IsWindows())
        {
            return Error("PcuCp.NativeHost OCR requires Windows.", path);
        }

        try
        {
            var engine = CreateEngine(language);
            if (engine is null)
            {
                return Error("ocr_unavailable:no_ocr_language_available", path);
            }

            var file = await StorageFile.GetFileFromPathAsync(Path.GetFullPath(path));
            using IRandomAccessStream stream = await file.OpenAsync(FileAccessMode.Read);
            var decoder = await BitmapDecoder.CreateAsync(stream);
            using var bitmap = await decoder.GetSoftwareBitmapAsync();
            var result = await engine.RecognizeAsync(bitmap);
            return ConvertResult(path, engine, result);
        }
        catch (Exception ex)
        {
            return Error($"ocr_failed:{ex.Message}", path);
        }
    }

    private static OcrEngine? CreateEngine(string? language)
    {
        if (!string.IsNullOrWhiteSpace(language))
        {
            try
            {
                var requested = new Windows.Globalization.Language(language);
                var explicitEngine = OcrEngine.TryCreateFromLanguage(requested);
                if (explicitEngine is not null)
                {
                    return explicitEngine;
                }
            }
            catch
            {
                // Fall through to user profile languages.
            }
        }

        var engine = OcrEngine.TryCreateFromUserProfileLanguages();
        if (engine is not null)
        {
            return engine;
        }
        var languages = OcrEngine.AvailableRecognizerLanguages;
        return languages.Count > 0 ? OcrEngine.TryCreateFromLanguage(languages[0]) : null;
    }

    internal static OcrImagePayload ConvertResult(string path, OcrEngine engine, OcrResult result, int maxWords = int.MaxValue, int maxCharacters = int.MaxValue)
    {
        var lines = new List<OcrLine>();
        var words = new List<OcrWord>();
        long characters = 0;
        foreach (var line in result.Lines)
        {
            characters += line.Text.Length;
            if (characters > maxCharacters || lines.Count >= maxWords)
                throw new NativeFailure("ocr_result_too_large", "OCR result exceeds the bounded text/line budget.");
            var lineWords = new List<OcrWord>();
            foreach (var word in line.Words)
            {
                if (words.Count >= maxWords)
                    throw new NativeFailure("ocr_result_too_large", "OCR result exceeds the bounded word budget.");
                var rect = word.BoundingRect;
                var item = new OcrWord(
                    word.Text,
                    rect.X,
                    rect.Y,
                    rect.Width,
                    rect.Height,
                    rect.X + rect.Width / 2,
                    rect.Y + rect.Height / 2
                );
                lineWords.Add(item);
                words.Add(item);
            }
            lines.Add(new OcrLine(line.Text, lineWords));
        }

        return new OcrImagePayload(
            0,
            "pcucp.ocr-image/v1",
            "ok",
            "ocr-image",
            "image",
            path,
            engine.RecognizerLanguage.LanguageTag,
            string.Join(Environment.NewLine, lines.Select(line => line.Text)),
            lines.Count,
            words.Count,
            lines,
            words,
            Array.Empty<string>()
        );
    }

    private static OcrImagePayload Error(string message, string path) => new(
        1,
        "pcucp.ocr-image/v1",
        "error",
        "ocr-image",
        "image",
        path,
        null,
        string.Empty,
        0,
        0,
        Array.Empty<OcrLine>(),
        Array.Empty<OcrWord>(),
        new[] { message }
    );

    private static string? ReadOption(string[] args, string name)
    {
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[i + 1];
            }
        }
        return null;
    }
}
