using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class CucpWin32 {
  public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

  [DllImport("user32.dll")]
  public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

  [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
  public static extern int GetWindowTextLength(IntPtr hWnd);

  [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

  [DllImport("user32.dll")]
  public static extern bool IsWindowVisible(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool IsIconic(IntPtr hWnd);

  [DllImport("user32.dll", SetLastError = true)]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

  [DllImport("user32.dll")]
  public static extern IntPtr GetForegroundWindow();

  public const uint GA_ROOT = 2;

  [StructLayout(LayoutKind.Sequential)]
  public struct POINT { public int X; public int Y; }

  [DllImport("user32.dll")]
  public static extern IntPtr WindowFromPoint(POINT point);

  [DllImport("user32.dll")]
  public static extern IntPtr GetAncestor(IntPtr hwnd, uint gaFlags);

  [DllImport("user32.dll", CharSet = CharSet.Auto)]
  public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

  [DllImport("user32.dll")]
  public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

  public class WindowInfo {
    public IntPtr Hwnd;
    public IntPtr ChildHwnd;
    public string Title;
    public string ClassName;
    public uint Pid;
    public string ProcessName;
    public bool Visible;
    public bool Minimized;
    public bool Foreground;
    public int X; public int Y; public int Width; public int Height;
  }

  public class MonitorInfo {
    public string DeviceName;
    public bool Primary;
    public int X; public int Y; public int Width; public int Height;
    public int WorkX; public int WorkY; public int WorkWidth; public int WorkHeight;
    public uint DpiX; public uint DpiY;
    public double ScaleX; public double ScaleY;
  }

  public class VirtualScreenInfo {
    public int X; public int Y; public int Width; public int Height;
    public int MonitorCount;
    public bool SameDisplayFormat;
  }

  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
  public struct MONITORINFOEX {
    public int cbSize;
    public RECT rcMonitor;
    public RECT rcWork;
    public uint dwFlags;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
    public string szDevice;
  }

  public delegate bool MonitorEnumProc(IntPtr hMonitor, IntPtr hdcMonitor, ref RECT lprcMonitor, IntPtr dwData);

  [DllImport("user32.dll")]
  public static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr lprcClip, MonitorEnumProc lpfnEnum, IntPtr dwData);

  [DllImport("user32.dll", CharSet = CharSet.Auto)]
  public static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFOEX lpmi);

  [DllImport("user32.dll")]
  public static extern IntPtr MonitorFromPoint(POINT pt, uint dwFlags);

  [DllImport("user32.dll")]
  public static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint dwFlags);

  [DllImport("user32.dll")]
  public static extern int GetSystemMetrics(int nIndex);

  [DllImport("shcore.dll")]
  public static extern int GetDpiForMonitor(IntPtr hmonitor, int dpiType, out uint dpiX, out uint dpiY);

  [DllImport("user32.dll")]
  public static extern uint GetDpiForWindow(IntPtr hwnd);

  public static MonitorInfo BuildMonitorInfo(IntPtr hMonitor) {
    var mi = new MONITORINFOEX();
    mi.cbSize = Marshal.SizeOf(typeof(MONITORINFOEX));
    if (!GetMonitorInfo(hMonitor, ref mi)) return null;
    uint dx = 96, dy = 96;
    try { GetDpiForMonitor(hMonitor, 0, out dx, out dy); } catch { dx = 96; dy = 96; }
    return new MonitorInfo {
      DeviceName = mi.szDevice,
      Primary = ((mi.dwFlags & 1) == 1),
      X = mi.rcMonitor.Left,
      Y = mi.rcMonitor.Top,
      Width = mi.rcMonitor.Right - mi.rcMonitor.Left,
      Height = mi.rcMonitor.Bottom - mi.rcMonitor.Top,
      WorkX = mi.rcWork.Left,
      WorkY = mi.rcWork.Top,
      WorkWidth = mi.rcWork.Right - mi.rcWork.Left,
      WorkHeight = mi.rcWork.Bottom - mi.rcWork.Top,
      DpiX = dx,
      DpiY = dy,
      ScaleX = Math.Round(dx / 96.0, 4),
      ScaleY = Math.Round(dy / 96.0, 4)
    };
  }

  public static List<MonitorInfo> EnumerateMonitors() {
    var result = new List<MonitorInfo>();
    EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, delegate (IntPtr hMonitor, IntPtr hdc, ref RECT rc, IntPtr data) {
      try {
        var info = BuildMonitorInfo(hMonitor);
        if (info != null) result.Add(info);
      } catch { }
      return true;
    }, IntPtr.Zero);
    return result;
  }

  public static MonitorInfo MonitorFromScreenPointInfo(int x, int y) {
    POINT pt = new POINT { X = x, Y = y };
    IntPtr h = MonitorFromPoint(pt, 2);
    if (h == IntPtr.Zero) return null;
    return BuildMonitorInfo(h);
  }

  public static MonitorInfo MonitorFromWindowInfo(IntPtr hwnd) {
    IntPtr h = MonitorFromWindow(hwnd, 2);
    if (h == IntPtr.Zero) return null;
    return BuildMonitorInfo(h);
  }

  public static uint GetWindowDpiValue(IntPtr hwnd) {
    try { return GetDpiForWindow(hwnd); } catch { return 0; }
  }

  public static VirtualScreenInfo GetVirtualScreenInfo() {
    return new VirtualScreenInfo {
      X = GetSystemMetrics(76),
      Y = GetSystemMetrics(77),
      Width = GetSystemMetrics(78),
      Height = GetSystemMetrics(79),
      MonitorCount = GetSystemMetrics(80),
      SameDisplayFormat = (GetSystemMetrics(81) != 0)
    };
  }

  public static WindowInfo GetWindowInfo(IntPtr root, IntPtr child) {
    if (root == IntPtr.Zero) return null;
    int len = GetWindowTextLength(root);
    var sb = new StringBuilder(Math.Max(256, len + 4));
    GetWindowText(root, sb, sb.Capacity);
    var title = sb.ToString();
    var cb = new StringBuilder(256);
    GetClassName(root, cb, cb.Capacity);
    var cls = cb.ToString();
    uint pid; GetWindowThreadProcessId(root, out pid);
    string pname = "";
    try { pname = Process.GetProcessById((int)pid).ProcessName; } catch { }
    RECT r; GetWindowRect(root, out r);
    return new WindowInfo {
      Hwnd = root,
      ChildHwnd = child,
      Title = title,
      ClassName = cls,
      Pid = pid,
      ProcessName = pname,
      Visible = IsWindowVisible(root),
      Minimized = IsIconic(root),
      Foreground = (root == GetForegroundWindow()),
      X = r.Left, Y = r.Top, Width = r.Right - r.Left, Height = r.Bottom - r.Top
    };
  }

  public static WindowInfo WindowFromScreenPoint(int x, int y) {
    POINT pt = new POINT { X = x, Y = y };
    IntPtr child = WindowFromPoint(pt);
    if (child == IntPtr.Zero) return null;
    IntPtr root = GetAncestor(child, GA_ROOT);
    if (root == IntPtr.Zero) root = child;
    return GetWindowInfo(root, child);
  }

  public static List<WindowInfo> EnumerateTopLevel() {
    var result = new List<WindowInfo>();
    IntPtr fg = GetForegroundWindow();
    EnumWindows(delegate (IntPtr hwnd, IntPtr lParam) {
      try {
        bool vis = IsWindowVisible(hwnd);
        // skip non-visible windows for the default fast path. Caller can
        // still enumerate hidden windows separately if needed.
        if (!vis) return true;
        int len = GetWindowTextLength(hwnd);
        if (len <= 0) return true;
        var sb = new StringBuilder(len + 4);
        GetWindowText(hwnd, sb, sb.Capacity);
        var title = sb.ToString();
        if (string.IsNullOrWhiteSpace(title)) return true;
        var cb = new StringBuilder(256);
        GetClassName(hwnd, cb, cb.Capacity);
        var cls = cb.ToString();
        // skip well-known shell/system windows that pollute the list.
        if (cls == "Progman" || cls == "WorkerW" || cls == "Shell_TrayWnd" ||
            cls == "Shell_SecondaryTrayWnd" || cls == "TaskListThumbnailWnd" ||
            cls == "ApplicationFrameWindow" && (title == "Settings" || title == "Microsoft Store") == false) {
          // ApplicationFrameWindow는 UWP 컨테이너인데 진짜 사용자 창인 경우가 많아서
          // title 기준으로만 제외하지 않음. Progman/WorkerW/Shell_TrayWnd만 hard skip.
          if (cls == "Progman" || cls == "WorkerW" || cls == "Shell_TrayWnd" || cls == "Shell_SecondaryTrayWnd" || cls == "TaskListThumbnailWnd") {
            return true;
          }
        }
        uint pid; GetWindowThreadProcessId(hwnd, out pid);
        string pname = "";
        try { pname = Process.GetProcessById((int)pid).ProcessName; } catch { }
        RECT r; GetWindowRect(hwnd, out r);
        var info = new WindowInfo {
          Hwnd = hwnd,
          ChildHwnd = hwnd,
          Title = title,
          ClassName = cls,
          Pid = pid,
          ProcessName = pname,
          Visible = vis,
          Minimized = IsIconic(hwnd),
          Foreground = (hwnd == fg),
          X = r.Left, Y = r.Top, Width = r.Right - r.Left, Height = r.Bottom - r.Top
        };
        result.Add(info);
      } catch { }
      return true;
    }, IntPtr.Zero);
    return result;
  }
}
