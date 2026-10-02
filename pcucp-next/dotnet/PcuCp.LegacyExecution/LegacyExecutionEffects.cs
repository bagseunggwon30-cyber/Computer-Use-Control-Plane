using System.Text.Json;

// Effects are capabilities supplied by the trusted entry point, never by a plan.
// There is deliberately no process, shell, filesystem, desktop or network API here.
internal enum LegacyExecutionEffectKind
{
    WorkflowPlan, Child, Native, LocalMacro, CdpPort, HistoryRead, HistoryAppend,
    TrajectoryAppend, Sleep, Clock, Timestamp, CachePath, FileExists, RemoveFile, SendEscape, Console
}
internal sealed record LegacyExecutionAuthority(bool AllowLiveControl, bool ConfirmSensitive);
internal sealed record LegacyExecutionEffect(
    LegacyExecutionEffectKind Kind, string Name, string[] Argv, JsonElement Data,
    bool Live = false, bool Quiet = false, bool Brief = false, bool ConfirmSensitive = false);
internal interface ILegacyExecutionEffects
{
    JsonElement Invoke(LegacyExecutionEffect effect);
}
internal sealed record LegacyExecutionResult(JsonElement Payload, int Exit, int JsonDepth, string? Brief, bool EmitJson = true);

// Reply failures preserve which operations can catch them. Policy/transport failures
// are not ordinary legacy failures and are never swallowed by fallback catches.
internal sealed class LegacyExecutionEffectException(string message, bool mutationMayHaveOccurred = false) : Exception(message)
{
    internal bool MutationMayHaveOccurred { get; } = mutationMayHaveOccurred;
}
// A failed observation after possible input cannot enter a legacy read fallback.
internal sealed class LegacyExecutionPostDispatchException(string message) : Exception(message);
internal sealed class LegacyExecutionUncertainException(LegacyExecutionEffect effect, JsonElement reply) : Exception("A mutation may have occurred; no fallback or retry was attempted.")
{
    internal LegacyExecutionEffect Effect { get; } = effect;
    internal JsonElement Reply { get; } = reply.Clone();
}
