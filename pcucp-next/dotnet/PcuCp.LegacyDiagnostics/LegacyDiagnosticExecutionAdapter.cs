using System.Text.Json;

// Reuses the already qualified sequence-bound execution session and tagged codec.
// This is a descriptor adapter, not another shell/process/wire implementation.
internal sealed class LegacyDiagnosticExecutionAdapter(ILegacyExecutionEffects effects) : ILegacyDiagnosticEffects
{
    public JsonElement Invoke(LegacyDiagnosticEffect effect)
    {
        try
        {
            return effects.Invoke(new(LegacyExecutionEffectKind.Diagnostic, effect.Kind.ToString(), effect.Argv,
                JsonSerializer.SerializeToElement(new { name = effect.Name, value = effect.Data })));
        }
        catch (LegacyExecutionEffectException e)
        {
            if (e.MutationMayHaveOccurred) throw new LegacyExecutionProtocolException("Diagnostic owned-state effect outcome is uncertain; automatic retry is disabled.");
            throw new LegacyDiagnosticEffectException(e.Message);
        }
    }
}
