using System.Text.Json;

/// <summary>Closed pure-operation registry. No shell, PowerShell, filesystem, network or input.</summary>
internal static class LegacyCompatibilityDispatcher
{
    internal static object Execute(JsonElement request)
    {
        if (request.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Compatibility request must be an object.");
        var fields = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in request.EnumerateObject())
            if (!fields.Add(property.Name) || property.Name is not ("schema" or "operation" or "args"))
                throw CommandOptions.Invalid("Compatibility request has duplicate or unknown fields.");
        if (!request.TryGetProperty("schema", out var schema) || schema.ValueKind != JsonValueKind.String || schema.GetString() != "cucp.legacy-compat/v1" ||
            !request.TryGetProperty("operation", out var operation) || operation.ValueKind != JsonValueKind.String ||
            !request.TryGetProperty("args", out var args) || args.ValueKind != JsonValueKind.Object)
            throw CommandOptions.Invalid("Expected schema, operation and args under cucp.legacy-compat/v1.");
        return operation.GetString() switch
        {
            "safety-classify" => LegacySafetyKernel.Classify(args),
            "safety-truncate" => LegacySafetyKernel.Truncate(args),
            "coord-map" => LegacyCoordinateKernel.Map(args),
            "strategy-score" => LegacyStrategyKernel.Score(args),
            "strategy-normalize" => LegacyStrategyKernel.Normalize(args),
            "workflow-plan-from-parsed" => LegacyWorkflowKernel.PlanFromParsed(args),
            _ => throw CommandOptions.Invalid("Unsupported pure compatibility operation.")
        };
    }
}
