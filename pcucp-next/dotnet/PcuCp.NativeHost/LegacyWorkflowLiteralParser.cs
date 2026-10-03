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

    // Contextual words such as public, static and default are command names
    // in a subexpression (observed PS5.1 run 37074340659). Actual statement
    // keywords still need their own grammar and are never admitted as names.
    private const int MaximumEmbeddedDepth = 64;
    private enum DollarScanContext { ExpandableString, HereString, Expression }

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
        if (step.Length > 65536) return Reject("unsupported_token", "Step exceeds the literal input limit.");
        var syntaxFailure = PreflightParseErrors(step);
        if (syntaxFailure is not null) return syntaxFailure;
        var items = new List<string>();
        var index = 0;
        var commandStart = true;
        while (index < step.Length)
        {
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
            var signedNumber = commandStart && first is ('+' or '-');
            if ((commandStart && first is ('.' or '!' or '[')) || first == ']' ||
                signedNumber && (index + 1 == step.Length || !(char.IsAsciiDigit(step[index + 1]) || step[index + 1] == '.')))
                return Reject("unsupported_token", "Expression and dot-sourcing prefixes require further parser qualification.");
            if (first == '[' && (index + 1 == step.Length || char.IsWhiteSpace(step[index + 1]) || step[index + 1] is '\0' or '(' or ')' or '{' or '}' or ';' or '|' or '&' or ','))
                return Reject("unsupported_token", "A standalone bracket is not a literal argument.");
            if (first == '#' || first == '@' && !startsHereString)
                return Reject("unsupported_token", "Comments and splatting are outside the literal-command subset.");
            if (first == '-' && index + 1 < step.Length && (char.IsLetter(step[index + 1]) || step[index + 1] is '_' or '?'))
                return Reject("unsupported_token", "unsupported token type 'CommandParameter'");
            var value = new StringBuilder();
            if (startsHereString)
            {
                var failure = ReadHereString(step, ref index, value);
                if (failure is not null) return failure;
                if (step.AsSpan(tokenStart, index - tokenStart).Contains('\0'))
                    return Reject("unsupported_token", "NUL inside here-strings is not yet qualified.");
                // The footer ends the String token even without whitespace.
                // Observed word suffixes begin a separate token; punctuation
                // suffixes still require the outer token grammar to qualify.
                if (index < step.Length && !char.IsWhiteSpace(step[index]) && !IsIdentifierStart(step[index]))
                    return Reject("unsupported_token", "This adjacent here-string suffix requires further parser qualification.");
            }
            while (!startsHereString && index < step.Length && !char.IsWhiteSpace(step[index]))
            {
                // A physical NUL starts another generic token, but is retained
                // at that token's start. It is not whitespace or end-of-input.
                if (step[index] == '\0' && index != tokenStart) break;
                var c = step[index++];
                if (c == '$')
                {
                    // A standalone variable/subexpression remains a rejected
                    // token; dollar text inside a generic word is outer data.
                    if (startsQuoted || index - 1 == tokenStart)
                        return Reject("unsupported_token", "This unquoted dollar syntax requires further parser qualification.");
                    var failure = ReadDollarText(step, ref index, value);
                    if (failure is not null) return failure;
                    continue;
                }
                if (c is '(' or ')' or '{' or '}' or ';' or '|' or '&' or '<' or '>' or ',')
                    return Reject("unsupported_token", "Operators, variables and execution constructs are not literal command tokens.");
                if (c == '`')
                {
                    if (index == step.Length || step[index] == '\0' && index - 1 != tokenStart)
                    { value.Append('`'); continue; }
                    // Within a generic word only the immediate character is
                    // escaped. In CRLF the remaining LF is still a boundary.
                    var escaped = step[index++];
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
                        if (quoted == '\0') return Reject("unsupported_token", "NUL inside quoted strings is not yet qualified.");
                        if (single ? IsSingle(quoted) : IsDouble(quoted))
                        {
                            if (index < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index])))
                            { value.Append(step[index++]); continue; }
                            closed = true;
                            break;
                        }
                        if (!single && quoted == '$')
                        {
                            var failure = ReadDollarText(step, ref index, value);
                            if (failure is not null) return failure;
                            continue;
                        }
                        if (!single && quoted == '`' && index < step.Length)
                        {
                            if (step[index] == '\0') return Reject("unsupported_token", "NUL inside quoted strings is not yet qualified.");
                            quoted = Unescape(step[index++]);
                        }
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
            var wasCommandStart = commandStart;
            if (commandStart)
            {
                if (signedNumber && !IsSignedDecimalLiteral(step.AsSpan(tokenStart, index - tokenStart)))
                    return Reject("unsupported_token", "This signed numeric expression is not yet qualified.");
                if (ReservedStarts.Contains(content)) return Reject("unsupported_token", "Reserved statement keywords are not literal commands.");
                if (startsQuoted || content.Length > 0 && (char.IsDigit(content[0]) || content[0] is '+' or '-'))
                {
                    // A leading quoted/number expression cannot silently be
                    // reinterpreted as a command followed by arbitrary arguments.
                    var next = index;
                    while (next < step.Length && char.IsWhiteSpace(step[next]) && step[next] is not ('\r' or '\n')) next++;
                    var remainder = step[next..];
                    if (remainder.Length > 0 && remainder[0] is not ('\r' or '\n'))
                        return Reject("parse_error", "Expression-form command prefixes are not supported.");
                }
                commandStart = false;
            }
            // PS5.1 omits a generic token consisting only of a physical NUL
            // boundary. Retain NUL-prefixed words and cooked escape payloads.
            var physicalNulBoundary = step.AsSpan(tokenStart, index - tokenStart).SequenceEqual("\0");
            if (content.Length > 0 && !physicalNulBoundary) items.Add(content);
            // Quoted strings keep their value as an ordinary argument; only
            // generic words (including backtick-cooked words) enter raw mode.
            if (!wasCommandStart && !startsQuoted && content == "--%")
            {
                // Marker-adjacent physical NUL remains outside this repair's
                // candidate subset. Keep this boundary closed; NUL inside an
                // already-delimited raw argument is a separate boundary.
                if (index < step.Length && step[index] == '\0')
                    return Reject("unsupported_token", "NUL adjacent to a stop-parsing marker is not yet qualified.");
                // Stop-parsing retains the rest of this physical line as one
                // raw argument. No dollar, escape, quote or percent expansion.
                while (index < step.Length && char.IsWhiteSpace(step[index]) && step[index] is not ('\r' or '\n')) index++;
                var rawStart = index;
                var inDoubleQuotes = false;
                while (index < step.Length && step[index] is not ('\r' or '\n'))
                {
                    var raw = step[index];
                    if (IsDouble(raw)) inDoubleQuotes = !inDoubleQuotes;
                    if (!inDoubleQuotes && (raw == '|' || raw == '&' && index + 1 < step.Length && step[index + 1] == '&'))
                        return Reject("unsupported_token", "Stop-parsing does not consume pipeline operators.");
                    index++;
                }
                if (index > rawStart) items.Add(step[rawStart..index]);
            }
        }
        return new(items.Count > 0, items.Count > 0 ? "" : "empty_step", "", items.ToArray());
    }

    // A bounded numeric grammar, not a conversion or expression evaluator.
    // Type suffixes, multipliers, hex and out-of-range values remain gaps.
    private static bool IsSignedDecimalLiteral(ReadOnlySpan<char> raw)
    {
        if (raw.Length < 2 || raw[0] is not ('+' or '-')) return false;
        var offset = 1;
        var digits = 0;
        while (offset < raw.Length && char.IsAsciiDigit(raw[offset])) { offset++; digits++; }
        if (offset < raw.Length && raw[offset] == '.')
        {
            offset++;
            while (offset < raw.Length && char.IsAsciiDigit(raw[offset])) { offset++; digits++; }
        }
        if (digits == 0) return false;
        if (offset < raw.Length && raw[offset] is 'e' or 'E')
        {
            offset++;
            if (offset < raw.Length && raw[offset] is '+' or '-') offset++;
            var exponentStart = offset;
            while (offset < raw.Length && char.IsAsciiDigit(raw[offset])) offset++;
            if (offset == exponentStart) return false;
        }
        return offset == raw.Length && decimal.TryParse(raw, System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out _);
    }

    // These scanners validate syntax only; no value is evaluated. In particular,
    // the outer legacy String token retains a subexpression's original spelling.
    // Unsupported expression families fail closed rather than being accepted by
    // a delimiter balancer. The depth bound also protects adversarial input.
    // API: caller consumed '$'; null means success, other results are explicit
    // syntax/qualification failures. A failed scan may have advanced index.
    private static ParsedStep? ReadDollarText(string step, ref int index, StringBuilder value, int depth = 0, DollarScanContext context = DollarScanContext.ExpandableString)
    {
        if (depth >= MaximumEmbeddedDepth)
            return EmbeddedUnsupported("The embedded nesting limit was exceeded.");
        var start = index - 1;
        if (index == step.Length || IsEmbeddedWhitespace(step[index]) || IsSingle(step[index]) || IsDouble(step[index]))
        {
            value.Append('$');
            return null;
        }
        ParsedStep? failure;
        if (step[index] == '(')
            failure = ReadEmbeddedSubexpression(step, ref index, depth + 1, context);
        else if (step[index] == '{')
            failure = ReadBracedVariable(step, ref index);
        else
            failure = ReadUnbracedVariable(step, ref index);
        if (failure is not null) return failure;
        if (step.AsSpan(start, index - start).Contains('\0'))
            return EmbeddedUnsupported("Physical NUL inside quoted dollar syntax is not yet qualified.");
        value.Append(step, start, index - start);
        return null;
    }

    private static ParsedStep? ReadUnbracedVariable(string step, ref int index)
    {
        // Special variables end after one character; suffix text is parsed by
        // the caller's string or expression context, never folded into the name.
        if (step[index] is '$' or '^' or '?') { index++; return null; }
        if (!IsVariablePart(step[index]))
            return EmbeddedUnsupported("This variable spelling is not yet qualified.");
        while (index < step.Length && IsVariablePart(step[index])) index++;
        if (index < step.Length && step[index] == ':')
        {
            // A doubled colon ends the variable before the member-like text.
            // A single scope/drive separator requires a nonempty name. Later
            // single colons remain name text, but ANY doubled colon ends it.
            if (index + 1 < step.Length && step[index + 1] == ':') return null;
            index++;
            if (index == step.Length || !IsVariablePart(step[index]))
                return EmbeddedMalformed("A scoped variable requires a name after ':'.");
            while (index < step.Length && (IsVariablePart(step[index]) || step[index] == ':'))
            {
                if (step[index] == ':' && index + 1 < step.Length && step[index + 1] == ':') break;
                index++;
            }
        }
        return null;
    }

    private static ParsedStep? ReadBracedVariable(string step, ref int index)
    {
        var nameStart = ++index;
        while (index < step.Length && step[index] != '}')
        {
            var c = step[index++];
            if (c == '{') return EmbeddedMalformed("An unescaped '{' cannot occur in a braced variable.");
            if (IsDouble(c) || c is '\r' or '\n')
                return EmbeddedMalformed("The braced variable is missing its closing '}'.");
            if (!IsVariablePart(c) && c is not (':' or '-' or '.' or ' ' or '\t'))
                return EmbeddedUnsupported("This braced variable spelling is not yet qualified.");
        }
        if (index == step.Length) return EmbeddedMalformed("The braced variable is missing its closing '}'.");
        if (index == nameStart) return EmbeddedMalformed("A braced variable requires a name.");
        var name = step.AsSpan(nameStart, index - nameStart);
        var colon = name.IndexOf(':');
        if (colon == name.Length - 1)
            return EmbeddedMalformed("A scoped variable requires a name after ':'.");
        if (colon == 0)
            return EmbeddedUnsupported("An empty scope/drive prefix is not yet qualified.");
        index++;
        return null;
    }

    // The outer string pass is deliberately separate from expression grammar.
    // PS5.1 counts raw parentheses even inside quotes. Ordinary expandable
    // strings also collapse a backtick/double-quote followed by a double quote;
    // here-strings do not. Parse the resulting bounded body, then retain the
    // original source slice in the caller. Never execute or evaluate the body.
    private static ParsedStep? ReadEmbeddedSubexpression(string step, ref int index, int depth, DollarScanContext context)
    {
        if (depth >= MaximumEmbeddedDepth)
            return EmbeddedUnsupported("The embedded nesting limit was exceeded.");
        if (context == DollarScanContext.Expression)
            return ReadEmbeddedBody(step, ref index, depth);

        var body = new StringBuilder();
        var parentheses = 0;
        while (index < step.Length)
        {
            var c = step[index++];
            if (c == '(')
            {
                parentheses++;
                if (depth + parentheses > MaximumEmbeddedDepth)
                    return EmbeddedUnsupported("The embedded nesting limit was exceeded.");
            }
            else if (c == ')') parentheses--;
            if (context == DollarScanContext.ExpandableString && (c == '`' || IsDouble(c)) &&
                index < step.Length && IsDouble(step[index]))
                c = step[index++];
            body.Append(c);
            if (parentheses != 0) continue;
            var nestedIndex = 0;
            var text = body.ToString();
            var failure = ReadEmbeddedBody(text, ref nestedIndex, depth);
            if (failure is not null) return failure;
            return nestedIndex == text.Length ? null : EmbeddedMalformed("Unexpected text follows the embedded expression.");
        }
        return EmbeddedMalformed("The subexpression is missing its raw closing ')'.");
    }

    // Supported bodies: an empty body, one command plus literal arguments, or
    // an expression made from integer/string/variable/subexpression operands
    // separated by arithmetic operators. Other statements/operators stay gaps.
    private static ParsedStep? ReadEmbeddedBody(string step, ref int index, int depth)
    {
        if (depth >= MaximumEmbeddedDepth)
            return EmbeddedUnsupported("The embedded nesting limit was exceeded.");
        index++; // '('
        SkipEmbeddedWhitespace(step, ref index);
        if (index == step.Length) return EmbeddedMalformed("The subexpression is missing ')'.");
        if (step[index] == ')') { index++; return null; }
        if (IsIdentifierStart(step[index]))
        {
            var start = index++;
            while (index < step.Length && (IsIdentifierPart(step[index]) || step[index] == '-')) index++;
            var name = step[start..index];
            if (Comparer.Equals(name, "if") || Comparer.Equals(name, "enum"))
            {
                var afterName = index;
                SkipEmbeddedWhitespace(step, ref afterName);
                if (afterName == step.Length || step[afterName] == ')')
                    return EmbeddedMalformed("The embedded statement requires its declaration or condition.");
                return EmbeddedUnsupported("This embedded statement grammar is not yet qualified.");
            }
            if (ReservedStarts.Contains(name))
                return EmbeddedUnsupported("This embedded statement grammar is not yet qualified.");
            return ReadEmbeddedCommandTail(step, ref index, depth);
        }
        var failure = ReadEmbeddedOperand(step, ref index, depth);
        if (failure is not null) return failure;
        while (true)
        {
            SkipEmbeddedWhitespace(step, ref index);
            if (index == step.Length) return EmbeddedMalformed("The subexpression is missing ')'.");
            if (step[index] == ')') { index++; return null; }
            if (IsDouble(step[index])) return EmbeddedMalformed("The subexpression is missing ')'.");
            if (step[index] is not ('+' or '-' or '*' or '/' or '%'))
            {
                if (IsVariablePart(step[index]) || step[index] is '$' or '^')
                    return EmbeddedMalformed("An expression operand cannot be followed by an adjacent bare token.");
                if (step[index] == ':' && index + 1 < step.Length && step[index + 1] == ':')
                {
                    var member = index + 2;
                    SkipEmbeddedWhitespace(step, ref member);
                    if (member == step.Length || step[member] == ')')
                        return EmbeddedMalformed("Static member access requires a member expression.");
                }
                return EmbeddedUnsupported("This embedded expression operator is not yet qualified.");
            }
            var operation = step[index++];
            if (operation is '+' or '-' && index < step.Length && step[index] == operation)
                return EmbeddedUnsupported("Increment and decrement expressions are not yet qualified.");
            SkipEmbeddedWhitespace(step, ref index);
            if (index == step.Length || step[index] == ')')
                return EmbeddedMalformed("The embedded arithmetic operator requires an operand.");
            failure = ReadEmbeddedOperand(step, ref index, depth);
            if (failure is not null) return failure;
        }
    }

    private static ParsedStep? ReadEmbeddedCommandTail(string step, ref int index, int depth)
    {
        while (true)
        {
            if (index == step.Length) return EmbeddedMalformed("The subexpression is missing ')'.");
            if (step[index] == ')') { index++; return null; }
            if (!IsEmbeddedWhitespace(step[index]))
            {
                if (IsDouble(step[index])) return EmbeddedMalformed("The subexpression is missing ')'.");
                return EmbeddedUnsupported("This embedded command boundary is not yet qualified.");
            }
            var sawNewline = false;
            while (index < step.Length && IsEmbeddedWhitespace(step[index]))
                sawNewline |= step[index++] is '\r' or '\n';
            if (index == step.Length) return EmbeddedMalformed("The subexpression is missing ')'.");
            if (step[index] == ')') { index++; return null; }
            if (step[index] == '#')
            {
                // A close hidden by a line comment cannot terminate the body.
                while (index < step.Length && step[index] is not ('\r' or '\n')) index++;
                if (index == step.Length || step.IndexOf(')', index) < 0)
                    return EmbeddedMalformed("The subexpression is missing an uncommented ')'.");
                return EmbeddedUnsupported("Embedded comments require further parser qualification.");
            }
            if (sawNewline && IsDouble(step[index]) && index + 1 < step.Length && step[index + 1] == '@')
                return EmbeddedMalformed("The here-string footer precedes the subexpression closing ')'.");
            if (sawNewline)
                return EmbeddedUnsupported("Multiple embedded statements are not yet qualified.");
            var failure = ReadEmbeddedCommandArgument(step, ref index, depth);
            if (failure is not null) return failure;
        }
    }

    // A command argument can join bare, variable and quoted fragments. Scanning
    // the complete bounded argument is necessary to diagnose an unclosed quote
    // after a mode-dependent outer transform; stopping at its first fragment
    // would hide that parse error behind an unsupported-boundary result.
    private static ParsedStep? ReadEmbeddedCommandArgument(string step, ref int index, int depth)
    {
        while (index < step.Length && !IsEmbeddedWhitespace(step[index]) && step[index] != ')')
        {
            ParsedStep? failure;
            if (IsSingle(step[index]) || IsDouble(step[index]))
                failure = ReadEmbeddedQuotedOperand(step, ref index, depth);
            else if (step[index] == '$')
            {
                index++;
                failure = ReadDollarText(step, ref index, new StringBuilder(), depth, DollarScanContext.Expression);
            }
            else if (IsVariablePart(step[index]) || step[index] is '-' or '.')
            {
                while (index < step.Length && (IsVariablePart(step[index]) || step[index] is '-' or '.')) index++;
                failure = null;
            }
            else return EmbeddedUnsupported("This embedded command argument is not yet qualified.");
            if (failure is not null) return failure;
        }
        return null;
    }

    private static ParsedStep? ReadEmbeddedOperand(string step, ref int index, int depth)
    {
        if (index == step.Length || step[index] == ')')
            return EmbeddedMalformed("The embedded expression requires an operand.");
        if (IsSingle(step[index]) || IsDouble(step[index]))
            return ReadEmbeddedQuotedOperand(step, ref index, depth);
        if (step[index] == '$')
        {
            index++;
            return ReadDollarText(step, ref index, new StringBuilder(), depth, DollarScanContext.Expression);
        }
        if (step[index] is '+' or '-') index++;
        if (index == step.Length || !char.IsAsciiDigit(step[index]))
            return EmbeddedUnsupported("This embedded operand is not yet qualified.");
        var numberStart = index;
        while (index < step.Length && char.IsAsciiDigit(step[index])) index++;
        if (index - numberStart > 18)
            return EmbeddedUnsupported("Large numeric literals require further parser qualification.");
        return null;
    }

    private static ParsedStep? ReadEmbeddedQuotedOperand(string step, ref int index, int depth)
    {
        var single = IsSingle(step[index++]);
        while (index < step.Length)
        {
            var c = step[index++];
            if (single ? IsSingle(c) : IsDouble(c))
            {
                if (index < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index])))
                { index++; continue; }
                return null;
            }
            // The enclosing extraction pass already validated raw parenthesis
            // boundaries and applied its context-dependent quote transform.
            if (!single && c == '`' && index < step.Length) { index++; continue; }
            if (!single && c == '$')
            {
                var failure = ReadDollarText(step, ref index, new StringBuilder(), depth);
                if (failure is not null) return failure;
            }
        }
        return EmbeddedMalformed("The embedded string is missing its terminator.");
    }

    private static bool IsVariablePart(char c) => char.IsLetterOrDigit(c) || c is '_' or '?';
    private static bool IsEmbeddedWhitespace(char c) => c is ' ' or '\t' or '\r' or '\n';
    private static void SkipEmbeddedWhitespace(string step, ref int index)
    {
        while (index < step.Length && IsEmbeddedWhitespace(step[index])) index++;
    }
    private static ParsedStep EmbeddedUnsupported(string detail) => Reject("unsupported_token", detail);
    private static ParsedStep EmbeddedMalformed(string detail) => Reject("parse_error", detail);

    private static ParsedStep? ReadHereString(string step, ref int index, StringBuilder value)
    {
        var single = step[index + 1] == '\'';
        index += 2;
        while (index < step.Length && step[index] is ' ' or '\t') index++;
        if (index == step.Length || step[index] is not ('\r' or '\n'))
            return Reject("parse_error", "A here-string header must end with a newline.");
        var headerNewline = step[index++];
        if (headerNewline == '\r' && index < step.Length && step[index] == '\n') index++;
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
                beforeBoundary = value.Length;
                value.Append(c);
                if (c == '\r' && index < step.Length && step[index] == '\n') value.Append(step[index++]);
                atLineStart = true;
                continue;
            }
            if (!single && c == '$')
            {
                var failure = ReadDollarText(step, ref index, value, context: DollarScanContext.HereString);
                if (failure is not null) return failure;
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
