using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace PcuCp.LegacyHelper
{
    // The provider vocabulary is closed by the real provider. No input, process,
    // arbitrary expression, arbitrary file-read or remote execution operations.
    public interface ILegacyHelperProvider
    {
        object Invoke(string operation, params object[] arguments);
        void EnumerateWindows(Action<long> visit);
    }

    // Fixture exhaustion is a harness defect, never a simulated desktop error.
    public sealed class LegacyHelperFixtureException : Exception
    {
        public LegacyHelperFixtureException(string message) : base(message) { }
    }

    public sealed class LegacyHelperActions
    {
        private readonly ILegacyHelperProvider provider;
        private readonly Func<DateTime> utcNow;
        private readonly int pid;
        private readonly string pipeName;
        private object ocrEngine;
        private string ocrError;
        public DateTime StartedAt { get; private set; }
        public int RequestCount { get; private set; }
        public bool Win32Loaded { get; private set; }
        public bool UiaLoaded { get; private set; }
        public bool OcrWarm { get { return ocrEngine != null; } }

        public LegacyHelperActions(ILegacyHelperProvider provider, int pid, string pipeName, Func<DateTime> utcNow)
        {
            this.provider = provider ?? throw new ArgumentNullException(nameof(provider));
            this.utcNow = utcNow ?? throw new ArgumentNullException(nameof(utcNow));
            this.pid = pid;
            this.pipeName = pipeName;
            StartedAt = utcNow();
        }

        public Dictionary<string, object> Dispatch(string action, IDictionary<string, object> args)
        {
            RequestCount++;
            if (args != null)
            {
                // The server assigns JSON argument properties to a PS hashtable.
                // Case variants collide and the later assignment wins.
                var normalized = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
                foreach (var pair in args) normalized[pair.Key] = pair.Value;
                args = normalized;
            }
            // PowerShell switch string cases are case-insensitive, with no trim.
            if (string.Equals(action, "windows", StringComparison.OrdinalIgnoreCase)) return Windows(args);
            if (string.Equals(action, "health", StringComparison.OrdinalIgnoreCase)) return Health();
            if (string.Equals(action, "focused", StringComparison.OrdinalIgnoreCase)) return Focused();
            if (string.Equals(action, "modal-detect", StringComparison.OrdinalIgnoreCase)) return Modal();
            if (string.Equals(action, "ocr-screen-fast", StringComparison.OrdinalIgnoreCase)) return Ocr(args);
            if (string.Equals(action, "uia-find-fast", StringComparison.OrdinalIgnoreCase)) return Uia(args);
            if (string.Equals(action, "shutdown", StringComparison.OrdinalIgnoreCase)) return Map("status", "ok", "shutting_down", true);
            return Map("status", "fallback_required", "reason", "action_not_supported_in_server", "action", action,
                "recommended_action", "wrapper should fall back to child process for this action");
        }

        private object Call(string operation, params object[] args) { return provider.Invoke(operation, args); }
        private static bool Recoverable(Exception error) { return !(error is LegacyHelperFixtureException); }
        public static Dictionary<string, object> Map(params object[] pairs)
        {
            var result = new Dictionary<string, object>(StringComparer.Ordinal);
            for (int i = 0; i < pairs.Length; i += 2) result.Add((string)pairs[i], pairs[i + 1]);
            return result;
        }
        private static Dictionary<string, object> Error(string reason) { return Map("status", "error", "reason", reason); }
        private static Dictionary<string, object> Error(string reason, string detail) { return Map("status", "error", "reason", reason, "detail", detail); }
        internal static object Property(IDictionary<string, object> value, string name)
        {
            if (value == null) return null;
            object found;
            if (value.TryGetValue(name, out found)) return found;
            foreach (var pair in value) if (string.Equals(pair.Key, name, StringComparison.OrdinalIgnoreCase)) return pair.Value;
            return null;
        }
        private static object Field(object value, string name) { return Property(value as IDictionary<string, object>, name); }
        private static IEnumerable<object> Items(object value)
        {
            var enumerable = value as IEnumerable;
            if (enumerable == null || value is string || value is IDictionary) return Enumerable.Empty<object>();
            return enumerable.Cast<object>();
        }
        // Covers JSON primitives and JSON arrays, including PS's one-item array rule.
        internal static bool Truth(object value)
        {
            if (value == null) return false;
            if (value is bool) return (bool)value;
            if (value is string) return ((string)value).Length > 0;
            var list = value as IList;
            if (list != null) return list.Count > 1 || (list.Count == 1 && Truth(list[0]));
            switch (Type.GetTypeCode(value.GetType()))
            {
                case TypeCode.Byte: case TypeCode.SByte: case TypeCode.Int16: case TypeCode.UInt16:
                case TypeCode.Int32: case TypeCode.UInt32: case TypeCode.Int64: case TypeCode.UInt64:
                case TypeCode.Single: case TypeCode.Double: case TypeCode.Decimal:
                    return Convert.ToDouble(value, CultureInfo.InvariantCulture) != 0;
                default: return true;
            }
        }
        internal static string Text(object value)
        {
            if (value == null) return "";
            var list = value as IList;
            if (list != null) return string.Join(" ", list.Cast<object>().Select(Text));
            if (value is IDictionary)
            {
                var entries = new List<string>();
                var cursor = ((IDictionary)value).GetEnumerator();
                while (cursor.MoveNext()) entries.Add(Text(cursor.Key) + "=" + Text(cursor.Value));
                return "@{" + string.Join("; ", entries) + "}";
            }
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }
        private static string ArgumentText(IDictionary<string, object> args, string name)
        { var value = Property(args, name); return Truth(value) ? Text(value) : null; }
        internal static int Integer(object value)
        {
            if (value == null) return 0;
            var text = value as string;
            if (text != null)
            {
                text = text.Trim();
                if (text.Length == 0) return 0;
                if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) return checked((int)Convert.ToInt64(text.Substring(2), 16));
                return Convert.ToInt32(double.Parse(text, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture));
            }
            return Convert.ToInt32(value, CultureInfo.InvariantCulture);
        }
        private static long Long(object value) { return Convert.ToInt64(value, CultureInfo.InvariantCulture); }
        private static double Number(object value) { return Convert.ToDouble(value, CultureInfo.InvariantCulture); }
        private static Regex Literal(string text) { return new Regex(Regex.Escape(text), RegexOptions.IgnoreCase); }
        private bool EnsureWin32()
        {
            if (Win32Loaded) return true;
            try { Call("win32.ensure"); Win32Loaded = true; return true; }
            catch (Exception error) when (Recoverable(error)) { return false; }
        }
        private bool EnsureUia()
        {
            if (UiaLoaded) return true;
            try { Call("uia.load"); UiaLoaded = true; return true; }
            catch (Exception error) when (Recoverable(error)) { return false; }
        }
        private bool EnsureOcr()
        {
            if (ocrEngine != null) return true;
            try
            {
                Call("ocr.initialize");
                var engine = Call("ocr.createProfile");
                if (engine == null)
                {
                    var languages = Items(Call("ocr.languages")).ToList();
                    if (languages.Count > 0) engine = Call("ocr.createLanguage", languages[0]);
                }
                if (engine == null) { ocrError = "no_ocr_language_available"; return false; }
                ocrEngine = engine;
                return true;
            }
            catch (Exception error) when (Recoverable(error)) { ocrError = error.Message; return false; }
        }
        private static object Difference(int right, int left)
        {
            long result = (long)right - left;
            if (result >= int.MinValue && result <= int.MaxValue) return (int)result;
            return (double)result;
        }
        private object WindowRect(long hwnd)
        {
            var rect = Call("win32.rect", hwnd);
            int left = Integer(Field(rect, "left")), top = Integer(Field(rect, "top"));
            return Map("x", left, "y", top, "w", Difference(Integer(Field(rect, "right")), left), "h", Difference(Integer(Field(rect, "bottom")), top));
        }
        private Dictionary<string, object> Windows(IDictionary<string, object> args)
        {
            if (!EnsureWin32()) return Error("win32_unavailable");
            string match = ArgumentText(args, "Match");
            Regex rx = null;
            if (!string.IsNullOrEmpty(match)) try { rx = Literal(match); } catch (ArgumentException) { }
            var windows = new List<object>();
            provider.EnumerateWindows(hwnd =>
            {
                if (!Truth(Call("win32.visible", hwnd))) return;
                int length = Integer(Call("win32.titleLength", hwnd));
                if (length <= 0) return;
                string title = Text(Call("win32.title", hwnd, checked(length + 1)));
                if (title.Length == 0) return;
                string clazz = Text(Call("win32.class", hwnd, 256));
                int process = Integer(Call("win32.pid", hwnd));
                if (rx == null || rx.IsMatch(title))
                    windows.Add(Map("hwnd", hwnd, "title", title, "class", clazz, "pid", process, "rect", WindowRect(hwnd)));
            });
            long fg = Long(Call("win32.foreground"));
            object foreground = null;
            if (fg != 0)
            {
                int length = Integer(Call("win32.titleLength", fg));
                if (length > 0) foreground = Map("hwnd", fg, "title", Text(Call("win32.title", fg, checked(length + 1))));
            }
            return Map("status", "ok", "schema", "cucp.observation/v1", "kind", "windows", "sources", new[] { "win32_helper_server" },
                "foreground", foreground, "windows", windows.ToArray(), "count", windows.Count);
        }
        private Dictionary<string, object> Health()
        {
            return Map("status", "ok", "schema", "cucp.health/v1", "helper_mode", "persistent_server", "pid", pid, "pipe_name", pipeName,
                "uptime_s", Integer((utcNow() - StartedAt).TotalSeconds), "request_count", RequestCount, "win32_loaded", Win32Loaded);
        }
        private Dictionary<string, object> Focused()
        {
            if (!EnsureWin32()) return Error("win32_unavailable");
            long fg = Long(Call("win32.foreground"));
            if (fg == 0) return Map("status", "partial", "reason", "no_foreground");
            string title = Text(Call("win32.title", fg, 512)), clazz = Text(Call("win32.class", fg, 256));
            int process = Integer(Call("win32.pid", fg));
            return Map("status", "ok", "schema", "cucp.focused/v1", "hwnd", fg, "title", title, "class", clazz, "pid", process, "rect", WindowRect(fg));
        }
        private static object[] Sort(List<Dictionary<string, object>> values)
        { return values.OrderByDescending(x => Integer(x["score"])).Cast<object>().ToArray(); }
        private Dictionary<string, object> Modal()
        {
            // Modal's assembly loading is separate from the successful-only UIA cache.
            Call("uia.loadModal");
            if (!EnsureWin32()) return Error("win32_unavailable");
            object foreground = null;
            var candidates = new List<Dictionary<string, object>>();
            try
            {
                long fg = Long(Call("win32.foreground"));
                if (fg != 0) foreground = Map("hwnd", fg, "title", Text(Call("win32.title", fg, 512)), "class", Text(Call("win32.class", fg, 256)));
            }
            catch (Exception error) when (Recoverable(error)) { }
            try
            {
                var root = Call("uia.root");
                foreach (var element in Items(Call("uia.children", root, "window-or-pane")))
                {
                    try
                    {
                        string name = Text(Call("uia.name", element)), clazz = Text(Call("uia.class", element));
                        var rect = Call("uia.rect", element);
                        bool modal = false;
                        try { modal = Truth(Call("uia.isModal", element)); } catch (Exception error) when (Recoverable(error)) { }
                        int score = 0; string reason = null;
                        if (modal) { score += 100; reason = "uia_window_is_modal"; }
                        if (Regex.IsMatch(clazz, "(?i)#32770|MessageBox|Dialog|TaskDialog|Popup"))
                        { score += 60; if (reason == null) reason = "dialog_class_name"; }
                        double width = Number(Field(rect, "width")), height = Number(Field(rect, "height"));
                        if (rect != null && width > 0 && width < 900 && height > 0 && height < 600)
                        { score += 20; if (reason == null) reason = "small_window_size"; }
                        if (score > 0)
                        {
                            object hwnd = null;
                            try { hwnd = Integer(Call("uia.handle", element)); } catch (Exception error) when (Recoverable(error)) { }
                            candidates.Add(Map("hwnd", hwnd, "title", name, "class", clazz, "score", score, "reason", reason, "is_modal", modal));
                        }
                    }
                    catch (Exception error) when (Recoverable(error)) { }
                }
            }
            catch (Exception error) when (Recoverable(error)) { }
            var sorted = Sort(candidates);
            string recommendation = "observe";
            if (sorted.Length > 0)
            {
                var top = (Dictionary<string, object>)sorted[0];
                recommendation = Truth(top["is_modal"]) || Integer(top["score"]) >= 100 ? "dismiss_or_confirm" : Integer(top["score"]) >= 60 ? "confirm_dialog" : "wait";
            }
            return Map("status", "ok", "schema", "cucp.modal-detect/v1", "foreground", foreground, "modal_candidates", sorted,
                "candidate_count", sorted.Length, "recommended_action", recommendation);
        }
        private Dictionary<string, object> Ocr(IDictionary<string, object> args)
        {
            if (!EnsureWin32()) return Error("win32_unavailable");
            if (!EnsureOcr()) return Error("ocr_init_failed", ocrError);
            Call("ocr.loadDrawing");
            // Retain otherwise-unused acquisition: the legacy primary-screen access
            // occurs before the protected Forms load and can fail the whole dispatch.
            Call("ocr.primaryScreenWidth");
            try { Call("ocr.loadFormsAndVirtualWidth"); } catch (Exception error) when (Recoverable(error)) { }
            int x = OcrArgument(args, "X", 0), y = OcrArgument(args, "Y", 0), width = OcrArgument(args, "W", 800), height = OcrArgument(args, "H", 600);
            int maximum = 10000;
            try { maximum = Integer(Call("ocr.maxDimension")); } catch (Exception error) when (Recoverable(error)) { }
            if (width > maximum || height > maximum) return Map("status", "error", "reason", "region_exceeds_max_image_dimension", "max_dim", maximum);
            string path = Text(Call("ocr.tempPath"));
            try { Call("ocr.capture", x, y, width, height, path); }
            catch (Exception error) when (Recoverable(error)) { return Error("screenshot_failed", error.Message); }
            try
            {
                Call("ocr.prepareAsync");
                var file = Call("ocr.loadFile", path);
                var stream = Call("ocr.openRead", file);
                var decoder = Call("ocr.createDecoder", stream);
                var bitmap = Call("ocr.getBitmap", decoder);
                var result = Call("ocr.recognize", ocrEngine, bitmap);
                var lines = Items(Field(result, "lines")).Select(line => (object)Map("text", Field(line, "text"), "word_count", Integer(Field(line, "word_count")))).ToArray();
                return Map("status", "ok", "schema", "cucp.ocr-screen/v1", "region", Map("x", x, "y", y, "w", width, "h", height),
                    "text", Field(result, "text"), "line_count", lines.Length, "lines", lines, "engine_warm", true);
            }
            catch (Exception error) when (Recoverable(error)) { return Error("ocr_failed", error.Message); }
            finally { try { Call("ocr.removeTemp", path); } catch (Exception error) when (Recoverable(error)) { } }
        }
        private static int OcrArgument(IDictionary<string, object> args, string name, int fallback)
        { var value = Property(args, name); return Truth(value) ? Integer(value) : fallback; }
        private Dictionary<string, object> Uia(IDictionary<string, object> args)
        {
            if (!EnsureUia()) return Error("uia_load_failed");
            if (!EnsureWin32()) return Error("win32_unavailable");
            string label = ArgumentText(args, "Label"), match = ArgumentText(args, "Match");
            if (string.IsNullOrEmpty(label)) return Error("missing_label");
            try
            {
                var root = Call("uia.root"); var target = root;
                if (!string.IsNullOrEmpty(match))
                {
                    var rxMatch = Literal(match);
                    foreach (var window in Items(Call("uia.children", root, "all")))
                    {
                        try { if (rxMatch.IsMatch(Text(Call("uia.name", window)))) { target = window; break; } }
                        catch (Exception error) when (Recoverable(error)) { }
                    }
                }
                var rxLabel = Literal(label);
                var candidates = new List<Dictionary<string, object>>();
                int index = 0;
                foreach (var element in Items(Call("uia.subtree", target)))
                {
                    if (++index > 800) break;
                    try
                    {
                        string name = Text(Call("uia.name", element));
                        if (name.Length == 0 || !rxLabel.IsMatch(name)) continue;
                        var rect = Call("uia.rect", element);
                        double x = Number(Field(rect, "x")), y = Number(Field(rect, "y")), width = Number(Field(rect, "width")), height = Number(Field(rect, "height"));
                        if (width <= 0 || height <= 0) continue;
                        int score = 50;
                        if (string.Equals(name, label, StringComparison.InvariantCultureIgnoreCase)) score = 100;
                        else if (name.ToLowerInvariant().StartsWith(label.ToLowerInvariant())) score = 80;
                        int centerX = Integer(x + width / 2), centerY = Integer(y + height / 2);
                        var item = Map("name", name, "score", score, "rect", Map("x", Integer(x), "y", Integer(y), "w", Integer(width), "h", Integer(height)),
                            "click_point", Map("x", centerX, "y", centerY), "control_type", Text(Call("uia.controlType", element)));
                        candidates.Add(item);
                        if (candidates.Count >= 16) break;
                    }
                    catch (Exception error) when (Recoverable(error)) { }
                }
                var sorted = Sort(candidates);
                if (sorted.Length == 0) return Map("status", "partial", "reason", "no_match", "label", label, "match", match, "candidate_count", 0);
                var best = (Dictionary<string, object>)sorted[0];
                return Map("status", "ok", "schema", "cucp.uia-find/v1", "label", label, "match", match, "score", Integer(best["score"]),
                    "best", best, "candidates", sorted, "candidate_count", sorted.Length, "uia_warm", true);
            }
            catch (Exception error) when (Recoverable(error)) { return Error("uia_query_failed", error.Message); }
        }
    }
}
