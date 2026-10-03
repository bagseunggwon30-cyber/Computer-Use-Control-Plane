using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.Linq;
using PcuCp.LegacyObservation;

internal static class ActionContractTests
{
    public static void Run(Action<bool, string> check)
    {
        HitTestChecks(check);
        HitScanChecks(check);
        WindowAndTreeChecks(check);
        FindChecks(check);
    }

    private static void HitTestChecks(Action<bool, string> check)
    {
        var p = new InertProvider();
        var a = new ObservationActions(p);
        var result = a.HitTest(new ObservationOptions());
        check(result.ExitCode == 1 && Equals(result.Payload["reason"], "missing_coords"), "hit-test: coordinate gate");
        check(p.Calls.Count == 0, "hit-test: missing coordinates acquire nothing");
        p.WindowAtPoint = (x, y) => 0;
        result = a.HitTest(new ObservationOptions { HasCoordinates = true, X = 0, Y = -7 });
        check(result.ExitCode == 2 && Equals(result.Payload["reason"], "no_window_at_coords"), "hit-test: zero HWND partial");
        check(Equals(result.Payload["x"], 0) && Equals(result.Payload["y"], -7), "hit-test: zero/negative coordinates retained");
        check(p.Calls.SequenceEqual(new[] { "window:0,-7" }), "hit-test: zero HWND exits before root lookup");
        p = new InertProvider(); a = new ObservationActions(p);
        p.ProcessFailure = true;
        result = a.HitTest(new ObservationOptions { HasCoordinates = true, X = -1, Y = 0, SkipUia = true, TargetHwnd = 10, TargetMatch = "wrong" });
        check(result.ExitCode == 0 && Equals(result.Payload["matched"], true), "hit-test: HWND takes priority over title");
        check(Equals(result.Payload["match_reason"], "hwnd_match"), "hit-test: HWND match reason");
        check(Equals(result.Payload["process_name"], ""), "hit-test: process exception keeps empty name");
        check(!result.Payload.Contains("uia_point") && Equals(result.Payload["uia_skipped"], true), "hit-test: skip excludes UIA point");
        check(p.Calls.SequenceEqual(new[] { "window:-1,0", "root:11", "title:10:256", "title:11:256", "class:10:256", "pid:10", "process:42" }), "hit-test: ordered acquisition and exact 256 buffers");
        check(result.Payload["child_hwnd"] is long && result.Payload["root_hwnd"] is long && result.Payload["process_id"] is int, "hit-test: handle/process numeric types");
        check(Keys(result.Payload) == "status,x,y,child_hwnd,root_hwnd,root_title,child_title,root_class,process_id,process_name,target_hwnd,target_match,matched,match_reason,uia_skipped", "hit-test: payload field order");
        p.ProcessFailure = false; p.Process = null;
        result = a.HitTest(new ObservationOptions { HasCoordinates = true, SkipUia = true, TargetHwnd = 12 });
        check(result.ExitCode == 2 && Equals(result.Payload["match_reason"], "hwnd_mismatch"), "hit-test: HWND mismatch partial");
        check(result.Payload["process_name"] == null, "hit-test: process missing preserves null assignment");
        result = a.HitTest(new ObservationOptions { HasCoordinates = true, SkipUia = true, TargetMatch = "wanted MAIN" });
        check(result.ExitCode == 0 && Equals(result.Payload["match_reason"], "title_match"), "hit-test: invariant lowercase title match");
        p.Title = "";
        result = a.HitTest(new ObservationOptions { HasCoordinates = true, SkipUia = true, TargetMatch = "wanted" });
        check(result.ExitCode == 2 && Equals(result.Payload["matched"], false), "hit-test: empty title mismatch is boolean false");
        p.Title = "Wanted Main"; p.UiaAvailable = false;
        result = a.HitTest(new ObservationOptions { HasCoordinates = true });
        check(result.ExitCode == 0 && Equals(result.Payload["match_reason"], "no_target_specified") && !result.Payload.Contains("uia_point"), "hit-test: unavailable refinement is optional");
        check(p.UiaChecks == 1, "hit-test: ordinary path attempts refinement");
        p.UiaAvailable = true; p.PointNode = ClickNode("point", "button");
        result = a.HitTest(new ObservationOptions { HasCoordinates = true });
        var point = (OrderedDictionary)result.Payload["uia_point"];
        check(point != null && Equals(point["native_clickable"], true), "hit-test: refinement output attached");
        check(Keys(point) == "refined_x,refined_y,score,role,pattern,point_source,native_clickable,match", "hit-test: refinement field order");
        p.RawProcessId = uint.MaxValue; p.Calls.Clear();
        bool overflow = false;
        try { a.HitTest(new ObservationOptions { HasCoordinates = true }); } catch (OverflowException) { overflow = true; }
        check(overflow, "hit-test: overflowing raw process id fails payload cast");
        check(p.Calls.Contains("process:4294967295") && p.Calls.Contains("ensure-uia"), "hit-test: raw process lookup and refinement precede payload overflow");
    }

    private static void HitScanChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var a = new ObservationActions(p);
        var result = a.HitScan(new ObservationOptions());
        check(result.ExitCode == 1 && p.Calls.Count == 0, "hit-scan: missing coordinates gate");
        p.UiaAvailable = false;
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = -1, ScanStep = 0, ClickInset = 0, SkipUia = true });
        check(result.ExitCode == 2 && Equals(result.Payload["reason"], "no_uia_candidate"), "hit-scan: no candidate partial");
        check(Equals(result.Payload["radius"], 0) && Equals(result.Payload["step"], 6) && Equals(result.Payload["click_inset"], 3), "hit-scan: lower/default clamps");
        check(Equals(result.Payload["sample_count"], 1) && Equals(result.Payload["target_matched_samples"], 1), "hit-scan: radius zero samples origin once");
        check(p.UiaChecks == 1, "hit-scan: SkipUia has no effect");
        check(p.Calls.Take(4).SequenceEqual(new[] { "metric:76", "metric:77", "metric:78", "metric:79" }), "hit-scan: virtual metrics acquisition order");
        check(result.Payload["elapsed_ms"] is int && (int)result.Payload["elapsed_ms"] >= 0, "hit-scan: rounded elapsed Int32");
        p = new InertProvider { UiaAvailable = false }; a = new ObservationActions(p);
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 3, ScanStep = 2, ClickInset = -9 });
        check(Equals(result.Payload["sample_count"], 25), "hit-scan: radius remainder endpoints included");
        check(p.WindowPoints.Take(5).SequenceEqual(new[] { "-3,-3", "-2,-3", "0,-3", "2,-3", "3,-3" }), "hit-scan: y-major ascending sample order");
        check(p.WindowPoints.Last() == "3,3", "hit-scan: final positive corner");
        p = new InertProvider { UiaAvailable = false, Vx = -1, Vy = -1, Vw = 2, Vh = 2 }; a = new ObservationActions(p);
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 2, ScanStep = 1 });
        check(Equals(result.Payload["sample_count"], 4), "hit-scan: half-open virtual bounds");
        check(p.WindowPoints.SequenceEqual(new[] { "-1,-1", "0,-1", "-1,0", "0,0" }), "hit-scan: negative virtual coordinates retained");
        p = new InertProvider { UiaAvailable = false, Log = false }; a = new ObservationActions(p);
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 100, ScanStep = 1 });
        check(Equals(result.Payload["radius"], 64) && Equals(result.Payload["sample_count"], 16641), "hit-scan: exact maximum 16641 samples without lowered cap");
        check(p.UiaChecks == 16641, "hit-scan: maximum scan visits every target-matched sample");
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 64, ScanStep = 99 });
        check(Equals(result.Payload["step"], 16) && Equals(result.Payload["sample_count"], 81), "hit-scan: upper step clamp");
        p = new InertProvider { WindowAtPoint = (x, y) => 0 }; a = new ObservationActions(p);
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 2, ScanStep = 2 });
        check(Equals(result.Payload["sample_count"], 9) && Equals(result.Payload["target_matched_samples"], 0) && p.UiaChecks == 0, "hit-scan: failed sample guards do not resolve UIA");
        p = new InertProvider { PointNode = ClickNode("point", "button") }; a = new ObservationActions(p);
        p.PointLookup = (x, y) => { p.PointNode.Values[ObservationProperty.LocalizedControlType] = x < 0 ? "BUTTON" : "button"; return p.PointNode; };
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 2, ScanStep = 2 });
        var best = (OrderedDictionary)result.Payload["best"];
        check(result.ExitCode == 0 && Equals(result.Payload["candidate_count"], 9), "hit-scan: retains all duplicate candidate rows");
        check(Equals(best["support"], 9), "hit-scan: keys group role case-insensitively");
        check(Equals(best["final_score"], (int)best["base_score"] + 9 * 7 + 20), "hit-scan: support and clickable bonuses");
        check(best["distance_from_origin"] is double && best["area"] is int, "hit-scan: distance and rounded area types");
        check(Equals(((OrderedDictionary)result.Payload["recommended_point"])["confidence"], "high"), "hit-scan: native click confidence high");
        check(((OrderedDictionary[])result.Payload["candidates"]).Length == 9, "hit-scan: multi candidate array");
        check(Keys(best) == "sample_x,sample_y,dx,dy,refined_x,refined_y,final_score,base_score,support,distance_from_origin,role,pattern,point_source,native_clickable,depth,area,match", "hit-scan: ranked field order");
        check(Keys(result.Payload) == "status,x,y,radius,step,click_inset,target_hwnd,target_match,sample_count,target_matched_samples,candidate_count,best,recommended_point,candidates,elapsed_ms", "hit-scan: success field order");
        p = new InertProvider { PointNode = ClickNode("point", "button") }; a = new ObservationActions(p);
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 3, ScanStep = 1 });
        check(Equals(result.Payload["candidate_count"], 49) && ((OrderedDictionary[])result.Payload["candidates"]).Length == 12, "hit-scan: top twelve cap leaves total candidate count");
        p.PointNode.Clickable = false;
        result = a.HitScan(new ObservationOptions { HasCoordinates = true });
        check(((OrderedDictionary[])result.Payload["candidates"]).Length == 1, "hit-scan: singleton remains array");
        check(Equals(((OrderedDictionary)result.Payload["recommended_point"])["confidence"], "low"), "hit-scan: single non-native confidence low");
        p.Vx = 0; p.Vy = 0; p.Vw = 2; p.Vh = 1;
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 1, ScanStep = 1 });
        check(Equals(((OrderedDictionary)result.Payload["recommended_point"])["confidence"], "medium"), "hit-scan: two non-native supports confidence medium");
        p.Vh = 2;
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, ScanRadius = 1, ScanStep = 1 });
        check(Equals(((OrderedDictionary)result.Payload["recommended_point"])["confidence"], "high"), "hit-scan: four non-native supports confidence high");
        p.Vx = -100; p.Vy = -100; p.Vw = 200; p.Vh = 200;
        p.PointNode.Rect.X = 100; p.PointNode.Rect.Y = 100;
        p.WindowAtPoint = (x, y) => x >= 100 ? 0 : 11;
        result = a.HitScan(new ObservationOptions { HasCoordinates = true });
        check(result.ExitCode == 2 && Equals(result.Payload["target_matched_samples"], 1) && Equals(result.Payload["candidate_count"], 0), "hit-scan: refined coordinate guard discards candidate");
        p = new InertProvider { UiaAvailable = false, Vx = int.MaxValue - 1, Vy = 0, Vw = 1, Vh = 1 }; a = new ObservationActions(p);
        result = a.HitScan(new ObservationOptions { HasCoordinates = true, X = int.MaxValue, ScanRadius = 1, ScanStep = 1 });
        check(Equals(result.Payload["sample_count"], 1) && p.WindowPoints[0] == (int.MaxValue - 1).ToString(CultureInfo.InvariantCulture) + ",0", "hit-scan: origin arithmetic does not wrap at Int32 max");
    }

    private static void WindowAndTreeChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var a = new ObservationActions(p);
        var result = a.UiaTree(new ObservationOptions { Match = "absent" });
        check(result.ExitCode == 2 && Equals(result.Payload["reason"], "no_matching_window") && p.Calls.SequenceEqual(new[] { "windows" }), "uia-tree: unmatched title never falls back to foreground");
        p.Windows.Insert(0, new ObservationWindow { Hwnd = 20, Title = "other", Foreground = false });
        p.Windows.Add(new ObservationWindow { Hwnd = 30, Title = "Wanted Extra", Foreground = true });
        p.Calls.Clear();
        result = a.UiaTree(new ObservationOptions { Match = "WANTED" });
        check(Equals(result.Payload["target_hwnd"], 10L) && p.Calls.Take(3).SequenceEqual(new[] { "windows", "handle:10", "descendants:root" }), "uia-tree: first title match and Descendants root");
        check(p.UiaChecks == 0, "uia-tree: adapter owns initial UIA availability check");
        p.Windows[1].Foreground = false; p.Calls.Clear();
        result = a.UiaTree(new ObservationOptions());
        check(Equals(result.Payload["target_hwnd"], 30L), "uia-tree: first foreground root without Match");
        p.Root = null;
        result = a.UiaTree(new ObservationOptions());
        check(result.ExitCode == 2 && Equals(result.Payload["reason"], "uia_root_null"), "uia-tree: null root partial");
        p = new InertProvider(); a = new ObservationActions(p);
        var small = Node("small", "small"); small.Rect.Width = 5;
        var hidden = Node("hidden", "hidden"); hidden.Values[ObservationProperty.IsOffscreen] = true;
        var blank = Node("blank", " ");
        var accepted = Node("accepted", " "); accepted.Values[ObservationProperty.AutomationId] = "\t"; accepted.Values[ObservationProperty.HelpText] = "help label";
        accepted.FailProperties.UnionWith(new[] { ObservationProperty.LocalizedControlType, ObservationProperty.IsOffscreen, ObservationProperty.IsEnabled });
        accepted.Rect = new ObservationRect { X = -2.5, Y = 1.5, Width = 10.5, Height = 8.5 };
        var after = Node("after", "after");
        p.Nodes.AddRange(new[] { small, hidden, blank, accepted, after });
        result = a.UiaTree(new ObservationOptions { MaxElements = 1 });
        var items = (OrderedDictionary[])result.Payload["affordances"];
        check(items.Length == 1 && Equals(result.Payload["affordance_count"], 1), "uia-tree: MaxElements counts accepted rows");
        check(!p.Calls.Contains("current:after"), "uia-tree: cap stops before reading next current");
        check(!p.Calls.Any(c => c.StartsWith("property:small:", StringComparison.Ordinal)), "uia-tree: small bounds skip all properties");
        check(p.Calls.Where(c => c.StartsWith("property:hidden:", StringComparison.Ordinal)).SequenceEqual(new[] {
            "property:hidden:Name", "property:hidden:AutomationId", "property:hidden:HelpText", "property:hidden:AccessKey", "property:hidden:ClassName", "property:hidden:LocalizedControlType", "property:hidden:IsOffscreen", "property:hidden:IsEnabled" }), "uia-tree: exact getter order even offscreen");
        check(Equals(items[0]["text"], "help label") && Equals(items[0]["role"], "") && Equals(items[0]["enabled"], true), "uia-tree: whitespace fallback and independent property failures");
        var rect = (OrderedDictionary)items[0]["rect"]; var center = (OrderedDictionary)items[0]["center"];
        check(Equals(rect["x"], -2) && Equals(rect["y"], 2) && Equals(rect["width"], 10) && Equals(rect["height"], 8), "uia-tree: midpoint-to-even rectangle conversion");
        check(Equals(center["x"], 3) && Equals(center["y"], 6), "uia-tree: center calculated from unrounded rectangle");
        check(Keys(items[0]) == "text,name,automation_id,help_text,access_key,class_name,role,enabled,rect,center", "uia-tree: affordance field order");
        check(Keys(result.Payload) == "status,target_hwnd,affordance_count,affordances", "uia-tree: envelope field order");
        p.Calls.Clear(); result = a.UiaTree(new ObservationOptions { MaxElements = 0 });
        check(((OrderedDictionary[])result.Payload["affordances"]).Length == 0 && !p.Calls.Any(c => c.StartsWith("current:", StringComparison.Ordinal)), "uia-tree: zero cap still acquires Descendants but no Current");
        accepted.FailProperties.Clear(); accepted.Values[ObservationProperty.LocalizedControlType] = null;
        p.Nodes.Clear(); p.Nodes.Add(accepted);
        result = a.UiaTree(new ObservationOptions());
        check(((OrderedDictionary[])result.Payload["affordances"])[0]["role"] == null, "uia-tree: successful null localized role stays null");
    }

    private static void FindChecks(Action<bool, string> check)
    {
        var p = new InertProvider(); var a = new ObservationActions(p);
        var result = a.UiaFind(new ObservationOptions());
        check(result.ExitCode == 1 && Equals(result.Payload["reason"], "missing_label") && p.Calls.Count == 0, "uia-find: label gate precedes acquisition");
        result = a.UiaFind(new ObservationOptions { Label = "Save", Match = "missing" });
        check(result.ExitCode == 2 && Equals(result.Payload["reason"], "no_matching_window"), "uia-find: no unmatched foreground fallback");
        p.Root = null; result = a.UiaFind(new ObservationOptions { Label = "Save" });
        check(Equals(result.Payload["reason"], "uia_root_null"), "uia-find: null root partial");
        p = new InertProvider(); a = new ObservationActions(p);
        var failOffscreen = Node("failed", "Save"); failOffscreen.FailProperties.Add(ObservationProperty.IsOffscreen);
        var wrongRole = Node("wrong-role", "Save"); wrongRole.Values[ObservationProperty.LocalizedControlType] = "edit";
        var noMatch = Node("no-match", "Other");
        var match = Node("match", " SAVE\r\n NOW "); match.Values[ObservationProperty.LocalizedControlType] = "";
        match.Patterns.Add(ObservationPattern.Toggle); match.Patterns.Add(ObservationPattern.Value); match.ValueReadFailure = true;
        match.Clickable = true; match.ClickX = 1000; match.ClickY = -1000; match.Rect = new ObservationRect { X = 10, Y = 20, Width = 20, Height = 10 };
        var after = Node("after", "Save Now");
        p.Nodes.AddRange(new[] { failOffscreen, wrongRole, noMatch, match, after });
        result = a.UiaFind(new ObservationOptions { Label = "save\t now", Role = "button", MaxElements = 1, ClickInset = 3 });
        check(result.ExitCode == 0 && Equals(result.Payload["ambiguous"], false), "uia-find: unique accepted match");
        check(result.Payload["candidates"] is OrderedDictionary, "uia-find: singleton candidates is scalar");
        var top = (OrderedDictionary)result.Payload["top"];
        check(Equals(top["score"], 100) && Equals(top["match_reason"], "exact"), "uia-find: label/hay whitespace normalization");
        check(Equals(top["role"], ""), "uia-find: empty localized role passes supplied Role filter");
        check(Equals(top["invoke_pattern"], "TogglePattern") && Equals(top["value_pattern"], true) && top["value_readonly"] == null, "uia-find: pattern priority and partial Value read failure");
        var click = (OrderedDictionary)top["click_point"];
        check(Equals(click["x"], 27) && Equals(click["y"], 23) && Equals(click["native_clickable"], true), "uia-find: native clickable point clamped by inset");
        check(!p.Calls.Contains("current:after"), "uia-find: accepted-only MaxElements stops later current");
        check(!p.Calls.Contains("property:failed:Name"), "uia-find: throwing IsOffscreen drops element before name");
        check(!p.Calls.Any(c => c.EndsWith(":ClassName", StringComparison.Ordinal) || c.EndsWith(":IsEnabled", StringComparison.Ordinal)), "uia-find: does not read ClassName or IsEnabled");
        check(p.Calls.Where(c => c.StartsWith("property:match:", StringComparison.Ordinal)).SequenceEqual(new[] {
            "property:match:IsOffscreen", "property:match:Name", "property:match:AutomationId", "property:match:HelpText", "property:match:AccessKey", "property:match:LocalizedControlType" }), "uia-find: exact property order");
        check(Keys(top) == "text,role,rect,center,click_point,score,match_reason,automation_id,invoke_pattern,value_pattern,value_readonly", "uia-find: candidate field order");
        check(Keys(result.Payload) == "status,label,top,candidates,ambiguous", "uia-find: envelope field order");
        check(p.UiaChecks == 0, "uia-find: adapter owns initial UIA availability check");
        p = new InertProvider(); a = new ObservationActions(p);
        p.Nodes.Add(Node("exact", "Save")); p.Nodes.Add(Node("second", "Save12345678"));
        result = a.UiaFind(new ObservationOptions { Label = "Save" });
        check(result.ExitCode == 0 && Equals(result.Payload["ambiguous"], false), "uia-find: score gap exactly eight is unambiguous");
        p.Nodes[1].Values[ObservationProperty.Name] = "Save1234567";
        result = a.UiaFind(new ObservationOptions { Label = "Save" });
        check(result.ExitCode == 2 && Equals(result.Payload["ambiguous"], true), "uia-find: score gap seven is ambiguous");
        check(result.Payload["candidates"] is OrderedDictionary[], "uia-find: multiple candidates is array");
        p.Nodes.Clear(); p.Nodes.Add(Node("prefix", "satin"));
        result = a.UiaFind(new ObservationOptions { Label = "save" });
        check(Equals(((OrderedDictionary)result.Payload["top"])["score"], 15) && Equals(((OrderedDictionary)result.Payload["top"])["match_reason"], "prefix"), "uia-find: two-character prefix score");
        p.Nodes.Clear(); p.Nodes.Add(Node("literal", "prefix [a].* suffix"));
        result = a.UiaFind(new ObservationOptions { Label = "[a].*" });
        check(Equals(((OrderedDictionary)result.Payload["top"])["match_reason"], "substring"), "uia-find: regex metacharacters escaped literally");
        p.Nodes.Clear(); var access = Node("access", ""); access.Values[ObservationProperty.AccessKey] = "Ctrl+S"; p.Nodes.Add(access);
        result = a.UiaFind(new ObservationOptions { Label = "Ctrl+S" });
        check(Equals(((OrderedDictionary)result.Payload["top"])["text"], "") && Equals(((OrderedDictionary)result.Payload["top"])["score"], 100), "uia-find: AccessKey can match with empty output text");
        access.Values[ObservationProperty.Name] = " "; access.Values[ObservationProperty.AutomationId] = "save";
        result = a.UiaFind(new ObservationOptions { Label = "save" });
        check(Equals(((OrderedDictionary)result.Payload["top"])["text"], " "), "uia-find: output text truth differs from non-whitespace scoring filter");
        p.Nodes.Clear(); p.Nodes.Add(Node("blank-label", "abc"));
        result = a.UiaFind(new ObservationOptions { Label = " " });
        check(result.ExitCode == 0 && Equals(((OrderedDictionary)result.Payload["top"])["score"], 97), "uia-find: whitespace-only label preserves empty substring behavior");
        p.Nodes.Clear();
        for (int i = 0; i < 20; i++) p.Nodes.Add(Node("tie-" + i, "Save"));
        result = a.UiaFind(new ObservationOptions { Label = "Save" });
        check(((OrderedDictionary[])result.Payload["candidates"]).Length == 5 && Equals(result.Payload["ambiguous"], true), "uia-find: top five cap on large tied set");
        // Tied order deliberately not asserted as stable: net48/Windows PowerShell oracle is separate qualification.
        p.Nodes.Clear(); p.Nodes.Add(Node("none", "Other"));
        result = a.UiaFind(new ObservationOptions { Label = "Save" });
        check(result.ExitCode == 2 && Equals(result.Payload["reason"], "no_match") && Equals(result.Payload["label"], "Save"), "uia-find: no match envelope");
        p.Calls.Clear(); result = a.UiaFind(new ObservationOptions { Label = "Save", MaxElements = -1 });
        check(result.ExitCode == 2 && !p.Calls.Any(c => c.StartsWith("current:", StringComparison.Ordinal)), "uia-find: negative cap yields no accepted matches");
        p = new InertProvider(); a = new ObservationActions(p); var failedBounds = Node("bounds-fail", "Save"); failedBounds.BoundsFailure = true;
        var failedCurrent = Node("current-fail", "Save"); failedCurrent.CurrentFailure = true;
        var good = Node("good", "Save"); good.PatternFailures.UnionWith(new[] { ObservationPattern.Invoke, ObservationPattern.Toggle, ObservationPattern.SelectionItem, ObservationPattern.Value }); good.ClickFailure = true;
        p.Nodes.AddRange(new[] { failedBounds, failedCurrent, good });
        result = a.UiaFind(new ObservationOptions { Label = "Save" });
        top = (OrderedDictionary)result.Payload["top"];
        check(result.ExitCode == 0 && top["invoke_pattern"] == null && Equals(top["value_pattern"], false), "uia-find: per-element and pattern exceptions isolated");
        check(Equals(((OrderedDictionary)top["click_point"])["source"], "rect_center"), "uia-find: clickable exception falls back to center");
    }

    private static string Keys(OrderedDictionary map) { return string.Join(",", map.Keys.Cast<string>()); }
    private static TestNode Node(string id, string name)
    {
        var node = new TestNode { Id = id, Rect = new ObservationRect { X = -5, Y = -5, Width = 10, Height = 10 } };
        node.Values[ObservationProperty.Name] = name;
        node.Values[ObservationProperty.AutomationId] = "";
        node.Values[ObservationProperty.HelpText] = "";
        node.Values[ObservationProperty.AccessKey] = "";
        node.Values[ObservationProperty.ClassName] = "Button";
        node.Values[ObservationProperty.LocalizedControlType] = "button";
        node.Values[ObservationProperty.IsEnabled] = true;
        node.Values[ObservationProperty.IsOffscreen] = false;
        return node;
    }
    private static TestNode ClickNode(string id, string role)
    {
        var node = Node(id, "Save"); node.Values[ObservationProperty.LocalizedControlType] = role;
        node.Patterns.Add(ObservationPattern.Invoke); node.Clickable = true;
        return node;
    }
    private sealed class TestNode
    {
        public string Id = "";
        public ObservationRect Rect = new ObservationRect();
        public readonly Dictionary<ObservationProperty, object> Values = new Dictionary<ObservationProperty, object>();
        public readonly HashSet<ObservationProperty> FailProperties = new HashSet<ObservationProperty>();
        public readonly HashSet<ObservationPattern> Patterns = new HashSet<ObservationPattern>();
        public readonly HashSet<ObservationPattern> PatternFailures = new HashSet<ObservationPattern>();
        public bool CurrentFailure, BoundsFailure, ValueReadFailure, ClickFailure, Clickable;
        public double ClickX, ClickY;
    }
    private sealed class InertProvider : IObservationProvider
    {
        public readonly List<string> Calls = new List<string>();
        public readonly List<string> WindowPoints = new List<string>();
        public readonly List<TestNode> Nodes = new List<TestNode>();
        public readonly List<ObservationWindow> Windows = new List<ObservationWindow> { new ObservationWindow { Hwnd = 10, Title = "Wanted Main", Foreground = true } };
        public object Root = "root";
        public string Title = "Wanted Main", Process = "process";
        public int Vx = -100, Vy = -100, Vw = 200, Vh = 200, UiaChecks;
        public bool UiaAvailable = true, ProcessFailure, Log = true;
        public uint RawProcessId = 42;
        public TestNode PointNode;
        public Func<int, int, long> WindowAtPoint = (x, y) => 11;
        public Func<int, int, TestNode> PointLookup;
        private void Record(string call) { if (Log) Calls.Add(call); }
        public bool EnsureUia() { Record("ensure-uia"); UiaChecks++; return UiaAvailable; }
        public long WindowFromPoint(int x, int y) { string point = x.ToString(CultureInfo.InvariantCulture) + "," + y.ToString(CultureInfo.InvariantCulture); Record("window:" + point); if (Log) WindowPoints.Add(point); return WindowAtPoint(x, y); }
        public long RootAncestor(long hwnd) { Record("root:" + hwnd); return 10; }
        public string WindowText(long hwnd, int capacity) { Record("title:" + hwnd + ":" + capacity); return hwnd == 10 ? Title : "child"; }
        public string WindowClass(long hwnd, int capacity) { Record("class:" + hwnd + ":" + capacity); return "RootClass"; }
        public uint ProcessId(long hwnd) { Record("pid:" + hwnd); return RawProcessId; }
        public string ProcessName(uint id) { Record("process:" + id); if (ProcessFailure) throw new InvalidOperationException("process exited"); return Process; }
        public int SystemMetric(int index) { Record("metric:" + index); switch (index) { case 76: return Vx; case 77: return Vy; case 78: return Vw; case 79: return Vh; default: throw new InvalidOperationException("unknown metric"); } }
        public IEnumerable<ObservationWindow> TopLevelWindows() { Record("windows"); return Windows; }
        public object FromPoint(int x, int y) { Record("point:" + x + "," + y); return PointLookup == null ? PointNode : PointLookup(x, y); }
        public object FromHandle(long hwnd) { Record("handle:" + hwnd); return Root; }
        public IEnumerable<object> Descendants(object element) { Record("descendants:" + element); return Nodes.Cast<object>(); }
        public object Current(object element) { var node = (TestNode)element; Record("current:" + node.Id); if (node.CurrentFailure) throw new InvalidOperationException("stale current"); return node; }
        public ObservationRect Bounds(object current) { var node = (TestNode)current; Record("bounds:" + node.Id); if (node.BoundsFailure) throw new InvalidOperationException("stale bounds"); return node.Rect; }
        public object Property(object current, ObservationProperty property) { var node = (TestNode)current; Record("property:" + node.Id + ":" + property); if (node.FailProperties.Contains(property)) throw new InvalidOperationException("property unavailable"); return node.Values[property]; }
        public object Pattern(object element, ObservationPattern pattern) { var node = (TestNode)element; Record("pattern:" + node.Id + ":" + pattern); if (node.PatternFailures.Contains(pattern)) throw new InvalidOperationException("pattern unavailable"); return node.Patterns.Contains(pattern) ? node : null; }
        public bool ValueReadOnly(object pattern) { var node = (TestNode)pattern; Record("value-readonly:" + node.Id); if (node.ValueReadFailure) throw new InvalidOperationException("value current unavailable"); return true; }
        public bool ClickablePoint(object element, out double x, out double y) { var node = (TestNode)element; Record("clickable:" + node.Id); if (node.ClickFailure) throw new InvalidOperationException("click point unavailable"); x = node.ClickX; y = node.ClickY; return node.Clickable; }
        public object ControlViewWalker() { Record("walker"); return "walker"; }
        public object Parent(object walker, object element) { Record("parent:" + ((TestNode)element).Id); return null; }
    }
}
