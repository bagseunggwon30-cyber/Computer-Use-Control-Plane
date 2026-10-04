using System.Text.Json;

/// <summary>Closed pure-operation registry. No shell, PowerShell, filesystem, network or input.</summary>
internal static class LegacyCompatibilityDispatcher
{
    internal static object Execute(JsonElement request, bool confirmationOnly = false)
    {
        if (request.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Compatibility request must be an object.");
        var fields = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in request.EnumerateObject())
            if (!fields.Add(property.Name) || property.Name is not ("schema" or "operation" or "args" or "culture"))
                throw CommandOptions.Invalid("Compatibility request has duplicate or unknown fields.");
        if (!request.TryGetProperty("schema", out var schema) || schema.ValueKind != JsonValueKind.String || schema.GetString() != "cucp.legacy-compat/v1" ||
            !request.TryGetProperty("operation", out var operation) || operation.ValueKind != JsonValueKind.String ||
            !request.TryGetProperty("args", out var args) || args.ValueKind != JsonValueKind.Object)
            throw CommandOptions.Invalid("Expected schema, operation and args under cucp.legacy-compat/v1.");
        if (confirmationOnly && operation.GetString() != "execution-confirmation")
            throw CommandOptions.Invalid("The execution confirmation entry accepts only execution-confirmation.");
        return operation.GetString() switch
        {
            "execution-confirmation" => LegacyExecutionStartup.Confirmation(args),
            "safety-classify" => LegacySafetyKernel.Classify(args),
            "safety-truncate" => LegacySafetyKernel.Truncate(args),
            "coord-map" => LegacyCoordinateKernel.Map(args),
            "coord-window" => LegacyCoordinateKernel.SelectWindow(args),
            "coord-batch-points" => LegacyCoordinateKernel.BatchPoints(args),
            "coord-macro-prepare" => LegacyCoordinateMacro.Prepare(args),
            "strategy-score" => LegacyStrategyKernel.Score(args),
            "strategy-normalize" => LegacyStrategyKernel.Normalize(args),
            "workflow-plan-from-parsed" => LegacyWorkflowKernel.PlanFromParsed(args),
            "task-preset-prepare" => LegacyTaskPresetKernel.PreparePreset(args),
            "task-preset-complete" => LegacyTaskPresetKernel.CompletePreset(args),
            "task-plan-prepare" => LegacyTaskFormKernel.PrepareTask(args),
            "task-plan-assemble" => LegacyTaskFormKernel.AssembleTask(args),
            "task-plan-complete" => LegacyTaskFormKernel.CompleteTask(args),
            "form-plan-prepare" => LegacyTaskFormKernel.PrepareForm(args),
            "form-plan-complete" => LegacyTaskFormKernel.CompleteForm(args),
            "smart-plan-advance" => EvaluateSmartPlan(args),
            "app-profile-advance" => LegacyAppProfileController.Advance(args),
            _ => throw CommandOptions.Invalid("Unsupported pure compatibility operation.")
        };
    }

    private static object EvaluateSmartPlan(JsonElement args)
    {
        // Preserve the qualified planner's semantic-error boundary before replay
        // begins. Errors during replay already carry the exact acquired trace.
        try { return LegacySmartPlanKernel.Advance(args); }
        catch (Exception error)
        {
            return new { state = "error", error = error.Message, queries = Array.Empty<object>() };
        }
    }
}
