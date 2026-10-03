using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Linq;
using System.Globalization;
using PcuCp.LegacyObservation;

internal static class PrimitiveContractTests
{
    internal static void Run(Action<bool, string> check)
    {
        PatternChecks(check);
        PayloadChecks(check);
        GeometryChecks(check);
        RefinementChecks(check);
        GuardChecks(check);
    }

    private static void PatternChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var primitive = new ObservationPrimitives(p); var node = new Node("one");
        check(primitive.SupportedPattern(null) == null && p.Trace.Count == 0, "Null pattern element must not read");
        node.Patterns.Add(ObservationPattern.Invoke); node.Patterns.Add(ObservationPattern.Toggle);
        check(primitive.SupportedPattern(node) == "InvokePattern", "Invoke pattern has first priority");
        check(Trace(p) == "pattern:one:Invoke", "Successful Invoke must stop pattern reads");
        p.Reset(); p.Fail("pattern:one:Invoke");
        check(primitive.SupportedPattern(node) == "TogglePattern", "Invoke failure must fall through to Toggle");
        check(Trace(p) == "pattern:one:Invoke|pattern:one:Toggle", "Pattern catch and order changed");
        p.Reset(); node.Patterns.Clear(); node.Patterns.Add(ObservationPattern.SelectionItem);
        check(primitive.SupportedPattern(node) == "SelectionItemPattern", "SelectionItem pattern missing");
        check(Trace(p) == "pattern:one:Invoke|pattern:one:Toggle|pattern:one:SelectionItem", "Pattern priority changed");
        p.Reset(); node.Patterns.Clear(); node.Patterns.Add(ObservationPattern.Value);
        check(primitive.SupportedPattern(node) == null && p.Trace.Count == 3, "Value must not be a supported click pattern");
    }

    private static void PayloadChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var primitive = new ObservationPrimitives(p); var node = new Node("one");
        node.Current.Rect = Rect(-2.5, 1.5, 5, 7);
        node.Current.Properties[ObservationProperty.Name] = "  ";
        node.Current.Properties[ObservationProperty.AutomationId] = "auto";
        var payload = primitive.MatchPayload(node.Current, null);
        check(string.Join(",", payload.Keys.Cast<string>()) == "name,automation_id,class_name,role,rect,center,area,is_enabled,is_offscreen,invoke_pattern,preferred_identifier", "Match payload key order");
        check(Trace(p) == "bounds:one|property:one:Name|property:one:AutomationId|property:one:LocalizedControlType|property:one:ClassName|property:one:IsEnabled|property:one:IsOffscreen", "Match payload getter order/cached current changed");
        check((string)payload["preferred_identifier"] == "automation_id" && (string)payload["invoke_pattern"] == "", "Identifier choice/null string binding changed");
        check((int)((OrderedDictionary)payload["rect"])["x"] == -2 && (int)((OrderedDictionary)payload["rect"])["y"] == 2, "Payload rect midpoint-to-even conversion");
        check((int)((OrderedDictionary)payload["center"])["x"] == 0 && (int)((OrderedDictionary)payload["center"])["y"] == 5, "Payload center conversion");
        check((int)payload["area"] == 35, "Payload integer area");
        p.Reset(); node.Current.Properties[ObservationProperty.Name] = "name";
        check((string)primitive.MatchPayload(node.Current, "TogglePattern")["preferred_identifier"] == "name", "Name must precede automation id");
        p.Reset(); node.Current.Properties[ObservationProperty.Name] = null; node.Current.Properties[ObservationProperty.AutomationId] = "\t";
        node.Current.Properties[ObservationProperty.ClassName] = "class";
        check((string)primitive.MatchPayload(node.Current, "")["preferred_identifier"] == "class_name", "Class fallback missing");
        p.Reset(); node.Current.Properties[ObservationProperty.ClassName] = " "; node.Current.Properties[ObservationProperty.LocalizedControlType] = null;
        payload = primitive.MatchPayload(node.Current, "");
        check((string)payload["name"] == "" && payload["role"] == null && (string)payload["preferred_identifier"] == "none", "Null interpolation/uncast role differs from legacy");
        p.Reset();
        foreach (var property in new[] { ObservationProperty.Name, ObservationProperty.AutomationId, ObservationProperty.LocalizedControlType, ObservationProperty.ClassName, ObservationProperty.IsEnabled, ObservationProperty.IsOffscreen }) p.Fail("property:one:" + property);
        payload = primitive.MatchPayload(node.Current, "InvokePattern");
        check((string)payload["name"] == "" && (string)payload["automation_id"] == "" && (string)payload["class_name"] == "" && (string)payload["role"] == "", "Independent text defaults/catches changed");
        check((bool)payload["is_enabled"] && !(bool)payload["is_offscreen"] && p.Trace.Count == 7, "Independent bool defaults/catches changed");
        p.Reset(); p.Fail("bounds:one");
        check(Throws(() => primitive.MatchPayload(node.Current, "")) && Trace(p) == "bounds:one", "Bounds failure must escape before property reads");
        p.Reset(); node.Current.Rect = Rect(0, 0, 50000, 50000);
        check(Throws(() => primitive.MatchPayload(node.Current, "")) && p.Trace.Count == 7, "Area overflow must occur after getter reads");
    }

    private static void GeometryChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var primitive = new ObservationPrimitives(p); var node = new Node("one");
        foreach (var role in new[] { "button", "HYPERLINK", "menu item", "tab", "checkbox", "radio button", "combo", "split button", "pane with button" })
            check(primitive.RoleWeight(role) == 40, "Interactive role weight: " + role);
        foreach (var role in new[] { "edit", "document", "list item", "tree item", "data item", "custom edit" })
            check(primitive.RoleWeight(role) == 18, "Content role weight: " + role);
        foreach (var role in new[] { "pane", "window", "group", "custom" })
            check(primitive.RoleWeight(role) == -8, "Container role weight: " + role);
        check(primitive.RoleWeight(null) == 0 && primitive.RoleWeight("") == 0 && primitive.RoleWeight("단추") == 0, "Unknown/empty role weights");
        var culture = CultureInfo.CurrentCulture;
        try { CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("tr-TR"); check(primitive.RoleWeight("WİNDOW") == -8 && primitive.RoleWeight("EDİT") == 18, "PowerShell -match retains current-culture case folding after invariant lower"); }
        finally { CultureInfo.CurrentCulture = culture; }
        check(primitive.Clamp(0, 0, null) == null && primitive.Clamp(0, 0, new ObservationRect { IsEmpty = true }) == null, "Empty clamp must return null");
        check(primitive.Clamp(0, 0, Rect(0, 0, 0, 4)) == null && primitive.Clamp(0, 0, Rect(0, 0, 3, -1)) == null, "Nonpositive clamp dimensions");
        var point = primitive.Clamp(-100, 100, Rect(-10, -20, 20, 30));
        check(point.X == -7 && point.Y == 7 && point.Source == "center" && !point.NativeClickable, "Inset clamp limits/default tags");
        point = primitive.Clamp(100, 100, Rect(0, 0, 10, 20), -100, "native", true);
        check(point.X == 10 && point.Y == 20 && point.Source == "native" && point.NativeClickable, "Negative inset/right-bottom inclusive bounds");
        point = primitive.Clamp(-100, 100, Rect(0, 0, 2, 2), int.MaxValue);
        check(point.X == 0 && point.Y == 2, "Narrow bounds preserve fractional inset with banker's rounding");
        point = primitive.Clamp(-2.5, 2.5, Rect(-5, -5, 10, 10), 0);
        check(point.X == -2 && point.Y == 2, "Signed midpoint-to-even clamp");
        check(Throws(() => primitive.Clamp(double.NaN, 0, Rect(0, 0, 20, 20))), "Nonfinite clamp conversion must escape");
        check(primitive.PreferredClickPoint(null, node.Current.Rect) == null && primitive.PreferredClickPoint(node, null) == null && p.Trace.Count == 0, "Preferred point null gate must not read");
        check(primitive.PreferredClickPoint(node, new ObservationRect { IsEmpty = true }) == null && p.Trace.Count == 0, "Preferred point empty gate must not read");
        node.Clickable = true; node.ClickX = -100; node.ClickY = 100;
        point = primitive.PreferredClickPoint(node, Rect(0, 0, 20, 20));
        check(point.X == 3 && point.Y == 17 && point.NativeClickable && point.Source == "clickable_point", "Native clickable point must be clamped");
        p.Reset(); p.Fail("clickable:one"); point = primitive.PreferredClickPoint(node, Rect(0, 0, 5, 5));
        check(point.X == 2 && point.Y == 2 && !point.NativeClickable && point.Source == "rect_center", "Clickable exception must fall back to rounded center");
        p.Reset(); node.Clickable = false; point = primitive.PreferredClickPoint(node, Rect(1, 1, 5, 5));
        check(point.X == 4 && point.Y == 4 && !point.NativeClickable, "False clickable must fall back to center");
        p.Reset(); node.Clickable = true; node.ClickX = double.NaN; node.ClickY = 1;
        point = primitive.PreferredClickPoint(node, Rect(0, 0, 10, 10));
        check(point.X == 5 && point.Y == 5 && point.Source == "rect_center", "Native clamp error is inside preferred-point catch");
        p.Reset(); check(primitive.PreferredClickPoint(node, Rect(0, 0, 0, 10)) == null && Trace(p) == "clickable:one", "Zero width must still attempt clickable read");
    }

    private static void RefinementChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var primitive = new ObservationPrimitives(p);
        p.Available = false;
        check(primitive.ResolvePoint(0, 0) == null && Trace(p) == "ensure-uia", "Unavailable UIA must return without reads");
        p.Reset(); p.Available = true; p.Fail("ensure-uia");
        check(Throws(() => primitive.ResolvePoint(0, 0)) && p.Trace.Count == 1, "EnsureUia thrown error must escape");
        p.Reset(); p.Fail("from-point:0:0");
        check(primitive.ResolvePoint(0, 0) == null && Trace(p) == "ensure-uia|from-point:0:0", "FromPoint failure catch changed");
        p.Reset();
        check(primitive.ResolvePoint(0, 0) == null && p.Trace.Count == 2, "Null FromPoint must not acquire walker");
        var first = new Node("first"); p.PointNode = first; first.Patterns.Add(ObservationPattern.Invoke);
        p.Reset(); p.Fail("control-walker");
        check(Throws(() => primitive.ResolvePoint(0, 0)) && p.Trace.Count == 3, "Walker acquisition must escape traversal catch");
        p.Reset(); var result = primitive.ResolvePoint(-1, 2);
        check(result.Score == 170 && result.Depth == 0 && result.X == 10 && result.Y == 10 && result.PatternName == "InvokePattern", "Base refinement scoring/point");
        check(Trace(p) == "ensure-uia|from-point:-1:2|control-walker|current:first|bounds:first|pattern:first:Invoke|property:first:LocalizedControlType|property:first:IsEnabled|property:first:IsOffscreen|clickable:first|bounds:first|property:first:Name|property:first:AutomationId|property:first:LocalizedControlType|property:first:ClassName|property:first:IsEnabled|property:first:IsOffscreen|parent:first", "Refinement getter order/identity/re-reads changed");
        check(p.WalkerIdentityPreserved && p.CurrentIdentityPreserved, "Acquisition identity lost");
        p.Reset(); p.Fail("current:first");
        check(primitive.ResolvePoint(0, 0) == null && !p.Trace.Contains("parent:first"), "Current failure must break before parent");
        p.Reset(); p.Fail("bounds:first");
        check(primitive.ResolvePoint(0, 0) == null && !p.Trace.Contains("parent:first"), "Bounds failure must break before parent");
        p.Reset(); p.Fail("bounds:first", 2);
        check(primitive.ResolvePoint(0, 0) == null && !p.Trace.Contains("parent:first"), "Payload bounds failure must discard candidate and break");
        p.Reset(); p.Fail("parent:first");
        check(primitive.ResolvePoint(0, 0).Score == 170, "Parent read failure must preserve existing best");
        p.Reset(); first.Current.Rect = Rect(0, 0, 1, 20);
        check(primitive.ResolvePoint(0, 0) == null && Trace(p) == "ensure-uia|from-point:0:0|control-walker|current:first|bounds:first|parent:first", "Invalid rect should skip reads but still traverse parent");
        first.Current.Rect = Rect(0, 0, 20, 20);
        var middle = new Node("middle"); var later = new Node("later"); first.Parent = middle; middle.Parent = later;
        middle.Current.Properties[ObservationProperty.LocalizedControlType] = "pane";
        later.Patterns.Add(ObservationPattern.Invoke); later.Clickable = true; later.ClickX = 12; later.ClickY = 13;
        p.Reset(); result = primitive.ResolvePoint(0, 0);
        check(result.Depth == 0 && result.Score == 170 && result.X == 10, "Equal-score later candidate must not replace first");
        first.Patterns.Clear(); p.Reset(); result = primitive.ResolvePoint(0, 0);
        check(result.Depth == 2 && result.Score == 170 && result.NativeClickable && result.X == 12, "Strictly better ancestor selection/native bonus/depth penalty");
        first.Parent = null; first.Patterns.Add(ObservationPattern.Invoke); first.Current.Properties[ObservationProperty.IsEnabled] = false; first.Current.Properties[ObservationProperty.IsOffscreen] = true;
        p.Reset(); result = primitive.ResolvePoint(0, 0);
        check(result.Score == 60, "Disabled/offscreen score penalties");
        first.Current.Properties[ObservationProperty.IsEnabled] = true; first.Current.Properties[ObservationProperty.IsOffscreen] = false;
        first.Current.Rect = Rect(0, 0, 360, 220); p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 160, "Inclusive bounded dimensions and no small-area bonus");
        first.Current.Rect = Rect(0, 0, 361, 220); p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 85, "Unbounded size penalty");
        first.Current.Properties[ObservationProperty.LocalizedControlType] = "unknown"; p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 45, "Threshold 45 must remain inclusive");
        first.Current.Properties[ObservationProperty.LocalizedControlType] = "pane"; p.Reset();
        check(primitive.ResolvePoint(0, 0) == null && p.Trace.Contains("clickable:first") && p.Trace.Count(x => x == "bounds:first") == 1, "Below threshold still attempts click point but not payload");
        first.Current.Properties[ObservationProperty.LocalizedControlType] = "button";
        first.Current.Rect = Rect(0, 0, 600, 200); p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 85, "Large-area penalty must be strictly over 120000");
        first.Current.Rect = Rect(0, 0, 601, 200); p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 55, "Large-area score penalty");
        first.Current.Rect = Rect(0, 0, 40, 20); p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 170, "Small-area bonus includes 800");
        first.Current.Rect = Rect(0, 0, 40.1, 20); p.Reset();
        check(primitive.ResolvePoint(0, 0).Score == 160, "Small-area bonus stops above 800");
        first.Current.Rect = Rect(0, 0, 20, 20); first.Current.Properties[ObservationProperty.LocalizedControlType] = "button";
        p.Reset(); p.Fail("property:first:IsEnabled"); p.Fail("property:first:IsOffscreen");
        check(primitive.ResolvePoint(0, 0).Score == 170, "Refinement bool getter failures retain defaults");
        p.Reset(); p.Fail("clickable:first");
        result = primitive.ResolvePoint(0, 0);
        check(result.Score == 170 && !result.NativeClickable, "Clickable failure retains center candidate without bonus");
        p.Reset(); p.Fail("property:first:LocalizedControlType");
        check(primitive.ResolvePoint(0, 0).Score == 130, "Refinement role getter failure retains empty default");
        p.Reset(); var node = first;
        for (var i = 1; i <= 6; i++) { node.Parent = new Node("depth" + i); node = node.Parent; node.Patterns.Add(ObservationPattern.Invoke); }
        result = primitive.ResolvePoint(0, 0);
        check(p.Trace.Count(x => x.StartsWith("current:", StringComparison.Ordinal)) == 6 && p.Trace.Contains("current:depth5") && !p.Trace.Contains("current:depth6"), "Traversal must read only depth 0 through 5");
        check(p.Trace.Contains("parent:depth5") && p.Trace.Count(x => x == "control-walker") == 1, "Depth5 parent read/one-time walker acquisition changed");
        p.Reset(); p.Fail("current:depth1");
        check(primitive.ResolvePoint(0, 0).Depth == 0 && !p.Trace.Contains("current:depth2"), "Broken ancestor must stop, not continue");
    }

    private static void GuardChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var primitive = new ObservationPrimitives(p);
        var guard = primitive.TestTarget(0, -1, 42, "Title");
        check(!guard.matched && guard.actual_hwnd == 0 && guard.actual_root_hwnd == 0 && guard.actual_title == "" && guard.reason == "no_window_at_coords", "No-window guard payload");
        check(Trace(p) == "window-point:0:-1", "No-window guard must stop before root/title");
        p.ChildHwnd = 11; p.RootHwnd = 22; p.Title = "A Mixed TITLE"; p.Reset();
        guard = primitive.TestTarget(-2, 0, 22, "unmatched");
        check(guard.matched && guard.reason == "" && guard.actual_hwnd == 11 && guard.actual_root_hwnd == 22, "ExpectedHwnd must win over title");
        check(Trace(p) == "window-point:-2:0|root:11|title:22:256", "Guard Win32 read order/capacity");
        p.Reset(); guard = primitive.TestTarget(0, 0, 23, "title");
        check(!guard.matched && guard.reason == "hwnd_mismatch", "Matching title must not override hwnd mismatch");
        p.Reset(); check(primitive.TestTarget(0, 0, 0, "mixed title").matched, "Title guard must use invariant case-insensitive substring");
        p.Reset(); guard = primitive.TestTarget(0, 0, -1, "missing");
        check(!guard.matched && guard.reason == "title_mismatch", "Negative hwnd must use title branch");
        p.Reset(); check(primitive.TestTarget(0, 0, 0, "").matched, "Absent guard passes existing window");
        p.Reset(); p.RootHwnd = 0; check(primitive.TestTarget(0, 0, 0, null).actual_root_hwnd == 0 && p.Trace.Contains("title:0:256"), "Zero root must not fall back to child");
        p.Reset(); p.Title = ""; guard = primitive.TestTarget(0, 0, 0, " ");
        check(!guard.matched && guard.reason == "title_mismatch", "Whitespace target is specified, not absent");
        p.Reset(); p.Fail("root:11"); check(Throws(() => primitive.TestTarget(0, 0, 0, "")), "Guard acquisition failures must escape");
    }

    private static ObservationRect Rect(double x, double y, double width, double height) { return new ObservationRect { X = x, Y = y, Width = width, Height = height }; }
    private static string Trace(InertProvider p) { return string.Join("|", p.Trace); }
    private static bool Throws(Action action) { try { action(); return false; } catch { return true; } }

    private sealed class Node
    {
        internal readonly string Name;
        internal readonly NodeCurrent Current;
        internal readonly HashSet<ObservationPattern> Patterns = new HashSet<ObservationPattern>();
        internal Node Parent;
        internal bool Clickable;
        internal double ClickX, ClickY;
        internal Node(string name) { Name = name; Current = new NodeCurrent(this); }
    }

    private sealed class NodeCurrent
    {
        internal readonly Node Element;
        internal ObservationRect Rect = PrimitiveContractTests.Rect(0, 0, 20, 20);
        internal readonly Dictionary<ObservationProperty, object> Properties = new Dictionary<ObservationProperty, object>();
        internal NodeCurrent(Node element)
        {
            Element = element;
            Properties[ObservationProperty.Name] = element.Name;
            Properties[ObservationProperty.AutomationId] = "";
            Properties[ObservationProperty.ClassName] = "";
            Properties[ObservationProperty.LocalizedControlType] = "button";
            Properties[ObservationProperty.IsEnabled] = true;
            Properties[ObservationProperty.IsOffscreen] = false;
        }
    }

    // Synthetic objects only: these tests never load or query Windows/UIA.
    private sealed class InertProvider : IObservationProvider
    {
        internal readonly List<string> Trace = new List<string>();
        private readonly Dictionary<string, int> counts = new Dictionary<string, int>();
        private readonly Dictionary<string, int> failures = new Dictionary<string, int>();
        private readonly object walker = new object();
        internal bool Available = true, WalkerIdentityPreserved = true, CurrentIdentityPreserved = true;
        internal Node PointNode;
        internal long ChildHwnd, RootHwnd;
        internal string Title = "";
        internal void Fail(string operation, int occurrence = 1) { failures[operation] = occurrence; }
        internal void Reset() { Trace.Clear(); counts.Clear(); failures.Clear(); }
        private void Record(string operation)
        {
            Trace.Add(operation);
            int count; counts.TryGetValue(operation, out count); counts[operation] = ++count;
            int fail; if (failures.TryGetValue(operation, out fail) && count == fail) throw new InvalidOperationException(operation);
        }
        public bool EnsureUia() { Record("ensure-uia"); return Available; }
        public long WindowFromPoint(int x, int y) { Record("window-point:" + x + ":" + y); return ChildHwnd; }
        public long RootAncestor(long hwnd) { Record("root:" + hwnd); return RootHwnd; }
        public string WindowText(long hwnd, int capacity) { Record("title:" + hwnd + ":" + capacity); return Title; }
        public object FromPoint(int x, int y) { Record("from-point:" + x + ":" + y); return PointNode; }
        public object Current(object element) { var node = (Node)element; Record("current:" + node.Name); return node.Current; }
        public ObservationRect Bounds(object current)
        {
            var value = (NodeCurrent)current; CurrentIdentityPreserved &= ReferenceEquals(value, value.Element.Current);
            Record("bounds:" + value.Element.Name); return value.Rect;
        }
        public object Property(object current, ObservationProperty property)
        {
            var value = (NodeCurrent)current; CurrentIdentityPreserved &= ReferenceEquals(value, value.Element.Current);
            Record("property:" + value.Element.Name + ":" + property); return value.Properties[property];
        }
        public object Pattern(object element, ObservationPattern pattern) { var node = (Node)element; Record("pattern:" + node.Name + ":" + pattern); return node.Patterns.Contains(pattern) ? node : null; }
        public bool ClickablePoint(object element, out double x, out double y) { var node = (Node)element; Record("clickable:" + node.Name); x = node.ClickX; y = node.ClickY; return node.Clickable; }
        public object ControlViewWalker() { Record("control-walker"); return walker; }
        public object Parent(object providedWalker, object element)
        {
            WalkerIdentityPreserved &= ReferenceEquals(walker, providedWalker);
            var node = (Node)element; Record("parent:" + node.Name); return node.Parent;
        }
        public string WindowClass(long hwnd, int capacity) { throw new NotSupportedException(); }
        public uint ProcessId(long hwnd) { throw new NotSupportedException(); }
        public string ProcessName(uint processId) { throw new NotSupportedException(); }
        public int SystemMetric(int index) { throw new NotSupportedException(); }
        public IEnumerable<ObservationWindow> TopLevelWindows() { throw new NotSupportedException(); }
        public object FromHandle(long hwnd) { throw new NotSupportedException(); }
        public IEnumerable<object> Descendants(object element) { throw new NotSupportedException(); }
        public bool ValueReadOnly(object pattern) { throw new NotSupportedException(); }
    }
}
