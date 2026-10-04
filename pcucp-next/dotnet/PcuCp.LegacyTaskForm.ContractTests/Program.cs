using System.Text.Json;

static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
static object Evaluate(JsonElement fixture)
{
    try
    {
        var args = fixture.GetProperty("args");
        return fixture.GetProperty("operation").GetString() switch
        {
            "prepare-task" => LegacyTaskFormKernel.PrepareTask(args),
            "prepare-form" => LegacyTaskFormKernel.PrepareForm(args),
            "assemble-task" => LegacyTaskFormKernel.AssembleTask(args),
            "complete-task" => LegacyTaskFormKernel.CompleteTask(args),
            "complete-form" => LegacyTaskFormKernel.CompleteForm(args),
            _ => throw CommandOptions.Invalid("Unknown fixture operation.")
        };
    }
    catch (NativeFailure error) { return new { threw = true, error = error.Code, message = error.Message }; }
}
if (args.SequenceEqual(new[] { "--fixtures" }))
{
    var input = Console.In.ReadToEnd();
    if (input.Length > 16777216) throw new InvalidOperationException("Fixture batch exceeds 16 MiB characters.");
    using var document = JsonDocument.Parse(input, new JsonDocumentOptions { MaxDepth = 64 });
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(Evaluate).ToArray()));
    return;
}

var checks = 0;
void Check(bool value, string message) { checks++; if (!value) throw new InvalidOperationException(message); }
JsonElement Prepare(string kind, string[] rest) => Json(Evaluate(Json(new { operation = "prepare-" + kind, args = new { rest } })));
object[] Captures(string kind, string[] rest, params object?[] plans) => Prepare(kind, rest).GetProperty("queries").EnumerateArray().Select((q, i) => (object)new { kind = q.GetProperty("kind"), argv = q.GetProperty("argv"), exit = 7, raw = "raw 한글", json = plans.Length == 0 ? new { safe_to_act = true, recommended_command = new[] { "macro", "windows" } } : plans[Math.Min(i, plans.Length - 1)] }).ToArray();
JsonElement Complete(string kind, string[] rest, object[] captured, object? workflow = null) => Json(Evaluate(Json(new { operation = "complete-" + kind, args = kind == "task" ? (object)new { rest, captured_query_results = captured, captured_workflow_plan = workflow, elapsed_ms = 37 } : new { rest, captured_query_results = captured, elapsed_ms = 37 } })));
void Invalid(string operation, object? args)
{
    var result = Json(Evaluate(Json(new { operation, args })));
    Check(result.TryGetProperty("threw", out var threw) && threw.GetBoolean() && result.GetProperty("error").GetString() == "invalid_arguments", "Invalid transport accepted: " + operation);
}

var formRest = new[] { "--field", "bad", "--field", " =x", "--field", " Name =😀=a", "--field", "Age=", "--send-label", "Send", "--match", "window", "--include-ocr", "--clear-first", "--point-plan", "--precision-radius", "4", "--precision-step", "2", "--cache-ttl", "3" };
var formPrepared = Prepare("form", formRest).GetProperty("queries");
Check(formPrepared.GetArrayLength() == 3, "Malformed fields must not prevent remaining queries");
var fieldArgs = formPrepared[0].GetProperty("argv").EnumerateArray().Select(v => v.GetString()).ToArray();
var sendArgs = formPrepared[2].GetProperty("argv").EnumerateArray().Select(v => v.GetString()).ToArray();
Check(fieldArgs.Contains("--clear-first") && !fieldArgs.Contains("--include-ocr") && !fieldArgs.Contains("--precision-points"), "Field planning must forward only original flags");
Check(!sendArgs.Contains("--clear-first") && sendArgs.Contains("--include-ocr") && sendArgs.Contains("--precision-points"), "Send planning flags");
var form = Complete("form", formRest, Captures("form", formRest));
Check(form.GetProperty("steps")[0].GetProperty("index").GetInt32() == 3 && form.GetProperty("steps")[2].GetProperty("index").GetInt32() == 5, "Malformed fields consume index");
Check(form.GetProperty("steps")[0].GetProperty("value_length").GetInt32() == 4, "UTF-16 length lost");
Check(form.GetProperty("errors").GetArrayLength() == 2 && !form.GetProperty("safe_to_act").GetBoolean(), "Malformed fields force partial");
Check(form.GetProperty("command_plan").GetArrayLength() == 3 && form.GetProperty("safe_step_count").GetInt32() == 3, "Preserve commands despite errors");
foreach (var plan in new object?[] { null, new { }, new { safe_to_act = false }, new { safe_to_act = "" }, new { safe_to_act = 0 }, new { safe_to_act = Array.Empty<object>() } })
{
    var rest = new[] { "--send-label", "Send" }; var payload = Complete("form", rest, Captures("form", rest, plan));
    Check(!payload.GetProperty("safe_to_act").GetBoolean() && payload.GetProperty("unsafe_steps").GetArrayLength() == 1, "Unsafe capture must remain in plan");
    Check(payload.GetProperty("command_plan").GetArrayLength() == 1, "Unsafe command omitted");
}
foreach (var truth in new object[] { true, "false", 1, new[] { false, false }, new { } })
{
    var rest = new[] { "--send-label", "Send" }; var payload = Complete("form", rest, Captures("form", rest, new { safe_to_act = truth }));
    Check(payload.GetProperty("safe_to_act").GetBoolean(), "Original truth conversion or nonzero exit semantics changed");
}
var taskRest = new[] { "--open-app", "app", "--verify-window", "title", "--pre-shortcut", "ctrl+a", "--type-text", "", "--text", "ignored", "--type-text", "second", "--clear-first", "--field", "Name=value", "--click-label", "one", "--click-label", "two", "--keys", "F4", "--shortcut", "F3", "--verify-label", "done", "--verify-after-step", "--verify-match", "fallback", "--verify-after-label", "after", "--settle-ms", "" };
var taskQueries = Prepare("task", taskRest).GetProperty("queries");
Check(taskQueries.GetArrayLength() == 3 && taskQueries[0].GetProperty("kind").GetString() == "form_plan", "Form must query before all clicks");
var taskCaptures = Captures("task", taskRest, null, new { safe_to_act = true, recommended_command = Array.Empty<object>() }, new { safe_to_act = false });
var assembled = Json(LegacyTaskFormKernel.AssembleTask(Json(new { rest = taskRest, captured_query_results = taskCaptures })));
Check(assembled.GetProperty("errors").GetArrayLength() == 2 && assembled.GetProperty("items").EnumerateArray().Count(v => v.GetProperty("kind").GetString() == "click") == 1, "Continue clicks after unparseable form");
Check(assembled.GetProperty("workflow_rest").EnumerateArray().Any(v => v.GetString() == ""), "Safe empty click must retain empty step");
var items = assembled.GetProperty("items").EnumerateArray().ToArray();
Check(items[2].GetProperty("command").EnumerateArray().Any(v => v.GetString() == "--clear") && !items[3].GetProperty("command").EnumerateArray().Any(v => v.GetString() == "--clear"), "Only first unguarded text clears");
Check(items[5].GetProperty("keys").GetString() == "F3" && items[6].GetProperty("keys").GetString() == "F4", "Shortcut values precede keys values");
var task = Complete("task", taskRest, taskCaptures, new { safe_to_run = true, live_step_count = 1, sensitive_step_count = 2, requires_sensitive_confirmation = true, step_count = 8 });
Check(!task.GetProperty("safe_to_run").GetBoolean() && task.GetProperty("requires_sensitive_confirmation").GetBoolean(), "Preserve workflow safety while errors prevent success");
Check(task.GetProperty("run_options").GetProperty("settle_ms").GetString() == "" && task.GetProperty("run_options").GetProperty("retry_delay_ms").ValueKind == JsonValueKind.Null, "Null/empty options collapsed");
Check(task.GetProperty("run_options").GetProperty("observe_after_step").GetBoolean() && task.GetProperty("run_options").GetProperty("observe_match").GetString() == "fallback", "Verification aliases");
foreach (var (text, expected) in new[] { ("1.5", "2"), ("2.5", "2"), ("1e2", "100"), ("1,000", "1000"), ("0x10", "16"), ("-1", "8000"), ("", "8000") })
{
    var rest = new[] { "--wait-title", "title", "--wait-timeout-ms", text };
    var value = Json(LegacyTaskFormKernel.AssembleTask(Json(new { rest, captured_query_results = Array.Empty<object>() })));
    Check(value.GetProperty("items")[0].GetProperty("command")[5].GetString() == expected, "Timeout conversion: " + text);
}
var emptyFormRest = new[] { "--field", "x=y" };
var nestedPlan = new { safe_to_act = true, command_plan = new object[] { new { command = Array.Empty<object>() }, new { command = new object[] { new object[] { "macro", new object?[] { "a", null, "b" } } }, label = "nested", route = "uia" } } };
var nested = Json(LegacyTaskFormKernel.AssembleTask(Json(new { rest = emptyFormRest, captured_query_results = Captures("task", emptyFormRest, nestedPlan) })));
Check(nested.GetProperty("items").GetArrayLength() == 1 && nested.GetProperty("items")[0].GetProperty("step").GetString() == "macro a b", "Unwrap then one-level flattening");
foreach (var rest in new[] { Array.Empty<string>(), new[] { "--app" }, new[] { "--wait-timeout-ms", "bad" }, new[] { "--verify-timeout-ms", "2147483648" } }) Invalid("prepare-task", new { rest });
foreach (var rest in new[] { Array.Empty<string>(), new[] { "--send-label", "" } }) Invalid("prepare-form", new { rest });
foreach (var kind in new[] { "task", "form" })
{
    var rest = new[] { "--send-label", "Send" }; var captures = Captures(kind, rest);
    Invalid("prepare-" + kind, new { rest, unknown = true });
    Invalid("prepare-" + kind, new { rest = new object?[] { true } });
    Invalid("prepare-" + kind, new { rest = Enumerable.Repeat("x", 4097).ToArray() });
    Invalid("prepare-" + kind, new { rest = new[] { new string('x', 262145) } });
    foreach (var capture in new object?[] { null, new object[0], new[] { new { kind = "wrong", argv = new[] { "bad" }, exit = 0, raw = "", json = new { } } } })
        Invalid(kind == "task" ? "assemble-task" : "complete-form", kind == "task" ? new { rest, captured_query_results = capture } : new { rest, captured_query_results = capture, elapsed_ms = 0 });
    foreach (var elapsed in new object?[] { null, "1", true, -1, 1.5, 2147483648L })
        Invalid("complete-" + kind, kind == "task" ? new { rest, captured_query_results = captures, captured_workflow_plan = (object?)null, elapsed_ms = elapsed } : new { rest, captured_query_results = captures, elapsed_ms = elapsed });
}
using (var duplicate = JsonDocument.Parse("{\"rest\":[],\"rest\":[]}")) Invalid("prepare-form", duplicate.RootElement);
var captureRest = new[] { "--send-label", "Send" };
var descriptor = Prepare("form", captureRest).GetProperty("queries")[0];
foreach (var captured in new object[]
{
    new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = "0", raw = "", json = new { } },
    new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = (object?)null, json = new { } },
    new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = "", json = true },
    new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = "", json = new object[0] },
    new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = "", json = new { }, unexpected = true },
    new { kind = "smart_plan", argv = new[] { "-Quiet", "macro", "smart-plan", "--label", "Other", "--json-only" }, exit = 0, raw = "", json = new { } },
    new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = new string('x', 1048577), json = new { } },
}) Invalid("complete-form", new { rest = captureRest, captured_query_results = new[] { captured }, elapsed_ms = 0 });
using (var duplicatePlan = JsonDocument.Parse("{\"safe_to_act\":true,\"SAFE_TO_ACT\":false}"))
    Invalid("complete-form", new { rest = captureRest, captured_query_results = new[] { new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = "", json = duplicatePlan.RootElement } }, elapsed_ms = 0 });
object deepPlan = new { value = "end" };
for (var i = 0; i < 34; i++) deepPlan = new { child = deepPlan };
Invalid("complete-form", new { rest = captureRest, captured_query_results = new[] { new { kind = "smart_plan", argv = descriptor.GetProperty("argv"), exit = 0, raw = "", json = deepPlan } }, elapsed_ms = 0 });
var orderedRest = new[] { "--click-label", "one", "--click-label", "two" };
Invalid("assemble-task", new { rest = orderedRest, captured_query_results = Captures("task", orderedRest).Reverse().ToArray() });
var noSteps = new[] { "--shortcut", " " };
Invalid("complete-task", new { rest = noSteps, captured_query_results = Array.Empty<object>(), captured_workflow_plan = new { safe_to_run = true }, elapsed_ms = 0 });
var nullTask = Complete("task", noSteps, [], null);
Check(nullTask.GetProperty("recommended_command").ValueKind == JsonValueKind.Null && nullTask.GetProperty("step_count").GetInt32() == 0, "No generated steps retains null commands");
var nullTextRest = new[] { "--type-text", null!, "--text", "ignored" };
var nullText = Json(LegacyTaskFormKernel.AssembleTask(Json(new { rest = nullTextRest, captured_query_results = Array.Empty<object>() })));
Check(nullText.GetProperty("items").GetArrayLength() == 1 && nullText.GetProperty("items")[0].GetProperty("command")[3].GetString() == "", "PS string-array binder normalizes null type-text to empty and suppresses text fallback");
var nullFieldRest = new[] { "--field", null! };
var nullField = Complete("form", nullFieldRest, []);
Check(nullField.GetProperty("field_count").GetInt32() == 1 && nullField.GetProperty("errors")[0].GetProperty("field").GetString() == "", "Null field interpolates to empty malformed field");
Check(Prepare("task", nullFieldRest).GetProperty("queries")[0].GetProperty("argv")[4].GetString() == "", "Null field normalizes before descriptor construction");
var emptyObserveRest = new[] { "--type-text", "x", "--observe-match", "" };
Check(Complete("task", emptyObserveRest, [], null).GetProperty("run_options").GetProperty("observe_match").GetString() == "", "Empty observe-match survives absent verify-match");
foreach (var (source, reason) in new[] { (" ", "Index was outside the bounds of the array."), ("2147483647.5", "Input string was not in a correct format."), ("1e400", "Input string was not in a correct format."), ("2147483648", "Value was either too large or too small for an Int32.") })
{
    var failed = Prepare("task", ["--wait-timeout-ms", source]);
    Check(failed.GetProperty("message").GetString() == $"Cannot convert value \"{source}\" to type \"System.Int32\". Error: \"{reason}\"", "Exact observed PS5.1 numeric exception");
}
foreach (var (command, expected) in new (object?, object?)[] { (Array.Empty<object>(), new { }), (new object?[] { null }, null), (new[] { "" }, ""), (new object[] { new[] { "macro", "windows" } }, new[] { "macro", "windows" }) })
{
    var value = Complete("form", captureRest, Captures("form", captureRest, new { safe_to_act = true, best_route = command, recommended_command = command }));
    Check(value.GetProperty("command_plan")[0].GetProperty("command").GetRawText() == Json(expected).GetRawText(), "Form conditional command output");
    Check(value.GetProperty("steps")[0].GetProperty("best_route").GetRawText() == Json(expected).GetRawText(), "Form conditional route output");
    Check(value.GetProperty("steps")[0].GetProperty("plan").GetProperty("recommended_command").GetRawText() == Json(command).GetRawText(), "Embedded source command remains unchanged");
}
Console.WriteLine($"Passed {checks} pure task/form contract checks; no child query or desktop action executed.");
