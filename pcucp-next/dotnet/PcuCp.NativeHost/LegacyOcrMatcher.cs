using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

/// <summary>Exact .NET/UTF-16 compatibility kernel for retained PS OCR callers.</summary>
internal static class LegacyOcrMatcher
{
    internal const int MaximumRequestBytes = 1024 * 1024;
    private const int MaximumItems = 10000;
    private const int MaximumTextUnits = 262144;
    private const long MaximumDistanceCells = 10000000;
    private static readonly Regex NonText = new(@"[^\p{L}\p{Nd}\s]+", RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1));
    private static readonly Regex Whitespace = new(@"\s+", RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1));

    internal static string Normalize(string? value)
    {
        if (string.IsNullOrEmpty(value)) return string.Empty;
        if (value.Length > 4096) throw CommandOptions.Invalid("OCR text exceeds 4096 UTF-16 units.");
        string normalized;
        try { normalized = value.Normalize(NormalizationForm.FormKC); }
        catch (ArgumentException) { normalized = value; } // matches original .NET fallback
        return Whitespace.Replace(NonText.Replace(normalized.ToLowerInvariant(), " "), " ").Trim();
    }

    private static int Distance(string left, string right)
    {
        var previous = Enumerable.Range(0, right.Length + 1).ToArray();
        var current = new int[right.Length + 1];
        for (var i = 1; i <= left.Length; i++)
        {
            current[0] = i;
            for (var j = 1; j <= right.Length; j++)
                current[j] = Math.Min(Math.Min(previous[j] + 1, current[j - 1] + 1), previous[j - 1] + (left[i - 1] == right[j - 1] ? 0 : 1));
            (previous, current) = (current, previous);
        }
        return previous[right.Length];
    }

    internal static int Score(string? needle, string? hay, string mode, ref long budget)
    {
        var n = Normalize(needle);
        var h = Normalize(hay);
        if (n.Length == 0 || h.Length == 0) return 0;
        // PowerShell's string -eq uses invariant culture, ignoring case.
        if (LegacyEqual(n, h)) return 100;
        if (mode == "exact") return 0;
        if (mode == "prefix") return LegacyIndex(h, n) == 0 ? 80 : 0;
        if (mode == "fuzzy")
        {
            budget -= (long)n.Length * h.Length;
            if (budget < 0) throw CommandOptions.Invalid("OCR matching exceeds the edit-distance budget.");
            var best = (int)Math.Round((1.0 - (double)Distance(n, h) / Math.Max(n.Length, h.Length)) * 100);
            if (h.Contains(n, StringComparison.Ordinal)) best = Math.Max(best, 55 + (int)Math.Floor((double)n.Length / h.Length * 30));
            return Math.Clamp(best, 0, 100);
        }
        var index = LegacyIndex(h, n);
        return index < 0 ? 0 : Math.Min(95, 50 + (int)Math.Floor((double)n.Length / h.Length * 30) + (index == 0 ? 10 : 0));
    }

    private static string Text(JsonElement obj, string key)
    {
        if (!obj.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return string.Empty;
        if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid($"{key} must be a string.");
        return value.GetString()!;
    }

    private static double Number(JsonElement obj, string key)
    {
        if (!obj.TryGetProperty(key, out var value) || value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var result) || !double.IsFinite(result) || Math.Abs(result) > 100000000)
            throw CommandOptions.Invalid($"{key} must be a finite bounded number.");
        return result;
    }

    private static JsonElement[] Array(JsonElement obj, string key)
    {
        if (!obj.TryGetProperty(key, out var value)) return [];
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() > MaximumItems) throw CommandOptions.Invalid($"{key} must be a bounded array.");
        return value.EnumerateArray().ToArray();
    }

    internal static object Match(JsonElement request)
    {
        if (request.ValueKind != JsonValueKind.Object || request.EnumerateObject().Any(p => p.Name is not ("schema" or "body" or "needle" or "mode" or "culture")) ||
            Text(request, "schema") != "cucp.legacy-ocr-match/v1" || !request.TryGetProperty("body", out var body) || body.ValueKind != JsonValueKind.Object)
            throw CommandOptions.Invalid("Expected bounded cucp.legacy-ocr-match/v1 object.");
        var needle = Text(request, "needle");
        var mode = Text(request, "mode");
        if (mode is not ("exact" or "prefix" or "contains" or "fuzzy")) throw CommandOptions.Invalid("Unsupported match mode.");
        var needsNgrams = Normalize(needle).Split(' ', StringSplitOptions.RemoveEmptyEntries).Length >= 2;
        var results = new List<Dictionary<string, object>>();
        long budget = MaximumDistanceCells;
        var items = 0;
        var characters = 0;
        void Add(JsonElement raw, string scope)
        {
            if (++items > MaximumItems || raw.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("OCR item budget exceeded or malformed item.");
            var text = Text(raw, "text");
            characters += text.Length;
            if (characters > MaximumTextUnits) throw CommandOptions.Invalid("OCR text budget exceeded.");
            var score = Score(needle, text, mode, ref budget);
            if (score == 0) return;
            var item = new Dictionary<string, object> { ["scope"] = scope, ["score"] = score, ["text"] = text };
            foreach (var key in new[] { "x", "y", "w", "h", "cx", "cy" }) item[key] = Number(raw, key);
            results.Add(item);
        }
        foreach (var line in Array(body, "lines"))
        {
            Add(line, "line");
            var words = Array(line, "words");
            foreach (var word in words) Add(word, "word");
            if (!needsNgrams) continue;
            for (var count = 2; count <= 3; count++)
                for (var start = 0; start <= words.Length - count; start++)
                {
                    if (++items > MaximumItems) throw CommandOptions.Invalid("OCR item budget exceeded.");
                    var slice = words.Skip(start).Take(count).ToArray();
                    var text = string.Join(" ", slice.Select(w => Text(w, "text")));
                    var score = Score(needle, text, mode, ref budget);
                    if (score == 0) continue;
                    var x = slice.Min(w => Number(w, "x"));
                    var y = slice.Min(w => Number(w, "y"));
                    // PS [int] uses banker's rounding, including half-pixel centers.
                    var width = checked((int)Math.Round(slice.Max(w => Number(w, "x") + Number(w, "w")) - x));
                    var height = checked((int)Math.Round(slice.Max(w => Number(w, "y") + Number(w, "h")) - y));
                    results.Add(new() { ["scope"] = "word_ngram", ["n"] = count, ["score"] = score, ["text"] = text,
                        ["x"] = checked((int)Math.Round(x)), ["y"] = checked((int)Math.Round(y)), ["w"] = width, ["h"] = height,
                        ["cx"] = checked((int)Math.Round(x + width / 2.0)), ["cy"] = checked((int)Math.Round(y + height / 2.0)) });
                }
        }
        static int Rank(Dictionary<string, object> item) => (string)item["scope"] switch { "word_ngram" => 0, "word" => 1, _ => 2 };
        int Compare(Dictionary<string, object> a, Dictionary<string, object> b)
        {
            var order = ((int)b["score"]).CompareTo((int)a["score"]);
            if (order == 0) order = Rank(a).CompareTo(Rank(b));
            if (order == 0) order = (Math.Round(Convert.ToDouble(a["w"])) * Math.Round(Convert.ToDouble(a["h"])))
                .CompareTo(Math.Round(Convert.ToDouble(b["w"])) * Math.Round(Convert.ToDouble(b["h"])));
            return order;
        }
        var ordered = results.ToArray();
        LegacySort(ordered, Compare);
        return new { candidates = ordered, candidate_count = ordered.Length, compatibility = "legacy-dotnet-utf16/v1" };
    }

    // Windows PowerShell 5 uses Windows NLS, not the modern runtime's ICU.
    // The compatibility kernel keeps those linguistic comparisons local.
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int CompareStringEx(string locale, uint flags, string left, int leftLength,
        string right, int rightLength, IntPtr version, IntPtr reserved, IntPtr sortHandle);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int FindNLSStringEx(string locale, uint flags, string source, int sourceLength,
        string value, int valueLength, IntPtr foundLength, IntPtr version, IntPtr reserved, IntPtr sortHandle);

    internal static bool LegacyEqual(string left, string right)
    {
        if (!OperatingSystem.IsWindows()) return CultureInfo.InvariantCulture.CompareInfo.Compare(left, right, CompareOptions.IgnoreCase) == 0;
        var result = CompareStringEx("", 1, left, left.Length, right, right.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (result == 0) throw new NativeFailure("nls_compare_failed", "Windows linguistic comparison failed.");
        return result == 2;
    }

    internal static int LegacyIndex(string source, string value)
    {
        if (!OperatingSystem.IsWindows()) return source.IndexOf(value, StringComparison.CurrentCulture);
        var result = FindNLSStringEx(CultureInfo.CurrentCulture.Name, 0, source, source.Length, value, value.Length,
            IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (result < 0 && Marshal.GetLastWin32Error() != 0) throw new NativeFailure("nls_search_failed", "Windows linguistic search failed.");
        return result;
    }

    internal static void LegacySort<T>(T[] values, Comparison<T> compare)
    {
        // Preserve PS5/.NET4 pre-4.5 equal-key ordering, rather than silently
        // switching first-match behavior to the modern stable LINQ ordering.
        void Swap(int a, int b) { if (a != b) (values[a], values[b]) = (values[b], values[a]); }
        void MedianSwap(int a, int b) { if (compare(values[a], values[b]) > 0) Swap(a, b); }
        void Heap(int begin, int end)
        {
            var size = end - begin + 1;
            void Down(int root, int count)
            {
                var kept = values[begin + root - 1];
                while (root <= count / 2)
                {
                    var child = 2 * root;
                    if (child < count && compare(values[begin + child - 1], values[begin + child]) < 0) child++;
                    if (compare(kept, values[begin + child - 1]) >= 0) break;
                    values[begin + root - 1] = values[begin + child - 1]; root = child;
                }
                values[begin + root - 1] = kept;
            }
            for (var i = size / 2; i >= 1; i--) Down(i, size);
            for (var i = size; i > 1; i--) { Swap(begin, begin + i - 1); Down(1, i - 1); }
        }
        void Sort(int begin, int end, int remaining)
        {
            while (begin < end)
            {
                if (remaining-- == 0) { Heap(begin, end); return; }
                var middle = begin + (end - begin) / 2;
                MedianSwap(begin, middle); MedianSwap(begin, end); MedianSwap(middle, end);
                var pivot = values[middle];
                var a = begin; var b = end;
                while (a <= b)
                {
                    while (compare(values[a], pivot) < 0) a++;
                    while (compare(pivot, values[b]) < 0) b--;
                    if (a > b) break;
                    Swap(a++, b--);
                }
                if (b - begin <= end - a) { if (begin < b) Sort(begin, b, remaining); begin = a; }
                else { if (a < end) Sort(a, end, remaining); end = b; }
            }
        }
        if (values.Length > 1) Sort(0, values.Length - 1, 32);
    }

}
