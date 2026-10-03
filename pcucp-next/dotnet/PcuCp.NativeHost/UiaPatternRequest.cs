using System.Text;

/// <summary>Pure argument contract shared by provider code and platform-neutral tests.</summary>
internal sealed record UiaPatternRequest(string Command, string? Text = null, string? SelectionMode = null,
    string? State = null, string Horizontal = "none", string Vertical = "none")
{
    internal static readonly string[] Commands = ["uia-invoke", "uia-set-value", "uia-toggle", "uia-select", "uia-expand-collapse", "uia-scroll"];
    internal static readonly string[] ScrollAmounts = ["none", "small-increment", "large-increment", "small-decrement", "large-decrement"];
    internal static UiaPatternRequest Parse(string command, CommandOptions options)
    {
        string[] extra = command switch
        {
            "uia-invoke" or "uia-toggle" => [], "uia-set-value" => ["--text-b64"],
            "uia-select" => ["--selection-mode"], "uia-expand-collapse" => ["--state"],
            "uia-scroll" => ["--horizontal", "--vertical"],
            _ => throw CommandOptions.Invalid("Unknown UIA pattern action.")
        };
        options.Allow(new[] { "--hwnd", "--pid", "--element-ref", "--allow-live-control",
            "--expected-x", "--expected-y", "--expected-width", "--expected-height" }.Concat(extra).ToArray());
        if (!options.Has("--allow-live-control")) throw new NativeFailure("live_control_required", "UIA actions require live control.");
        if (command == "uia-set-value")
        {
            var encoded = options.Required("--text-b64");
            if (encoded.Length > 24000) throw CommandOptions.Invalid("Encoded value is too long.");
            string text;
            try { text = new UTF8Encoding(false, true).GetString(Convert.FromBase64String(encoded)); }
            catch (Exception ex) when (ex is FormatException or DecoderFallbackException) { throw CommandOptions.Invalid("Invalid UTF-8/base64 value."); }
            if (text.Length > 4096 || text.Contains('\0')) throw CommandOptions.Invalid("Value must be at most 4096 UTF-16 units without NUL.");
            return new(command, Text: text);
        }
        if (command == "uia-select")
        {
            var mode = options.Get("--selection-mode") ?? "replace";
            if (mode is not ("replace" or "add" or "remove")) throw CommandOptions.Invalid("Selection mode must be replace, add or remove.");
            return new(command, SelectionMode: mode);
        }
        if (command == "uia-expand-collapse")
        {
            var state = options.Required("--state");
            if (state is not ("expanded" or "collapsed")) throw CommandOptions.Invalid("State must be expanded or collapsed.");
            return new(command, State: state);
        }
        if (command == "uia-scroll")
        {
            var horizontal = options.Get("--horizontal") ?? "none";
            var vertical = options.Get("--vertical") ?? "none";
            if (!ScrollAmounts.Contains(horizontal) || !ScrollAmounts.Contains(vertical) || (horizontal == "none" && vertical == "none"))
                throw CommandOptions.Invalid("Choose at least one non-none bounded UIA scroll amount.");
            return new(command, Horizontal: horizontal, Vertical: vertical);
        }
        return new(command);
    }
}

internal sealed record PreparedUiaAction(string Method, object? Before, Action Dispatch,
    Func<object?> ReadAfter, Action ValidateState);

/// <summary>One dispatch maximum; neither an exception nor failed readback permits fallback.</summary>
internal static class UiaPatternExecution
{
    internal static void RequireObservedState(object? observed, object? current)
    {
        if (observed is null || !Equals(observed, current))
            throw new NativeFailure("stale_element_state", "UIA pattern state changed since observation; observe again.");
    }

    internal static NativeResult Run(string command, object target, Action validate, Func<PreparedUiaAction> prepare)
    {
        var attempted = false;
        PreparedUiaAction? action = null;
        try
        {
            validate();
            action = prepare();
            validate();
            action.ValidateState();
            validate(); // State getters can block or let foreground/geometry change.
            attempted = true; // Provider calls can have effects before throwing.
            action.Dispatch();
            var after = action.ReadAfter();
            return NativeResult.Ok(command, new { target, method = action.Method, previous_state = action.Before,
                observed_state = after, dispatched = true, may_have_acted = true, automatic_retry = false,
                verification = after is null ? "not_verified" : "pattern_state_observed_not_asserted" });
        }
        catch (Exception ex)
        {
            return new NativeResult("pcucp.native/v1", attempted ? "partial" : "error", command,
                new { target, method = action?.Method, previous_state = action?.Before, may_have_acted = attempted, automatic_retry = false },
                [new NativeError(ex is NativeFailure nf ? nf.Code : "uia_provider_error", ex.Message)]);
        }
    }
}
