using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace PcuCp.LegacyHelper
{
    // Explicit direct invocation only. Automatic discovery never calls this.
    public static class LegacyHelperDirect
    {
        public static string PipeName(string name)
        {
            if (String.IsNullOrEmpty(name) || name.Length > 247 ||
                String.Equals(name, "anonymous", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".", StringComparison.Ordinal) || name.EndsWith(" ", StringComparison.Ordinal))
                throw new ArgumentException("direct pipe requires a bounded literal local name");
            foreach (char value in name)
                if (Char.IsControl(value) || value == '\\' || value == '/' || value == ':' ||
                    value == '"' || value == '<' || value == '>' || value == '|')
                    throw new ArgumentException("direct pipe requires a bounded literal local name");
            try { new UTF8Encoding(false, true).GetByteCount(name); }
            catch (EncoderFallbackException) { throw new ArgumentException("direct pipe name must be valid Unicode"); }
            return name; // Preserve accepted spelling. Never trim, normalize, or remap.
        }

        // Split before any Framework Path/DirectoryInfo call can expand 8.3 aliases.
        // Only directory aliases may differ later; lexical normalization is refused.
        public static string[] LockPathParts(string path)
        {
            if (String.IsNullOrEmpty(path) || path.Length < 4 ||
                !((path[0] >= 'A' && path[0] <= 'Z') || (path[0] >= 'a' && path[0] <= 'z')) ||
                path[1] != ':' || path[2] != '\\')
                throw new ArgumentException("direct lock requires an explicit absolute local path");
            string[] parts = path.Substring(3).Split('\\');
            foreach (string part in parts) FileComponent(part);
            LockLeaf(parts[parts.Length - 1]);
            return parts;
        }

        private static void FileComponent(string leaf)
        {
            if (String.IsNullOrEmpty(leaf) || leaf.EndsWith(".", StringComparison.Ordinal) || leaf.EndsWith(" ", StringComparison.Ordinal))
                throw new ArgumentException("direct lock requires an ordinary file leaf");
            foreach (char value in leaf)
                if (Char.IsControl(value) || "\\/:\"<>|?*".IndexOf(value) >= 0)
                    throw new ArgumentException("direct lock requires an ordinary file leaf");
            string stem = leaf.Split('.')[0].TrimEnd(' ', '.').ToUpperInvariant();
            if (stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" || stem == "CONIN$" || stem == "CONOUT$" || stem == "CLOCK$" ||
                System.Text.RegularExpressions.Regex.IsMatch(stem, @"\A(?:COM|LPT)[0-9¹²³]+\z"))
                throw new ArgumentException("direct lock must use non-device path components");
            try { new UTF8Encoding(false, true).GetByteCount(leaf); }
            catch (EncoderFallbackException) { throw new ArgumentException("direct lock path must be valid Unicode"); }
        }

        public static string LockLeaf(string leaf)
        {
            FileComponent(leaf);
            if (String.Equals(leaf, "helper.pid", StringComparison.OrdinalIgnoreCase) || String.Equals(leaf, "helper-staged.pid", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("direct lock must use an isolated non-device filename");
            return leaf;
        }

        public static string WindowsPipeName(string name)
        {
            name = PipeName(name);
            string expected = @"\\.\pipe\" + name;
            if (!String.Equals(Path.GetFullPath(expected), expected, StringComparison.Ordinal))
                throw new ArgumentException("direct pipe name would be normalized by Framework");
            return name;
        }
    }

    public sealed class LegacyHelperDebugLog
    {
        public const int MaxEvents = 128;
        public const int MaxLineCharacters = 192;
        private readonly Action<string> write;
        private int count, requests;
        private static readonly HashSet<string> Events = new HashSet<string>(StringComparer.Ordinal) {
            "server.start", "lock.written", "client.connected", "request.invalid", "idle.exit",
            "shutdown.requested", "pipe.error", "lock.cleanup", "server.exit"
        };
        public LegacyHelperDebugLog(Action<string> write) { this.write = write ?? throw new ArgumentNullException("write"); }
        private void Emit(string fields)
        {
            if (count > MaxEvents) return;
            if (++count > MaxEvents) { write("helper_debug event=limit"); return; }
            string line = "helper_debug " + fields;
            if (line.Length > MaxLineCharacters) throw new InvalidOperationException("debug metadata exceeded fixed bound");
            write(line);
        }
        public void Event(string name)
        {
            if (!Events.Contains(name)) throw new ArgumentException("unknown debug event");
            Emit("event=" + name);
        }
        public void Request(object id, string action)
        {
            if (count > MaxEvents) return;
            string known = "other";
            foreach (string value in new[] { "health", "windows", "focused", "modal-detect", "ocr-screen-fast", "uia-find-fast", "shutdown" })
                if (String.Equals(action, value, StringComparison.OrdinalIgnoreCase)) { known = value; break; }
            string kind = id == null ? "null" : id is string ? "string" : id is bool ? "boolean" :
                id is int || id is long || id is double || id is decimal ? "number" : "other";
            Emit("event=request sequence=" + (++requests).ToString(CultureInfo.InvariantCulture) + " action=" + known + " id_kind=" + kind);
        }
        public void Response(int exitCode)
        {
            if (exitCode != 0 && exitCode != 1 && exitCode != 2 && exitCode != 99)
                throw new ArgumentException("unknown debug response code");
            Emit("event=response exit_code=" + exitCode.ToString(CultureInfo.InvariantCulture));
        }
    }
}
