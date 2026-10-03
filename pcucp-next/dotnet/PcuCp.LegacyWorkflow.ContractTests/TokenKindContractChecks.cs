using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

internal static partial class LegacyWorkflowKernel
{
    private static void CheckTokenKindRepair(Action<bool, string> check)
    {
        var rawBytes = File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "workflow-token-kind-raw.json"));
        using var raw = JsonDocument.Parse(rawBytes);
        using var manifest = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-token-kind-repair.json")));
        var root = manifest.RootElement;
        check(Convert.ToHexString(SHA256.HashData(rawBytes)).ToLowerInvariant() == root.GetProperty("provenance").GetProperty("raw_capture_sha256").GetString(), "Immutable token-kind raw capture bytes");
        var targets = root.GetProperty("target_ids").EnumerateArray().Select(value => value.GetString()!).ToHashSet(StringComparer.Ordinal);
        check(targets.Count == 20, "Twenty observed token-kind targets");
        check(raw.RootElement.GetProperty("comparison_completed").GetBoolean() && raw.RootElement.GetProperty("cases").GetArrayLength() == 128, "Complete original 128-case capture");
        var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
        object FixturePlan(string step)
        {
            // Replay the same public argument-validation route as --fixtures,
            // including existing NUL validation failures before plan assembly.
            try { return Plan(JsonSerializer.SerializeToElement(new { rest = new[] { "--step", step } })); }
            catch (NativeFailure failure) { return new { threw = true, error = failure.Code }; }
        }
        var changed = 0;
        foreach (var fixture in raw.RootElement.GetProperty("cases").EnumerateArray())
        {
            var id = fixture.GetProperty("id").GetString()!;
            var step = fixture.GetProperty("step").GetString()!;
            var actual = ParseStep(step);
            // Targets match the untouched oracle exactly. Every other parsed
            // result AND full plan must retain the prior candidate's bytes of
            // diagnostic text and its acceptance/token behavior as JSON values.
            var expected = targets.Contains(id) ? fixture : fixture.GetProperty("candidate");
            check(JsonNode.DeepEquals(JsonNode.Parse(JsonSerializer.Serialize(actual, options)), JsonNode.Parse(expected.GetProperty("parsed").GetRawText())), "Exact token-kind parsed replay: " + id);
            check(JsonNode.DeepEquals(JsonNode.Parse(JsonSerializer.Serialize(FixturePlan(step), options)), JsonNode.Parse(expected.GetProperty("plan").GetRawText())), "Exact token-kind full plan replay: " + id);
            if (!targets.Contains(id)) continue;
            check(!actual.Ok && actual.Error == "unsupported_token" && actual.Tokens.Length == 0 && PreflightParseErrors(step) is null, "Token-kind repair remains rejection-only: " + id);
            changed++;
        }
        check(changed == 20, "All twenty exact token-kind repairs replayed");
        var neighbors = root.GetProperty("inferred_live_neighbors");
        foreach (var fixture in neighbors.EnumerateArray())
        {
            var id = fixture.GetProperty("id").GetString()!;
            var step = fixture.GetProperty("step").GetString()!;
            var actual = ParseStep(step);
            var expected = fixture.GetProperty("candidate");
            check(fixture.GetProperty("evidence").GetString() == "inferred-unqualified", "New token-kind probe remains inferred: " + id);
            check(!actual.Ok && actual.Error == expected.GetProperty("error").GetString() && actual.Tokens.Length == 0, "Token-kind rejection contract: " + id);
            if (fixture.GetProperty("comparison").GetString() == "exact")
                check(actual.Detail == expected.GetProperty("detail").GetString(), "Inferred exact token-kind detail: " + id);
            else
                check(PreflightParseErrors(step)?.Error == "parse_error", "Syntax preflight retains priority: " + id);
        }
        check(neighbors.GetArrayLength() == 24, "Twenty-four appended diagnostic probes");
        Console.WriteLine("Token-kind rejection repair: 20 exact parsed/full-plan targets; all 108 other prior candidate results unchanged; 24 inferred rejection probes. Historical 128-case replay now has 86 exact gaps (78 text-only, 8 normalized); not fresh Windows qualification or full parser parity.");
    }
}
