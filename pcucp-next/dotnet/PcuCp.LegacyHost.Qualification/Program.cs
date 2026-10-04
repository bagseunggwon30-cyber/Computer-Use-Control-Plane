using System.Globalization;
using System.Text;

// Portable proof fixture, never a substitute for the actual Windows NativeHost
// launch gate. All startup, protocol, reducers and effect semantics are linked
// production sources. No acquisition, process dispatch or input provider exists.
Console.OutputEncoding = new UTF8Encoding(false);
var guarded = ParentLifetimeGuard.Extract(args);
ParentLifetimeGuard.Start(guarded.Handle);
args = guarded.Args;
if (args.Length == 0 || args[0] != "legacy-diagnostic-session")
    throw new InvalidOperationException("Qualification fixture supports the diagnostic entry only.");
using var input = LegacySessionInput.Open(Console.OpenStandardInput());
var startup = LegacyExecutionStartup.Read(args.Skip(1).ToArray(), input, "diagnostics");
if (startup.Operation != "release-notes" || !startup.Brief || startup.Authority.AllowLiveControl || startup.Authority.ConfirmSensitive)
    throw new InvalidOperationException("Qualification fixture supports read-only brief release-notes only.");
CultureInfo.CurrentCulture = startup.Culture;
string Text(string name) => startup.Context.GetProperty(name).GetString()!;
var context = new LegacyDiagnosticContext(Text("audit_directory"), Text("cache_directory"), Text("wrapper_log"),
    startup.Context.GetProperty("cli_path").GetString(), Text("changelog_path"), Text("temp_root"), Text("benchmark_schema"), Text("release_schema"));
return new LegacyExecutionSession(input, Console.Out).Run(effects =>
{
    var result = new LegacyDiagnosticCoordinator(new LegacyDiagnosticExecutionAdapter(effects), startup.Rest, context, startup.Brief).Run(startup.Operation);
    return new LegacyExecutionResult(result.Payload, result.Exit, result.JsonDepth, result.Brief, result.EmitJson);
});
