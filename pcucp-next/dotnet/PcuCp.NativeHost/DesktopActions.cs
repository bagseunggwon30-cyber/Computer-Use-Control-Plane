using System.Runtime.InteropServices;
using System.Text;

internal static class DesktopActions
{
    private const uint KeyUp = 0x0002, Unicode = 0x0004;
    private static readonly string[] CommonOptions = ["--hwnd", "--pid", "--allow-live-control", "--expected-x", "--expected-y", "--expected-width", "--expected-height"];
    private static readonly Dictionary<string, ushort[]> Keys = CreateKeys();

    public static NativeResult Execute(string command, CommandOptions options)
    {
        var extra = command switch
        {
            "click" => new[] { "--x", "--y", "--button", "--count" }, "type" => new[] { "--text-b64" }, "key" => new[] { "--key" },
            "drag" => new[] { "--x", "--y", "--to-x", "--to-y", "--steps" },
            "scroll" => new[] { "--direction", "--amount" }, _ => Array.Empty<string>()
        };
        // Restoring a minimized window changes its rectangle. Reject geometry constraints
        // before any focus mutation; the caller observes a fresh rectangle after focusing.
        var common = command == "focus" ? CommonOptions.Where(option => !option.StartsWith("--expected-", StringComparison.Ordinal)) : CommonOptions;
        options.Allow(common.Concat(extra).ToArray());
        if (!options.Has("--allow-live-control")) throw new NativeFailure("live_control_required", "Native input requires --allow-live-control.");
        var target = WindowTarget.Read(options, true);
        PrivilegeInspector.RequireInputAccess(target.Pid);
        if (command == "focus")
        {
            if (NativeMethods.IsIconic(target.Hwnd)) NativeMethods.ShowWindow(target.Hwnd, 9);
            if (!NativeMethods.SetForegroundWindow(target.Hwnd) && NativeMethods.GetForegroundWindow() != target.Hwnd)
                throw new NativeFailure("focus_denied", "Windows denied foreground activation. Activate the window manually and observe again.");
            target.Validate(true);
            return NativeResult.Ok(command, new { target = target.Identity, verification = "foreground_confirmed", dispatched = true });
        }
        target.Validate(true);
        EnsureModifiersReleased();
        switch (command)
        {
            case "click": Click(target, options); break;
            case "drag": Drag(target, options); break;
            case "type": Type(target, options); break;
            case "key": Key(target, options); break;
            case "scroll": Scroll(target, options); break;
        }
        return NativeResult.Ok(command, new
        {
            target = target.Identity, verification = "not_verified", dispatched = true,
            note = "OS input dispatch succeeded. Observe the application to verify the intended result."
        });
    }

    private static void Click(WindowTarget target, CommandOptions options)
    {
        var x = options.RequiredInteger("--x");
        var y = options.RequiredInteger("--y");
        var count = options.Integer("--count", 1, 1, 2);
        var flags = (options.Get("--button") ?? "left").ToLowerInvariant() switch
        {
            "left" => (0x0002u, 0x0004u), "right" => (0x0008u, 0x0010u), "middle" => (0x0020u, 0x0040u),
            _ => throw CommandOptions.Invalid("--button must be left, right or middle.")
        };
        target.HitTest(x, y);
        var screen = NativeMethods.VirtualScreen;
        // Map the center of the physical pixel into SendInput's 16-bit virtual desktop space.
        var dx = InputGeometry.Normalize(x, screen.X, screen.Width);
        var dy = InputGeometry.Normalize(y, screen.Y, screen.Height);
        Dispatch(target, [Mouse(0x0001 | 0x8000 | 0x4000, dx: dx, dy: dy)]);
        // Re-check after movement; tooltips, menus and application state may have changed.
        target.HitTest(x, y);
        if (!NativeMethods.GetCursorPos(out var actual) || actual.X != x || actual.Y != y)
            throw new NativeFailure("pointer_position_mismatch", "The pointer did not reach the requested pixel; no click was sent.");
        // Keep both clicks together so another input producer cannot interleave
        // an unrelated action between the pair. App-level success still needs observation.
        Dispatch(target, ClickEvents(flags.Item1, flags.Item2, count));
    }

    private static void Drag(WindowTarget target, CommandOptions options)
    {
        var x = options.RequiredInteger("--x");
        var y = options.RequiredInteger("--y");
        var toX = options.RequiredInteger("--to-x");
        var toY = options.RequiredInteger("--to-y");
        var steps = options.Integer("--steps", 16, 1, 64);
        var screen = NativeMethods.VirtualScreen;
        var points = DragPoints(x, y, toX, toY, steps);
        foreach (var point in points) target.HitTest(point.X, point.Y);
        Dispatch(target, [Mouse(0x0001 | 0x8000 | 0x4000,
            dx: InputGeometry.Normalize(x, screen.X, screen.Width), dy: InputGeometry.Normalize(y, screen.Y, screen.Height))]);
        foreach (var point in points) target.HitTest(point.X, point.Y);
        if (!NativeMethods.GetCursorPos(out var actual) || actual.X != x || actual.Y != y || NativeMethods.VirtualScreen != screen)
            throw new NativeFailure("pointer_position_mismatch", "Pointer or desktop changed; no drag button-down was sent.");
        // One bounded SendInput batch: never sleep/cancel between down and up.
        Dispatch(target, DragEvents(points, screen));
    }

    internal static (int X, int Y)[] DragPoints(int x, int y, int toX, int toY, int steps)
    {
        if (steps is < 1 or > 64) throw CommandOptions.Invalid("Drag steps must be 1..64.");
        return Enumerable.Range(0, steps + 1).Select(i =>
            ((int)(x + ((long)toX - x) * i / steps), (int)(y + ((long)toY - y) * i / steps))).ToArray();
    }

    internal static NativeMethods.INPUT[] DragEvents((int X, int Y)[] points, PixelRect screen)
    {
        if (points.Length is < 2 or > 65) throw CommandOptions.Invalid("Invalid drag point count.");
        return new[] { Mouse(2) }.Concat(points.Skip(1).Select(p => Mouse(0x0001 | 0x8000 | 0x4000 | 0x2000,
            dx: InputGeometry.Normalize(p.X, screen.X, screen.Width), dy: InputGeometry.Normalize(p.Y, screen.Y, screen.Height))))
            .Append(Mouse(4)).ToArray();
    }

    internal static NativeMethods.INPUT[] ClickEvents(uint down, uint up, int count)
    {
        if (count is < 1 or > 2) throw CommandOptions.Invalid("Click count must be 1 or 2.");
        return Enumerable.Range(0, count).SelectMany(_ => new[] { Mouse(down), Mouse(up) }).ToArray();
    }

    private static void Type(WindowTarget target, CommandOptions options)
    {
        string text;
        try
        {
            var encoded = options.Required("--text-b64");
            if (encoded.Length > 65536) throw CommandOptions.Invalid("Encoded text exceeds the native input limit.");
            text = new UTF8Encoding(false, true).GetString(Convert.FromBase64String(encoded));
        }
        catch (FormatException) { throw CommandOptions.Invalid("--text-b64 must contain base64-encoded UTF-8."); }
        catch (DecoderFallbackException) { throw CommandOptions.Invalid("--text-b64 contains invalid UTF-8."); }
        if (text.Length == 0 || text.Length > 8192 || text.Contains('\0')) throw CommandOptions.Invalid("Text must contain 1..8192 UTF-16 units without NUL.");
        var events = new List<NativeMethods.INPUT>(text.Length * 2);
        foreach (var unit in text)
        {
            events.Add(Keyboard(0, unit, Unicode));
            events.Add(Keyboard(0, unit, Unicode | KeyUp));
        }
        // One bounded SendInput call keeps the UTF-16 sequence (including surrogate pairs) together.
        Dispatch(target, events.ToArray());
    }

    private static void Key(WindowTarget target, CommandOptions options)
    {
        var name = options.Required("--key").ToUpperInvariant();
        if (!Keys.TryGetValue(name, out var sequence)) throw CommandOptions.Invalid($"Unsupported key shortcut: {name}");
        var events = sequence.Select(vk => Keyboard(vk, 0, IsExtended(vk) ? 1u : 0u))
            .Concat(sequence.Reverse().Select(vk => Keyboard(vk, 0, KeyUp | (IsExtended(vk) ? 1u : 0u)))).ToArray();
        Dispatch(target, events);
    }

    private static void Scroll(WindowTarget target, CommandOptions options)
    {
        var direction = options.Required("--direction").ToLowerInvariant();
        var amount = options.Integer("--amount", 3, 1, 20);
        var (horizontal, sign) = direction switch
        {
            "up" => (false, 1), "down" => (false, -1), "left" => (true, -1), "right" => (true, 1),
            _ => throw CommandOptions.Invalid("--direction must be up, down, left or right.")
        };
        if (!NativeMethods.GetCursorPos(out var point)) throw new NativeFailure("pointer_unavailable", "Cannot read the pointer position.");
        // Windows can scroll inactive windows under the pointer. Never silently send a wheel event outside the target.
        target.HitTest(point.X, point.Y);
        Dispatch(target, [Mouse(horizontal ? 0x1000u : 0x0800u, unchecked((uint)(sign * 120 * amount)))]);
    }

    private static void Dispatch(WindowTarget target, NativeMethods.INPUT[] events)
    {
        PrivilegeInspector.RequireDefaultDesktop();
        target.Validate(true); // Immediately before SendInput; no automatic refocusing.
        var sent = NativeMethods.SendInput((uint)events.Length, events, Marshal.SizeOf<NativeMethods.INPUT>());
        if (sent != events.Length)
        {
            var error = Marshal.GetLastWin32Error();
            // A short SendInput may leave our modifiers/button down. Release only downs that
            // Windows says it accepted, never keys held by the user before this command.
            var releases = PendingReleases(events.Take((int)sent));
            var released = releases.Length == 0 || NativeMethods.SendInput((uint)releases.Length, releases, Marshal.SizeOf<NativeMethods.INPUT>()) == releases.Length;
            throw new NativeFailure("dispatch_failed", $"SendInput accepted {sent}/{events.Length} events (Win32 {error}); pending-input release {(released ? "completed" : "failed")}. Some input may have occurred; observe before retrying. UIPI or application restrictions may block input.");
        }
    }

    private static void EnsureModifiersReleased()
    {
        // Do not release keys held by the user; abort rather than changing the meaning of their input.
        if (new[] { 0x10, 0x11, 0x12, 0x5B, 0x5C, 0x01, 0x02, 0x04 }.Any(key => (NativeMethods.GetAsyncKeyState(key) & 0x8000) != 0))
            throw new NativeFailure("input_busy", "A modifier key or mouse button is held. Release it before automation.");
    }

    private static bool IsExtended(ushort key) => key is 0x21 or 0x22 or 0x23 or 0x24 or 0x25 or 0x26 or 0x27 or 0x28 or 0x2D or 0x2E;
    internal static NativeMethods.INPUT[] PendingReleases(IEnumerable<NativeMethods.INPUT> accepted)
    {
        var pending = new Dictionary<string, NativeMethods.INPUT>();
        foreach (var input in accepted)
        {
            if (input.Type == 1)
            {
                var key = input.Data.Keyboard;
                var id = $"key:{key.Vk}:{key.Scan}:{key.Flags & ~KeyUp}";
                if ((key.Flags & KeyUp) != 0) pending.Remove(id);
                else pending[id] = Keyboard(key.Vk, key.Scan, key.Flags | KeyUp);
            }
            else if (input.Type == 0)
            {
                foreach (var (down, up) in new[] { (2u, 4u), (8u, 16u), (32u, 64u) })
                {
                    if ((input.Data.Mouse.Flags & up) != 0) pending.Remove($"mouse:{down}");
                    if ((input.Data.Mouse.Flags & down) != 0) pending[$"mouse:{down}"] = Mouse(up);
                }
            }
        }
        return pending.Values.Reverse().ToArray();
    }
    private static NativeMethods.INPUT Keyboard(ushort vk, ushort scan, uint flags) => new() { Type = 1, Data = new NativeMethods.InputUnion { Keyboard = new NativeMethods.KEYBDINPUT { Vk = vk, Scan = scan, Flags = flags } } };
    private static NativeMethods.INPUT Mouse(uint flags, uint data = 0, int dx = 0, int dy = 0) => new() { Type = 0, Data = new NativeMethods.InputUnion { Mouse = new NativeMethods.MOUSEINPUT { Dx = dx, Dy = dy, MouseData = data, Flags = flags } } };
    private static Dictionary<string, ushort[]> CreateKeys()
    {
        var keys = new Dictionary<string, ushort[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["ENTER"] = [0x0D], ["TAB"] = [0x09], ["ESC"] = [0x1B], ["ESCAPE"] = [0x1B], ["BACKSPACE"] = [0x08],
            ["DELETE"] = [0x2E], ["SPACE"] = [0x20], ["LEFT"] = [0x25], ["RIGHT"] = [0x27], ["UP"] = [0x26], ["DOWN"] = [0x28],
            ["HOME"] = [0x24], ["END"] = [0x23], ["PAGEUP"] = [0x21], ["PAGEDOWN"] = [0x22], ["SHIFT+TAB"] = [0x10, 0x09],
            ["CTRL+HOME"] = [0x11, 0x24], ["CTRL+END"] = [0x11, 0x23], ["ALT+F4"] = [0x12, 0x73]
        };
        foreach (var key in "ACVXZYSFL") keys[$"CTRL+{key}"] = [0x11, key];
        for (var i = 1; i <= 12; i++) keys[$"F{i}"] = [(ushort)(0x6F + i)];
        return keys;
    }
}
