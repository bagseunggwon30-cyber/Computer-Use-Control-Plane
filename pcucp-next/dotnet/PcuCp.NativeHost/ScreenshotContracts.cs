internal sealed record ScreenshotImage(string MimeType, string Data, int Width, int Height);
internal sealed record ScreenshotGeometry(int X, int Y, int Width, int Height, int ImageWidth, int ImageHeight);
internal sealed record ScreenshotData(ScreenshotImage Image, object Target, ScreenshotGeometry Geometry,
    PixelRect WindowGeometry, string CapturedAt, string CoordinateSpace, string CaptureSemantics,
    bool TargetForeground, bool CursorIncluded);
