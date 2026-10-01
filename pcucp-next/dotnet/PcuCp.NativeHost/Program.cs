using System.IO;
using System.Text;
using System.Text.Json;

Console.OutputEncoding = new UTF8Encoding(false);
try
{
    var startup = ParentLifetimeGuard.Extract(args);
    args = startup.Args;
    ParentLifetimeGuard.Start(startup.Handle);
}
catch (Exception ex)
{
    Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error("startup", "parent_guard_failed", ex.Message), NativeDispatcher.JsonOptions));
    return 2;
}
var command = args.Length > 0 ? args[0].ToLowerInvariant() : "version";
if (command == "serve")
{
    try
    {
        var options = new CommandOptions(args.Skip(1).ToArray());
        options.Allow("--allow-live-control");
        return await NativeSession.RunAsync(Console.OpenStandardInput(), Console.Out,
            options.Has("--allow-live-control"), NativeDispatcher.ExecuteAsync);
    }
    catch (IOException) { return 1; }
    catch (Exception ex)
    {
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command,
            ex is NativeFailure failure ? failure.Code : "native_failure", ex.Message), NativeDispatcher.JsonOptions));
        return 2;
    }
}
var result = await NativeDispatcher.ExecuteAsync(command, args.Skip(1).ToArray());
Console.WriteLine(JsonSerializer.Serialize(result.Payload, NativeDispatcher.JsonOptions));
return result.ExitCode;
