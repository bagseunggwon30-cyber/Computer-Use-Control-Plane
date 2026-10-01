using System.Text.Json;

/// <summary>
/// Pure workflow planning. Never evaluates text or executes a command.
/// The literal lexer is a qualification candidate, not a full PowerShell parser;
/// keep the original parser until Windows differential qualification is complete.
/// </summary>
internal static partial class LegacyWorkflowKernel
{
    internal sealed record ParsedStep(bool Ok, string Error, string Detail, string[] Tokens);
    private static readonly StringComparer Comparer = StringComparer.InvariantCultureIgnoreCase;
    private static readonly HashSet<string> ReadOnlyMacros = new(Comparer)
    {
        "windows", "native-windows", "wait-window", "wait-label", "find-label", "list-affordances",
        "health-quick", "health-detail", "native-health", "metrics", "perf", "log-tail", "diagnose-lag",
        "session", "trajectory", "history", "screenshot", "native-screenshot",
        "safety-classify", "coord-profile", "coord-map", "coord-anchor", "hit-test", "hit-test-batch", "hit-scan", "point-plan", "target-validate", "smart-plan", "app-profile", "task-preset", "task-plan", "form-plan",
        "cdp-detect", "cdp-smart-find", "cdp-smart-type-find", "ocr-screen", "ocr-image", "ocr-find-text", "ocr-uia-fuse", "screenshot-diff",
        "cdp-deep-find", "modal-detect", "recovery-plan", "precision-validate", "benchmark", "release-notes"
    };
    private static readonly HashSet<string> LiveMacros = new(Comparer)
    {
        "app-launch", "app-close", "with-app", "focus-window", "focus-verify",
        "click-label", "double-click-label", "right-click-label", "click-id", "click-point",
        "fill-label", "shortcut", "shortcut-native", "type-native", "uia-click-label",
        "uia-invoke", "uia-set-value", "uia-toggle", "safe-type", "smart-click", "form-run",
        "icon-click", "vision-click", "vision-click-precise", "click-and-verify", "click-and-verify-screen",
        "ocr-click", "ocr-uia-invoke", "cdp-type", "cdp-click", "cdp-eval", "cdp-smart-click", "cdp-smart-type",
        "auto-do", "goal", "notify", "multi-select", "multi-edit", "clipboard", "process", "registry",
        "ime-paste", "safe-type-ime", "recovery-run"
    };
    private static void Fields(JsonElement args, params string[] allowed)
    {
        if (args.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Workflow arguments must be an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in args.EnumerateObject())
            if (!names.Add(property.Name) || !allowed.Contains(property.Name)) throw CommandOptions.Invalid("Unknown or duplicate workflow argument.");
    }

    private static string[] ReadRest(JsonElement args, bool allowNul)
    {
        if (!args.TryGetProperty("rest", out var rest) || rest.ValueKind != JsonValueKind.Array || rest.GetArrayLength() > 4096)
            throw CommandOptions.Invalid("rest must be an array with at most 4096 strings.");
        var values = new List<string>();
        var length = 0;
        foreach (var item in rest.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Each rest item must be a string.");
            var value = item.GetString()!;
            length += value.Length;
            if ((!allowNul && value.Contains('\0')) || length > 262144)
                throw CommandOptions.Invalid("rest exceeds the input limit or contains unsupported NUL.");
            values.Add(value);
        }
        return values.ToArray();
    }

    /// <summary>Assemble a plan from results of the retained, exact PSParser adapter.
    /// Token data is never evaluated. This method never calls the candidate lexer.
    /// </summary>
    internal static object PlanFromParsed(JsonElement args)
    {
        Fields(args, "rest", "parsed_steps");
        var rest = ReadRest(args, allowNul: true);
        var specs = ReadStepSpecs(rest);
        if (specs.Length > 256) throw CommandOptions.Invalid("Workflow contains more than 256 steps.");
        if (!args.TryGetProperty("parsed_steps", out var rawSteps) || rawSteps.ValueKind != JsonValueKind.Array || rawSteps.GetArrayLength() != specs.Length)
            throw CommandOptions.Invalid("parsed_steps must have one result for every derived --step specification.");
        var parsedSteps = new List<ParsedStep>();
        var totalUnits = 0;
        foreach (var step in rawSteps.EnumerateArray())
        {
            Fields(step, "ok", "error", "detail", "tokens");
            if (!step.TryGetProperty("ok", out var rawOk) || rawOk.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
                !step.TryGetProperty("error", out var rawError) || rawError.ValueKind != JsonValueKind.String ||
                !step.TryGetProperty("detail", out var rawDetail) || rawDetail.ValueKind != JsonValueKind.String ||
                !step.TryGetProperty("tokens", out var rawTokens) || rawTokens.ValueKind != JsonValueKind.Array || rawTokens.GetArrayLength() > 4096)
                throw CommandOptions.Invalid("Each parsed result requires boolean ok, string error/detail and at most 4096 string tokens.");
            var ok = rawOk.GetBoolean();
            var error = rawError.GetString()!;
            var detail = rawDetail.GetString()!;
            if (error.Length > 64 || detail.Length > 65536) throw CommandOptions.Invalid("Parsed diagnostic exceeds its length bound.");
            totalUnits += error.Length + detail.Length;
            var tokens = new List<string>();
            foreach (var token in rawTokens.EnumerateArray())
            {
                if (token.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Parsed tokens must be strings.");
                var value = token.GetString()!;
                if (value.Length is 0 or > 65536) throw CommandOptions.Invalid("Parsed tokens must contain 1..65536 UTF-16 units.");
                totalUnits += value.Length;
                if (totalUnits > 262144) throw CommandOptions.Invalid("Parsed results exceed 262144 UTF-16 units.");
                tokens.Add(value);
            }
            if (totalUnits > 262144) throw CommandOptions.Invalid("Parsed results exceed 262144 UTF-16 units.");
            if (ok ? (error.Length != 0 || detail.Length != 0 || tokens.Count == 0) :
                (tokens.Count != 0 || error is not ("parse_error" or "unsupported_token" or "empty_step")))
                throw CommandOptions.Invalid("Inconsistent parsed result: preserve the exact parser success/error shape.");
            parsedSteps.Add(new ParsedStep(ok, error, detail, tokens.ToArray()));
        }
        return Assemble(rest, specs, parsedSteps.ToArray());
    }

    internal static string[] ReadStepSpecs(string[] rest)
    {
        var result = new List<string>();
        for (var i = 0; i < rest.Length; i++)
        {
            if (!Comparer.Equals(rest[i], "--step")) continue;
            var start = ++i;
            while (i < rest.Length && !Comparer.Equals(rest[i], "--step")) i++;
            result.Add(string.Join(" ", rest[start..i]));
            i--;
        }
        return result.ToArray();
    }

    private static object Assemble(string[] rest, string[] specs, ParsedStep[] parsedSteps)
    {
        if (specs.Length == 0) throw CommandOptions.Invalid("macro workflow-plan/run requires --step \"macro <name> ...\"");
        if (specs.Length > 256) throw CommandOptions.Invalid("Workflow contains more than 256 steps.");
        string? name = null;
        for (var i = 0; i + 1 < rest.Length; i++)
            if (Comparer.Equals(rest[i], "--name")) { name = rest[i + 1]; break; }
        var steps = new List<object>();
        var errors = new List<object>();
        var allowedCount = 0;
        var liveCount = 0;
        var sensitiveCount = 0;
        for (var i = 0; i < specs.Length; i++)
        {
            var raw = specs[i];
            var index = i + 1;
            var parsed = parsedSteps[i];
            if (!parsed.Ok)
            {
                errors.Add(new { index, code = parsed.Error, message = parsed.Detail, step = raw });
                continue;
            }
            var command = parsed.Tokens;
            if (!Comparer.Equals(command[0], "macro")) command = ["macro", .. command];
            if (command.Length < 2)
            {
                errors.Add(new { index, code = "missing_macro_name", message = "step must name a macro", step = raw });
                continue;
            }
            var macro = command[1];
            bool allowed, liveRequired;
            string reason;
            if (Comparer.Equals(macro, "workflow-plan") || Comparer.Equals(macro, "workflow-run"))
                (allowed, liveRequired, reason) = (false, false, "recursive_workflow_blocked");
            else if (Comparer.Equals(macro, "session"))
            {
                var action = command.Length >= 3 ? command[2] : "info";
                allowed = new[] { "info", "helper-status", "autostart-status" }.Contains(action, Comparer);
                liveRequired = !allowed;
                reason = allowed ? "read_only_session_action" : "mutating_session_action_not_in_workflow_allowlist";
            }
            else if (ReadOnlyMacros.Contains(macro)) (allowed, liveRequired, reason) = (true, false, "read_only_macro");
            else if (LiveMacros.Contains(macro)) (allowed, liveRequired, reason) = (true, true, "live_macro");
            else (allowed, liveRequired, reason) = (false, false, "macro_not_in_workflow_allowlist");
            if (!allowed) errors.Add(new { index, code = reason, message = "workflow step macro is not allowed", macro, step = raw });
            var safety = LegacySafetyKernel.Classify(JsonSerializer.SerializeToElement(new { text = string.Join(" ", command), macro }));
            var requiresSensitive = liveRequired && JsonSerializer.SerializeToElement(safety).GetProperty("requires_explicit_confirmation").GetBoolean();
            if (allowed) allowedCount++;
            if (liveRequired) liveCount++;
            if (requiresSensitive) sensitiveCount++;
            steps.Add(new { index, raw, macro, command, allowed, live_required = liveRequired, reason, safety,
                requires_sensitive_confirmation = requiresSensitive });
        }
        var safeToRun = steps.Count > 0 && allowedCount == steps.Count && errors.Count == 0;
        return new
        {
            schema = "cucp.workflow-plan/v1", status = safeToRun ? "ok" : "partial", name,
            step_count = steps.Count, allowed_count = allowedCount, live_step_count = liveCount, sensitive_step_count = sensitiveCount,
            requires_sensitive_confirmation = sensitiveCount > 0, safe_to_run = safeToRun,
            safety_policy = new
            {
                schema = "cucp.safety-policy/v1", confirmation_flag = "--confirm-sensitive",
                levels_requiring_confirmation = new[] { "medium", "high", "critical" },
                categories_requiring_confirmation = new[] { "credentials", "payment", "destructive", "external_send", "identity_or_privacy", "system_change", "app_settings" }
            },
            steps, errors
        };
    }

}
