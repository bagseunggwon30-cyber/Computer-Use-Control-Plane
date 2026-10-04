using System.Collections;
using System.Globalization;
using System.Text.Json;

// No paths, filesystem, shell, provider, network or mutation authority. All input
// is an already captured, bounded file-existence flag and physical text lines.
internal sealed record HistoryCapture(bool Exists, string[] Lines);
internal sealed class HistoryReducer(string runtime, CultureInfo culture)
{
    internal static readonly StringComparer KeyComparer = StringComparer.OrdinalIgnoreCase;
    private static readonly StringComparer Comparison = StringComparer.InvariantCultureIgnoreCase;

    internal object? Pick(HistoryCapture capture, string label, string match, int lookback)
    {
        if (!capture.Exists || capture.Lines.Length == 0) return null;
        var candidates = new List<object?>();
        for (int i = capture.Lines.Length - 1; i >= 0 && candidates.Count < lookback; i--)
        {
            if (!TryParse(capture.Lines[i], out object? row)) continue;
            if (Comparison.Equals(Text(Property(row, "label")), label) && Comparison.Equals(Text(Property(row, "match")), match))
                candidates.Add(row);
        }
        var counts = new Hashtable(KeyComparer);
        foreach (object? row in candidates)
        {
            object? strategy = Property(row, "strategy");
            if (!Success(Property(row, "success")) || !Truth(strategy)) continue;
            string key = Text(strategy);
            counts[key] = counts.ContainsKey(key) ? (int)counts[key]! + 1 : 1;
        }
        if (counts.Count == 0) return null;
        int maximum = counts.Values.Cast<int>().Max();
        var top = counts.Keys.Cast<string>().Where(k => (int)counts[k]! == maximum).ToArray();
        if (top.Length == 1) return top[0];
        foreach (object? row in candidates)
            if (Success(Property(row, "success")) && top.Contains(Text(Property(row, "strategy")), Comparison))
                return Text(Property(row, "strategy"));
        return top[0];
    }

    internal Dictionary<string, object?> Stats(HistoryCapture capture)
    {
        int total = 0, success = 0;
        var counts = new Hashtable(KeyComparer);
        // Original -not $all applies array truthiness before row parsing:
        // a single empty physical line returns the empty stats object, while
        // two empty lines are truthy and both increment total after parsing.
        if (capture.Exists && Truth(capture.Lines.Cast<object?>().ToList()))
            foreach (string line in capture.Lines)
            {
                if (!TryParse(line, out object? row)) continue;
                total++;
                if (!Success(Property(row, "success"))) continue;
                success++;
                string key = Text(Property(row, "strategy"));
                counts[key] = counts.ContainsKey(key) ? (int)counts[key]! + 1 : 1;
            }
        return new() { ["total"] = total, ["success"] = success,
            ["success_rate"] = total == 0 ? 0.0 : Math.Round((double)success / total * 100, 1), ["strategies"] = counts };
    }

    internal List<object?> Read(HistoryCapture capture)
    {
        var records = new List<object?>();
        if (!capture.Exists) return records;
        foreach (string line in capture.Lines)
        {
            if (string.IsNullOrWhiteSpace(line) || !TryParse(line, out object? row) || !Truth(row)) continue;
            records.Add(row);
        }
        return records;
    }

    internal object? LastGood(HistoryCapture capture, string appKey)
    {
        if (appKey.Length == 0) return null;
        var records = Read(capture).Where(row => Comparison.Equals(Text(Property(row, "app_key")), appKey)
            && Success(Property(row, "success")) && Truth(Property(row, "strategy"))).ToList();
        // Original Sort-Object does not request a stable sort. Use List.Sort,
        // not OrderBy or a fabricated most-recent tie rule. Framework/Core
        // equal-key permutations remain a hard Windows differential gate.
        // PS5 ISO timestamps remain strings: offsets compare lexically.
        records.Sort((left, right) => -CompareTimestamp(Property(left, "ts"), Property(right, "ts")));
        return records.FirstOrDefault();
    }

    private bool TryParse(string line, out object? row)
    {
        try { row = HistoryJson.Parse(line, runtime); return true; }
        catch (JsonException) { row = null; return false; }
    }

    private int CompareTimestamp(object? left, object? right)
    {
        if (left is null) return right is null ? 0 : -1;
        if (right is null) return 1;
        if (left is DateTime a && right is DateTime b) return a.CompareTo(b);
        if (IsNumber(left) && IsNumber(right)) return Convert.ToDouble(left, CultureInfo.InvariantCulture).CompareTo(Convert.ToDouble(right, CultureInfo.InvariantCulture));
        // Sort-Object defaults to the caller's culture (unlike -eq). Mixed
        // non-string IComparable coercions are deliberately not claimed exact.
        return culture.CompareInfo.Compare(Text(left), Text(right), CompareOptions.IgnoreCase);
    }

    internal static object? Property(object? value, string name)
    {
        if (value is Dictionary<string, object?> members)
            return members.FirstOrDefault(p => KeyComparer.Equals(p.Key, name)).Value;
        if (value is not List<object?> elements) return null;
        var results = new List<object?>();
        foreach (object? element in elements)
        {
            object? member = Property(element, name);
            if (member is List<object?> nested) results.AddRange(nested);
            else if (member is not null) results.Add(member);
        }
        return results.Count switch { 0 => null, 1 => results[0], _ => results };
    }

    internal static bool Truth(object? value) => value switch
    {
        null => false, bool boolean => boolean, string text => text.Length > 0,
        List<object?> list => list.Count > 1 || list.Count == 1 && Truth(list[0]),
        _ when IsNumber(value) => Convert.ToDouble(value, CultureInfo.InvariantCulture) != 0,
        _ => true
    };

    internal static bool Success(object? value)
    {
        // -eq on a collection filters matching values; the if condition then
        // applies PowerShell collection truthiness, not any-nonzero coercion.
        if (value is List<object?> list) return Truth(list.Where(ScalarEqualsTrue).ToList());
        return ScalarEqualsTrue(value);
    }
    private static bool ScalarEqualsTrue(object? value) => value switch
    {
        bool boolean => boolean,
        string text => Comparison.Equals(text, "True"),
        _ when IsNumber(value) => Convert.ToDouble(value, CultureInfo.InvariantCulture) == 1,
        _ => false
    };
    private static bool IsNumber(object? value) => value is int or long or double or decimal;

    internal static string Text(object? value) => value switch
    {
        null => "", bool boolean => boolean ? "True" : "False", string text => text,
        DateTime date => date.ToString(CultureInfo.InvariantCulture),
        List<object?> list => string.Join(" ", list.Select(Text)),
        Dictionary<string, object?> obj => "@{" + string.Join("; ", obj.Select(p => p.Key + "=" + MemberText(p.Value))) + "}",
        IFormattable number => number.ToString(null, CultureInfo.InvariantCulture),
        _ => value.ToString() ?? ""
    };
    private static string MemberText(object? value) => value is List<object?> ? "System.Object[]" : Text(value);
}
