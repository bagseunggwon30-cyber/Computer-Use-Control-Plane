// Startup-only option interpretation. Plan and reply data must never call this
// to mint new authority. Values that spell a switch remain option values.
internal static class LegacyExecutionConsent
{
    private static readonly HashSet<string> ValueOptions = new(StringComparer.InvariantCultureIgnoreCase)
    {
        "--action", "--after", "--ambiguity-window", "--app", "--app-args", "--args", "--baseline", "--before",
        "--button", "--cache-ttl", "--cdp-page-match", "--cdp-port", "--click-inset", "--click-label",
        "--click-refine", "--click-x", "--click-y", "--command", "--crop-size", "--describe", "--expr",
        "--expr-b64", "--failed-reason", "--failed-step", "--field", "--file", "--from", "--height",
        "--history-tolerance", "--hold-ms", "--id", "--idle-timeout-ms", "--ignore-region", "--interval-ms",
        "--iters", "--keep-latest", "--keys", "--label", "--language", "--last", "--limit", "--lines", "--macro",
        "--match", "--match-window", "--max-attempts", "--max-bytes", "--max-candidates", "--max-commands",
        "--max-cycles", "--max-files", "--max-mb", "--max-phase-ms", "--max-points", "--max-size", "--max-steps",
        "--micro-radius", "--micro-step", "--min-confidence", "--min-score", "--min-size", "--mode", "--model",
        "--name", "--near-radius", "--near-x", "--near-y", "--norm-x", "--norm-y", "--objective",
        "--observe-match", "--ocr-language", "--ocr-match", "--ocr-max-candidates", "--offset-x", "--offset-y",
        "--older-than-minutes", "--open-app", "--out", "--out-path", "--page-match", "--path", "--pid", "--point",
        "--point-cache-ttl", "--point-radius", "--point-step", "--points", "--policy", "--port", "--pre-shortcut",
        "--precision-radius", "--precision-step", "--provider", "--radius", "--refine", "--region",
        "--retry-delay-ms", "--retry-failed-step", "--retry-on-no-change", "--role", "--sample-ms", "--samples",
        "--screenshot", "--selector", "--send-label", "--set", "--settle-ms", "--shortcut", "--since",
        "--since-minutes", "--step", "--target-hwnd", "--target-match", "--text", "--threshold", "--timeout-ms",
        "--title", "--type-text", "--until-label", "--value", "--verify-after-label", "--verify-label",
        "--verify-label-after-step", "--verify-label-interval-ms", "--verify-label-timeout-ms",
        "--verify-label-window", "--verify-match", "--verify-timeout-ms", "--verify-title", "--verify-wait-ms",
        "--verify-window", "--version", "--wait-change-ms", "--wait-ms", "--wait-timeout-ms", "--wait-title",
        "--warn-fast-ms", "--width", "--window", "--x", "--y"
    };
    internal static bool HasStandaloneConfirmation(IEnumerable<string?> originalArgv)
    {
        bool value = false;
        foreach (var token in originalArgv)
        {
            if (value) { value = false; continue; }
            if (string.Equals(token, "--confirm-sensitive", StringComparison.InvariantCultureIgnoreCase)) return true;
            if (token is not null && ValueOptions.Contains(token)) value = true;
        }
        return false;
    }
}
