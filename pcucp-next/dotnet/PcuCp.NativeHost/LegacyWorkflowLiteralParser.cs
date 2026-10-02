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

    // Declaration/contextual keywords are not qualified as single-command
    // subexpressions. Keep this guard local to the new embedded-text subset;
    // top-level keyword classification remains a separate historical gap.
    private static readonly HashSet<string> UnqualifiedSubexpressionStarts = new(Comparer)
    {
        "public", "private", "static", "interface", "enum", "namespace", "module", "type", "assembly", "command", "hidden", "base", "default"
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
            var startsHereString = first == '@' && index + 1 < step.Length && step[index + 1] is '\'' or '"';
            var startsQuoted = IsSingle(first) || IsDouble(first) || startsHereString;
            if (commandStart && first is '.' or '+' or '-' or '!')
                return Reject("unsupported_token", "Expression and dot-sourcing prefixes require further parser qualification.");
            if (first == '#' || first == '@' && !startsHereString)
                return Reject("unsupported_token", "Comments and splatting are outside the literal-command subset.");
            if (first == '-' && index + 1 < step.Length && (char.IsLetter(step[index + 1]) || step[index + 1] is '_' or '?'))
                return Reject("unsupported_token", "unsupported token type 'CommandParameter'");
            var value = new StringBuilder();
            if (startsHereString)
            {
                var failure = ReadHereString(step, ref index, value);
                if (failure is not null) return failure;
                // A here-string is a complete token. Do not reinterpret an
                // adjacent suffix, operator or comment as part of its value.
                if (index < step.Length && !char.IsWhiteSpace(step[index]))
                    return Reject("unsupported_token", "Adjacent here-string suffixes require further parser qualification.");
            }
            while (!startsHereString && index < step.Length && !char.IsWhiteSpace(step[index]))
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
                        if (!single && quoted == '$')
                        {
                            if (!ReadDollarText(step, ref index, value))
                                return Reject("unsupported_token", "This embedded dollar syntax requires further parser qualification.");
                            continue;
                        }
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

    // Only a small syntactically unambiguous subset of embedded dollar text is
    // admitted. PSParser still parses embedded syntax even though the legacy
    // adapter only consumes its outer String token. Balancing parentheses or
    // treating every quoted dollar as data would silently accept parse errors.
    // Keep complex/nested syntax as an explicit gap, and preserve accepted
    // source slices verbatim rather than cooking escapes inside a subexpression.
    private static bool ReadDollarText(string step, ref int index, StringBuilder value)
    {
        var start = index - 1; // The caller has consumed '$'.
        if (index == step.Length || step[index] is ' ' or '\t' or '\r' or '\n' || IsSingle(step[index]) || IsDouble(step[index]))
        {
            value.Append('$');
            return true;
        }
        if (step[index] == '(')
        {
            index++;
            while (index < step.Length && step[index] is ' ' or '\t') index++;
            var nameStart = index;
            if (index == step.Length || !IsIdentifierStart(step[index])) return false;
            while (index < step.Length && (IsIdentifierPart(step[index]) || step[index] == '-')) index++;
            var name = step[nameStart..index];
            if (ReservedStarts.Contains(name) || UnqualifiedSubexpressionStarts.Contains(name)) return false;
            while (index < step.Length && step[index] is ' ' or '\t') index++;
            if (index == step.Length || step[index] != ')') return false;
            index++;
        }
        else
        {
            var braced = step[index] == '{';
            if (braced) index++;
            if (index == step.Length || !IsIdentifierPart(step[index])) return false;
            while (index < step.Length && IsIdentifierPart(step[index])) index++;
            if (index < step.Length && step[index] == ':')
            {
                index++;
                if (index == step.Length || !IsIdentifierPart(step[index])) return false;
                while (index < step.Length && IsIdentifierPart(step[index])) index++;
            }
            if (braced)
            {
                if (index == step.Length || step[index] != '}') return false;
                index++;
            }
            else if (index < step.Length && (step[index] is ':' or '?' || char.IsLetterOrDigit(step[index])))
                return false; // Do not split a longer PS variable at an unqualified name character.
        }
        value.Append(step, start, index - start);
        return true;
    }

    private static ParsedStep? ReadHereString(string step, ref int index, StringBuilder value)
    {
        var single = step[index + 1] == '\'';
        index += 2;
        while (index < step.Length && step[index] is ' ' or '\t') index++;
        if (index == step.Length || step[index] is not ('\r' or '\n'))
            return Reject("parse_error", "A here-string header must end with a newline.");
        if (step[index] == '\r' && (index + 1 == step.Length || step[index + 1] != '\n'))
            return Reject("unsupported_token", "Bare-CR here-string boundaries are not yet qualified.");
        index += step[index] == '\r' ? 2 : 1;
        var atLineStart = true;
        var beforeBoundary = 0;
        while (index < step.Length)
        {
            if (atLineStart && index + 1 < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index])) && step[index + 1] == '@')
            {
                value.Length = beforeBoundary; // Exclude the final physical newline only.
                index += 2;
                return null;
            }
            atLineStart = false;
            var c = step[index++];
            if (c is '\r' or '\n')
            {
                if (c == '\r' && (index == step.Length || step[index] != '\n'))
                    return Reject("unsupported_token", "Bare-CR here-string boundaries are not yet qualified.");
                beforeBoundary = value.Length;
                value.Append(c);
                if (c == '\r') value.Append(step[index++]);
                atLineStart = true;
                continue;
            }
            if (!single && c == '$')
            {
                if (!ReadDollarText(step, ref index, value))
                    return Reject("unsupported_token", "This embedded dollar syntax requires further parser qualification.");
                continue;
            }
            if (!single && c == '`' && index < step.Length) c = Unescape(step[index++]);
            value.Append(c);
        }
        return Reject("parse_error", "The here-string is missing its column-zero terminator.");
    }

    private static bool IsIdentifierStart(char c) => char.IsAsciiLetter(c) || c == '_';
    private static bool IsIdentifierPart(char c) => IsIdentifierStart(c) || char.IsAsciiDigit(c);

    private static bool IsSingle(char c) => c is '\'' or '\u2018' or '\u2019' or '\u201A' or '\u201B';
    private static bool IsDouble(char c) => c is '"' or '\u201C' or '\u201D' or '\u201E';
    private static char Unescape(char c) => c switch
    {
        '0' => '\0', 'a' => '\a', 'b' => '\b', 'f' => '\f', 'n' => '\n', 'r' => '\r', 't' => '\t', 'v' => '\v',
        _ => c // PowerShell 5.1: `e and `u do not have the PowerShell 6+ meanings.
    };
    private static ParsedStep Reject(string error, string detail) => new(false, error, detail, []);
}
