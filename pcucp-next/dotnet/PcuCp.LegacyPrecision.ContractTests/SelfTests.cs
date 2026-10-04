using System.Text.Json;
using System.Text;

internal static class SelfTests
{
    internal static void Run()
    {
        int checks = 0;
        void Check(bool condition, string why) { checks++; if (!condition) throw new InvalidOperationException(why); }
        JsonElement Run(string op, object args) => JsonSerializer.SerializeToElement(LegacyPrecisionKernel.Advance(op, JsonSerializer.SerializeToElement(args)));
        JsonElement Complete(string op, object args)
        {
            var result = Run(op, args); Check(result.GetProperty("state").GetString() == "complete", op + " did not complete"); return result.GetProperty("payload");
        }
        var rest = new[] { "--x", "100", "--y", "100", "--target-match", "Fixture" };
        var initial = Run("point-plan", new { rest });
        Check(initial.GetProperty("query").GetProperty("kind").GetString() == "hit-test", "Guard must be acquired first");
        var guardArgs = new { x = 100, y = 100, target_hwnd = 0, target_match = "Fixture" };
        var guard = new { kind = "hit-test", args = guardArgs, result = new { status = "ok", matched = false } };
        var profileArgs = new { has_point = true, x = 100, y = 100, target_hwnd = 0, target_match = "Fixture" };
        var profile = new { kind = "coord-profile", args = profileArgs, result = new { status = "ok", coordinate_risk = "low", warnings = Array.Empty<string>() } };
        var stopped = Run("point-plan", new { rest, captured_replies = new object[] { guard, profile }, cache_seconds = 10 });
        Check(stopped.GetProperty("state").GetString() == "complete", "Mismatched guard should complete");
        Check(stopped.GetProperty("exit").GetInt32() == 2, "Mismatched guard must remain partial");
        Check(stopped.GetProperty("queries").GetArrayLength() == 2, "Mismatched guard must not scan/cache");
        Check(stopped.GetProperty("effects").GetArrayLength() == 0, "Mismatched guard must not write cache");
        Check(!stopped.GetProperty("payload").GetProperty("mouse_moved").GetBoolean(), "Planning must not move mouse");
        var noGuard = Complete("point-plan", new { rest, captured_replies = new object[] { new { kind = "hit-test", args = guardArgs, result = (object?)null }, profile }, cache_seconds = 10 });
        Check(noGuard.GetProperty("precheck").ValueKind == JsonValueKind.Object && !noGuard.GetProperty("precheck").EnumerateObject().Any(), "PS5 no-output guard must render an empty object");
        Check(noGuard.GetProperty("checks")[0].GetProperty("evidence").GetRawText() == "{}", "No-output evidence shape changed");
        Check(noGuard.GetProperty("reason").GetString() == "fast_guard_mismatch", "No-output guard must remain false");
        var noMap = Complete("coord-anchor", new { rest, captured_replies = new[] { new { kind = "coord-map", args = new { from = "screen", x = 100, y = 100, norm_x = 0, norm_y = 0, has_norm = false, target_hwnd = 0, target_match = "Fixture" }, result = (object?)null } } });
        Check(noMap.GetProperty("coord_map").GetRawText() == "{}", "PS5 no-output map must render an empty object");
        Check(LegacyPrecisionKernel.S(JsonSerializer.SerializeToElement(new { value = new[] { "macro", "click-point" }, Count = 2 })) == "@{value=System.Object[]; Count=2}", "PS5 object member array stringification changed");
        foreach (var replies in new object[][] { [new { kind = "hit-scan", args = guardArgs, result = (object?)null }], [guard, profile, guard], [new { kind = "hit-test", args = guardArgs, result = (object?)null, error = "ambiguous" }] })
            Check(Run("point-plan", new { rest, captured_replies = replies }).GetProperty("state").GetString() == "error", "Malformed/unused capture accepted");
        foreach (var value in new[] { ("high", 3), ("HIGH", 3), ("medium", 2), ("low", 1), ("unknown", 0), ("", 0) })
            Check(Complete("confidence-rank", new { value = value.Item1 }).GetInt32() == value.Item2, "Confidence rank changed");
        foreach (int width in new[] { 0, 1, 20, 21, 44, 45, 100, 140, 141 })
        foreach (int height in new[] { 0, 1, 20, 21, 32, 33, 100, 101 })
        {
            string expected = width <= 0 || height <= 0 ? "unknown" : width <= 20 || height <= 20 || width * height <= 900 ? "tiny" : width <= 44 || height <= 32 || width * height <= 2200 ? "small" : width <= 140 && height <= 100 ? "medium" : "large";
            Check(Complete("size-class", new { rect = new { width, height }, area = 0 }).GetString() == expected, "Size threshold changed");
        }
        for (int x = -1; x <= 10; x++) for (int y = -1; y <= 10; y++)
        {
            var edge = Complete("edge-distance", new { point = new { x, y }, rect = new { x = 0, y = 0, width = 10, height = 10 } });
            Check(edge.GetProperty("min").GetInt32() == Math.Min(Math.Min(x, y), Math.Min(9 - x, 9 - y)), "Inclusive/exclusive edge changed");
        }
        var read = Complete("history-read", new { lines = new[] { "bad", "", "{\"n\":1}", "{\"n\":2}" }, last = 2 });
        Check(read.GetArrayLength() == 2 && read[1].GetProperty("n").GetInt32() == 2, "History tail order changed");
        Check(Complete("history-distance", new { a = new { x = .1, y = .2 }, b = new { x = .1, y = .2 } }).GetDouble() == 0, "Normalized distance changed");
        Check(Complete("history-distance", new { a = (object?)null, b = new { x = 0, y = 0 } }).GetDouble() == double.MaxValue, "Missing point distance changed");
        var record = new { anchor_id = "same", target_match = "Fixture", normalized_window_point = new { x = .5, y = .5 }, safe_to_reuse = true, coordinate_risk = "low", coord_signature = "one", ts = "old" };
        var scored = Complete("history-score", new { record, records = Enumerable.Repeat(record, 8).ToArray(), tolerance = .012, history_file = "history" });
        Check(scored.GetProperty("score").GetInt32() == 100, "Score clamp changed");
        Check(scored.GetProperty("matched_record_count").GetInt32() == 8, "Exact duplicates must remain independent matches");
        Check(scored.GetProperty("near_match_count").GetInt32() == 8, "Near counts overlap exact matches");
        var empty = Complete("history-score", new { record, records = Array.Empty<object>(), history_file = "history" });
        Check(empty.GetProperty("score").GetInt32() == 45, "No-history safe score changed");
        var largeRecords = Enumerable.Range(0, 500).Select(i => new { anchor_id = S(i), payload = new string('x', 1900) }).ToArray();
        var large = Run("history-score", new { record, records = largeRecords, history_file = "history" });
        Check(large.GetProperty("state").GetString() == "complete", "Near-cap history must complete");
        Check(JsonSerializer.Serialize(large).Length < 4096, "History result must not echo captured large history");
        var point = new { x = 100, y = 100, native_clickable = true, point_source = "native" };
        var plan = new { status = "ok", safe_to_act = true, confidence = "high", recommended_point = point, recommended_command = new[] { "macro", "click-point" }, precheck = new { matched = true }, coordinate_profile = new { coordinate_risk = "low", warnings = Array.Empty<string>() }, best = new { match = new { rect = new { x = 99, y = 99, width = 20, height = 20 } }, support = 1, pattern = "" } };
        var childArgs = new { argv = new[] { "--x", "100", "--y", "100", "--radius", "6", "--step", "2", "--click-inset", "2", "--cache-ttl", "0", "--target-match", "Fixture" } };
        var validated = Run("target-validate", new { rest, captured_replies = new[] { new { kind = "point-plan-child", args = childArgs, result = new { exit = 0, raw = "json", json = plan } } } });
        Check(validated.GetProperty("payload").GetProperty("safe_to_click").GetBoolean(), "Supported tiny target rejected");
        Check(validated.GetProperty("payload").GetProperty("validation").GetProperty("near_element_edge").GetBoolean(), "Edge warning must remain advisory");
        var special = Complete("history-read", new { lines = new[] { "{\"value\":[1,2],\"Count\":2}" } });
        Check(special[0].ValueKind == JsonValueKind.Object, "value/Count object was guessed to be an array");
        var reader = new ReadEffectsFixture();
        var inProcess = JsonSerializer.SerializeToElement(LegacyPrecisionKernel.Execute("coord-anchor", JsonSerializer.SerializeToElement(new { rest = rest.Concat(new[] { "--record-history" }).ToArray(), history_file = "H", history_max = 500, now = "clock", elapsed_ms = 0 }), reader));
        Check(inProcess.GetProperty("state").GetString() == "complete", "In-process anchor did not complete");
        Check(reader.Maps == 1 && reader.Histories == 1, "In-process observations must be acquired only once");
        Check(inProcess.GetProperty("effects").GetArrayLength() == 1, "Requested history write must be a terminal effect");
        Check(!inProcess.GetProperty("payload").GetProperty("reuse_history").GetProperty("recorded").GetBoolean(), "Unexecuted history effect must not claim success");
        Check(inProcess.GetProperty("payload").GetProperty("reuse_history").EnumerateObject().Last().Name == "recorded", "Legacy Add-Member -Force must put recorded last before rendering");
        Check(JsonSerializer.Serialize(inProcess).Length < 10000, "Terminal result must not echo near-cap history lines");
        var childEnvelope = Complete("child-plan-envelope", new { raw_lines = new[] { "{", "  \"status\":\"ok\"", "}" }, exit_code = 2 });
        Check(childEnvelope.GetProperty("exit").GetInt32() == 2 && childEnvelope.GetProperty("json").GetProperty("status").GetString() == "ok", "Child output parsing/exit changed");
        Check(childEnvelope.GetProperty("raw").GetString() == "{\n  \"status\":\"ok\"\n}", "Child output must join raw lines with LF");
        Check(Complete("child-plan-envelope", new { raw_lines = new[] { "not JSON" }, exit_code = 1 }).GetProperty("json").ValueKind == JsonValueKind.Null, "Unparseable child output must stay null");
        try { LegacyPrecisionSession.ReadStartup(new StringReader(new string('x', 4194305))); throw new Exception("Startup bound ignored"); }
        catch (LegacyExecutionProtocolException) { Check(true, "Startup is bounded before complete line allocation"); }
        Check(LegacyPrecisionSession.ReadStartup(new StringReader("\uFEFF{\"test\":true}\r\n")).GetProperty("test").GetBoolean(), "Single Framework startup BOM was rejected");
        foreach (string invalid in new[] { "\uFEFF\uFEFF{}\n", "{\uFEFF}\n", "{}\uFEFF\n", " \uFEFF{}\n" })
        {
            try { LegacyPrecisionSession.ReadStartup(new StringReader(invalid)); throw new Exception("Invalid startup BOM accepted"); }
            catch (JsonException) { Check(true, "Repeated or embedded startup BOM rejected"); }
        }
        Storage(Check);
        Console.WriteLine($"PASS: {checks} isolated precision contracts; no desktop probes or input executed.");
    }
    private sealed class ReadEffectsFixture : IPrecisionReadEffects
    {
        internal int Maps, Histories;
        public object? CoordinateMap(PrecisionTargetPoint point)
        {
            Maps++;
            return JsonSerializer.SerializeToElement(new { status = "ok", selected_window = new { hwnd = 42, title = "Fixture", process = "app", @class = "Window", rect = new { x = 0, y = 0, width = 200, height = 200 } }, normalized_window_point = new { x = .5, y = .5 }, screen_point = new { x = 100, y = 100 }, inside_window = true, inside_visible_clip = true, coordinate_profile = new { coordinate_risk = "low", coord_signature = "signature" }, warnings = Array.Empty<string>() });
        }
        public string[] HistoryLines(string path)
        {
            if (path != "H") throw new InvalidOperationException("History authority changed");
            Histories++; return Enumerable.Range(0, 500).Select(n => JsonSerializer.Serialize(new { anchor_id = S(n), payload = new string('x', 1900) })).ToArray();
        }
        public object? HitTest(PrecisionTargetPoint point) => throw new InvalidOperationException("Unexpected hit test");
        public object? CoordinateProfile(PrecisionTargetPoint point) => throw new InvalidOperationException("Unexpected coordinate profile");
        public object? HitScan(PrecisionScan scan) => throw new InvalidOperationException("Unexpected hit scan");
        public object? ChildPointPlan(PrecisionChildPlan plan) => throw new InvalidOperationException("Unexpected child plan");
        public object? ReadCache(string path, string key, int maximumAgeSeconds) => throw new InvalidOperationException("Unexpected cache read");
    }
    private static string S(int value) => value.ToString(System.Globalization.CultureInfo.InvariantCulture);
    private static void Storage(Action<bool, string> check)
    {
        string root = Path.Combine(Path.GetTempPath(), "CUCP precision " + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try
        {
            string history = Path.Combine(root, "nested", "한글.jsonl"), cache = Path.Combine(root, "cache"); Directory.CreateDirectory(cache);
            DateTime clock = new(2026, 10, 2, 1, 2, 3, DateTimeKind.Local); var store = new LegacyPrecisionStorage(history, cache, () => clock); string key = new('a', 32);
            check(store.HistoryLines().Length == 0, "Missing history must be empty");
            check(store.AppendHistory("{\"n\":1}", 500), "History append failed");
            check(File.ReadAllBytes(history).Take(3).SequenceEqual(new byte[] { 239, 187, 191 }), "History BOM missing");
            check(store.HistoryLines().Length == 1, "History append count changed");
            for (int i = 2; i <= 51; i++) store.AppendHistory("{\"n\":" + i + "}", 50);
            check(store.HistoryLines().Length == 50, "History trimming changed");
            var tinyStore = new LegacyPrecisionStorage(Path.Combine(root, "tiny-history"), cache, () => clock);
            check(tinyStore.AppendHistory("{\"n\":0}", 1) && tinyStore.AppendHistory("{\"n\":1}", 1), "Tiny-limit append failed");
            check(tinyStore.HistoryLines().SequenceEqual(new[] { "{\"n\":0}", "{\"n\":1}", "{\"n\":0}", "{\"n\":1}" }), "Negative multi-index history selection must drop out-of-range entries");
            store.WriteCache(key, "{\"status\":\"ok\"}"); File.SetLastWriteTime(store.CachePath(key), clock.AddSeconds(-5));
            var hit = JsonSerializer.SerializeToElement(store.ReadCache(key, 5)); check(hit.GetProperty("AgeMs").GetInt32() == 5000, "TTL equality must hit");
            check(store.ReadCache(key, 4) == null, "Stale cache must miss");
            File.SetLastWriteTime(store.CachePath(key), clock.AddSeconds(1));
            check(JsonSerializer.SerializeToElement(store.ReadCache(key, 1)).GetProperty("AgeMs").GetInt32() == -1000, "Future timestamps must retain negative age");
            File.WriteAllText(store.CachePath(key), "invalid"); check(store.ReadCache(key, 9999) == null, "Malformed cache must miss");
            string blocker = Path.Combine(root, "file"); File.WriteAllText(blocker, "block");
            var failed = new LegacyPrecisionStorage(Path.Combine(blocker, "history"), blocker, () => clock);
            check(!failed.AppendHistory("{}", 500), "Directory creation failure must return false");
            failed.WriteCache(key, "{}"); check(File.ReadAllText(blocker) == "block", "Cache write failure modified blocker");
            try { store.CachePath("../escape"); throw new Exception("Path accepted"); } catch (ArgumentException) { check(true, "Path key rejected"); }
        }
        finally { Directory.Delete(root, true); }
    }
}
