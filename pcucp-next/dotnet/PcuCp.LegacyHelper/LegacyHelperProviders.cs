using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Automation;

namespace PcuCp.LegacyHelper
{
    // This provider is opt-in at the host boundary. The action reducer and its
    // synthetic fixtures never instantiate this class or touch a real desktop.
    public sealed class WindowsLegacyHelperProvider : ILegacyHelperProvider
    {
        private Type engineType, fileType, decoderType, bitmapType, streamType, resultType, accessType;
        private MethodInfo asTask;
        private object activeStream, activeBitmap;

        public object Invoke(string operation, params object[] args)
        {
            switch (operation)
            {
                case "win32.ensure":
                    if (Environment.OSVersion.Platform != PlatformID.Win32NT) throw new PlatformNotSupportedException("Win32 desktop observations require Windows.");
                    if (typeof(HelperWin32).Assembly.GetName().Name != "PcuCp.LegacyInterop") throw new InvalidOperationException("Mismatched legacy interop assembly.");
                    return null;
                case "win32.visible": return HelperWin32.IsWindowVisible(Handle(args[0]));
                case "win32.titleLength": return HelperWin32.GetWindowTextLength(Handle(args[0]));
                case "win32.title":
                    var title = new StringBuilder((int)args[1]);
                    HelperWin32.GetWindowText(Handle(args[0]), title, (int)args[1]);
                    return title.ToString();
                case "win32.class":
                    var clazz = new StringBuilder((int)args[1]);
                    HelperWin32.GetClassName(Handle(args[0]), clazz, (int)args[1]);
                    return clazz.ToString();
                case "win32.pid":
                    uint process; HelperWin32.GetWindowThreadProcessId(Handle(args[0]), out process);
                    return checked((int)process);
                case "win32.rect":
                    HelperWin32.RECT rect; HelperWin32.GetWindowRect(Handle(args[0]), out rect);
                    return LegacyHelperActions.Map("left", rect.Left, "top", rect.Top, "right", rect.Right, "bottom", rect.Bottom);
                case "win32.foreground": return HelperWin32.GetForegroundWindow().ToInt64();
                case "uia.load": LoadUia(); return null;
                case "uia.loadModal":
                    try { Assembly.Load("UIAutomationClient, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"); } catch (Exception) { }
                    try { Assembly.Load("UIAutomationTypes, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"); } catch (Exception) { }
                    return null;
                case "uia.root": case "uia.children": case "uia.subtree": case "uia.name": case "uia.class":
                case "uia.rect": case "uia.isModal": case "uia.handle": case "uia.controlType":
                    return Uia(operation, args);
                case "ocr.initialize": InitializeOcr(); return null;
                case "ocr.createProfile": return ReflectCall(engineType, null, "TryCreateFromUserProfileLanguages");
                case "ocr.languages": return Values(ReadProperty(engineType, null, "AvailableRecognizerLanguages"));
                case "ocr.createLanguage": return ReflectCall(engineType, null, "TryCreateFromLanguage", args[0]);
                case "ocr.loadDrawing": Assembly.Load("System.Drawing, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a"); return null;
                case "ocr.primaryScreenWidth": return System.Windows.Forms.Screen.PrimaryScreen.Bounds.Width;
                case "ocr.loadFormsAndVirtualWidth":
                    Assembly.Load("System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089");
                    return System.Windows.Forms.SystemInformation.VirtualScreen.Width;
                case "ocr.maxDimension": return ReadProperty(engineType, null, "MaxImageDimension");
                case "ocr.tempPath": return Path.Combine(Path.GetTempPath(), "cucp-srv-ocr-" + Guid.NewGuid().ToString("N") + ".png");
                case "ocr.capture": Capture((int)args[0], (int)args[1], (int)args[2], (int)args[3], (string)args[4]); return null;
                case "ocr.prepareAsync": PrepareAsync(); return null;
                case "ocr.loadFile": return Wait(ReflectCall(fileType, null, "GetFileFromPathAsync", args[0]), fileType);
                case "ocr.openRead": activeStream = Wait(ReflectCall(fileType, args[0], "OpenAsync", Enum.ToObject(accessType, 0)), streamType); return activeStream;
                case "ocr.createDecoder": return Wait(ReflectCall(decoderType, null, "CreateAsync", args[0]), decoderType);
                case "ocr.getBitmap": activeBitmap = Wait(ReflectCall(decoderType, args[0], "GetSoftwareBitmapAsync"), bitmapType); return activeBitmap;
                case "ocr.recognize": return OcrResult(Wait(ReflectCall(engineType, args[0], "RecognizeAsync", args[1]), resultType));
                case "ocr.removeTemp":
                    // Deliberate resource-lifetime improvement: release WinRT file
                    // readers before deletion. No new screen or input acquisition.
                    try { (activeBitmap as IDisposable)?.Dispose(); } catch (Exception) { }
                    try { (activeStream as IDisposable)?.Dispose(); } catch (Exception) { }
                    activeBitmap = null; activeStream = null;
                    try { File.Delete((string)args[0]); } catch (Exception) { }
                    return null;
                default: throw new InvalidOperationException("Unsupported helper provider operation: " + operation);
            }
        }

        private static IntPtr Handle(object value) { return new IntPtr(Convert.ToInt64(value)); }
        public void EnumerateWindows(Action<long> visit)
        {
            Exception failure = null;
            HelperWin32.EnumWindows((hwnd, unused) =>
            {
                try { visit(hwnd.ToInt64()); return true; }
                catch (Exception error) { failure = error; return false; }
            }, IntPtr.Zero);
            // Do not unwind an exception through a native callback frame.
            if (failure != null) throw failure;
        }
        private static void LoadUia()
        {
            Assembly.Load("UIAutomationClient, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35");
            Assembly.Load("UIAutomationTypes, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35");
            Assembly.Load("WindowsBase, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35");
        }
        private static object Uia(string operation, object[] args)
        {
            if (operation == "uia.root") return AutomationElement.RootElement;
            var element = (AutomationElement)args[0];
            switch (operation)
            {
                case "uia.children":
                    Condition condition = (string)args[1] == "window-or-pane"
                        ? (Condition)new OrCondition(new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Window), new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Pane))
                        : Condition.TrueCondition;
                    return element.FindAll(TreeScope.Children, condition).Cast<AutomationElement>().Cast<object>().ToArray();
                case "uia.subtree": return element.FindAll(TreeScope.Subtree, Condition.TrueCondition).Cast<AutomationElement>().Cast<object>().ToArray();
                case "uia.name": return element.Current.Name;
                case "uia.class": return element.Current.ClassName;
                case "uia.rect":
                    var rect = element.Current.BoundingRectangle;
                    return LegacyHelperActions.Map("x", rect.X, "y", rect.Y, "width", rect.Width, "height", rect.Height);
                case "uia.isModal": return ((WindowPattern)element.GetCurrentPattern(WindowPattern.Pattern)).Current.IsModal;
                case "uia.handle": return element.Current.NativeWindowHandle;
                case "uia.controlType": return element.Current.LocalizedControlType;
                default: throw new InvalidOperationException("Unsupported UIA observation.");
            }
        }
        private static void Capture(int x, int y, int width, int height, string path)
        {
            using (var bitmap = new Bitmap(width, height))
            using (var graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(x, y, 0, 0, new Size(width, height));
                bitmap.Save(path, ImageFormat.Png);
            }
        }
        private static Type RuntimeType(string name, string assembly)
        { return Type.GetType(name + ", " + assembly + ", ContentType=WindowsRuntime", true); }
        private void InitializeOcr()
        {
            Assembly.Load("System.Runtime.WindowsRuntime, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089");
            var engine = RuntimeType("Windows.Media.Ocr.OcrEngine", "Windows.Media.Ocr");
            fileType = RuntimeType("Windows.Storage.StorageFile", "Windows.Storage");
            bitmapType = RuntimeType("Windows.Graphics.Imaging.SoftwareBitmap", "Windows.Graphics.Imaging");
            decoderType = RuntimeType("Windows.Graphics.Imaging.BitmapDecoder", "Windows.Graphics.Imaging");
            RuntimeType("Windows.Storage.Streams.RandomAccessStream", "Windows.Storage.Streams");
            RuntimeType("Windows.Globalization.Language", "Windows.Globalization");
            streamType = RuntimeType("Windows.Storage.Streams.IRandomAccessStream", "Windows.Storage.Streams");
            resultType = RuntimeType("Windows.Media.Ocr.OcrResult", "Windows.Media.Ocr");
            accessType = RuntimeType("Windows.Storage.FileAccessMode", "Windows.Storage");
            engineType = engine;
        }
        private void PrepareAsync()
        {
            var assembly = Assembly.Load("System.Runtime.WindowsRuntime, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089");
            asTask = assembly.GetType("System.WindowsRuntimeSystemExtensions", true).GetMethods()
                .First(method => method.Name == "AsTask" && method.GetParameters().Length == 1 && method.IsGenericMethod);
        }
        private object Wait(object operation, Type result)
        {
            var task = (Task)asTask.MakeGenericMethod(result).Invoke(null, new[] { operation });
            task.Wait();
            return task.GetType().GetProperty("Result").GetValue(task, null);
        }
        private static object ReflectCall(Type type, object target, string method, params object[] args)
        { return type.GetMethods().Single(candidate => candidate.Name == method && candidate.GetParameters().Length == args.Length).Invoke(target, args); }
        private static object ReadProperty(Type type, object target, string name)
        { return type.GetProperty(name).GetValue(target, null); }
        private static object ReadProperty(object value, string name) { return ReadProperty(value.GetType(), value, name); }
        private static object[] Values(object value) { return ((IEnumerable)value).Cast<object>().ToArray(); }
        private static object OcrResult(object result)
        {
            var lines = new List<object>();
            foreach (var line in (IEnumerable)ReadProperty(result, "Lines"))
                lines.Add(LegacyHelperActions.Map("text", ReadProperty(line, "Text"), "word_count", ((IEnumerable)ReadProperty(line, "Words")).Cast<object>().Count()));
            return LegacyHelperActions.Map("text", ReadProperty(result, "Text"), "lines", lines.ToArray());
        }
    }
}
