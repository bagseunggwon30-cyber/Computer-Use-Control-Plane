using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

internal static class AppLifecycleContractChecks
{
    internal static async Task RunAsync(Action<bool, string> check)
    {
        void Reject(Action action, string code)
        {
            try { action(); }
            catch (NativeFailure ex) { check(ex.Code == code, $"Expected {code}, got {ex.Code}"); return; }
            throw new Exception($"Expected rejection: {code}");
        }
        async Task RejectAsync(Func<Task<NativeResult>> action, string code)
        {
            try { await action(); }
            catch (NativeFailure ex) { check(ex.Code == code, $"Expected {code}, got {ex.Code}"); return; }
            throw new Exception($"Expected rejection: {code}");
        }
        static string Encode(object value) => Convert.ToBase64String(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value)));
        static CommandOptions Launch(string path = @"C:\Program Files\Example\app.exe", string? encoded = null) =>
            new(encoded is null ? ["--path", path, "--allow-live-control"] : ["--path", path, "--args-b64", encoded, "--allow-live-control"]);
        static CommandOptions Close(int timeout = 1500) =>
            new(["--hwnd", "0xABCD", "--pid", "42", "--timeout-ms", timeout.ToString(System.Globalization.CultureInfo.InvariantCulture), "--allow-live-control"]);
        static JsonElement Data(NativeResult result) => JsonSerializer.SerializeToElement(result.Data);

        check(Marshal.SizeOf<NativeMethods.STARTUPINFO>() == (IntPtr.Size == 8 ? 104 : 68), "STARTUPINFO ABI size mismatch");
        check(Marshal.OffsetOf<NativeMethods.STARTUPINFO>(nameof(NativeMethods.STARTUPINFO.StdInput)).ToInt32() == (IntPtr.Size == 8 ? 80 : 56), "STARTUPINFO handle layout mismatch");
        check(Marshal.SizeOf<NativeMethods.PROCESS_INFORMATION>() == (IntPtr.Size == 8 ? 24 : 16), "PROCESS_INFORMATION ABI size mismatch");
        foreach (var valid in new[] { @"C:\Windows\app.exe", "C:/Program Files/App.EXE", @"\\server\share\dir\app.exe" })
            check(AppLaunchSpec.IsAbsoluteExecutablePath(valid), $"Absolute executable rejected: {valid}");
        foreach (var invalid in new[] { "app.exe", @".\app.exe", @"C:app.exe", @"\app.exe", "/tmp/app.exe", "https://example/app.exe", @"C:\run.cmd", @"C:\run.bat", @"C:\file.lnk", @"C:\file.exe:stream.exe", @"\\?\C:\app.exe", @"\\.\C:\app.exe", @"\\server\app.exe", "C:\\a\0.exe", "C:\\a\n.exe", @"C:\a|b.exe", @"C:\a*.exe" })
            Reject(() => AppLaunchSpec.Read(Launch(invalid), _ => true), "invalid_arguments");
        Reject(() => AppLaunchSpec.Read(Launch(), _ => false), "executable_not_found");
        var values = new[] { "", "a b", "한글", "--allow-live-control", "x&y|z>out", "quoted\"word", @"C:\path with space\" };
        var plan = AppLaunchSpec.Read(Launch(encoded: Encode(values)), _ => true);
        check(plan.Arguments.SequenceEqual(values), "Launch argument vector was reinterpreted");
        check(AppLaunchSpec.Read(Launch(), _ => true).Arguments.Count == 0, "Omitted vector was not empty");
        foreach (var invalid in new[] { "not base64!", Convert.ToBase64String([0xff]), Encode("string"), Encode(new object[] { 1 }), Encode(new string?[] { null }), Encode(new[] { "has\0nul" }), Encode(new[] { new string('x', 8193) }), Encode(Enumerable.Repeat("", 129).ToArray()), Encode(Enumerable.Repeat(new string('x', 8192), 4).ToArray()) })
            Reject(() => AppLaunchSpec.Read(Launch(encoded: invalid), _ => true), "invalid_arguments");
        check(AppLaunchSpec.QuoteArgument("") == "\"\"", "Empty argument quoting failed");
        check(AppLaunchSpec.QuoteArgument("a b") == "\"a b\"", "Space argument quoting failed");
        check(AppLaunchSpec.QuoteArgument("a\"b") == "\"a\\\"b\"", "Literal quote escaping failed");
        check(AppLaunchSpec.QuoteArgument("a\\") == "\"a\\\\\"", "Trailing slash escaping failed");
        check(SplitWindowsCommandLine(plan.CommandLine()).SequenceEqual(new[] { plan.Path }.Concat(values)), "Argument quoting did not round-trip");
        var random = new Random(1631);
        const string chars = "ab \\\"\t&|한글";
        for (var i = 0; i < 400; i++)
        {
            var vector = Enumerable.Range(0, random.Next(1, 10)).Select(_ => new string(Enumerable.Range(0, random.Next(0, 80)).Select(_ => chars[random.Next(chars.Length)]).ToArray())).ToArray();
            var spec = new AppLaunchSpec(@"C:\Apps\Test app.exe", vector);
            check(SplitWindowsCommandLine(spec.CommandLine()).SequenceEqual(new[] { spec.Path }.Concat(vector)), "Random Windows argv round-trip failed");
        }

        var platform = new FakePlatform();
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-launch", new CommandOptions(["--path", @"C:\app.exe"]), platform), "live_control_required");
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-close", new CommandOptions(["--hwnd", "0xABCD", "--pid", "42"]), platform), "live_control_required");
        check(platform.Calls.Count == 0, "Missing authority reached platform calls");
        foreach (var invalid in new[]
        {
            new[] { "--hwnd", "0xABCD", "--allow-live-control" },
            new[] { "--pid", "42", "--allow-live-control" },
            new[] { "--hwnd", "0x0", "--pid", "42", "--allow-live-control" },
            new[] { "--hwnd", "0xABCD", "--pid", "0", "--allow-live-control" },
            new[] { "--hwnd", "0xABCD", "--pid", "42", "--force", "true", "--allow-live-control" }
        }) await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-close", new CommandOptions(invalid), platform), "invalid_arguments");
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-close", Close(-1), platform), "invalid_arguments");
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-close", Close(10001), platform), "invalid_arguments");
        check(platform.Calls.Count == 0, "Malformed close reached platform calls");

        var launched = await AppLifecycleActions.ExecuteAsync("app-launch", Launch(encoded: Encode(values)), platform);
        check(platform.Calls.SequenceEqual(new[] { "file-exists", "launch-access", "launch" }), "Launch did not validate before mutation");
        check(platform.LaunchSpec!.Arguments.SequenceEqual(values), "Launch platform received a changed argument vector");
        check(launched.Status == "ok" && Data(launched).GetProperty("pid").GetInt32() == 73 && Data(launched).GetProperty("verification").GetString() == "not_verified", "Launch incorrectly claimed app readiness");
        platform = new FakePlatform { AccessError = "secure_desktop_unavailable" };
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-launch", Launch(), platform), "secure_desktop_unavailable");
        check(!platform.Calls.Contains("launch"), "Launch proceeded after denied access");

        platform = new FakePlatform { CloseAt = 100 };
        var closed = await AppLifecycleActions.ExecuteAsync("app-close", Close(120), platform);
        check(closed.Status == "ok" && Data(closed).GetProperty("closed").GetBoolean() && !Data(closed).GetProperty("still_open").GetBoolean(), "Closed window was not confirmed");
        check(Data(closed).GetProperty("verification").GetString() == "window_closed", "Close incorrectly described verification");
        check(platform.Calls.Take(3).SequenceEqual(new[] { "read-target", "close-access", "request-close" }) && platform.Calls.Count(x => x == "request-close") == 1, "Close was unguarded or repeated");
        check(platform.Delays.SequenceEqual(new[] { 50, 50 }), "Close did not stop when the window disappeared");
        platform = new FakePlatform();
        var stillOpen = await AppLifecycleActions.ExecuteAsync("app-close", Close(120), platform);
        check(stillOpen.Status == "partial" && stillOpen.Errors.Single().Code == "app_still_open", "Open target presented as success");
        check(!Data(stillOpen).GetProperty("closed").GetBoolean() && Data(stillOpen).GetProperty("still_open").GetBoolean(), "Timeout did not preserve still-open state");
        check(platform.ElapsedMilliseconds == 120 && platform.Delays.SequenceEqual(new[] { 50, 50, 20 }), "Close exceeded its bounded polling budget");
        check(platform.Calls.Count(x => x == "request-close") == 1, "Timeout retried close");
        platform = new FakePlatform();
        stillOpen = await AppLifecycleActions.ExecuteAsync("app-close", Close(0), platform);
        check(stillOpen.Status == "partial" && platform.Delays.Count == 0, "Zero timeout waited or claimed success");
        platform = new FakePlatform { CloseAt = 0 };
        closed = await AppLifecycleActions.ExecuteAsync("app-close", Close(), platform);
        check(closed.Status == "ok" && platform.Delays.Count == 0 && platform.Calls.Count(x => x == "request-close") == 1, "Immediate closure waited or repeated dispatch");
        platform = new FakePlatform();
        stillOpen = await AppLifecycleActions.ExecuteAsync("app-close", new CommandOptions(["--hwnd", "0xABCD", "--pid", "42", "--allow-live-control"]), platform);
        check(Data(stillOpen).GetProperty("timeout_ms").GetInt32() == 1500 && platform.ElapsedMilliseconds == 1500, "Default close timeout changed");
        platform = new FakePlatform { AccessError = "elevation_required" };
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-close", Close(), platform), "elevation_required");
        check(!platform.Calls.Contains("request-close"), "Close proceeded after denied access");
        platform = new FakePlatform { CloseError = "geometry_changed" };
        await RejectAsync(() => AppLifecycleActions.ExecuteAsync("app-close", Close(), platform), "geometry_changed");
        check(platform.Delays.Count == 0 && !platform.Calls.Contains("is-open"), "Failed close was polled as dispatched");

        foreach (var command in new[] { "app-launch", "app-close", "APP-LAUNCH", "APP-CLOSE" })
        {
            string Request(bool withFlag) => JsonSerializer.Serialize(new { schema = "pcucp.native.request/v1", id = 1, command, args = withFlag ? new[] { "--allow-live-control" } : Array.Empty<string>() });
            Reject(() => NativeSession.Parse(Request(false), false, 0), "live_control_required");
            Reject(() => NativeSession.Parse(Request(true), false, 0), "live_control_required");
            check(NativeSession.Parse(Request(true), true, 0).Command == command.ToLowerInvariant(), "Approved lifecycle request rejected by session");
        }
    }

    // Independent argv parser for the documented Windows backslash/quote rules. No OS process is created.
    private static IReadOnlyList<string> SplitWindowsCommandLine(string command)
    {
        var result = new List<string>();
        var i = 0;
        while (i < command.Length)
        {
            while (i < command.Length && command[i] is ' ' or '\t') i++;
            if (i == command.Length) break;
            var value = new StringBuilder();
            var quoted = false;
            while (i < command.Length && (quoted || command[i] is not (' ' or '\t')))
            {
                var slashes = 0;
                while (i < command.Length && command[i] == '\\') { slashes++; i++; }
                if (i < command.Length && command[i] == '"')
                {
                    value.Append('\\', slashes / 2);
                    if (slashes % 2 == 0) quoted = !quoted;
                    else value.Append('"');
                    i++;
                }
                else
                {
                    value.Append('\\', slashes);
                    if (i < command.Length && (quoted || command[i] is not (' ' or '\t'))) value.Append(command[i++]);
                }
            }
            result.Add(value.ToString());
        }
        return result;
    }

    private sealed class FakePlatform : IAppLifecyclePlatform
    {
        internal List<string> Calls { get; } = [];
        internal List<int> Delays { get; } = [];
        internal AppLaunchSpec? LaunchSpec { get; private set; }
        internal string? AccessError { get; init; }
        internal string? CloseError { get; init; }
        internal long CloseAt { get; init; } = long.MaxValue;
        public long ElapsedMilliseconds { get; private set; }
        public bool FileExists(string path) { Calls.Add("file-exists"); return true; }
        public void RequireLaunchAccess() { Calls.Add("launch-access"); RequireAccess(); }
        public int Launch(AppLaunchSpec spec) { Calls.Add("launch"); LaunchSpec = spec; return 73; }
        public IAppCloseTarget ReadCloseTarget(CommandOptions options) { Calls.Add("read-target"); return new FakeTarget(this); }
        public Task DelayAsync(int milliseconds) { Delays.Add(milliseconds); ElapsedMilliseconds += milliseconds; return Task.CompletedTask; }
        private void RequireAccess() { if (AccessError is not null) throw new NativeFailure(AccessError, "Simulated access refusal"); }
        private sealed class FakeTarget(FakePlatform owner) : IAppCloseTarget
        {
            public object Identity => new { hwnd = "0xABCD", pid = 42 };
            public void RequireAccess() { owner.Calls.Add("close-access"); owner.RequireAccess(); }
            public void RequestClose()
            {
                owner.Calls.Add("request-close");
                if (owner.CloseError is not null) throw new NativeFailure(owner.CloseError, "Simulated dispatch refusal");
            }
            public bool IsOpen { get { owner.Calls.Add("is-open"); return owner.ElapsedMilliseconds < owner.CloseAt; } }
        }
    }
}
