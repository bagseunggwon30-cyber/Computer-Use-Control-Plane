using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

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
    Check(LegacyTaskPresetKernel.QuoteToken("I", CultureInfo.GetCultureInfo("tr-TR")) == "'I'", "Framework Turkish ASCII range must quote I");
    Check(LegacyTaskPresetKernel.QuoteToken("ı", CultureInfo.GetCultureInfo("tr-TR")) == "'ı'", "Framework Turkish ASCII range must quote dotless i");
    Check(LegacyTaskPresetKernel.QuoteToken("literal\n", CultureInfo.GetCultureInfo("en-US")) == "literal\n", "Original terminal-LF anchor behavior changed");
    Check(LegacyTaskPresetKernel.QuoteToken("\n", CultureInfo.GetCultureInfo("en-US")) == "'\n'", "Bare token still requires at least one allowed character");
    Check(LegacyTaskPresetKernel.QuoteToken("x\r\n", CultureInfo.GetCultureInfo("en-US")) == "'x\r\n'", "CRLF must not be accepted by terminal-LF rule");
    int controllerChecks = RunControllerChecks();
    Console.WriteLine($"PASS: {checks} isolated app-profile contracts and {controllerChecks} pure controller guards; no probes or history writes executed.");
    return;
}
var input = Console.In.ReadToEnd();
if (input.Length > 16777216) throw new ArgumentException("Fixture batch exceeds 16MiB.");
using var document = JsonDocument.Parse(input);
if (document.RootElement.ValueKind != JsonValueKind.Array) throw new ArgumentException("Expected fixture batch array.");
if (args.SequenceEqual(new[] { "--controller-fixtures" }))
{
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(LegacyAppProfileController.Advance)));
    return;
}
if (args.SequenceEqual(new[] { "--quote-fixtures" }))
{
    CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("en-US");
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(fixture =>
    {
        string? value = fixture.GetProperty("value").GetString();
        var culture = CultureInfo.GetCultureInfo(fixture.GetProperty("culture").GetString()!);
        return new { value = LegacyTaskPresetKernel.QuoteToken(value, culture), step = LegacyTaskPresetKernel.StepString(new[] { "macro", value ?? "" }, culture) };
    })));
    if (CultureInfo.CurrentCulture.Name != "en-US") throw new InvalidOperationException("Quote fixture leaked culture.");
    return;
}
if (args.SequenceEqual(new[] { "--casing-fixtures" }))
{
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(fixture =>
    {
        string value = fixture.GetProperty("value").GetString()!;
        var culture = CultureInfo.GetCultureInfo(fixture.GetProperty("culture").GetString()!);
        return new
        {
            invariant = LegacyStrategyKernel.LowerValue(value, CultureInfo.InvariantCulture),
            current = LegacyStrategyKernel.LowerValue(value, culture),
            characters = string.Concat(value.Select(c => LegacyStrategyKernel.LowerValue(c.ToString(), culture)))
        };
    })));
    return;
}
Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(LegacyAppProfileKernel.Advance)));

static int RunControllerChecks()
{
    int checks = 0;
    void Check(bool condition, string reason) { checks++; if (!condition) throw new InvalidOperationException(reason); }
    JsonObject Obj(object value) => JsonSerializer.SerializeToNode(value)!.AsObject();
    JsonObject Run(JsonObject value) => JsonSerializer.SerializeToNode(LegacyAppProfileController.Advance(JsonSerializer.SerializeToElement(value)))!.AsObject();
    JsonObject Copy(JsonObject value) => value.DeepClone().AsObject();
    string State(JsonObject value) => value["state"]!.GetValue<string>();
    void Rejected(JsonObject value, string reason) => Check(State(Run(value)) == "error", reason);
    var window = new { title = "Fixture 한글", process = "chrome", @class = "Main", hwnd = 12L, pid = 30, visible = true, foreground = true, minimized = false, rect = new { x = 0, y = 0, width = 640, height = 480 } };
    JsonObject Capture(string kind, string[] argv, object? result) => Obj(new { kind, argv, result });
    var captures = new[]
    {
        Capture("windows", [], new[] { window }),
        Capture("windows", ["-Match", "Fixture 한글"], new[] { window }),
        Capture("cdp_port", ["9222", "120"], true),
        Capture("native", ["-Action", "cdp-detect", "-CdpPort", "9222"], new { Json = new { status = "ok", browser = "Fixture", page_count = 2 } }),
        Capture("uia", ["-FocusedWindow", "Fixture 한글", "-MaxElements", "120", "-MinSize", "6", "-Hwnd", "12"], new[] { new { text = "Save", role = "Button", small_icon = true } }),
        Capture("history", ["chrome|main|browser_or_electron"], new { strategy = "cdp_dom" })
    };
    var request = Obj(new { rest = new[] { "--match", "Fixture 한글", "--probe", "--label", "Save", "--record-strategy" },
        brief = false, culture = "en-US", history_file = "Z:\\fixture-only\\strategy.jsonl", elapsed_ms = 0, cdp_elapsed_ms = 0, uia_elapsed_ms = 0, captured_replies = Array.Empty<object>() });
    int evaluations = 0;
    for (int i = 0; i < captures.Length; i++)
    {
        var query = Run(request);
        Check(State(query) == "query" && query["query"]!["kind"]!.GetValue<string>() == captures[i]["kind"]!.GetValue<string>(), "Controller changed the next acquisition");
        Check(query["record_authorization"] is null && query["kernel_evaluations"]!.GetValue<int>() == 1, "Early acquisition gained record authority");
        evaluations += query["kernel_evaluations"]!.GetValue<int>();
        request["captured_replies"]!.AsArray().Add(captures[i].DeepClone());
    }
    var pending = Run(request);
    Check(State(pending) == "query" && pending["query"]!["kind"]!.GetValue<string>() == "record", "Expected pending record");
    Check(pending["kernel_evaluations"]!.GetValue<int>() == 2, "Record preflight must use exactly one additional pure evaluation");
    var receipt = pending["record_authorization"]!.AsObject();
    Check(receipt["strategy_score"]!["total_score"]!.GetValue<int>() == 84 && receipt["strategy_score"]!["confidence"]!.GetValue<string>() == "high", "Record permission must derive from complete score");
    Check(receipt["context_sha256"]!.GetValue<string>().Length == 64, "Missing bounded invocation binding");
    evaluations += pending["kernel_evaluations"]!.GetValue<int>();
    var preparedCompletion = pending["record_completion"]!.AsObject();
    Check(State(preparedCompletion) == "complete" && preparedCompletion["queries"]!.AsArray().Count == 7, "Record must have a complete validated output before Append");
    Check(!preparedCompletion["payload"]!["strategy_persistence"]!["recorded"]!.GetValue<bool>() && preparedCompletion["payload"]!["strategy_persistence"]!["record"] is null, "Prevalidated completion must retain the explicit null record placeholder");
    Check(evaluations == 8, "Production must finish its seven facade calls/eight evaluations before Append");
    var actualRecord = Capture("record", pending["query"]!["argv"]!.AsArray().Select(v => v!.GetValue<string>()).ToArray(), new { error = "fixture_write_failed" });
    var completeRequest = Copy(request);
    completeRequest["captured_replies"]!.AsArray().Add(actualRecord.DeepClone());
    completeRequest["record_authorization"] = receipt.DeepClone();
    var complete = Run(completeRequest);
    Check(State(complete) == "complete", "Authorized record completion failed: " + complete["error"]);
    Check(!complete["payload"]!["strategy_persistence"]!["recorded"]!.GetValue<bool>(), "Failed actual record must remain failed");
    Check(complete["record_authorization"] is null, "Completion must not issue another record authorization");
    evaluations += complete["kernel_evaluations"]!.GetValue<int>();
    Check(evaluations == 9 && complete["queries"]!.AsArray().Count == 7, "Maximum path must remain eight facade calls/nine evaluations/seven acquisitions");
    var missing = Copy(completeRequest); missing.Remove("record_authorization"); Rejected(missing, "Missing preflight authorization accepted");
    var unsolicited = Copy(request); unsolicited["record_authorization"] = receipt.DeepClone(); Rejected(unsolicited, "Unsolicited preflight authorization accepted");
    var extra = Copy(completeRequest); extra["record_authorization"]!["extra"] = true; Rejected(extra, "Extra authorization field accepted");
    var absent = Copy(completeRequest); absent["record_authorization"]!.AsObject().Remove("schema"); Rejected(absent, "Missing authorization field accepted");
    var oversized = Copy(completeRequest); oversized["record_authorization"]!["context_sha256"] = new string('0', 1048577); Rejected(oversized, "Oversized authorization accepted");
    string duplicate = completeRequest.ToJsonString().Replace("\"record_authorization\":{", "\"record_authorization\":{\"schema\":\"duplicate\",");
    using (var duplicated = JsonDocument.Parse(duplicate))
        Check(JsonSerializer.SerializeToElement(LegacyAppProfileController.Advance(duplicated.RootElement)).GetProperty("state").GetString() == "error", "Duplicate receipt field accepted");
    string receiptWire = completeRequest["record_authorization"]!.ToJsonString();
    foreach (var replacement in new[] { ("\"pid\":30", "\"hwnd\":12"), ("\"y\":0", "\"x\":0"), ("\"confidence\":\"high\"", "\"recommended_strategy\":\"cdp_dom\"") })
    {
        string malformed = completeRequest.ToJsonString().Replace(receiptWire, receiptWire.Replace(replacement.Item1, replacement.Item2));
        using var nestedDuplicate = JsonDocument.Parse(malformed);
        Check(JsonSerializer.SerializeToElement(LegacyAppProfileController.Advance(nestedDuplicate.RootElement)).GetProperty("state").GetString() == "error", "Duplicate nested receipt field accepted");
    }
    foreach (string field in new[] { "app_type", "app_key", "history_file", "context_sha256" })
    {
        var modified = Copy(completeRequest); modified["record_authorization"]![field] = "altered";
        Rejected(modified, "Changed authorization binding accepted: " + field);
    }
    foreach (string field in new[] { "hwnd", "pid" })
    {
        var modified = Copy(completeRequest); modified["record_authorization"]!["selected_window"]![field] = 99;
        Rejected(modified, "Changed target handle/id accepted");
    }
    var geometry = Copy(completeRequest); geometry["record_authorization"]!["selected_window"]!["rect"]!["x"] = 99; Rejected(geometry, "Changed geometry accepted");
    var scoreChanged = Copy(completeRequest); scoreChanged["record_authorization"]!["strategy_score"]!["total_score"] = 85; Rejected(scoreChanged, "Changed preflight score accepted");
    var fullScoreChanged = Copy(completeRequest); fullScoreChanged["record_authorization"]!["strategy_score_sha256"] = new string('0', 64); Rejected(fullScoreChanged, "Changed full score digest accepted");
    var restChanged = Copy(completeRequest); restChanged["rest"]!.AsArray().Add("--unused-option"); Rejected(restChanged, "Changed rest accepted despite matching recommendation");
    var cultureChanged = Copy(completeRequest); cultureChanged["culture"] = "ko-KR"; Rejected(cultureChanged, "Changed culture accepted despite matching recommendation");
    var destinationChanged = Copy(completeRequest); destinationChanged["history_file"] = "elsewhere"; Rejected(destinationChanged, "Changed destination accepted");
    var evidenceChanged = Copy(completeRequest); evidenceChanged["captured_replies"]![3]!["result"]!["Json"]!["browser"] = "other"; Rejected(evidenceChanged, "Changed capture accepted despite matching score");
    var reordered = Copy(completeRequest); reordered["captured_replies"]![3]!["argv"]![1] = "cdp-click"; Rejected(reordered, "Acquisition action mutation accepted");
    var repeated = Copy(completeRequest); repeated["captured_replies"]!.AsArray().Add(actualRecord.DeepClone()); Rejected(repeated, "Repeated record accepted");
    var noPermission = Copy(request); noPermission["rest"]!.AsArray().RemoveAt(5); var noRecord = Run(noPermission);
    Check(State(noRecord) == "complete" && noRecord["record_authorization"] is null, "Missing record flag must never authorize Append");
    var disabled = Copy(request); disabled["rest"]!.AsArray().Add("--no-strategy-history"); disabled["captured_replies"]!.AsArray().RemoveAt(5);
    Check(State(Run(disabled)) == "complete", "Disabled history must suppress history and record");
    var low = Obj(new { rest = new[] { "--record-strategy" }, culture = "en-US", captured_replies = new object[]
    {
        new { kind = "windows", argv = Array.Empty<string>(), result = new[] { new { title = "Editor", process = "notepad", @class = "Main", visible = true, rect = new { width = 640, height = 480 } } } },
        new { kind = "history", argv = new[] { "notepad|main|document_or_mail_app" }, result = (object?)null }
    }});
    var lowResult = Run(low);
    Check(State(lowResult) == "complete" && lowResult["record_authorization"] is null && lowResult["payload"]!["strategy_score"]!["confidence"]!.GetValue<string>() == "low", "Low-confidence explicit record request gained authorization");
    var timed = Copy(completeRequest); timed["elapsed_ms"] = 7; timed["cdp_elapsed_ms"] = 4; timed["uia_elapsed_ms"] = 5;
    Check(State(Run(timed)) == "complete", "Measured durations must not invalidate the invocation binding");
    var rawUnicode = JsonSerializer.Serialize(completeRequest, new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
    Check(State(Run(JsonNode.Parse(rawUnicode)!.AsObject())) == "complete", "Equivalent Unicode transport encoding changed authorization");
    var thrown = Copy(completeRequest); thrown["captured_replies"]![6]!.AsObject().Remove("result"); thrown["captured_replies"]![6]!["error"] = "fixture_record";
    var failure = Run(thrown); Check(State(failure) == "error" && failure["error"]!.GetValue<string>() == "fixture_record", "Append failure changed or was retried");
    foreach (JsonNode? value in new JsonNode?[] { null, new JsonObject(), JsonValue.Create(false), JsonValue.Create("recorded"), new JsonArray(), new JsonArray("recorded") })
    {
        var shape = Copy(completeRequest); shape["captured_replies"]![6]!["result"] = value?.DeepClone();
        Check(State(Run(shape)) == "complete", "Actual record result shape was rejected");
    }
    var large = Copy(request); large["captured_replies"]![5]!["result"]!["extra"] = new string('x', 600000);
    var largePending = Run(large);
    Check(State(largePending) == "query" && largePending["record_authorization"]!.ToJsonString().Length < 4096, "Receipt duplicates large history evidence");
    large["record_authorization"] = largePending["record_authorization"]!.DeepClone(); large["captured_replies"]!.AsArray().Add(actualRecord.DeepClone());
    Check(large.ToJsonString().Length < 1048576 && State(Run(large)) == "complete", "Large captured history grew beyond the final transport budget");
    var nearLimit = Copy(request); nearLimit["captured_replies"]![5]!["result"]!["extra"] = new string('x', 1040000);
    var preparedNearLimit = Run(nearLimit);
    Check(nearLimit.ToJsonString().Length < 1048576 && State(preparedNearLimit["record_completion"]!.AsObject()) == "complete", "Near-limit input must complete its assembly before persistence");
    var finalFrame = Copy(nearLimit); var largeRecord = actualRecord.DeepClone(); largeRecord["result"] = Obj(new { success = true, extra = new string('r', 20000) }); finalFrame["captured_replies"]!.AsArray().Add(largeRecord);
    Check(finalFrame.ToJsonString().Length > 1048576, "Near-limit regression must exceed the bridge cap if a final replay were attempted");
    return checks;
}
