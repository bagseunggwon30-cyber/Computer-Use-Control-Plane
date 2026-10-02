using System.Globalization;
using System.Text.Json;

if (args.SequenceEqual(new[] { "--self-test" }))
{
    int checks = 0;
    void Check(bool condition, string reason) { checks++; if (!condition) throw new InvalidOperationException(reason); }
    JsonElement Run(object value) => JsonSerializer.SerializeToElement(LegacyAppProfileKernel.Advance(JsonSerializer.SerializeToElement(value)));
    object Capture(string kind, string[] argv, object? result) => new { kind, argv, result };
    var window = new { title = "Editor", process = "notepad", @class = "Main", hwnd = 12L, pid = 30, visible = true, foreground = true, minimized = false, rect = new { x = 0, y = 0, width = 640, height = 480 } };
    var empty = Capture("windows", [], Array.Empty<object>());
    Check(Run(new { rest = Array.Empty<string>() }).GetProperty("query").GetProperty("kind").GetString() == "windows", "Enumeration must be first");
    var noTarget = Run(new { rest = new[] { "--record-strategy" }, captured_replies = new[] { empty } });
    Check(noTarget.GetProperty("exit").GetInt32() == 2, "No window must be partial");
    Check(noTarget.GetProperty("queries").GetArrayLength() == 1, "No target must not access history/record");
    var windows = Capture("windows", [], new[] { window });
    var query = Run(new { rest = Array.Empty<string>(), captured_replies = new[] { windows } });
    Check(query.GetProperty("query").GetProperty("kind").GetString() == "history", "Default desktop must query history after enumeration");
    var history = Capture("history", ["notepad|main|document_or_mail_app"], null);
    var result = Run(new { rest = Array.Empty<string>(), captured_replies = new[] { windows, history }, brief = true });
    Check(result.GetProperty("state").GetString() == "complete", "Explicit null history must complete");
    Check(result.GetProperty("queries").GetArrayLength() == 2, "No record flag must never request record");
    Check(result.GetProperty("payload").GetProperty("app_type").GetString() == "document_or_mail_app", "App classification changed");
    Check(result.GetProperty("brief").GetString()!.StartsWith("ok app-profile type=document_or_mail_app"), "Brief changed");
    var disabled = Run(new { rest = new[] { "--record-strategy", "--no-strategy-history" }, captured_replies = new[] { windows } });
    Check(disabled.GetProperty("payload").GetProperty("strategy_persistence").GetProperty("skipped_reason").GetString() == "disabled_by_no_strategy_history", "Disabled history must suppress record");
    var lowScore = Run(new { rest = new[] { "--record-strategy" }, captured_replies = new[] { windows, history } });
    Check(lowScore.GetProperty("state").GetString() == "complete", "Low confidence must suppress record");
    Check(lowScore.GetProperty("payload").GetProperty("strategy_persistence").GetProperty("skipped_reason").GetString() == "confidence_below_medium", "Low confidence skip changed");
    var goodHistory = Capture("history", ["notepad|main|document_or_mail_app"], new { strategy = "uia_set_value" });
    var toRecord = Run(new { rest = new[] { "--remember-strategy" }, captured_replies = new[] { windows, goodHistory } });
    Check(toRecord.GetProperty("query").GetProperty("kind").GetString() == "record", "Explicit remember with sufficient confidence must request record");
    Check(toRecord.GetProperty("query").GetProperty("argv")[3].GetString() == "medium", "Record confidence must derive from score");
    var record = Capture("record", toRecord.GetProperty("query").GetProperty("argv").EnumerateArray().Select(v => v.GetString()!).ToArray(), new { error = "fixture_write_failed" });
    var recordFailed = Run(new { rest = new[] { "--remember-strategy" }, captured_replies = new[] { windows, goodHistory, record } });
    Check(!recordFailed.GetProperty("payload").GetProperty("strategy_persistence").GetProperty("recorded").GetBoolean(), "Error-bearing record must not count as recorded");
    foreach (string envelope in new[] {
        "{\"kind\":3,\"argv\":[],\"result\":[]}",
        "{\"kind\":\"windows\",\"argv\":[\"wrong\"],\"result\":[]}",
        "{\"kind\":\"windows\",\"argv\":[],\"result\":[],\"error\":\"bad\"}",
        "{\"kind\":\"windows\",\"kind\":\"windows\",\"argv\":[],\"result\":[]}",
        "{\"kind\":\"windows\",\"argv\":[],\"result\":[],\"extra\":0}",
        "{\"kind\":\"windows\",\"argv\":[]}",
        "{\"kind\":\"windows\",\"argv\":[],\"error\":null}" })
    {
        using var doc = JsonDocument.Parse("{\"rest\":[],\"captured_replies\":[" + envelope + "]}");
        Check(JsonSerializer.SerializeToElement(LegacyAppProfileKernel.Advance(doc.RootElement)).GetProperty("state").GetString() == "error", "Malformed capture accepted");
    }
    Check(Run(new { rest = Array.Empty<string>(), captured_replies = new[] { empty, empty } }).GetProperty("state").GetString() == "error", "Unused replies accepted");
    var historyFailure = new { kind = "history", argv = new[] { "notepad|main|document_or_mail_app" }, error = "fixture_history" };
    Check(Run(new { rest = Array.Empty<string>(), captured_replies = new object[] { windows, historyFailure } }).GetProperty("state").GetString() == "complete", "History errors must be swallowed");
    var windowFailure = new { kind = "windows", argv = Array.Empty<string>(), error = "fixture_windows" };
    Check(Run(new { rest = Array.Empty<string>(), captured_replies = new object[] { windowFailure } }).GetProperty("error").GetString() == "fixture_windows", "Enumeration errors must propagate");
    Check(Run(new { rest = new[] { "--cdp-port", "bad" } }).GetProperty("queries").GetArrayLength() == 0, "Numeric option errors must precede acquisition");
    var previous = CultureInfo.CurrentCulture;
    try
    {
        CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("en-US");
        var score = JsonSerializer.SerializeToElement(LegacyStrategyKernel.Score(JsonSerializer.SerializeToElement(new { route_order = new[] { "uıa_pattern" }, culture = "tr-TR" })));
        Check(score.GetProperty("route_order").EnumerateArray().Any(v => v.GetString() == "uia_pattern"), "Explicit culture must apply to alias regex");
        Check(CultureInfo.CurrentCulture.Name == "en-US", "Scoring leaked requested culture");
        Check(LegacyStrategyKernel.NormalizeValue("uİa_pattern", CultureInfo.GetCultureInfo("tr-TR")) == "uia_pattern", "Turkish regex alias not preserved");
        Check(CultureInfo.CurrentCulture.Name == "en-US", "Early alias return leaked culture");
    }
    finally { CultureInfo.CurrentCulture = previous; }
    Console.WriteLine($"PASS: {checks} isolated app-profile contracts; no probes or history writes executed.");
    return;
}
var input = Console.In.ReadToEnd();
if (input.Length > 16777216) throw new ArgumentException("Fixture batch exceeds 16MiB.");
using var document = JsonDocument.Parse(input);
if (document.RootElement.ValueKind != JsonValueKind.Array) throw new ArgumentException("Expected fixture batch array.");
Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(LegacyAppProfileKernel.Advance)));
