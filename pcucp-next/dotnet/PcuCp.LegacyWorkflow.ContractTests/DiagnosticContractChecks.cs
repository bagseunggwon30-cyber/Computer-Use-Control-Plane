using System.Text.Json;

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
        Console.WriteLine($"Diagnostic candidate replay: {observed} observed top-level errors and {inferred} inferred precedence/opaque-region contracts. Exact localized diagnostics remain unqualified.");
    }
}
