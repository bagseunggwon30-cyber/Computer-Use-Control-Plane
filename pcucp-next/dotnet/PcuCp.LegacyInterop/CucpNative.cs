using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class CucpNative {
  // ----- delegates -----
  public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

  // ----- window enum -----
  [DllImport("user32.dll")]
  public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

  [DllImport("user32.dll", CharSet = CharSet.Auto)]
  public static extern int GetWindowTextLength(IntPtr hWnd);

  [DllImport("user32.dll", CharSet = CharSet.Auto)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

  [DllImport("user32.dll", CharSet = CharSet.Auto)]
  public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

  [DllImport("user32.dll")]
  public static extern bool IsWindowVisible(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool IsIconic(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool SetProcessDPIAware();

  [DllImport("user32.dll")]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

  [DllImport("user32.dll")]
  public static extern IntPtr GetForegroundWindow();

  [DllImport("user32.dll")]
  public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

  // ----- focus / show -----
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

  [DllImport("user32.dll")]
  public static extern bool BringWindowToTop(IntPtr hWnd);

  // ----- cursor -----
  [DllImport("user32.dll")]
  public static extern bool GetCursorPos(out POINT lpPoint);

  [DllImport("user32.dll")]
  public static extern bool SetCursorPos(int X, int Y);

  // ----- input injection (SendInput) -----
  [DllImport("user32.dll", SetLastError = true)]
  public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

  [DllImport("user32.dll", SetLastError = true)]
  public static extern short VkKeyScan(char ch);

  [DllImport("user32.dll", SetLastError = true)]
  public static extern uint MapVirtualKey(uint uCode, uint uMapType);

  // ----- desktop bounds -----
  [DllImport("user32.dll")]
  public static extern int GetSystemMetrics(int nIndex);

  // ----- v1.2.0: hit-testing — 좌표가 진짜 어떤 윈도우 안인지 클릭 전 검증 -----
  // WindowFromPoint: 화면 좌표를 받아 그 위치의 child window hwnd 반환
  // GetAncestor + GA_ROOT: child hwnd → top-level (root) hwnd 로 변환
  // 이 둘을 조합하면 "좌표가 어느 top-level 윈도우 안인지" 결정론적으로 판단 가능.
  // (GetWindowThreadProcessId 는 이미 위에 정의돼 있어 재선언 안 함)
  [DllImport("user32.dll")]
  public static extern IntPtr WindowFromPoint(POINT Point);

  [DllImport("user32.dll")]
  public static extern IntPtr GetAncestor(IntPtr hwnd, uint gaFlags);

  public const uint GA_PARENT  = 1;
  public const uint GA_ROOT    = 2;
  public const uint GA_ROOTOWNER = 3;

  // ----- structs -----
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

  [StructLayout(LayoutKind.Sequential)]
  public struct POINT { public int X; public int Y; }

  [StructLayout(LayoutKind.Sequential)]
  public struct MOUSEINPUT {
    public int dx; public int dy;
    public uint mouseData; public uint dwFlags;
    public uint time; public IntPtr dwExtraInfo;
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct KEYBDINPUT {
    public ushort wVk; public ushort wScan;
    public uint dwFlags; public uint time;
    public IntPtr dwExtraInfo;
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct HARDWAREINPUT {
    public uint uMsg; public ushort wParamL; public ushort wParamH;
  }

  [StructLayout(LayoutKind.Explicit)]
  public struct INPUTUNION {
    [FieldOffset(0)] public MOUSEINPUT mi;
    [FieldOffset(0)] public KEYBDINPUT ki;
    [FieldOffset(0)] public HARDWAREINPUT hi;
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct INPUT {
    public uint type;          // 0=mouse, 1=keyboard, 2=hardware
    public INPUTUNION u;
  }

  // ----- constants -----
  public const uint INPUT_MOUSE = 0;
  public const uint INPUT_KEYBOARD = 1;

  // mouse flags
  public const uint MOUSEEVENTF_MOVE        = 0x0001;
  public const uint MOUSEEVENTF_LEFTDOWN    = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP      = 0x0004;
  public const uint MOUSEEVENTF_RIGHTDOWN   = 0x0008;
  public const uint MOUSEEVENTF_RIGHTUP     = 0x0010;
  public const uint MOUSEEVENTF_MIDDLEDOWN  = 0x0020;
  public const uint MOUSEEVENTF_MIDDLEUP    = 0x0040;
  public const uint MOUSEEVENTF_ABSOLUTE    = 0x8000;
  public const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;

  // keyboard flags
  public const uint KEYEVENTF_KEYUP   = 0x0002;
  public const uint KEYEVENTF_UNICODE = 0x0004;
  public const uint KEYEVENTF_SCANCODE = 0x0008;

  // virtual keys (subset)
  public const ushort VK_CONTROL = 0x11;
  public const ushort VK_SHIFT   = 0x10;
  public const ushort VK_MENU    = 0x12;     // Alt
  public const ushort VK_LWIN    = 0x5B;
  public const ushort VK_RETURN  = 0x0D;
  public const ushort VK_TAB     = 0x09;
  public const ushort VK_ESCAPE  = 0x1B;
  public const ushort VK_BACK    = 0x08;
  public const ushort VK_DELETE  = 0x2E;
  public const ushort VK_SPACE   = 0x20;

  // GetSystemMetrics indices
  public const int SM_CXVIRTUALSCREEN = 78;
  public const int SM_CYVIRTUALSCREEN = 79;
  public const int SM_XVIRTUALSCREEN  = 76;
  public const int SM_YVIRTUALSCREEN  = 77;
  public const int SM_CXSCREEN        = 0;
  public const int SM_CYSCREEN        = 1;

  // ShowWindow nCmdShow
  public const int SW_RESTORE = 9;
  public const int SW_SHOW    = 5;

  // ----- helpers -----
  public class WindowInfo {
    public IntPtr Hwnd;
    public string Title;
    public string ClassName;
    public uint Pid;
    public string ProcessName;
    public bool Visible;
    public bool Minimized;
    public bool Foreground;
    public int X, Y, Width, Height;
  }

  public static List<WindowInfo> EnumerateTopLevel() {
    var result = new List<WindowInfo>();
    IntPtr fg = GetForegroundWindow();
    EnumWindows(delegate (IntPtr hwnd, IntPtr lParam) {
      try {
        bool vis = IsWindowVisible(hwnd);
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
        // Hard skip: Windows shell artifacts that pollute every enum
        if (cls == "Progman" || cls == "WorkerW" || cls == "Shell_TrayWnd" ||
            cls == "Shell_SecondaryTrayWnd" || cls == "TaskListThumbnailWnd") {
          return true;
        }
        uint pid; GetWindowThreadProcessId(hwnd, out pid);
        string pname = "";
        try { pname = Process.GetProcessById((int)pid).ProcessName; } catch { }
        RECT r; GetWindowRect(hwnd, out r);
        result.Add(new WindowInfo {
          Hwnd = hwnd, Title = title, ClassName = cls,
          Pid = pid, ProcessName = pname,
          Visible = vis, Minimized = IsIconic(hwnd),
          Foreground = (hwnd == fg),
          X = r.Left, Y = r.Top,
          Width = r.Right - r.Left, Height = r.Bottom - r.Top
        });
      } catch { }
      return true;
    }, IntPtr.Zero);
    return result;
  }

  // ----- mouse click via SendInput (v1.6.0: absolute-only, race-free) -----
  // 변경 사항 (v1.6.0):
  //   - SetCursorPos 제거 — SendInput absolute 와 race 발생 가능, 정확도 ↓
  //   - 단일 SendInput batch 안에서 [move, down, up] 원자적 실행
  //   - move 후 5ms 마이크로 sleep 으로 OS scheduler 가 hover state 인식하게 함
  //   - PostClickX / PostClickY 정적 필드로 호출자가 실제 도착 좌표 검증 가능
  public static int PostClickX = 0;
  public static int PostClickY = 0;
  public static int PostClickRequestedX = 0;
  public static int PostClickRequestedY = 0;
  public static void SendMouseClick(int x, int y, string button, bool doubleClick) {
    PostClickRequestedX = x;
    PostClickRequestedY = y;

    int virtW = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    int virtH = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    int virtX = GetSystemMetrics(SM_XVIRTUALSCREEN);
    int virtY = GetSystemMetrics(SM_YVIRTUALSCREEN);
    if (virtW <= 0) virtW = GetSystemMetrics(SM_CXSCREEN);
    if (virtH <= 0) virtH = GetSystemMetrics(SM_CYSCREEN);

    int normX = (int)((double)(x - virtX) * 65535 / Math.Max(1, virtW - 1));
    int normY = (int)((double)(y - virtY) * 65535 / Math.Max(1, virtH - 1));

    uint downFlag, upFlag;
    switch (button) {
      case "right":  downFlag = MOUSEEVENTF_RIGHTDOWN;  upFlag = MOUSEEVENTF_RIGHTUP;  break;
      case "middle": downFlag = MOUSEEVENTF_MIDDLEDOWN; upFlag = MOUSEEVENTF_MIDDLEUP; break;
      default:       downFlag = MOUSEEVENTF_LEFTDOWN;   upFlag = MOUSEEVENTF_LEFTUP;   break;
    }

    // Stage 1: move only — Windows hover state 인식까지 대기
    var move = new INPUT {
      type = INPUT_MOUSE,
      u = new INPUTUNION { mi = new MOUSEINPUT {
        dx = normX, dy = normY, mouseData = 0,
        dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time = 0, dwExtraInfo = IntPtr.Zero
      }}
    };
    var moveArr = new INPUT[] { move };
    SendInputChecked(moveArr);

    // 5ms micro-sleep — OS 가 hover state 디스패치할 시간 확보
    System.Threading.Thread.Sleep(5);

    // Stage 2: down + up batch — 클릭이 hover state 위에서 발생하도록
    var down = new INPUT { type = INPUT_MOUSE, u = new INPUTUNION { mi = new MOUSEINPUT { dwFlags = downFlag } } };
    var up   = new INPUT { type = INPUT_MOUSE, u = new INPUTUNION { mi = new MOUSEINPUT { dwFlags = upFlag } } };
    var clickArr = new INPUT[] { down, up };
    SendInputChecked(clickArr);

    // 도착 좌표 검증 — 호출자가 hit-test 시 사용
    POINT p;
    if (GetCursorPos(out p)) {
      PostClickX = p.X;
      PostClickY = p.Y;
    } else {
      PostClickX = x;
      PostClickY = y;
    }

    if (doubleClick) {
      System.Threading.Thread.Sleep(60);
      SendInputChecked(clickArr);
    }
  }

  private static void SendInputChecked(INPUT[] inputs) {
    uint requested = (uint)inputs.Length;
    uint inserted = SendInput(requested, inputs, Marshal.SizeOf(typeof(INPUT)));
    if (inserted != requested) {
      int error = Marshal.GetLastWin32Error();
      throw new InvalidOperationException("input_injection_incomplete: inserted=" + inserted +
        ", requested=" + requested + ", win32_error=" + error +
        ". Input may be blocked by UIPI or the desktop boundary; do not replay blindly.");
    }
  }

  // ----- type text via SendInput unicode (handles Korean, emoji, etc.) -----
  public static void SendUnicodeText(string text) {
    if (string.IsNullOrEmpty(text)) return;
    var inputs = new List<INPUT>();
    foreach (char ch in text) {
      var down = new INPUT { type = INPUT_KEYBOARD, u = new INPUTUNION { ki = new KEYBDINPUT {
        wVk = 0, wScan = (ushort)ch, dwFlags = KEYEVENTF_UNICODE,
        time = 0, dwExtraInfo = IntPtr.Zero
      }}};
      var up = down;
      up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
      inputs.Add(down);
      inputs.Add(up);
    }
    SendInputChecked(inputs.ToArray());
  }

  // ----- send virtual key (down/up) -----
  public static void SendVk(ushort vk, bool keyUp) {
    var input = new INPUT { type = INPUT_KEYBOARD, u = new INPUTUNION { ki = new KEYBDINPUT {
      wVk = vk, wScan = 0, dwFlags = keyUp ? KEYEVENTF_KEYUP : 0,
      time = 0, dwExtraInfo = IntPtr.Zero
    }}};
    var arr = new INPUT[] { input };
    SendInputChecked(arr);
  }
}
