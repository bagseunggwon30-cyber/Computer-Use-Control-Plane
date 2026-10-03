using System;
using System.Collections.Generic;
using System.Collections.Specialized;
namespace PcuCp.LegacyObservation {
    // Closed read-only boundary. No input, pattern execution, callbacks, caches or element reconstruction.
    public enum ObservationProperty { Name, AutomationId, HelpText, AccessKey, ClassName, LocalizedControlType, IsEnabled, IsOffscreen }
    public enum ObservationPattern { Invoke, Toggle, SelectionItem, Value }
    public sealed class ObservationRect { public double X, Y, Width, Height; public bool IsEmpty; }
    public sealed class ObservationWindow { public long Hwnd; public string Title; public bool Foreground; }
    public sealed class ObservationPoint { public int X, Y; public string Source; public bool NativeClickable; }
    public sealed class ObservationRefinement { public int X, Y, Score, Depth; public string PatternName, Role; public double Area; public string PointSource; public bool NativeClickable; public OrderedDictionary Match; }
    public sealed class ObservationGuard { public bool matched; public long actual_hwnd, actual_root_hwnd; public string actual_title, reason; }
    public sealed class ObservationResult { public OrderedDictionary Payload; public int ExitCode; public ObservationResult(OrderedDictionary payload, int exitCode = 0) { Payload = payload; ExitCode = exitCode; } }
    public sealed class ObservationOptions {
        public bool HasCoordinates, SkipUia;
        public int X, Y, TargetHwnd, ClickInset = 3, ScanRadius, ScanStep = 6, MaxElements = 400, MinSize = 6;
        public string TargetMatch = "", Match = "", Label = "", Role = "";
    }
    public interface IObservationProvider {
        bool EnsureUia();
        long WindowFromPoint(int x, int y);
        long RootAncestor(long hwnd);
        string WindowText(long hwnd, int capacity);
        string WindowClass(long hwnd, int capacity);
        uint ProcessId(long hwnd);
        string ProcessName(uint processId);
        int SystemMetric(int index);
        IEnumerable<ObservationWindow> TopLevelWindows();
        object FromPoint(int x, int y);
        object FromHandle(long hwnd);
        IEnumerable<object> Descendants(object element);
        object Current(object element);
        ObservationRect Bounds(object current);
        object Property(object current, ObservationProperty property);
        object Pattern(object element, ObservationPattern pattern);
        bool ValueReadOnly(object pattern);
        bool ClickablePoint(object element, out double x, out double y);
        object ControlViewWalker();
        object Parent(object walker, object element);
    }
    public static class ObservationData {
        public static OrderedDictionary Map(params object[] values) { var result = new OrderedDictionary(); for (int i=0;i<values.Length;i+=2) result.Add((string)values[i],values[i+1]); return result; }
        public static int Integer(double value) { return checked((int)Math.Round(value, MidpointRounding.ToEven)); }
        public static string Text(object value) { return value == null ? "" : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture); }
        public static OrderedDictionary Rect(ObservationRect r) { return Map("x",Integer(r.X),"y",Integer(r.Y),"width",Integer(r.Width),"height",Integer(r.Height)); }
        public static OrderedDictionary Center(ObservationRect r) { return Map("x",Integer(r.X+r.Width/2),"y",Integer(r.Y+r.Height/2)); }
    }
}
