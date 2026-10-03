using System.Globalization;
using System.Text.Json;

internal sealed record HistoryFixture(string Id, string Operation, string Culture, HistoryCapture Capture,
    string Label, string Match, int Lookback, string AppKey);
internal static class HistoryContracts
{
    internal static HistoryFixture Validate(JsonElement fixture)
    {
        RequireObject(fixture, ["id", "operation", "culture", "exists", "lines", "label", "match", "lookback", "app_key"]);
        string id = String(fixture, "id", true), operation = String(fixture, "operation", true), culture = String(fixture, "culture", true);
        if (id.Length is < 1 or > 200 || operation is not ("pick" or "stats" or "app-read" or "last-good")) throw new ArgumentException("Invalid fixture identity/operation.");
        if (culture is not ("" or "en-US" or "ko-KR" or "tr-TR" or "de-DE")) throw new ArgumentException("Unsupported qualification culture.");
        if (!fixture.TryGetProperty("exists", out var exists) || exists.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new ArgumentException("Expected captured file existence.");
        if (!fixture.TryGetProperty("lines", out var lines) || lines.ValueKind != JsonValueKind.Array || lines.GetArrayLength() > 4096) throw new ArgumentException("Expected at most 4096 captured lines.");
        var captured = new List<string>(); long length = 0;
        foreach (var line in lines.EnumerateArray())
        {
            if (line.ValueKind != JsonValueKind.String) throw new ArgumentException("Captured lines must be strings.");
            string text = line.GetString()!;
            if (text.Length > 1024 * 1024 || text.Contains('\r') || text.Contains('\n')) throw new ArgumentException("Expected bounded physical file lines.");
            length += text.Length;
            if (length > 4 * 1024 * 1024) throw new ArgumentException("Capture exceeds 4 Mi characters.");
            captured.Add(text);
        }
        if (!exists.GetBoolean() && captured.Count != 0) throw new ArgumentException("Missing file cannot supply captured lines.");
        int lookback = 5;
        if (fixture.TryGetProperty("lookback", out var value) && (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out lookback))) throw new ArgumentException("Lookback must be Int32.");
        return new(id, operation, culture, new(exists.GetBoolean(), captured.ToArray()), String(fixture, "label"), String(fixture, "match"), lookback, String(fixture, "app_key"));
    }
    private static void RequireObject(JsonElement value, string[] allowed)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new ArgumentException("Fixture must be an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var member in value.EnumerateObject())
            if (!names.Add(member.Name) || !allowed.Contains(member.Name, StringComparer.Ordinal)) throw new ArgumentException("Unknown or duplicate fixture member.");
    }
    private static string String(JsonElement value, string name, bool required = false)
    {
        if (!value.TryGetProperty(name, out var member)) return required ? throw new ArgumentException("Missing " + name) : "";
        if (member.ValueKind != JsonValueKind.String || member.GetString()!.Length > 1024 * 1024) throw new ArgumentException("Expected bounded string " + name);
        return member.GetString()!;
    }

    internal static void Run()
    {
        int checks = 0;
        void Check(bool result, string message) { checks++; if (!result) throw new InvalidOperationException(message); }
        void Reject(string json)
        {
            using var doc = JsonDocument.Parse(json);
            try { Validate(doc.RootElement); } catch (ArgumentException) { checks++; return; }
            throw new InvalidOperationException("Invalid capture accepted.");
        }
        var reducer = new HistoryReducer("ps51", CultureInfo.GetCultureInfo("en-US"));
        HistoryCapture Capture(params string[] lines) => new(true, lines);
        string Row(string strategy, bool success = true, string label = "Save") => JsonSerializer.Serialize(new { label, match = "App", strategy, success });
        Check(reducer.Pick(new(false, []), "Save", "App", 5) is null, "Missing pick");
        Check(reducer.Pick(Capture(), "Save", "App", 5) is null, "Empty pick");
        Check(reducer.Pick(Capture(Row("old"), Row("new")), "Save", "App", 5) as string == "new", "Recent tie");
        Check(reducer.Pick(Capture(Row("old"), Row("old"), Row("new")), "Save", "App", 5) as string == "old", "Frequency");
        Check(reducer.Pick(Capture(Row("old"), Row("old"), Row("new")), "Save", "App", 1) as string == "new", "Lookback");
        Check(reducer.Pick(Capture(Row("yes"), Row("failure", false)), "Save", "App", 1) is null, "Failed records consume lookback");
        Check(reducer.Pick(Capture(Row("yes"), "broken", Row("irrelevant", label: "other")), "Save", "App", 1) as string == "yes", "Only matching valid rows consume lookback");
        Check(reducer.Pick(Capture(Row("UIA"), Row("uia")), "save", "APP", 5) as string == "uia", "Recent key spelling retained");
        foreach (int n in new[] { 0, -1, int.MinValue }) Check(reducer.Pick(Capture(Row("x")), "Save", "App", n) is null, "Nonpositive lookback");
        foreach (object? input in new object?[] { true, 1, 1L, 1m, 1.0, "true", "TRUE", new List<object?> { false, true } }) Check(HistoryReducer.Success(input), "Expected success coercion");
        foreach (object? input in new object?[] { null, false, 0, 2, "false", "1", "", new List<object?> { false } }) Check(!HistoryReducer.Success(input), "Unexpected success coercion");
        foreach (object? input in new object?[] { null, false, 0, "", new List<object?>(), new List<object?> { false } }) Check(!HistoryReducer.Truth(input), "False truth coercion");
        Check(HistoryReducer.Truth(new List<object?> { false, false }), "Multiple false values are truthy as collection");
        Check((int)reducer.Stats(Capture(""))["total"]! == 0 && (int)reducer.Stats(Capture("", ""))["total"]! == 2, "Outer line-array truthiness");
        var stats = reducer.Stats(Capture("", " ", "null", "false", "0", "[]", "broken", Row("x")));
        Check((int)stats["total"]! == 7 && (int)stats["success"]! == 1, "Blank/null/scalar rows counted; malformed ignored");
        Check((double)stats["success_rate"]! == 14.3, "Rounding");
        foreach ((int successes, double expected) in new[] { (1, 6.2), (3, 18.8) })
            Check((double)reducer.Stats(Capture(Enumerable.Range(0, 16).Select(i => Row("x", i < successes)).ToArray()))["success_rate"]! == expected, "Midpoint-to-even rounding");
        Check(reducer.Read(Capture("", "null", "false", "0", "[]", "[false]", "{}", "1", "\"value\"", "[false,false]", "broken")).Count == 4, "App read truth filter");
        Check(HistoryReducer.Text(new List<object?> { 1, true, null, "x" }) == "1 True  x", "Strategy interpolation");
        var rows = Capture("{\"ts\":\"2020\",\"app_key\":\"KEY\",\"strategy\":\"a\",\"success\":true,\"extra\":{\"preserve\":[1,2]}}",
            "{\"ts\":\"2021\",\"app_key\":\"key\",\"strategy\":\"b\",\"success\":true,\"extra\":42}");
        Check(HistoryReducer.Property(reducer.LastGood(rows, "Key"), "extra") is int n2 && n2 == 42, "LastGood preserves all fields");
        Check(reducer.LastGood(rows, "") is null, "Empty app key");
        Check(HistoryReducer.KeyComparer.Equals("X", "x"), "Hashtable comparer casing");
        Check(!HistoryReducer.KeyComparer.Equals("é", "e\u0301"), "Hashtable does not merge linguistic equivalents");
        Check(HistoryJson.Parse("[1]", "ps51") is List<object?>, "PS5 keeps root array");
        Check(HistoryJson.Parse("[1]", "ps7") is long, "PS7 singleton pipeline candidate");
        Check(HistoryJson.Parse("{x:'v'}", "ps51") is Dictionary<string, object?>, "Framework JSON dialect");
        Check(HistoryJson.Parse("\"\\/Date(0)\\/\"", "ps51") is DateTime, "Framework DateTime preserved");
        Check(HistoryJson.Parse("\"2020-01-01T00:00:00Z\"", "ps51") is string, "PS5 ISO text retained");
        string valid = "{\"id\":\"x\",\"operation\":\"stats\",\"culture\":\"\",\"exists\":true,\"lines\":[]}";
        using (var doc = JsonDocument.Parse(valid)) Check(Validate(doc.RootElement).Capture.Exists, "Valid capture");
        foreach (string invalid in new[] { valid.Replace("\"exists\":true", "\"exists\":1"), valid.Replace("\"lines\":[]", "\"lines\":[null]"), valid.Replace("\"lines\":[]", "\"lines\":[\"a\\nb\"]"),
            valid.Replace("\"exists\":true,\"lines\":[]", "\"exists\":false,\"lines\":[\"{}\"]"), valid.Replace("\"lines\":[]", "\"lines\":[],\"path\":\"C:\\\\private\""),
            valid.Replace("\"id\":\"x\"", "\"id\":\"x\",\"id\":\"y\""), valid.Replace("\"stats\"", "\"append\""), valid.Replace("\"culture\":\"\"", "\"culture\":\"unknown\""),
            valid.Replace("\"lines\":[]", "\"lines\":[],\"lookback\":1.5") }) Reject(invalid);
        using (var unicode = new MemoryStream(HistoryTransport.Utf8.GetBytes("한글😀 é e\u0301 İ 𐐷")))
            Check(HistoryTransport.Read(unicode) == "한글😀 é e\u0301 İ 𐐷", "Strict UTF-8 round trip");
        foreach (byte[] invalid in new byte[][] { [0xFF], [0xC0, 0xAF], [0xED, 0xA0, 0x80], [0xF0, 0x80, 0x80, 0x80], [0xE2, 0x82] })
        {
            using var malformed = new MemoryStream(invalid);
            try { HistoryTransport.Read(malformed); }
            catch (System.Text.DecoderFallbackException) { checks++; continue; }
            throw new InvalidOperationException("Malformed UTF-8 was replaced or accepted.");
        }
        Check(HistoryWire.CompactOutput(null, "ps51").Length == 0, "Observed PS5 top-level null emits no JSON item");
        Check(HistoryWire.CompactOutput(null, "ps7").SequenceEqual(new[] { "null" }), "PS7 literal JSON null remains distinct");
        Check(HistoryWire.CompactOutput(new List<object?>(), "ps51").SequenceEqual(new[] { "[]" }), "Empty array is one JSON string");
        Check(HistoryWire.CompactOutput(new List<object?> { null }, "ps51").SequenceEqual(new[] { "[null]" }), "Singleton null array preserves cardinality");
        Check(HistoryWire.CompactOutput(new Dictionary<string, object?> { ["value"] = null }, "ps51").SequenceEqual(new[] { "{\"value\":null}" }), "Nested null remains explicit JSON null");
        Check(HistoryWire.CompactOutput("", "ps51").SequenceEqual(new[] { "\"\"" }), "Empty string is not absent output");
        Console.WriteLine($"PASS: {checks} inferred history contracts; no PowerShell, file acquisition, provider or production operations executed.");
    }
}
