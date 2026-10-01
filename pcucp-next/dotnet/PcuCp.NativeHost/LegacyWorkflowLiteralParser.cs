using System.Text;
using System.Text.Json;

// Qualification-only candidate. Exclude this entire file from shipped NativeHost.
internal static partial class LegacyWorkflowKernel
{
    private static readonly HashSet<string> ReservedStarts = new(Comparer)
    {
        "begin", "break", "catch", "class", "continue", "data", "define", "do", "dynamicparam", "else", "elseif", "end", "exit",
        "filter", "finally", "for", "foreach", "from", "function", "if", "in", "param", "process", "return", "switch", "throw",
        "trap", "try", "until", "using", "var", "while", "workflow", "parallel", "sequence", "inlinescript", "configuration"
    };

    internal static object Plan(JsonElement args)
    {
        Fields(args, "rest");
        return Plan(ReadRest(args, allowNul: false));
    }

    internal static object Plan(string[] rest)
    {
        var specs = ReadStepSpecs(rest);
        return Assemble(rest, specs, specs.Select(ParseStep).ToArray());
    }

    // Explicit literal-only lexer. It never expands a variable, substitutes a
    // command, treats a string as executable code, or invokes a parser runtime.
    // Rejections outside this subset are intentional qualification gaps, not
    // evidence of compatibility with every token sequence accepted by PSParser.
    internal static ParsedStep ParseStep(string step)
    {
        if (step.Length > 65536 || step.Contains('\0')) return Reject("unsupported_token", "Step exceeds the literal input limit or contains NUL.");
        var items = new List<string>();
        var index = 0;
        var commandStart = true;
        while (index < step.Length)
        {
            if (char.IsWhiteSpace(step[index]) && step[index] is not (' ' or '\t' or '\r' or '\n'))
                return Reject("unsupported_token", "Non-ASCII token whitespace is not yet qualified.");
            if (char.IsWhiteSpace(step[index]))
            {
                if (step[index] is '\r' or '\n') commandStart = true;
                index++;
                continue;
            }
            if (step[index] == '`' && index + 1 < step.Length && step[index + 1] is '\r' or '\n')
            {
                index += 2;
                if (step[index - 1] == '\r' && index < step.Length && step[index] == '\n') index++;
                continue;
            }
            var first = step[index];
            var tokenStart = index;
            var startsQuoted = IsSingle(first) || IsDouble(first);
            if (commandStart && first is '.' or '+' or '-' or '!')
                return Reject("unsupported_token", "Expression and dot-sourcing prefixes require further parser qualification.");
            if (first == '#' || first == '@') return Reject("unsupported_token", "Comments, splatting and here-strings are outside the literal-command subset.");
            if (first == '-' && index + 1 < step.Length && (char.IsLetter(step[index + 1]) || step[index + 1] is '_' or '?'))
                return Reject("unsupported_token", "unsupported token type 'CommandParameter'");
            var value = new StringBuilder();
            while (index < step.Length && !char.IsWhiteSpace(step[index]))
            {
                var c = step[index++];
                if (c is '$' or '(' or ')' or '{' or '}' or '[' or ']' or ';' or '|' or '&' or '<' or '>' or ',')
                    return Reject("unsupported_token", "Operators, variables and execution constructs are not literal command tokens.");
                if (c == '`')
                {
                    if (index == step.Length) { value.Append('`'); continue; }
                    var escaped = step[index++];
                    if (escaped is '\r' or '\n')
                        return Reject("unsupported_token", "Adjacent-token line continuation is not yet qualified.");
                    value.Append(Unescape(escaped));
                    continue;
                }
                if (IsSingle(c) || IsDouble(c))
                {
                    var single = IsSingle(c);
                    var closed = false;
                    while (index < step.Length)
                    {
                        var quoted = step[index++];
                        if (single ? IsSingle(quoted) : IsDouble(quoted))
                        {
                            if (index < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index])))
                            { value.Append(step[index++]); continue; }
                            closed = true;
                            break;
                        }
                        if (!single && quoted == '$') return Reject("unsupported_token", "Expandable strings require further parser qualification.");
                        if (!single && quoted == '`' && index < step.Length) quoted = Unescape(step[index++]);
                        value.Append(quoted);
                    }
                    if (!closed) return Reject("parse_error", "The string is missing its terminator.");
                    continue;
                }
                value.Append(c);
            }
            var content = value.ToString();
            // PSParser rejects an unquoted standalone decrement operator here.
            // Quoted or backtick-escaped "--" remains literal data; do not use
            // the cooked value alone to distinguish those forms.
            if (step.AsSpan(tokenStart, index - tokenStart).SequenceEqual("--"))
                return Reject("unsupported_token", "unsupported token type 'Operator'");
            if (index < step.Length && char.IsWhiteSpace(step[index]) && step[index] is not (' ' or '\t' or '\r' or '\n'))
                return Reject("unsupported_token", "Non-ASCII token whitespace is not yet qualified.");
            if (commandStart)
            {
                if (ReservedStarts.Contains(content)) return Reject("unsupported_token", "Reserved statement keywords are not literal commands.");
                if (startsQuoted || content.Length > 0 && (char.IsDigit(content[0]) || content[0] is '+' or '-'))
                {
                    // A leading quoted/number expression cannot silently be
                    // reinterpreted as a command followed by arbitrary arguments.
                    var remainder = step[index..].TrimStart(' ', '\t');
                    if (remainder.Length > 0 && remainder[0] is not ('\r' or '\n'))
                        return Reject("parse_error", "Expression-form command prefixes are not supported.");
                }
                commandStart = false;
            }
            if (content.Length > 0) items.Add(content); // Original drops empty literal strings.
        }
        return new(items.Count > 0, items.Count > 0 ? "" : "empty_step", "", items.ToArray());
    }

    private static bool IsSingle(char c) => c is '\'' or '\u2018' or '\u2019' or '\u201A' or '\u201B';
    private static bool IsDouble(char c) => c is '"' or '\u201C' or '\u201D' or '\u201E';
    private static char Unescape(char c) => c switch
    {
        '0' => '\0', 'a' => '\a', 'b' => '\b', 'f' => '\f', 'n' => '\n', 'r' => '\r', 't' => '\t', 'v' => '\v',
        _ => c // PowerShell 5.1: `e and `u do not have the PowerShell 6+ meanings.
    };
    private static ParsedStep Reject(string error, string detail) => new(false, error, detail, []);
}
