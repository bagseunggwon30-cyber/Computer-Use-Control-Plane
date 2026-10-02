using System.Text.Json;

internal static class InteractionChecks
{
    internal static void Run()
    {
        int checks = 0;
        void Assert(bool condition, string detail) { checks++; if (!condition) throw new InvalidOperationException(detail); }
        foreach (string op in new[] { "click-point", "safe-type", "icon-click", "ocr-click", "click-label" })
        {
            var result = InteractionFixture.J(InteractionFixture.Evaluate(InteractionFixture.J(new { operation = op, rest = new[] { "--label", "Name" }, allow_live = false, replies = Array.Empty<object>() })));
            Assert(result.GetProperty("state").GetString() == "error", op + " authority");
            Assert(!result.GetProperty("effects").EnumerateArray().Any(e => e.GetProperty("live").GetBoolean()), op + " no live effect");
        }
        foreach (string op in new[] { "find-label", "icon-find", "precision-validate" })
        {
            var result = InteractionFixture.J(InteractionFixture.Evaluate(InteractionFixture.J(new { operation = op, rest = Array.Empty<string>(), allow_live = false, replies = Array.Empty<object>() })));
            Assert(result.GetProperty("state").GetString() == "error", op + " required options");
            Assert(result.GetProperty("effects").GetArrayLength() == 0, op + " validates before acquisition");
        }
        var click = InteractionFixture.J(InteractionFixture.Evaluate(InteractionFixture.J(new { operation = "click-point", rest = new[] { "--x", "0", "--y", "0" }, allow_live = true,
            replies = new object[] { new { ExitCode = 0, Json = new { status = "ok", mutation_may_have_occurred = true } } } })));
        Assert(click.GetProperty("exit").GetInt32() == 2, "uncertain click stops");
        Assert(click.GetProperty("effects").GetArrayLength() == 1, "uncertain click skips trajectory");
        Assert(click.GetProperty("effects")[0].GetProperty("live").GetBoolean(), "click is live");
        static object Reply(object? json, int exit = 0) => new { ExitCode = exit, ElapsedMs = 17, Raw = "raw", Json = json };
        static JsonElement Evaluate(string operation, string[] rest, object?[] replies, bool brief = false, bool doubleClick = false) =>
            InteractionFixture.J(InteractionFixture.Evaluate(InteractionFixture.J(new { operation, rest, replies, allow_live = true, brief, @double = doubleClick })));
        var windows = Reply(new { status = "ok", windows = new[] { new { hwnd = 42, title = "Editor" } } });
        var focused = Reply(new { status = "ok", verified = true, target_hwnd = 42 });
        var ok = Reply(new { status = "ok" });
        foreach (var stage in new[] { "focus", "click", "type", "shortcut" }) foreach (bool exception in new[] { false, true })
        {
            var captures = new List<object?> { windows };
            if (stage != "focus") captures.Add(focused);
            if (stage is "type" or "shortcut") captures.Add(ok);
            if (stage == "shortcut") captures.Add(ok);
            captures.Add(exception ? new { @throw = "uncertain input", mutation_may_have_occurred = true } : Reply(new { status = "ok", mutation_may_have_occurred = true }));
            var result = Evaluate("safe-type", ["--text", "한글 --confirm-sensitive", "--target-match", "Editor", "--max-attempts", "10", "--click-x", "0", "--click-y", "0", "--enter"], captures.ToArray());
            Assert(result.GetProperty("state").GetString() == "complete", "uncertain safe-type reports partial");
            Assert(result.GetProperty("exit").GetInt32() == 2, "uncertain safe-type cannot succeed");
            Assert(result.GetProperty("effects").GetArrayLength() == captures.Count, "uncertain input cannot retry or append");
            var last = result.GetProperty("effects")[captures.Count - 1];
            Assert(last.GetProperty("argv")[1].GetString() == stage && last.GetProperty("live").GetBoolean(), "native mutation classification");
            Assert(result.GetProperty("payload").GetProperty("automatic_retry").ValueKind == JsonValueKind.False, "uncertainty forbids automatic retry");
        }
        foreach (var failedStage in new[] { "click", "type", "shortcut" })
        {
            var captures = new List<object?> { windows, focused };
            if (failedStage is "type" or "shortcut") captures.Add(ok);
            if (failedStage == "shortcut") captures.Add(ok);
            captures.Add(Reply(new { status = "partial" }, 2));
            var result = Evaluate("safe-type", ["--text", "ordinary", "--target-match", "Editor", "--max-attempts", "10", "--click-x", "0", "--click-y", "0", "--enter"], captures.ToArray());
            Assert(result.GetProperty("exit").GetInt32() == 2, "failed dispatch remains partial");
            Assert(result.GetProperty("consumed").GetInt32() == captures.Count, "failed input cannot replay");
            Assert(result.GetProperty("payload").GetProperty("probe_mode").GetString() == "disabled", "probe remains disabled");
        }
        var retry = Evaluate("safe-type", ["--text", "ordinary", "--target-match", "Editor", "--max-attempts", "3"],
            [windows, Reply(new { verified = false }), Reply(new { verified = true, target_hwnd = 999 }), focused, ok]);
        Assert(retry.GetProperty("exit").GetInt32() == 0, "safe focus preparation retry");
        Assert(retry.GetProperty("effects").EnumerateArray().Count(e => e.GetProperty("kind").GetString() == "Native" && e.GetProperty("argv")[1].GetString() == "type") == 1, "only one text dispatch after verified identity");
        Assert(retry.GetProperty("payload").GetProperty("reason").GetString() == "focus_failed", "historical focus reason retained after later success");
        var values = new[] { (Value: "first", Score: 10), (Value: "second", Score: 10) };
        Assert(LegacyInteractionRanking.Sort(values, (a, b) => b.Score.CompareTo(a.Score))[0].Value == "second", "PS5 equal-key swap retained");
        // The exact qualified session serves interaction callbacks, without a second protocol.
        string Frames(long id, object value)
        {
            var bytes = JsonSerializer.SerializeToUtf8Bytes(value); var lines = new List<string>();
            for (int i = 0; i < bytes.Length; i += 49152) lines.Add(JsonSerializer.Serialize(new { kind = "part", id, data = Convert.ToBase64String(bytes, i, Math.Min(49152, bytes.Length - i)) }));
            lines.Add(JsonSerializer.Serialize(new { kind = "end", id })); return string.Join("\n", lines) + "\n";
        }
        object Envelope(object? value) => new { state = "ok", value = LegacyExecutionWire.Encode(InteractionFixture.J(value)) };
        JsonElement Terminal(string text)
        {
            using var stream = new MemoryStream();
            foreach (string line in text.Split('\n', StringSplitOptions.RemoveEmptyEntries))
            {
                using var doc = JsonDocument.Parse(line); var frame = doc.RootElement;
                if (frame.GetProperty("target").GetString() == "error" && frame.GetProperty("kind").GetString() == "part")
                    stream.Write(Convert.FromBase64String(frame.GetProperty("data").GetString()!));
            }
            using var terminal = JsonDocument.Parse(stream.ToArray()); return terminal.RootElement.Clone();
        }
        foreach (string malformed in new[] { "", "{}\n", Frames(2, Envelope(ok)), "{\"kind\":\"end\",\"id\":1,\"extra\":true}\n" })
        {
            using var writer = new StringWriter(); var session = new LegacyExecutionSession(new StringReader(malformed), writer);
            int exit = session.Run(e => new LegacyExecutionCoordinator(e, new(true, false), ["--x", "1", "--y", "2"]).RunInteraction("click-point"));
            Assert(exit == 1, "malformed interaction session fails");
            var terminal = Terminal(writer.ToString());
            Assert(terminal.GetProperty("mutation_may_have_occurred").GetBoolean(), "lost reply preserves mutation uncertainty");
            Assert(!terminal.GetProperty("automatic_retry").GetBoolean(), "lost reply cannot retry");
        }
        string largeText = new string('한', 600000);
        var large = Reply(new { status = "ok", result = largeText });
        using (var writer = new StringWriter())
        {
            var input = Frames(1, Envelope(large)) + Frames(2, Envelope(null));
            var session = new LegacyExecutionSession(new StringReader(input), writer);
            Assert(session.Run(e => new LegacyExecutionCoordinator(e, new(true, false), ["--x", "1", "--y", "2"]).RunInteraction("click-point")) == 0, "large captured reply crosses bounded frames");
            Assert(writer.ToString().Split('\n').Where(v => v.Length > 0).All(v => v.Length <= 66000), "interaction frame bound retained");
        }
        // Regressions observed by the pinned PS5.1 gate at 6fc7c882.
        object Element(string text = "Save", object? confidence = null) => new { text, confidence = confidence ?? "high", window = "Editor", role = "Button",
            rect = new { x = 10, y = 20, width = 20, height = 20 }, affordance_id = text };
        object Shot(object[] grounded) => new { Grounded = grounded, FusedElements = Array.Empty<object>(), Items = Array.Empty<object>(), ObservationId = "fixture", FromCache = false };
        var label = Evaluate("find-label", ["--label", "Save"], [Shot([Element()])]);
        Assert(label.GetProperty("payload").GetProperty("candidates").GetProperty("sources").GetString() == "grounded", "conditional source array unrolls its single item");
        var decimalConfidence = Evaluate("find-label", ["--label", "Save"], [Shot([Element(confidence: .5)])]);
        Assert(decimalConfidence.GetProperty("payload").GetProperty("score").GetInt32() == 104, "PS5 fractional JSON confidence is Decimal, not Double");
        var integerConfidence = Evaluate("find-label", ["--label", "Save"], [Shot([Element(confidence: 1)])]);
        Assert(integerConfidence.GetProperty("payload").GetProperty("score").GetInt32() == 109, "PS5 Int32 confidence keeps its boost");
        foreach (int confidence in new[] { 429496729, 429496730, -429496729, 2147483647 })
        {
            var boundary = Evaluate("find-label", ["--label", "Save"], [Shot([Element(confidence: confidence)])]);
            if (confidence is 429496730 or 2147483647)
            {
                string product = ((double)confidence * 5).ToString(System.Globalization.CultureInfo.InvariantCulture);
                Assert(boundary.GetProperty("error").GetString() == $"Cannot convert value \"{product}\" to type \"System.Int32\". Error: \"Value was either too large or too small for an Int32.\"", "confidence conversion retains the PS Int32 cast error");
            }
            else
            {
                var payload = boundary.GetProperty("payload");
                Assert(payload.GetProperty("score").GetDouble() == (double)confidence * 5 + 104, "confidence score promotes without wrapping");
                Assert(payload.GetProperty("score").GetRawText() == (confidence > 0 ? "2147483749" : "-2147483541"), "confidence promotion retains PS5 integral JSON spelling");
            }
            var iconBoundary = Evaluate("icon-find", ["--label", "Save"], [new object[] { Element(confidence: confidence) }]);
            Assert(iconBoundary.GetProperty("payload").GetProperty("top").GetProperty("score").GetInt32() == 100, "IconFind ignores numeric confidence at Int32 boundaries");
        }
        var emptyExplain = Evaluate("find-label", ["--label", "Save", "--explain"], [Shot([])]);
        Assert(emptyExplain.GetProperty("payload").GetProperty("data").GetProperty("candidates").GetRawText() == "{}", "empty Select-Object pipeline retains its empty PS object");
        var oneIcon = Evaluate("icon-find", ["--label", "Save", "--limit", "1"], [new object[] { Element(), Element("Save now") }]);
        Assert(oneIcon.GetProperty("payload").GetProperty("candidates").ValueKind == JsonValueKind.Array && oneIcon.GetProperty("payload").GetProperty("candidates").GetArrayLength() == 1,
            "indexed icon truncation retains a singleton array");
        var oneJson = Evaluate("click-point", ["--x", "10", "--y", "20"], [Reply(new object[] { new { status = "ok" } })], brief: true);
        Assert(oneJson.GetProperty("brief").GetString() == "ok click-point @(10,20) button=left elapsed_ms=17", "singleton native JSON member projection");
        var manyJson = Evaluate("click-point", ["--x", "10", "--y", "20"], [Reply(new object[] { new { status = "ok" }, new { status = "partial" } })], brief: true);
        Assert(manyJson.GetProperty("brief").GetString() == "ok click-point @(10,20) button=left elapsed_ms=17 refined=( , ) source= ", "multi-item member projection preserves null slots and any-equality");
        var noExit = Evaluate("ocr-click", ["--text", "Save"], [null], brief: true);
        Assert(noExit.GetProperty("brief").GetString() == "partial ocr-click 'Save' reason=no_text_match exit=", "missing exit remains empty in legacy text");
        var noExitPoint = Evaluate("click-point", ["--x", "10", "--y", "20"], [new { score = 75 }]);
        Assert(noExitPoint.GetProperty("effects")[1].GetProperty("data").GetProperty("exit").ValueKind == JsonValueKind.Null, "uncast trajectory exit preserves null");
        var noExitDouble = Evaluate("click-label", ["--label", "Save"], [Shot([Element()]), new { }], brief: true, doubleClick: true);
        Assert(noExitDouble.GetProperty("effects").EnumerateArray().Count(e => e.GetProperty("live").GetBoolean()) == 1, "missing exit is not successful and cannot trigger second click");
        if (OperatingSystem.IsWindows())
        {
            Assert(!LegacyInteractionText.Equal("한글", "한글".Normalize(System.Text.NormalizationForm.FormD)), "Windows NLS does not equate composed/decomposed Hangul");
            Assert(!LegacyInteractionText.ContainsPrefix("한글".Normalize(System.Text.NormalizationForm.FormD), "한글"), "Windows NLS prefix match must not add a decomposed Hangul candidate");
            Assert(LegacyInteractionText.Equal("café", "cafe\u0301"), "Windows NLS still equates composed/decomposed Latin");
        }
        Console.WriteLine($"{checks} interaction contracts passed; no actual input, model, clipboard or sleep executed.");
    }
}
