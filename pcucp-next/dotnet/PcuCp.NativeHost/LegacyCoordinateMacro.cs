using System.Globalization;
using System.Text.Json;

// Fixed macro argv conversion only. No acquisition, paths, shell, or input.
internal static class LegacyCoordinateMacro
{
    internal static object Prepare(JsonElement args)
    {
        var fields = args.EnumerateObject().Select(p => p.Name).ToArray();
        if (fields.Length != 2 || fields.Distinct(StringComparer.Ordinal).Count() != 2 ||
            fields.Any(p => p is not ("name" or "rest")) || !args.TryGetProperty("name", out var name) ||
            name.ValueKind != JsonValueKind.String || !args.TryGetProperty("rest", out var input) ||
            input.ValueKind != JsonValueKind.Array || input.EnumerateArray().Any(p => p.ValueKind != JsonValueKind.String))
            throw CommandOptions.Invalid("Invalid coordinate macro argv.");
        string macro = name.GetString()!; string[] rest = input.EnumerateArray().Select(p => p.GetString()!).ToArray();
        string? Opt(string key) { for (int i = 0; i + 1 < rest.Length; ++i) if (string.Equals(rest[i], key, StringComparison.InvariantCultureIgnoreCase)) return rest[i + 1]; return null; }
        var target = Opt("--target-match") ?? "";
        if (macro is "coord-profile" or "coord-map") { if (target.Length == 0) target = Opt("--match") ?? ""; if (target.Length == 0) target = Opt("--window") ?? ""; }
        bool jsonOnly = rest.Any(p => string.Equals(p, "--json-only", StringComparison.InvariantCultureIgnoreCase));
        if (macro == "hit-test-batch")
        {
            var points = new List<string>();
            for (int i = 0; i + 1 < rest.Length; ++i) if (string.Equals(rest[i], "--point", StringComparison.InvariantCultureIgnoreCase)) points.Add(rest[++i]);
            if (Opt("--points") is { Length: > 0 } raw) points.AddRange(raw.Split(';').Where(p => p.Trim().Length != 0));
            return new { action = "batch", args = new { points, maximum = LegacyTaskFormKernel.LegacyInt(Opt("--max-points")),
                target_hwnd = LegacyTaskFormKernel.LegacyInt(Opt("--target-hwnd")), target_match = Opt("--target-match") }, json_only = false, display_from = "" };
        }
        string? x = Opt("--x"), y = Opt("--y");
        long hwnd = LegacyAppProfileKernel.N(Opt("--target-hwnd"), true);
        if (macro == "coord-profile")
        {
            bool hasPoint = x is not null && y is not null;
            return new { action = "profile", args = new { x = hasPoint ? LegacyTaskFormKernel.LegacyInt(x) : 0,
                y = hasPoint ? LegacyTaskFormKernel.LegacyInt(y) : 0, has_point = hasPoint, target_hwnd = hwnd, target_match = target }, json_only = jsonOnly, display_from = "" };
        }
        if (macro != "coord-map") throw CommandOptions.Invalid("Unknown coordinate macro.");
        string source = Opt("--from") ?? ""; if (source.Length == 0) source = Opt("--mode") ?? ""; if (source.Length == 0) source = "screen";
        string? nx = Opt("--norm-x"), ny = Opt("--norm-y"); bool hasNorm = nx is not null && ny is not null;
        if (!hasNorm && (x is null || y is null)) throw CommandOptions.Invalid("macro coord-map requires --x/--y or --norm-x/--norm-y");
        double Number(string? value) => string.IsNullOrEmpty(value) ? 0 : double.Parse(value, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture);
        return new { action = "map", args = new { source, x = Number(x), y = Number(y), norm_x = hasNorm ? Number(nx) : 0,
            norm_y = hasNorm ? Number(ny) : 0, has_norm = hasNorm, target_hwnd = hwnd, target_match = target }, json_only = jsonOnly, display_from = source };
    }
}
