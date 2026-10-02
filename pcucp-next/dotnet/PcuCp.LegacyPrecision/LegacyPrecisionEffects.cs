// The in-process coordinator implements these fixed read-only operations. It
// cannot dispatch a general macro, shell command, or input action through this API.
internal readonly record struct PrecisionTargetPoint(int X, int Y, long TargetHwnd, string TargetMatch);
internal readonly record struct PrecisionScan(PrecisionTargetPoint Point, int ClickInset, int Radius, int Step);
internal readonly record struct PrecisionChildPlan(PrecisionScan Scan, int CacheSeconds, bool NoCache);
internal interface IPrecisionReadEffects
{
    object? CoordinateMap(PrecisionTargetPoint point);
    object? HitTest(PrecisionTargetPoint point);
    object? CoordinateProfile(PrecisionTargetPoint point);
    object? HitScan(PrecisionScan scan);
    object? ChildPointPlan(PrecisionChildPlan plan);
    string[] HistoryLines(string configuredPath);
    object? ReadCache(string configuredDirectory, string key, int maximumAgeSeconds);
}
