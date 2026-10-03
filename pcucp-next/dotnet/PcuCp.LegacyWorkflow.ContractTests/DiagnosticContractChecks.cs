using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security.Cryptography;

internal static partial class LegacyWorkflowKernel
{
    internal static void CheckDiagnosticContracts(Action<bool, string> check)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-diagnostic-candidate.json")));
        var cases = document.RootElement.GetProperty("cases");
        var observed = 0;
        var inferred = 0;
        foreach (var fixture in cases.EnumerateArray())
        {
            var id = fixture.GetProperty("id").GetString()!;
            var step = fixture.GetProperty("step").GetString()!;
            if (fixture.GetProperty("evidence").GetString() == "observed-windows-powershell-5.1") observed++; else inferred++;
            var expected = fixture.GetProperty("preflight_error").GetString();
            var preflight = PreflightParseErrors(step);
            check((preflight?.Error ?? "") == expected, "Diagnostic preflight contract: " + id);
            check(preflight is null || !preflight.Ok && preflight.Tokens.Length == 0, "Preflight cannot accept or reinterpret tokens: " + id);
            if (fixture.TryGetProperty("candidate_error", out var candidateError))
            {
                var actual = ParseStep(step);
                check(!actual.Ok && actual.Error == candidateError.GetString() && actual.Tokens.Length == 0, "Diagnostic precedence contract: " + id);
            }
        }
        check(observed == 9 && inferred > 30, "Explicitly separate observed errors from inferred precedence contracts");
        CheckObservedDiagnosticRepair(check);
        Console.WriteLine($"Diagnostic candidate replay: {observed} observed top-level errors and {inferred} inferred precedence/opaque-region contracts. Exact localized diagnostics remain unqualified.");
    }

    private static void CheckObservedDiagnosticRepair(Action<bool, string> check)
    {
        var rawBytes = File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "workflow-raw-diagnostics-observed.json"));
        using var raw = JsonDocument.Parse(rawBytes);
        using var manifest = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-diagnostic-repair.json")));
        var provenance = manifest.RootElement.GetProperty("provenance");
        check(Convert.ToHexString(SHA256.HashData(rawBytes)).ToLowerInvariant() == provenance.GetProperty("raw_capture_sha256").GetString(), "Immutable diagnostic capture bytes");
        check(raw.RootElement.GetProperty("comparison_completed").GetBoolean() && raw.RootElement.GetProperty("cases").GetArrayLength() == 101, "Complete original 101-case capture");
        var targets = manifest.RootElement.GetProperty("target_ids").EnumerateArray().Select(value => value.GetString()!).ToHashSet(StringComparer.Ordinal);
        check(targets.Count == 3, "Exactly three observed diagnostic repair targets");
        var replayed = 0;
        foreach (var fixture in raw.RootElement.GetProperty("cases").EnumerateArray())
        {
            var id = fixture.GetProperty("id").GetString()!;
            if (!targets.Contains(id)) continue;
            var step = fixture.GetProperty("step").GetString()!;
            var expected = fixture.GetProperty("parsed");
            var actual = ParseStep(step);
            check(actual.Ok == expected.GetProperty("ok").GetBoolean() && actual.Error == expected.GetProperty("error").GetString() &&
                actual.Tokens.SequenceEqual(expected.GetProperty("tokens").EnumerateArray().Select(token => token.GetString()!)), "Observed diagnostic code/token replay: " + id);
            check(!actual.Ok && actual.Tokens.Length == 0, "Diagnostic repair cannot accept a construct: " + id);
            // Original diagnostic wording is replayed as data, not synthesized.
            // Candidate-local explanations are still a separate parity debt.
            var plan = PlanFromParsed(JsonSerializer.SerializeToElement(new { rest = new[] { "--step", step }, parsed_steps = new[] { expected.Clone() } }));
            check(JsonNode.DeepEquals(JsonNode.Parse(JsonSerializer.Serialize(plan)), JsonNode.Parse(fixture.GetProperty("plan").GetRawText())), "Exact original diagnostic plan preservation: " + id);
            replayed++;
        }
        check(replayed == 3, "All three observed diagnostic targets replayed");
        var neighbors = manifest.RootElement.GetProperty("inferred_neighbors");
        foreach (var fixture in neighbors.EnumerateArray())
        {
            var id = fixture.GetProperty("id").GetString()!;
            var step = fixture.GetProperty("step").GetString()!;
            check(fixture.GetProperty("evidence").GetString() == "inferred-unqualified", "Neighbor evidence remains inferred: " + id);
            check((PreflightParseErrors(step)?.Error ?? "") == fixture.GetProperty("preflight_error").GetString(), "Inferred context preflight: " + id);
            var actual = ParseStep(step);
            check(!actual.Ok && actual.Error == fixture.GetProperty("candidate").GetProperty("error").GetString() && actual.Tokens.Length == 0, "Inferred context remains rejected: " + id);
        }
        Console.WriteLine($"Observed diagnostic repair: {replayed}/3 error-code/token replays and exact original-plan pass-throughs; {neighbors.GetArrayLength()} inferred rejection neighbors. Historical raw capture retains 84/101 exact differences, including 73 text-only and 11 normalized differences; these overlapping counts are not full grammar parity.");
    }

}
