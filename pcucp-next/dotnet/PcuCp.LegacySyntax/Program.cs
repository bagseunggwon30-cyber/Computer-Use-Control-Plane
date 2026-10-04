using System;
using System.Collections.Generic;
using System.IO;
using System.Globalization;
using System.Linq;
using System.Management.Automation;
using System.Management.Automation.Language;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class Program
{
    [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    private static int Main(string[] args)
    {
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
        Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
        try
        {
            if (args.Length != 0)
            {
                if (args.Length != 2 || args[0] != "--parent-handle" || !long.TryParse(args[1], out long value) || value <= 0)
                    throw new ArgumentException("Unknown syntax startup options.");
                var parent = new IntPtr(value);
                if (WaitForSingleObject(parent, 0) != 258) throw new InvalidOperationException("Syntax parent guard failed before tokenization.");
                new Thread(() => { WaitForSingleObject(parent, uint.MaxValue); CloseHandle(parent); Environment.Exit(125); })
                { IsBackground = true, Name = "syntax-parent" }.Start();
            }
            using (var input = Console.OpenStandardInput())
            using (var buffer = new MemoryStream())
            {
                var block = new byte[4096]; int read;
                while ((read = input.Read(block, 0, block.Length)) != 0)
                {
                    if (buffer.Length + read > 32 * 1024 * 1024) throw new ArgumentException("Syntax input exceeds 32 MiB.");
                    buffer.Write(block, 0, read);
                }
                var json = new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024, RecursionLimit = 100 };
                var request = ParseRequest(json, new UTF8Encoding(false, true).GetString(buffer.ToArray()));
                if (request != null && request.TryGetValue("schema", out object schema) && Equals(schema, "cucp.source-map-input/v1"))
                {
                    string mapped = json.Serialize(SourceMap(request));
                    if (new UTF8Encoding(false, true).GetByteCount(mapped) > 4 * 1024 * 1024)
                        throw new ArgumentException("Source-map reply exceeds 4 MiB.");
                    Console.WriteLine(mapped);
                    return 0;
                }
                if (request == null || request.Count != 3 || !request.ContainsKey("schema") || !Equals(request["schema"], "cucp.legacy-syntax/v1") ||
                    !request.TryGetValue("culture", out object locale) || !(locale is string cultureName) || cultureName.Length > 128 ||
                    !request.TryGetValue("steps", out object source) || !(source is object[] steps) || steps.Any(step => !(step is string)))
                    throw new ArgumentException("Expected a typed workflow step array.");
                Thread.CurrentThread.CurrentCulture = CultureInfo.GetCultureInfo(cultureName);
                Thread.CurrentThread.CurrentUICulture = CultureInfo.GetCultureInfo(cultureName);
                Console.WriteLine(json.Serialize(new { schema = "cucp.legacy-syntax/v1", parsed_steps = steps.Cast<string>().Select(Parse).ToArray() }));
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.GetType().Name + ": " + error.Message); return 1; }
    }
    private static IDictionary<string, object> ParseRequest(JavaScriptSerializer json, string source)
    {
        // Validate names before Framework JSON materialization can overwrite
        // an earlier (including escaped) property. Token text remains data.
        var objects = new Stack<HashSet<string>>();
        for (int i = 0; i < source.Length; i++)
        {
            char value = source[i];
            if (value == '{' || value == '[')
            {
                if (objects.Count >= 100) throw new ArgumentException("Syntax JSON nesting exceeds 100.");
                objects.Push(value == '{' ? new HashSet<string>(StringComparer.Ordinal) : null);
            }
            else if (value == '}' || value == ']')
            {
                if (objects.Count == 0) throw new ArgumentException("Invalid syntax JSON nesting.");
                objects.Pop();
            }
            else if (value == '"')
            {
                int first = i++; bool ended = false;
                for (; i < source.Length; i++) { if (source[i] == '\\') i++; else if (source[i] == '"') { ended = true; break; } }
                if (!ended) throw new ArgumentException("Unterminated syntax JSON string.");
                int next = i + 1; while (next < source.Length && char.IsWhiteSpace(source[next])) next++;
                if (next < source.Length && source[next] == ':' && objects.Count != 0 && objects.Peek() != null &&
                    !objects.Peek().Add(json.Deserialize<string>(source.Substring(first, i - first + 1))))
                    throw new ArgumentException("Duplicate syntax JSON property.");
            }
        }
        return json.DeserializeObject(source) as IDictionary<string, object>;
    }
    private static object Parse(string step)
    {
        var tokens = PSParser.Tokenize(step, out var errors);
        if (errors.Count != 0) return new { ok = false, error = "parse_error", detail = string.Join("; ", errors.Select(error => error.Message)), tokens = new string[0] };
        var items = new List<string>();
        foreach (var token in tokens)
        {
            if (token.Type == PSTokenType.NewLine || token.Type == PSTokenType.LineContinuation) continue;
            if (token.Type != PSTokenType.Command && token.Type != PSTokenType.CommandArgument && token.Type != PSTokenType.String && token.Type != PSTokenType.Number)
                return new { ok = false, error = "unsupported_token", detail = "unsupported token type '" + token.Type + "'", tokens = new string[0] };
            // PowerShell's invariant comparison treats NUL-only token content
            // as equal to empty. String.IsNullOrEmpty does not preserve this.
            if (token.Content != null && !StringComparer.InvariantCultureIgnoreCase.Equals(token.Content, "")) items.Add(token.Content);
        }
        return new { ok = items.Count != 0, error = items.Count == 0 ? "empty_step" : "", detail = "", tokens = items.ToArray() };
    }

    private static string Hash(string text)
    {
        using (var hash = SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(new UTF8Encoding(false, true).GetBytes(text))).Replace("-", "").ToLowerInvariant();
    }

    private static object SourceMap(IDictionary<string, object> request)
    {
        if (request.Count != 2 || !request.TryGetValue("files", out object value) || !(value is object[] files) || files.Length == 0 || files.Length > 1024)
            throw new ArgumentException("Expected bounded source-map files.");
        var paths = new HashSet<string>(StringComparer.Ordinal);
        var result = new List<KeyValuePair<string, object>>();
        foreach (object item in files)
        {
            if (!(item is IDictionary<string, object> file) || file.Count != 2 ||
                !file.TryGetValue("path", out object pathValue) || !(pathValue is string path) || path.Length > 4096 ||
                !Regex.IsMatch(path, @"\A(?:scripts/[a-zA-Z0-9_.-]+\.ps1|tests/fixtures/legacy-[a-zA-Z0-9_.-]+-adapter\.ps1)\z") ||
                !paths.Add(path) || !file.TryGetValue("text", out object textValue) || !(textValue is string text) || text.Contains("\r\n") || text.StartsWith("\uFEFF", StringComparison.Ordinal))
                throw new ArgumentException("Invalid or duplicate source-map file.");
            Token[] tokens;
            ParseError[] errors;
            // Parse source as inert data. No Runspace, pipeline or script block
            // is created or invoked, including function bodies with side effects.
            var ast = Parser.ParseInput(text, out tokens, out errors);
            if (errors.Length != 0) throw new ArgumentException("Source-map parse failed for " + path + ": " + errors[0].Message);
            var functions = ast.FindAll(node => node is FunctionDefinitionAst, true).Cast<FunctionDefinitionAst>().Select(function =>
            {
                string parentName = null;
                for (Ast parent = function.Parent; parent != null; parent = parent.Parent)
                    if (parent is FunctionDefinitionAst owner) { parentName = owner.Name; break; }
                return new { name = function.Name, parent_function = parentName, start_utf16 = function.Extent.StartOffset,
                    end_utf16 = function.Extent.EndOffset, sha256 = Hash(function.Extent.Text) };
            }).ToArray();
            result.Add(new KeyValuePair<string, object>(path,new { path, sha256 = Hash(text), utf16_length = (long)text.Length, functions }));
        }
        return new { schema = "cucp.migration-source-map/v1", encoding = "utf-8-no-bom-lf",
            files = result.OrderBy(pair => pair.Key,StringComparer.CurrentCultureIgnoreCase).Select(pair => pair.Value).ToArray() };
    }
}
