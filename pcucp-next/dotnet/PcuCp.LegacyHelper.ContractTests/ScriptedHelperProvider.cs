using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace PcuCp.LegacyHelper
{
    // Shared by the net8 contract runner and the net48 host's explicit --fixture
    // route. Captures are data only; this class has no reference to real providers.
    public sealed class ScriptedHelperProvider : ILegacyHelperProvider
    {
        private readonly IList<object> expected;
        public readonly List<object> Calls = new List<object>();
        public int Consumed { get; private set; }
        public ScriptedHelperProvider(object calls)
        { expected = RequireSequence(calls, "calls").ToList(); }
        internal static IEnumerable<object> RequireSequence(object value, string name)
        {
            if (!(value is IEnumerable) || value is string || value is IDictionary)
                throw new LegacyHelperFixtureException("Fixture " + name + " must be an explicit array");
            return ((IEnumerable)value).Cast<object>();
        }
        internal static IEnumerable<object> Sequence(object value)
        { return value is IEnumerable && !(value is string) && !(value is IDictionary) ? ((IEnumerable)value).Cast<object>() : Enumerable.Empty<object>(); }
        private static bool Equal(object left, object right)
        {
            if (left == null || right == null) return left == right;
            var leftMap = left as IDictionary<string, object>; var rightMap = right as IDictionary<string, object>;
            if (leftMap != null || rightMap != null)
            {
                if (leftMap == null || rightMap == null || leftMap.Count != rightMap.Count) return false;
                return leftMap.All(pair => rightMap.ContainsKey(pair.Key) && Equal(pair.Value, rightMap[pair.Key]));
            }
            if (left is IEnumerable && !(left is string) || right is IEnumerable && !(right is string))
            {
                if (!(left is IEnumerable) || left is string || !(right is IEnumerable) || right is string) return false;
                var l = Sequence(left).ToList(); var r = Sequence(right).ToList();
                return l.Count == r.Count && l.Zip(r, Equal).All(x => x);
            }
            if (left is string || right is string || left is bool || right is bool) return left.Equals(right);
            try { return Convert.ToDecimal(left, CultureInfo.InvariantCulture) == Convert.ToDecimal(right, CultureInfo.InvariantCulture); }
            catch (Exception) { return left.Equals(right); }
        }
        public object Invoke(string operation, params object[] arguments)
        {
            Calls.Add(LegacyHelperActions.Map("op", operation, "args", arguments));
            if (Consumed >= expected.Count) throw new LegacyHelperFixtureException("Unplanned provider access: " + operation);
            var capture = expected[Consumed] as IDictionary<string, object>;
            if (capture == null) throw new LegacyHelperFixtureException("Capture is not an object at " + Consumed);
            var op = LegacyHelperActions.Property(capture, "op") as string;
            if (op != operation) throw new LegacyHelperFixtureException("Expected " + op + " but observed " + operation + " at " + Consumed);
            if (!capture.ContainsKey("args")) throw new LegacyHelperFixtureException("Capture has no explicit args at " + Consumed);
            if (!Equal(capture["args"], arguments)) throw new LegacyHelperFixtureException("Argument mismatch for " + operation + " at " + Consumed);
            Consumed++;
            if (capture.ContainsKey("throw")) throw new InvalidOperationException(Convert.ToString(capture["throw"], CultureInfo.InvariantCulture));
            if (!capture.ContainsKey("result")) throw new LegacyHelperFixtureException("Capture has neither result nor throw at " + (Consumed - 1));
            return capture["result"];
        }
        public void EnumerateWindows(Action<long> visit)
        { foreach (var handle in Sequence(Invoke("win32.enumerate"))) visit(Convert.ToInt64(handle, CultureInfo.InvariantCulture)); }
        public void AssertExhausted()
        { if (Consumed != expected.Count) throw new LegacyHelperFixtureException("Unused provider captures: " + (expected.Count - Consumed)); }
    }

    public static class LegacyHelperFixtureRunner
    {
        public static Dictionary<string, object> Evaluate(IDictionary<string, object> fixture)
        {
            var provider = new ScriptedHelperProvider(LegacyHelperActions.Property(fixture, "calls"));
            var clocks = ScriptedHelperProvider.RequireSequence(LegacyHelperActions.Property(fixture, "clock"), "clock").ToList();
            int clockCursor = 0;
            var oldCulture = CultureInfo.CurrentCulture; var oldUiCulture = CultureInfo.CurrentUICulture;
            string culture = LegacyHelperActions.Property(fixture, "culture") as string ?? "en-US";
            try
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture);
                CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo(culture);
                Func<DateTime> clock = () =>
                {
                    if (clockCursor >= clocks.Count) throw new LegacyHelperFixtureException("Unplanned clock access at " + clockCursor);
                    return DateTime.Parse(Convert.ToString(clocks[clockCursor++], CultureInfo.InvariantCulture), CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);
                };
                int pid = Convert.ToInt32(LegacyHelperActions.Property(fixture, "pid") ?? 123, CultureInfo.InvariantCulture);
                string pipe = LegacyHelperActions.Property(fixture, "pipe_name") as string ?? "fixture";
                var actions = new LegacyHelperActions(provider, pid, pipe, clock);
                var requests = fixture.ContainsKey("requests")
                    ? ScriptedHelperProvider.RequireSequence(fixture["requests"], "requests").ToList() : new List<object>();
                if (requests.Count == 0 && fixture.ContainsKey("action")) requests.Add(fixture);
                var responses = new List<object>();
                foreach (IDictionary<string, object> request in requests)
                {
                    Dictionary<string, object> result = null; string error = null; int exit = 0;
                    try
                    {
                        result = actions.Dispatch(LegacyHelperActions.Text(LegacyHelperActions.Property(request, "action")), LegacyHelperActions.Property(request, "args") as IDictionary<string, object>);
                        string status = result["status"] as string;
                        exit = status == "error" ? 1 : status == "partial" ? 2 : status == "fallback_required" ? 99 : 0;
                    }
                    catch (Exception failure) when (!(failure is LegacyHelperFixtureException)) { error = failure.Message; exit = 1; }
                    responses.Add(LegacyHelperActions.Map("id", LegacyHelperActions.Property(request, "id"), "exit_code", exit, "result", result, "error", error));
                }
                provider.AssertExhausted();
                if (clockCursor != clocks.Count) throw new LegacyHelperFixtureException("Unused clock captures: " + (clocks.Count - clockCursor));
                return LegacyHelperActions.Map("responses", responses.ToArray(), "calls", provider.Calls.ToArray(), "consumed", provider.Consumed, "clock_consumed", clockCursor,
                    "state", LegacyHelperActions.Map("request_count", actions.RequestCount, "win32_loaded", actions.Win32Loaded, "uia_loaded", actions.UiaLoaded,
                        "ocr_warm", actions.OcrWarm, "started_at", actions.StartedAt.ToString("o", CultureInfo.InvariantCulture)));
            }
            finally { CultureInfo.CurrentCulture = oldCulture; CultureInfo.CurrentUICulture = oldUiCulture; }
        }
    }
}
