using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Automation;
using PcuCp.LegacyImages;
using PcuCp.LegacyObservation;

namespace PcuCp.LegacyDesktop
{
    internal sealed partial class DesktopActions
    {
        internal static readonly HashSet<string> Actions = new HashSet<string>(StringComparer.Ordinal)
        { "windows", "focused", "focus", "screenshot", "click", "type", "shortcut", "uia-tree", "uia-find", "uia-click",
          "uia-invoke", "uia-set-value", "uia-toggle", "ocr-screen", "ocr-image", "ocr-find-text", "ocr-uia-fuse",
          "ocr-uia-invoke", "screenshot-diff", "hit-test", "hit-scan", "ime-paste", "modal-detect", "health" };
        private static readonly HashSet<string> LiveActions = new HashSet<string>(StringComparer.Ordinal)
        { "focus", "click", "type", "shortcut", "uia-click", "uia-invoke", "uia-set-value", "uia-toggle", "ocr-uia-invoke", "ime-paste" };
        internal static bool IsLive(string action) => LiveActions.Contains(action);
        private readonly DesktopOptions o;
        private readonly WindowsObservationProvider observation = new WindowsObservationProvider();
        private readonly WinRtFileOcrBackend ocrBackend = new WinRtFileOcrBackend();
        private readonly FileOcrSession ocr;
        private readonly ObservationPrimitives primitives;
        internal DesktopActions(DesktopOptions options)
        { o = options; primitives = new ObservationPrimitives(observation); ocr = new FileOcrSession(ocrBackend); }
        private static Dictionary<string, object> D(params object[] pairs) => DesktopReply.Map(pairs);
        private static DesktopReply R(int exit, params object[] pairs) => DesktopReply.Of(exit, pairs);
        internal DesktopReply Run()
        {
            switch (o.Action)
            {
                case "windows": return Windows();
                case "focused": return Focused();
                case "health": return Health();
                case "modal-detect": return Modal();
                case "screenshot": return Screenshot();
                case "uia-tree": case "uia-find": case "hit-test": case "hit-scan": return Observe();
                case "screenshot-diff":
                    var diff = ScreenshotDiff.Compare(o.Text("DiffBefore"), o.Text("DiffAfter"), o.Int("ScreenshotX", -1),
                        o.Int("ScreenshotY", -1), o.Int("ScreenshotW", -1), o.Int("ScreenshotH", -1), o.Int("DiffThreshold", 16), o.Text("DiffIgnoreRegions"));
                    return DesktopReply.From(diff.ExitCode, diff.Data);
                case "ocr-image":
                    var image = ocr.Observe(o.Text("OcrPath"), o.Text("OcrLanguage"));
                    return DesktopReply.From(image.ExitCode, image.Data);
                case "ocr-screen": return OcrScreen();
                case "ocr-find-text": return OcrFind();
                case "ocr-uia-fuse": return OcrUia(false);
                case "ocr-uia-invoke": return OcrUia(true);
                case "focus": return Focus();
                case "click": return Click();
                case "type": return TypeText();
                case "shortcut": return Shortcut();
                case "ime-paste": return ImePaste();
                case "uia-click": case "uia-invoke": case "uia-set-value": case "uia-toggle": return UiaAction();
                default: throw new ArgumentException("Unsupported desktop action.");
            }
        }
        private static IDictionary<string, object> Window(CucpNative.WindowInfo w) => D("hwnd", w.Hwnd.ToInt64(), "title", w.Title,
            "class", w.ClassName, "pid", (int)w.Pid, "process", w.ProcessName, "visible", w.Visible, "minimized", w.Minimized,
            "foreground", w.Foreground, "rect", D("x", w.X, "y", w.Y, "width", w.Width, "height", w.Height));
        private DesktopReply Windows()
        {
            string match = o.Text("Match");
            var windows = CucpNative.EnumerateTopLevel().Where(w => match.Length == 0 ||
                (w.Title ?? "").ToLowerInvariant().Contains(match.ToLowerInvariant()) ||
                (w.ProcessName ?? "").ToLowerInvariant().Contains(match.ToLowerInvariant())).Select(Window).ToArray();
            return R(0, "status", "ok", "match", match, "count", windows.Length, "windows", windows);
        }
        private DesktopReply Focused()
        {
            var window = CucpNative.EnumerateTopLevel().FirstOrDefault(w => w.Foreground);
            if (window == null) return R(2, "status", "partial", "reason", "no_foreground_window");
            var value = Window(window); value.Remove("visible"); value.Remove("minimized"); value.Remove("foreground");
            return R(0, "status", "ok", "foreground", value);
        }
        private DesktopReply Health()
        {
            bool uia = observation.EnsureUia(), available = ocr.Ensure(o.Text("OcrLanguage"));
            string[] languages = new string[0];
            if (available)
            {
                try { languages = ocrBackend.AvailableLanguages().Cast<object>().Select(l => Convert.ToString(Property(l, "LanguageTag"))).ToArray(); }
                catch { }
            }
            return R(0, "status", "ok", "win32", true, "uia", uia, "ocr", available, "ocr_languages", languages,
                "ocr_engine_language", ocr.Engine == null ? null : ocrBackend.LanguageTag(ocr.Engine), "ocr_error", ocr.Error,
                "psversion", null, "runtime", "net48", "pid", System.Diagnostics.Process.GetCurrentProcess().Id);
        }
        private DesktopReply Observe()
        {
            if (o.Action == "uia-find" && o.Text("Label").Length == 0) return R(1, "status", "error", "reason", "missing_label");
            if ((o.Action == "hit-test" || o.Action == "hit-scan") && !o.HasCoordinates)
                return R(1, "status", "error", "reason", "missing_coords", "recommended_action", "provide -X and -Y (zero and negative screen coordinates are valid)");
            if ((o.Action == "uia-tree" || o.Action == "uia-find") && !observation.EnsureUia())
                return o.Action == "uia-tree" ? R(2, "status", "partial", "reason", "uia_unavailable", "recommended_action", "UIAutomationClient assembly load failed") :
                    R(2, "status", "partial", "reason", "uia_unavailable");
            var options = new ObservationOptions { HasCoordinates = o.HasCoordinates, X = o.Int("X"), Y = o.Int("Y"),
                TargetHwnd = o.Int("TargetHwnd"), TargetMatch = o.Text("TargetMatch"), ClickInset = o.Int("ClickInset", 3),
                ScanRadius = o.Int("ScanRadius"), ScanStep = o.Int("ScanStep", 6), SkipUia = o.Flag("SkipUia"),
                Match = o.Text("Match"), Label = o.Text("Label"), Role = o.Text("Role"), MaxElements = o.Int("MaxElements", 400), MinSize = o.Int("MinSize", 6) };
            var actions = new ObservationActions(observation);
            ObservationResult result;
            switch (o.Action)
            { case "uia-tree": result = actions.UiaTree(options); break; case "uia-find": result = actions.UiaFind(options); break;
              case "hit-test": result = actions.HitTest(options); break; default: result = actions.HitScan(options); break; }
            return DesktopReply.From(result.ExitCode, result.Payload);
        }
        private object Rect(int x, int y, int width, int height) => D("x", x, "y", y, "width", width, "height", height);
        private (int X, int Y, int W, int H) Region()
        {
            int x = o.Int("ScreenshotX", -1), y = o.Int("ScreenshotY", -1), w = o.Int("ScreenshotW", -1), h = o.Int("ScreenshotH", -1);
            return (x >= 0 ? x : CucpNative.GetSystemMetrics(CucpNative.SM_XVIRTUALSCREEN),
                y >= 0 ? y : CucpNative.GetSystemMetrics(CucpNative.SM_YVIRTUALSCREEN),
                w > 0 ? w : CucpNative.GetSystemMetrics(CucpNative.SM_CXVIRTUALSCREEN),
                h > 0 ? h : CucpNative.GetSystemMetrics(CucpNative.SM_CYVIRTUALSCREEN));
        }
        private static Bitmap Capture(int x, int y, int width, int height)
        {
            var bitmap = new Bitmap(width, height);
            try { using (var graphics = Graphics.FromImage(bitmap)) graphics.CopyFromScreen(x, y, 0, 0, new Size(width, height)); return bitmap; }
            catch { bitmap.Dispose(); throw; }
        }
        private DesktopReply Screenshot()
        {
            string output = o.Text("OutPath");
            if (output.Length == 0) return R(1, "status", "error", "reason", "missing_outpath", "recommended_action", "provide -OutPath <png file>");
            var region = Region(); Bitmap bitmap;
            try { bitmap = Capture(region.X, region.Y, region.W, region.H); }
            catch (Exception error)
            { return R(2, "status", "partial", "reason", "screenshot_unavailable", "detail", error.Message,
                "recommended_action", "Run from an interactive unlocked desktop session, or retry with a smaller visible region.",
                "out_path", output, "rect", Rect(region.X, region.Y, region.W, region.H)); }
            using (bitmap)
            {
                string directory = Path.GetDirectoryName(output);
                if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                bitmap.Save(output, ImageFormat.Png);
            }
            return R(0, "status", "ok", "out_path", output, "rect", Rect(region.X, region.Y, region.W, region.H), "bytes", new FileInfo(output).Length);
        }
        private DesktopReply Modal()
        {
            object foreground = null;
            try
            {
                var hwnd = CucpNative.GetForegroundWindow(); var title = new StringBuilder(512); var cls = new StringBuilder(256);
                CucpNative.GetWindowText(hwnd, title, title.Capacity); CucpNative.GetClassName(hwnd, cls, cls.Capacity);
                foreground = D("hwnd", checked((int)hwnd.ToInt64()), "title", title.ToString(), "class", cls.ToString());
            }
            catch { }
            var candidates = new List<Dictionary<string, object>>();
            try
            {
                var elements = AutomationElement.RootElement.FindAll(TreeScope.Children, new OrCondition(
                    new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Window),
                    new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Pane)));
                foreach (AutomationElement element in elements)
                {
                    try
                    {
                        var current = element.Current; var rect = current.BoundingRectangle;
                        bool modal = element.TryGetCurrentPattern(WindowPattern.Pattern, out object pattern) && ((WindowPattern)pattern).Current.IsModal;
                        int score = modal ? 100 : 0; string reason = modal ? "uia_window_is_modal" : null;
                        if (Regex.IsMatch(current.ClassName, "#32770|MessageBox|Dialog|TaskDialog|Popup", RegexOptions.IgnoreCase))
                        { score += 60; reason = reason ?? "dialog_class_name"; }
                        if (rect.Width > 0 && rect.Width < 900 && rect.Height > 0 && rect.Height < 600)
                        { score += 20; reason = reason ?? "small_window_size"; }
                        if (score > 0) candidates.Add(D("hwnd", current.NativeWindowHandle, "title", current.Name, "class", current.ClassName,
                            "role", current.LocalizedControlType, "rect", D("x", Convert.ToInt32(rect.X), "y", Convert.ToInt32(rect.Y),
                            "w", Convert.ToInt32(rect.Width), "h", Convert.ToInt32(rect.Height)), "score", score, "reason", reason, "is_modal", modal));
                    }
                    catch { }
                }
            }
            catch { }
            var sorted = candidates.OrderByDescending(item => (int)item["score"]).ToArray();
            string recommendation = sorted.Length == 0 ? "observe" : (bool)sorted[0]["is_modal"] || (int)sorted[0]["score"] >= 100 ? "dismiss_or_confirm" :
                (int)sorted[0]["score"] >= 60 ? "confirm_dialog" : "wait";
            return R(0, "status", "ok", "foreground", foreground, "modal_candidates", sorted, "candidate_count", sorted.Length, "recommended_action", recommendation);
        }
        private static object Property(object value, string name) => value?.GetType().GetProperty(name)?.GetValue(value, null);
    }
}
