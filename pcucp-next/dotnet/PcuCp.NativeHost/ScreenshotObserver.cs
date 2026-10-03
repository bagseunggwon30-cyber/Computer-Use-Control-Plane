using System.IO;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;

internal static class ScreenshotObserver
{
    public static NativeResult Observe(CommandOptions options)
    {
        options.Allow("--hwnd", "--pid", "--max-width", "--max-height");
        var target = WindowTarget.Read(options, false);
        var maximumWidth = options.Integer("--max-width", 1600, 64, 4096);
        var maximumHeight = options.Integer("--max-height", 1000, 64, 4096);
        return NativeResult.Ok("screenshot", CaptureWindow(target, maximumWidth, maximumHeight));
    }

    internal static ScreenshotData CaptureWindow(WindowTarget target, int maximumWidth, int maximumHeight)
    {
        PrivilegeInspector.RequireDefaultDesktop();
        if (!NativeMethods.IsWindowVisible(target.Hwnd) || NativeMethods.IsIconic(target.Hwnd))
            throw new NativeFailure("target_not_visible", "Cannot capture a hidden or minimized window from the visible desktop.");
        var window = target.Rect();
        var screen = NativeMethods.VirtualScreen;
        var left = Math.Max(window.X, screen.X);
        var top = Math.Max(window.Y, screen.Y);
        var right = Math.Min((long)window.X + window.Width, (long)screen.X + screen.Width);
        var bottom = Math.Min((long)window.Y + window.Height, (long)screen.Y + screen.Height);
        var width = checked((int)(right - left));
        var height = checked((int)(bottom - top));
        if (width <= 0 || height <= 0) throw new NativeFailure("target_offscreen", "The target does not intersect the virtual desktop.");
        if ((long)width * height > 32_000_000) throw new NativeFailure("capture_too_large", "Capture exceeds the 32-megapixel allocation limit.");
        var image = Capture(left, top, width, height);
        target.Validate(false);
        if (window != target.Rect()) throw new NativeFailure("geometry_changed", "Window moved during capture; observe again.");
        var scale = Math.Min(1.0, Math.Min((double)maximumWidth / width, (double)maximumHeight / height));
        BitmapSource output = image;
        if (scale < 1)
        {
            output = new TransformedBitmap(image, new ScaleTransform(scale, scale));
            output.Freeze();
        }
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(output));
        using var stream = new MemoryStream();
        encoder.Save(stream);
        if (stream.Length > 24 * 1024 * 1024) throw new NativeFailure("capture_too_large", "Encoded screenshot exceeds the 24 MiB limit.");
        return new ScreenshotData(
            new ScreenshotImage("image/png", Convert.ToBase64String(stream.ToArray()), output.PixelWidth, output.PixelHeight),
            target.Identity, new ScreenshotGeometry(left, top, width, height, output.PixelWidth, output.PixelHeight), window,
            DateTimeOffset.UtcNow.ToString("O"), "physical_screen_pixels", "visible_desktop_crop_may_include_occluding_windows",
            NativeMethods.GetForegroundWindow() == target.Hwnd, false);
    }

    private static BitmapSource Capture(int x, int y, int width, int height)
    {
        var screen = NativeMethods.GetDC(IntPtr.Zero);
        if (screen == IntPtr.Zero) throw new NativeFailure("capture_failed", "Cannot acquire desktop device context.");
        IntPtr memory = IntPtr.Zero, bitmap = IntPtr.Zero, previous = IntPtr.Zero;
        try
        {
            memory = NativeMethods.CreateCompatibleDC(screen);
            bitmap = NativeMethods.CreateCompatibleBitmap(screen, width, height);
            if (memory == IntPtr.Zero || bitmap == IntPtr.Zero) throw new NativeFailure("capture_failed", "Cannot allocate capture bitmap.");
            previous = NativeMethods.SelectObject(memory, bitmap);
            if (previous == IntPtr.Zero || previous == new IntPtr(-1)) throw new NativeFailure("capture_failed", "Cannot select capture bitmap.");
            if (!NativeMethods.BitBlt(memory, 0, 0, width, height, screen, x, y, 0x00CC0020 | 0x40000000))
                throw new NativeFailure("capture_failed", $"Desktop capture failed (Win32 {Marshal.GetLastWin32Error()}).");
            var image = Imaging.CreateBitmapSourceFromHBitmap(bitmap, IntPtr.Zero, Int32Rect.Empty, BitmapSizeOptions.FromEmptyOptions());
            image.Freeze();
            return image;
        }
        finally
        {
            if (previous != IntPtr.Zero && previous != new IntPtr(-1)) NativeMethods.SelectObject(memory, previous);
            if (bitmap != IntPtr.Zero) NativeMethods.DeleteObject(bitmap);
            if (memory != IntPtr.Zero) NativeMethods.DeleteDC(memory);
            NativeMethods.ReleaseDC(IntPtr.Zero, screen);
        }
    }
}
