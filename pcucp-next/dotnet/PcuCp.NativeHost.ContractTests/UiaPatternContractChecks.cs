using System.Text;
using System.Text.Json;

internal static class UiaPatternContractChecks
{
    internal static void Run(Action<bool, string> check)
    {
        CommandOptions Options(params string[] extras) => new(new[] { "--allow-live-control", "--element-ref", "ref", "--hwnd", "0x20", "--pid", "42" }.Concat(extras).ToArray());
        void Reject(Action action, string label)
        {
            try { action(); } catch (NativeFailure) { check(true, label); return; }
            check(false, label);
        }
        JsonElement Data(NativeResult result) => JsonSerializer.SerializeToElement(result.Data);
        foreach (var command in UiaPatternRequest.Commands)
        {
            Reject(() => UiaPatternRequest.Parse(command, new CommandOptions([])), $"Read-only {command} parsed");
            var wire = JsonSerializer.Serialize(new { schema = "pcucp.native.request/v1", id = 1, command, args = Array.Empty<string>() });
            Reject(() => NativeSession.Parse(wire, false, 0), $"Read-only session authorized {command}");
            Reject(() => UiaPatternRequest.Parse(command, Options("--coordinate-fallback", "true")), "Fallback flag allowed");
        }
        check(UiaPatternRequest.Parse("uia-toggle", Options()).Command == "uia-toggle", "Toggle parse failed");
        check(UiaPatternRequest.Parse("uia-select", Options()).SelectionMode == "replace", "Default selection must replace");
        foreach (var mode in new[] { "replace", "add", "remove" })
            check(UiaPatternRequest.Parse("uia-select", Options("--selection-mode", mode)).SelectionMode == mode, "Selection mode lost");
        Reject(() => UiaPatternRequest.Parse("uia-select", Options("--selection-mode", "all")), "Unbounded selection allowed");
        foreach (var state in new[] { "expanded", "collapsed" })
            check(UiaPatternRequest.Parse("uia-expand-collapse", Options("--state", state)).State == state, "Expansion state lost");
        Reject(() => UiaPatternRequest.Parse("uia-expand-collapse", Options()), "Expansion without explicit intent accepted");
        Reject(() => UiaPatternRequest.Parse("uia-expand-collapse", Options("--state", "toggle")), "Implicit expansion toggle allowed");
        foreach (var horizontal in UiaPatternRequest.ScrollAmounts)
        foreach (var vertical in UiaPatternRequest.ScrollAmounts)
        {
            if (horizontal == "none" && vertical == "none")
                Reject(() => UiaPatternRequest.Parse("uia-scroll", Options()), "Both-none scrolling allowed");
            else
            {
                var r = UiaPatternRequest.Parse("uia-scroll", Options("--horizontal", horizontal, "--vertical", vertical));
                check(r.Horizontal == horizontal && r.Vertical == vertical, "Scroll amount changed");
            }
        }
        Reject(() => UiaPatternRequest.Parse("uia-scroll", Options("--vertical", "999")), "Arbitrary scroll count allowed");
        Reject(() => UiaPatternRequest.Parse("uia-toggle", Options("--text-b64", "YWJj")), "Text accepted by toggle");
        Reject(() => UiaPatternRequest.Parse("uia-unknown", Options()), "Unknown UIA command accepted");
        foreach (var text in new[] { "", "한글 😀", new string('x', 4096) })
            check(UiaPatternRequest.Parse("uia-set-value", Options("--text-b64", Convert.ToBase64String(Encoding.UTF8.GetBytes(text)))).Text == text, "Valid Unicode value lost");
        foreach (var encoded in new[] { "!bad", "/w==", "AA==", Convert.ToBase64String(Encoding.UTF8.GetBytes(new string('x', 4097))) })
            Reject(() => UiaPatternRequest.Parse("uia-set-value", Options("--text-b64", encoded)), "Malformed/oversize text allowed");

        UiaPatternExecution.RequireObservedState("on", "on");
        check(true, "Matching observed state rejected");
        Reject(() => UiaPatternExecution.RequireObservedState("off", "on"), "State changed since observation allowed");
        Reject(() => UiaPatternExecution.RequireObservedState(null, "on"), "Missing observed state allowed");
        foreach (var command in UiaPatternRequest.Commands)
        {
            var calls = 0;
            var state = "before";
            var validations = 0;
            var ok = UiaPatternExecution.Run(command, new { pid = 42 }, () => validations++, () =>
                new("test-pattern", state, () => { calls++; state = "after"; }, () => state, () => { }));
            check(ok.Status == "ok" && calls == 1 && validations == 3, "Pattern did not validate and dispatch exactly once");
            check(Data(ok).GetProperty("previous_state").GetString() == "before" && Data(ok).GetProperty("observed_state").GetString() == "after", "Pattern state evidence lost");
            check(Data(ok).GetProperty("verification").GetString() == "pattern_state_observed_not_asserted", "Pattern readback overclaims goal verification");
            calls = 0;
            var rejected = UiaPatternExecution.Run(command, new { }, () => throw new NativeFailure("stale", "stale"), () =>
                new("test", null, () => calls++, () => null, () => { }));
            check(rejected.Status == "error" && calls == 0 && !Data(rejected).GetProperty("may_have_acted").GetBoolean(), "Invalid target dispatched");
            rejected = UiaPatternExecution.Run(command, new { }, () => { }, () => throw new NativeFailure("unsupported_pattern", "unsupported"));
            check(rejected.Status == "error" && calls == 0, "Unsupported pattern caused fallback");
            rejected = UiaPatternExecution.Run(command, new { }, () => { }, () =>
                new("test", null, () => calls++, () => null, () => throw new NativeFailure("element_state_changed", "changed")));
            check(rejected.Status == "error" && calls == 0, "Changed state dispatched");
            var partial = UiaPatternExecution.Run(command, new { }, () => { }, () =>
                new("test", "before", () => { calls++; throw new InvalidOperationException("Provider may have acted"); }, () => null, () => { }));
            check(partial.Status == "partial" && calls == 1 && Data(partial).GetProperty("may_have_acted").GetBoolean(), "Provider exception lost uncertainty or replayed");
            calls = 0;
            partial = UiaPatternExecution.Run(command, new { }, () => { }, () =>
                new("test", "before", () => calls++, () => throw new InvalidOperationException("Readback unavailable"), () => { }));
            check(partial.Status == "partial" && calls == 1 && !Data(partial).GetProperty("automatic_retry").GetBoolean(), "Readback failure retried or claimed success");
        }
    }
}
