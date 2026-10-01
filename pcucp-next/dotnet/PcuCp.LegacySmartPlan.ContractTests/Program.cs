using System.Text.Json;
if (args.SequenceEqual(new[] { "--self-test" }))
{
    int checks = 0;
    void Check(bool condition, string reason) { checks++; if (!condition) throw new InvalidOperationException(reason); }
    JsonElement Run(object value) => JsonSerializer.SerializeToElement(LegacySmartPlanKernel.Advance(JsonSerializer.SerializeToElement(value)));
    var rest = new[] { "--label", "Save" };
    var initial = Run(new { rest });
    Check(initial.GetProperty("state").GetString() == "query", "Missing history must request capture");
    Check(initial.GetProperty("query").GetProperty("kind").GetString() == "history", "History must be first");
    var history = new { kind = "history", argv = new[] { "Save", "", "5" }, result = (object?)null };
    var pending = Run(new { rest, captured_replies = new object[] { history } });
    Check(pending.GetProperty("query").GetProperty("argv")[1].GetString() == "uia-find", "Explicit null history must advance");
    var uia = new { kind = "native", argv = new[] { "-Action", "uia-find", "-Label", "Save" }, result = (object?)null };
    var complete = Run(new { rest, captured_replies = new object[] { history, uia }, brief = true });
    Check(complete.GetProperty("state").GetString() == "complete", "Explicit null helper must complete partial plan");
    Check(complete.GetProperty("exit").GetInt32() == 2, "No candidate must exit partial");
    Check(!complete.GetProperty("payload").GetProperty("safe_to_act").GetBoolean(), "No candidate must not authorize action");
    Check(complete.GetProperty("brief").GetString()!.Contains("no_safe_route"), "Brief output changed");
    foreach (object[] replies in new[] {
        new object[] { new { kind = "history", argv = new[] { "WRONG", "", "5" }, result = (object?)null } },
        new object[] { new { kind = "native", argv = new[] { "Save", "", "5" }, result = (object?)null } },
        new object[] { new { kind = "history", argv = new[] { "Save", "", "5" } } },
        new object[] { history, uia, history } })
        Check(Run(new { rest, captured_replies = replies }).GetProperty("state").GetString() == "error", "Malformed or extra capture accepted");
    foreach (var envelope in new[] {
        "{\"kind\":123,\"argv\":[\"Save\",\"\",\"5\"],\"result\":null}",
        "{\"kind\":[\"history\"],\"argv\":[\"Save\",\"\",\"5\"],\"result\":null}",
        "{\"kind\":\"history\",\"argv\":[\"Save\",\"\",\"5\"],\"result\":null,\"extra\":true}",
        "{\"kind\":\"history\",\"kind\":\"history\",\"argv\":[\"Save\",\"\",\"5\"],\"result\":null}",
        "{\"kind\":\"history\",\"argv\":[\"Save\",\"\",\"5\"],\"result\":null,\"result\":null}",
        "{\"kind\":\"history\",\"argv\":[\"Save\",\"\",\"5\"],\"result\":null,\"error\":\"ignored\"}" })
    {
        using var invalid = JsonDocument.Parse("{\"rest\":[\"--label\",\"Save\"],\"captured_replies\":[" + envelope + "]}");
        Check(JsonSerializer.SerializeToElement(LegacySmartPlanKernel.Advance(invalid.RootElement)).GetProperty("state").GetString() == "error", "Noncanonical capture envelope accepted");
    }
    var failedHistory = new { kind = "history", argv = new[] { "Save", "", "5" }, error = "fixture_history" };
    Check(Run(new { rest, captured_replies = new object[] { failedHistory, uia } }).GetProperty("exit").GetInt32() == 2, "History exception must remain swallowed");
    var failedUia = new { kind = "native", argv = new[] { "-Action", "uia-find", "-Label", "Save" }, error = "fixture_uia" };
    Check(Run(new { rest, captured_replies = new object[] { history, failedUia } }).GetProperty("error").GetString() == "fixture_uia", "Native exception must propagate");
    var historyArray = new { kind = "history", argv = new[] { "Save", "", "5" }, result = new[] { "first", "second" } };
    var arrayPlan = Run(new { rest, captured_replies = new object[] { historyArray, uia } });
    Check(arrayPlan.GetProperty("payload").GetProperty("history_hint").GetProperty("Count").GetInt32() == 2, "History array ETS shape changed");
    var overflowUia = new { kind = "native", argv = new[] { "-Action", "uia-find", "-Label", "Save" }, result = new { Json = new { status = "ok", top = new { score = 2147483648L, invoke_pattern = "Invoke" } } } };
    var overflow = Run(new { rest, captured_replies = new object[] { history, overflowUia } });
    Check(overflow.GetProperty("error").GetString() == "Cannot convert value \"2147483648\" to type \"System.Int32\". Error: \"Value was either too large or too small for an Int32.\"", "Numeric conversion must preserve PS wrapper");
    Console.WriteLine($"PASS: {checks} isolated SmartPlan captured-reply contracts; no probes executed.");
    return;
}
var input = Console.In.ReadToEnd();
if (input.Length > 16777216) throw new ArgumentException("Fixture batch exceeds 16MiB.");
using var document = JsonDocument.Parse(input);
object Evaluate(JsonElement args)
{
    try { return LegacySmartPlanKernel.Advance(args); }
    catch (Exception ex) { return new { state = "error", error = ex.Message, queries = Array.Empty<object>() }; }
}
Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(Evaluate)));
