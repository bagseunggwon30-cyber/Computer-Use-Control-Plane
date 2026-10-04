using System.Text.Json;

/// <summary>Closed pure precision replay. No acquisition, persistence or input.</summary>
internal static class LegacyPrecisionFacade
{
    internal static object Execute(JsonElement request)
    {
        string[] names = request.ValueKind == JsonValueKind.Object ? request.EnumerateObject().Select(p => p.Name).ToArray() : [];
        string[] fields = ["schema", "operation", "args", "culture"];
        if (names.Length != fields.Length || names.Distinct(StringComparer.Ordinal).Count() != names.Length || fields.Any(n => !names.Contains(n)) ||
            request.GetProperty("schema").ValueKind != JsonValueKind.String || request.GetProperty("schema").GetString() != "cucp.legacy-precision-advance/v1" ||
            request.GetProperty("operation").ValueKind != JsonValueKind.String || request.GetProperty("args").ValueKind != JsonValueKind.Object)
            throw CommandOptions.Invalid("Expected closed typed precision advance request.");
        string operation = request.GetProperty("operation").GetString()!;
        if (operation is not ("coord-anchor" or "point-plan" or "target-validate" or "history-read" or "history-distance" or "history-score" or
            "cache-key" or "confidence-rank" or "size-class" or "edge-distance" or "child-plan-envelope"))
            throw CommandOptions.Invalid("Unknown pure precision operation.");
        return LegacyPrecisionKernel.Advance(operation, request.GetProperty("args"));
    }
}
