/// <summary>Pure bounded contract; PNGs never traverse the native request frame.</summary>
internal sealed record OcrWindowRequest(int MaximumWidth, int MaximumHeight, string? Language)
{
    internal static OcrWindowRequest Parse(CommandOptions options)
    {
        options.Allow("--hwnd", "--pid", "--max-width", "--max-height", "--language",
            "--expected-x", "--expected-y", "--expected-width", "--expected-height");
        var width = options.Integer("--max-width", 1600, 64, 4096);
        var height = options.Integer("--max-height", 1000, 64, 4096);
        var language = options.Get("--language");
        if (language is not null && (language.Length is < 2 or > 64 ||
            language.Split('-').Any(part => part.Length == 0 || part.Any(c => !char.IsAsciiLetterOrDigit(c)))))
            throw CommandOptions.Invalid("Language must be a bounded BCP-47 language tag.");
        return new(width, height, language);
    }

    internal static void ValidateBitmap(uint width, uint height, uint engineMaximum)
    {
        if (width == 0 || height == 0 || width > engineMaximum || height > engineMaximum || (long)width * height > 4_000_000)
            throw new NativeFailure("ocr_image_too_large", "OCR image exceeds the recognizer or four-megapixel limit; request smaller dimensions.");
    }
}
