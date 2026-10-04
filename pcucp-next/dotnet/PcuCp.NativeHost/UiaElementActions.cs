using System.Windows.Automation;

internal static class UiaElementActions
{
    private sealed record Entry(AutomationElement Element, int[] RuntimeId, IntPtr Hwnd, int Pid,
        string Name, string AutomationId, int ControlType, RectInfo Geometry, IReadOnlyDictionary<string, object> PatternStates);
    private static readonly UiaReferenceStore<Entry> References = new();
    internal static void BeginObservation() => References.Begin();
    internal static void Invalidate() => References.Clear();
    internal static string? Register(AutomationElement element, WindowTarget? target, IReadOnlyDictionary<string, object> states)
    {
        if (target is null) return null;
        var current = element.Current;
        var rect = current.BoundingRectangle;
        if (current.ProcessId != target.Pid || rect.IsEmpty || current.IsPassword) return null;
        var runtime = element.GetRuntimeId();
        if (runtime is null || runtime.Length == 0) return null;
        return References.Add(new(element, runtime, target.Hwnd, target.Pid, current.Name ?? "",
            current.AutomationId ?? "", current.ControlType.Id, new(rect.X, rect.Y, rect.Width, rect.Height), states));
    }

    internal static NativeResult Execute(string command, CommandOptions options)
    {
        var request = UiaPatternRequest.Parse(command, options);
        // Consume before any provider call. A provider failure cannot make a token replayable.
        var entry = References.Consume(options.Required("--element-ref"));
        var target = WindowTarget.Read(options, true);
        if (target.Hwnd != entry.Hwnd || target.Pid != entry.Pid)
            throw new NativeFailure("target_mismatch", "Element reference belongs to another target.");
        void Validate()
        {
            PrivilegeInspector.RequireInputAccess(target.Pid);
            target.Validate(true);
            ValidateElement(entry, target);
        }
        return UiaPatternExecution.Run(command, target.Identity, Validate, () =>
        {
            var action = Prepare(entry.Element, request);
            var key = command switch
            {
                "uia-toggle" => "toggle", "uia-select" => "selection_item",
                "uia-expand-collapse" => "expand_collapse", "uia-scroll" => "scroll", _ => null
            };
            if (key is not null)
            {
                entry.PatternStates.TryGetValue(key, out var observed);
                UiaPatternExecution.RequireObservedState(observed, action.Before);
            }
            return action;
        });
    }

    internal static IReadOnlyDictionary<string, object> ReadPatternStates(AutomationElement element, IReadOnlyList<string> patterns)
    {
        var states = new Dictionary<string, object>(StringComparer.Ordinal);
        if (element.Current.IsPassword) return states;
        if (patterns.Contains("Toggle"))
            states["toggle"] = new ToggleSnapshot(Pattern<TogglePattern>(element, TogglePattern.Pattern).Current.ToggleState.ToString().ToLowerInvariant());
        if (patterns.Contains("SelectionItem"))
            states["selection_item"] = new SelectionSnapshot(Pattern<SelectionItemPattern>(element, SelectionItemPattern.Pattern).Current.IsSelected);
        if (patterns.Contains("ExpandCollapse"))
            states["expand_collapse"] = new ExpansionSnapshot(Pattern<ExpandCollapsePattern>(element, ExpandCollapsePattern.Pattern).Current.ExpandCollapseState.ToString().ToLowerInvariant());
        if (patterns.Contains("Scroll"))
        {
            var current = Pattern<ScrollPattern>(element, ScrollPattern.Pattern).Current;
            states["scroll"] = Snapshot(current.HorizontalScrollPercent, current.VerticalScrollPercent,
                current.HorizontalViewSize, current.VerticalViewSize, current.HorizontallyScrollable, current.VerticallyScrollable);
        }
        return states;
    }

    private static T Pattern<T>(AutomationElement element, AutomationPattern pattern) where T : class
    {
        if (!element.TryGetCurrentPattern(pattern, out var value) || value is not T typed)
            throw new NativeFailure("unsupported_pattern", $"Element does not support {typeof(T).Name}; no fallback is performed.");
        return typed;
    }

    private static PreparedUiaAction Stateful(string method, Func<object?> read, Action dispatch)
    {
        var before = read();
        return new(method, before, dispatch, read, () =>
        {
            if (!Equals(before, read())) throw new NativeFailure("element_state_changed", "UIA pattern state changed during preflight; observe again.");
        });
    }

    private static PreparedUiaAction Prepare(AutomationElement element, UiaPatternRequest request)
    {
        switch (request.Command)
        {
            case "uia-invoke":
                var invoke = Pattern<InvokePattern>(element, InvokePattern.Pattern);
                return new("InvokePattern.Invoke", null, invoke.Invoke, () => null, () => { });
            case "uia-set-value":
                var value = Pattern<ValuePattern>(element, ValuePattern.Pattern);
                void Writable()
                {
                    if (value.Current.IsReadOnly) throw new NativeFailure("value_readonly", "Element ValuePattern is read-only.");
                }
                Writable();
                // Never echo the value or read the existing field value into metadata.
                return new("ValuePattern.SetValue", null, () => value.SetValue(request.Text!), () => null, Writable);
            case "uia-toggle":
                var toggle = Pattern<TogglePattern>(element, TogglePattern.Pattern);
                return Stateful("TogglePattern.Toggle", () => new ToggleSnapshot(toggle.Current.ToggleState.ToString().ToLowerInvariant()), toggle.Toggle);
            case "uia-select":
                var selection = Pattern<SelectionItemPattern>(element, SelectionItemPattern.Pattern);
                Action select = request.SelectionMode switch
                {
                    "replace" => selection.Select, "add" => selection.AddToSelection, "remove" => selection.RemoveFromSelection,
                    _ => throw CommandOptions.Invalid("Unsupported selection operation.")
                };
                return Stateful("SelectionItemPattern." + (request.SelectionMode switch { "replace" => "Select", "add" => "AddToSelection", _ => "RemoveFromSelection" }),
                    () => new SelectionSnapshot(selection.Current.IsSelected), select);
            case "uia-expand-collapse":
                var expand = Pattern<ExpandCollapsePattern>(element, ExpandCollapsePattern.Pattern);
                object ReadExpansion()
                {
                    var state = expand.Current.ExpandCollapseState;
                    if (state == ExpandCollapseState.LeafNode) throw new NativeFailure("unsupported_pattern", "A leaf node cannot expand or collapse.");
                    return new ExpansionSnapshot(state.ToString().ToLowerInvariant());
                }
                return Stateful(request.State == "expanded" ? "ExpandCollapsePattern.Expand" : "ExpandCollapsePattern.Collapse",
                    ReadExpansion, request.State == "expanded" ? expand.Expand : expand.Collapse);
            case "uia-scroll":
                var scroll = Pattern<ScrollPattern>(element, ScrollPattern.Pattern);
                object ReadScroll()
                {
                    var state = scroll.Current;
                    if ((request.Horizontal != "none" && !state.HorizontallyScrollable) || (request.Vertical != "none" && !state.VerticallyScrollable))
                        throw new NativeFailure("scroll_axis_unavailable", "Requested UIA scroll axis is unavailable.");
                    return Snapshot(state.HorizontalScrollPercent, state.VerticalScrollPercent,
                        state.HorizontalViewSize, state.VerticalViewSize, state.HorizontallyScrollable, state.VerticallyScrollable);
                }
                return Stateful("ScrollPattern.Scroll", ReadScroll, () => scroll.Scroll(Amount(request.Horizontal), Amount(request.Vertical)));
            default: throw CommandOptions.Invalid("Unknown UIA operation.");
        }
    }

    private sealed record ToggleSnapshot(string State);
    private sealed record SelectionSnapshot(bool Selected);
    private sealed record ExpansionSnapshot(string State);
    private sealed record ScrollSnapshot(double HorizontalPercent, double VerticalPercent,
        double HorizontalViewSize, double VerticalViewSize, bool HorizontallyScrollable, bool VerticallyScrollable);
    private static ScrollSnapshot Snapshot(double horizontal, double vertical, double width, double height, bool horizontalEnabled, bool verticalEnabled)
    {
        if (!double.IsFinite(horizontal) || !double.IsFinite(vertical) || !double.IsFinite(width) || !double.IsFinite(height) ||
            horizontal < -1 || horizontal > 100 || vertical < -1 || vertical > 100 || width < 0 || width > 100 || height < 0 || height > 100)
            throw new InvalidOperationException("Provider returned invalid scroll percentages.");
        return new(horizontal, vertical, width, height, horizontalEnabled, verticalEnabled);
    }

    private static ScrollAmount Amount(string amount) => amount switch
    {
        "none" => ScrollAmount.NoAmount, "small-increment" => ScrollAmount.SmallIncrement,
        "large-increment" => ScrollAmount.LargeIncrement, "small-decrement" => ScrollAmount.SmallDecrement,
        "large-decrement" => ScrollAmount.LargeDecrement, _ => throw CommandOptions.Invalid("Invalid UIA scroll amount.")
    };

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
