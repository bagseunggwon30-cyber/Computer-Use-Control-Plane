using System.Text.Json;

internal static class CoordinateContractChecks
{
    internal static void Run(Action<bool, string> check)
    {
        var desktop = new { x = -1920, y = -200, width = 3840, height = 1280, right = 1920, bottom = 1080, monitor_count = 2 };
        var window = new { hwnd = 42, title = "한글", process = "fixture", @class = "Window", rect = new { x = -2000, y = -250, width = 400, height = 300 } };
        JsonElement Map(string mode, double x, double y) => JsonSerializer.SerializeToElement(LegacyCoordinateKernel.Map(JsonSerializer.SerializeToElement(new
            { from = mode, x, y, selected_window = window, virtual_screen = desktop })));
        var origin = Map("visible-window", 0, 0);
        check(origin.GetProperty("screen_point").GetProperty("x").GetInt32() == -1920 && origin.GetProperty("screen_point").GetProperty("y").GetInt32() == -200, "Visible origin changed");
        check(origin.GetProperty("window_point").GetProperty("x").GetInt32() == 80, "Clipped window offset lost");
        var edge = Map("normalized", 1, 1);
        check(!edge.GetProperty("inside_window").GetBoolean() && !edge.GetProperty("inside_visible_clip").GetBoolean(), "Exclusive edge was clamped into window");
        check(edge.GetProperty("warnings").GetArrayLength() == 3, "Outside/rounding warnings lost");
        check(Map("screen", -0.5, 2.5).GetProperty("screen_point").GetProperty("x").GetInt32() == 0, "Negative midpoint round changed");
        check(Map("screen", -0.5, 2.5).GetProperty("screen_point").GetProperty("y").GetInt32() == 2, "Banker's rounding changed");
        check(Map("no-such-mode", 0, 0).GetProperty("reason").GetString() == "unsupported_from", "Unsupported mode accepted");
        check(Map("SCREEN", 0, 0).GetProperty("from").GetString() == "screen", "Case normalization changed");
        var failed = false;
        try { Map("normalized", 1e12, 0); } catch (NativeFailure) { failed = true; }
        check(failed, "Unbounded mapped coordinate accepted");
    }
}
