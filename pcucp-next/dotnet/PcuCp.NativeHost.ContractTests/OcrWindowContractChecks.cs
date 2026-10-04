using System.Text.Json;

internal static class OcrWindowContractChecks
{
    internal static void Run(Action<bool, string> check)
    {
        void Reject(Action action, string label)
        {
            try { action(); } catch (NativeFailure) { check(true, label); return; }
            check(false, label);
        }
        var capture = new ScreenshotData(new ScreenshotImage("image/png", "AA==", 800, 500), new { hwnd = "0x20", pid = 42 },
            new ScreenshotGeometry(-1600, -200, 1600, 1000, 800, 500), new PixelRect(-1600, -200, 1600, 1000),
            "2026-10-01T00:00:00Z", "physical_screen_pixels", "visible_desktop_crop_may_include_occluding_windows", true, false);
        var json = JsonSerializer.SerializeToElement(capture, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
        check(json.GetProperty("image").GetProperty("mime_type").GetString() == "image/png", "Screenshot image schema changed");
        check(json.GetProperty("geometry").GetProperty("image_width").GetInt32() == 800 && json.GetProperty("geometry").GetProperty("x").GetInt32() == -1600, "OCR screenshot image/global coordinate identities lost");
        check(json.GetProperty("window_geometry").GetProperty("width").GetInt32() == 1600 && json.GetProperty("target_foreground").GetBoolean(), "Screenshot window metadata changed");
        check(json.GetProperty("capture_semantics").GetString() == "visible_desktop_crop_may_include_occluding_windows" && !json.GetProperty("cursor_included").GetBoolean(), "Capture limitations lost");
        var defaults = OcrWindowRequest.Parse(new CommandOptions(["--hwnd", "0x20"]));
        check(defaults.MaximumWidth == 1600 && defaults.MaximumHeight == 1000 && defaults.Language is null, "OCR defaults mismatch screenshot");
        foreach (var tag in new[] { "ko", "ko-KR", "en-US", "zh-Hant-TW" })
            check(OcrWindowRequest.Parse(new CommandOptions(["--language", tag])).Language == tag, "Language tag lost");
        foreach (var tag in new[] { "", "a", "-ko", "ko-", "ko--KR", "ko_KR", "../ko", new string('x', 65) })
            Reject(() => OcrWindowRequest.Parse(new CommandOptions(["--language", tag])), "Invalid language tag accepted");
        foreach (var dimension in new[] { "0", "63", "4097", "NaN" })
            Reject(() => OcrWindowRequest.Parse(new CommandOptions(["--max-width", dimension])), "Invalid OCR image bound accepted");
        Reject(() => OcrWindowRequest.Parse(new CommandOptions(["--image-b64", "AA=="])), "PNG allowed into short native request");
        Reject(() => OcrWindowRequest.Parse(new CommandOptions(["--path", "secret.png"])), "OCR window accepted disk source");
        Reject(() => OcrWindowRequest.Parse(new CommandOptions(["--allow-live-control"])), "Read-only OCR window accepted mutation flag");
        OcrWindowRequest.ValidateBitmap(2000, 2000, 4096);
        check(true, "Four-megapixel image rejected");
        Reject(() => OcrWindowRequest.ValidateBitmap(2001, 2000, 4096), "OCR pixel budget exceeded");
        Reject(() => OcrWindowRequest.ValidateBitmap(0, 100, 4096), "Zero OCR dimension accepted");
        Reject(() => OcrWindowRequest.ValidateBitmap(1600, 1000, 1000), "Recognizer dimension bound ignored");
        var req = NativeSession.Parse("{\"schema\":\"pcucp.native.request/v1\",\"id\":1,\"command\":\"ocr-window\",\"args\":[\"--hwnd\",\"0x20\"]}", false, 0);
        check(req.Command == "ocr-window", "Read-only OCR blocked by native authority parser");
    }
}
