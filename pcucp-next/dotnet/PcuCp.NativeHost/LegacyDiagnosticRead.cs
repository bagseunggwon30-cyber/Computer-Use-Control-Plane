using System.Diagnostics;
using System.Text.Json;
using System.Windows.Automation;
using Windows.Media.Ocr;

/// <summary>Read-only acquisitions. Ordinals refer to two owned process snapshots.</summary>
internal static class LegacyDiagnosticRead
{
    private static readonly List<Process[]> Snapshots = [];
    internal static NativeResult Execute(CommandOptions options)
    {
        string? operation = options.Get("--operation");
        if (operation == "uia-affordances") options.Allow("--operation", "--focused-window", "--max-elements", "--min-size", "--hwnd");
        else if (operation == "hit-test-point") options.Allow("--operation", "--x", "--y", "--target-hwnd", "--target-match");
        else if (operation == "coordinate-snapshot") options.Allow("--operation", "--x", "--y", "--target-hwnd", "--has-point");
        else if (operation == "coordinate-target") options.Allow("--operation", "--target-hwnd");
        else if (operation == "process-metrics") options.Allow("--operation", "--current", "--previous");
        else options.Allow("--operation");
        object? data = options.Get("--operation") switch
        {
            "ensure-win32" => OperatingSystem.IsWindows(), "ensure-uia" => UiaAvailable(),
            "windows" => WrapperWindows(), "processes" => Processes(), "process-metrics" => Metrics(options),
            "uia-affordances" => Affordances(options),
            "hit-test-point" => LegacyCoordinateRead.Hit(options), "coordinate-snapshot" => LegacyCoordinateRead.Snapshot(options),
            "coordinate-target" => LegacyCoordinateRead.Target(options),
            "desktop-size" => new { width = CucpWin32.GetSystemMetrics(0), height = CucpWin32.GetSystemMetrics(1) },
            "native-health" => Health(), "native-windows" => NativeWindows(),
            "native-focused" => Focused(), "native-modal-detect" => Modal(),
            _ => throw CommandOptions.Invalid("Unknown read-only diagnostic acquisition.")
        };
        // Native serve requires an object data envelope; the legacy effect
        // value may itself be a Boolean, array, or object.
        return NativeResult.Ok("legacy-diagnostic-read", new { value = data });
    }
    private static object Affordances(CommandOptions options)
    {
        int maximum = LegacyTaskFormKernel.LegacyInt(options.Get("--max-elements") ?? "400");
        int minimum = LegacyTaskFormKernel.LegacyInt(options.Get("--min-size") ?? "6");
        if (!long.TryParse(options.Get("--hwnd") ?? "0", out long hwnd) || maximum > 20000 || minimum < 0)
            throw CommandOptions.Invalid("Invalid affordance acquisition bounds.");
        return LegacyAffordances.Read(options.Get("--focused-window") ?? "", maximum, minimum, hwnd);
    }
    private static bool UiaAvailable()
    {
        try { return typeof(AutomationElement).Assembly is not null; } catch { return false; }
    }
    private static object Windows()
    {
        return CucpNative.EnumerateTopLevel().Select(w => new Dictionary<string, object?>
        {
            ["hwnd"] = w.Hwnd.ToInt64(), ["title"] = w.Title, ["class"] = w.ClassName, ["pid"] = (int)w.Pid,
            ["process"] = w.ProcessName, ["visible"] = w.Visible, ["minimized"] = w.Minimized, ["foreground"] = w.Foreground,
            ["rect"] = new { x = w.X, y = w.Y, width = w.Width, height = w.Height }
        }).ToArray();
    }
    private static object WrapperWindows()
    {
        return CucpWin32.EnumerateTopLevel().Select(w => new Dictionary<string, object?>
        {
            ["hwnd"] = w.Hwnd.ToInt64(), ["title"] = w.Title, ["class"] = w.ClassName, ["pid"] = (int)w.Pid,
            ["process"] = w.ProcessName, ["visible"] = w.Visible, ["minimized"] = w.Minimized, ["foreground"] = w.Foreground,
            ["rect"] = new { x = w.X, y = w.Y, width = w.Width, height = w.Height }
        }).ToArray();
    }
    private static object Health()
    {
        string? error = null, language = null;
        string[] languages = [];
        bool ocr = false;
        try
        {
            languages = OcrEngine.AvailableRecognizerLanguages.Select(value => value.LanguageTag).ToArray();
            var engine = OcrEngine.TryCreateFromUserProfileLanguages();
            ocr = engine is not null; language = engine?.RecognizerLanguage.LanguageTag;
            if (!ocr) error = "no_ocr_language_available";
        }
        catch (Exception exception) { error = exception.Message; }
        return new { status = "ok", win32 = true, uia = UiaAvailable(), ocr, ocr_languages = languages,
            ocr_engine_language = language, ocr_error = error, psversion = (string?)null,
            runtime = "dotnet", pid = Environment.ProcessId };
    }
    private static object NativeWindows()
    {
        var windows = (Dictionary<string, object?>[])Windows();
        return new { status = "ok", match = "", windows, count = windows.Length };
    }
    private static object Focused()
    {
        var value = CucpNative.EnumerateTopLevel().FirstOrDefault(window => window.Foreground);
        if (value is null) return new { status = "partial", reason = "no_foreground_window" };
        return new { status = "ok", foreground = new Dictionary<string, object?>
        {
            ["hwnd"] = value.Hwnd.ToInt64(), ["title"] = value.Title, ["class"] = value.ClassName,
            ["pid"] = (int)value.Pid, ["process"] = value.ProcessName,
            ["rect"] = new { x = value.X, y = value.Y, width = value.Width, height = value.Height }
        }};
    }
    private static object Modal()
    {
        var candidates = new List<Dictionary<string, object?>>();
        object? foreground = null;
        try
        {
            var windows = AutomationElement.RootElement.FindAll(TreeScope.Children, Condition.TrueCondition);
            foreach (AutomationElement element in windows)
            {
                try
                {
                    var current = element.Current;
                    var rect = current.BoundingRectangle;
                    bool modal = element.TryGetCurrentPattern(WindowPattern.Pattern, out var pattern) && ((WindowPattern)pattern).Current.IsModal;
                    string? reason = modal ? "uia_window_is_modal" : null;
                    int score = modal ? 100 : 0;
                    if (System.Text.RegularExpressions.Regex.IsMatch(current.ClassName, "#32770|MessageBox|Dialog|TaskDialog|Popup", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                    { score += 60; reason ??= "dialog_class_name"; }
                    if (!rect.IsEmpty && rect.Width > 0 && rect.Width < 900 && rect.Height > 0 && rect.Height < 600)
                    { score += 20; reason ??= "small_window_size"; }
                    if (score > 0) candidates.Add(new Dictionary<string, object?>
                    {
                        ["hwnd"] = current.NativeWindowHandle, ["title"] = current.Name, ["class"] = current.ClassName,
                        ["role"] = current.LocalizedControlType, ["rect"] = new { x = (int)Math.Round(rect.X), y = (int)Math.Round(rect.Y), w = (int)Math.Round(rect.Width), h = (int)Math.Round(rect.Height) },
                        ["score"] = score, ["reason"] = reason, ["is_modal"] = modal
                    });
                }
                catch { }
            }
        }
        catch { }
        try
        {
            var hwnd = CucpNative.GetForegroundWindow();
            var title = new System.Text.StringBuilder(512);
            var className = new System.Text.StringBuilder(256);
            CucpNative.GetWindowText(hwnd, title, title.Capacity);
            CucpNative.GetClassName(hwnd, className, className.Capacity);
            foreground = new Dictionary<string, object?>
            {
                ["hwnd"] = checked((int)hwnd.ToInt64()), ["title"] = title.ToString(), ["class"] = className.ToString()
            };
        }
        catch { }
        var sorted = candidates.OrderByDescending(value => (int)value["score"]!).ToArray();
        string recommendation = sorted.Length == 0 ? "observe" : (bool)sorted[0]["is_modal"]! || (int)sorted[0]["score"]! >= 100 ? "dismiss_or_confirm" : (int)sorted[0]["score"]! >= 60 ? "confirm_dialog" : "wait";
        return new { status = "ok", foreground, modal_candidates = sorted, candidate_count = sorted.Length, recommended_action = recommendation };
    }
    private static object Processes()
    {
        if (Snapshots.Count == 2) throw CommandOptions.Invalid("A diagnostic owner can acquire only two process snapshots.");
        Process[] acquired = Process.GetProcesses();
        if (acquired.Length > 16384)
        {
            foreach (var process in acquired) process.Dispose();
            throw CommandOptions.Invalid("Process snapshot exceeds its bounded budget.");
        }
        var rows = new List<object>();
        var retained = new List<Process>();
        foreach (var process in acquired)
        {
            try { rows.Add(new { id = process.Id, name = process.ProcessName }); retained.Add(process); }
            catch { process.Dispose(); }
        }
        Snapshots.Add(retained.ToArray());
        return rows.ToArray();
    }
    private static object Metrics(CommandOptions options)
    {
        if (Snapshots.Count != 2 || !int.TryParse(options.Get("--current"), out int current) || current < 0 || current >= Snapshots[1].Length)
            throw CommandOptions.Invalid("Current process ordinal has no owned snapshot.");
        Process process = Snapshots[1][current];
        Process? previous = null;
        string? raw = options.Get("--previous");
        if (raw is not null)
        {
            if (!int.TryParse(raw, out int index) || index < 0 || index >= Snapshots[0].Length)
                throw CommandOptions.Invalid("Previous process ordinal has no owned snapshot.");
            previous = Snapshots[0][index];
            if (previous.Id != process.Id) throw CommandOptions.Invalid("Process metrics changed the owned PID relationship.");
        }
        var result = new Dictionary<string, object?>();
        try { result["private_bytes"] = process.PrivateMemorySize64; } catch { }
        try { result["started_at"] = process.StartTime.ToString("o"); } catch { }
        try
        {
            if (previous is not null)
            {
                result["current_cpu_ms"] = process.TotalProcessorTime.TotalMilliseconds;
                result["previous_cpu_ms"] = previous.TotalProcessorTime.TotalMilliseconds;
            }
        }
        catch { }
        try { result["priority"] = process.PriorityClass.ToString(); } catch { }
        return result;
    }
    internal static void Close()
    {
        foreach (var snapshot in Snapshots) foreach (var process in snapshot) process.Dispose();
        Snapshots.Clear();
    }
}
