using System.Text.Json;

internal static class BoundaryContracts
{
    internal static int Run()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-boundary-candidate.json")));
        var root = document.RootElement;
        if (root.GetProperty("observed_provenance").GetProperty("evidence").GetString() != "observed-windows-powershell-5.1" ||
            root.GetProperty("inferred_provenance").GetProperty("evidence").GetString() != "inferred-unqualified")
            throw new Exception("Boundary fixture evidence labels changed.");
        var count = 0;
        foreach (var group in new[] { "observed", "inferred" })
        {
            foreach (var fixture in root.GetProperty(group).EnumerateArray())
            {
                var expected = fixture.GetProperty(group == "observed" ? "expected" : "candidate");
                var actual = LegacyWorkflowKernel.ParseStep(fixture.GetProperty("step").GetString()!);
                if (actual.Ok != expected.GetProperty("ok").GetBoolean() ||
                    !actual.Tokens.SequenceEqual(expected.GetProperty("tokens").EnumerateArray().Select(token => token.GetString()!)) ||
                    expected.TryGetProperty("error", out var error) && actual.Error != error.GetString())
                    throw new Exception("Boundary " + group + " contract: " + fixture.GetProperty("id").GetString() + ": " + JsonSerializer.Serialize(actual));
                count++;
            }
        }
        Console.WriteLine($"Boundary candidate: {root.GetProperty("observed").GetArrayLength()} observed PS5.1 replays and {root.GetProperty("inferred").GetArrayLength()} inferred contracts; no new Windows evidence.");
        using var observedDocument = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-ps51-boundary-observed.json")));
        var observed = observedDocument.RootElement;
        if (observed.GetProperty("provenance").GetProperty("evidence").GetString() != "observed-windows-powershell-5.1")
            throw new Exception("Boundary repair evidence label changed.");
        var targets = observed.GetProperty("repair_target_ids").EnumerateArray().Select(id => id.GetString()!).ToHashSet(StringComparer.Ordinal);
        var matched = 0;
        var gaps = observed.GetProperty("observed_gaps");
        if (gaps.GetArrayLength() != 33 || targets.Count != 5) throw new Exception("Historical boundary repair counts changed.");
        foreach (var fixture in gaps.EnumerateArray())
        {
            var expected = fixture.GetProperty("before");
            var actual = LegacyWorkflowKernel.ParseStep(fixture.GetProperty("step").GetString()!);
            var matches = actual.Ok == expected.GetProperty("ok").GetBoolean() &&
                actual.Error == expected.GetProperty("error").GetString() &&
                actual.Tokens.SequenceEqual(expected.GetProperty("tokens").EnumerateArray().Select(token => token.GetString()!));
            if (matches) matched++;
            if ((actual.Ok || targets.Contains(fixture.GetProperty("id").GetString()!)) && !matches)
                throw new Exception("Observed boundary repair regression: " + fixture.GetProperty("id").GetString());
            count++;
        }
        Console.WriteLine($"Boundary PS5.1 repair replay: {matched}/33 historical gaps match; {33 - matched} remain. This is not a new Windows run.");
        return count;
    }
}
