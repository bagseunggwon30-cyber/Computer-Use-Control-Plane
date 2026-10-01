using System.Text;
using System.Text.Json;

/// <summary>
/// Pure workflow planning. Never evaluates text or executes a command.
/// The literal lexer is a qualification candidate, not a full PowerShell parser;
/// keep the original parser until Windows differential qualification is complete.
/// </summary>
internal static class LegacyWorkflowKernel
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
    private static readonly HashSet<string> ReservedStarts = new(Comparer)
    {
        "begin", "break", "catch", "class", "continue", "data", "define", "do", "dynamicparam", "else", "elseif", "end", "exit",
        "filter", "finally", "for", "foreach", "from", "function", "if", "in", "param", "process", "return", "switch", "throw",
        "trap", "try", "until", "using", "var", "while", "workflow", "parallel", "sequence", "inlinescript", "configuration"
    };

    internal static object Plan(JsonElement args)
    {
        if (args.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Workflow arguments must be an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in args.EnumerateObject())
            if (!names.Add(property.Name) || property.Name != "rest") throw CommandOptions.Invalid("Unknown or duplicate workflow argument.");
        if (!args.TryGetProperty("rest", out var rest) || rest.ValueKind != JsonValueKind.Array || rest.GetArrayLength() > 4096)
            throw CommandOptions.Invalid("rest must be an array with at most 4096 strings.");
        var values = new List<string>();
        var length = 0;
        foreach (var item in rest.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Each rest item must be a string.");
            var value = item.GetString()!;
            length += value.Length;
            if (value.Contains('\0') || length > 262144) throw CommandOptions.Invalid("rest exceeds the input limit or contains NUL.");
            values.Add(value);
        }
        return Plan(values.ToArray());
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

    internal static object Plan(string[] rest)
    {
        var specs = ReadStepSpecs(rest);
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
            var parsed = ParseStep(raw);
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

    // Explicit literal-only lexer. It never expands a variable, substitutes a
    // command, treats a string as executable code, or invokes a parser runtime.
    // Rejections outside this subset are intentional qualification gaps, not
    // evidence of compatibility with every token sequence accepted by PSParser.
    internal static ParsedStep ParseStep(string step)
    {
        if (step.Length > 65536 || step.Contains('\0')) return Reject("unsupported_token", "Step exceeds the literal input limit or contains NUL.");
        var items = new List<string>();
        var index = 0;
        var commandStart = true;
        while (index < step.Length)
        {
            if (char.IsWhiteSpace(step[index]) && step[index] is not (' ' or '\t' or '\r' or '\n'))
                return Reject("unsupported_token", "Non-ASCII token whitespace is not yet qualified.");
            if (char.IsWhiteSpace(step[index]))
            {
                if (step[index] is '\r' or '\n') commandStart = true;
                index++;
                continue;
            }
            if (step[index] == '`' && index + 1 < step.Length && step[index + 1] is '\r' or '\n')
            {
                index += 2;
                if (step[index - 1] == '\r' && index < step.Length && step[index] == '\n') index++;
                continue;
            }
            var first = step[index];
            var startsQuoted = IsSingle(first) || IsDouble(first);
            if (commandStart && first is '.' or '+' or '-' or '!')
                return Reject("unsupported_token", "Expression and dot-sourcing prefixes require further parser qualification.");
            if (first == '#' || first == '@') return Reject("unsupported_token", "Comments, splatting and here-strings are outside the literal-command subset.");
            if (first == '-' && index + 1 < step.Length && (char.IsLetter(step[index + 1]) || step[index + 1] is '_' or '?'))
                return Reject("unsupported_token", "unsupported token type 'CommandParameter'");
            var value = new StringBuilder();
            while (index < step.Length && !char.IsWhiteSpace(step[index]))
            {
                var c = step[index++];
                if (c is '$' or '(' or ')' or '{' or '}' or '[' or ']' or ';' or '|' or '&' or '<' or '>' or ',')
                    return Reject("unsupported_token", "Operators, variables and execution constructs are not literal command tokens.");
                if (c == '`')
                {
                    if (index == step.Length) { value.Append('`'); continue; }
                    var escaped = step[index++];
                    if (escaped is '\r' or '\n')
                        return Reject("unsupported_token", "Adjacent-token line continuation is not yet qualified.");
                    value.Append(Unescape(escaped));
                    continue;
                }
                if (IsSingle(c) || IsDouble(c))
                {
                    var single = IsSingle(c);
                    var closed = false;
                    while (index < step.Length)
                    {
                        var quoted = step[index++];
                        if (single ? IsSingle(quoted) : IsDouble(quoted))
                        {
                            if (index < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index])))
                            { value.Append(step[index++]); continue; }
                            closed = true;
                            break;
                        }
                        if (!single && quoted == '$') return Reject("unsupported_token", "Expandable strings require further parser qualification.");
                        if (!single && quoted == '`' && index < step.Length) quoted = Unescape(step[index++]);
                        value.Append(quoted);
                    }
                    if (!closed) return Reject("parse_error", "The string is missing its terminator.");
                    continue;
                }
                value.Append(c);
            }
            var content = value.ToString();
            if (index < step.Length && char.IsWhiteSpace(step[index]) && step[index] is not (' ' or '\t' or '\r' or '\n'))
                return Reject("unsupported_token", "Non-ASCII token whitespace is not yet qualified.");
            if (commandStart)
            {
                if (ReservedStarts.Contains(content)) return Reject("unsupported_token", "Reserved statement keywords are not literal commands.");
                if (startsQuoted || content.Length > 0 && (char.IsDigit(content[0]) || content[0] is '+' or '-'))
                {
                    // A leading quoted/number expression cannot silently be
                    // reinterpreted as a command followed by arbitrary arguments.
                    var remainder = step[index..].TrimStart(' ', '\t');
                    if (remainder.Length > 0 && remainder[0] is not ('\r' or '\n'))
                        return Reject("parse_error", "Expression-form command prefixes are not supported.");
                }
                commandStart = false;
            }
            if (content.Length > 0) items.Add(content); // Original drops empty literal strings.
        }
        return new(items.Count > 0, items.Count > 0 ? "" : "empty_step", "", items.ToArray());
    }

    private static bool IsSingle(char c) => c is '\'' or '\u2018' or '\u2019' or '\u201A' or '\u201B';
    private static bool IsDouble(char c) => c is '"' or '\u201C' or '\u201D' or '\u201E';
    private static char Unescape(char c) => c switch
    {
        '0' => '\0', 'a' => '\a', 'b' => '\b', 'f' => '\f', 'n' => '\n', 'r' => '\r', 't' => '\t', 'v' => '\v',
        _ => c // PowerShell 5.1: `e and `u do not have the PowerShell 6+ meanings.
    };
    private static ParsedStep Reject(string error, string detail) => new(false, error, detail, []);
}
