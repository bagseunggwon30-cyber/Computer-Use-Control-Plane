using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

internal static class ProgressContractChecks
{
    internal static void Run()
    {
        string directory = Path.Combine(Path.GetTempPath(), "owned-helper-progress-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory); int checks = 0;
        Action<bool> check = condition => { if (!condition) throw new Exception("Owned progress contract failed"); checks++; };
        Func<object, string> serialize = value => JsonSerializer.Serialize(value);
        try
        {
            string path = Path.Combine(directory, "sequence.jsonl");
            using (var progress = new OwnedProviderProgress(path, "uia", serialize))
            {
                progress.Emit("group.start"); progress.StartRequest("uia-missing"); progress.Emit("dispatch.start");
                progress.ProviderTicks = 3; progress.DiagnosticTicks = 5; progress.Emit("dispatch.end");
                // Prefix must be readable and complete before Dispose/terminal state.
                string[] prefix;
                using (var reader = new StreamReader(new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)))
                    prefix = reader.ReadToEnd().Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries);
                check(prefix.Length == 4);
                using (var parsed = JsonDocument.Parse(prefix[3]))
                {
                    check(parsed.RootElement.GetProperty("sequence").GetInt32() == 4);
                    check(parsed.RootElement.GetProperty("provider_ticks").GetInt64() == 3);
                    check(parsed.RootElement.GetProperty("diagnostic_ticks").GetInt64() == 5);
                }
                progress.Emit("serialize.start"); progress.Emit("serialize.end"); progress.Emit("write.start"); progress.Emit("write.end");
                progress.FinishRequest(); progress.Emit("group.end");
                bool refused = false;
                try { using (var duplicate = new OwnedProviderProgress(path, "uia", serialize)) { } } catch (IOException) { refused = true; }
                check(refused);
            }
            var lines = File.ReadAllLines(path); check(lines.Length == 10);
            long prior = -1, priorWrite = -1;
            for (int i = 0; i < lines.Length; i++) using (var row = JsonDocument.Parse(lines[i]))
            {
                var element = row.RootElement; long elapsed = element.GetProperty("elapsed_ticks").GetInt64(), writes = element.GetProperty("write_ticks").GetInt64();
                check(element.GetProperty("sequence").GetInt32() == i + 1 && elapsed >= prior && writes >= priorWrite);
                prior = elapsed; priorWrite = writes;
            }
            using (var progress = new OwnedProviderProgress(Path.Combine(directory, "count.jsonl"), "uia", serialize))
            {
                for (int i = 0; i < OwnedProviderProgress.MaxRecords; i++) progress.Emit("group.start");
                bool refused = false; try { progress.Emit("group.start"); } catch (InvalidOperationException) { refused = true; } check(refused);
            }
            string overflow = Path.Combine(directory, "overflow.jsonl");
            using (var progress = new OwnedProviderProgress(overflow, "uia", _ => new string('x', OwnedProviderProgress.MaxBytes)))
            {
                bool refused = false; try { progress.Emit("group.start"); } catch (InvalidOperationException) { refused = true; } check(refused);
                check(new FileInfo(overflow).Length == 0);
            }
            Console.WriteLine("Passed " + checks + " owned progress contracts; generated files only.");
        }
        finally { Directory.Delete(directory, true); }
    }
}
