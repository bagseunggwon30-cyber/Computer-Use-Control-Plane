// Uniquely named synthetic acquisition facades for pinned PowerShell actions.
// oracle.ps1 substitutes only verified AST type-name extents, then checks every
// resolved type against this exact emitted assembly before importing actions.
// This file
// has no P/Invoke, input, process launch, file capture, or real desktop access.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using System.Web.Script.Serialization;

namespace CucpFixture
{
public static class HelperFixture
{
    public static IDictionary<string, object> Data;
    public static List<object> Effects = new List<object>();
    public static void Trace(string op, params object[] args) { Effects.Add(new Dictionary<string,object> { {"op", op}, {"args", args} }); }
    public static void Initialize(string json) { Data = (IDictionary<string, object>)new JavaScriptSerializer().DeserializeObject(json); Effects.Clear(); }
    public static object Get(IDictionary<string, object> obj, string name, object fallback = null)
    { object value; return obj != null && obj.TryGetValue(name, out value) ? value : fallback; }
    public static IDictionary<string, object> Map(object value) { return value as IDictionary<string, object>; }
    public static IEnumerable Values(object value) { return value as IEnumerable ?? new object[0]; }
    public static IDictionary<string, object> Window(IntPtr handle)
    {
        foreach (object item in Values(Get(Data, "windows"))) { var map = Map(item); if (Convert.ToInt64(Get(map, "hwnd")) == handle.ToInt64()) return map; }
        throw new InvalidOperationException("Unplanned synthetic HWND: " + handle);
    }
    public static void Fail(IDictionary<string, object> data, string operation)
    { if (Convert.ToString(Get(data, "throw_on")) == operation) throw new InvalidOperationException("owned fixture " + operation + " failure"); }
}
public class HelperWin32
{
    public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr parameter);
    public static IntPtr GetForegroundWindow() { HelperFixture.Trace("win32.foreground"); return new IntPtr(Convert.ToInt64(HelperFixture.Get(HelperFixture.Data, "foreground", 0))); }
    public static bool IsWindowVisible(IntPtr hwnd) { HelperFixture.Trace("win32.visible", hwnd.ToInt64()); return Convert.ToBoolean(HelperFixture.Get(HelperFixture.Window(hwnd), "visible", true)); }
    public static int GetWindowTextLength(IntPtr hwnd) { HelperFixture.Trace("win32.titleLength", hwnd.ToInt64()); return Convert.ToString(HelperFixture.Get(HelperFixture.Window(hwnd), "title", "")).Length; }
    public static int GetWindowText(IntPtr hwnd, StringBuilder builder, int maximum)
    { HelperFixture.Trace("win32.title", hwnd.ToInt64(), maximum); string value = Convert.ToString(HelperFixture.Get(HelperFixture.Window(hwnd), "title", "")); value = value.Substring(0, Math.Min(value.Length, maximum - 1)); builder.Append(value); return value.Length; }
    public static int GetClassName(IntPtr hwnd, StringBuilder builder, int maximum)
    { HelperFixture.Trace("win32.class", hwnd.ToInt64(), maximum); string value = Convert.ToString(HelperFixture.Get(HelperFixture.Window(hwnd), "class", "")); value = value.Substring(0, Math.Min(value.Length, maximum - 1)); builder.Append(value); return value.Length; }
    public static uint GetWindowThreadProcessId(IntPtr hwnd, out int pid) { HelperFixture.Trace("win32.pid", hwnd.ToInt64()); pid = Convert.ToInt32(HelperFixture.Get(HelperFixture.Window(hwnd), "pid", 0)); return 1; }
    public static bool GetWindowRect(IntPtr hwnd, ref RECT rect)
    { HelperFixture.Trace("win32.rect", hwnd.ToInt64()); var r = HelperFixture.Map(HelperFixture.Get(HelperFixture.Window(hwnd), "rect")); rect.Left = Convert.ToInt32(HelperFixture.Get(r, "x")); rect.Top = Convert.ToInt32(HelperFixture.Get(r, "y")); rect.Right = rect.Left + Convert.ToInt32(HelperFixture.Get(r, "w")); rect.Bottom = rect.Top + Convert.ToInt32(HelperFixture.Get(r, "h")); return true; }
    public static bool EnumWindows(EnumWindowsProc visit, IntPtr parameter)
    { HelperFixture.Trace("win32.enumerate"); foreach (object item in HelperFixture.Values(HelperFixture.Get(HelperFixture.Data, "windows"))) if (!visit(new IntPtr(Convert.ToInt64(HelperFixture.Get(HelperFixture.Map(item), "hwnd"))), parameter)) break; return true; }
}
namespace System.Windows.Automation
{
    public enum TreeScope { Children, Subtree }
    public class Condition { public static Condition TrueCondition = new Condition(); }
    public class PropertyCondition : Condition { public PropertyCondition(object property, object value) { } }
    public class OrCondition : Condition { public OrCondition(params Condition[] conditions) { } }
    public class ControlType { public static object Window = new object(), Pane = new object(); }
    public class FixtureRect { public double X, Y, Width, Height; }
    public class FixtureCurrent
    {
        public IDictionary<string,object> Data;
        private string Token { get { return Convert.ToString(HelperFixture.Get(Data,"id")); } }
        public string Name { get { HelperFixture.Trace("uia.name",Token); return Convert.ToString(HelperFixture.Get(Data,"name","")); } }
        public string ClassName { get { HelperFixture.Trace("uia.class",Token); return Convert.ToString(HelperFixture.Get(Data,"class","")); } }
        public string LocalizedControlType { get { HelperFixture.Trace("uia.controlType",Token); return Convert.ToString(HelperFixture.Get(Data,"control_type","")); } }
        public int NativeWindowHandle { get { HelperFixture.Trace("uia.handle",Token); return Convert.ToInt32(HelperFixture.Get(Data,"hwnd",0)); } }
        public FixtureRect BoundingRectangle { get { HelperFixture.Trace("uia.rect",Token); var r=HelperFixture.Map(HelperFixture.Get(Data,"rect")); return new FixtureRect { X=Convert.ToDouble(HelperFixture.Get(r,"x",0)),Y=Convert.ToDouble(HelperFixture.Get(r,"y",0)),Width=Convert.ToDouble(HelperFixture.Get(r,"w",0)),Height=Convert.ToDouble(HelperFixture.Get(r,"h",0)) }; } }
        public bool IsModal { get { return Convert.ToBoolean(HelperFixture.Get(Data,"is_modal",false)); } }
    }
    public class WindowPattern
    {
        public static object Pattern = new object();
        public FixtureCurrent Current;
    }
    public class AutomationElement
    {
        public static object ControlTypeProperty = new object();
        private IDictionary<string, object> data;
        private bool root;
        public static AutomationElement RootElement { get { HelperFixture.Trace("uia.root"); HelperFixture.Fail(HelperFixture.Data, "uia_root"); return new AutomationElement { root = true }; } }
        public FixtureCurrent Current
        {
            get
            {
                HelperFixture.Fail(data, "current");
                return new FixtureCurrent { Data = data };
            }
        }
        public object GetCurrentPattern(object pattern) { HelperFixture.Trace("uia.isModal",Convert.ToString(HelperFixture.Get(data,"id"))); HelperFixture.Fail(data, "pattern"); return new WindowPattern { Current = Current }; }
        public AutomationElement[] FindAll(TreeScope scope, Condition condition)
        {
            string token = root ? "root" : Convert.ToString(HelperFixture.Get(data,"id"));
            if (scope == TreeScope.Children) HelperFixture.Trace("uia.children", token, condition is OrCondition ? "window-or-pane" : "all");
            else HelperFixture.Trace("uia.subtree", token);
            HelperFixture.Fail(root ? HelperFixture.Data : data, "find_all");
            var result = new List<AutomationElement>();
            object value = root ? HelperFixture.Get(HelperFixture.Data, scope == TreeScope.Children ? "uia_children" : "uia_subtree") : HelperFixture.Get(data, "subtree");
            foreach (object item in HelperFixture.Values(value)) result.Add(new AutomationElement { data = HelperFixture.Map(item) });
            return result.ToArray();
        }
    }
}

// Synthetic OCR flow: bitmap and screen facades only carry fixture numbers.
// They neither create an image nor open/capture any desktop resource.
namespace System.Drawing
{
    public class Size { public int Width, Height; public Size(int w,int h){Width=w;Height=h;} }
    public class Bitmap : IDisposable
    {
        internal int W,H,X,Y;
        public Bitmap(int w,int h){W=w;H=h;}
        public void Save(string path, object format)
        {
            HelperFixture.Effects.Add(new Dictionary<string,object>{{"op","ocr.tempPath"},{"args",new object[0]},{"value",path}});
            HelperFixture.Trace("ocr.capture",X,Y,W,H,path);
        }
        public void Dispose() { }
    }
    public class Graphics : IDisposable
    {
        private Bitmap image;
        public static Graphics FromImage(Bitmap bitmap){return new Graphics{image=bitmap};}
        public void CopyFromScreen(int x,int y,int destinationX,int destinationY,Size size){image.X=x;image.Y=y;}
        public void Dispose(){ }
    }
}
namespace System.Drawing.Imaging { public class ImageFormat {public static object Png=new object();} }
namespace System.Windows.Forms
{
    public class FixtureBounds
    {
        internal string Operation;
        public int Width { get { HelperFixture.Trace(Operation); return 1920; } }
    }
    public class Screen
    {
        public static Screen PrimaryScreen { get { return new Screen(); } }
        public FixtureBounds Bounds { get { return new FixtureBounds {Operation="ocr.primaryScreenWidth"}; } }
    }
    public class SystemInformation
    {
        public static FixtureBounds VirtualScreen {get {return new FixtureBounds {Operation="ocr.loadFormsAndVirtualWidth"};}}
    }
}
public class WindowsRuntimeSystemExtensions
{
    public static global::System.Threading.Tasks.Task<T> AsTask<T>(object operation)
    { return global::System.Threading.Tasks.Task.FromResult((T)operation); }
}
namespace Windows.Storage.Streams
{
    public class IRandomAccessStream { }
}
namespace Windows.Storage
{
    public enum FileAccessMode {Read}
    public class StorageFile
    {
        public static StorageFile GetFileFromPathAsync(string path)
        {HelperFixture.Trace("ocr.prepareAsync");HelperFixture.Trace("ocr.loadFile",path);return new StorageFile();}
        public Windows.Storage.Streams.IRandomAccessStream OpenAsync(FileAccessMode access)
        {HelperFixture.Trace("ocr.openRead","file");return new Windows.Storage.Streams.IRandomAccessStream();}
    }
}
namespace Windows.Graphics.Imaging
{
    public class SoftwareBitmap { }
    public class BitmapDecoder
    {
        public static BitmapDecoder CreateAsync(Windows.Storage.Streams.IRandomAccessStream stream)
        {HelperFixture.Trace("ocr.createDecoder","stream");return new BitmapDecoder();}
        public SoftwareBitmap GetSoftwareBitmapAsync(){HelperFixture.Trace("ocr.getBitmap","decoder");return new SoftwareBitmap();}
    }
}
namespace Windows.Media.Ocr
{
    public class OcrLine {public string Text; public object[] Words;}
    public class OcrResult {public string Text;public OcrLine[] Lines;}
    public class OcrEngine
    {
        public static int MaxImageDimension {get {HelperFixture.Trace("ocr.maxDimension");return Convert.ToInt32(HelperFixture.Get(HelperFixture.Data,"max_dimension",10000));}}
        public OcrResult RecognizeAsync(Windows.Graphics.Imaging.SoftwareBitmap bitmap)
        {
            HelperFixture.Trace("ocr.recognize","engine","bitmap");
            var value=HelperFixture.Map(HelperFixture.Get(HelperFixture.Data,"ocr_result"));
            var lines=new List<OcrLine>();
            foreach(object item in HelperFixture.Values(HelperFixture.Get(value,"lines")))
            {var line=HelperFixture.Map(item);lines.Add(new OcrLine{Text=(string)HelperFixture.Get(line,"text"),Words=new object[Convert.ToInt32(HelperFixture.Get(line,"word_count",0))]});}
            return new OcrResult{Text=(string)HelperFixture.Get(value,"text"),Lines=lines.ToArray()};
        }
    }
}

} // namespace CucpFixture
