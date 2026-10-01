using System.Globalization;

internal sealed class WindowTarget
{
    public IntPtr Hwnd { get; }
    public int Pid { get; }
    private readonly PixelRect? expected;
    private WindowTarget(IntPtr hwnd, int pid, PixelRect? expected) { Hwnd = hwnd; Pid = pid; this.expected = expected; }
    public object Identity => new { hwnd = NativeMethods.HwndString(Hwnd), pid = Pid };

    public static WindowTarget Read(CommandOptions options, bool requirePid)
    {
        var hwnd = ParseHwnd(options.Required("--hwnd"));
        if (!NativeMethods.IsWindow(hwnd)) throw new NativeFailure("target_not_found", "The target window no longer exists.");
        if (NativeMethods.GetAncestor(hwnd, 2) != hwnd) throw CommandOptions.Invalid("--hwnd must identify a top-level window.");
        NativeMethods.GetWindowThreadProcessId(hwnd, out var actualPid);
        var pid = requirePid ? options.RequiredInteger("--pid", 1) : options.Integer("--pid", (int)actualPid, 1, int.MaxValue);
        if ((uint)pid != actualPid) throw new NativeFailure("target_mismatch", "The window does not belong to the expected process.");
        var names = new[] { "--expected-x", "--expected-y", "--expected-width", "--expected-height" };
        PixelRect? expected = null;
        if (names.Any(options.Has))
        {
            if (!names.All(options.Has)) throw CommandOptions.Invalid("Supply all four --expected-* geometry values together.");
            expected = new PixelRect(options.RequiredInteger(names[0]), options.RequiredInteger(names[1]), options.RequiredInteger(names[2], 1), options.RequiredInteger(names[3], 1));
        }
        var target = new WindowTarget(hwnd, pid, expected);
        target.Validate(false);
        return target;
    }

    internal static IntPtr ParseHwnd(string raw)
    {
        if (raw.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) raw = raw[2..];
        if (!long.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var number) || number <= 0)
            throw CommandOptions.Invalid("--hwnd must be a nonzero hexadecimal window handle.");
        return new IntPtr(number);
    }

    public PixelRect Rect()
    {
        if (!NativeMethods.GetWindowRect(Hwnd, out var rect)) throw new NativeFailure("target_not_found", "Unable to read target window geometry.");
        return new PixelRect(rect.Left, rect.Top, checked(rect.Right - rect.Left), checked(rect.Bottom - rect.Top));
    }

    public void Validate(bool requireForeground)
    {
        if (!NativeMethods.IsWindow(Hwnd)) throw new NativeFailure("target_not_found", "The target window no longer exists.");
        NativeMethods.GetWindowThreadProcessId(Hwnd, out var pid);
        if (pid != (uint)Pid) throw new NativeFailure("target_mismatch", "Target process changed; observe again.");
        if (expected is not null && expected != Rect()) throw new NativeFailure("geometry_changed", "Window geometry changed; observe again before acting.");
        if (requireForeground && NativeMethods.GetForegroundWindow() != Hwnd)
            throw new NativeFailure("foreground_mismatch", "The expected window is not foreground; focus explicitly or observe again.");
        if (requireForeground && (!NativeMethods.IsWindowVisible(Hwnd) || NativeMethods.IsIconic(Hwnd)))
            throw new NativeFailure("target_not_visible", "The target window is hidden or minimized.");
    }

    public void HitTest(int x, int y)
    {
        if (!NativeMethods.VirtualScreen.Contains(x, y) || !Rect().Contains(x, y))
            throw new NativeFailure("point_outside_target", "The physical screen coordinate is outside the target or virtual desktop.");
        var hit = NativeMethods.WindowFromPoint(new NativeMethods.POINT(x, y));
        if (hit == IntPtr.Zero || NativeMethods.GetAncestor(hit, 2) != Hwnd)
            throw new NativeFailure("hit_test_mismatch", "Another window covers the requested point.");
        NativeMethods.GetWindowThreadProcessId(hit, out var pid);
        if (pid != (uint)Pid) throw new NativeFailure("target_mismatch", "The point belongs to a different process.");
    }
}
