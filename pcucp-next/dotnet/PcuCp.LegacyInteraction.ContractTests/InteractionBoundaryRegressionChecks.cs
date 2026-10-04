using System.Text.Json;

// Stable LR IDs match the accepted Pester invariants. Fixtures invoke the actual
// production coordinator; their captured effects never execute native input or sleep.
internal static class InteractionBoundaryRegressionChecks
{
    private static int checks;
    private static void Check(bool condition, string id, string detail)
    {
        if (!condition) throw new InvalidOperationException($"{id}: {detail}");
        checks++;
    }
    private static object Reply(object? json, int exit = 0) => new { ExitCode = exit, Json = json };
    private static object Windows(params long[] handles) => Reply(new
    {
        status = "ok", windows = handles.Select(hwnd => new { hwnd, title = "Note" }).ToArray()
    });
    private static object Focused() => Reply(new { status = "ok", verified = true, target_hwnd = 42 });
    private static object Ok() => Reply(new { status = "ok" });
    private static object Scan(int x, int y) => Reply(new
    {
        status = "ok", recommended_point = new { x, y }, best = new { final_score = 42 }
    });
    private static JsonElement Evaluate(string operation, string[] rest, params object?[] replies) =>
        InteractionFixture.J(InteractionFixture.Evaluate(InteractionFixture.J(new { operation, rest, replies, allow_live = true })));
    private static JsonElement[] Effects(JsonElement result) => result.GetProperty("effects").EnumerateArray().ToArray();
    private static JsonElement[] Native(JsonElement result) => Effects(result).Where(e => e.GetProperty("kind").GetString() == "Native").ToArray();
    private static string[] Argv(JsonElement effect) => effect.GetProperty("argv").EnumerateArray().Select(v => v.GetString()!).ToArray();
    private static string? Option(JsonElement effect, string name)
    {
        var argv = Argv(effect); int index = Array.IndexOf(argv, name);
        return index >= 0 && index + 1 < argv.Length ? argv[index + 1] : null;
    }
    private static void Completed(JsonElement result, int exit, string id)
    {
        Check(result.GetProperty("state").GetString() == "complete", id, "Kernel did not complete: " + result);
        Check(result.GetProperty("exit").GetInt32() == exit, id, "Unexpected exit code");
    }
    private static void Actions(JsonElement result, string id, params string[] expected)
    {
        Check(Native(result).Select(e => Argv(e)[1]).SequenceEqual(expected), id, "Native action order/count changed");
        Check(result.GetProperty("consumed").GetInt32() == expected.Length, id, "Unexpected captured reply consumption");
    }

    internal static void Run()
    {
        foreach (var test in new (string Id, Action Run)[]
        {
            ("LR04 signed click coordinates", SignedClickCoordinates),
            ("LR05 asymmetric missing coordinates", MissingCoordinate),
            ("LR06 guarded text identity and evidence", GuardedTyping),
            ("LR07 failed or uncertain typing never replays", FailedTyping),
            ("LR08 failed send preserves text evidence", FailedSend),
            ("LR09 ambiguous title stops before input", AmbiguousTarget),
            ("LR12 one sample cannot establish stability", SinglePrecisionSample),
            ("LR13 negative recommended point evidence", NegativePrecisionPoint)
        })
        {
            test.Run();
            Console.WriteLine("PASS " + test.Id);
        }
        Console.WriteLine($"Passed {checks} independent interaction boundary assertions across 8 accepted regression IDs.");
    }

    private static void SignedClickCoordinates()
    {
        const string id = "LR04";
        var result = Evaluate("click-point", ["--x", "-20", "--y", "0"], Reply(new { status = "ok", x = -20, y = 0 }));
        Completed(result, 0, id); Actions(result, id, "click");
        var click = Native(result).Single();
        Check(Option(click, "-X") == "-20" && Option(click, "-Y") == "0", id, "Signed or zero coordinate was changed");
        Check(click.GetProperty("live").GetBoolean(), id, "Click lost its live classification");
    }

    private static void MissingCoordinate()
    {
        const string id = "LR05";
        foreach (var rest in new[] { new[] { "--x", "0" }, new[] { "--y", "0" } })
        {
            var result = Evaluate("click-point", rest);
            Check(result.GetProperty("state").GetString() == "error", id, "An omitted coordinate became zero");
            Check(result.GetProperty("error").GetString() == "macro click-point requires --x and --y", id, "Missing coordinate was not rejected at validation");
            Check(Effects(result).Length == 0 && result.GetProperty("consumed").GetInt32() == 0, id, "Missing coordinate reached an effect");
        }
    }

    private static void GuardedTyping()
    {
        const string id = "LR06", text = "hello 한글 + ^ % {value}\nsecond line";
        var result = Evaluate("safe-type", ["--text", text, "--target-match", "Note", "--enter", "--probe", "SHOULD NEVER TYPE", "--skip-probe"],
            Windows(42), Focused(), Ok(), Ok());
        Completed(result, 0, id); Actions(result, id, "windows", "focus", "type", "shortcut");
        var native = Native(result);
        Check(Effects(result).Length == 4, id, "Guarded typing acquired an extra effect");
        Check(Option(native[1], "-WindowHwnd") == "42", id, "Focus was not pinned to the selected window");
        Check(Option(native[2], "-Text") == text, id, "Requested text changed or a probe was typed");
        Check(native.Skip(2).All(e => Option(e, "-TargetHwnd") == "42"), id, "Type or send lost the pinned HWND");
        Check(Option(native[3], "-Keys") == "enter", id, "Requested send changed");
        Check(native.All(e => !Argv(e).Contains("ctrl+z") && !Argv(e).Contains("SHOULD NEVER TYPE")), id, "Probe or undo reached native input");
        var payload = result.GetProperty("payload");
        Check(payload.GetProperty("text_dispatched").GetBoolean(), id, "Successful text dispatch was lost");
        Check(!payload.GetProperty("application_result_verified").GetBoolean(), id, "Input dispatch claimed application verification");
        Check(payload.GetProperty("probe").ValueKind == JsonValueKind.Null && payload.GetProperty("probe_mode").GetString() == "disabled", id, "Probe evidence changed");
    }

    private static void FailedTyping()
    {
        const string id = "LR07";
        foreach (bool uncertain in new[] { false, true })
        {
            object failure = uncertain ? Reply(new { status = "ok", mutation_may_have_occurred = true }) : Reply(new { status = "error" }, 1);
            // Spare successful replies make a replay observable rather than hiding it behind exhaustion.
            var result = Evaluate("safe-type", ["--text", "hello", "--target-match", "Note", "--max-attempts", "3", "--enter"],
                Windows(42), Focused(), failure, Ok(), Ok(), Ok(), Ok());
            Completed(result, 2, id); Actions(result, id, "windows", "focus", "type");
            Check(Effects(result).Length == 3, id, "A failed type continued to another effect");
            if (uncertain)
            {
                var payload = result.GetProperty("payload");
                Check(payload.GetProperty("mutation_may_have_occurred").GetBoolean() && !payload.GetProperty("automatic_retry").GetBoolean(), id, "Uncertain typing lost its no-retry evidence");
            }
        }
    }

    private static void FailedSend()
    {
        const string id = "LR08";
        var result = Evaluate("safe-type", ["--text", "hello", "--target-match", "Note", "--enter", "--max-attempts", "3"],
            Windows(42), Focused(), Ok(), Reply(new { status = "blocked" }, 3), Ok(), Ok());
        Completed(result, 2, id); Actions(result, id, "windows", "focus", "type", "shortcut");
        Check(Effects(result).Length == 4, id, "A failed send continued to another effect");
        var payload = result.GetProperty("payload");
        Check(payload.GetProperty("text_dispatched").GetBoolean(), id, "Failed send erased successful text evidence");
        Check(payload.GetProperty("reason").GetString() == "send_blocked_or_failed", id, "Failed send was not distinguished from failed typing");
        Check(!payload.GetProperty("application_result_verified").GetBoolean(), id, "Failed send claimed application verification");
    }

    private static void AmbiguousTarget()
    {
        const string id = "LR09";
        var result = Evaluate("safe-type", ["--text", "hello", "--target-match", "Note"], Windows(42, 43), Focused(), Ok());
        Completed(result, 2, id); Actions(result, id, "windows");
        Check(Effects(result).Length == 1 && Effects(result).All(e => !e.GetProperty("live").GetBoolean()), id, "Ambiguous selection reached focus or input");
        Check(result.GetProperty("payload").GetProperty("reason").GetString() == "ambiguous_target", id, "Ambiguity reason changed");
    }

    private static void SinglePrecisionSample()
    {
        const string id = "LR12";
        var result = Evaluate("precision-validate", ["--x", "0", "--y", "0", "--samples", "1"], Scan(0, 0));
        Completed(result, 2, id); Actions(result, id, "hit-scan");
        var payload = result.GetProperty("payload");
        Check(payload.GetProperty("sample_count").GetInt32() == 1, id, "Successful single sample was not counted");
        Check(!payload.GetProperty("stable").GetBoolean(), id, "One sample was declared stable");
        Check(payload.GetProperty("drift_max").ValueKind == JsonValueKind.Null, id, "One sample supplied invented drift evidence");
        Check(Effects(result).All(e => !e.GetProperty("live").GetBoolean()), id, "Precision validation requested input");
    }

    private static void NegativePrecisionPoint()
    {
        const string id = "LR13";
        var result = Evaluate("precision-validate", ["--x", "-30", "--y", "0", "--samples", "2"], Scan(-30, 0), Scan(-30, 0));
        Completed(result, 0, id); Actions(result, id, "hit-scan", "hit-scan");
        Check(Native(result).All(e => Option(e, "-X") == "-30" && Option(e, "-Y") == "0"), id, "Hit-scan input coordinates changed");
        var payload = result.GetProperty("payload");
        Check(payload.GetProperty("sample_count").GetInt32() == 2 && payload.GetProperty("error_count").GetInt32() == 0, id, "Signed recommended points were discarded");
        Check(payload.GetProperty("stable").GetBoolean() && payload.GetProperty("drift_max").GetDouble() == 0, id, "Identical points did not provide stability evidence");
        Check(payload.GetProperty("points").EnumerateArray().All(p => p.GetProperty("x").GetInt32() == -30 && p.GetProperty("y").GetInt32() == 0 && p.GetProperty("score").GetInt32() == 42), id, "recommended_point or best.final_score fields were not used");
        Check(Effects(result).All(e => !e.GetProperty("live").GetBoolean()), id, "Precision validation requested input");
    }
}
