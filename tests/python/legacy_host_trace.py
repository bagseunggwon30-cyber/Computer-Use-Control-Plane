"""Fail-closed validator for bounded candidate-only Linux process traces.

Input is raw stderr from ``strace -f [-q] -e trace=process -s 4096`` without ``-v``
(environment expansion), timestamps, colors or summary mode. One ``-q`` may
suppress attach/personality notices; ``-qq`` would hide required exits. This module does
not run strace. Its fixtures are synthetic syntax examples, never observed CI
proof; unknown Linux/strace variants must fail qualification rather than be
silently ignored. The caller retains the original raw trace as an artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
from typing import Sequence

MAX_TRACE_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
_ROOT = "unprefixed-root"
_PROCESS_CALLS = frozenset(("clone", "clone3", "fork", "vfork", "wait4", "waitid",
                           "waitpid", "exit", "exit_group", "kill", "tkill", "tgkill"))
_FORBIDDEN_PROGRAMS = frozenset(("sh", "bash", "dash", "zsh", "ksh", "fish", "csh", "tcsh",
                               "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"))


class TraceValidationError(ValueError):
    """Missing, malformed, ambiguous or disallowed process-level evidence."""


def _require(condition, message):
    if not condition:
        raise TraceValidationError(message)


def _cstring(text, position):
    """Decode strace's byte-oriented C string quoting, never Python eval."""
    _require(position < len(text) and text[position] == '"', "Expected a complete quoted trace string")
    position += 1
    output = bytearray()
    escapes = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13,
               '\\': 92, '"': 34}
    while position < len(text):
        char = text[position]
        if char == '"':
            try:
                value = output.decode("utf-8", errors="strict")
            except UnicodeError as error:
                raise TraceValidationError("Trace string is not UTF-8") from error
            _require("\0" not in value, "NUL is not valid executable/argv evidence")
            return value, position + 1
        _require(ord(char) >= 32 and char != "\x7f", "Unescaped control character in trace string")
        if char != "\\":
            output.extend(char.encode("utf-8"))
            position += 1
            continue
        position += 1
        _require(position < len(text), "Incomplete trace string escape")
        char = text[position]
        if char in escapes:
            output.append(escapes[char])
            position += 1
        elif char in "01234567":
            matched = re.match(r"[0-7]{1,3}", text[position:])
            value = int(matched[0], 8)
            _require(value <= 255, "Invalid octal byte in trace string")
            output.append(value)
            position += len(matched[0])
        elif char == "x":
            matched = re.match(r"x([0-9a-fA-F]{2})", text[position:])
            _require(matched is not None, "Invalid hexadecimal trace escape")
            output.append(int(matched[1], 16))
            position += 3
        else:
            raise TraceValidationError("Unsupported trace string escape")
    raise TraceValidationError("Unterminated trace string")


def _outside_strings(text):
    result, position = [], 0
    while position < len(text):
        if text[position] == '"':
            _, position = _cstring(text, position)
            result.append('"string"')
        else:
            result.append(text[position])
            position += 1
    return "".join(result)


def _execve(text):
    """Only fully displayed argv plus opaque environment pointer are accepted."""
    position = len("execve(")
    executable, position = _cstring(text, position)

    def consume(token):
        nonlocal position
        while position < len(text) and text[position].isspace():
            position += 1
        _require(text.startswith(token, position), "Malformed execve syntax")
        position += len(token)

    consume(",")
    consume("[")
    argv = []
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if text.startswith("]", position):
            position += 1
            break
        arg, position = _cstring(text, position)
        argv.append(arg)
        while position < len(text) and text[position].isspace():
            position += 1
        if text.startswith("]", position):
            position += 1
            break
        consume(",")
        _require(not text.startswith("]", position), "Trailing execve argv comma")
    consume(",")
    remainder = text[position:].strip()
    _require(re.fullmatch(r"(?:0x[0-9a-fA-F]+(?: /\* [0-9]+ vars? \*/)?|NULL)\s*\)\s*=\s*0", remainder),
             "Execve must succeed with opaque environment and no abbreviation")
    _require(argv, "Execve argv cannot be empty")
    return executable, tuple(argv)


def _prefix(line):
    matched = re.match(r"^\[pid\s+([1-9][0-9]*)\]\s+(.*)$", line)
    if matched:
        return int(matched[1]), matched[2]
    matched = re.match(r"^([1-9][0-9]*)\s+(.*)$", line)
    if matched:
        return int(matched[1]), matched[2]
    _require(not line.startswith(("[", " ", "\t")), "Unsupported trace line prefix")
    return _ROOT, line


def _expected(mode, python, dotnet, dll, argv):
    _require(mode in ("root", "typed-child", "daemon"), "Unknown qualification mode")
    for name, path in (("Python", python), ("dotnet", dotnet), ("DLL", dll)):
        _require(type(path) is str and PurePosixPath(path).is_absolute() and "\0" not in path,
                 name + " must be an explicit absolute path")
        _require(PurePosixPath(path).name.lower() not in _FORBIDDEN_PROGRAMS, "Shell/PowerShell executable is prohibited")
    _require(PurePosixPath(dotnet).name == "dotnet" and dll.endswith(".dll"), "Expected the fixed Linux dotnet/DLL boundary")
    _require(isinstance(argv, (list, tuple)) and all(type(arg) is str and "\0" not in arg for arg in argv),
             "Expected root argv must be a complete string array")
    argv = tuple(argv)
    _require(argv[:3] == (python, "-m", "pcucp_cli.legacy_host_entry"), "Expected the exact Python staged module entry")
    tail = argv[3:]
    separator = tail.index("--") if "--" in tail else len(tail)
    options, legacy = tail[:separator], tail[separator + 1:]
    switches = {"--staged-brief-host", "--brief", "--quiet", "--typed-child"}
    valued = {"--changelog", "--cdp-endpoint", "--timeout-s", "--culture"}
    seen, position = set(), 0
    while position < len(options):
        option = options[position]
        _require(option in switches | valued and option not in seen, "Unsupported or duplicate expected root option")
        seen.add(option)
        position += 1
        if option in valued:
            _require(position < len(options), "Missing expected root option value")
            position += 1
    _require({"--staged-brief-host", "--brief"} <= seen, "Expected the opt-in brief checkpoint")
    if mode == "typed-child":
        _require("--typed-child" in seen and not legacy, "Typed child must use stdin, not legacy argv")
    else:
        _require("--typed-child" not in seen, "Root/daemon cannot use typed-child startup")
        if mode == "root":
            _require(legacy == ("macro", "release-notes"), "Trace root must exercise the read-only release-notes slice")
        else:
            _require(legacy == ("macro", "daemon", "serve", "--max-commands", "1"),
                     "Trace daemon must bound itself to exactly one requested coordinator")
    return argv


@dataclass(frozen=True)
class _Execution:
    pid: int | str
    executable: str
    argv: tuple[str, ...]


def validate_trace(raw: bytes | str, *, expected_python: str, expected_dotnet: str,
                   expected_dll: str, mode: str, expected_root_argv: Sequence[str]) -> dict:
    """Return inspectable evidence only when every raw line has been accounted for.

    No-prefix lines represent the root. Child execs need explicit PID evidence;
    an all-unprefixed two-exec transcript cannot establish separate ownership.
    Only exact same-PID unfinished/resumed calls are joined, except the standard
    transition from an unprefixed root to its first explicit root PID.
    """
    wanted = _expected(mode, expected_python, expected_dotnet, expected_dll, expected_root_argv)
    _require(type(raw) in (bytes, str), "Trace must be raw bytes or text")
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise TraceValidationError("Invalid trace encoding") from error
    _require(0 < len(raw) <= MAX_TRACE_BYTES, "Trace is empty or exceeds the bounded capture")
    _require(raw.endswith(b"\n"), "Trace is truncated: missing final newline")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise TraceValidationError("Trace is not strict UTF-8") from error
    _require("\0" not in text and "\ufeff" not in text and "\r" not in text, "Unsupported trace control/encoding marker")
    executions, creations, exits, exit_lines, signals = [], [], {}, {}, []
    attached, observed, pending, syscall_counts = set(), set(), {}, {}
    root_alias = None
    resumed_count = 0

    def normalize(pid):
        return _ROOT if pid == root_alias else pid

    for number, line in enumerate(text.splitlines(), 1):
        _require(line and len(line.encode("utf-8")) <= MAX_LINE_BYTES, f"Empty or oversized trace line {number}")
        _require("Operation not permitted" not in line and not re.search(r"\bEPERM\b", _outside_strings(line)),
                 "Trace collection or traced operation was denied")
        notice = re.fullmatch(r"strace: Process ([1-9][0-9]*) attached", line)
        if notice:
            _require(int(notice[1]) not in attached, "Repeated attachment evidence")
            attached.add(int(notice[1]))
            continue
        _require(not line.startswith("strace:"), "Unsupported strace diagnostic or incomplete collection")
        pid, body = _prefix(line)
        pid = normalize(pid)
        observed.add(pid)
        exit_match = re.fullmatch(r"\+\+\+ exited with ([0-9]+) \+\+\+", body)
        if exit_match:
            _require(exit_match[1] == "0" and pid not in exits, "Tracee failed or has duplicate exit evidence")
            exits[pid] = 0
            exit_lines[pid] = number
            continue
        _require(not body.startswith("+++"), "Missing successful tracee exit evidence")
        _require(pid not in exits, "Activity appears after tracee exit")
        if re.fullmatch(r"--- SIG[A-Z0-9_]+ \{[^\n]*\} ---", body):
            _require("..." not in _outside_strings(body), "Abbreviated signal evidence")
            continue
        resumed = re.fullmatch(r"<\.\.\. ([a-z0-9_]+) resumed>(.*)", body)
        if resumed:
            if pid not in pending and root_alias is None and _ROOT in pending and pid != _ROOT:
                # A root vfork may become prefixed after its child is attached.
                _require(pid not in attached and pending[_ROOT][0] == resumed[1], "Ambiguous resumed caller")
                root_alias = pid
                observed.discard(pid)
                pid = _ROOT
            _require(pid in pending and pending[pid][0] == resumed[1], "Orphaned or mismatched resumed syscall")
            _, before = pending.pop(pid)
            body = before + resumed[2]
            resumed_count += 1
        else:
            _require(pid not in pending, "Caller emitted a new syscall before its unfinished call resumed")
        if body.endswith("<unfinished ...>"):
            match = re.match(r"^([a-z0-9_]+)\(", body)
            _require(match is not None and match[1] in _PROCESS_CALLS | {"execve"}, "Unsupported unfinished syscall")
            pending[pid] = (match[1], body[:-len("<unfinished ...>")])
            continue
        outside = _outside_strings(body)
        _require("..." not in outside and "<unfinished" not in outside and "resumed>" not in outside,
                 "Abbreviated or malformed trace evidence")
        match = re.fullmatch(r"([a-z0-9_]+)\((.*)\)\s*=\s*(.+)", body)
        _require(match is not None, f"Unsupported trace syntax at line {number}")
        name, arguments, result = match.groups()
        _require(name != "execveat", "execveat is not an accepted execution boundary")
        _require(name in _PROCESS_CALLS | {"execve"}, "Unexpected process-trace syscall: " + name)
        syscall_counts[name] = syscall_counts.get(name, 0) + 1
        if name == "execve":
            executable, argv = _execve(body)
            _require(PurePosixPath(executable).name.lower() not in _FORBIDDEN_PROGRAMS, "Shell/PowerShell execution detected")
            executions.append(_Execution(pid, executable, argv))
            _require(len(executions) <= 2, "Unexpected extra executable")
        elif name in ("clone", "clone3", "fork", "vfork"):
            is_thread = False
            if name in ("clone", "clone3"):
                flags = re.search(r"\bflags=([A-Za-z0-9_|]+)(?=\s*[,}]|$)", _outside_strings(arguments))
                _require(flags is not None, "Clone flags are not fully visible")
                tokens = flags[1].split("|")
                numeric = [int(token, 0) for token in tokens if re.fullmatch(r"0x[0-9a-fA-F]+|0|[1-9][0-9]*", token)]
                # Linux UAPI sched.h: CLONE_UNTRACED=0x00800000 and
                # CLONE_THREAD=0x00010000. Reject hidden children even when
                # the same request looks like an otherwise allowed thread.
                _require("CLONE_UNTRACED" not in tokens and not any(value & 0x00800000 for value in numeric),
                         "CLONE_UNTRACED could evade process evidence")
                is_thread = "CLONE_THREAD" in tokens or any(value & 0x00010000 for value in numeric)
            if re.fullmatch(r"[1-9][0-9]*", result):
                creations.append((pid, int(result), is_thread))
            else:
                _require(re.fullmatch(r"-1 (?:ENOSYS|EAGAIN|ENOMEM) \([^\n]+\)", result), "Unsupported process creation outcome")
        elif name in ("exit", "exit_group"):
            _require(arguments == "0" and result == "?", "Tracee requested an unsuccessful exit")
        else:
            _require(re.fullmatch(r"(?:[0-9]+|-1 [A-Z0-9_]+ \([^\n]+\)|\? ERESTARTSYS \([^\n]+\))", result),
                     "Unsupported process-control result")
            if name in ("kill", "tkill", "tgkill"):
                pattern = r"(-?[1-9][0-9]*),\s*(SIG[A-Z0-9_]+|0)" if name == "kill" else (
                    r"([1-9][0-9]*),\s*(SIG[A-Z0-9_]+|0)" if name == "tkill" else
                    r"([1-9][0-9]*),\s*([1-9][0-9]*),\s*(SIG[A-Z0-9_]+|0)")
                target = re.fullmatch(pattern, arguments)
                _require(target is not None, "Unsupported or broad signal target")
                signals.append((name, tuple(int(value) for value in target.groups()[:-1])))
    _require(not pending, "Unfinished syscall lacks completion evidence")
    _require(len(executions) == 2, "Exactly two successful execve events are required")
    root, worker = executions
    if root.pid != _ROOT:
        _require(root_alias is None or root_alias == root.pid, "Conflicting root PID evidence")
        root_alias = root.pid
    # Prefixes may first expose the root PID after the initial unprefixed exec.
    created_children = [child for _, child, _ in creations]
    _require(len(created_children) == len(set(created_children)), "Repeated tracee PID creation is ambiguous")
    children = set(created_children)
    _require(attached <= children, "Attached tracee lacks process/thread creation evidence")
    candidates = {pid for pid in observed if type(pid) is int and pid not in children}
    if root_alias is None and candidates:
        _require(len(candidates) == 1, "Ambiguous unprefixed root PID")
        root_alias = candidates.pop()
    norm = lambda pid: _ROOT if pid == root_alias else pid
    root_pid, worker_pid = norm(root.pid), norm(worker.pid)
    _require(root_pid == _ROOT and type(worker_pid) is int and root_pid != worker_pid,
             "Separate root/worker PID ownership is missing")
    _require(root.executable == expected_python and root.argv == wanted, "Root executable or complete argv differs from expectation")
    _require(worker.executable == expected_dotnet and worker.argv ==
             (expected_dotnet, expected_dll, "legacy-diagnostic-session"), "Coordinator executable/DLL/entry or argv changed")
    process_creations = [(norm(parent), child) for parent, child, thread in creations if not thread]
    _require(process_creations == [(_ROOT, worker_pid)], "Expected exactly one owned root-to-coordinator process creation")
    normalized_exits, normalized_exit_lines = {}, {}
    for pid, code in exits.items():
        key = norm(pid)
        _require(key not in normalized_exits, "Conflicting root exit evidence")
        normalized_exits[key] = code
        normalized_exit_lines[key] = exit_lines[pid]
    needed = {norm(pid) for pid in observed} | children | {_ROOT, worker_pid}
    _require(needed == set(normalized_exits), "Missing tracee exit evidence")
    _require({norm(pid) for pid in observed} <= children | {_ROOT}, "Unowned tracee activity")
    _require(normalized_exit_lines[worker_pid] < normalized_exit_lines[_ROOT], "Root exited before its coordinator")
    _require(all(norm(parent) in needed and child in needed for parent, child, _ in creations), "Unowned process creation evidence")
    # Reconstruct only the observed root/worker thread groups; wire syntax
    # cannot legitimize signaling an unrelated process or a broad process set.
    groups = {_ROOT: _ROOT, worker_pid: worker_pid}
    unresolved = [(norm(parent), child) for parent, child, thread in creations if thread]
    while unresolved:
        resolved = [(parent, child) for parent, child in unresolved if parent in groups]
        _require(resolved, "Thread creation lacks an owned parent group")
        for parent, child in resolved:
            _require(child not in groups, "Conflicting thread/process group evidence")
            groups[child] = groups[parent]
            unresolved.remove((parent, child))
    owned_numbers = children | ({root_alias} if root_alias is not None else set())
    for name, targets in signals:
        if name == "kill":
            target = targets[0]
            _require(target in owned_numbers or target == -worker_pid and target != -1,
                     "kill target is outside the owned root/worker group")
        elif name == "tkill":
            _require(targets[0] in owned_numbers, "tkill target is outside owned tracees")
        else:
            group, thread = targets
            _require(group in owned_numbers and thread in owned_numbers and
                     groups.get(norm(thread)) == norm(group), "tgkill target/group is outside owned tracees")
    return dict(schema="cucp.legacy-host-process-trace/v1", mode=mode,
                trace_sha256=hashlib.sha256(raw).hexdigest(), trace_bytes=len(raw), trace_lines=len(text.splitlines()),
                successful_execve_count=2, failed_execve_count=0, execveat_count=0,
                process_spawn_count=1, thread_spawn_count=sum(thread for _, _, thread in creations),
                attached_pid_count=len(attached), successful_exit_count=len(normalized_exits),
                resumed_syscall_count=resumed_count, owned_signal_call_count=len(signals), syscall_counts=syscall_counts,
                root_pid=root_alias, worker_pid=worker_pid,
                executions=[dict(role="root", executable=root.executable, argv=list(root.argv), exit_code=0),
                            dict(role="coordinator", executable=worker.executable, argv=list(worker.argv), exit_code=0)])
