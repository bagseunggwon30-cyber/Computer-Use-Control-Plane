using System.Text.Json;

/// <summary>Pure legacy coordinate mapping over an already captured desktop/window snapshot.</summary>
internal static class LegacyCoordinateKernel
{
    private sealed record Rect(int X, int Y, int Width, int Height)
    {
        internal long Right => (long)X + Width;
        internal long Bottom => (long)Y + Height;
        internal object Json => new { x = X, y = Y, width = Width, height = Height };
    }
    private sealed record Point(int X, int Y)
    {
        internal object Json => new { x = X, y = Y };
    }
    private static readonly string[] Modes = ["screen", "window", "visible-window", "normalized", "visible-normalized"];
    internal static object BatchPoints(JsonElement args)
    {
        var fields = args.EnumerateObject().Select(p => p.Name).ToArray();
        if (fields.Length != 2 || fields.Distinct(StringComparer.Ordinal).Count() != 2 ||
            fields.Any(p => p is not ("points" or "maximum")) || !args.TryGetProperty("points", out var points) ||
            points.ValueKind != JsonValueKind.Array || points.EnumerateArray().Any(p => p.ValueKind != JsonValueKind.String))
            throw CommandOptions.Invalid("Invalid captured point specifications.");
        int maximum = Integer(args, "maximum"); if (maximum <= 0) maximum = 200;
        if (points.GetArrayLength() == 0) throw CommandOptions.Invalid("macro hit-test-batch requires --point \"x,y\" or --points \"x,y;x,y\"");
        if (points.GetArrayLength() > maximum) throw CommandOptions.Invalid($"macro hit-test-batch point count exceeds --max-points ({maximum})");
        var valid = new List<object>(); var errors = new List<object>(); int index = 0;
        foreach (var point in points.EnumerateArray())
        {
            ++index; string text = point.GetString()!;
            var match = System.Text.RegularExpressions.Regex.Match(text, @"^\s*(-?\d+)\s*,\s*(-?\d+)\s*$");
            if (!match.Success) { errors.Add(new { index, point = text, code = "bad_point_spec", message = "point must be x,y" }); continue; }
            int x = int.Parse(match.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture);
            int y = int.Parse(match.Groups[2].Value, System.Globalization.CultureInfo.InvariantCulture);
            if (x <= 0 || y <= 0) { errors.Add(new { index, point = text, code = "invalid_coords", message = "x and y must be positive" }); continue; }
            valid.Add(new { index, x, y });
        }
        return new { schema = "cucp.coord-batch-points/v1", valid, errors };
    }
    internal static object SelectWindow(JsonElement args)
    {
        var fields = args.EnumerateObject().Select(p => p.Name).ToArray();
        if (fields.Length != 3 || fields.Distinct(StringComparer.Ordinal).Count() != 3 ||
            fields.Any(p => p is not ("windows" or "match" or "modern")) ||
            !args.TryGetProperty("modern", out var mode) || mode.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
            !args.TryGetProperty("windows", out var windows) || windows.ValueKind != JsonValueKind.Array || windows.GetArrayLength() > 16384)
            throw CommandOptions.Invalid("Invalid captured coordinate window selection.");
        bool modern = mode.GetBoolean();
        string Lower(string text) => modern ? text.ToLowerInvariant() : LegacyTextKernel.LowerValue(text, System.Globalization.CultureInfo.InvariantCulture);
        bool Equal(string left, string right) => modern ? StringComparer.InvariantCultureIgnoreCase.Equals(left, right) : LegacyOcrMatcher.LegacyEqual(left, right);
        bool Contains(string source, string value) => source.Length != 0 && (modern ? source.IndexOf(value, StringComparison.CurrentCulture) : LegacyOcrMatcher.LegacyIndex(source, value)) >= 0;
        bool Flag(JsonElement row, string name) => row.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        string match = Text(args, "match"), needle = Lower(match);
        var rows = windows.EnumerateArray().Where(row => Flag(row, "visible") && needle.Length != 0 &&
            (Contains(Lower(Text(row, "title")), needle) || Contains(Lower(Text(row, "process")), needle))).ToArray();
        int Rank(JsonElement row) => Text(row, "title").Length != 0 && Equal(Lower(Text(row, "title")), needle) ? 0 :
            Text(row, "process").Length != 0 && Equal(Lower(Text(row, "process")), needle) ? 1 : 2;
        if (modern) rows = rows.OrderBy(Rank).ThenBy(row => Flag(row, "minimized") ? 1 : 0).ToArray();
        else LegacyOcrMatcher.LegacySort(rows, (left, right) => {
            int comparison = Rank(left).CompareTo(Rank(right));
            return comparison != 0 ? comparison : Flag(left, "minimized").CompareTo(Flag(right, "minimized"));
        });
        return new { schema = "cucp.coord-window/v1", window = rows.Length == 0 ? (JsonElement?)null : rows[0].Clone() };
    }
    private static void Fields(JsonElement args)
    {
        if (args.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Coordinate arguments must be an object.");
        var allowed = new HashSet<string>(["from", "x", "y", "norm_x", "norm_y", "has_norm", "target_hwnd", "target_match", "virtual_screen", "selected_window", "coordinate_profile"], StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var field in args.EnumerateObject())
            if (!allowed.Contains(field.Name) || !seen.Add(field.Name)) throw CommandOptions.Invalid("Unknown or duplicate coordinate field.");
    }
    private static string Text(JsonElement args, string name, int max = 32768)
    {
        if (!args.TryGetProperty(name, out var value) || value.ValueKind == JsonValueKind.Null) return string.Empty;
        if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid($"{name} must be a string.");
        var result = value.GetString()!;
        if (result.Length > max) throw CommandOptions.Invalid($"{name} exceeds its length limit.");
        return result;
    }
    private static double Number(JsonElement args, string name)
    {
        if (!args.TryGetProperty(name, out var value)) return 0;
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var result) || !double.IsFinite(result) || Math.Abs(result) > 1e12)
            throw CommandOptions.Invalid($"{name} must be a finite bounded number.");
        return result;
    }
    private static long Long(JsonElement args, string name)
    {
        if (!args.TryGetProperty(name, out var value)) return 0;
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt64(out var result)) throw CommandOptions.Invalid($"{name} must be an integer.");
        return result;
    }
    private static int Integer(JsonElement args, string name, int minimum = int.MinValue)
    {
        if (!args.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out var result) || result < minimum)
            throw CommandOptions.Invalid($"{name} must be a bounded integer.");
        return result;
    }
    private static Rect Rectangle(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Rectangle must be an object.");
        return new(Integer(value, "x"), Integer(value, "y"), Integer(value, "width", 0), Integer(value, "height", 0));
    }
    private static int Round(double value)
    {
        var rounded = Math.Round(value, MidpointRounding.ToEven);
        if (!double.IsFinite(rounded) || rounded < int.MinValue || rounded > int.MaxValue)
            throw CommandOptions.Invalid("Mapped point exceeds 32-bit physical coordinate range.");
        return (int)rounded;
    }
    private static Point P(double x, double y) => new(Round(x), Round(y));
    private static bool Inside(Point p, Rect r) => p.X >= r.X && p.X < r.Right && p.Y >= r.Y && p.Y < r.Bottom;

    internal static object Map(JsonElement args)
    {
        Fields(args);
        var from = Text(args, "from", 64).ToLowerInvariant();
        if (from.Length == 0) from = "screen";
        var x = Number(args, "x"); var y = Number(args, "y");
        var normX = Number(args, "norm_x"); var normY = Number(args, "norm_y");
        var hasNorm = false;
        if (args.TryGetProperty("has_norm", out var has))
        {
            if (has.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw CommandOptions.Invalid("has_norm must be boolean.");
            hasNorm = has.GetBoolean();
        }
        var targetHwnd = Long(args, "target_hwnd");
        var targetMatch = Text(args, "target_match");
        if (!args.TryGetProperty("virtual_screen", out var desktop)) throw CommandOptions.Invalid("Captured virtual_screen is required.");
        var virtualRect = Rectangle(desktop);
        var right = Integer(desktop, "right"); var bottom = Integer(desktop, "bottom");
        var monitors = Integer(desktop, "monitor_count", 0);
        if (right != virtualRect.Right || bottom != virtualRect.Bottom) throw CommandOptions.Invalid("Virtual-screen bounds disagree with dimensions.");
        var virtualJson = new { x = virtualRect.X, y = virtualRect.Y, width = virtualRect.Width, height = virtualRect.Height, right, bottom, monitor_count = monitors };
        if (!args.TryGetProperty("selected_window", out var window) || window.ValueKind == JsonValueKind.Null)
            return new { schema = "cucp.coord-map/v1", status = "partial", reason = "target_window_not_found", from,
                target_hwnd = targetHwnd, target_match = targetMatch, virtual_screen = virtualJson, elapsed_ms = 0,
                next_step = "Provide --target-match or --target-hwnd, or use --from screen with a point inside the target window." };
        if (window.ValueKind != JsonValueKind.Object || !window.TryGetProperty("rect", out var rectJson)) throw CommandOptions.Invalid("Selected window requires a rectangle.");
        var rect = Rectangle(rectJson);
        var left = Math.Max(rect.X, virtualRect.X); var top = Math.Max(rect.Y, virtualRect.Y);
        var clipRight = Math.Min(rect.Right, right); var clipBottom = Math.Min(rect.Bottom, bottom);
        var clip = new Rect(left, top, Round(Math.Max(0, clipRight - left)), Round(Math.Max(0, clipBottom - top)));
        Point screenPoint, windowPoint, visiblePoint;
        object? normalized = null;
        var rounding = false;
        if ((from is "visible-window" or "visible-normalized") && (clip.Width <= 0 || clip.Height <= 0))
            return new { schema = "cucp.coord-map/v1", status = "partial", reason = "window_not_visible_in_virtual_screen", from,
                selected_window = window.Clone(), virtual_screen = virtualJson, elapsed_ms = 0 };
        switch (from)
        {
            case "screen":
                screenPoint = P(x, y);
                windowPoint = P((long)screenPoint.X - rect.X, (long)screenPoint.Y - rect.Y);
                visiblePoint = P((long)screenPoint.X - clip.X, (long)screenPoint.Y - clip.Y);
                break;
            case "window":
                windowPoint = P(x, y);
                screenPoint = P((long)rect.X + windowPoint.X, (long)rect.Y + windowPoint.Y);
                visiblePoint = P((long)screenPoint.X - clip.X, (long)screenPoint.Y - clip.Y);
                break;
            case "visible-window":
                visiblePoint = P(x, y);
                screenPoint = P((long)clip.X + visiblePoint.X, (long)clip.Y + visiblePoint.Y);
                windowPoint = P((long)screenPoint.X - rect.X, (long)screenPoint.Y - rect.Y);
                break;
            case "normalized":
            case "visible-normalized":
                if (!hasNorm) { normX = x; normY = y; }
                normalized = new { x = Math.Round(normX, 6), y = Math.Round(normY, 6) };
                var basis = from == "normalized" ? rect : clip;
                screenPoint = P(basis.X + normX * basis.Width, basis.Y + normY * basis.Height);
                windowPoint = P((long)screenPoint.X - rect.X, (long)screenPoint.Y - rect.Y);
                visiblePoint = P((long)screenPoint.X - clip.X, (long)screenPoint.Y - clip.Y);
                rounding = true;
                break;
            default:
                return new { schema = "cucp.coord-map/v1", status = "partial", reason = "unsupported_from", from, supported_from = Modes, elapsed_ms = 0 };
        }
        if (normalized is null && rect.Width > 0 && rect.Height > 0)
            normalized = new { x = Math.Round((double)windowPoint.X / rect.Width, 6), y = Math.Round((double)windowPoint.Y / rect.Height, 6) };
        var insideWindow = Inside(screenPoint, rect); var insideVisible = Inside(screenPoint, clip);
        var warnings = new List<string>();
        if (!insideWindow) warnings.Add("mapped_point_outside_window");
        if (!insideVisible) warnings.Add("mapped_point_outside_visible_clip");
        if (rounding) warnings.Add("normalized_point_rounded_to_integer_screen_pixel");
        object? profile = null;
        if (args.TryGetProperty("coordinate_profile", out var rawProfile) && rawProfile.ValueKind != JsonValueKind.Null)
        {
            if (rawProfile.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("coordinate_profile must be an object or null.");
            profile = rawProfile.Clone();
            if (Text(rawProfile, "coordinate_risk", 64).Equals("high", StringComparison.OrdinalIgnoreCase))
            {
                warnings.Add("coordinate_profile_high_risk");
                if (rawProfile.TryGetProperty("warnings", out var extra))
                {
                    var values = extra.ValueKind == JsonValueKind.Array ? extra.EnumerateArray().ToArray() : new[] { extra };
                    if (values.Length > 1000) throw CommandOptions.Invalid("Coordinate warning budget exceeded.");
                    foreach (var value in values)
                    {
                        if (value.ValueKind == JsonValueKind.Null) continue;
                        if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Coordinate warnings must be strings.");
                        var text = value.GetString();
                        if (!string.IsNullOrEmpty(text)) warnings.Add(text);
                    }
                }
            }
        }
        return new
        {
            schema = "cucp.coord-map/v1", status = "ok", from,
            input = new { x, y, norm_x = hasNorm ? (double?)normX : null, norm_y = hasNorm ? (double?)normY : null },
            selected_window = new Dictionary<string, object?> { ["hwnd"] = Long(window, "hwnd"), ["title"] = Text(window, "title"),
                ["process"] = Text(window, "process"), ["class"] = Text(window, "class"), ["rect"] = rectJson.Clone() },
            virtual_screen = virtualJson, visible_window_clip = clip.Json,
            screen_point = screenPoint.Json, window_point = windowPoint.Json, visible_window_point = visiblePoint.Json,
            normalized_window_point = normalized, inside_window = insideWindow, inside_visible_clip = insideVisible,
            coordinate_profile = profile, warnings, elapsed_ms = 0,
            next_step = "Use screen_point with point-plan or click-point after read-only verification; use normalized_window_point to persist a layout-relative target."
        };
    }
}
