using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using PcuCp.LegacyObservation;

namespace PcuCp.LegacyDesktop
{
    internal sealed partial class DesktopActions
    {
        private DesktopReply Focus()
        {
            IntPtr hwnd = IntPtr.Zero; int requested = o.Int("WindowHwnd"); string title = o.Text("WindowTitle");
            if (requested > 0) hwnd = new IntPtr(requested);
            else if (title.Length != 0) hwnd = CucpNative.EnumerateTopLevel().FirstOrDefault(w =>
                !string.IsNullOrEmpty(w.Title) && w.Title.ToLowerInvariant().Contains(title.ToLowerInvariant()))?.Hwnd ?? IntPtr.Zero;
            else return R(1, "status", "error", "reason", "missing_target", "recommended_action", "provide -WindowHwnd or -WindowTitle");
            if (hwnd == IntPtr.Zero) return R(2, "status", "partial", "reason", "no_matching_window", "window_title", title, "window_hwnd", requested);
            CucpNative.ShowWindow(hwnd, CucpNative.SW_RESTORE); CucpNative.BringWindowToTop(hwnd);
            bool returned = CucpNative.SetForegroundWindow(hwnd); Thread.Sleep(80);
            IntPtr actual = CucpNative.GetForegroundWindow(); bool verified = actual == hwnd;
            return R(verified ? 0 : 2, "status", verified ? "ok" : "partial", "set_foreground_returned", returned,
                "verified", verified, "target_hwnd", hwnd.ToInt64(), "actual_foreground_hwnd", actual.ToInt64());
        }
        private DesktopReply ForegroundGuard()
        {
            int hwnd = o.Int("TargetHwnd"); string match = o.Text("TargetMatch");
            if (hwnd <= 0 && match.Length == 0) return null;
            IntPtr foreground = CucpNative.GetForegroundWindow(); var title = new StringBuilder(256);
            CucpNative.GetWindowText(foreground, title, title.Capacity);
            bool same = hwnd > 0 ? foreground.ToInt64() == hwnd : title.ToString().ToLowerInvariant().Contains(match.ToLowerInvariant());
            return same ? null : R(3, "status", "blocked", "reason", "focus_target_mismatch", "actual_foreground_hwnd", foreground.ToInt64(),
                "actual_foreground_title", title.ToString(), "target_hwnd", hwnd, "target_match", match,
                "mismatch_reason", hwnd > 0 ? "hwnd_mismatch" : "title_mismatch",
                "recommended_action", "Re-focus target window (use focus action) before typing");
        }
        private DesktopReply Click()
        {
            if (!o.HasCoordinates) return R(1, "status", "error", "reason", "missing_coords",
                "recommended_action", "provide -X and -Y (zero and negative screen coordinates are valid)");
            int x = o.Int("X"), y = o.Int("Y"), vx = CucpNative.GetSystemMetrics(CucpNative.SM_XVIRTUALSCREEN),
                vy = CucpNative.GetSystemMetrics(CucpNative.SM_YVIRTUALSCREEN), vw = CucpNative.GetSystemMetrics(CucpNative.SM_CXVIRTUALSCREEN),
                vh = CucpNative.GetSystemMetrics(CucpNative.SM_CYVIRTUALSCREEN), target = o.Int("TargetHwnd");
            string match = o.Text("TargetMatch"), button = o.Text("Button", "left"), refinement = o.Text("ClickRefine", "none");
            if (x < vx || x >= (long)vx + vw || y < vy || y >= (long)vy + vh)
                return R(3, "status", "blocked", "reason", "coords_out_of_virtual_desktop", "x", x, "y", y,
                    "virtual_desktop", Rect(vx, vy, vw, vh));
            if (target > 0 || match.Length != 0)
            {
                var hit = primitives.TestTarget(x, y, target, match);
                if (!hit.matched) return R(3, "status", "blocked", "reason", "hit_test_target_mismatch", "x", x, "y", y,
                    "actual_root_hwnd", hit.actual_root_hwnd, "actual_title", hit.actual_title, "target_hwnd", target,
                    "target_match", match, "mismatch_reason", hit.reason,
                    "recommended_action", "verify target window position; coords may have shifted (window moved/resized/full-screen toggle)");
            }
            int originalX = x, originalY = y; ObservationRefinement refined = null;
            if (string.Equals(refinement, "uia-safe", StringComparison.OrdinalIgnoreCase))
            {
                refined = primitives.ResolvePoint(x, y, inset: o.Int("ClickInset", 3));
                if (refined != null)
                {
                    x = refined.X; y = refined.Y;
                    if ((target > 0 || match.Length != 0) && !primitives.TestTarget(x, y, target, match).matched)
                    { x = originalX; y = originalY; refined = null; }
                }
            }
            bool twice = string.Equals(button, "double", StringComparison.OrdinalIgnoreCase);
            CucpNative.SendMouseClick(x, y, twice ? "left" : button, twice);
            int postX = CucpNative.PostClickX, postY = CucpNative.PostClickY;
            double dx = (double)postX - x, dy = (double)postY - y;
            int drift = Convert.ToInt32(Math.Sqrt(dx * dx + dy * dy));
            var result = R(0, "status", "ok", "x", x, "y", y, "button", button, "double", twice, "target_hwnd", target,
                "target_match", match, "click_refine", refinement, "post_click", D("requested_x", x, "requested_y", y,
                    "actual_x", postX, "actual_y", postY, "drift_px", drift, "accurate", drift <= 3));
            if (refined != null)
            {
                result.Payload["original"] = D("x", originalX, "y", originalY); result.Payload["refined_by"] = "uia-safe";
                result.Payload["refined_point_source"] = refined.PointSource; result.Payload["native_clickable_point"] = refined.NativeClickable;
                result.Payload["refine_score"] = refined.Score; result.Payload["refine_depth"] = refined.Depth; result.Payload["uia_match"] = refined.Match;
            }
            return result;
        }
        private DesktopReply TypeText()
        {
            string text = o.Text("Text"); bool clear = o.Flag("ClearFirst"), enter = o.Flag("PressEnter");
            if (text.Length == 0 && !clear && !enter) return R(1, "status", "error", "reason", "missing_text");
            var guard = ForegroundGuard(); if (guard != null) return guard;
            if (clear)
            {
                CucpNative.SendVk(CucpNative.VK_CONTROL, false); Thread.Sleep(20);
                ushort a = (ushort)(CucpNative.VkKeyScan('a') & 255); CucpNative.SendVk(a, false); CucpNative.SendVk(a, true);
                CucpNative.SendVk(CucpNative.VK_CONTROL, true); Thread.Sleep(30);
                CucpNative.SendVk(CucpNative.VK_BACK, false); CucpNative.SendVk(CucpNative.VK_BACK, true); Thread.Sleep(30);
            }
            if (text.Length != 0) CucpNative.SendUnicodeText(text);
            if (enter) { Thread.Sleep(30); CucpNative.SendVk(CucpNative.VK_RETURN, false); CucpNative.SendVk(CucpNative.VK_RETURN, true); }
            return R(0, "status", "ok", "text_length", text.Length, "clear", clear, "enter", enter);
        }
        private DesktopReply Shortcut()
        {
            string keys = o.Text("Keys"); if (keys.Length == 0) return R(1, "status", "error", "reason", "missing_keys");
            var guard = ForegroundGuard(); if (guard != null) return guard;
            var tokens = keys.ToLowerInvariant().Split('+').Select(value => value.Trim()).ToArray();
            var mapped = new Dictionary<string, ushort> { ["ctrl"] = CucpNative.VK_CONTROL, ["shift"] = CucpNative.VK_SHIFT,
                ["alt"] = CucpNative.VK_MENU, ["win"] = CucpNative.VK_LWIN, ["enter"] = CucpNative.VK_RETURN,
                ["tab"] = CucpNative.VK_TAB, ["esc"] = CucpNative.VK_ESCAPE, ["escape"] = CucpNative.VK_ESCAPE,
                ["space"] = CucpNative.VK_SPACE, ["backspace"] = CucpNative.VK_BACK, ["delete"] = CucpNative.VK_DELETE };
            var codes = new List<ushort>();
            foreach (string token in tokens)
            {
                if (mapped.TryGetValue(token, out ushort code)) codes.Add(code);
                else if (Regex.IsMatch(token, "^f[0-9]{1,2}$")) codes.Add((ushort)(0x6f + int.Parse(token.Substring(1))));
                else if (token.Length == 1) codes.Add((ushort)(CucpNative.VkKeyScan(token[0]) & 255));
                else return R(1, "status", "error", "reason", "unknown_key", "token", token);
            }
            foreach (ushort code in codes) { CucpNative.SendVk(code, false); Thread.Sleep(8); }
            Thread.Sleep(30);
            for (int index = codes.Count - 1; index >= 0; index--) { CucpNative.SendVk(codes[index], true); Thread.Sleep(8); }
            return R(0, "status", "ok", "keys", keys, "tokens", tokens);
        }
        private DesktopReply ImePaste()
        {
            string text = o.Text("Text"); if (text.Length == 0) return R(1, "status", "error", "reason", "missing_text", "recommended_action", "provide -Text");
            object guard = null; int target = o.Int("TargetHwnd"); string match = o.Text("TargetMatch");
            if (target > 0 || match.Length != 0)
            {
                try
                {
                    IntPtr hwnd = CucpNative.GetForegroundWindow(); var title = new StringBuilder(512); CucpNative.GetWindowText(hwnd, title, title.Capacity);
                    int actual = checked((int)hwnd.ToInt64()); bool sameHandle = target > 0 && target == actual;
                    bool sameTitle = match.Length != 0 && title.Length != 0 && Regex.IsMatch(title.ToString(), Regex.Escape(match), RegexOptions.IgnoreCase);
                    guard = D("foreground_hwnd", actual, "foreground_title", title.ToString(), "match_hwnd", sameHandle, "match_title", sameTitle);
                    if (!sameHandle && !sameTitle) return R(3, "status", "blocked", "reason", "target_mismatch", "guard", guard,
                        "recommended_action", "focus the target window first");
                }
                catch (Exception error) { return R(1, "status", "error", "reason", "hit_test_failed", "detail", error.Message); }
            }
            string previous = null; bool restored = false;
            try { if (Clipboard.ContainsText()) previous = Clipboard.GetText(); } catch { }
            DesktopReply failure = null;
            try
            {
                Clipboard.SetDataObject(text, true, 5, 100); Thread.Sleep(60); SendKeys.SendWait("^v"); Thread.Sleep(80);
                if (o.Flag("PressEnter")) { SendKeys.SendWait("{ENTER}"); Thread.Sleep(40); }
            }
            catch (Exception error) { failure = R(1, "status", "error", "reason", "paste_failed", "detail", error.Message); }
            finally
            {
                try { if (previous != null) { Clipboard.SetDataObject(previous, true, 5, 100); restored = true; } } catch { restored = false; }
            }
            return failure ?? R(0, "status", "ok", "method", "clipboard_paste", "text_len", text.Length,
                "pressed_enter", o.Flag("PressEnter"), "restored_clipboard", restored, "guard", guard, "mouse_moved", false);
        }
    }
}
