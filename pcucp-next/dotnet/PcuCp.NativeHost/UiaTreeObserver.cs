using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Automation;

internal sealed record UiaNode(string Name, string ControlType, string AutomationId, string ClassName, int ProcessId,
    string NativeWindowHandle, RectInfo? BoundingRectangle, IReadOnlyList<string> Patterns, IReadOnlyList<UiaNode> Children, string? ElementRef, IReadOnlyDictionary<string, object> PatternStates);

internal static class UiaTreeObserver
{
    public static NativeResult Observe(CommandOptions options)
    {
        options.Allow("--hwnd", "--pid", "--max-depth", "--max-nodes", "--deadline-ms");
        if (options.Has("--pid") && !options.Has("--hwnd")) throw CommandOptions.Invalid("--pid requires --hwnd for UIA observation.");
        var maxDepth = options.Integer("--max-depth", 1, 0, 12);
        var maxNodes = options.Integer("--max-nodes", 200, 1, 2000);
        var deadline = options.Integer("--deadline-ms", 1500, 50, 10000);
        UiaElementActions.BeginObservation();
        var context = new Context(maxDepth, maxNodes, deadline);
        var nodes = new List<UiaNode>();
        WindowTarget? target = null;
        try
        {
            if (options.Has("--hwnd"))
            {
                target = WindowTarget.Read(options, false);
                context.Target = target;
                var root = AutomationElement.FromHandle(target.Hwnd);
                if (root is null) throw new NativeFailure("uia_target_unavailable", "UIA could not resolve the target window.");
                var node = context.Read(root, 0);
                if (node is not null) nodes.Add(node);
                target.Validate(false);
            }
            else
            {
                var walker = TreeWalker.ControlViewWalker;
                var child = walker.GetFirstChild(AutomationElement.RootElement);
                while (child is not null && context.CanContinue())
                {
                    var node = context.Read(child, 0);
                    if (node is not null) nodes.Add(node);
                    if (!context.CanContinue()) break;
                    child = walker.GetNextSibling(child);
                }
            }
        }
        catch (Exception ex) when (IsProviderFailure(ex)) { context.Error("uia_provider_error", ex.Message); }
        if (context.Errors.Count > 0) UiaElementActions.Invalidate();
        return NativeResult.Observation("uia-tree", new
        {
            max_depth = maxDepth, max_nodes = maxNodes, deadline_ms = deadline, nodes, count = nodes.Count,
            total_nodes = context.Count, target = target?.Identity, truncated = context.Truncated,
            deadline_semantics = "best_effort_between_provider_calls; caller process timeout is the hard bound"
        }, context.Errors);
    }

    private static bool IsProviderFailure(Exception ex) => ex is ElementNotAvailableException or InvalidOperationException or COMException or UnauthorizedAccessException or System.ComponentModel.Win32Exception;

    private sealed class Context(int maxDepth, int maxNodes, int deadline)
    {
        private readonly Stopwatch clock = Stopwatch.StartNew();
        public WindowTarget? Target { get; set; }
        public int Count { get; private set; }
        public bool Truncated { get; private set; }
        public List<NativeError> Errors { get; } = [];
        public void Error(string code, string message)
        {
            if (Errors.Count < 20 && !Errors.Any(error => error.Code == code && error.Message == message)) Errors.Add(new NativeError(code, message));
        }
        public bool CanContinue()
        {
            if (Count >= maxNodes) { Truncated = true; Error("node_limit", "UIA node budget reached."); return false; }
            if (clock.ElapsedMilliseconds >= deadline) { Truncated = true; Error("deadline_reached", "UIA best-effort deadline reached."); return false; }
            return true;
        }
        public UiaNode? Read(AutomationElement element, int depth)
        {
            if (!CanContinue()) return null;
            Count++;
            try
            {
                var current = element.Current;
                var name = current.Name ?? string.Empty;
                var type = current.ControlType.ProgrammaticName.Replace("ControlType.", "", StringComparison.Ordinal);
                var id = current.AutomationId ?? string.Empty;
                var className = current.ClassName ?? string.Empty;
                var pid = current.ProcessId;
                var handle = $"0x{unchecked((uint)current.NativeWindowHandle):X}";
                var rect = current.BoundingRectangle;
                RectInfo? geometry = rect.IsEmpty ? null : new RectInfo(rect.X, rect.Y, rect.Width, rect.Height);
                string[] patterns = [];
                try
                {
                    patterns = element.GetSupportedPatterns().Select(pattern => pattern.ProgrammaticName.Replace("PatternIdentifiers.Pattern", "", StringComparison.Ordinal).Replace("Pattern.Pattern", "", StringComparison.Ordinal).Replace("Identifiers.Pattern", "", StringComparison.Ordinal).Replace("Pattern", "", StringComparison.Ordinal).Replace(".", "", StringComparison.Ordinal))
                        .Where(value => value.Length > 0).Distinct().OrderBy(value => value, StringComparer.Ordinal).ToArray();
                }
                catch (Exception ex) when (IsProviderFailure(ex)) { Error("uia_patterns_unavailable", ex.Message); }
                var children = new List<UiaNode>();
                if (depth < maxDepth && CanContinue())
                {
                    try
                    {
                        var walker = TreeWalker.ControlViewWalker;
                        var child = walker.GetFirstChild(element);
                        while (child is not null && CanContinue())
                        {
                            var node = Read(child, depth + 1);
                            if (node is not null) children.Add(node);
                            if (!CanContinue()) break;
                            child = walker.GetNextSibling(child);
                        }
                    }
                    catch (Exception ex) when (IsProviderFailure(ex)) { Error("uia_children_unavailable", ex.Message); }
                }
                var states = UiaElementActions.ReadPatternStates(element, patterns);
                var reference = UiaElementActions.Register(element, Target, states);
                return new UiaNode(name, type, id, className, pid, handle, geometry, patterns, children, reference, states);
            }
            catch (Exception ex) when (IsProviderFailure(ex)) { Error("uia_element_unavailable", ex.Message); return null; }
        }
    }
}
