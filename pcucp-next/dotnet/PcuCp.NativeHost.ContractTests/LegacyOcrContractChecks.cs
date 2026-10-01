using System.Text.Json;

internal static class LegacyOcrContractChecks
{
    internal static void Run(Action<bool, string> check)
    {
        check(LegacyOcrMatcher.Normalize(" ＳＡＶＥ—Ａｓ! 설정 １２3 ") == "save as 설정 123", "Legacy normalization changed");
        foreach (var (needle, hay, mode, expected) in new[] {
            ("Save", "Save", "exact", 100), ("Save", "Save changes", "prefix", 80),
            ("Save", "Save changes", "contains", 70), ("Save", "Changes Save", "contains", 60),
            ("Save", "Sava", "fuzzy", 75), ("설정", "설졍", "fuzzy", 50),
            ("", "text", "fuzzy", 0), ("!", "!", "exact", 0) })
        {
            long budget = 100000;
            check(LegacyOcrMatcher.Score(needle, hay, mode, ref budget) == expected, "Legacy score changed: " + mode);
        }
        var request = """
            {"schema":"cucp.legacy-ocr-match/v1","needle":"Save As","mode":"exact","body":{"lines":[
                {"text":"Save As","x":0,"y":0,"w":31,"h":11,"cx":16,"cy":6,"words":[
                    {"text":"Save","x":0,"y":0,"w":21,"h":11,"cx":10,"cy":6},
                    {"text":"As","x":22,"y":0,"w":9,"h":11,"cx":26,"cy":6}]}]}}
            """;
        using var doc = JsonDocument.Parse(request);
        var result = JsonSerializer.SerializeToElement(LegacyOcrMatcher.Match(doc.RootElement));
        var items = result.GetProperty("candidates");
        check(items.GetArrayLength() == 2 && items[0].GetProperty("scope").GetString() == "word_ngram", "Legacy ngram priority lost");
        check(items[0].GetProperty("cx").GetInt32() == 16 && items[0].GetProperty("cy").GetInt32() == 6, "Legacy midpoint rounding lost");
        foreach (var invalid in new[] { "{}", request.Replace("\"exact\"", "\"eval\""), request.Replace("\"schema\":", "\"unknown\":1,\"schema\":") })
        {
            try { using var bad = JsonDocument.Parse(invalid); LegacyOcrMatcher.Match(bad.RootElement); check(false, "Invalid compatibility input accepted"); }
            catch (NativeFailure) { check(true, "Invalid input rejected"); }
        }
        long exhausted = 0;
        try { LegacyOcrMatcher.Score("a", "b", "fuzzy", ref exhausted); check(false, "Unbounded fuzzy work accepted"); }
        catch (NativeFailure) { check(true, "Fuzzy work budget enforced"); }
    }
}
