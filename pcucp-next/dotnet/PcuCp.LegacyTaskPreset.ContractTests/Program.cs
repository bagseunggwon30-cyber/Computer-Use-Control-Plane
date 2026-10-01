using System.Text.Json;

static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
static JsonElement Prepare(params string[] rest) => Json(LegacyTaskPresetKernel.PreparePreset(Json(new { rest })));
static JsonElement Complete(string[] rest, object captured, int elapsed = 13) => Json(LegacyTaskPresetKernel.CompletePreset(Json(new { rest, captured_query_result = captured, elapsed_ms = elapsed })));
static object Evaluate(JsonElement fixture)
{
    var operation = fixture.GetProperty("operation").GetString();
    var args = fixture.GetProperty("args");
    try
    {
        return operation switch
        {
            "prepare" => LegacyTaskPresetKernel.PreparePreset(args),
            "complete" => LegacyTaskPresetKernel.CompletePreset(args),
            "helpers" => LegacyTaskPresetKernel.CommandHelpers(args),
            "quote" => new { value = LegacyTaskPresetKernel.QuoteToken(args.GetProperty("value").ValueKind == JsonValueKind.Null ? null : args.GetProperty("value").GetString()) },
            _ => throw CommandOptions.Invalid("Unknown fixture operation.")
        };
    }
    catch (NativeFailure error) { return new { threw = true, error = error.Code, message = error.Message }; }
}
if (args.SequenceEqual(new[] { "--fixtures" }))
{
    var input = Console.In.ReadToEnd();
    if (input.Length > 4194304) throw new InvalidOperationException("Fixture request exceeds 4 MiB characters.");
    using var document = JsonDocument.Parse(input);
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(Evaluate).ToArray()));
    return;
}
var checks = 0;
void Check(bool value, string message) { checks++; if (!value) throw new InvalidOperationException(message); }
void Invalid(object value, string operation)
{
    var result = Json(Evaluate(Json(new { operation, args = value })));
    Check(result.GetProperty("threw").GetBoolean() && result.GetProperty("error").GetString() == "invalid_arguments", "Invalid request accepted");
}
foreach (var (kind, extra, mode) in new[]
{
    ("document", new[]{"--text","x"}, "task"), ("mail", new[]{"--send"}, "task"),
    ("form", new[]{"--submit"}, "workflow"), ("form-submit", new[]{"--field","x="}, "workflow"),
    ("upload", new[]{"--path","x"}, "workflow"), ("file-upload", new[]{"--file","x"}, "workflow"),
    ("download", Array.Empty<string>(), "workflow"), ("file-download", Array.Empty<string>(), "workflow"),
    ("settings", Array.Empty<string>(), "workflow"), ("app-settings", Array.Empty<string>(), "workflow")
})
{
    var rest = new[] { "--kind", kind }.Concat(extra).ToArray();
    var preparation = Prepare(rest);
    Check(preparation.GetProperty("kind").GetString() == kind && preparation.GetProperty("mode").GetString() == mode, "Alias or mode lost");
    Check(preparation.GetProperty("queries").GetArrayLength() == 1, "Query order/count");
    var result = mode == "task" ? Complete(rest, new { exit = 9, raw = "ignored", json = new { safe_to_run = true, safety = new { confirmation = true } } })
        : Complete(rest, new { workflow_plan = new { safe_to_run = true, errors = new[] { "retained" } } });
    Check(result.GetProperty("status").GetString() == "ok", "Existing safety truth value lost");
    Check(result.GetProperty("elapsed_ms").GetInt32() == (mode == "task" ? 13 : 0), "Elapsed semantics");
}
var documentRest = new[] { "--kind", "document", "--text", "hello", "--replace", "--save", "--shortcut", "", "--shortcut", "ctrl+x", "--allow-cdp" };
var query = Prepare(documentRest).GetProperty("queries")[0].GetProperty("argv").EnumerateArray().Select(x => x.GetString()).ToArray();
Check(query.SequenceEqual(new[] { "-Quiet", "macro", "task-plan", "--app", "notepad", "--wait-title", "Notepad", "--match", "Notepad", "--type-text", "hello", "--pre-shortcut", "ctrl+a", "--shortcut", "ctrl+s", "--shortcut", "--shortcut", "ctrl+x", "--allow-cdp", "--json-only" }), "Task argv exact order or empty filtering changed");
var mail = Prepare("--kind", "MAIL", "--to", "x", "--allow-cdp");
Check(mail.GetProperty("queries")[0].GetProperty("argv").EnumerateArray().Count(x => x.GetString() == "--allow-cdp") == 2, "Legacy duplicate flags must remain");
var missingJson = Complete(documentRest, new { exit = 2, raw = "failure\n한글", json = (object?)null });
Check(missingJson.GetProperty("status").GetString() == "partial" && missingJson.GetProperty("task_plan_raw").GetString() == "failure\n한글", "Raw error preservation");
var partial = Complete(["--kind", "settings"], new { workflow_plan = new { safe_to_run = false, errors = new[] { new { code = "a" }, new { code = "b" } }, requires_sensitive_confirmation = true } });
Check(partial.GetProperty("workflow_plan").GetProperty("errors").GetArrayLength() == 2, "Do not drop accumulated plan errors");
Check(partial.GetProperty("workflow_plan").GetProperty("requires_sensitive_confirmation").GetBoolean(), "Safety metadata lost");
Check(!missingJson.TryGetProperty("mode", out _), "Task payload must not gain workflow-only fields");
Check(LegacyTaskPresetKernel.QuoteToken("") == "''" && LegacyTaskPresetKernel.QuoteToken(null) == "''", "Null/empty quote");
Check(LegacyTaskPresetKernel.QuoteToken("a'b") == "'a''b'", "Apostrophe quote");
Check(LegacyTaskPresetKernel.QuoteToken("C:\\temp\\x") == "C:\\temp\\x", "Bare token path");
Check(LegacyTaskPresetKernel.QuoteToken("$name; hi") == "'$name; hi'", "Treat syntax as literal");
var helpers = Json(LegacyTaskPresetKernel.CommandHelpers(Json(new { command = new object?[] { "macro", new object?[] { "a b", null, "" }, new object?[] { new[] { "x", "y" } } } })));
Check(helpers.GetProperty("step").GetString() == "macro 'a b' '' 'x y'", "One-level helper flattening");
foreach (var rest in new[] { Array.Empty<string>(), new[] { "--kind", "unknown" }, new[] { "--kind", "document" }, new[] { "--kind", "mail" }, new[] { "--kind", "upload" }, new[] { "--kind", "form" }, new[] { "--kind", "settings", "--field", "missing" }, new[] { "--kind", "settings", "--field", " =x" } }) Invalid(new { rest }, "prepare");
Invalid(new { rest = new[] { "--kind", "settings" }, unexpected = 1 }, "prepare");
Invalid(new { rest = new[] { "--kind", "settings", new string('x', 262145) } }, "prepare");
Invalid(new { rest = new[] { "--kind", "settings" }, captured_query_result = new { workflow_plan = new { } }, elapsed_ms = -1 }, "complete");
Invalid(new { rest = documentRest, captured_query_result = new { exit = 1, raw = "", json = true }, elapsed_ms = 1 }, "complete");
Invalid(new { command = new { executable = "anything" } }, "helpers");
foreach (var raw in new[]
{
    "null", "[]", "{}", "{\"rest\":null}", "{\"rest\":[null]}",
    "{\"rest\":[\"--kind\",\"settings\"],\"rest\":[]}",
})
{
    using var parsed = JsonDocument.Parse(raw);
    Invalid(parsed.RootElement, "prepare");
}
foreach (var elapsed in new object?[] { null, "1", true, -1, 1.5, 2147483648L })
    Invalid(new { rest = new[]{ "--kind", "settings" }, captured_query_result = new { workflow_plan = (object?)null }, elapsed_ms = elapsed }, "complete");
foreach (var captured in new object?[] { null, new { }, new { workflow_plan = true }, new { workflow_plan = Array.Empty<object>() }, new { workflow_plan = new { }, extra = 1 } })
    Invalid(new { rest = new[]{ "--kind", "settings" }, captured_query_result = captured, elapsed_ms = 0 }, "complete");
foreach (var captured in new object?[] { null, new { }, new { exit = "1", raw = "", json = new { } }, new { exit = 0, raw = (object?)null, json = new { } }, new { exit = 0, raw = "", json = new { }, extra = 1 } })
    Invalid(new { rest = documentRest, captured_query_result = captured, elapsed_ms = 0 }, "complete");
Console.WriteLine($"Passed {checks} pure task-preset checks; no child query or desktop action executed.");
