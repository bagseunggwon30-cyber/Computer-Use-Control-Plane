using System.Text;

// Qualification-only preflight: this file belongs to the contract-test project,
// never NativeHost. A null result means no error was established in this bounded
// scan, NOT that arbitrary PowerShell syntax has been validated. It cannot emit
// accepted tokens or widen the literal parser's accepted language.
internal static partial class LegacyWorkflowKernel
{
    // These grammar productions require a condition, declaration or scriptblock.
    // Bare words in argument position, quoted words and escaped words are data.
    private static readonly HashSet<string> IncompleteStatementKeywords = new(Comparer)
    {
        "if", "elseif", "while", "for", "foreach", "switch", "function", "filter", "class", "enum",
        "begin", "process", "end", "dynamicparam", "try", "catch", "finally", "do", "trap", "data"
    };

    private static ParsedStep? PreflightParseErrors(string step)
    {
        var groups = new Stack<char>();
        var atStatementStart = true;
        var atTokenStart = true;
        var index = 0;
        while (index < step.Length)
        {
            var c = step[index];
            if (char.IsWhiteSpace(c))
            {
                if (c is '\r' or '\n') atStatementStart = true;
                atTokenStart = true;
                index++;
                continue;
            }
            if (atTokenStart && !atStatementStart && PreflightStopParsingMarker(step, index, out var markerEnd))
            {
                // A physical NUL immediately after a cooked marker is an
                // unqualified token boundary. Do not reinterpret its opaque
                // suffix as quote/expression syntax. Reject it here as well
                // as in the ordinary scanner, keeping this fix independently
                // fail closed while the Windows oracle result remains unknown.
                if (markerEnd < step.Length && step[markerEnd] == '\0')
                    return Reject("unsupported_token", "NUL adjacent to a stop-parsing marker is not yet qualified.");
                index = markerEnd;
                var doubleQuoted = false;
                while (index < step.Length && step[index] is not ('\r' or '\n'))
                {
                    var raw = step[index];
                    if (!doubleQuoted && (raw == '|' || raw == '&' && index + 1 < step.Length && step[index + 1] == '&')) break;
                    if (IsDouble(raw)) doubleQuoted = !doubleQuoted;
                    index++;
                }
                continue;
            }
            if (c == '`')
            {
                if (atTokenStart && index + 1 < step.Length && step[index + 1] is '\r' or '\n')
                {
                    index += 2;
                    if (step[index - 1] == '\r' && index < step.Length && step[index] == '\n') index++;
                    continue; // A standalone line continuation preserves command position.
                }
                // Inside a token, escaped physical LF remains data; CRLF
                // retains its LF as a boundary, matching PS5 argument scanning.
                index += index + 1 < step.Length ? 2 : 1;
                atStatementStart = false;
                atTokenStart = false;
                continue;
            }
            if (atTokenStart && c == '#')
            {
                while (index < step.Length && step[index] is not ('\r' or '\n')) index++;
                continue;
            }
            if (atTokenStart && c == '<' && index + 1 < step.Length && step[index + 1] == '#')
            {
                var depth = 1;
                index += 2;
                while (index < step.Length && depth > 0)
                {
                    if (index + 1 < step.Length && step[index] == '<' && step[index + 1] == '#') { depth++; index += 2; }
                    else if (index + 1 < step.Length && step[index] == '#' && step[index + 1] == '>') { depth--; index += 2; }
                    else index++;
                }
                if (depth != 0) return SyntaxError("A block comment is missing its terminator.");
                continue;
            }
            if (atTokenStart && c == '@' && index + 1 < step.Length && step[index + 1] is '\'' or '"')
            {
                var failure = PreflightHereString(step, ref index, out var qualified);
                if (failure is not null || !qualified) return failure;
                atStatementStart = false;
                atTokenStart = true; // Here-string footer ends a complete token.
                continue;
            }
            if (IsSingle(c) || IsDouble(c))
            {
                var failure = PreflightQuotedString(step, ref index, out var qualified);
                if (failure is not null || !qualified) return failure;
                atStatementStart = false;
                atTokenStart = false;
                continue;
            }
            if (c == '$')
            {
                index++;
                var failure = ReadDollarText(step, ref index, new StringBuilder());
                if (failure is not null) return failure.Error == "parse_error" ? failure : null;
                atStatementStart = false;
                atTokenStart = false;
                continue;
            }
            if ((c is '&' or '|') && index + 1 < step.Length && step[index + 1] == c)
                return SyntaxError("This statement separator is not valid in Windows PowerShell 5.1.");
            if (atTokenStart && c == '<')
                return SyntaxError("The input redirection operator is reserved.");
            if (c is '(' or '{')
            {
                if (groups.Count == 128) return null; // Explicit, fail-closed qualification bound.
                groups.Push(c);
                atStatementStart = atTokenStart = true;
                index++;
                continue;
            }
            if (c is ')' or '}')
            {
                if (groups.Count == 0 || groups.Pop() != (c == ')' ? '(' : '{'))
                    return SyntaxError("An unexpected closing delimiter was found.");
                atStatementStart = false;
                atTokenStart = true;
                index++;
                continue;
            }
            if (c is ';' or '|')
            {
                atStatementStart = atTokenStart = true;
                index++;
                continue;
            }
            if (atStatementStart && char.IsAsciiLetter(c))
            {
                var start = index;
                while (index < step.Length && (char.IsAsciiLetter(step[index]) || step[index] == '-')) index++;
                var keyword = step[start..index];
                var end = index;
                while (end < step.Length && char.IsWhiteSpace(step[end]) && step[end] is not ('\r' or '\n')) end++;
                if (IncompleteStatementKeywords.Contains(keyword) &&
                    (end == step.Length || step[end] is ';' or '\r' or '\n' or ')' or '}' || step[end] == '#'))
                    return SyntaxError("The statement is missing required syntax.");
                atStatementStart = atTokenStart = false;
                continue;
            }
            atStatementStart = atTokenStart = false;
            index++;
        }
        return groups.Count == 0 ? null : SyntaxError("An opening delimiter is missing its closing delimiter.");
    }

    // PS5 stop-parsing is triggered by the cooked marker token. The raw scan
    // tracks double-quote state only for pipeline boundaries; unmatched quotes
    // and backticks in its payload never become ordinary parser syntax.
    private static bool PreflightStopParsingMarker(string step, int start, out int end)
    {
        end = start;
        var cooked = new StringBuilder();
        while (end < step.Length && !char.IsWhiteSpace(step[end]) && !(end != start && step[end] == '\0'))
        {
            var c = step[end++];
            if (c is '$' or '(' or ')' or '{' or '}' or ';' or '|' or '&' or '<' or '>') return false;
            if (c == '`')
            {
                if (end == step.Length) return false;
                cooked.Append(Unescape(step[end++]));
            }
            else if (IsSingle(c) || IsDouble(c))
            {
                var single = IsSingle(c);
                var closed = false;
                while (end < step.Length)
                {
                    var quoted = step[end++];
                    if (single ? IsSingle(quoted) : IsDouble(quoted))
                    {
                        if (end < step.Length && (single ? IsSingle(step[end]) : IsDouble(step[end]))) { cooked.Append(step[end++]); continue; }
                        closed = true;
                        break;
                    }
                    if (!single && quoted == '$') return false;
                    if (!single && quoted == '`' && end < step.Length) quoted = Unescape(step[end++]);
                    cooked.Append(quoted);
                    if (cooked.Length > 3) return false;
                }
                if (!closed) return false;
            }
            else cooked.Append(c);
            if (cooked.Length > 3) return false;
        }
        return cooked.ToString() == "--%";
    }

    private static ParsedStep? PreflightQuotedString(string step, ref int index, out bool qualified)
    {
        qualified = true;
        var single = IsSingle(step[index++]);
        while (index < step.Length)
        {
            var c = step[index++];
            if (single ? IsSingle(c) : IsDouble(c))
            {
                if (index < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index]))) { index++; continue; }
                return null;
            }
            if (!single && c == '`' && index < step.Length) { index++; continue; }
            if (!single && c == '$')
            {
                var failure = ReadDollarText(step, ref index, new StringBuilder());
                if (failure is null) continue;
                qualified = failure.Error == "parse_error";
                return qualified ? failure : null;
            }
        }
        return SyntaxError("The string is missing its terminator.");
    }

    private static ParsedStep? PreflightHereString(string step, ref int index, out bool qualified)
    {
        qualified = true;
        var single = step[index + 1] == '\'';
        index += 2;
        while (index < step.Length && step[index] is ' ' or '\t') index++;
        if (index == step.Length || step[index] is not ('\r' or '\n'))
            return SyntaxError("A here-string header must end with a newline.");
        if (step[index++] == '\r' && index < step.Length && step[index] == '\n') index++;
        var lineStart = true;
        while (index < step.Length)
        {
            if (lineStart && index + 1 < step.Length && (single ? IsSingle(step[index]) : IsDouble(step[index])) && step[index + 1] == '@')
            { index += 2; return null; }
            lineStart = false;
            var c = step[index++];
            if (!single && c == '`' && index < step.Length) { index++; continue; }
            if (c is '\r' or '\n')
            {
                if (c == '\r' && index < step.Length && step[index] == '\n') index++;
                lineStart = true;
                continue;
            }
            if (!single && c == '$')
            {
                var failure = ReadDollarText(step, ref index, new StringBuilder());
                if (failure is null) continue;
                qualified = failure.Error == "parse_error";
                return qualified ? failure : null;
            }
        }
        return SyntaxError("The here-string is missing its column-zero terminator.");
    }

    // These are deliberately native candidate explanations, not invented claims
    // about exact localized PSParser messages. The raw diagnostic gate records
    // and compares original detail/message strings without normalization.
    private static ParsedStep SyntaxError(string detail) => Reject("parse_error", detail);
}
