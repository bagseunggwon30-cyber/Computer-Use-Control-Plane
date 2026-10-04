using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

/// <summary>Pure compatibility classifier; a classification never grants authority.</summary>
internal static class LegacySafetyKernel
{
    private sealed record Rule(string Category, int Weight, string Pattern, string Reason);
    private static readonly Rule[] Rules = [
        new("credentials", 85, "password|passcode|otp|2fa|mfa|api[-_ ]?key|secret|token|private key|비밀번호|암호|인증번호|일회용|토큰|시크릿|api키|api 키", "credential_or_secret_entry"),
        new("payment", 80, "payment|pay now|checkout|purchase|buy|subscribe|billing|credit card|card number|결제|구매|구독|카드|청구|계좌|입금|출금", "payment_or_billing_action"),
        new("destructive", 85, "delete|remove|uninstall|format|wipe|factory reset|reset account|close account|deactivate|cancel subscription|drop database|삭제|제거|초기화|포맷|탈퇴|해지|폐기|영구|복구 불가", "destructive_or_irreversible_action"),
        new("external_send", 55, "send|submit|post|publish|email|mail|telegram|slack|discord|dm|upload|share|발송|전송|제출|게시|공개|업로드|공유|메일|문자|카톡|텔레그램", "external_send_or_publish_action"),
        new("identity_or_privacy", 80, "ssn|social security|passport|driver.?license|id card|resident registration|주민등록|여권|운전면허|신분증|개인정보|민감정보", "identity_or_private_data"),
        new("system_change", 70, "registry|regedit|firewall|permission|admin|administrator|environment variable|system settings|레지스트리|방화벽|권한|관리자|환경변수", "system_or_permission_change"),
        new("app_settings", 50, "settings|preferences|configuration|설정|환경설정|구성", "application_settings_change"),
    ];
    private static string ReadText(JsonElement args, string name, int maximum)
    {
        if (!args.TryGetProperty(name, out var value) || value.ValueKind == JsonValueKind.Null) return string.Empty;
        if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid($"{name} must be a string or null.");
        var result = value.GetString()!;
        if (result.Length > maximum) throw CommandOptions.Invalid($"{name} exceeds its UTF-16-unit limit.");
        return result;
    }
    private static void Fields(JsonElement args, params string[] allowed)
    {
        if (args.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Safety arguments must be an object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var field in args.EnumerateObject())
            if (!names.Add(field.Name) || !allowed.Contains(field.Name)) throw CommandOptions.Invalid("Unknown or duplicate safety argument.");
    }
    internal static string TruncateValue(string? value, int maximum = 180)
    {
        if (maximum is < 0 or > 262144) throw CommandOptions.Invalid("Truncation maximum must be 0..262144 UTF-16 units.");
        if (value is null) return string.Empty;
        return value.Length <= maximum ? value : value[..maximum] + "...";
    }
    internal static object Truncate(JsonElement args)
    {
        Fields(args, "value", "max");
        var value = ReadText(args, "value", 262144);
        var maximum = 180;
        if (args.TryGetProperty("max", out var raw) && (raw.ValueKind != JsonValueKind.Number || !raw.TryGetInt32(out maximum) || maximum is < 0 or > 262144))
            throw CommandOptions.Invalid("max must be 0..262144.");
        return new { value = TruncateValue(value, maximum) };
    }
    internal static object Classify(JsonElement args)
    {
        Fields(args, "text", "macro");
        var raw = ReadText(args, "text", 262144);
        var macro = ReadText(args, "macro", 128);
        var hay = (macro + " " + raw).ToLowerInvariant();
        var categories = new List<object>();
        var matches = new List<object>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var score = 0;
        var maximumWeight = 0;
        void Add(string category, int weight, string pattern, string reason)
        {
            if (seen.Add(category))
            {
                categories.Add(new { category, weight, reason });
                score += weight;
            }
            matches.Add(new { category, pattern, reason });
            maximumWeight = Math.Max(maximumWeight, weight);
        }
        foreach (var rule in Rules)
            if (Regex.IsMatch(hay, rule.Pattern, RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1)))
                Add(rule.Category, rule.Weight, rule.Pattern, rule.Reason);
        // PS switch is case-insensitive. Do not change category insertion or
        // duplicate-weight semantics: registry retains category weight 70 but score 80.
        if (string.Equals(macro, "registry", StringComparison.InvariantCultureIgnoreCase))
            Add("system_change", 80, "macro:registry", "registry_macro");
        else if (string.Equals(macro, "process", StringComparison.InvariantCultureIgnoreCase))
            Add("system_change", 65, "macro:process", "process_control_macro");
        else if (string.Equals(macro, "app-close", StringComparison.InvariantCultureIgnoreCase) &&
            Regex.IsMatch(hay, "--force|force", RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1)))
            Add("destructive", 70, "macro:app-close --force", "forced_app_close");
        else if (string.Equals(macro, "notify", StringComparison.InvariantCultureIgnoreCase))
            Add("external_send", 45, "macro:notify", "notification_macro");
        score = Math.Max(Math.Min(score, 100), maximumWeight);
        var risk = score >= 80 ? "critical" : score >= 65 ? "high" : score >= 45 ? "medium" : score > 0 ? "low" : "none";
        var requires = score >= 45;
        return new
        {
            schema = "cucp.safety-classify/v1", status = "ok", macro, risk_level = risk,
            risk_score = score, requires_explicit_confirmation = requires, blocked_by_default = requires,
            confirmation_flag = "--confirm-sensitive", categories, matches, input_preview = TruncateValue(raw),
            recommended_action = requires ? "Require explicit user confirmation before live control; prefer --dry-run/read-only planning first." :
                "No sensitive-action confirmation required by the local classifier."
        };
    }
}
