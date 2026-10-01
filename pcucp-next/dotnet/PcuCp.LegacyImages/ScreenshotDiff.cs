using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;

namespace PcuCp.LegacyImages
{
    public sealed class DiffResult
    {
        public int ExitCode { get; internal set; }
        public OrderedDictionary Data { get; internal set; }
    }

    // Compatibility implementation, not a screenshot acquisition or input API.
    public static class ScreenshotDiff
    {
        private static OrderedDictionary Map(params object[] pairs)
        {
            var result = new OrderedDictionary();
            for (int i = 0; i < pairs.Length; i += 2) result.Add(pairs[i], pairs[i + 1]);
            return result;
        }
        private static DiffResult Error(string reason, params object[] extra)
        {
            var data = Map("status", "error", "reason", reason);
            for (int i = 0; i < extra.Length; i += 2) data.Add(extra[i], extra[i + 1]);
            return new DiffResult { ExitCode = 1, Data = data };
        }
        private static int LegacyInt(string source)
        {
            string value = source.Trim();
            if (value.Length == 0) return 0;
            try
            {
                if (value.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
                    return unchecked((int)uint.Parse(value.Substring(2), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture));
                return int.Parse(value, NumberStyles.Integer, CultureInfo.InvariantCulture);
            }
            catch (Exception ex) when (ex is FormatException || ex is OverflowException)
            {
                throw new FormatException("Cannot convert value \"" + source + "\" to type \"System.Int32\". Error: \"" + ex.Message + "\"");
            }
        }
        private static T Invoke<T>(string method, int arguments, Func<T> action)
        {
            try { return action(); }
            catch (Exception ex)
            {
                throw new InvalidOperationException("Exception calling \"" + method + "\" with \"" + arguments + "\" argument(s): \"" + ex.Message + "\"", ex);
            }
        }
        public static DiffResult Compare(string before, string after, int x, int y, int width, int height,
            int threshold, string ignoreRegions)
        {
            if (string.IsNullOrEmpty(before) || string.IsNullOrEmpty(after))
                return Error("missing_diff_paths", "recommended_action", "provide -DiffBefore and -DiffAfter");
            if (!File.Exists(before) && !Directory.Exists(before)) return Error("before_not_found", "path", before);
            if (!File.Exists(after) && !Directory.Exists(after)) return Error("after_not_found", "path", after);
            Bitmap bmp1 = null, bmp2 = null;
            BitmapData data1 = null, data2 = null;
            try
            {
                bmp1 = (Bitmap)Invoke("FromFile", 1, () => Image.FromFile(before));
                bmp2 = (Bitmap)Invoke("FromFile", 1, () => Image.FromFile(after));
                int cmpW = Math.Min(bmp1.Width, bmp2.Width), cmpH = Math.Min(bmp1.Height, bmp2.Height);
                if (width > 0) cmpW = Math.Min(cmpW, width);
                if (height > 0) cmpH = Math.Min(cmpH, height);
                int offX = x > 0 ? x : 0, offY = y > 0 ? y : 0;
                if ((long)offX + cmpW > bmp1.Width) cmpW = bmp1.Width - offX;
                if ((long)offY + cmpH > bmp1.Height) cmpH = bmp1.Height - offY;
                if ((long)offX + cmpW > bmp2.Width) cmpW = bmp2.Width - offX;
                if ((long)offY + cmpH > bmp2.Height) cmpH = bmp2.Height - offY;
                if (cmpW <= 0 || cmpH <= 0) return Error("empty_compare_region", "cmp_w", cmpW, "cmp_h", cmpH);
                var rect = new Rectangle(offX, offY, cmpW, cmpH);
                data1 = Invoke("LockBits", 3, () => bmp1.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb));
                data2 = Invoke("LockBits", 3, () => bmp2.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb));
                int stride = data1.Stride;
                int byteCount = checked(Math.Abs(stride) * cmpH);
                var buf1 = new byte[byteCount]; var buf2 = new byte[byteCount];
                Marshal.Copy(data1.Scan0, buf1, 0, byteCount);
                Marshal.Copy(data2.Scan0, buf2, 0, byteCount);
                var masks = new List<OrderedDictionary>();
                if (!string.IsNullOrEmpty(ignoreRegions)) foreach (string raw in ignoreRegions.Split(';'))
                {
                    string spec = raw.Trim(); if (spec.Length == 0) continue;
                    string[] parts = spec.Split(','); if (parts.Length != 4) continue;
                    int rx = LegacyInt(parts[0].Trim()) - offX, ry = LegacyInt(parts[1].Trim()) - offY;
                    int rw = LegacyInt(parts[2].Trim()), rh = LegacyInt(parts[3].Trim());
                    if (rx < 0) { rw += rx; rx = 0; }
                    if (ry < 0) { rh += ry; ry = 0; }
                    if (rw <= 0 || rh <= 0) continue;
                    if ((long)rx + rw > cmpW) rw = cmpW - rx;
                    if ((long)ry + rh > cmpH) rh = cmpH - ry;
                    if (rw <= 0 || rh <= 0) continue;
                    masks.Add(Map("x", rx, "y", ry, "w", rw, "h", rh));
                }
                int changed = 0, ignored = 0, total = checked(cmpW * cmpH);
                for (int yy = 0; yy < cmpH; yy++) for (int xx = 0; xx < cmpW; xx++)
                {
                    bool skip = false;
                    foreach (var mask in masks)
                        if (xx >= (int)mask["x"] && xx < (int)mask["x"] + (int)mask["w"] &&
                            yy >= (int)mask["y"] && yy < (int)mask["y"] + (int)mask["h"]) { skip = true; break; }
                    if (skip) { ignored++; continue; }
                    int index = yy * stride + xx * 4;
                    // PowerShell supports negative array indexes. Keep this legacy stride rule.
                    int b = index < 0 ? byteCount + index : index;
                    int g = index + 1 < 0 ? byteCount + index + 1 : index + 1;
                    int r = index + 2 < 0 ? byteCount + index + 2 : index + 2;
                    int sum = Math.Abs(buf1[b] - buf2[b]) + Math.Abs(buf1[g] - buf2[g]) + Math.Abs(buf1[r] - buf2[r]);
                    if (sum > threshold) changed++;
                }
                int effective = total - ignored;
                double ratio = effective > 0 ? (double)changed / effective : 0.0;
                return new DiffResult { ExitCode = 0, Data = Map("status", "ok", "width", cmpW, "height", cmpH,
                    "total_pixels", total, "effective_pixels", effective, "ignored_pixels", ignored,
                    "ignored_regions", masks.ToArray(), "changed_pixels", changed, "changed_ratio", Math.Round(ratio, 6),
                    "changed", ratio > 0.001, "threshold", threshold, "offset", Map("x", offX, "y", offY),
                    "before", before, "after", after) };
            }
            catch (Exception ex) { return Error("diff_failed", "detail", ex.Message); }
            finally
            {
                if (data1 != null && bmp1 != null) try { bmp1.UnlockBits(data1); } catch { }
                if (data2 != null && bmp2 != null) try { bmp2.UnlockBits(data2); } catch { }
                if (bmp1 != null) bmp1.Dispose();
                if (bmp2 != null) bmp2.Dispose();
            }
        }
    }
}
