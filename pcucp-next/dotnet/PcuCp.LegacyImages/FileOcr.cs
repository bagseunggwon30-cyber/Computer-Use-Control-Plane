using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;

namespace PcuCp.LegacyImages
{
    public sealed class FileOcrResult
    {
        public int ExitCode { get; internal set; }
        public OrderedDictionary Data { get; internal set; }
    }

    public sealed class OcrOperationResult
    {
        public object Value { get; internal set; }
        public string Error { get; internal set; }
    }

    // The seam permits captured language/error contracts without using an OS engine.
    public interface IFileOcrBackend
    {
        void Initialize();
        object CreateFromLanguage(string language);
        object CreateFromProfile();
        IList AvailableLanguages();
        object CreateFromAvailableLanguage(object language);
        object Load(string path);
        object Recognize(object engine, object bitmap);
        string LanguageTag(object engine);
    }

    // A session mirrors the script's once-only initialization, including failed attempts.
    public sealed class FileOcrSession
    {
        private readonly IFileOcrBackend backend;
        public bool Loaded { get; private set; }
        public object Engine { get; private set; }
        public string Error { get; private set; }
        public FileOcrSession() : this(new WinRtFileOcrBackend()) { }
        public FileOcrSession(IFileOcrBackend backend) { this.backend = backend ?? throw new ArgumentNullException(nameof(backend)); }

        public bool Ensure(string language)
        {
            if (Loaded) return Engine != null;
            Loaded = true;
            try
            {
                backend.Initialize();
                object engine = null;
                if (!string.IsNullOrEmpty(language))
                    try { engine = backend.CreateFromLanguage(language); } catch { engine = null; }
                if (engine == null) engine = backend.CreateFromProfile();
                if (engine == null)
                {
                    var available = backend.AvailableLanguages();
                    if (available != null && available.Count > 0) engine = backend.CreateFromAvailableLanguage(available[0]);
                }
                if (engine == null) { Error = "no_ocr_language_available"; return false; }
                Engine = engine;
                return true;
            }
            catch (Exception ex) { Error = ex.Message; return false; }
        }

        public FileOcrResult Observe(string path, string language)
        {
            var validation = FileOcr.ValidatePath(path);
            if (validation != null) return validation;
            if (!Ensure(language)) return FileOcr.Unavailable(Error);
            return FileOcr.RecognizeFile(path, Engine, backend);
        }
    }

    public static class FileOcr
    {
        internal static OrderedDictionary Map(params object[] pairs)
        {
            var data = new OrderedDictionary();
            for (int i = 0; i < pairs.Length; i += 2) data.Add(pairs[i], pairs[i + 1]);
            return data;
        }
        private static FileOcrResult Failure(string reason, params object[] pairs)
        {
            var data = Map("status", "error", "reason", reason);
            for (int i = 0; i < pairs.Length; i += 2) data.Add(pairs[i], pairs[i + 1]);
            return new FileOcrResult { ExitCode = 1, Data = data };
        }
        public static FileOcrResult ValidatePath(string path)
        {
            if (string.IsNullOrEmpty(path)) return Failure("missing_ocr_path", "recommended_action", "provide -OcrPath <png file>");
            // Test-Path accepts directories; preserve that distinction from File.Exists.
            if (!File.Exists(path) && !Directory.Exists(path)) return Failure("ocr_path_not_found", "ocr_path", path);
            return null;
        }
        public static FileOcrResult Unavailable(string error)
        { return Failure("ocr_unavailable", "ocr_error", error, "recommended_action", "install_windows_ocr_language_pack"); }
        public static FileOcrResult RecognizeFile(string path, object engine)
        { return RecognizeFile(path, engine, new WinRtFileOcrBackend()); }
        internal static FileOcrResult RecognizeFile(string path, object engine, IFileOcrBackend backend)
        {
            object bitmap = null;
            try
            {
                bitmap = backend.Load(path);
                var result = backend.Recognize(engine, bitmap);
                var data = ConvertResult(result, 0, 0);
                data.Add("status", "ok");
                data.Add("engine_language", backend.LanguageTag(engine));
                data.Add("source", "image");
                data.Add("ocr_path", path);
                return new FileOcrResult { ExitCode = 0, Data = data };
            }
            catch (Exception ex) { return Failure("ocr_failed", "detail", ex.Message, "ocr_path", path); }
            finally { (bitmap as IDisposable)?.Dispose(); }
        }

        internal static object Property(object target, string name)
        {
            if (target == null) return null;
            var dictionary = target as IDictionary;
            if (dictionary != null) return dictionary.Contains(name) ? dictionary[name] : null;
            return target.GetType().GetProperty(name)?.GetValue(target, null);
        }
        private static IEnumerable Items(object target)
        { return target as IEnumerable ?? new object[0]; }
        private static int Int(object value) { return System.Convert.ToInt32(value, CultureInfo.InvariantCulture); }
        private static double Number(object value) { return System.Convert.ToDouble(value, CultureInfo.InvariantCulture); }
        // PowerShell promotes overflowing Int32 arithmetic to Double.
        private static object Add(int left, int right)
        {
            long value = (long)left + right;
            if (value >= int.MinValue && value <= int.MaxValue) return (int)value;
            return (double)value;
        }
        private static object Arithmetic(double value, bool promote)
        { if (!promote && value >= int.MinValue && value <= int.MaxValue) return (int)value; return value; }

        public static OrderedDictionary ConvertResult(object result, int offsetX, int offsetY)
        {
            var lines = new List<OrderedDictionary>();
            int wordCount = 0;
            foreach (var line in Items(Property(result, "Lines")))
            {
                var words = new List<OrderedDictionary>();
                object minX = int.MaxValue, minY = int.MaxValue, maxR = 0, maxB = 0;
                foreach (var word in Items(Property(line, "Words")))
                {
                    var rect = Property(word, "BoundingRect");
                    object x = Add(Int(Property(rect, "X")), offsetX), y = Add(Int(Property(rect, "Y")), offsetY);
                    int width = Int(Property(rect, "Width")), height = Int(Property(rect, "Height"));
                    var item = Map("text", Property(word, "Text"), "x", x, "y", y, "w", width, "h", height,
                        "cx", Arithmetic(Number(x) + Int(width / 2.0), x is double),
                        "cy", Arithmetic(Number(y) + Int(height / 2.0), y is double));
                    words.Add(item); wordCount++;
                    if (Number(x) < Number(minX)) minX = x;
                    if (Number(y) < Number(minY)) minY = y;
                    double right = Number(x) + width, bottom = Number(y) + height;
                    if (right > Number(maxR)) maxR = Arithmetic(right, x is double);
                    if (bottom > Number(maxB)) maxB = Arithmetic(bottom, y is double);
                }
                if (words.Count == 0) continue;
                bool horizontalDouble = minX is double || maxR is double;
                bool verticalDouble = minY is double || maxB is double;
                double lineWidth = Number(maxR) - Number(minX), lineHeight = Number(maxB) - Number(minY);
                lines.Add(Map("text", Property(line, "Text"), "x", minX, "y", minY,
                    "w", Arithmetic(lineWidth, horizontalDouble), "h", Arithmetic(lineHeight, verticalDouble),
                    "cx", Arithmetic(Number(minX) + Int(lineWidth / 2), minX is double),
                    "cy", Arithmetic(Number(minY) + Int(lineHeight / 2), minY is double),
                    "word_count", words.Count, "words", words.ToArray()));
            }
            return Map("text", Property(result, "Text"), "line_count", lines.Count, "word_count", wordCount, "lines", lines.ToArray());
        }

        public static OcrOperationResult TryLoadSoftwareBitmapFromFile(string path)
        { return Operation(() => new WinRtFileOcrBackend().Load(path)); }
        public static OcrOperationResult TryWaitAsyncOperation(object operation, Type resultType)
        { return Operation(() => WinRtFileOcrBackend.Wait(operation, resultType)); }
        private static OcrOperationResult Operation(Func<object> callback)
        {
            try { return new OcrOperationResult { Value = callback() }; }
            catch (Exception ex) { return new OcrOperationResult { Error = ex.Message }; }
        }
    }

    // Uses the same .NET Framework WinRT projection as the retained helper. No
    // PowerShell assembly, code evaluation, process, capture, input or network APIs.
    public sealed class WinRtFileOcrBackend : IFileOcrBackend
    {
        private static readonly object Gate = new object();
        private static Type engineType, fileType, decoderType, bitmapType, streamType, resultType, languageType, accessType;
        private static Type RuntimeType(string name, string assembly)
        { return Type.GetType(name + ", " + assembly + ", ContentType=WindowsRuntime", true); }
        public void Initialize()
        {
            lock (Gate)
            {
                if (engineType != null) return;
                // Load all types before committing initialization, just as _Ensure-OCR.
                Assembly.Load("System.Runtime.WindowsRuntime, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089");
                var e = RuntimeType("Windows.Media.Ocr.OcrEngine", "Windows.Media.Ocr");
                fileType = RuntimeType("Windows.Storage.StorageFile", "Windows.Storage");
                bitmapType = RuntimeType("Windows.Graphics.Imaging.SoftwareBitmap", "Windows.Graphics.Imaging");
                decoderType = RuntimeType("Windows.Graphics.Imaging.BitmapDecoder", "Windows.Graphics.Imaging");
                RuntimeType("Windows.Storage.Streams.RandomAccessStream", "Windows.Storage.Streams");
                streamType = RuntimeType("Windows.Storage.Streams.IRandomAccessStream", "Windows.Storage.Streams");
                languageType = RuntimeType("Windows.Globalization.Language", "Windows.Globalization");
                resultType = RuntimeType("Windows.Media.Ocr.OcrResult", "Windows.Media.Ocr");
                accessType = RuntimeType("Windows.Storage.FileAccessMode", "Windows.Storage");
                engineType = e;
            }
        }
        private static object Call(Type type, object target, string method, params object[] args)
        {
            try
            {
                var candidate = type.GetMethods().Single(m => m.Name == method && m.GetParameters().Length == args.Length);
                return candidate.Invoke(target, args);
            }
            catch (Exception ex)
            {
                var detail = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException.Message : ex.Message;
                throw new InvalidOperationException("Exception calling \"" + method + "\" with \"" + args.Length + "\" argument(s): \"" + detail + "\"", ex);
            }
        }
        public object CreateFromLanguage(string language)
        {
            Initialize();
            var requested = Activator.CreateInstance(languageType, new object[] { language });
            return Call(engineType, null, "TryCreateFromLanguage", requested);
        }
        public object CreateFromProfile() { Initialize(); return Call(engineType, null, "TryCreateFromUserProfileLanguages"); }
        public IList AvailableLanguages()
        {
            Initialize();
            var source = (IEnumerable)engineType.GetProperty("AvailableRecognizerLanguages").GetValue(null, null);
            var list = new ArrayList(); foreach (var language in source) list.Add(language); return list;
        }
        public object CreateFromAvailableLanguage(object language) { return Call(engineType, null, "TryCreateFromLanguage", language); }
        public string LanguageTag(object engine) { return (string)FileOcr.Property(FileOcr.Property(engine, "RecognizerLanguage"), "LanguageTag"); }
        public static object Wait(object operation, Type resultType)
        {
            var assembly = Assembly.Load("System.Runtime.WindowsRuntime, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089");
            var extensions = assembly.GetType("System.WindowsRuntimeSystemExtensions", true);
            var asTask = extensions.GetMethods().First(m => m.Name == "AsTask" && m.GetParameters().Length == 1 && m.IsGenericMethod);
            var generic = (MethodInfo)Call(asTask.GetType(), asTask, "MakeGenericMethod", new object[] { new Type[] { resultType } });
            // Invoke is an actual legacy boundary; retain its own wrapper.
            var task = (Task)Call(typeof(MethodBase), generic, "Invoke", null, new object[] { operation });
            Call(typeof(Task), task, "Wait");
            return task.GetType().GetProperty("Result").GetValue(task, null);
        }
        public object Load(string path)
        {
            Initialize();
            var file = Wait(Call(fileType, null, "GetFileFromPathAsync", path), fileType);
            var stream = Wait(Call(fileType, file, "OpenAsync", Enum.ToObject(accessType, 0)), streamType);
            try
            {
                var decoder = Wait(Call(decoderType, null, "CreateAsync", stream), decoderType);
                return Wait(Call(decoderType, decoder, "GetSoftwareBitmapAsync"), bitmapType);
            }
            finally { (stream as IDisposable)?.Dispose(); }
        }
        public object Recognize(object engine, object bitmap)
        { Initialize(); return Wait(Call(engineType, engine, "RecognizeAsync", bitmap), resultType); }
    }
}
