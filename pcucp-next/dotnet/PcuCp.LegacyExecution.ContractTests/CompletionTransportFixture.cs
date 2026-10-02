using System.Text;
using System.Text.Json;

// The existing disposable session runner has no native/desktop executor. This
// mode changes only its final wire bytes to test the receiving production host.
internal static class CompletionTransportFixture
{
    internal static bool TryRun(string[] args)
    {
        string? path = Environment.GetEnvironmentVariable("CUCP_COMPLETION_FIXTURE");
        if (path is null || args.Length != 1 || args[0] is not
            ("legacy-execution-session" or "legacy-interaction-session" or "legacy-diagnostic-session")) return false;
        using var input = JsonDocument.Parse(File.ReadAllText(path));
        var root = input.RootElement;
        string log = root.GetProperty("log").GetString()!;
        void Record(string value) => File.AppendAllText(log, value + "\n");
        Record("start");
        // Use the real UTF-8 reader and startup parser, including its single
        // leading-BOM rule. Never execute the operation being validated.
        using var reader = LegacySessionInput.Open(Console.OpenStandardInput());
        string family = args[0] switch { "legacy-interaction-session" => "interaction", "legacy-diagnostic-session" => "diagnostics", _ => "execution" };
        _ = LegacyExecutionStartup.Read([], reader, family);
        Record("startup");
        using var writer = new CompletionWriter(Console.Out, root.GetProperty("completion").GetString()!);
        Environment.ExitCode = new LegacyExecutionSession(reader, writer).Run(effects =>
        {
            if (root.GetProperty("after_write").GetBoolean())
            {
                effects.Invoke(new LegacyExecutionEffect(LegacyExecutionEffectKind.TrajectoryAppend, "workflow-run", [],
                    JsonSerializer.SerializeToElement(new { status = "ok", executed_count = 0, failed_count = 0, total_steps = 0, elapsed_ms = 0 })));
                Record("write-acknowledged");
            }
            return new LegacyExecutionResult(JsonSerializer.SerializeToElement("fixture"), root.GetProperty("process_exit").GetInt32(), 1, null);
        });
        return true;
    }

    private sealed class CompletionWriter(TextWriter output, string completion) : TextWriter
    {
        public override Encoding Encoding => output.Encoding;
        public override void Flush() => output.Flush();
        public override void WriteLine(string? value)
        {
            using var frame = JsonDocument.Parse(value!);
            var root = frame.RootElement;
            if (root.GetProperty("target").GetString() == "complete" && root.GetProperty("kind").GetString() == "part")
                value = JsonSerializer.Serialize(new { kind = "part", target = "complete", id = root.GetProperty("id").GetInt64(),
                    data = Convert.ToBase64String(Encoding.UTF8.GetBytes(completion)) });
            output.WriteLine(value);
        }
    }
}
