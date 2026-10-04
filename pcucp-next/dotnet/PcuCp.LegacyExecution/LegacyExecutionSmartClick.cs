using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult SmartClick()
    {
        Live("macro smart-click requires -AllowLiveControl");
        string? label = V("--label"), match = V("--match"), role = V("--role"), verifyLabel = V("--verify-label"), language = V("--ocr-language");
        int timeout = I(V("--verify-timeout-ms")), wait = I(V("--verify-wait-ms")), retries = I(V("--retry-on-no-change")), candidates = I(V("--ocr-max-candidates")), port = I(V("--cdp-port"));
        bool vision = F("--allow-vision"), mouse = F("--allow-mouse-fallback"), noOcr = F("--no-ocr"), verifyScreen = F("--verify-screen-changed"), noHistory = F("--no-history");
        bool precision = F("--precision-points") || F("--point-plan"), cdp = !F("--no-cdp") && (F("--allow-cdp") || Has(V("--cdp-page-match")) || Has(V("--cdp-port")));
        string ocrMatch = Has(V("--ocr-match")) ? V("--ocr-match")! : "contains";
        string? radiusRaw = Has(V("--precision-radius")) ? V("--precision-radius") : V("--point-radius"), stepRaw = Has(V("--precision-step")) ? V("--precision-step") : V("--point-step"), ttlRaw = Has(V("--point-cache-ttl")) ? V("--point-cache-ttl") : V("--cache-ttl");
        if (!Has(label)) throw CommandOptions.Invalid("macro smart-click requires --label");
        if (timeout <= 0) timeout = 3000; if (wait <= 0) wait = 500; if (retries < 0) retries = 0; if (candidates <= 0) candidates = 4; candidates = Math.Min(8, candidates); if (port <= 0) port = 9222;
        int radius = Math.Clamp(Has(radiusRaw) ? I(radiusRaw) : 6, 0, 64), step = Has(stepRaw) ? I(stepRaw) : 2, ttl = Math.Max(0, Has(ttlRaw) ? I(ttlRaw) : cacheSeconds);
        if (step <= 0) step = 2; step = Math.Min(16, step);
        JsonElement hint = Null;
        if (!noHistory) { try { hint = Effect(LegacyExecutionEffectKind.HistoryRead, argv: [label!, match ?? "", "5"]); } catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { } }
        if (T(hint) && !F("--prefer-history") && new[] { "uia_precision_point", "fusion_uia_invoke", "fusion_coord", "ocr_text", "vision_precise" }.Any(h => Eq(hint, h))) hint = Null;
        bool Stage(params string[] names) => !T(hint) || names.Any(n => Eq(hint, n));
        string strategy = "", line = ""; int rc = 1;
        Start("total"); string? before = null, after = null; JsonElement region = Null;
        List<string> LabelArgs(string action) { var a = new List<string> { "-Action", action, "-Label", label! }; if (Has(match)) a.AddRange(["-Match", match!]); if (Has(role)) a.AddRange(["-Role", role!]); return a; }
        List<string> OcrArgs(string action) { var a = new List<string> { "-Action", action, "-OcrText", label!, "-OcrMatch", ocrMatch, "-OcrMaxCandidates", candidates.ToString() }; if (Has(match)) a.AddRange(["-Match", match!]); if (Has(language)) a.AddRange(["-OcrLanguage", language!]); return a; }
        JsonElement Click(int x, int y) { var a = new List<string> { "-Action", "click", "-X", x.ToString(), "-Y", y.ToString(), "-Button", "left", "-ClickRefine", "uia-safe" }; if (Has(match)) a.AddRange(["-TargetMatch", match!]); return Parsed(Native(a.ToArray())); }
        string Path(string prefix) => S(Effect(LegacyExecutionEffectKind.CachePath, prefix, data: Effect(LegacyExecutionEffectKind.Timestamp, "HHmmss-fff")));
        JsonElement Screenshot(string path) => Parsed(Native("-Action", "screenshot", "-OutPath", path, "-ScreenshotX", S(P(region, "x")), "-ScreenshotY", S(P(region, "y")), "-ScreenshotW", S(P(region, "width")), "-ScreenshotH", S(P(region, "height"))));
        bool Exists(string path) => T(Effect(LegacyExecutionEffectKind.FileExists, data: path));
        void Remove(string path) => Effect(LegacyExecutionEffectKind.RemoveFile, data: path);
        void History(string selected, bool success) { if (!noHistory) Effect(LegacyExecutionEffectKind.HistoryAppend, argv: [label!, match ?? "", selected], data: D("success", success, "elapsed_ms", Elapsed("total"))); }
        LegacyExecutionResult Partial(string? text, bool always = false) => new(Null, 2, 0, brief || always ? text : null, false);
        if (verifyScreen)
        {
            try
            {
                var fg = Parsed(Native("-Action", "focused")); if (T(fg) && T(P(fg, "foreground"))) { var r = P(P(fg, "foreground"), "rect"); region = J(D("x", I(P(r, "x")), "y", I(P(r, "y")), "width", I(P(r, "width")), "height", I(P(r, "height")))); }
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { }
            if (!T(region)) verifyScreen = false;
            else
            {
                before = Path("smartclick-before"); if (!Eq(P(Screenshot(before), "status"), "ok")) { verifyScreen = false; if (Exists(before)) Remove(before); before = null; }
            }
        }
        if (rc != 0 && Stage("cdp_smart_click") && cdp)
        {
            try
            {
                if (T(Effect(LegacyExecutionEffectKind.CdpPort, argv: [port.ToString(), "120"])))
                {
                    var a = new List<string> { "-Action", "cdp-smart-click", "-CdpText", label!, "-CdpPort", port.ToString() };
                    if (Has(V("--cdp-page-match"))) a.AddRange(["-CdpPageMatch", V("--cdp-page-match")!]); else if (Has(match)) a.AddRange(["-CdpPageMatch", match!]);
                    var r = Parsed(Native(a.ToArray())); if (Eq(P(r, "status"), "ok")) { strategy = "cdp_smart_click"; rc = 0; line = $"ok smart-click '{label}' strategy=cdp_smart_click matched='{S(P(r, "matched_text"))}' score={S(P(r, "score"))} tag={S(P(r, "tag_name"))} mouse_moved=False"; }
                }
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { }
        }
        if (rc != 0 && Stage("uia_pattern"))
        {
            var r = Parsed(Native(LabelArgs("uia-invoke").ToArray()));
            if (Eq(P(r, "status"), "ok")) { strategy = "uia_pattern"; rc = 0; line = $"ok smart-click '{label}' strategy=uia_pattern method={S(P(r, "method"))} mouse_moved=False"; }
            else if (Eq(P(r, "reason"), "low_confidence_match") && !T(hint))
            {
                // Original emits this text even in JSON mode and before history.
                var text = $"partial smart-click '{label}' low_confidence score={S(P(r, "score"))} strategy=stopped";
                Effect(LegacyExecutionEffectKind.Console, data: text); History("uia_pattern", false); return new(Null, 2, 0, null, false);
            }
        }
        if (rc != 0 && Stage("uia_coord", "uia_precision_point") && mouse)
        {
            bool attempted = false;
            if (precision)
            {
                try
                {
                    var r = Parsed(Native(LabelArgs("uia-find").ToArray())); var top = P(r, "top"); var point = P(top, "click_point");
                    if (Eq(P(r, "status"), "ok") && !T(P(r, "ambiguous")) && T(top) && T(point) && T(P(point, "x")) && T(P(point, "y")))
                    {
                        attempted = true; var a = new List<string> { "--x", S(P(point, "x")), "--y", S(P(point, "y")), "--refine", "uia-safe", "--micro-refine", "--precision-radius", radius.ToString(), "--precision-step", step.ToString(), "--cache-ttl", ttl.ToString() };
                        if (Has(match)) a.AddRange(["--target-match", match!]);
                        var clicked = Effect(LegacyExecutionEffectKind.LocalMacro, "click-point", a.ToArray(), live: true);
                        if (I(P(clicked, "exit")) == 0) { strategy = "uia_precision_point"; rc = 0; line = $"ok smart-click '{label}' strategy=uia_precision_point @({S(P(point, "x"))},{S(P(point, "y"))}) micro_refine=True cache_ttl={ttl} mouse_moved=True"; }
                    }
                }
                catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { }
            }
            if (rc != 0 && !attempted)
            {
                var r = Parsed(Native(LabelArgs("uia-click").ToArray())); if (Eq(P(r, "status"), "ok")) { strategy = "uia_coord"; rc = 0; line = $"ok smart-click '{label}' strategy=uia_coord @({S(P(r, "x"))},{S(P(r, "y"))}) mouse_moved=True"; }
            }
        }
        if (rc != 0 && Stage("icon_find") && mouse)
        {
            try
            {
                var r = Parsed(Effect(LegacyExecutionEffectKind.LocalMacro, "icon-find", ["--label", label!, "--match", match ?? "", "--max-size", "96", "--limit", "5", "--json-only"])); var top = P(r, "top");
                if (Eq(P(r, "status"), "ok") && T(top) && I(P(top, "score")) >= 60)
                {
                    int x = I(P(P(top, "center"), "x")), y = I(P(P(top, "center"), "y"));
                    if (Eq(P(Click(x, y), "status"), "ok")) { strategy = "icon_find"; rc = 0; line = $"ok smart-click '{label}' strategy=icon_find @({x},{y}) score={S(P(top, "score"))} mouse_moved=True"; }
                }
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { }
        }
        if (rc != 0 && Stage("fusion_uia_invoke", "fusion_coord") && !noOcr)
        {
            try
            {
                var r = Parsed(Native(OcrArgs("ocr-uia-invoke").ToArray()));
                if (Eq(P(r, "status"), "ok"))
                {
                    strategy = "fusion_uia_invoke"; rc = 0;
                    string id = T(P(r, "uia_name")) ? $"name='{S(P(r, "uia_name"))}'" : T(P(r, "uia_automation_id")) ? $"id='{S(P(r, "uia_automation_id"))}'" : T(P(r, "uia_class_name")) ? $"class='{S(P(r, "uia_class_name"))}'" : "";
                    line = $"ok smart-click '{label}' strategy=fusion_uia_invoke method={S(P(r, "method"))} {id} mouse_moved=False";
                }
                else if (Eq(P(r, "reason"), "no_invoke_pattern") && mouse)
                {
                    int x = I(P(P(r, "fallback_coord"), "x")), y = I(P(P(r, "fallback_coord"), "y"));
                    if (Eq(P(Click(x, y), "status"), "ok")) { strategy = "fusion_coord"; rc = 0; line = $"ok smart-click '{label}' strategy=fusion_coord @({x},{y}) ocr_score={S(P(r, "ocr_score"))} mouse_moved=True"; }
                }
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { }
        }
        if (rc != 0 && Stage("ocr_text") && mouse && !noOcr)
        {
            try
            {
                var r = Parsed(Native(OcrArgs("ocr-find-text").ToArray())); var top = P(r, "top");
                if (Eq(P(r, "status"), "ok") && T(top) && I(P(top, "score")) >= 70)
                {
                    int x = I(P(top, "cx")), y = I(P(top, "cy")); if (Eq(P(Click(x, y), "status"), "ok")) { strategy = "ocr_text"; rc = 0; line = $"ok smart-click '{label}' strategy=ocr_text matched='{S(P(top, "text"))}' score={S(P(top, "score"))} @({x},{y}) mouse_moved=True"; }
                }
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure) { }
        }
        if (rc != 0 && Stage("vision_precise") && vision && visionAvailable)
        {
            var a = new List<string> { "macro", "vision-click-precise", "--describe", label! }; if (Has(match)) a.AddRange(["--window", match!]);
            strategy = "vision_attempt"; var r = Child(a, live: true, childBrief: true, direct: true);
            if (I(P(r, "exit")) == 0) { rc = 0; strategy = "vision_precise"; line = $"ok smart-click '{label}' strategy=vision_precise mouse_moved=True"; }
        }
        int elapsed = Stop("total"); bool verified = true;
        if (rc == 0 && Has(verifyLabel))
        {
            var a = new List<string> { "macro", "wait-label", "--label", verifyLabel!, "--timeout-ms", timeout.ToString() }; if (Has(match)) a.AddRange(["--window", match!]);
            verified = I(P(Child(a, quiet: false, direct: true), "exit")) == 0;
            if (!verified) return Partial($"partial smart-click '{label}' strategy={strategy} verify_failed='{verifyLabel}'");
        }
        bool screenVerified = true; double ratio = 0; int retryCount = 0;
        void Diff()
        {
            if (Eq(P(Screenshot(after!), "status"), "ok"))
            {
                var d = Parsed(Native("-Action", "screenshot-diff", "-DiffBefore", before!, "-DiffAfter", after!, "-DiffThreshold", "16"));
                if (Eq(P(d, "status"), "ok")) { var n = P(d, "changed_ratio"); ratio = n.ValueKind == JsonValueKind.Null ? 0 : double.Parse(S(n), System.Globalization.CultureInfo.InvariantCulture); screenVerified = T(P(d, "changed")); }
            }
        }
        if (rc == 0 && verifyScreen && Has(before))
        {
            Sleep(wait); after = Path("smartclick-after"); Diff(); Remove(before!); if (Has(after)) Remove(after!);
            while (!screenVerified && retryCount < retries)
            {
                retryCount++; before = Path("smartclick-retry-before"); if (!Eq(P(Screenshot(before), "status"), "ok")) break;
                var retry = Parsed(Native(LabelArgs("uia-invoke").ToArray()));
                if (Eq(P(retry, "status"), "ok")) strategy += "+retry_uia_pattern";
                else if (mouse && !noOcr && Eq(P(Parsed(Native(OcrArgs("ocr-uia-invoke").ToArray())), "status"), "ok")) strategy += "+retry_fusion";
                Sleep(wait); after = Path("smartclick-retry-after"); Diff(); Remove(before); if (Has(after)) Remove(after!);
            }
            if (!screenVerified) return Partial($"partial smart-click '{label}' strategy={strategy} screen_unchanged ratio={ratio} retries={retryCount}");
        }
        if (rc != 0 && T(hint))
        {
            hint = Null; var r = Parsed(Native(LabelArgs("uia-invoke").ToArray()));
            if (Eq(P(r, "status"), "ok")) { strategy = "uia_pattern+hint_fallback"; rc = 0; line = $"ok smart-click '{label}' strategy=uia_pattern hint_fallback method={S(P(r, "method"))} mouse_moved=False"; }
            else if (mouse && !noOcr)
            {
                var f = Parsed(Native(OcrArgs("ocr-uia-invoke").ToArray())); if (Eq(P(f, "status"), "ok")) { strategy = "fusion_uia_invoke+hint_fallback"; rc = 0; line = $"ok smart-click '{label}' strategy=fusion_uia_invoke hint_fallback method={S(P(f, "method"))} mouse_moved=False"; }
            }
        }
        if (rc != 0)
        {
            if (Has(before) && Exists(before!)) Remove(before!);
            if (brief) Effect(LegacyExecutionEffectKind.Console, data: $"partial smart-click '{label}' all_strategies_failed allow_vision={vision} allow_mouse={mouse}");
            History("none", false); return new(Null, 2, 0, null, false);
        }
        History(strategy.Split('+')[0], true);
        if (Has(verifyLabel)) line += $" verified='{verifyLabel}'"; if (verifyScreen) line += $" screen_changed={screenVerified} ratio={ratio}"; if (T(hint)) line += $" hint='{S(hint)}'"; line += $" elapsed_ms={elapsed}";
        return Result(D("schema", "cucp.smart-click/v1", "status", "ok", "label", label, "strategy", strategy, "hinted_strategy", hint, "verified", verified,
            "verify_label", verifyLabel, "verify_screen_changed", screenVerified, "verify_screen_ratio", ratio, "elapsed_ms", elapsed), 0, 4, line, brief);
    }
}
