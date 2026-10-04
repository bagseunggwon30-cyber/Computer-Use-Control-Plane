using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows.Automation;

namespace PcuCp.LegacyDesktop
{
    internal sealed partial class DesktopActions
    {
        private sealed class LabelMatch { internal AutomationElement Element; internal int Score; internal string Reason; }
        private static string Normal(string value) => Regex.Replace(value.ToLowerInvariant(), "\\s+", " ").Trim();
        private static string SafeText(Func<string> read) { try { return read() ?? ""; } catch { return ""; } }
        private LabelMatch ResolveLabel()
        {
            if (!observation.EnsureUia()) return null;
            string match = o.Text("Match"), role = o.Text("Role"), needle = Normal(o.Text("Label"));
            var windows = CucpNative.EnumerateTopLevel();
            var selected = match.Length != 0 ? windows.FirstOrDefault(w => !string.IsNullOrEmpty(w.Title) &&
                w.Title.ToLowerInvariant().Contains(match.ToLowerInvariant())) : windows.FirstOrDefault(w => w.Foreground);
            if (selected == null) return null;
            var root = AutomationElement.FromHandle(selected.Hwnd); if (root == null) return null;
            var elements = root.FindAll(TreeScope.Descendants, Condition.TrueCondition);
            LabelMatch best = null; int count = 0, minimum = o.Int("MinSize", 6), maximum = o.Int("MaxElements", 400);
            foreach (AutomationElement element in elements)
            {
                if (count >= maximum) break;
                try
                {
                    var current = element.Current; var rect = current.BoundingRectangle;
                    if (rect.IsEmpty || rect.Width < minimum || rect.Height < minimum || current.IsOffscreen) continue;
                    string localized = SafeText(() => current.LocalizedControlType);
                    if (role.Length != 0 && localized.Length != 0 && localized.ToLowerInvariant() != role.ToLowerInvariant()) continue;
                    string[] labels = { SafeText(() => current.Name), SafeText(() => current.AutomationId),
                        SafeText(() => current.HelpText), SafeText(() => current.AccessKey) };
                    if (labels.All(string.IsNullOrWhiteSpace)) continue;
                    int score = 0; string reason = "";
                    foreach (string text in labels.Where(value => !string.IsNullOrWhiteSpace(value)))
                    {
                        string hay = Normal(text); int local = 0;
                        if (hay == needle) local = 100;
                        else if (Regex.IsMatch(hay, Regex.Escape(needle), RegexOptions.IgnoreCase)) local = 60 + Math.Max(0, 40 - Math.Abs(hay.Length - needle.Length));
                        else if (needle.Length >= 2 && hay.Contains(needle.Substring(0, 2))) local = 15;
                        if (local > score) { score = local; reason = local >= 100 ? "exact" : local >= 60 ? "substring" : "prefix"; }
                    }
                    if (score > (best?.Score ?? 0)) best = new LabelMatch { Element = element, Score = score, Reason = reason };
                    count++;
                }
                catch { }
            }
            return best;
        }
        private static object Pattern(AutomationElement element, AutomationPattern pattern)
        { try { return element.GetCurrentPattern(pattern); } catch { return null; } }
        private static object Bounds(System.Windows.Rect rect) => D("x", Convert.ToInt32(rect.X), "y", Convert.ToInt32(rect.Y),
            "width", Convert.ToInt32(rect.Width), "height", Convert.ToInt32(rect.Height));
        private static DesktopReply Uncertain(Exception error) => R(2, "status", "partial", "reason", "mutation_may_have_occurred",
            "mutation_may_have_occurred", true, "automatic_retry", false, "detail", error.Message,
            "recommended_action", "Inspect the target and re-ground before deciding whether another action is safe.");
        private DesktopReply UiaAction()
        {
            string label = o.Text("Label"); if (label.Length == 0) return R(1, "status", "error", "reason", "missing_label");
            var resolved = ResolveLabel(); if (resolved == null) return R(2, "status", "partial", "reason", "no_match", "label", label);
            var element = resolved.Element; var current = element.Current;
            if (o.Action == "uia-click")
            {
                var rect = current.BoundingRectangle; int x = Convert.ToInt32(rect.X + rect.Width / 2), y = Convert.ToInt32(rect.Y + rect.Height / 2);
                string button = o.Text("Button", "left"); bool twice = string.Equals(button, "double", StringComparison.OrdinalIgnoreCase);
                CucpNative.SendMouseClick(x, y, twice ? "left" : button, twice);
                return R(0, "status", "ok", "label", label, "x", x, "y", y, "button", button, "matched_text", current.Name,
                    "rect", Bounds(rect), "score", resolved.Score, "match_reason", resolved.Reason);
            }
            if (o.Action == "uia-set-value")
            {
                var value = Pattern(element, ValuePattern.Pattern) as ValuePattern;
                if (value == null) return R(2, "status", "partial", "reason", "no_value_pattern", "label", label,
                    "recommended_action", "Try macro type-native after focusing the field");
                if (value.Current.IsReadOnly) return R(2, "status", "partial", "reason", "value_readonly", "label", label);
                try { value.SetValue(o.Text("Value")); }
                catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "ValuePattern.SetValue", "label", label, "matched_text", current.Name,
                    "value_length", o.Text("Value").Length, "keyboard_used", false);
            }
            if (o.Action == "uia-toggle")
            {
                var toggle = Pattern(element, TogglePattern.Pattern) as TogglePattern;
                if (toggle == null) return R(2, "status", "partial", "reason", "no_toggle_pattern", "label", label);
                string previous = toggle.Current.ToggleState.ToString();
                try { toggle.Toggle(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "TogglePattern", "label", label, "matched_text", current.Name,
                    "previous_state", previous, "mouse_moved", false);
            }
            if (resolved.Score < 60) return R(2, "status", "partial", "reason", "low_confidence_match", "label", label,
                "score", resolved.Score, "match_reason", resolved.Reason, "matched_text", current.Name,
                "recommended_action", "라벨 정확도 낮음(score<60). 다른 라벨/role/match로 시도하거나 macro find-label --explain 으로 후보 확인.");
            var invoke = Pattern(element, InvokePattern.Pattern) as InvokePattern;
            if (invoke != null)
            {
                try { invoke.Invoke(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "InvokePattern", "label", label, "matched_text", current.Name,
                    "automation_id", current.AutomationId, "rect", Bounds(current.BoundingRectangle), "score", resolved.Score,
                    "match_reason", resolved.Reason, "mouse_moved", false);
            }
            var select = Pattern(element, SelectionItemPattern.Pattern) as SelectionItemPattern;
            if (select != null)
            {
                try { select.Select(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "SelectionItemPattern", "label", label, "matched_text", current.Name,
                    "score", resolved.Score, "mouse_moved", false);
            }
            var expand = Pattern(element, ExpandCollapsePattern.Pattern) as ExpandCollapsePattern;
            if (expand != null)
            {
                try { expand.Expand(); } catch (Exception error) { return Uncertain(error); }
                return R(0, "status", "ok", "method", "ExpandCollapsePattern", "label", label, "matched_text", current.Name,
                    "score", resolved.Score, "mouse_moved", false);
            }
            return R(2, "status", "partial", "reason", "no_invoke_pattern", "label", label, "matched_text", current.Name,
                "rect", Bounds(current.BoundingRectangle), "score", resolved.Score,
                "recommended_action", "UIA pattern 미지원 element. 좌표 클릭이 필요하면 macro click-point --x N --y N 호출.");
        }
        private sealed class Fusion
        {
            internal IDictionary<string, object> Ocr; internal AutomationElement Element; internal object Current;
            internal string Pattern; internal bool CanInvoke; internal object Match; internal int Score;
        }
        private Fusion Fuse(AutomationElement root, IList<IDictionary<string, object>> candidates)
        {
            var elements = root.FindAll(TreeScope.Descendants, Condition.TrueCondition); var results = new List<Fusion>();
            foreach (var ocr in candidates.Take(o.Int("OcrMaxCandidates", 8)))
            {
                int x = Convert.ToInt32(ocr["cx"]), y = Convert.ToInt32(ocr["cy"]); double area = double.MaxValue; AutomationElement hit = null;
                foreach (AutomationElement element in elements)
                {
                    try
                    {
                        var rect = element.Current.BoundingRectangle;
                        if (rect.IsEmpty || x < rect.X || x > rect.X + rect.Width || y < rect.Y || y > rect.Y + rect.Height) continue;
                        double size = rect.Width * rect.Height; if (size < area) { hit = element; area = size; }
                    }
                    catch { }
                }
                if (hit == null) continue;
                for (int depth = 0; depth <= 6 && hit != null; depth++)
                {
                    try
                    {
                        var current = hit.Current; if (current.BoundingRectangle.IsEmpty) break;
                        string pattern = primitives.SupportedPattern(hit), role = SafeText(() => current.LocalizedControlType);
                        bool enabled = true, offscreen = false; try { enabled = current.IsEnabled; } catch { } try { offscreen = current.IsOffscreen; } catch { }
                        int score = Convert.ToInt32(ocr["score"]); if (pattern != null) score += 100;
                        if (Regex.IsMatch(role, "button|menu|hyperlink|tab|list item|check|radio", RegexOptions.IgnoreCase)) score += 20;
                        score += enabled ? 10 : -20; if (offscreen) score -= 30; if (depth > 0) score -= depth * 3;
                        results.Add(new Fusion { Ocr = ocr, Element = hit, Current = current, Pattern = pattern,
                            CanInvoke = !string.IsNullOrEmpty(pattern), Match = primitives.MatchPayload(current, pattern), Score = score });
                        if (pattern != null) break;
                        var parent = TreeWalker.ControlViewWalker.GetParent(hit); if (parent == null || parent.Equals(root)) break; hit = parent;
                    }
                    catch { break; }
                }
            }
            return results.OrderByDescending(value => value.CanInvoke).ThenByDescending(value => value.Score)
                .ThenByDescending(value => Convert.ToInt32(value.Ocr["score"])).FirstOrDefault();
        }
    }
}
