using System.Globalization;
using System.Text.Json;

/// <summary>Pure legacy task/form recipes and captured-result assembly. Never executes a query or command.</summary>
internal static class LegacyTaskFormKernel
{
    private static readonly StringComparer OptionComparer = StringComparer.InvariantCultureIgnoreCase;
    private static readonly JsonElement Null = JsonSerializer.SerializeToElement<object?>(null);
    private static readonly JsonElement EmptyOutput = JsonSerializer.SerializeToElement(new { });
    private sealed record Query(string kind, string[] argv);
    private sealed record Capture(int Exit, string Raw, JsonElement Plan);
    private sealed record Field(int Index, string Label, string Value);
    private sealed record FormRecipe(Options Options, Query[] Queries, Field[] Fields, object[] Errors);
    private sealed record TaskRecipe(Options Options, Query[] Queries, int WaitTimeout, int VerifyTimeout);
    private sealed record TaskAssembly(TaskRecipe Recipe, List<string> Steps, List<object> Items, List<object> Errors, JsonElement FormPlan, string[] WorkflowRest);

    private sealed class Options(string[] rest)
    {
        internal readonly string[] Rest = rest;
        internal string? Value(string name)
        {
            for (var i = 0; i + 1 < Rest.Length; i++) if (OptionComparer.Equals(Rest[i], name)) return Rest[i + 1];
            return null;
        }
        internal string[] Values(string name)
        {
            var result = new List<string>();
            for (var i = 0; i + 1 < Rest.Length; i++) if (OptionComparer.Equals(Rest[i], name)) result.Add(Rest[++i]);
            return result.ToArray();
        }
        internal bool Flag(string name) => Rest.Contains(name, OptionComparer);
        internal string? Match => Fallback(Value("--match"), Value("--window"));
        internal string? App => Fallback(Value("--app"), Value("--open-app"));
        internal string? WaitTitle => Fallback(Value("--wait-title"), Value("--verify-window"));
        internal string? CacheTtl => Fallback(Value("--point-cache-ttl"), Value("--cache-ttl"));
        internal string? ObserveMatch => string.IsNullOrEmpty(Value("--observe-match")) && !string.IsNullOrEmpty(Value("--verify-match")) ? Value("--verify-match") : Value("--observe-match");
        internal string? VerifyAfterLabel => Fallback(Value("--verify-label-after-step"), Value("--verify-after-label"));
        internal bool Observe => Flag("--observe-after-step") || Flag("--verify-after-step");
        internal string[] TypeTexts => Values("--type-text") is { Length: > 0 } values ? values : Values("--text");
        internal string[] Shortcuts => Values("--shortcut").Concat(Values("--keys")).ToArray();
    }

    internal static object PrepareTask(JsonElement args)
    {
        Fields(args, "rest");
        var recipe = BuildTask(ReadRest(args));
        return new { schema = "cucp.task-plan-preparation/v1", queries = recipe.Queries };
    }

    internal static object PrepareForm(JsonElement args)
    {
        Fields(args, "rest");
        var recipe = BuildForm(ReadRest(args));
        return new { schema = "cucp.form-plan-preparation/v1", queries = recipe.Queries };
    }

    internal static object AssembleTask(JsonElement args)
    {
        Fields(args, "rest", "captured_query_results");
        var assembly = Assemble(BuildTask(ReadRest(args)), args);
        return new
        {
            schema = "cucp.task-plan-assembly/v1", workflow_required = assembly.Steps.Count > 0,
            workflow_rest = assembly.WorkflowRest, items = assembly.Items, errors = assembly.Errors, form_plan = assembly.FormPlan
        };
    }

    internal static object CompleteTask(JsonElement args)
    {
        Fields(args, "rest", "captured_query_results", "captured_workflow_plan", "elapsed_ms");
        var assembly = Assemble(BuildTask(ReadRest(args)), args);
        var elapsed = Elapsed(args);
        var workflow = RequiredPlan(args, "captured_workflow_plan");
        if (assembly.Steps.Count == 0 && workflow.ValueKind != JsonValueKind.Null)
            throw CommandOptions.Invalid("captured_workflow_plan must be null when no workflow query is required.");
        var o = assembly.Recipe.Options;
        var safe = Truth(workflow) && Truth(Property(workflow, "safe_to_run")) && assembly.Errors.Count == 0;
        return new
        {
            schema = "cucp.task-plan/v1", status = safe ? "ok" : "partial", name = o.Value("--name"), app = o.App, match = o.Match,
            elapsed_ms = elapsed, safe_to_run = safe,
            live_step_count = Truth(workflow) ? LegacyInt(Property(workflow, "live_step_count")) : 0,
            sensitive_step_count = Truth(workflow) ? LegacyInt(Property(workflow, "sensitive_step_count")) : 0,
            requires_sensitive_confirmation = Truth(workflow) && Truth(Property(workflow, "requires_sensitive_confirmation")),
            step_count = Truth(workflow) ? LegacyInt(Property(workflow, "step_count")) : 0,
            recommended_command = assembly.Steps.Count > 0 ? WorkflowRun(o, assembly.Steps, false) : null,
            dry_run_command = assembly.Steps.Count > 0 ? WorkflowRun(o, assembly.Steps, true) : null,
            run_options = new
            {
                settle_ms = o.Value("--settle-ms"), observe_after_step = o.Observe, verify_after_step = o.Flag("--verify-after-step"),
                observe_match = o.ObserveMatch, verify_label_after_step = o.VerifyAfterLabel, verify_label_window = o.Value("--verify-label-window"),
                verify_label_timeout_ms = o.Value("--verify-label-timeout-ms"), verify_label_interval_ms = o.Value("--verify-label-interval-ms"),
                retry_failed_step = o.Value("--retry-failed-step"), retry_delay_ms = o.Value("--retry-delay-ms"), retry_live_steps = o.Flag("--retry-live-steps")
            },
            workflow_plan = workflow, items = assembly.Items, form_plan = assembly.FormPlan, errors = assembly.Errors,
            next_step = safe
                ? "Run dry_run_command first; run recommended_command with -AllowLiveControl only after user authorization when live_step_count > 0. If requires_sensitive_confirmation is true, add --confirm-sensitive only after explicit approval of that exact action."
                : "Resolve errors or unsafe embedded plans, then re-run task-plan."
        };
    }

    internal static object CompleteForm(JsonElement args)
    {
        Fields(args, "rest", "captured_query_results", "elapsed_ms");
        var recipe = BuildForm(ReadRest(args));
        var captures = Captures(args, recipe.Queries);
        var elapsed = Elapsed(args);
        var steps = new List<object>(); var commands = new List<object>(); var unsafeSteps = new List<object>();
        var safeCount = 0; var captureIndex = 0;
        void Add(int index, string kind, string label, int length)
        {
            var r = captures[captureIndex++]; var plan = r.Plan;
            var safe = Truth(plan) && Truth(Property(plan, "safe_to_act"));
            var route = Truth(plan) ? ConditionalOutput(Property(plan, "best_route")) : Null;
            var command = Truth(plan) ? ConditionalOutput(Property(plan, "recommended_command")) : Null;
            steps.Add(new { index, kind, label, value_length = length, exit = r.Exit, safe_to_act = safe, best_route = route,
                recommended_command = command, plan, raw = Truth(plan) ? null : r.Raw });
            commands.Add(new { index, kind, label, safe_to_act = safe, route, command });
            if (safe) safeCount++;
            else unsafeSteps.Add(new { index, kind, label, route, exit = r.Exit });
        }
        foreach (var field in recipe.Fields) Add(field.Index, "type", field.Label, field.Value.Length);
        var send = recipe.Options.Value("--send-label");
        var fieldCount = recipe.Options.Values("--field").Length;
        if (!string.IsNullOrEmpty(send)) Add(fieldCount + 1, "click", send, 0);
        var allSafe = steps.Count > 0 && safeCount == steps.Count && recipe.Errors.Length == 0;
        return new
        {
            schema = "cucp.form-plan/v1", status = allSafe ? "ok" : "partial", match = recipe.Options.Match,
            field_count = fieldCount, send_label = send, safe_to_act = allSafe, step_count = steps.Count, safe_step_count = safeCount,
            elapsed_ms = elapsed, command_plan = commands, unsafe_steps = unsafeSteps, steps, errors = recipe.Errors,
            next_step = allSafe ? "Run each recommended_command in order with -AllowLiveControl only after user authorization; verify after each step."
                : "Resolve unsafe steps by narrowing labels/window, enabling --allow-cdp, or inspecting each embedded smart-plan."
        };
    }

    private static TaskRecipe BuildTask(string[] rest)
    {
        var o = new Options(rest);
        // These casts precede required-input validation, including when the value will not be used.
        var wait = LegacyInt(o.Value("--wait-timeout-ms"));
        var verify = LegacyInt(o.Value("--verify-timeout-ms"));
        var fields = o.Values("--field"); var clicks = o.Values("--click-label"); var send = o.Value("--send-label");
        if (string.IsNullOrEmpty(o.App) && string.IsNullOrEmpty(o.WaitTitle) && fields.Length == 0 && clicks.Length == 0 &&
            o.TypeTexts.Length == 0 && o.Values("--pre-shortcut").Length == 0 && o.Shortcuts.Length == 0 && string.IsNullOrEmpty(send) && string.IsNullOrEmpty(o.Value("--verify-label")))
            throw CommandOptions.Invalid("macro task-plan requires --app/--wait-title/--field/--type-text/--shortcut/--click-label/--send-label/--verify-label");
        var queries = new List<Query>();
        if (fields.Length > 0 || !string.IsNullOrEmpty(send))
        {
            var command = new List<string> { "-Quiet", "macro", "form-plan" };
            foreach (var field in fields) command.AddRange(["--field", field]);
            AddValue(command, "--send-label", send);
            AddQueryOptions(command, o, clear: true, points: true);
            command.Add("--json-only"); queries.Add(new("form_plan", command.ToArray()));
        }
        foreach (var click in clicks)
        {
            var command = new List<string> { "-Quiet", "macro", "smart-plan", "--label", click };
            AddQueryOptions(command, o, clear: false, points: true);
            command.Add("--json-only"); queries.Add(new("smart_plan", command.ToArray()));
        }
        return new(o, queries.ToArray(), wait <= 0 ? 8000 : wait, verify <= 0 ? 3000 : verify);
    }

    private static FormRecipe BuildForm(string[] rest)
    {
        var o = new Options(rest); var specs = o.Values("--field"); var send = o.Value("--send-label");
        if (specs.Length == 0 && string.IsNullOrEmpty(send)) throw CommandOptions.Invalid("macro form-plan requires --field \"Label=Value\" and/or --send-label");
        var fields = new List<Field>(); var queries = new List<Query>(); var errors = new List<object>();
        for (var index = 0; index < specs.Length; index++)
        {
            var spec = specs[index] ?? ""; var equals = spec.IndexOf('=');
            if (equals <= 0) { errors.Add(new { code = "bad_field_spec", message = "field spec must be Label=Value", field = spec }); continue; }
            var label = spec[..equals].Trim();
            if (label.Length == 0) { errors.Add(new { code = "empty_field_label", message = "field label is empty", field = spec }); continue; }
            var value = spec[(equals + 1)..]; fields.Add(new(index + 1, label, value));
            var command = new List<string> { "-Quiet", "macro", "smart-plan", "--label", label, "--type-text", value };
            AddQueryOptions(command, o, clear: true, points: false);
            command.Add("--json-only"); queries.Add(new("smart_plan", command.ToArray()));
        }
        if (!string.IsNullOrEmpty(send))
        {
            var command = new List<string> { "-Quiet", "macro", "smart-plan", "--label", send };
            AddQueryOptions(command, o, clear: false, points: true);
            command.Add("--json-only"); queries.Add(new("smart_plan", command.ToArray()));
        }
        return new(o, queries.ToArray(), fields.ToArray(), errors.ToArray());
    }

    private static void AddQueryOptions(List<string> command, Options o, bool clear, bool points)
    {
        AddValue(command, "--match", o.Match);
        foreach (var flag in new[] { "--allow-cdp", "--no-cdp" }) if (o.Flag(flag)) command.Add(flag);
        foreach (var flag in new[] { "--cdp-page-match", "--cdp-port" }) AddValue(command, flag, o.Value(flag));
        if (clear && o.Flag("--clear-first")) command.Add("--clear-first");
        if (!points) return;
        if (o.Flag("--include-ocr")) command.Add("--include-ocr");
        if (o.Flag("--precision-points") || o.Flag("--point-plan")) command.Add("--precision-points");
        foreach (var flag in new[] { "--precision-radius", "--precision-step" }) AddValue(command, flag, o.Value(flag));
        AddValue(command, "--point-cache-ttl", o.CacheTtl);
    }

    private static TaskAssembly Assemble(TaskRecipe recipe, JsonElement args)
    {
        var captures = Captures(args, recipe.Queries); var cursor = 0; var o = recipe.Options;
        var steps = new List<string>(); var items = new List<object>(); var errors = new List<object>(); var form = Null;
        void Step(string[] command, string kind, bool live, params (string, object?)[] extra)
        {
            var step = LegacyTaskPresetKernel.StepString(command); steps.Add(step);
            var item = Map(("kind", kind)); foreach (var pair in extra) item.Add(pair.Item1, pair.Item2);
            item.Add("safe_to_act", true); item.Add("live_required", live); item.Add("command", command); item.Add("step", step); items.Add(item);
        }
        if (!string.IsNullOrEmpty(o.App))
        {
            var command = new List<string> { "macro", "app-launch", "--name", o.App };
            AddValue(command, "--args", o.Value("--app-args"));
            if (!string.IsNullOrEmpty(o.WaitTitle)) command.AddRange(["--wait-title", o.WaitTitle, "--wait-timeout-ms", recipe.WaitTimeout.ToString(CultureInfo.InvariantCulture)]);
            Step(command.ToArray(), "app_launch", true);
        }
        else if (!string.IsNullOrEmpty(o.WaitTitle)) Step(["macro", "wait-window", "--title", o.WaitTitle, "--timeout-ms", recipe.WaitTimeout.ToString(CultureInfo.InvariantCulture)], "wait_window", false);
        foreach (var shortcut in o.Values("--pre-shortcut")) if (!string.IsNullOrWhiteSpace(shortcut)) Step(["macro", "shortcut", "--keys", shortcut], "shortcut", true, ("phase", "pre"), ("keys", shortcut));
        var typeIndex = 0;
        foreach (var text in o.TypeTexts)
        {
            if (text is null) continue;
            typeIndex++;
            var guarded = !string.IsNullOrEmpty(o.Match);
            var command = guarded ? new List<string> { "macro", "safe-type", "--target-match", o.Match!, "--text", text } : new List<string> { "macro", "type-native", "--text", text };
            if (!guarded && o.Flag("--clear-first") && typeIndex == 1) command.Add("--clear");
            if (o.Flag("--press-enter") || o.Flag("--enter")) command.Add("--enter");
            Step(command.ToArray(), "type_text", true, ("route", guarded ? "safe_type_guarded" : "type_native"), ("index", typeIndex));
        }
        if (o.Values("--field").Length > 0 || !string.IsNullOrEmpty(o.Value("--send-label")))
        {
            var result = captures[cursor++]; form = result.Plan;
            if (!Truth(form)) errors.Add(new { code = "form_plan_unparseable", exit = result.Exit, raw = result.Raw });
            else if (!Truth(Property(form, "safe_to_act"))) errors.Add(new { code = "form_plan_not_safe", unsafe_steps = Property(form, "unsafe_steps"), errors = Property(form, "errors") });
            else foreach (var child in Enumerate(Property(form, "command_plan")))
            {
                var command = Unwrap(Property(child, "command"));
                if (command.GetArrayLength() == 0) continue;
                var step = CommandStep(command); steps.Add(step);
                items.Add(new { kind = "form_step", label = Property(child, "label"), route = Property(child, "route"), safe_to_act = true, live_required = true, command, step });
            }
        }
        foreach (var label in o.Values("--click-label"))
        {
            var result = captures[cursor++]; var plan = result.Plan;
            if (!Truth(plan) || !Truth(Property(plan, "safe_to_act"))) { errors.Add(new { code = "click_plan_not_safe", label, exit = result.Exit, plan }); continue; }
            var command = Unwrap(Property(plan, "recommended_command")); var step = CommandStep(command); steps.Add(step);
            items.Add(new { kind = "click", label, route = Property(plan, "best_route"), safe_to_act = true, live_required = true, command, step, plan });
        }
        foreach (var shortcut in o.Shortcuts) if (!string.IsNullOrWhiteSpace(shortcut)) Step(["macro", "shortcut", "--keys", shortcut], "shortcut", true, ("phase", "post"), ("keys", shortcut));
        var verify = o.Value("--verify-label");
        if (!string.IsNullOrEmpty(verify))
        {
            var command = new List<string> { "macro", "wait-label", "--label", verify, "--timeout-ms", recipe.VerifyTimeout.ToString(CultureInfo.InvariantCulture) };
            AddValue(command, "--window", o.Match); Step(command.ToArray(), "verify_label", false, ("label", verify));
        }
        var workflow = new List<string> { "--name", Fallback(o.Value("--name"), "task")! };
        foreach (var step in steps) workflow.AddRange(["--step", step]);
        return new(recipe, steps, items, errors, form, workflow.ToArray());
    }

    private static string[] WorkflowRun(Options o, List<string> steps, bool dry)
    {
        var command = new List<string> { "macro", "workflow-run" }; if (dry) command.Add("--dry-run");
        AddValue(command, "--settle-ms", o.Value("--settle-ms"));
        if (o.Observe && !o.Flag("--verify-after-step")) command.Add("--observe-after-step");
        if (o.Flag("--verify-after-step")) command.Add("--verify-after-step");
        AddValue(command, "--observe-match", o.ObserveMatch); AddValue(command, "--verify-label-after-step", o.VerifyAfterLabel);
        foreach (var name in new[] { "--verify-label-window", "--verify-label-timeout-ms", "--verify-label-interval-ms", "--retry-failed-step", "--retry-delay-ms" }) AddValue(command, name, o.Value(name));
        if (o.Flag("--retry-live-steps")) command.Add("--retry-live-steps");
        foreach (var step in steps) command.AddRange(["--step", step]);
        return command.ToArray();
    }

    // The qualified helper's step is computed BEFORE unwrapping. Call it again
    // on the unwrapped array to preserve the original UnwrapCommand -> StepString order.
    private static JsonElement Unwrap(JsonElement command) => JsonSerializer.SerializeToElement(LegacyTaskPresetKernel.CommandHelpers(JsonSerializer.SerializeToElement(new { command }))).GetProperty("unwrapped").Clone();
    private static string CommandStep(JsonElement command) => JsonSerializer.SerializeToElement(LegacyTaskPresetKernel.CommandHelpers(JsonSerializer.SerializeToElement(new { command }))).GetProperty("step").GetString()!;
    private static Dictionary<string, object?> Map(params (string, object?)[] pairs) => pairs.ToDictionary(p => p.Item1, p => p.Item2);
    private static string? Fallback(string? first, string? second) => string.IsNullOrEmpty(first) ? second : first;
    private static void AddValue(List<string> command, string name, string? value) { if (!string.IsNullOrEmpty(value)) command.AddRange([name, value]); }
    private static JsonElement Property(JsonElement value, string name)
    {
        if (value.ValueKind == JsonValueKind.Object)
            foreach (var property in value.EnumerateObject()) if (OptionComparer.Equals(property.Name, name)) return property.Value.Clone();
        return Null;
    }
    // A property emitted from an if statement is collected as pipeline output:
    // one item becomes a scalar, while zero items are AutomationNull.Value.
    // Windows PowerShell 5.1 serializes that empty output sentinel as {}.
    private static JsonElement ConditionalOutput(JsonElement value) => value.ValueKind == JsonValueKind.Array
        ? value.GetArrayLength() switch { 0 => EmptyOutput, 1 => value[0].Clone(), _ => value }
        : value;
    private static IEnumerable<JsonElement> Enumerate(JsonElement value) => value.ValueKind == JsonValueKind.Array ? value.EnumerateArray() : value.ValueKind == JsonValueKind.Null ? [] : new[] { value };
    private static bool Truth(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined or JsonValueKind.False => false, JsonValueKind.True or JsonValueKind.Object => true,
        JsonValueKind.String => value.GetString()!.Length > 0, JsonValueKind.Number => value.GetDouble() != 0,
        JsonValueKind.Array => value.GetArrayLength() > 1 || (value.GetArrayLength() == 1 && Truth(value[0])), _ => false
    };

    internal static int LegacyInt(string? source)
    {
        if (string.IsNullOrEmpty(source)) return 0;
        var value = source.Trim();
        if (value.Length == 0) throw CommandOptions.Invalid($"Cannot convert value \"{source}\" to type \"System.Int32\". Error: \"Index was outside the bounds of the array.\"");
        const string format = "Input string was not in a correct format.";
        const string overflow = "Value was either too large or too small for an Int32.";
        string failure;
        try
        {
            if (value.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            {
                try { return unchecked((int)uint.Parse(value[2..], NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture)); }
                catch (OverflowException) { throw CommandOptions.Invalid($"Cannot convert value \"{source}\" to type \"System.Int32\". Error: \"Value was either too large or too small for a UInt32.\""); }
            }
            try { return int.Parse(value, NumberStyles.Integer, CultureInfo.InvariantCulture); }
            catch (FormatException)
            {
                try
                {
                    var number = double.Parse(value, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture);
                    if (!double.IsFinite(number)) throw new FormatException();
                    return Convert.ToInt32(number);
                }
                // PS5.1 retains the first integer-format failure if its
                // floating-point fallback fails, including overflow.
                catch (Exception fallbackError) when (fallbackError is FormatException or OverflowException) { throw new FormatException(); }
            }
        }
        catch (FormatException) { failure = format; }
        catch (OverflowException) { failure = overflow; }
        throw CommandOptions.Invalid($"Cannot convert value \"{source}\" to type \"System.Int32\". Error: \"{failure}\"");
    }
    internal static int LegacyInt(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null => 0, JsonValueKind.String => LegacyInt(value.GetString()), JsonValueKind.True => 1, JsonValueKind.False => 0,
        JsonValueKind.Number => NumericInt(value),
        _ => throw CommandOptions.Invalid("Captured workflow counts must be scalar values convertible to Int32.")
    };
    private static int NumericInt(JsonElement value)
    {
        try { return Convert.ToInt32(value.GetDouble()); }
        catch (OverflowException) { throw CommandOptions.Invalid($"Cannot convert value \"{value.GetRawText()}\" to type \"System.Int32\". Error: \"Value was either too large or too small for an Int32.\""); }
    }

    private static void Fields(JsonElement value, params string[] allowed)
    {
        if (value.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Task/form arguments must be an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
            if (!names.Add(property.Name) || !allowed.Contains(property.Name)) throw CommandOptions.Invalid("Unknown or duplicate task/form argument.");
    }
    private static string[] ReadRest(JsonElement args)
    {
        if (!args.TryGetProperty("rest", out var rest) || rest.ValueKind != JsonValueKind.Array || rest.GetArrayLength() > 4096)
            throw CommandOptions.Invalid("rest must contain at most 4096 string-or-null values.");
        var result = new List<string>(); var size = 0;
        foreach (var value in rest.EnumerateArray())
        {
            // The original [string[]] parameter binder normalizes null members
            // to empty before option readers run (Windows oracle, 11 cases).
            if (value.ValueKind == JsonValueKind.Null) { result.Add(""); continue; }
            if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("rest items must be strings or null.");
            var text = value.GetString()!; size += text.Length;
            if (size > 262144) throw CommandOptions.Invalid("rest exceeds 262144 UTF-16 units.");
            result.Add(text);
        }
        return result.ToArray();
    }
    private static int Elapsed(JsonElement args)
    {
        if (!args.TryGetProperty("elapsed_ms", out var elapsed) || elapsed.ValueKind != JsonValueKind.Number || !elapsed.TryGetInt32(out var value) || value < 0)
            throw CommandOptions.Invalid("elapsed_ms must be a nonnegative Int32.");
        return value;
    }
    private static JsonElement RequiredPlan(JsonElement args, string name)
    {
        if (!args.TryGetProperty(name, out var plan) || plan.ValueKind is not (JsonValueKind.Object or JsonValueKind.Null))
            throw CommandOptions.Invalid($"{name} must be the captured object or null.");
        ValidateJson(plan); return plan.Clone();
    }
    private static Capture[] Captures(JsonElement args, Query[] queries)
    {
        if (!args.TryGetProperty("captured_query_results", out var captured) || captured.ValueKind != JsonValueKind.Array || captured.GetArrayLength() != queries.Length)
            throw CommandOptions.Invalid("captured_query_results must match the exact prepared query count.");
        ValidateJson(captured);
        var results = new List<Capture>(); var index = 0;
        foreach (var result in captured.EnumerateArray())
        {
            Fields(result, "kind", "argv", "exit", "raw", "json"); var query = queries[index++];
            if (!result.TryGetProperty("kind", out var kind) || kind.ValueKind != JsonValueKind.String || kind.GetString() != query.kind ||
                !result.TryGetProperty("argv", out var argv) || argv.ValueKind != JsonValueKind.Array || argv.GetArrayLength() != query.argv.Length ||
                argv.EnumerateArray().Any(v => v.ValueKind != JsonValueKind.String) || !argv.EnumerateArray().Select(v => v.GetString()).SequenceEqual(query.argv))
                throw CommandOptions.Invalid("Captured query kind and argv must match preparation in exact order.");
            if (!result.TryGetProperty("exit", out var exit) || exit.ValueKind != JsonValueKind.Number || !exit.TryGetInt32(out var code) ||
                !result.TryGetProperty("raw", out var raw) || raw.ValueKind != JsonValueKind.String)
                throw CommandOptions.Invalid("Captured query requires Int32 exit and string raw.");
            results.Add(new(code, raw.GetString()!, RequiredPlan(result, "json")));
        }
        return results.ToArray();
    }
    private static void ValidateJson(JsonElement value)
    {
        if (value.GetRawText().Length > 1048576) throw CommandOptions.Invalid("Captured data exceeds 1048576 JSON characters.");
        var count = 0;
        void Visit(JsonElement node, int depth)
        {
            if (++count > 65536 || depth > 32) throw CommandOptions.Invalid("Captured data exceeds node or depth bounds.");
            if (node.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(OptionComparer);
                foreach (var property in node.EnumerateObject())
                {
                    if (!names.Add(property.Name)) throw CommandOptions.Invalid("Captured objects contain duplicate properties.");
                    Visit(property.Value, depth + 1);
                }
            }
            else if (node.ValueKind == JsonValueKind.Array) foreach (var item in node.EnumerateArray()) Visit(item, depth + 1);
            else if (node.ValueKind == JsonValueKind.Number && !double.IsFinite(node.GetDouble())) throw CommandOptions.Invalid("Captured numbers must be finite.");
        }
        Visit(value, 0);
    }
}
