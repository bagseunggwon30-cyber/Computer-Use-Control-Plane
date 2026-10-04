using System.Text.Json;
using System.IO;

// The host supplies operation, original argv and authority once, outside the reply
// stream. Every response is bound to the single outstanding effect sequence number.
// One 48 KiB byte chunk per JSONL frame; no growing transcript or total-workflow cap.
internal sealed class LegacyExecutionSession(TextReader input, TextWriter output) : ILegacyExecutionEffects
{
    private long sequence;
    private bool potentialStateChangeSent;
    private const int ChunkBytes = 49152;
    private static readonly JsonSerializerOptions Options = new() { MaxDepth = 128 };
    private void Frame(string serialized) { output.WriteLine(serialized); output.Flush(); }
    private void Send(string kind, long id, object value, bool mayChangeState = false)
    {
        // Preflight the entire message, including all frame serialization, before
        // any bytes leave this process. The host cannot dispatch a partial value.
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(value, Options);
        var parts = new List<string>();
        for (int offset = 0; offset < bytes.Length; offset += ChunkBytes)
        {
            int length = Math.Min(ChunkBytes, bytes.Length - offset);
            parts.Add(JsonSerializer.Serialize(new { kind = "part", target = kind, id, data = Convert.ToBase64String(bytes, offset, length) }, Options));
        }
        string end = JsonSerializer.Serialize(new { kind = "end", target = kind, id }, Options);
        foreach (string part in parts) Frame(part);
        // Sending the terminator can make host dispatch possible even if its write
        // or flush throws. Earlier encoding/part failures cannot dispatch this effect.
        // A rejected preflight must not consume an ID that the host never received.
        sequence = id;
        if (mayChangeState) potentialStateChangeSent = true;
        Frame(end);
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
        long id = sequence + 1;
        Send("effect", id, new { kind = effect.Kind.ToString(), name = effect.Name, argv = effect.Argv, data = LegacyExecutionWire.Encode(effect.Data),
            live = effect.Live, quiet = effect.Quiet, brief = effect.Brief, confirm_sensitive = effect.ConfirmSensitive }, LegacyExecutionEffectSemantics.MayChangeState(effect));
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
        => Run(effects => new LegacyExecutionCoordinator(effects, authority, rest, brief, cacheSeconds, visionAvailable).Run(operation));

    // Only a trusted host dispatch supplies this factory. Operation names and
    // authority still come from the separate validated startup, never replies.
    internal int Run(Func<ILegacyExecutionEffects, LegacyExecutionResult> operation)
    {
        try
        {
            var result = operation(this);
            Send("complete", sequence + 1, new { payload = LegacyExecutionWire.Encode(result.Payload), exit = result.Exit, json_depth = result.JsonDepth, brief = result.Brief, emit_json = result.EmitJson });
            return result.Exit;
        }
        catch (Exception error)
        {
            // Preserve phase and uncertainty for every failed reply/assembly path.
            // A failure after dispatch must never be mislabeled as startup refusal.
            try { Send("error", sequence + 1, new { message = error.Message, mutation_may_have_occurred = potentialStateChangeSent, automatic_retry = false }); }
            catch (Exception streamError) when (streamError is IOException or ObjectDisposedException) { } // Caller owns uncertainty.
            return 1;
        }
    }
}
