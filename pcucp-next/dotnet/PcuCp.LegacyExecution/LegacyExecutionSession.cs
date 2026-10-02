using System.Text.Json;
using System.IO;

// The host supplies operation, original argv and authority once, outside the reply
// stream. Every response is bound to the single outstanding effect sequence number.
// One 48 KiB byte chunk per JSONL frame; no growing transcript or total-workflow cap.
internal sealed class LegacyExecutionSession(TextReader input, TextWriter output) : ILegacyExecutionEffects
{
    private long sequence;
    private bool liveEffectSent;
    private const int ChunkBytes = 49152;
    private static readonly JsonSerializerOptions Options = new() { MaxDepth = 128 };
    private void Frame(object value) { output.WriteLine(JsonSerializer.Serialize(value, Options)); output.Flush(); }
    private void Send(string kind, long id, object value)
    {
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(value, Options);
        for (int offset = 0; offset < bytes.Length; offset += ChunkBytes)
        {
            int length = Math.Min(ChunkBytes, bytes.Length - offset);
            Frame(new { kind = "part", target = kind, id, data = Convert.ToBase64String(bytes, offset, length) });
        }
        Frame(new { kind = "end", target = kind, id });
    }
    private string ReadReplyFrame()
    {
        var line = new System.Text.StringBuilder();
        while (true)
        {
            int next = input.Read();
            if (next < 0) throw new LegacyExecutionProtocolException("Execution effect reply stream closed; no mutation is retried.");
            if (next == '\n') return line.ToString().TrimEnd('\r');
            if (line.Length == 66000) throw new LegacyExecutionProtocolException("Execution reply frame exceeds 66000 characters.");
            line.Append((char)next);
        }
    }
    public JsonElement Invoke(LegacyExecutionEffect effect)
    {
        long id = ++sequence;
        if (effect.Live) liveEffectSent = true;
        Send("effect", id, new { kind = effect.Kind.ToString(), name = effect.Name, argv = effect.Argv, data = LegacyExecutionWire.Encode(effect.Data),
            live = effect.Live, quiet = effect.Quiet, brief = effect.Brief, confirm_sensitive = effect.ConfirmSensitive });
        using var buffer = new MemoryStream();
        while (true)
        {
            string line = ReadReplyFrame();
            using var document = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 8 }); var frame = document.RootElement;
            var names = frame.ValueKind == JsonValueKind.Object ? frame.EnumerateObject().Select(p => p.Name).ToArray() : [];
            if (names.Distinct(StringComparer.Ordinal).Count() != names.Length || names.Any(n => n is not ("kind" or "id" or "data")) ||
                frame.ValueKind != JsonValueKind.Object || !frame.TryGetProperty("id", out var frameId) || frameId.ValueKind != JsonValueKind.Number || !frameId.TryGetInt64(out long observedId) || observedId != id ||
                !frame.TryGetProperty("kind", out var frameKind) || frameKind.ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("Execution reply is not bound to the outstanding effect.");
            if (frameKind.GetString() == "end") { if (names.Length != 2) throw new LegacyExecutionProtocolException("Unexpected terminal reply fields."); break; }
            if (frameKind.GetString() != "part" || names.Length != 3 || !frame.TryGetProperty("data", out var data) || data.ValueKind != JsonValueKind.String)
                throw new LegacyExecutionProtocolException("Invalid execution reply chunk.");
            byte[] bytes;
            try { bytes = Convert.FromBase64String(data.GetString()!); } catch (FormatException) { throw new LegacyExecutionProtocolException("Invalid execution reply encoding."); }
            if (bytes.Length > ChunkBytes) throw new LegacyExecutionProtocolException("Execution reply chunk exceeds 48 KiB; split the same value into more chunks.");
            buffer.Write(bytes);
        }
        using var reply = JsonDocument.Parse(buffer.ToArray(), new JsonDocumentOptions { MaxDepth = 128 }); var envelope = reply.RootElement;
        var fields = envelope.ValueKind == JsonValueKind.Object ? envelope.EnumerateObject().Select(p => p.Name).ToArray() : [];
        if (fields.Distinct(StringComparer.Ordinal).Count() != fields.Length || envelope.ValueKind != JsonValueKind.Object || !envelope.TryGetProperty("state", out var state) || state.ValueKind != JsonValueKind.String)
            throw new LegacyExecutionProtocolException("Invalid execution reply envelope.");
        if (state.GetString() == "error" && fields.Length is 2 or 3 && envelope.TryGetProperty("message", out var message) && message.ValueKind == JsonValueKind.String)
        {
            bool uncertain = false;
            if (fields.Length == 3)
            {
                if (!envelope.TryGetProperty("mutation_may_have_occurred", out var mutation) || mutation.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                    throw new LegacyExecutionProtocolException("Invalid mutation uncertainty metadata.");
                uncertain = mutation.GetBoolean();
            }
            throw new LegacyExecutionEffectException(message.GetString()!, uncertain);
        }
        if (fields.Length != 2 || state.GetString() != "ok" || !envelope.TryGetProperty("value", out var value)) throw new LegacyExecutionProtocolException("Invalid execution reply state.");
        return LegacyExecutionWire.Decode(value);
    }
    internal int Run(string operation, string[] rest, LegacyExecutionAuthority authority, bool brief = false, int cacheSeconds = 5, bool visionAvailable = false)
    {
        try
        {
            var result = new LegacyExecutionCoordinator(this, authority, rest, brief, cacheSeconds, visionAvailable).Run(operation);
            Send("complete", ++sequence, new { payload = LegacyExecutionWire.Encode(result.Payload), exit = result.Exit, json_depth = result.JsonDepth, brief = result.Brief, emit_json = result.EmitJson });
            return result.Exit;
        }
        catch (Exception error)
        {
            // Preserve phase and uncertainty for every failed reply/assembly path.
            // A failure after dispatch must never be mislabeled as startup refusal.
            try { Send("error", ++sequence, new { message = error.Message, mutation_may_have_occurred = liveEffectSent, automatic_retry = false }); }
            catch (Exception streamError) when (streamError is IOException or ObjectDisposedException) { } // Caller owns uncertainty.
            return 1;
        }
    }
}
