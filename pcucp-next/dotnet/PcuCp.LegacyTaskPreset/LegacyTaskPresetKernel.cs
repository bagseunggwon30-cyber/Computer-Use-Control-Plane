using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

/// <summary>Pure preset recipes and captured-result assembly. Performs no query or action.</summary>
internal static class LegacyTaskPresetKernel
{
    private static readonly StringComparer Comparer = StringComparer.InvariantCultureIgnoreCase;
    private static readonly string[] TaskValues = ["--name", "--verify-label", "--verify-timeout-ms", "--settle-ms", "--observe-match", "--verify-match", "--verify-label-after-step", "--verify-label-window", "--verify-label-timeout-ms", "--verify-label-interval-ms", "--retry-failed-step", "--retry-delay-ms", "--precision-radius", "--precision-step", "--point-cache-ttl"];
    private static readonly string[] TaskSwitches = ["--allow-cdp", "--no-cdp", "--precision-points", "--include-ocr", "--verify-after-step", "--observe-after-step", "--retry-live-steps", "--clear-first", "--enter", "--press-enter"];
    private static readonly string[] WorkflowValues = ["--settle-ms", "--observe-match", "--verify-match", "--verify-label-after-step", "--verify-label-window", "--verify-label-timeout-ms", "--verify-label-interval-ms", "--retry-failed-step", "--retry-delay-ms"];
    private static readonly string[] WorkflowSwitches = ["--observe-after-step", "--verify-after-step", "--retry-live-steps"];
    private sealed record Recipe(string Kind, string Mode, string[] TaskArgs, string[] Steps, object[] ExtraCommands, string[] Notes, string[] WorkflowRest, string[] WorkflowRun, string[] WorkflowDryRun);

    internal static object PreparePreset(JsonElement args)
    {
        Fields(args, "rest");
        var recipe = Build(ReadRest(args));
        return new
        {
            schema = "cucp.task-preset-preparation/v1", kind = recipe.Kind, mode = recipe.Mode,
            queries = new[] { new { kind = recipe.Mode == "task" ? "task_plan" : "workflow_plan",
                argv = recipe.Mode == "task" ? new[] { "-Quiet" }.Concat(recipe.TaskArgs).Append("--json-only").ToArray() : null,
                rest = recipe.Mode == "workflow" ? recipe.WorkflowRest : null } },
            workflow_steps = recipe.Steps, extra_commands = recipe.ExtraCommands, notes = recipe.Notes
        };
    }

    internal static object CompletePreset(JsonElement args)
    {
        Fields(args, "rest", "captured_query_result", "elapsed_ms");
        var recipe = Build(ReadRest(args));
        if (!args.TryGetProperty("elapsed_ms", out var elapsed) || elapsed.ValueKind != JsonValueKind.Number || !elapsed.TryGetInt32(out var milliseconds) || milliseconds < 0)
            throw CommandOptions.Invalid("elapsed_ms must be a nonnegative Int32.");
        if (!args.TryGetProperty("captured_query_result", out var captured))
            throw CommandOptions.Invalid("captured_query_result is required.");
        // A captured result is data, not a callback or instructions to execute.
        if (captured.GetRawText().Length > 1048576) throw CommandOptions.Invalid("Captured result exceeds 1048576 JSON characters.");
        if (recipe.Mode == "workflow")
        {
            Fields(captured, "workflow_plan");
            if (!captured.TryGetProperty("workflow_plan", out var plan) || plan.ValueKind is not (JsonValueKind.Object or JsonValueKind.Null))
                throw CommandOptions.Invalid("workflow_plan must be the captured object or null.");
            var status = Safe(plan) ? "ok" : "partial";
            return new
            {
                schema = "cucp.task-preset/v1", status, kind = recipe.Kind, mode = "workflow", elapsed_ms = 0,
                generated_task_plan_command = (object?)null, generated_task_run_command = (object?)null,
                generated_workflow_plan_command = new[] { "macro", "workflow-plan" }.Concat(recipe.WorkflowRest).ToArray(),
                generated_workflow_run_command = recipe.WorkflowRun, generated_workflow_dry_run_command = recipe.WorkflowDryRun,
                extra_commands = recipe.ExtraCommands, task_plan_exit = (object?)null, task_plan = (object?)null,
                task_plan_raw = (object?)null, workflow_plan = plan.Clone(), notes = recipe.Notes,
                next_step = status == "ok"
                    ? "Run generated_workflow_dry_run_command first. For live control, use generated_workflow_run_command with -AllowLiveControl; add --confirm-sensitive only after explicit approval when required."
                    : "Inspect workflow_plan errors and narrow labels/window/app before running."
            };
        }
        Fields(captured, "exit", "raw", "json");
        if (!captured.TryGetProperty("exit", out var exit) || exit.ValueKind != JsonValueKind.Number || !exit.TryGetInt32(out var exitCode) ||
            !captured.TryGetProperty("raw", out var raw) || raw.ValueKind != JsonValueKind.String ||
            !captured.TryGetProperty("json", out var taskPlan) || taskPlan.ValueKind is not (JsonValueKind.Object or JsonValueKind.Null))
            throw CommandOptions.Invalid("Task result requires Int32 exit, string raw and object-or-null json.");
        var taskStatus = Safe(taskPlan) ? "ok" : "partial";
        return new
        {
            schema = "cucp.task-preset/v1", status = taskStatus, kind = recipe.Kind, elapsed_ms = milliseconds,
            generated_task_plan_command = recipe.TaskArgs,
            generated_task_run_command = new[] { "macro", "task-run" }.Concat(recipe.TaskArgs.Skip(2)).ToArray(),
            task_plan_exit = exitCode, task_plan = taskPlan.Clone(),
            task_plan_raw = taskPlan.ValueKind == JsonValueKind.Null ? raw.GetString() : null,
            notes = recipe.Notes,
            next_step = taskStatus == "ok"
                ? "Run generated_task_run_command with --dry-run first, then with -AllowLiveControl only after user authorization."
                : "Inspect task_plan errors and narrow labels/window/app before running."
        };
    }

    private static Recipe Build(string[] rest)
    {
        var kind = (Value(rest, "--kind") ?? "");
        if (kind.Length == 0) kind = Value(rest, "--preset") ?? "";
        if (kind.Length == 0) kind = Value(rest, "--type") ?? "";
        kind = kind.ToLowerInvariant();
        if (kind.Length == 0) throw CommandOptions.Invalid("macro task-preset requires --kind document|mail|form-submit|file-upload|file-download|settings");
        var task = new List<string> { "macro", "task-plan" };
        var steps = new List<string>();
        var extras = new List<object>();
        var notes = new List<string>();
        var mode = "task";
        var app = Value(rest, "--app");
        var title = Value(rest, "--wait-title");
        var match = Value(rest, "--match");
        var cdp = !Switch(rest, "--no-cdp");
        void AddTask(params string?[] items) { task.AddRange(items.Where(x => !string.IsNullOrEmpty(x)).Select(x => x!)); }
        void Step(IEnumerable<string> command) { steps.Add(StepString(command)); }
        List<string> Click(string label)
        {
            var command = new List<string> { "macro", "smart-click", "--label", label, "--allow-mouse-fallback" };
            AddValue(command, "--match", match);
            if (cdp) command.Add("--allow-cdp");
            return command;
        }
        switch (kind)
        {
            case "document":
                var text = Fallback(Value(rest, "--text"), Value(rest, "--body"));
                if (string.IsNullOrEmpty(text)) throw CommandOptions.Invalid("macro task-preset --kind document requires --text");
                app = Fallback(app, "notepad"); title = Fallback(title, "Notepad"); match = Fallback(match, title);
                AddTask("--app", app, "--wait-title", title, "--match", match, "--type-text", text);
                if (Switch(rest, "--replace")) AddTask("--pre-shortcut", "ctrl+a");
                if (Switch(rest, "--save")) AddTask("--shortcut", "ctrl+s");
                foreach (var shortcut in Values(rest, "--shortcut")) AddTask("--shortcut", shortcut);
                notes.Add("document preset maps to app launch/wait, optional replace, text input, optional save shortcut");
                break;
            case "mail":
                var to = Value(rest, "--to"); var subject = Value(rest, "--subject"); var body = Value(rest, "--body");
                var send = Value(rest, "--send-label");
                if (string.IsNullOrEmpty(send) && Switch(rest, "--send")) send = "Send";
                if (string.IsNullOrEmpty(to) && string.IsNullOrEmpty(subject) && string.IsNullOrEmpty(body) && string.IsNullOrEmpty(send))
                    throw CommandOptions.Invalid("macro task-preset --kind mail requires --to/--subject/--body and optionally --send-label");
                if (!string.IsNullOrEmpty(app)) AddTask("--app", app);
                if (!string.IsNullOrEmpty(title)) AddTask("--wait-title", title);
                if (!string.IsNullOrEmpty(match)) AddTask("--match", match);
                if (!string.IsNullOrEmpty(to)) AddTask("--field", Fallback(Value(rest, "--to-label"), "To") + "=" + to);
                if (!string.IsNullOrEmpty(subject)) AddTask("--field", Fallback(Value(rest, "--subject-label"), "Subject") + "=" + subject);
                if (!string.IsNullOrEmpty(body)) AddTask("--field", Fallback(Value(rest, "--body-label"), "Body") + "=" + body);
                if (!string.IsNullOrEmpty(send)) AddTask("--send-label", send);
                if (cdp) AddTask("--allow-cdp");
                notes.Add("mail preset maps to form fields and optional send label; --allow-cdp is enabled unless --no-cdp is set");
                break;
            case "form":
            case "form-submit":
                mode = "workflow";
                var fields = Values(rest, "--field");
                send = Fallback(Value(rest, "--send-label"), Value(rest, "--submit-label"));
                if (string.IsNullOrEmpty(send) && Switch(rest, "--submit")) send = "Submit";
                if (fields.Length == 0 && string.IsNullOrEmpty(send)) throw CommandOptions.Invalid("macro task-preset --kind form-submit requires --field and/or --send-label/--submit-label");
                var form = new List<string> { "macro", "form-run" };
                foreach (var field in fields) form.AddRange(["--field", field]);
                AddValue(form, "--send-label", send); AddValue(form, "--match", match);
                if (cdp) form.Add("--allow-cdp");
                AddValue(form, "--cdp-page-match", Value(rest, "--cdp-page-match")); AddValue(form, "--cdp-port", Value(rest, "--cdp-port"));
                foreach (var flag in new[] { "--clear-first", "--include-ocr" }) if (Switch(rest, flag)) form.Add(flag);
                if (Switch(rest, "--precision-points") || Switch(rest, "--point-plan")) form.Add("--precision-points");
                Step(form); extras.Add(new { kind = "form_dry_run", command = form.Append("--dry-run").ToArray() });
                notes.Add("form-submit preset maps to one form-run workflow step; run the generated form dry-run command before live control");
                break;
            case "file-upload":
            case "upload":
                mode = "workflow";
                var path = Fallback(Value(rest, "--path"), Value(rest, "--file"));
                if (string.IsNullOrEmpty(path)) throw CommandOptions.Invalid("macro task-preset --kind file-upload requires --path");
                var uploadLabel = Fallback(Value(rest, "--upload-label"), Fallback(Value(rest, "--label"), "Upload"));
                var dialog = Fallback(Value(rest, "--dialog-title"), "Open");
                var dialogTimeout = Fallback(Value(rest, "--dialog-timeout-ms"), "8000");
                var click = Click(uploadLabel!);
                foreach (var flag in new[] { "--precision-points", "--include-ocr" }) if (Switch(rest, flag)) click.Add(flag);
                Step(click); Step(["macro", "wait-window", "--title", dialog!, "--timeout-ms", dialogTimeout!]);
                Step(["macro", "safe-type", "--target-match", dialog!, "--text", path, "--enter"]);
                notes.Add("file-upload preset maps to upload button click, file dialog wait, guarded path entry, and Enter");
                break;
            case "file-download":
            case "download":
                mode = "workflow";
                var label = Fallback(Value(rest, "--download-label"), Fallback(Value(rest, "--label"), "Download"));
                click = Click(label!);
                foreach (var flag in new[] { "--precision-points", "--include-ocr" }) if (Switch(rest, flag)) click.Add(flag);
                Step(click);
                var verify = Value(rest, "--verify-label");
                if (!string.IsNullOrEmpty(verify))
                {
                    var wait = new List<string> { "macro", "wait-label", "--label", verify, "--timeout-ms", Fallback(Value(rest, "--verify-timeout-ms"), "5000")! };
                    AddValue(wait, "--window", match); Step(wait);
                }
                notes.Add("file-download preset maps to a download button click plus optional verification label wait");
                break;
            case "settings":
            case "app-settings":
                mode = "workflow";
                var settings = Fallback(Value(rest, "--settings-label"), "Settings");
                var save = Fallback(Value(rest, "--save-label"), Value(rest, "--apply-label"));
                if (string.IsNullOrEmpty(save) && Switch(rest, "--save")) save = "Save";
                if (string.IsNullOrEmpty(save) && Switch(rest, "--apply")) save = "Apply";
                Step(Click(settings!));
                foreach (var spec in Values(rest, "--field"))
                {
                    var equals = spec.IndexOf('=');
                    if (equals <= 0) throw CommandOptions.Invalid("macro task-preset --kind settings field must be Label=Value");
                    var fieldLabel = spec[..equals].Trim(); var fieldValue = spec[(equals + 1)..];
                    if (fieldLabel.Length == 0) throw CommandOptions.Invalid("macro task-preset --kind settings field label is empty");
                    Step(Click(fieldLabel));
                    Step(!string.IsNullOrEmpty(match) ? ["macro", "safe-type", "--target-match", match, "--text", fieldValue] : ["macro", "type-native", "--text", fieldValue]);
                }
                foreach (var clickLabel in Values(rest, "--click-label")) Step(Click(clickLabel));
                if (!string.IsNullOrEmpty(save)) Step(Click(save));
                notes.Add("settings preset maps to open settings, optional field edits, optional extra clicks, and optional save/apply");
                break;
            default:
                throw CommandOptions.Invalid("macro task-preset supports --kind document|mail|form-submit|file-upload|file-download|settings");
        }
        if (mode == "task")
        {
            foreach (var name in TaskValues) if (!string.IsNullOrEmpty(Value(rest, name))) AddTask(name, Value(rest, name));
            foreach (var name in TaskSwitches) if (Switch(rest, name)) AddTask(name);
        }
        var workflowRest = new List<string>(); var run = new List<string>(); var dry = new List<string>();
        if (mode == "workflow")
        {
            workflowRest.AddRange(["--name", Fallback(Value(rest, "--name"), kind)!]);
            foreach (var step in steps) workflowRest.AddRange(["--step", step]);
            run.AddRange(["macro", "workflow-run"]); dry.AddRange(["macro", "workflow-run", "--dry-run"]);
            foreach (var name in WorkflowValues) { AddValue(run, name, Value(rest, name)); AddValue(dry, name, Value(rest, name)); }
            foreach (var name in WorkflowSwitches) if (Switch(rest, name)) { run.Add(name); dry.Add(name); }
            foreach (var step in steps) { run.AddRange(["--step", step]); dry.AddRange(["--step", step]); }
        }
        return new(kind, mode, task.ToArray(), steps.ToArray(), extras.ToArray(), notes.ToArray(), workflowRest.ToArray(), run.ToArray(), dry.ToArray());
    }

    internal static string QuoteToken(string? value, CultureInfo? culture = null)
    {
        return LegacyTextKernel.IsBareCommandToken(value, culture ?? CultureInfo.CurrentCulture)
            ? value! : "'" + (value ?? "").Replace("'", "''", StringComparison.Ordinal) + "'";
    }
    internal static string StepString(IEnumerable<string> command, CultureInfo? culture = null) => string.Join(" ", command.Select(value => QuoteToken(value, culture)));

    // JSON-only compatibility probes for the legacy one-level argv helpers. The
    // recipes themselves always construct string argv; objects are not argv.
    internal static object CommandHelpers(JsonElement args)
    {
        Fields(args, "command");
        if (!args.TryGetProperty("command", out var command)) throw CommandOptions.Invalid("command is required.");
        ValidateCommand(command, 0);
        var items = command.ValueKind == JsonValueKind.Null ? [] : command.ValueKind == JsonValueKind.Array ? command.EnumerateArray().ToArray() : new[] { command };
        var unwrapped = items.Length == 1 && items[0].ValueKind == JsonValueKind.Array ? items[0].EnumerateArray().ToArray() : items;
        var tokens = new List<string>();
        foreach (var item in items)
        {
            if (item.ValueKind == JsonValueKind.Null) continue;
            if (item.ValueKind == JsonValueKind.Array)
            {
                foreach (var sub in item.EnumerateArray()) if (sub.ValueKind != JsonValueKind.Null) tokens.Add(PsString(sub));
            }
            else tokens.Add(PsString(item));
        }
        return new { step = StepString(tokens), unwrapped };
    }
    private static void ValidateCommand(JsonElement value, int depth)
    {
        if (depth > 8 || value.GetRawText().Length > 262144) throw CommandOptions.Invalid("command exceeds JSON argv bounds.");
        if (value.ValueKind == JsonValueKind.Array)
        {
            if (value.GetArrayLength() > 4096) throw CommandOptions.Invalid("command exceeds argv item bounds.");
            foreach (var item in value.EnumerateArray()) ValidateCommand(item, depth + 1);
        }
        else if (value.ValueKind is not (JsonValueKind.String or JsonValueKind.Null or JsonValueKind.True or JsonValueKind.False or JsonValueKind.Number))
            throw CommandOptions.Invalid("command supports only JSON scalars and arrays.");
    }
    private static string PsString(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString()!, JsonValueKind.Null => "",
        JsonValueKind.True => "True", JsonValueKind.False => "False",
        JsonValueKind.Array => string.Join(" ", value.EnumerateArray().Select(PsString)),
        JsonValueKind.Number when value.TryGetInt64(out var number) => number.ToString(CultureInfo.InvariantCulture),
        JsonValueKind.Number => value.GetDouble().ToString(CultureInfo.InvariantCulture),
        _ => throw CommandOptions.Invalid("Unsupported argv value.")
    };
    private static bool Safe(JsonElement plan) => plan.ValueKind == JsonValueKind.Object && plan.EnumerateObject().Where(p => Comparer.Equals(p.Name, "safe_to_run")).Select(p => Truth(p.Value)).FirstOrDefault();
    private static bool Truth(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.False => false, JsonValueKind.True or JsonValueKind.Object => true,
        JsonValueKind.String => value.GetString()!.Length != 0, JsonValueKind.Number => value.GetDouble() != 0,
        JsonValueKind.Array => value.GetArrayLength() > 1 || (value.GetArrayLength() == 1 && Truth(value[0])), _ => false
    };
    private static void Fields(JsonElement args, params string[] allowed)
    {
        if (args.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Preset arguments must be an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in args.EnumerateObject())
            if (!names.Add(property.Name) || !allowed.Contains(property.Name)) throw CommandOptions.Invalid("Unknown or duplicate preset argument.");
    }
    private static string[] ReadRest(JsonElement args)
    {
        if (!args.TryGetProperty("rest", out var raw) || raw.ValueKind != JsonValueKind.Array || raw.GetArrayLength() > 4096)
            throw CommandOptions.Invalid("rest must contain at most 4096 strings.");
        var result = new List<string>(); var length = 0;
        foreach (var value in raw.EnumerateArray())
        {
            if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("rest items must be strings.");
            var text = value.GetString()!; length += text.Length;
            if (length > 262144) throw CommandOptions.Invalid("rest exceeds 262144 UTF-16 units.");
            result.Add(text);
        }
        return result.ToArray();
    }
    private static string? Value(string[] rest, string name)
    {
        for (var i = 0; i + 1 < rest.Length; i++) if (Comparer.Equals(rest[i], name)) return rest[i + 1];
        return null;
    }
    private static string[] Values(string[] rest, string name)
    {
        var values = new List<string>();
        for (var i = 0; i + 1 < rest.Length; i++) if (Comparer.Equals(rest[i], name)) values.Add(rest[++i]);
        return values.ToArray();
    }
    private static bool Switch(string[] rest, string name) => rest.Contains(name, Comparer);
    private static string? Fallback(string? first, string? second) => string.IsNullOrEmpty(first) ? second : first;
    private static void AddValue(List<string> command, string name, string? value) { if (!string.IsNullOrEmpty(value)) command.AddRange([name, value]); }
}
