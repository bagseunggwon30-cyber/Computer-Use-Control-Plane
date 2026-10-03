using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using PcuCp.LegacyHelper;

internal static class HelperContractChecks
{
    private static int checks;
    private const string Start = "2020-01-01T00:00:00Z";
    private static Dictionary<string, object> M(params object[] pairs) { return LegacyHelperActions.Map(pairs); }
    private static object C(string operation, object result, params object[] args) { return M("op", operation, "args", args, "result", result); }
    private static object F(string operation, string error, params object[] args) { return M("op", operation, "args", args, "throw", error); }
    private static object Request(string action, IDictionary<string, object> args = null) { return M("action", action, "args", args ?? M()); }
    private static Dictionary<string, object> D(object value) { return (Dictionary<string, object>)value; }
    private static object[] A(object value) { return (object[])value; }
    private static void Check(bool condition, string description)
    { checks++; if (!condition) throw new InvalidOperationException("Contract failed: " + description); }
    private static void Same(object actual, object expected, string description)
    { Check(object.Equals(actual, expected), description + " (expected " + expected + ", got " + actual + ")"); }
    private static Dictionary<string, object> Evaluate(object[] requests, IEnumerable<object> calls, string[] clock = null, string culture = "en-US")
    { return LegacyHelperFixtureRunner.Evaluate(M("requests", requests, "calls", calls.ToArray(), "clock", clock ?? new[] { Start }, "culture", culture)); }
    private static Dictionary<string, object> Response(Dictionary<string, object> run, int index = 0) { return D(A(run["responses"])[index]); }
    private static Dictionary<string, object> Result(Dictionary<string, object> run, int index = 0) { return D(Response(run, index)["result"]); }
    private static Dictionary<string, object> Run(string action, IEnumerable<object> calls, Dictionary<string, object> args = null, string culture = "en-US")
    { return Evaluate(new[] { Request(action, args) }, calls, null, culture); }
    private static object Rectangle(double x = 0, double y = 0, double width = 100, double height = 100)
    { return M("x", x, "y", y, "width", width, "height", height); }
    private static IEnumerable<object> UiaInit()
    { return new[] { C("uia.load", null), C("win32.ensure", null) }; }
    private static IEnumerable<object> UiaItem(string token, string name, double x = 0, double y = 0, double width = 100, double height = 100)
    { return new[] { C("uia.name", name, token), C("uia.rect", Rectangle(x, y, width, height), token), C("uia.controlType", "button", token) }; }
    private static IEnumerable<object> OcrInit()
    { return new[] { C("win32.ensure", null), C("ocr.initialize", null), C("ocr.createProfile", "engine") }; }
    private static IEnumerable<object> OcrPrepare(object max = null)
    { return new[] { C("ocr.loadDrawing", null), C("ocr.primaryScreenWidth", 1920), C("ocr.loadFormsAndVirtualWidth", 3000), C("ocr.maxDimension", max ?? 10000) }; }
    private static IEnumerable<object> OcrSuccess(int x = 0, int y = 0, int width = 800, int height = 600)
    {
        return new[] { C("ocr.tempPath", "owned.png"), C("ocr.capture", null, x, y, width, height, "owned.png"), C("ocr.prepareAsync", null),
            C("ocr.loadFile", "file", "owned.png"), C("ocr.openRead", "stream", "file"), C("ocr.createDecoder", "decoder", "stream"),
            C("ocr.getBitmap", "bitmap", "decoder"), C("ocr.recognize", M("text", "한글\nSave", "lines", new[] { M("text", "한글", "word_count", 1), M("text", "Save", "word_count", 0) }), "engine", "bitmap"),
            C("ocr.removeTemp", null, "owned.png") };
    }

    internal static void Run()
    {
        HealthAndState(); WindowsAndFocused(); Modal(); Uia(); Ocr(); FixtureGuards();
        Console.WriteLine("Passed " + checks + " helper action contracts; synthetic providers only.");
    }
    private static void HealthAndState()
    {
        var run = Evaluate(new[] { Request("HeAlTh"), Request("health"), Request("health"), Request("health") }, new object[0],
            new[] { Start, "2020-01-01T00:00:00.5Z", "2020-01-01T00:00:01.5Z", "2020-01-01T00:00:02.5Z", "2020-01-01T00:00:03.5Z" });
        Same(Result(run, 0)["uptime_s"], 0, "health rounds .5 to even zero");
        Same(Result(run, 1)["uptime_s"], 2, "health rounds 1.5 to two");
        Same(Result(run, 2)["uptime_s"], 2, "health rounds 2.5 to even two");
        Same(Result(run, 3)["uptime_s"], 4, "health rounds 3.5 to four");
        Same(Result(run, 3)["request_count"], 4, "health counts current request");
        Same(Result(run)["win32_loaded"], false, "health causes no Win32 load");
        Same(Result(run)["helper_mode"], "persistent_server", "legacy helper mode retained");
        Same(Result(run)["pid"], 123, "health integer PID");
        run = Evaluate(new[] { Request("unknown"), Request("shutdown"), Request(" health "), Request("health") }, new object[0], new[] { Start, Start });
        Same(Response(run)["exit_code"], 99, "unsupported signals fallback");
        Same(Result(run)["action"], "unknown", "unsupported action text retained");
        Same(Result(run, 1)["shutting_down"], true, "shutdown reducer acknowledgment");
        Same(Response(run, 2)["exit_code"], 99, "actions are not trimmed");
        Same(Result(run, 3)["request_count"], 4, "unsupported and shutdown are counted");
        run = Evaluate(new[] { Request("focused"), Request("focused"), Request("health"), Request("focused") },
            new[] { F("win32.ensure", "first load failed"), C("win32.ensure", null), C("win32.foreground", 0), C("win32.foreground", 0) }, new[] { Start, Start });
        Same(Result(run)["reason"], "win32_unavailable", "Win32 acquisition failure mapped");
        Same(Result(run, 1)["reason"], "no_foreground", "failed Win32 init retried");
        Same(Result(run, 2)["win32_loaded"], true, "successful Win32 init visible to health");
        Same(D(run["state"])["request_count"], 4, "all stateful calls counted");
    }
    private static void WindowsAndFocused()
    {
        var calls = new[] { C("win32.ensure", null), C("win32.enumerate", new long[] { 1, 2, 3, 4, 5 }),
            C("win32.visible", false, 1L), C("win32.visible", true, 2L), C("win32.titleLength", 0, 2L),
            C("win32.visible", true, 3L), C("win32.titleLength", 9, 3L), C("win32.title", "", 3L, 10),
            C("win32.visible", true, 4L), C("win32.titleLength", 5, 4L), C("win32.title", "Other", 4L, 6),
            C("win32.class", "SAVE", 4L, 256), C("win32.pid", 9, 4L),
            C("win32.visible", true, 5L), C("win32.titleLength", 4, 5L), C("win32.title", "SaVe", 5L, 5),
            C("win32.class", "Frame", 5L, 256), C("win32.pid", 12, 5L), C("win32.rect", M("left", -5, "top", 3, "right", 105, "bottom", 103), 5L),
            C("win32.foreground", 4L), C("win32.titleLength", 5, 4L), C("win32.title", "Other", 4L, 6) };
        var run = Run("windows", calls, M("mAtCh", "save")); var result = Result(run);
        Same(result["count"], 1, "title-only match ignores class but acquires class and PID first");
        var window = D(A(result["windows"])[0]);
        Same(window["hwnd"], 5L, "HWND numeric Int64"); Same(window["pid"], 12, "PID numeric Int32");
        Same(D(window["rect"])["w"], 110, "Win32 right-left width"); Same(D(window["rect"])["h"], 100, "Win32 bottom-top height");
        Same(D(result["foreground"])["hwnd"], 4L, "foreground independent of Match");
        Same(A(result["windows"]).Length, 1, "singleton windows retains array");
        Same(((string[])result["sources"])[0], "win32_helper_server", "legacy source identifier");
        run = Run("windows", new[] { C("win32.ensure", null), C("win32.enumerate", new object[0]), C("win32.foreground", 8), C("win32.titleLength", 0, 8L) });
        Same(Result(run)["foreground"], null, "foreground no title length is null");
        Same(A(Result(run)["windows"]).Length, 0, "empty windows retains array");
        run = Run("focused", new[] { C("win32.ensure", null), C("win32.foreground", 2147483648L), C("win32.title", "한글 😀", 2147483648L, 512),
            C("win32.class", "", 2147483648L, 256), C("win32.pid", 42, 2147483648L),
            C("win32.rect", M("left", int.MinValue, "top", -1, "right", int.MaxValue, "bottom", 0), 2147483648L) });
        Same(Result(run)["hwnd"], 2147483648L, "wide foreground HWND preserved");
        Same(Result(run)["title"], "한글 😀", "Unicode title retained");
        Same(D(Result(run)["rect"])["w"], 4294967295d, "overflowing subtraction promotes to double");
        run = Run("focused", new[] { C("win32.ensure", null), F("win32.foreground", "focus failure") });
        Same(Response(run)["result"], null, "focused provider failure escapes action");
        Same(Response(run)["error"], "focus failure", "focused provider error retained");
        Same(D(run["state"])["request_count"], 1, "throwing dispatch counted");
    }
    private static void Modal()
    {
        var calls = new List<object> { C("uia.loadModal", null), C("win32.ensure", null), F("win32.foreground", "gone"), C("uia.root", "root"),
            C("uia.children", new[] { "broken", "small", "tie", "dialog", "modal", "boundary" }, "root", "window-or-pane"), F("uia.name", "gone", "broken") };
        Action<string, string, bool, int, object> Add = (token, clazz, modal, handle, rectangle) =>
        { calls.Add(C("uia.name", token, token)); calls.Add(C("uia.class", clazz, token)); calls.Add(C("uia.rect", rectangle, token)); calls.Add(C("uia.isModal", modal, token)); if (token != "boundary") calls.Add(C("uia.handle", handle, token)); };
        Add("small", "Frame", false, 1, Rectangle()); Add("tie", "Frame", false, 2, Rectangle());
        Add("dialog", "xTaskDialogX", false, 3, Rectangle()); Add("modal", "#32770", true, 4, Rectangle());
        Add("boundary", "Frame", false, 5, Rectangle(0, 0, 900, 600));
        var run = Run("modal-detect", calls); var result = Result(run); var candidates = A(result["modal_candidates"]);
        Same(result["foreground"], null, "modal foreground failure soft"); Same(result["candidate_count"], 4, "modal size boundary excluded");
        Same(D(candidates[0])["score"], 180, "modal score sums modal class and small");
        Same(D(candidates[0])["reason"], "uia_window_is_modal", "modal reason prioritizes isModal");
        Same(D(candidates[1])["score"], 80, "dialog class plus size score");
        Same(D(candidates[1])["reason"], "dialog_class_name", "class reason before size");
        Same(D(candidates[2])["title"], "small", "ties preserve enumeration order");
        Same(D(candidates[3])["title"], "tie", "second tie stays second");
        Same(result["recommended_action"], "dismiss_or_confirm", "top modal recommendation");
        Same(D(run["state"])["uia_loaded"], false, "modal does not set uia-find cache");
        run = Run("modal-detect", new[] { C("uia.loadModal", null), C("win32.ensure", null), C("win32.foreground", 0), C("uia.root", "root"),
            C("uia.children", new[] { "dialog" }, "root", "window-or-pane"), C("uia.name", "message", "dialog"), C("uia.class", "Popup", "dialog"),
            C("uia.rect", Rectangle(0, 0, 900, 600), "dialog"), F("uia.isModal", "no pattern", "dialog"), F("uia.handle", "unavailable", "dialog") });
        Same(Result(run)["recommended_action"], "confirm_dialog", "score60 recommendation");
        Same(D(A(Result(run)["modal_candidates"])[0])["hwnd"], null, "native handle error gives null");
        run = Run("modal-detect", new[] { C("uia.loadModal", null), C("win32.ensure", null), C("win32.foreground", 0), F("uia.root", "unavailable") });
        Same(Result(run)["status"], "ok", "modal query failure is soft success");
        Same(Result(run)["recommended_action"], "observe", "empty modal recommendation");
    }
    private static void Uia()
    {
        var run = Evaluate(new[] { Request("uia-find-fast"), Request("uia-find-fast"), Request("uia-find-fast") },
            new[] { F("uia.load", "load failure"), C("uia.load", null), F("win32.ensure", "win32 failure"), C("win32.ensure", null) });
        Same(Result(run)["reason"], "uia_load_failed", "UIA load failure wins before Win32");
        Same(Result(run, 1)["reason"], "win32_unavailable", "Win32 load follows successful UIA");
        Same(Result(run, 2)["reason"], "missing_label", "validation follows acquisition cache setup");
        run = Run("uia-find-fast", UiaInit(), M("Label", "Save", "label", false));
        Same(Result(run)["reason"], "missing_label", "later lowercase argument overwrites uppercase hashtable key");
        run = Run("uia-find-fast", UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.subtree", new object[0], "root") }), M("label", false, "Label", "Save"));
        Same(Result(run)["label"], "Save", "later uppercase argument overwrites lowercase hashtable key");
        var calls = UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.children", new[] { "bad", "first", "second" }, "root", "all"),
            F("uia.name", "gone", "bad"), C("uia.name", "Application", "first"), C("uia.subtree", new[] { "contains", "prefix", "exact" }, "first") })
            .Concat(UiaItem("contains", "resave", 0.5, 1.5, 2, 2)).Concat(UiaItem("prefix", "Save as")).Concat(UiaItem("exact", "SAVE"));
        run = Run("uia-find-fast", calls, M("Label", "save", "Match", "Application"));
        var result = Result(run); var candidates = A(result["candidates"]);
        Same(result["candidate_count"], 3, "three UIA matches"); Same(result["score"], 100, "exact score100");
        Same(D(candidates[1])["score"], 80, "prefix score80"); Same(D(candidates[2])["score"], 50, "contains score50");
        Same(D(D(candidates[2])["rect"])["x"], 0, "UIA x rounds to even zero");
        Same(D(D(candidates[2])["rect"])["y"], 2, "UIA y rounds to even two");
        Same(D(D(candidates[2])["click_point"])["x"], 2, "center rounded after addition");
        Same(D(D(candidates[2])["click_point"])["y"], 2, "center2.5 rounds even");
        Same(D(run["state"])["uia_loaded"], true, "successful UIA cached");
        calls = UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.children", new[] { "child" }, "root", "all"), C("uia.name", "other", "child"),
            C("uia.subtree", new[] { "empty", "badrect", "badtype", "good" }, "root"), C("uia.name", "", "empty"),
            C("uia.name", "[a]", "badrect"), C("uia.rect", Rectangle(0, 0, 0, 10), "badrect"), C("uia.name", "[a]", "badtype"),
            C("uia.rect", Rectangle(), "badtype"), F("uia.controlType", "gone", "badtype") }).Concat(UiaItem("good", "[a]"));
        run = Run("uia-find-fast", calls, M("label", "[a]", "match", "missing"));
        Same(Result(run)["candidate_count"], 1, "missing Match scans root and per-element failures skip");
        Same(D(Result(run)["best"])["name"], "[a]", "regex metacharacters are literal");
        var capCalls = UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.subtree", Enumerable.Range(0, 17).Select(i => "n" + i).ToArray(), "root") }).ToList();
        for (int i = 0; i < 16; i++) capCalls.AddRange(UiaItem("n" + i, "Save " + i));
        run = Run("uia-find-fast", capCalls, M("Label", "Save"));
        Same(Result(run)["candidate_count"], 16, "cap16 occurs before evaluating seventeenth");
        Same(D(A(Result(run)["candidates"])[15])["name"], "Save 15", "cap tie order retained");
        var scanCalls = UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.subtree", Enumerable.Range(0, 801).Select(i => "n" + i).ToArray(), "root") }).ToList();
        for (int i = 0; i < 800; i++) scanCalls.Add(C("uia.name", "other", "n" + i));
        run = Run("uia-find-fast", scanCalls, M("Label", "Save"));
        Same(Result(run)["reason"], "no_match", "scan cap800 does not inspect801"); Same(Response(run)["exit_code"], 2, "no match is partial exit2");
        run = Run("uia-find-fast", UiaInit().Concat(new[] { F("uia.root", "query failure") }), M("Label", "Save"));
        Same(Result(run)["reason"], "uia_query_failed", "root failure maps query error"); Same(Result(run)["detail"], "query failure", "query detail preserved");
        run = Run("uia-find-fast", UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.subtree", new[] { "n" }, "root") }).Concat(UiaItem("n", "i")), M("Label", "I"), "en-US");
        Same(Result(run)["score"], 100, "en-US regex and invariant equality match I with i");
        run = Run("uia-find-fast", UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.subtree", new[] { "n" }, "root"), C("uia.name", "i", "n") }), M("Label", "I"), "tr-TR");
        Same(Result(run)["reason"], "no_match", "Turkish regex I does not match i");
        run = Run("uia-find-fast", UiaInit().Concat(new[] { C("uia.root", "root"), C("uia.subtree", new[] { "n" }, "root") }).Concat(UiaItem("n", "ı")), M("Label", "I"), "tr-TR");
        Same(Result(run)["score"], 50, "Turkish regex matching differs from invariant exact/prefix");
    }
    private static void Ocr()
    {
        var run = Evaluate(new[] { Request("ocr-screen-fast"), Request("ocr-screen-fast", M("x", false, "y", -2, "w", 0, "h", 300.5)) },
            OcrInit().Concat(OcrPrepare()).Concat(OcrSuccess()).Concat(OcrPrepare()).Concat(OcrSuccess(0, -2, 800, 300)));
        Same(Result(run)["engine_warm"], true, "OCR first success already reports warm");
        Same(Result(run)["line_count"], 2, "OCR retains all lines including zero words");
        Same(D(A(Result(run)["lines"])[1])["word_count"], 0, "OCR zero-word line retained");
        Same(Result(run)["text"], "한글\nSave", "OCR Unicode multiline text");
        Same(D(Result(run, 1)["region"])["w"], 800, "OCR zero width selects default800");
        Same(D(Result(run, 1)["region"])["h"], 300, "OCR height midpoint rounds even");
        Same(D(run["state"])["ocr_warm"], true, "OCR successful engine retained");
        run = Evaluate(new[] { Request("ocr-screen-fast"), Request("ocr-screen-fast") }, new[] { C("win32.ensure", null), F("ocr.initialize", "first failure"),
            C("ocr.initialize", null), C("ocr.createProfile", null), C("ocr.languages", new[] { "lang1", "lang2" }), C("ocr.createLanguage", "engine", "lang1") }
            .Concat(OcrPrepare()).Concat(OcrSuccess()));
        Same(Result(run)["reason"], "ocr_init_failed", "OCR init failure mapping");
        Same(Result(run)["detail"], "first failure", "OCR init error detail"); Same(Result(run, 1)["status"], "ok", "OCR failed init retries and uses first available language");
        run = Evaluate(new[] { Request("ocr-screen-fast"), Request("ocr-screen-fast") }, new[] { C("win32.ensure", null), C("ocr.initialize", null), C("ocr.createProfile", null), C("ocr.languages", new object[0]),
            C("ocr.initialize", null), C("ocr.createProfile", null), C("ocr.languages", new[] { "lang" }), C("ocr.createLanguage", null, "lang") });
        Same(Result(run)["detail"], "no_ocr_language_available", "OCR missing profile and languages error");
        Same(Result(run, 1)["detail"], "no_ocr_language_available", "OCR null language engine error");
        Same(D(run["state"])["ocr_warm"], false, "failed init never warms cache");
        run = Run("ocr-screen-fast", OcrInit().Concat(OcrPrepare(100)), M("W", 101, "H", 1));
        Same(Result(run)["reason"], "region_exceeds_max_image_dimension", "OCR max checked before capture"); Same(Result(run)["max_dim"], 100, "OCR max dimension exposed");
        run = Run("ocr-screen-fast", OcrInit().Concat(OcrPrepare()).Concat(new[] { C("ocr.tempPath", "owned.png"), F("ocr.capture", "invalid size", 0, 0, 0, -1, "owned.png") }), M("W", "0", "H", -1));
        Same(Result(run)["reason"], "screenshot_failed", "truthy string0 becomes zero unlike numeric0");
        Same(Result(run)["detail"], "invalid size", "capture failure detail; no postcapture remove");
        run = Run("ocr-screen-fast", OcrInit().Concat(OcrPrepare()).Concat(new[] { C("ocr.tempPath", "owned.png"), C("ocr.capture", null, 0, 0, 800, 600, "owned.png"),
            C("ocr.prepareAsync", null), F("ocr.loadFile", "load failure", "owned.png"), F("ocr.removeTemp", "remove failure", "owned.png") }));
        Same(Result(run)["reason"], "ocr_failed", "OCR load failures distinct from capture");
        Same(Result(run)["detail"], "load failure", "cleanup failure does not replace OCR detail");
        run = Run("ocr-screen-fast", OcrInit().Concat(new[] { C("ocr.loadDrawing", null), F("ocr.primaryScreenWidth", "primary screen failure") }));
        Same(Response(run)["result"], null, "primary screen failure escapes action before protected Forms probe");
        Same(Response(run)["error"], "primary screen failure", "primary screen error detail retained");
        run = Run("ocr-screen-fast", OcrInit().Concat(new[] { C("ocr.loadDrawing", null), C("ocr.primaryScreenWidth", 1920), F("ocr.loadFormsAndVirtualWidth", "ignored"), F("ocr.maxDimension", "ignored") }), M("W", 10001));
        Same(Result(run)["max_dim"], 10000, "OCR max fallback10000 and Forms failure soft");
        run = Run("ocr-screen-fast", OcrInit().Concat(new[] { C("ocr.loadDrawing", null), C("ocr.primaryScreenWidth", 1920), C("ocr.loadFormsAndVirtualWidth", 1920) }), M("W", "bogus"));
        Same(Response(run)["exit_code"], 1, "OCR invalid integer escapes before max query"); Same(Response(run)["result"], null, "OCR argument error not mapped as screenshot");
    }
    private static void FixtureGuards()
    {
        Action<Action, string> Fails = (action, message) => { bool failed = false; try { action(); } catch (LegacyHelperFixtureException) { failed = true; } Check(failed, message); };
        Fails(() => Run("windows", new object[0]), "missing fixture access fails outside provider-failure catches");
        Fails(() => LegacyHelperFixtureRunner.Evaluate(M("calls", 42, "clock", new[] { Start }, "action", "shutdown")), "scalar calls collection fails even without acquisition");
        Fails(() => LegacyHelperFixtureRunner.Evaluate(M("clock", new[] { Start }, "action", "shutdown")), "missing calls collection fails");
        Fails(() => LegacyHelperFixtureRunner.Evaluate(M("calls", M(), "clock", new[] { Start }, "action", "shutdown")), "dictionary calls collection fails");
        Fails(() => LegacyHelperFixtureRunner.Evaluate(M("calls", new object[0], "clock", Start, "action", "shutdown")), "scalar clock collection fails");
        Fails(() => LegacyHelperFixtureRunner.Evaluate(M("calls", new object[0], "clock", new[] { Start }, "requests", 42, "action", "shutdown")), "invalid requests collection cannot use shorthand fallback");
        Fails(() => Run("focused", new[] { M("op", "win32.ensure", "args", 42, "result", null) }), "scalar capture args cannot equal empty argument array");
        Fails(() => Run("focused", new[] { M("op", "win32.ensure", "args", new object[0]) }), "capture requires result or explicit simulated exception");
        Fails(() => Run("windows", new[] { C("win32.foreground", 0) }), "reordered fixture access fails");
        Fails(() => Run("focused", new[] { C("win32.ensure", null), C("win32.foreground", 1), C("win32.title", "x", 1L, 42) }), "fixture arguments exact");
        Fails(() => Run("shutdown", new[] { C("win32.ensure", null) }), "unused captures fail closed");
        Fails(() => Evaluate(new[] { Request("health") }, new object[0]), "unplanned clock fails");
        Fails(() => Evaluate(new[] { Request("shutdown") }, new object[0], new[] { Start, Start }), "unused clock fails");
        Fails(() => Run("modal-detect", new[] { C("uia.loadModal", null), C("win32.ensure", null), C("win32.foreground", 0) }), "modal broad catch cannot swallow fixture exhaustion");
        Fails(() => Run("ocr-screen-fast", OcrInit().Concat(OcrPrepare()).Concat(OcrSuccess().Take(8))), "OCR finally cannot swallow missing cleanup capture");
        Same(LegacyHelperActions.Truth(new object[] { false }), false, "one-item false array false");
        Same(LegacyHelperActions.Truth(new object[] { false, false }), true, "two-item array true");
        Same(LegacyHelperActions.Text(new object[] { "Save", "as" }), "Save as", "array interpolation space joins");
        Same(LegacyHelperActions.Text(M("label", "Save")), "@{label=Save}", "dictionary string coercion enumerates entries without invalid cast");
        Same(LegacyHelperActions.Integer("1.5"), 2, "string fractional integer rounds even");
        Same(LegacyHelperActions.Integer("0x10"), 16, "hex numeric string supported");
    }
}
