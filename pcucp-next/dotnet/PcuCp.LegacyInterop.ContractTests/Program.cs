using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;

// No interop method is invoked. All checks concern managed reflection or ABI layout.
internal static class Program
{
    private static int checks;
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
        checks++;
    }

    private static int Main(string[] args)
    {
        try
        {
            Check(args.Length == 0 || args.Length == 2 && args[0] == "--baseline" ||
                args.Length == 4 && args[0] == "--baseline" && args[2] == "--candidate",
                "Usage: [--baseline original.dll [--candidate current.dll]]");
            Check(Marshal.SizeOf(typeof(CucpNative.INPUT)) == (IntPtr.Size == 8 ? 40 : 28), "INPUT size");
            Check(Marshal.OffsetOf(typeof(CucpNative.INPUT), "u").ToInt32() == (IntPtr.Size == 8 ? 8 : 4), "INPUT union alignment");
            Check(Marshal.SizeOf(typeof(CucpNative.INPUTUNION)) == (IntPtr.Size == 8 ? 32 : 24), "INPUTUNION size");
            Check(Marshal.SizeOf(typeof(CucpNative.MOUSEINPUT)) == (IntPtr.Size == 8 ? 32 : 24), "MOUSEINPUT size");
            Check(Marshal.SizeOf(typeof(CucpNative.KEYBDINPUT)) == (IntPtr.Size == 8 ? 24 : 16), "KEYBDINPUT size");
            Check(Marshal.SizeOf(typeof(CucpNative.HARDWAREINPUT)) == 8, "HARDWAREINPUT size");
            foreach (var type in new[] { typeof(CucpNative.RECT), typeof(CucpWin32.RECT), typeof(HelperWin32.RECT) })
                Check(Marshal.SizeOf(type) == 16, type.FullName + " size");
            Check(Marshal.SizeOf(typeof(CucpNative.POINT)) == 8 && Marshal.SizeOf(typeof(CucpWin32.POINT)) == 8, "POINT sizes");
            foreach (var field in typeof(CucpNative.INPUTUNION).GetFields())
                Check(Marshal.OffsetOf(typeof(CucpNative.INPUTUNION), field.Name).ToInt32() == 0, "Union field offset: " + field.Name);
            // CharSet.Auto follows Windows Unicode; Linux source-only checks use ANSI.
            var windows = Environment.OSVersion.Platform == PlatformID.Win32NT;
            Check(Marshal.SizeOf(typeof(CucpWin32.MONITORINFOEX)) == (windows ? 104 : 72), "MONITORINFOEX size");
            var sendInput = typeof(CucpNative).GetMethod("SendInput").GetCustomAttribute<DllImportAttribute>();
            Check(sendInput.Value == "user32.dll" && sendInput.SetLastError, "SendInput metadata");
            Check(typeof(CucpNative).GetMethod("SendUnicodeText").GetParameters()[0].ParameterType == typeof(string), "Unicode text API");
            Check(typeof(HelperWin32).GetMethod("GetWindowText").GetCustomAttribute<DllImportAttribute>().CharSet == CharSet.None,
                "Legacy helper default charset was silently changed");
            Check(typeof(CucpWin32).GetMethod("GetWindowText").GetCustomAttribute<DllImportAttribute>().CharSet == CharSet.Auto,
                "Legacy wrapper charset was silently changed");
            if (args.Length >= 2)
            {
                var before = Assembly.LoadFile(Path.GetFullPath(args[1]));
                var after = args.Length == 4 ? Assembly.LoadFile(Path.GetFullPath(args[3])) : typeof(CucpNative).Assembly;
                var expected = Describe(before);
                var actual = Describe(after);
                var missing = expected.Except(actual).ToArray();
                var added = actual.Except(expected).ToArray();
                Check(missing.Length == 0 && added.Length == 0,
                    "Baseline API/ABI mismatch\nMissing:\n" + string.Join("\n", missing) + "\nAdded:\n" + string.Join("\n", added));
                Console.WriteLine("PASS: " + expected.Length + " baseline public API, P/Invoke, marshalling and ABI entries match.");
            }
            Console.WriteLine("PASS: " + checks + " managed metadata/ABI checks; no Windows desktop methods executed.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }

    private static bool IsInteropType(Type type)
    {
        return new[] { "CucpNative", "CucpWin32", "HelperWin32" }.Any(name => type.FullName == name || type.FullName.StartsWith(name + "+", StringComparison.Ordinal));
    }

    private static string TypeName(Type type)
    {
        if (type.IsByRef) return TypeName(type.GetElementType()) + "&";
        if (type.IsArray) return TypeName(type.GetElementType()) + "[" + new string(',', type.GetArrayRank() - 1) + "]";
        if (type.IsGenericType)
            return type.GetGenericTypeDefinition().FullName + "<" + string.Join(",", type.GetGenericArguments().Select(TypeName)) + ">";
        return type.FullName ?? type.Name;
    }

    private static string Attributes(IEnumerable<CustomAttributeData> attributes)
    {
        return string.Join(";", attributes.OrderBy(a => a.AttributeType.FullName, StringComparer.Ordinal).Select(a =>
            TypeName(a.AttributeType) + "(" + string.Join(",", a.ConstructorArguments.Select(Value)) + ")" +
            string.Join(",", a.NamedArguments.OrderBy(n => n.MemberName, StringComparer.Ordinal).Select(n => n.MemberName + "=" + Value(n.TypedValue)))));
    }

    private static string Value(CustomAttributeTypedArgument value)
    {
        if (value.Value is Type) return TypeName((Type)value.Value);
        var array = value.Value as IEnumerable<CustomAttributeTypedArgument>;
        return array == null ? Convert.ToString(value.Value, CultureInfo.InvariantCulture) : "[" + string.Join(",", array.Select(Value)) + "]";
    }

    private static string Parameter(ParameterInfo parameter)
    {
        return TypeName(parameter.ParameterType) + ":" + parameter.Name + ":" + parameter.Attributes + ":" + Attributes(parameter.GetCustomAttributesData());
    }

    private static string[] Describe(Assembly assembly)
    {
        var result = new List<string>();
        const BindingFlags flags = BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly;
        foreach (var type in assembly.GetExportedTypes().Where(IsInteropType))
        {
            var prefix = TypeName(type);
            result.Add(prefix + " TYPE " + type.Attributes + " BASE " + (type.BaseType == null ? "" : TypeName(type.BaseType)));
            var layout = type.StructLayoutAttribute;
            if (layout != null) result.Add(prefix + " LAYOUT " + layout.Value + ":" + layout.Pack + ":" + layout.Size + ":" + layout.CharSet);
            if (type.IsValueType) result.Add(prefix + " SIZE " + Marshal.SizeOf(type));
            foreach (var field in type.GetFields(flags))
            {
                result.Add(prefix + " FIELD " + field.Name + ":" + TypeName(field.FieldType) + ":" + field.Attributes + ":" + Attributes(field.GetCustomAttributesData()) +
                    (field.IsLiteral ? ":" + Convert.ToString(field.GetRawConstantValue(), CultureInfo.InvariantCulture) : ""));
                if (type.IsValueType && !field.IsStatic) result.Add(prefix + " OFFSET " + field.Name + ":" + Marshal.OffsetOf(type, field.Name));
            }
            foreach (var method in type.GetMethods(flags))
                result.Add(prefix + " METHOD " + method.Name + ":" + method.Attributes + ":" + method.GetMethodImplementationFlags() + ":" +
                    Parameter(method.ReturnParameter) + "(" + string.Join(",", method.GetParameters().Select(Parameter)) + "):" + Attributes(method.GetCustomAttributesData()));
            foreach (var ctor in type.GetConstructors(flags))
                result.Add(prefix + " CTOR " + ctor.Attributes + "(" + string.Join(",", ctor.GetParameters().Select(Parameter)) + ")");
        }
        return result.OrderBy(line => line, StringComparer.Ordinal).ToArray();
    }
}
