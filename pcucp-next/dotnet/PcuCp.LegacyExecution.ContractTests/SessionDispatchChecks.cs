using System.IO;
using System.Text;
using System.Text.Json;

// Inert JSONL endpoints only. No filesystem, process, desktop or model effect runs.
internal static class SessionDispatchChecks
{
    private static JsonElement J(object? value) => JsonSerializer.SerializeToElement(value);
    private static LegacyExecutionEffect E(LegacyExecutionEffectKind kind, string name = "", string[]? argv = null,
        object? data = null, bool live = false) => new(kind, name, argv ?? [], data is JsonElement element ? element : J(data), live);
    private static LegacyExecutionResult Result(JsonElement? payload = null) => new(payload ?? J(null), 0, 8, null);
    private static string Reply(long id, object envelope)
    {
        string data = Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(envelope));
        return JsonSerializer.Serialize(new { kind = "part", id, data }) + "\n" + JsonSerializer.Serialize(new { kind = "end", id }) + "\n";
    }
    private static string Ok(long id) => Reply(id, new { state = "ok", value = LegacyExecutionWire.Encode(J(null)) });
    private sealed record Message(string Target, long Id, JsonElement Payload);
    private static List<Message> Messages(IEnumerable<string> lines)
    {
        var buffers = new Dictionary<(string, long), MemoryStream>();
        var messages = new List<Message>();
        foreach (string line in lines.Where(line => line.Length != 0))
        {
            using var frame = JsonDocument.Parse(line);
            string target = frame.RootElement.GetProperty("target").GetString()!;
            long id = frame.RootElement.GetProperty("id").GetInt64();
            var key = (target, id);
            if (frame.RootElement.GetProperty("kind").GetString() == "part")
            {
                if (!buffers.TryGetValue(key, out var buffer)) buffers[key] = buffer = new();
                buffer.Write(Convert.FromBase64String(frame.RootElement.GetProperty("data").GetString()!));
            }
            else
            {
                using var payload = JsonDocument.Parse(buffers[key].ToArray());
                messages.Add(new(target, id, payload.RootElement.Clone()));
                buffers[key].Dispose(); buffers.Remove(key);
            }
        }
        foreach (var buffer in buffers.Values) buffer.Dispose();
        return messages;
    }
    private static List<Message> Messages(StringWriter writer) => Messages(writer.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries));

    // Records successful WriteLine calls separately from the raw partial stream.
    // A damaged transport need not deliver the final error, but its attempted error
    // envelope must still account for dispatch correctly without a second effect.
    private sealed class FailingWriter(string target, string kind, bool onFlush = false) : TextWriter
    {
        public override Encoding Encoding => Encoding.UTF8;
        internal readonly List<string> CompleteLines = [];
        internal readonly StringBuilder Raw = new();
        internal bool Failed;
        private bool failFlush;
        public override void WriteLine(string? value)
        {
            using var parsed = JsonDocument.Parse(value!);
            bool matches = !Failed && parsed.RootElement.GetProperty("target").GetString() == target &&
                parsed.RootElement.GetProperty("kind").GetString() == kind;
            if (matches && !onFlush)
            {
                Raw.Append(value!.AsSpan(0, value!.Length / 2)); Failed = true;
                throw new IOException("Injected partial frame write.");
            }
            CompleteLines.Add(value!); Raw.AppendLine(value);
            if (matches) failFlush = true;
        }
        public override void Flush()
        {
            if (!failFlush) return;
            failFlush = false; Failed = true;
            throw new IOException("Injected frame flush failure.");
        }
    }

    internal static void Run(Action<bool, string> check)
    {
        void Error(List<Message> messages, bool uncertain, string reason)
        {
            var errors = messages.Where(m => m.Target == "error").ToArray();
            check(errors.Length == 1, reason + ": expected one terminal error");
            check(errors[0].Payload.GetProperty("mutation_may_have_occurred").GetBoolean() == uncertain, reason + ": incorrect mutation phase");
            check(!errors[0].Payload.GetProperty("automatic_retry").GetBoolean(), reason + ": automatic retry was enabled");
        }
        static LegacyExecutionResult InvokeOne(ILegacyExecutionEffects effects, LegacyExecutionEffect effect)
        { effects.Invoke(effect); return Result(); }

        var cases = new List<(LegacyExecutionEffect Effect, bool Write)>
        {
            (E(LegacyExecutionEffectKind.HistoryAppend), true),
            (E(LegacyExecutionEffectKind.TrajectoryAppend), true),
            (E(LegacyExecutionEffectKind.RemoveFile), true),
            (E(LegacyExecutionEffectKind.PointCacheWrite), true),
            (E(LegacyExecutionEffectKind.AnchorAppend), true),
            (E(LegacyExecutionEffectKind.Appshot), true),
            (E(LegacyExecutionEffectKind.Notice), true),
            (E(LegacyExecutionEffectKind.Child, argv: ["macro", "task-plan"]), true),
            (E(LegacyExecutionEffectKind.Child, "direct", ["macro", "windows"]), true),
            (E(LegacyExecutionEffectKind.Cucp), true),
            (E(LegacyExecutionEffectKind.Vision), true),
            (E(LegacyExecutionEffectKind.LocalMacro, "click-point"), true),
            (E(LegacyExecutionEffectKind.LocalMacro, "icon-find"), false),
            (E(LegacyExecutionEffectKind.LocalMacro, "unregistered"), true),
            (E(LegacyExecutionEffectKind.Native, argv: ["-Action", "screenshot", "-OutPath", "owned.png"]), true),
            (E(LegacyExecutionEffectKind.Native, argv: ["-Action", "screenshot-diff"]), true),
            (E(LegacyExecutionEffectKind.Native, argv: ["-Action", "uia-find", "-Label", "screenshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "AuditProbe"), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "ClearAppshotCache"), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Appshot"), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Notice"), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "HelperUp"), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "AssertAuthorized"), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "helperup"), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "assertauthorized"), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", data: new { name = "health-quick" }), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", data: new { name = "find-label" }), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", ["--rich"], new { name = "windows" }), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", ["--match", "--rich"], new { name = "windows" }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", ["--rich", "--json-only"], new { name = "windows" }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", ["--rich"], new { name = "Windows" }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", data: new { name = "windows", value = "find-label" }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", data: new { value = new { name = "health-quick" } }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", data: new { name = 1 }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Cli", ["observe", "appshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Cli", ["observe", "screenshot", "--out", "owned.png"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Cli", ["observe", "context", "--label", "screenshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Cli", ["version", "observe", "appshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Native", ["-Action", "screenshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "Native", ["-Action", "focused"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "FileStat", data: "AuditProbe"), false),
            (E(LegacyExecutionEffectKind.Native, argv: ["-action", "screenshot"]), true),
            (E(LegacyExecutionEffectKind.Native, argv: ["-Action", "Screenshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "auditprobe"), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Macro", data: new { name = "HEALTH-QUICK" }), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "Cli", ["OBSERVE", "appshot"]), true),
            (E(LegacyExecutionEffectKind.Diagnostic, "cli", ["observe", "appshot"]), false),
            (E(LegacyExecutionEffectKind.Diagnostic, "native", ["-Action", "screenshot"]), false),
            (E(LegacyExecutionEffectKind.LocalMacro, "ICON-FIND"), true)
        };
        foreach (var kind in new[] { LegacyExecutionEffectKind.WorkflowPlan, LegacyExecutionEffectKind.CdpPort,
            LegacyExecutionEffectKind.HistoryRead, LegacyExecutionEffectKind.Sleep, LegacyExecutionEffectKind.Clock,
            LegacyExecutionEffectKind.Timestamp, LegacyExecutionEffectKind.CachePath, LegacyExecutionEffectKind.FileExists,
            LegacyExecutionEffectKind.Console, LegacyExecutionEffectKind.Win32Windows, LegacyExecutionEffectKind.UIAffordances,
            LegacyExecutionEffectKind.HitTestPoint, LegacyExecutionEffectKind.PointCacheRead, LegacyExecutionEffectKind.CoordProfile,
            LegacyExecutionEffectKind.AnchorScore, LegacyExecutionEffectKind.PipelineOutput,
            LegacyExecutionEffectKind.ObservationId }) cases.Add((E(kind), false));
        foreach (var kind in Enum.GetValues<LegacyExecutionEffectKind>())
            check(LegacyExecutionEffectSemantics.MayChangeState(E(kind, live: true)), "An existing Live effect lost uncertainty classification: " + kind);
        foreach (var (effect, write) in cases)
        {
            check(LegacyExecutionEffectSemantics.MayChangeState(effect) == write, "Incorrect closed state classification: " + effect.Kind + ":" + effect.Name);
            using var output = new StringWriter();
            var session = new LegacyExecutionSession(new StringReader(""), output);
            check(session.Run(fx => InvokeOne(fx, effect)) == 1, "Disconnected effect reply was accepted");
            var messages = Messages(output); Error(messages, write, "Disconnected " + effect.Kind + ":" + effect.Name);
            var sent = messages.Where(m => m.Target == "effect").ToArray();
            check(sent.Length == 1, "Disconnect retried an effect");
            check(!sent[0].Payload.GetProperty("live").GetBoolean() && !sent[0].Payload.GetProperty("confirm_sensitive").GetBoolean(), "Owned state classification granted input or sensitive authority");
        }

        using var deepDocument = JsonDocument.Parse(new string('[', 80) + "0" + new string(']', 80), new JsonDocumentOptions { MaxDepth = 128 });
        JsonElement deep = deepDocument.RootElement.Clone();
        foreach (bool live in new[] { false, true })
        {
            using var output = new StringWriter();
            var session = new LegacyExecutionSession(new StringReader(""), output);
            check(session.Run(fx => InvokeOne(fx, E(LegacyExecutionEffectKind.HistoryAppend, data: deep, live: live))) == 1, "Deep tagged effect serialization was accepted");
            Error(Messages(output), false, "Rejected pre-dispatch serialization");
            check(Messages(output).Single().Id == 1, "Rejected preflight consumed an unobserved sequence ID");
            check(!output.ToString().Contains("\"target\":\"effect\"", StringComparison.Ordinal), "Failed serialization leaked effect frames");
        }
        var disposed = JsonDocument.Parse("{}"); var invalid = disposed.RootElement; disposed.Dispose();
        using (var output = new StringWriter())
        {
            var session = new LegacyExecutionSession(new StringReader(""), output);
            check(session.Run(fx => InvokeOne(fx, E(LegacyExecutionEffectKind.HistoryAppend, data: invalid, live: true))) == 1, "Invalid wire value was accepted");
            Error(Messages(output), false, "Rejected pre-dispatch wire encoding");
            check(Messages(output).Single().Id == 1, "Rejected wire encoding consumed an unobserved sequence ID");
            check(!output.ToString().Contains("\"target\":\"effect\"", StringComparison.Ordinal), "Failed wire encoding leaked effect frames");
        }

        foreach (bool write in new[] { false, true })
        foreach (string reply in new[] { "not-json\n", "{\"kind\":\"end\",\"id\":2}\n", "{\"kind\":\"end\",\"id\":\"1\"}\n", new string('x', 66001) + "\n" })
        {
            using var output = new StringWriter(); var session = new LegacyExecutionSession(new StringReader(reply), output);
            var effect = E(write ? LegacyExecutionEffectKind.PointCacheWrite : LegacyExecutionEffectKind.Clock);
            check(session.Run(fx => InvokeOne(fx, effect)) == 1, "Malformed effect reply was accepted");
            var messages = Messages(output); Error(messages, write, "Malformed reply");
            check(messages.Count(m => m.Target == "effect") == 1, "Malformed reply retried an effect");
        }

        foreach (string kind in new[] { "part", "end" }) foreach (bool onFlush in new[] { false, true })
        {
            using var output = new FailingWriter("effect", kind, onFlush);
            var session = new LegacyExecutionSession(new StringReader(""), output);
            check(session.Run(fx => InvokeOne(fx, E(LegacyExecutionEffectKind.HistoryAppend))) == 1, "Partial writer failure was accepted");
            check(output.Failed, "Partial writer injection did not execute");
            var messages = Messages(output.CompleteLines); Error(messages, kind == "end", "Partial " + kind + (onFlush ? " flush" : " write"));
            check(messages.Count(m => m.Target == "effect") == (kind == "end" && onFlush ? 1 : 0), "Part failure dispatched or retried an effect");
        }

        foreach (bool write in new[] { false, true }) foreach (bool encode in new[] { false, true })
        {
            using var output = new StringWriter(); var session = new LegacyExecutionSession(new StringReader(Ok(1)), output);
            int exit = session.Run(fx =>
            {
                fx.Invoke(E(write ? LegacyExecutionEffectKind.AnchorAppend : LegacyExecutionEffectKind.Clock));
                if (!encode) throw new InvalidOperationException("Report assembly failed.");
                return Result(deep);
            });
            check(exit == 1, "Terminal failure after acknowledged effect was accepted");
            var messages = Messages(output); Error(messages, write, "Failure after acknowledged effect");
            check(messages.Single(m => m.Target == "error").Id == 2, "Terminal preflight failure skipped an ID");
            check(messages.Count(m => m.Target == "effect") == 1 && messages.All(m => m.Target != "complete"), "Terminal failure repeated an effect or emitted incomplete completion");
        }
        using (var output = new StringWriter())
        {
            var session = new LegacyExecutionSession(new StringReader(Ok(1)), output);
            check(session.Run(fx => { fx.Invoke(E(LegacyExecutionEffectKind.TrajectoryAppend)); return InvokeOne(fx, E(LegacyExecutionEffectKind.Clock)); }) == 1,
                "Lost read after an acknowledged write was accepted");
            var messages = Messages(output); Error(messages, true, "Write followed by read disconnect");
            check(messages.Count(m => m.Target == "effect") == 2, "Lost read repeated an earlier write");
        }
        using (var output = new StringWriter())
        {
            var session = new LegacyExecutionSession(new StringReader(Ok(1)), output);
            check(session.Run(fx => { fx.Invoke(E(LegacyExecutionEffectKind.HistoryAppend)); return InvokeOne(fx, E(LegacyExecutionEffectKind.Appshot, data: deep)); }) == 1,
                "Second effect preflight failure was accepted");
            var messages = Messages(output); Error(messages, true, "Later serialization cannot erase earlier write");
            check(messages.Single(m => m.Target == "error").Id == 2, "Rejected second effect consumed an unobserved ID");
            check(messages.Count(m => m.Target == "effect") == 1, "Rejected second effect was sent");
        }
        foreach (var prior in new[] { E(LegacyExecutionEffectKind.HistoryAppend), E(LegacyExecutionEffectKind.Native, argv: ["-Action", "focused"]) })
        foreach (var read in new[] { LegacyExecutionEffectKind.HistoryRead, LegacyExecutionEffectKind.UIAffordances, LegacyExecutionEffectKind.Win32Windows })
        using (var output = new StringWriter())
        {
            string reply = Ok(1) + Reply(2, new { state = "error", message = "Known read failure.", mutation_may_have_occurred = false });
            var session = new LegacyExecutionSession(new StringReader(reply), output); bool ordinary = false;
            int exit = session.Run(fx =>
            {
                fx.Invoke(prior);
                try { fx.Invoke(E(read)); }
                catch (LegacyExecutionEffectException error) { ordinary = !error.MutationMayHaveOccurred; }
                return Result();
            });
            check(exit == 0 && ordinary, "Known read error reply was changed into unknown prior-write outcome");
            check(Messages(output).Count(m => m.Target == "complete") == 1, "Caught known read failure lost completion");
        }
        using (var output = new StringWriter())
        {
            string reply = Reply(1, new { state = "ok", value = LegacyExecutionWire.Encode(J(true)) });
            var session = new LegacyExecutionSession(new StringReader(reply), output);
            int exit = session.Run(fx => Result(fx.Invoke(E(LegacyExecutionEffectKind.Diagnostic, "AssertAuthorized"))));
            var messages = Messages(output);
            check(exit == 0 && messages.All(m => m.Target != "error"), "Known blocked reply became an uncertain exception");
            var payload = messages.Single(m => m.Target == "complete").Payload.GetProperty("payload");
            check(LegacyExecutionWire.Decode(payload).GetBoolean(), "Known authorization rejection changed its Boolean value");
        }
    }
}
