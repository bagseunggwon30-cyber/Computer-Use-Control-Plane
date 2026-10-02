using System.Text.Json;

// Independent assertions for the accepted benchmark invariants. Captured native
// replies and deterministic clock effects exercise production coordination only.
internal static class DiagnosticBoundaryRegressionChecks
{
    private static int checks;
    private static void Check(bool condition, string id, string detail)
    {
        if (!condition) throw new InvalidOperationException($"{id}: {detail}");
        checks++;
    }
    private static JsonElement Benchmark(int iterations, object[] replies, int[] clocks) =>
        JsonSerializer.SerializeToElement(DiagnosticFixture.Evaluate(JsonSerializer.SerializeToElement(new
        {
            operation = "benchmark", rest = new[] { "--iters", iterations.ToString(System.Globalization.CultureInfo.InvariantCulture) }, replies, clocks
        })));
    private static JsonElement[] Results(JsonElement result, int samples, string id)
    {
        Check(result.GetProperty("state").GetString() == "complete", id, "Benchmark did not complete: " + result);
        var rows = result.GetProperty("payload").GetProperty("results").EnumerateArray().ToArray();
        Check(rows.Select(r => r.GetProperty("name").GetString()).SequenceEqual(new[] { "windows", "health", "focused", "modal-detect" }), id, "Benchmark omitted or reordered a target");
        Check(result.GetProperty("consumed").GetInt32() == samples, id, "Benchmark omitted a captured sample");
        Check(result.GetProperty("effects").EnumerateArray().Count(e => e.GetProperty("kind").GetString() == "Native") == samples, id, "Unexpected native acquisition count");
        return rows;
    }
    internal static void Run()
    {
        ZeroSuccessfulSamples(); Console.WriteLine("PASS LR10 zero successful samples cannot pass an SLO");
        NearestRankP95(); Console.WriteLine("PASS LR11 nearest-rank p95 includes max of three samples");
        Console.WriteLine($"Passed {checks} independent diagnostic boundary assertions across 2 accepted regression IDs.");
    }

    private static void ZeroSuccessfulSamples()
    {
        const string id = "LR10";
        // A plausible JSON status cannot override an unsuccessful native exit.
        var replies = Enumerable.Repeat<object>(new { exit = 5, json = new { status = "ok" } }, 8).ToArray();
        var result = Benchmark(2, replies, [10, 20, 30, 40, 50, 60, 70, 80]);
        foreach (var row in Results(result, 8, id))
        {
            Check(row.GetProperty("ok_count").GetInt32() == 0 && row.GetProperty("failure_count").GetInt32() == 2, id, "Failed native exit became a successful sample");
            Check(!row.GetProperty("slo_ok").GetBoolean(), id, "No evidence passed an SLO");
            Check(row.GetProperty("p95_ms").ValueKind == JsonValueKind.Null && row.GetProperty("p50_ms").ValueKind == JsonValueKind.Null && row.GetProperty("avg_ms").ValueKind == JsonValueKind.Null, id, "Failed samples supplied timing statistics");
            var samples = row.GetProperty("samples").EnumerateArray().ToArray();
            Check(samples.Length == 2 && samples.All(s => !s.GetProperty("ok").GetBoolean()), id, "Failed sample evidence was lost");
        }
        Check(result.GetProperty("payload").GetProperty("slo_pass_count").GetInt32() == 0, id, "Aggregate SLO count passed without successful samples");
    }

    private static void NearestRankP95()
    {
        const string id = "LR11";
        var replies = Enumerable.Repeat<object>(new { exit = 0, json = new { status = "ok" } }, 12).ToArray();
        var result = Benchmark(3, replies, [10, 40, 30, 70, 20, 60, 2, 4, 3, 80, 50, 60]);
        var rows = Results(result, 12, id); int[] expected = [40, 70, 4, 80];
        for (int index = 0; index < rows.Length; index++)
        {
            var row = rows[index]; var samples = row.GetProperty("samples").EnumerateArray().ToArray();
            Check(samples.Length == 3 && samples.All(s => s.GetProperty("ok").GetBoolean()) && row.GetProperty("ok_count").GetInt32() == 3, id, "Fixture did not produce three successful observations");
            Check(row.GetProperty("p95_ms").GetInt32() == expected[index], id, "Nearest-rank p95 dropped the slowest observation");
            Check(row.GetProperty("p95_ms").GetInt32() == samples.Max(s => s.GetProperty("ms").GetInt32()), id, "p95 differs from the slowest successful sample");
        }
    }
}
