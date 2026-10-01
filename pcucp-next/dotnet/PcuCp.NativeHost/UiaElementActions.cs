using System.Text;
using System.Windows.Automation;

internal static class UiaElementActions
{
    private sealed record Entry(AutomationElement Element, int[] RuntimeId, IntPtr Hwnd, int Pid,
        string Name, string AutomationId, int ControlType, RectInfo Geometry);
    private static readonly UiaReferenceStore<Entry> References = new();
    internal static void BeginObservation() => References.Begin();
    internal static void Invalidate() => References.Clear();
    internal static string? Register(AutomationElement element, WindowTarget? target)
    {
        if (target is null) return null;
        var current = element.Current;
        var rect = current.BoundingRectangle;
        if (current.ProcessId != target.Pid || rect.IsEmpty || current.IsPassword) return null;
        var runtime = element.GetRuntimeId();
        if (runtime is null || runtime.Length == 0) return null;
        return References.Add(new(element, runtime, target.Hwnd, target.Pid, current.Name ?? "",
            current.AutomationId ?? "", current.ControlType.Id, new(rect.X, rect.Y, rect.Width, rect.Height)));
    }

    internal static NativeResult Execute(string command, CommandOptions options)
    {
        options.Allow("--hwnd", "--pid", "--element-ref", "--text-b64", "--allow-live-control",
            "--expected-x", "--expected-y", "--expected-width", "--expected-height");
        if (!options.Has("--allow-live-control")) throw new NativeFailure("live_control_required", "UIA actions require live control.");
        // Consume before any provider call. A provider failure can never make a token replayable.
        var entry = References.Consume(options.Required("--element-ref"));
        var target = WindowTarget.Read(options, true);
        if (target.Hwnd != entry.Hwnd || target.Pid != entry.Pid)
            throw new NativeFailure("target_mismatch", "Element reference belongs to another target.");
        PrivilegeInspector.RequireInputAccess(target.Pid);
        target.Validate(true);
        var attempted = false;
        try
        {
            ValidateElement(entry, target);
            object pattern;
            string? value = null;
            if (command == "uia-invoke")
            {
                if (options.Has("--text-b64")) throw CommandOptions.Invalid("Invoke does not accept a value.");
                if (!entry.Element.TryGetCurrentPattern(InvokePattern.Pattern, out pattern))
                    throw new NativeFailure("unsupported_pattern", "Element does not support InvokePattern; no input fallback is performed.");
            }
            else
            {
                var encoded = options.Required("--text-b64");
                if (encoded.Length > 24000) throw CommandOptions.Invalid("Encoded value is too long.");
                try { value = new UTF8Encoding(false, true).GetString(Convert.FromBase64String(encoded)); }
                catch (Exception ex) when (ex is FormatException or DecoderFallbackException) { throw CommandOptions.Invalid("Invalid UTF-8/base64 value."); }
                if (value.Length > 4096 || value.Contains('\0')) throw CommandOptions.Invalid("Value must be at most 4096 UTF-16 units without NUL.");
                if (!entry.Element.TryGetCurrentPattern(ValuePattern.Pattern, out pattern) || ((ValuePattern)pattern).Current.IsReadOnly)
                    throw new NativeFailure("unsupported_pattern", "Element does not support a writable ValuePattern.");
            }
            ValidateElement(entry, target);
            target.Validate(true);
            PrivilegeInspector.RequireInputAccess(target.Pid);
            attempted = true;
            if (command == "uia-invoke") ((InvokePattern)pattern).Invoke();
            else ((ValuePattern)pattern).SetValue(value!);
            return NativeResult.Ok(command, new { target = target.Identity, dispatched = true,
                verification = "not_verified", automatic_retry = false, may_have_acted = true });
        }
        catch (Exception ex)
        {
            return new NativeResult("pcucp.native/v1", attempted ? "partial" : "error", command,
                new { may_have_acted = attempted, automatic_retry = false },
                [new NativeError(ex is NativeFailure nf ? nf.Code : "uia_provider_error", ex.Message)]);
        }
    }

    private static void ValidateElement(Entry entry, WindowTarget target)
    {
        var current = entry.Element.Current;
        var rect = current.BoundingRectangle;
        if (current.ProcessId != entry.Pid || !entry.RuntimeId.SequenceEqual(entry.Element.GetRuntimeId()) ||
            current.Name != entry.Name || current.AutomationId != entry.AutomationId || current.ControlType.Id != entry.ControlType ||
            rect.IsEmpty || new RectInfo(rect.X, rect.Y, rect.Width, rect.Height) != entry.Geometry)
            throw new NativeFailure("stale_element_reference", "Element identity or geometry changed; observe again.");
        if (!current.IsEnabled || current.IsOffscreen || current.IsPassword)
            throw new NativeFailure("element_unavailable", "Disabled, offscreen and password elements cannot be acted on.");
        var centerX = rect.X + rect.Width / 2;
        var centerY = rect.Y + rect.Height / 2;
        if (!double.IsFinite(centerX) || !double.IsFinite(centerY) || centerX < int.MinValue || centerX > int.MaxValue || centerY < int.MinValue || centerY > int.MaxValue)
            throw new NativeFailure("element_unavailable", "Invalid element geometry.");
        target.HitTest((int)Math.Floor(centerX), (int)Math.Floor(centerY));
        // Prove containment in the exact observed HWND, not just a shared process.
        var root = AutomationElement.FromHandle(target.Hwnd);
        var cursor = entry.Element;
        for (var depth = 0; cursor is not null && depth < 64; depth++)
        {
            if (Automation.Compare(cursor, root)) return;
            cursor = TreeWalker.RawViewWalker.GetParent(cursor);
        }
        throw new NativeFailure("target_mismatch", "Element is no longer inside the observed window.");
    }
}
