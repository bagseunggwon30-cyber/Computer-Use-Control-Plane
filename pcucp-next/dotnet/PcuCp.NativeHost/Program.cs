using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows.Automation;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage;
using Windows.Storage.Streams;

Console.OutputEncoding = Encoding.UTF8;
var command = args.Length > 0 ? args[0].Trim().ToLowerInvariant() : "version";
var commandArgs = args.Skip(1).ToArray();
var options = new JsonSerializerOptions { WriteIndented = true };

switch (command)
{
    case "version":
        Console.WriteLine(JsonSerializer.Serialize(NativeVersion.Create(), options));
        return 0;
    case "windows":
        Console.WriteLine(JsonSerializer.Serialize(WindowEnumerator.Observe(), options));
        return 0;
    case "uia-tree":
        Console.WriteLine(JsonSerializer.Serialize(UiaTreeObserver.Observe(commandArgs), options));
        return 0;
    case "ocr-image":
        var ocrPayload = await OcrImageObserver.ObserveAsync(commandArgs);
        Console.WriteLine(JsonSerializer.Serialize(ocrPayload, options));
        return ocrPayload.ExitCode;
    default:
        Console.Error.WriteLine($"unknown native host command: {command}");
        return 2;
}

internal static class NativeVersion
{
    public static object Create() => new
    {
        schema = "pcucp.native.version/v1",
        status = "ok",
        component = "PcuCp.NativeHost",
        runtime = RuntimeInformation.FrameworkDescription,
        os = RuntimeInformation.OSDescription,
        process = Environment.ProcessId
    };
}

internal sealed record WindowInfo(
    [property: JsonPropertyName("hwnd")]
    string Hwnd,
    [property: JsonPropertyName("title")]
    string Title,
    [property: JsonPropertyName("process_name")]
    string ProcessName,
    [property: JsonPropertyName("process_id")]
    int ProcessId,
    [property: JsonPropertyName("visible")]
    bool Visible
);

internal sealed record RectInfo(
    [property: JsonPropertyName("x")]
    double X,
    [property: JsonPropertyName("y")]
    double Y,
    [property: JsonPropertyName("width")]
    double Width,
    [property: JsonPropertyName("height")]
    double Height
);

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

    private static OcrImagePayload ConvertResult(string path, OcrEngine engine, OcrResult result)
    {
        var lines = new List<OcrLine>();
        var words = new List<OcrWord>();
        foreach (var line in result.Lines)
        {
            var lineWords = new List<OcrWord>();
            foreach (var word in line.Words)
            {
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

internal sealed record UiaNode(
    [property: JsonPropertyName("name")]
    string Name,
    [property: JsonPropertyName("control_type")]
    string ControlType,
    [property: JsonPropertyName("automation_id")]
    string AutomationId,
    [property: JsonPropertyName("class_name")]
    string ClassName,
    [property: JsonPropertyName("process_id")]
    int ProcessId,
    [property: JsonPropertyName("native_window_handle")]
    string NativeWindowHandle,
    [property: JsonPropertyName("bounding_rectangle")]
    RectInfo? BoundingRectangle,
    [property: JsonPropertyName("patterns")]
    IReadOnlyList<string> Patterns,
    [property: JsonPropertyName("children")]
    IReadOnlyList<UiaNode> Children
);

internal static class UiaTreeObserver
{
    public static object Observe(string[] args)
    {
        if (!OperatingSystem.IsWindows())
        {
            return Error("PcuCp.NativeHost UIA observation requires Windows.");
        }

        var maxDepth = ParseIntOption(args, "--max-depth", 1);
        maxDepth = Math.Clamp(maxDepth, 0, 4);
        var nodes = new List<UiaNode>();
        var errors = new List<string>();

        try
        {
            var root = AutomationElement.RootElement;
            var children = root.FindAll(TreeScope.Children, Condition.TrueCondition);
            foreach (AutomationElement child in children)
            {
                try
                {
                    nodes.Add(ReadNode(child, 0, maxDepth));
                }
                catch (ElementNotAvailableException)
                {
                    errors.Add("Skipped unavailable UIA element.");
                }
                catch (InvalidOperationException ex)
                {
                    errors.Add($"Skipped UIA element: {ex.Message}");
                }
            }
        }
        catch (Exception ex) when (ex is ElementNotAvailableException or InvalidOperationException or COMException)
        {
            errors.Add(ex.Message);
        }

        return new
        {
            schema = "pcucp.uia-tree/v1",
            status = errors.Count == 0 ? "ok" : "partial",
            kind = "uia-tree",
            data = new
            {
                max_depth = maxDepth,
                nodes,
                count = nodes.Count
            },
            errors
        };
    }

    private static object Error(string message) => new
    {
        schema = "pcucp.uia-tree/v1",
        status = "error",
        kind = "uia-tree",
        data = new { max_depth = 0, nodes = Array.Empty<UiaNode>(), count = 0 },
        errors = new[] { message }
    };

    private static UiaNode ReadNode(AutomationElement element, int depth, int maxDepth)
    {
        var current = element.Current;
        var children = new List<UiaNode>();
        if (depth < maxDepth)
        {
            AutomationElementCollection? childElements = null;
            try
            {
                childElements = element.FindAll(TreeScope.Children, Condition.TrueCondition);
            }
            catch
            {
                childElements = null;
            }

            if (childElements is not null)
            {
                foreach (AutomationElement child in childElements)
                {
                    try
                    {
                        children.Add(ReadNode(child, depth + 1, maxDepth));
                    }
                    catch (ElementNotAvailableException)
                    {
                        // UIA trees are volatile. Skip disappeared nodes.
                    }
                }
            }
        }

        return new UiaNode(
            SafeString(() => current.Name),
            SafeString(() => current.ControlType.ProgrammaticName.Replace("ControlType.", "", StringComparison.Ordinal)),
            SafeString(() => current.AutomationId),
            SafeString(() => current.ClassName),
            SafeInt(() => current.ProcessId),
            $"0x{SafeInt(() => current.NativeWindowHandle):X}",
            RectFrom(current.BoundingRectangle),
            SupportedPatterns(element),
            children
        );
    }

    private static IReadOnlyList<string> SupportedPatterns(AutomationElement element)
    {
        try
        {
            return element.GetSupportedPatterns()
                .Select(pattern => CleanPatternName(pattern.ProgrammaticName))
                .Where(name => !string.IsNullOrWhiteSpace(name))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                .ToArray();
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    private static string CleanPatternName(string programmaticName)
    {
        if (string.IsNullOrWhiteSpace(programmaticName))
        {
            return string.Empty;
        }
        var name = programmaticName
            .Replace("PatternIdentifiers.Pattern", "", StringComparison.Ordinal)
            .Replace("Pattern.Pattern", "", StringComparison.Ordinal)
            .Replace("Identifiers.Pattern", "", StringComparison.Ordinal)
            .Replace("Pattern", "", StringComparison.Ordinal)
            .Replace(".", "", StringComparison.Ordinal);
        return name.Trim();
    }

    private static RectInfo? RectFrom(System.Windows.Rect rect)
    {
        if (rect.IsEmpty)
        {
            return null;
        }
        return new RectInfo(rect.X, rect.Y, rect.Width, rect.Height);
    }

    private static string SafeString(Func<string> read)
    {
        try { return read() ?? string.Empty; }
        catch { return string.Empty; }
    }

    private static int SafeInt(Func<int> read)
    {
        try { return read(); }
        catch { return 0; }
    }

    private static int ParseIntOption(string[] args, string name, int defaultValue)
    {
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase) &&
                int.TryParse(args[i + 1], out var value))
            {
                return value;
            }
        }
        return defaultValue;
    }
}

internal static class WindowEnumerator
{
    public static object Observe()
    {
        if (!OperatingSystem.IsWindows())
        {
            return new
            {
                schema = "pcucp.observation/v1",
                status = "error",
                kind = "windows",
                data = new { windows = Array.Empty<WindowInfo>() },
                errors = new[] { "PcuCp.NativeHost window enumeration requires Windows." }
            };
        }

        var windows = new List<WindowInfo>();
        EnumWindows((hwnd, _) =>
        {
            var visible = IsWindowVisible(hwnd);
            var title = GetWindowTitle(hwnd);
            if (!visible || string.IsNullOrWhiteSpace(title))
            {
                return true;
            }

            GetWindowThreadProcessId(hwnd, out var pid);
            windows.Add(new WindowInfo(
                $"0x{hwnd.ToInt64():X}",
                title,
                GetProcessName(pid),
                (int)pid,
                visible
            ));
            return true;
        }, IntPtr.Zero);

        return new
        {
            schema = "pcucp.observation/v1",
            status = "ok",
            kind = "windows",
            data = new
            {
                windows,
                count = windows.Count
            },
            errors = Array.Empty<string>()
        };
    }

    private static string GetWindowTitle(IntPtr hwnd)
    {
        var length = GetWindowTextLength(hwnd);
        if (length <= 0)
        {
            return string.Empty;
        }

        var builder = new StringBuilder(length + 1);
        _ = GetWindowText(hwnd, builder, builder.Capacity);
        return builder.ToString();
    }

    private static string GetProcessName(uint pid)
    {
        try
        {
            using var process = Process.GetProcessById((int)pid);
            return process.ProcessName;
        }
        catch
        {
            return string.Empty;
        }
    }

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
}
