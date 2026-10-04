using System.Globalization;

/// <summary>Retained wrapper Win32 reads only, separate from input/native helper primitives.</summary>
internal static class LegacyCoordinateRead
{
    private static Dictionary<string, object?> D(params object?[] pairs) => LegacyPrecisionKernel.D(pairs);
    internal static object Hit(CommandOptions options) => Hit(
        LegacyTaskFormKernel.LegacyInt(options.Get("--x")), LegacyTaskFormKernel.LegacyInt(options.Get("--y")),
        LegacyTaskFormKernel.LegacyInt(options.Get("--target-hwnd")), options.Get("--target-match") ?? "");
    internal static object Hit(int x, int y, int target, string match)
    {
        var window = CucpWin32.WindowFromScreenPoint(x, y);
        string reason = "no_target_specified"; bool matched = true;
        if (window is null) { reason = "no_window_at_coords"; matched = false; }
        else if (target > 0) { matched = window.Hwnd.ToInt64() == target; reason = matched ? "hwnd_match" : "hwnd_mismatch"; }
        else if (match.Length != 0)
        {
            string needle = match.ToLowerInvariant();
            matched = (window.Title ?? "").ToLowerInvariant().Contains(needle) || (window.ProcessName ?? "").ToLowerInvariant().Contains(needle);
            reason = matched ? "title_or_process_match" : "title_mismatch";
        }
        var value = D("status", window is null || (target > 0 || match.Length != 0) && !matched ? "partial" : "ok",
            "x", x, "y", y, "child_hwnd", window?.ChildHwnd.ToInt64() ?? 0, "root_hwnd", window?.Hwnd.ToInt64() ?? 0,
            "root_title", window?.Title ?? "", "child_title", "", "root_class", window?.ClassName ?? "",
            "process_id", (int)(window?.Pid ?? 0), "process_name", window?.ProcessName ?? "", "target_hwnd", target,
            "target_match", match, "matched", matched, "match_reason", reason, "uia_skipped", true, "source", "wrapper_win32_fast");
        if (window is null) value.Add("reason", "no_window_at_coords");
        return value;
    }
    private static object? Monitor(CucpWin32.MonitorInfo? value) => value is null ? null : D("device", value.DeviceName,
        "primary", value.Primary, "rect", D("x", value.X, "y", value.Y, "width", value.Width, "height", value.Height),
        "work_rect", D("x", value.WorkX, "y", value.WorkY, "width", value.WorkWidth, "height", value.WorkHeight),
        "dpi", D("x", value.DpiX, "y", value.DpiY, "scale_x", value.ScaleX, "scale_y", value.ScaleY));
    internal static object Target(CommandOptions options)
    {
        if (!long.TryParse(options.Get("--target-hwnd") ?? "0", NumberStyles.Integer, CultureInfo.InvariantCulture, out long target))
            throw CommandOptions.Invalid("Coordinate target must be Int64.");
        object? monitor = null, dpi = null;
        if (target != 0)
        {
            try { monitor = Monitor(CucpWin32.MonitorFromWindowInfo(new IntPtr(target))); } catch { }
            try { uint raw = CucpWin32.GetWindowDpiValue(new IntPtr(target)); if (raw > 0) dpi = D("dpi", raw, "scale", Math.Round(raw / 96.0, 4)); } catch { }
        }
        return D("target_monitor", monitor, "target_window_dpi", dpi);
    }
    internal static object Snapshot(CommandOptions options)
    {
        int x = LegacyTaskFormKernel.LegacyInt(options.Get("--x")), y = LegacyTaskFormKernel.LegacyInt(options.Get("--y"));
        if (!long.TryParse(options.Get("--target-hwnd") ?? "0", NumberStyles.Integer, CultureInfo.InvariantCulture, out long target))
            throw CommandOptions.Invalid("Coordinate snapshot target must be Int64.");
        bool hasPoint = options.Get("--has-point") == "true";
        if (options.Get("--has-point") is not (null or "true" or "false")) throw CommandOptions.Invalid("Coordinate point flag must be explicit true/false.");
        var screen = CucpWin32.GetVirtualScreenInfo();
        object? pointMonitor = null, targetMonitor = null, dpi = null;
        if (hasPoint) { try { pointMonitor = Monitor(CucpWin32.MonitorFromScreenPointInfo(x, y)); } catch { } }
        if (target != 0)
        {
            try { targetMonitor = Monitor(CucpWin32.MonitorFromWindowInfo(new IntPtr(target))); } catch { }
            try { uint raw = CucpWin32.GetWindowDpiValue(new IntPtr(target)); if (raw > 0) dpi = D("dpi", raw, "scale", Math.Round(raw / 96.0, 4)); } catch { }
        }
        return D("virtual_screen", D("x", screen.X, "y", screen.Y, "width", screen.Width, "height", screen.Height,
            "right", checked(screen.X + screen.Width), "bottom", checked(screen.Y + screen.Height), "monitor_count", screen.MonitorCount,
            "same_display_format", screen.SameDisplayFormat), "monitors", CucpWin32.EnumerateMonitors().Select(Monitor).ToArray(),
            "point_monitor", pointMonitor, "target_monitor", targetMonitor, "target_window_dpi", dpi);
    }
}
