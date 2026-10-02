using System.Collections;
using System.Collections.Specialized;
using PcuCp.LegacyImages;

var count = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); count++; }
string Keys(IDictionary value) => string.Join(",", value.Keys.Cast<object>());
Hashtable Word(string text, double x, double y, double w, double h) => new() { ["Text"] = text,
    ["BoundingRect"] = new Hashtable { ["X"] = x, ["Y"] = y, ["Width"] = w, ["Height"] = h } };
Hashtable Line(string text, params object[] words) => new() { ["Text"] = text, ["Words"] = words };
Hashtable Result(string text, params object[] lines) => new() { ["Text"] = text, ["Lines"] = lines };
OrderedDictionary[] Rows(IDictionary data, string name) => (OrderedDictionary[])data[name];

var empty = FileOcr.ConvertResult(null, 0, 0);
Check(Keys(empty) == "text,line_count,word_count,lines", "Result property order changed");
Check(empty["text"] == null && (int)empty["line_count"] == 0 && Rows(empty, "lines").Length == 0, "Null result changed");
var body = FileOcr.ConvertResult(Result("source\r\ntext\n", Line("omit"), Line("한글 😀", Word("Ａ", 1.5, 2.5, 3, 5), Word("B", 9.5, 8.5, 2.5, 1.5))), 10, -20);
Check((string)body["text"] == "source\r\ntext\n", "Original result Text must be kept verbatim");
Check((int)body["line_count"] == 1 && (int)body["word_count"] == 2, "Empty lines or counts changed");
var line = Rows(body, "lines")[0];
var words = Rows(line, "words");
Check(Keys(line) == "text,x,y,w,h,cx,cy,word_count,words", "Line property order changed");
Check(Keys(words[0]) == "text,x,y,w,h,cx,cy", "Word property order changed");
Check((int)words[0]["x"] == 12 && (int)words[0]["y"] == -18, "ToEven/offset order changed");
Check((int)words[0]["cx"] == 14 && (int)words[0]["cy"] == -16, "Odd-word center rounds before adding offset");
Check((int)words[1]["x"] == 20 && (int)words[1]["w"] == 2 && (int)words[1]["h"] == 2, "Rectangle ToEven changed");
Check((int)line["y"] == -18 && (int)line["h"] == 18 && (int)line["cy"] == -9, "Legacy zero-initialized max bound changed");
Check((int)line["x"] == 12 && (int)line["w"] == 10 && (int)line["cx"] == 17, "Line union changed");
var promoted = Rows(FileOcr.ConvertResult(Result("edge", Line("edge", Word("edge", int.MaxValue, 0, 2, 2))), 2, 0), "lines")[0];
Check(Rows(promoted, "words")[0]["x"] is double && (double)Rows(promoted, "words")[0]["x"] == 2147483649d, "PS overflow promotion changed");
Check((int)promoted["x"] == int.MaxValue, "Legacy initial minimum sentinel changed");

foreach (var scenario in new[] { "explicit", "profile", "first", "none", "explicit-throw", "profile-throw", "initialize-throw", "blank" })
{
    var backend = new FakeBackend(scenario);
    var session = new FileOcrSession(backend);
    bool available = session.Ensure(scenario == "blank" ? "" : "requested");
    var before = string.Join(",", backend.Calls);
    Check(session.Ensure("different") == available && string.Join(",", backend.Calls) == before, "Initialization must cache success and failure");
    Check(session.Loaded, "Loaded flag missing");
    if (scenario == "explicit") Check(before == "initialize,explicit:requested", "Explicit language priority changed");
    if (scenario == "profile") Check(before == "initialize,explicit:requested,profile", "Profile fallback changed");
    if (scenario == "first") Check(before == "initialize,explicit:requested,profile,available,first:available-one", "First available fallback changed");
    if (scenario == "none") Check(!available && session.Error == "no_ocr_language_available", "Unavailable language must stay explicit");
    if (scenario == "explicit-throw") Check(available && before.EndsWith(",profile"), "Invalid requested language must fall back");
    if (scenario == "profile-throw") Check(!available && session.Error == "profile failed" && !before.Contains("available"), "Profile exceptions must not fall back");
    if (scenario == "initialize-throw") Check(!available && session.Error == "initialize failed" && before == "initialize", "Initialization exception changed");
    if (scenario == "blank") Check(available && before == "initialize,profile", "Blank language must bypass explicit selection");
}

var root = Path.Combine(Path.GetTempPath(), "CUCP file OCR contracts " + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    var backend = new FakeBackend("profile");
    var session = new FileOcrSession(backend);
    Check((string)session.Observe("", "").Data["reason"] == "missing_ocr_path", "Missing path changed");
    Check((string)session.Observe(Path.Combine(root, "absent"), "").Data["reason"] == "ocr_path_not_found", "Absent path changed");
    Check(!session.Loaded && backend.Calls.Count == 0, "Path checks must precede OCR loading");
    Check(FileOcr.ValidatePath(root) == null, "Directories must reach decoder instead of path-not-found");
    var path = Path.Combine(root, "owned.txt"); File.WriteAllText(path, "owned fixture");
    backend.Captured = Result("verbatim\n", Line("word", Word("word", 1, 2, 3, 4)));
    var observed = session.Observe(path, "");
    Check(observed.ExitCode == 0 && (string)observed.Data["source"] == "image", "File success envelope changed");
    Check(Keys(observed.Data) == "text,line_count,word_count,lines,status,engine_language,source,ocr_path", "Success output order changed");
    Check((string)observed.Data["engine_language"] == "profile-tag" && (string)observed.Data["ocr_path"] == path, "Engine/path provenance changed");
    Check(backend.Disposed, "Owned software bitmap was not disposed");
    backend.ThrowLoad = true;
    var failed = session.Observe(path, "");
    Check(failed.ExitCode == 1 && (string)failed.Data["reason"] == "ocr_failed" && (string)failed.Data["detail"] == "full load detail", "Full OCR error detail changed");
    var unavailable = new FileOcrSession(new FakeBackend("none")).Observe(path, "");
    Check((string)unavailable.Data["reason"] == "ocr_unavailable" && (string)unavailable.Data["ocr_error"] == "no_ocr_language_available", "Unavailable error changed");
}
finally { Directory.Delete(root, true); }
Console.WriteLine($"PASS: {count} file-only OCR conversion/session contracts; no OS OCR, screenshots, input, or PowerShell executed.");

sealed class FakeBackend : IFileOcrBackend
{
    private readonly string scenario;
    public List<string> Calls = new();
    public object Captured;
    public bool ThrowLoad, Disposed;
    public FakeBackend(string scenario) { this.scenario = scenario; }
    public void Initialize() { Calls.Add("initialize"); if (scenario == "initialize-throw") throw new InvalidOperationException("initialize failed"); }
    public object CreateFromLanguage(string language)
    {
        Calls.Add("explicit:" + language);
        if (scenario == "explicit-throw") throw new ArgumentException("invalid language");
        return scenario == "explicit" ? "explicit-engine" : null;
    }
    public object CreateFromProfile()
    {
        Calls.Add("profile");
        if (scenario == "profile-throw") throw new InvalidOperationException("profile failed");
        return scenario is "profile" or "explicit-throw" or "blank" ? "profile-engine" : null;
    }
    public IList AvailableLanguages() { Calls.Add("available"); return scenario == "first" ? new[] { "available-one", "available-two" } : Array.Empty<string>(); }
    public object CreateFromAvailableLanguage(object language) { Calls.Add("first:" + language); return "available-engine"; }
    public object Load(string path) { Calls.Add("load:" + path); if (ThrowLoad) throw new InvalidOperationException("full load detail"); return new Bitmap(() => Disposed = true); }
    public object Recognize(object engine, object bitmap) { Calls.Add("recognize"); return Captured; }
    public string LanguageTag(object engine) => "profile-tag";
    sealed class Bitmap : IDisposable { readonly Action dispose; public Bitmap(Action dispose) { this.dispose = dispose; } public void Dispose() => dispose(); }
}
