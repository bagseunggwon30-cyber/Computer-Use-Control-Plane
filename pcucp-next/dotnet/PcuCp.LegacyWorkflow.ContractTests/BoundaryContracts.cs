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
        return count;
    }
}
