using System.Collections;
using System.Globalization;
using System.Text.Encodings.Web;
using System.Text.Json;

internal static class HistoryWire
{
    private static readonly JsonSerializerOptions Strings = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    internal static object Encode(object? value) => value switch
    {
        null => new { kind = "null" },
        Hashtable table => new { kind = "hashtable", properties = table.Keys.Cast<string>().Select(k => new { name = k, value = Encode(table[k]) }).ToArray() },
        Dictionary<string, object?> obj => new { kind = "object", properties = obj.Select(p => new { name = p.Key, value = Encode(p.Value) }).ToArray() },
        List<object?> list => new { kind = "array", items = list.Select(Encode).ToArray() },
        DateTime date => new { kind = "scalar", type = "DateTime", value = (object)date.ToString("o", CultureInfo.InvariantCulture) },
        _ => new { kind = "scalar", type = value.GetType().Name, value }
    };

    // PS5.1's actual null host observation (run 37092069983) has no
    // ConvertTo-Json pipeline output. Keep this distinct from PS7's existing
    // literal "null" output and from null nested inside an object or array.
    internal static string[] CompactOutput(object? value, string runtime) =>
        runtime == "ps51" && value is null ? [] : [Compact(value, runtime)];

    // Compact JSON is an exact-string observation, never canonicalized by the
    // Python gate. Hashtable enumeration is intentionally visible; Core's
    // randomized hash order is NOT assumed to match Framework PowerShell.
    internal static string Compact(object? value, string runtime) => value switch
    {
        null => "null", bool b => b ? "true" : "false", string s => Quote(s),
        Hashtable table => "{" + string.Join(",", table.Keys.Cast<string>().Select(k => Quote(k) + ":" + Compact(table[k], runtime))) + "}",
        Dictionary<string, object?> obj => "{" + string.Join(",", obj.Select(p => Quote(p.Key) + ":" + Compact(p.Value, runtime))) + "}",
        List<object?> list => "[" + string.Join(",", list.Select(v => Compact(v, runtime))) + "]",
        DateTime date => runtime == "ps51" ? "\"\\/Date(" + new DateTimeOffset(date).ToUnixTimeMilliseconds().ToString(CultureInfo.InvariantCulture) + ")\\/\"" : Quote(date.ToString("o", CultureInfo.InvariantCulture)),
        double number => Double(number),
        IFormattable number => number.ToString(null, CultureInfo.InvariantCulture),
        _ => throw new ArgumentException("Unknown candidate value type.")
    };
    private static string Quote(string value) => JsonSerializer.Serialize(value, Strings);
    private static string Double(double value)
    {
        string text = value.ToString("R", CultureInfo.InvariantCulture);
        return text.Contains('.') || text.Contains('E') || text.Contains('e') ? text : text + ".0";
    }
}
