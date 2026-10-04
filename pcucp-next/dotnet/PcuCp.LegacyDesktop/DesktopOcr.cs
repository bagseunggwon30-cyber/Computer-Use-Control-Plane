using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Windows.Automation;
using PcuCp.LegacyImages;

namespace PcuCp.LegacyDesktop
{
    internal sealed partial class DesktopActions
    {
        private int MaximumOcrDimension()
        {
            try { return Convert.ToInt32(ocr.Engine.GetType().GetProperty("MaxImageDimension").GetValue(null, null)); }
            catch { return 10000; }
        }
        private IDictionary Recognize(string path, int x, int y)
        {
            object bitmap = null;
            try { bitmap = ocrBackend.Load(path); return FileOcr.ConvertResult(ocrBackend.Recognize(ocr.Engine, bitmap), x, y); }
            finally { (bitmap as IDisposable)?.Dispose(); }
        }
        private DesktopReply OcrScreen()
        {
            if (!ocr.Ensure(o.Text("OcrLanguage"))) return R(1, "status", "error", "reason", "ocr_unavailable", "ocr_error", ocr.Error,
                "recommended_action", "install_windows_ocr_language_pack");
            var region = Region(); int maximum = MaximumOcrDimension();
            if (region.W > maximum || region.H > maximum) return R(1, "status", "error", "reason", "region_exceeds_max_image_dimension",
                "max_dim", maximum, "width", region.W, "height", region.H, "recommended_action", "provide_smaller_region_via_ScreenshotW_ScreenshotH");
            string path = Path.Combine(Path.GetTempPath(), "cucp-ocr-screen-" + Guid.NewGuid().ToString("N") + ".png");
            try
            {
                using (var bitmap = Capture(region.X, region.Y, region.W, region.H)) bitmap.Save(path, ImageFormat.Png);
                var result = DesktopReply.From(0, Recognize(path, region.X, region.Y)); result.Payload["status"] = "ok";
                result.Payload["engine_language"] = ocrBackend.LanguageTag(ocr.Engine); result.Payload["source"] = "screen";
                result.Payload["region"] = Rect(region.X, region.Y, region.W, region.H); return result;
            }
            catch (Exception error) { return R(1, "status", "error", "reason", "ocr_screen_failed", "detail", error.Message); }
            finally { if (File.Exists(path)) File.Delete(path); }
        }
        private sealed class OcrCapture
        {
            internal int X, Y, W, H;
            internal string Path, Error, Detail;
            internal int? Maximum;
        }
        private OcrCapture CaptureOcr(CucpNative.WindowInfo selected, string prefix)
        {
            var raw = (X: o.Int("ScreenshotX", -1), Y: o.Int("ScreenshotY", -1), W: o.Int("ScreenshotW", -1), H: o.Int("ScreenshotH", -1));
            if (selected != null && raw.X < 0 && raw.Y < 0 && raw.W <= 0 && raw.H <= 0)
                raw = (selected.X, selected.Y, selected.Width, selected.Height);
            var capture = new OcrCapture {
                X = raw.X >= 0 ? raw.X : CucpNative.GetSystemMetrics(CucpNative.SM_XVIRTUALSCREEN),
                Y = raw.Y >= 0 ? raw.Y : CucpNative.GetSystemMetrics(CucpNative.SM_YVIRTUALSCREEN),
                W = raw.W > 0 ? raw.W : CucpNative.GetSystemMetrics(CucpNative.SM_CXVIRTUALSCREEN),
                H = raw.H > 0 ? raw.H : CucpNative.GetSystemMetrics(CucpNative.SM_CYVIRTUALSCREEN) };
            int maximum = MaximumOcrDimension();
            if (capture.W > maximum || capture.H > maximum)
            { capture.Error = "region_exceeds_max_image_dimension"; capture.Maximum = maximum; return capture; }
            capture.Path = Path.Combine(Path.GetTempPath(), prefix + "-" + Guid.NewGuid().ToString("N") + ".png");
            try { using (var bitmap = Capture(capture.X, capture.Y, capture.W, capture.H)) bitmap.Save(capture.Path, ImageFormat.Png); }
            catch (Exception error) { capture.Error = "screenshot_unavailable"; capture.Detail = error.Message; if (File.Exists(capture.Path)) File.Delete(capture.Path); capture.Path = null; }
            return capture;
        }
        private static DesktopReply CaptureFailure(OcrCapture cap, string recommendation) => R(cap.Error == "screenshot_unavailable" ? 2 : 1,
            "status", cap.Error == "screenshot_unavailable" ? "partial" : "error", "reason", cap.Error, "detail", cap.Detail,
            "max_dim", cap.Maximum, "recommended_action", recommendation);
        private IList<IDictionary<string, object>> Matches(IDictionary body)
        {
            var candidates = Program.MatchOcr(body, o.Text("OcrText"), o.Text("OcrMatch", "contains"));
            int maximum = o.Int("OcrMaxCandidates", 8);
            if (maximum < 0) throw new ArgumentException("OCR candidate limit cannot be negative.");
            return candidates.Take(maximum).ToList();
        }
        private DesktopReply OcrFind()
        {
            string path = o.Text("OcrPath"), needle = o.Text("OcrText"), mode = o.Text("OcrMatch", "contains");
            if (needle.Length == 0) return R(1, "status", "error", "reason", "missing_ocr_text", "recommended_action", "provide -OcrText <search string>");
            if (path.Length != 0 && !File.Exists(path) && !Directory.Exists(path)) return R(1, "status", "error", "reason", "ocr_path_not_found", "ocr_path", path);
            if (!ocr.Ensure(o.Text("OcrLanguage"))) return R(1, "status", "error", "reason", "ocr_unavailable", "ocr_error", ocr.Error);
            IDictionary body; Dictionary<string, object> metadata;
            if (path.Length != 0)
            {
                try { body = Recognize(path, 0, 0); }
                catch (Exception error) { return R(1, "status", "error", "reason", "ocr_failed", "detail", error.Message); }
                metadata = D("source", "image", "ocr_path", path);
            }
            else
            {
                string match = o.Text("Match"); var window = match.Length == 0 ? null : CucpNative.EnumerateTopLevel().FirstOrDefault(w =>
                    !string.IsNullOrEmpty(w.Title) && w.Title.ToLowerInvariant().Contains(match.ToLowerInvariant()));
                var cap = CaptureOcr(window, "cucp-ocr-find");
                if (cap.Error != null) return CaptureFailure(cap, "Retry from an interactive unlocked desktop session, provide -OcrPath, or use a smaller visible region.");
                try { body = Recognize(cap.Path, cap.X, cap.Y); }
                catch (Exception error) { return R(1, "status", "error", "reason", "ocr_screen_failed", "detail", error.Message); }
                finally { if (File.Exists(cap.Path)) File.Delete(cap.Path); }
                metadata = D("source", "screen", "region", Rect(cap.X, cap.Y, cap.W, cap.H));
            }
            var candidates = Matches(body);
            var result = candidates.Count == 0 ? R(2, "status", "partial", "reason", "no_text_match", "ocr_text", needle, "ocr_match", mode,
                "engine_language", ocrBackend.LanguageTag(ocr.Engine), "total_lines", body["line_count"], "total_words", body["word_count"]) :
                R(0, "status", "ok", "ocr_text", needle, "ocr_match", mode, "engine_language", ocrBackend.LanguageTag(ocr.Engine),
                    "candidate_count", candidates.Count, "candidates", candidates, "top", candidates[0]);
            foreach (var pair in metadata) result.Payload[pair.Key] = pair.Value; return result;
        }
        private DesktopReply OcrUia(bool invoke)
        {
            string needle = o.Text("OcrText"), mode = o.Text("OcrMatch", "contains"), match = o.Text("Match");
            if (needle.Length == 0) return R(1, "status", "error", "reason", "missing_ocr_text");
            if (!observation.EnsureUia()) return R(1, "status", "error", "reason", "uia_unavailable");
            if (!ocr.Ensure(o.Text("OcrLanguage"))) return R(1, "status", "error", "reason", "ocr_unavailable", "ocr_error", ocr.Error);
            var windows = CucpNative.EnumerateTopLevel(); var window = match.Length == 0 ? null : windows.FirstOrDefault(w =>
                !string.IsNullOrEmpty(w.Title) && w.Title.ToLowerInvariant().Contains(match.ToLowerInvariant()));
            window = window ?? windows.FirstOrDefault(w => w.Foreground);
            if (window == null) return R(2, "status", "partial", "reason", "no_target_window");
            var cap = CaptureOcr(window, invoke ? "cucp-ouinv" : "cucp-fuse");
            if (cap.Error != null) return CaptureFailure(cap, "Retry from an interactive unlocked desktop session, provide a matching foreground window, or use a smaller visible region.");
            IList<IDictionary<string, object>> candidates;
            try { candidates = Matches(Recognize(cap.Path, cap.X, cap.Y)); }
            finally { if (File.Exists(cap.Path)) File.Delete(cap.Path); }
            if (candidates.Count == 0) return invoke ? R(2, "status", "partial", "reason", "no_ocr_match", "ocr_text", needle) :
                R(2, "status", "partial", "reason", "no_ocr_match", "ocr_text", needle, "ocr_match", mode, "recommendation", "low_confidence_skip");
            var top = candidates[0];
            if (invoke && Convert.ToInt32(top["score"]) < 70) return LowOcr(top);
            Fusion fusion = null;
            if (invoke)
            {
                var root = AutomationElement.FromHandle(window.Hwnd); if (root == null) return R(2, "status", "partial", "reason", "uia_root_null");
                fusion = Fuse(root, candidates);
            }
            else { try { var root = AutomationElement.FromHandle(window.Hwnd); if (root != null) fusion = Fuse(root, candidates); } catch { } }
            if (fusion != null) top = fusion.Ocr;
            if (!invoke)
            {
                bool canInvoke = fusion?.CanInvoke ?? false;
                return R(0, "status", "ok", "ocr_text", needle, "ocr_match", mode, "target_hwnd", window.Hwnd.ToInt64(),
                    "ocr_top", top, "uia_match", fusion?.Match, "can_invoke", canInvoke, "invoke_pattern", fusion?.Pattern,
                    "recommendation", Convert.ToInt32(top["score"]) < 70 ? "low_confidence_skip" : canInvoke ? "uia_invoke" : "ocr_click",
                    "candidate_count", candidates.Count, "candidates", candidates, "region", Rect(cap.X, cap.Y, cap.W, cap.H));
            }
            if (fusion == null) return R(2, "status", "partial", "reason", "no_uia_element_at_ocr_coord", "ocr_top", top);
            if (Convert.ToInt32(top["score"]) < 70) return LowOcr(top);
            var current = (AutomationElement.AutomationElementInformation)fusion.Current;
            string name = SafeText(() => current.Name), id = SafeText(() => current.AutomationId), cls = SafeText(() => current.ClassName);
            var element = fusion.Element;
            var inv = Pattern(element, InvokePattern.Pattern) as InvokePattern;
            if (inv != null)
            {
                try { inv.Invoke(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "InvokePattern", "matched_ocr_text", top["text"], "ocr_score", Convert.ToInt32(top["score"]),
                    "uia_name", name, "uia_automation_id", id, "uia_class_name", cls, "mouse_moved", false);
            }
            var toggle = Pattern(element, TogglePattern.Pattern) as TogglePattern;
            if (toggle != null)
            {
                string before = toggle.Current.ToggleState.ToString(); try { toggle.Toggle(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "TogglePattern", "matched_ocr_text", top["text"], "ocr_score", Convert.ToInt32(top["score"]),
                    "uia_name", name, "uia_automation_id", id, "previous_state", before, "mouse_moved", false);
            }
            var select = Pattern(element, SelectionItemPattern.Pattern) as SelectionItemPattern;
            if (select != null)
            {
                try { select.Select(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "SelectionItemPattern", "matched_ocr_text", top["text"], "ocr_score", Convert.ToInt32(top["score"]),
                    "uia_name", name, "uia_automation_id", id, "mouse_moved", false);
            }
            return R(2, "status", "partial", "reason", "no_invoke_pattern", "matched_ocr_text", top["text"], "ocr_score", Convert.ToInt32(top["score"]),
                "uia_name", name, "uia_automation_id", id, "uia_class_name", cls, "fallback_coord", D("x", top["cx"], "y", top["cy"]));
        }
        private static DesktopReply LowOcr(IDictionary<string, object> top) => R(2, "status", "partial", "reason", "low_confidence_match",
            "score", Convert.ToInt32(top["score"]), "matched_ocr_text", top["text"], "threshold", 70);
    }
}
