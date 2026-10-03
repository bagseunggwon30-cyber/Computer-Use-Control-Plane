"""Synthetic strace syntax/adversarial fixtures, not observed Linux CI evidence.

No strace execution, service, network access, downloaded fixture or user file.
Accepted examples cover documented flags plus conservative common line syntax;
actual CI output must independently pass the validator without format fallback.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legacy_host_trace import MAX_LINE_BYTES, MAX_TRACE_BYTES, TraceValidationError, validate_trace

PYTHON = "/owned/Python/bin/python3"
DOTNET = "/owned/dotnet/dotnet"
DLL = "/owned/source/fixture.dll"


def quoted(value):
    """Synthetic strace-style C bytes; JSON escapes are intentionally not used."""
    result = '"'
    for byte in value.encode("utf-8"):
        if byte in (34, 92):
            result += "\\" + chr(byte)
        elif 32 <= byte <= 126:
            result += chr(byte)
        else:
            result += "\\%03o" % byte
    return result + '"'


def root_argv(mode="root", changelog="/owned/CHANGELOG.md"):
    common = [PYTHON, "-m", "pcucp_cli.legacy_host_entry", "--staged-brief-host", "--brief", "--changelog", changelog]
    return common + ({"root": ["--", "macro", "release-notes"], "typed-child": ["--typed-child"],
                      "daemon": ["--", "macro", "daemon", "serve", "--max-commands", "1"]}[mode])


def execution(executable, argv):
    return "execve(" + quoted(executable) + ", [" + ", ".join(quoted(arg) for arg in argv) + "], 0x7ffd123abc /* 45 vars */) = 0"


def fixture(mode="root", *, style="bracket", changelog="/owned/CHANGELOG.md"):
    """A synthetic Python root, fixed DLL worker and two ordinary native threads."""
    def prefix(pid):
        if style == "numeric":
            return str(pid) + "  "
        if style == "mixed-root" and pid == 100:
            return ""
        return "[pid %5d] " % pid
    return "\n".join([
        prefix(100) + execution(PYTHON, root_argv(mode, changelog)),
        prefix(100) + "vfork( <unfinished ...>",
        "strace: Process 101 attached",
        prefix(101) + execution(DOTNET, [DOTNET, DLL, "legacy-diagnostic-session"]),
        prefix(100) + "<... vfork resumed>) = 101",
        prefix(100) + "clone3({flags=CLONE_VM|CLONE_THREAD, exit_signal=0}, 88) = -1 ENOSYS (Function not implemented)",
        prefix(100) + "clone(child_stack=NULL, flags=CLONE_VM|CLONE_THREAD|CLONE_SIGHAND) = 102",
        "strace: Process 102 attached",
        prefix(101) + "clone3({flags=CLONE_VM|CLONE_THREAD|CLONE_SIGHAND, exit_signal=0}, 88) = 103",
        "strace: Process 103 attached",
        prefix(103) + "exit(0) = ?",
        prefix(103) + "+++ exited with 0 +++",
        prefix(101) + "exit_group(0) = ?",
        prefix(101) + "+++ exited with 0 +++",
        prefix(100) + "--- SIGCHLD {si_signo=SIGCHLD, si_code=CLD_EXITED, si_pid=101, si_status=0} ---",
        prefix(100) + "wait4(101, [{WIFEXITED(s) && WEXITSTATUS(s) == 0}], 0, NULL) = 101",
        prefix(102) + "exit(0) = ?",
        prefix(102) + "+++ exited with 0 +++",
        prefix(100) + "exit_group(0) = ?",
        prefix(100) + "+++ exited with 0 +++",
    ]) + "\n"


def check(raw, mode="root", **kwargs):
    return validate_trace(raw, expected_python=PYTHON, expected_dotnet=DOTNET, expected_dll=DLL,
                          mode=mode, expected_root_argv=kwargs.pop("expected_root_argv", root_argv(mode)), **kwargs)


class TraceParserTests(unittest.TestCase):
    def test_synthetic_modes_and_supported_prefixes(self):
        for mode in ("root", "typed-child", "daemon"):
            for style in ("bracket", "numeric", "mixed-root"):
                with self.subTest(mode=mode, style=style):
                    raw = fixture(mode, style=style)
                    evidence = check(raw, mode)
                    self.assertEqual(evidence["successful_execve_count"], 2)
                    self.assertEqual(evidence["failed_execve_count"], 0)
                    self.assertEqual(evidence["execveat_count"], 0)
                    self.assertEqual(evidence["process_spawn_count"], 1)
                    self.assertEqual(evidence["thread_spawn_count"], 2)
                    self.assertEqual(evidence["successful_exit_count"], 4)
                    self.assertEqual(evidence["worker_pid"], 101)
                    self.assertEqual(evidence["mode"], mode)
                    self.assertEqual(evidence["trace_sha256"], hashlib.sha256(raw.encode()).hexdigest())
                    self.assertEqual(evidence["trace_bytes"], len(raw.encode()))
                    json.dumps(evidence)
                    # A single -q suppresses attach/personality notices, not
                    # syscalls or exits. Creation evidence still owns each PID.
                    quiet = re.sub(r"^strace: Process [0-9]+ attached\n", "", raw, flags=re.M)
                    quiet_evidence = check(quiet, mode)
                    self.assertEqual(quiet_evidence["attached_pid_count"], 0)
                    self.assertEqual(quiet_evidence["process_spawn_count"], 1)
                    self.assertEqual(quiet_evidence["successful_exit_count"], 4)

    def test_unprefixed_root_vfork_resumes_with_new_root_prefix(self):
        raw = fixture(style="mixed-root")
        raw = raw.replace("<... vfork resumed>", "[pid 100] <... vfork resumed>")
        evidence = check(raw)
        self.assertEqual(evidence["root_pid"], 100)
        self.assertEqual(evidence["resumed_syscall_count"], 1)

    def test_initial_unprefixed_root_but_later_root_prefix_is_bound(self):
        raw = fixture(style="numeric")
        raw = raw.replace("100  execve", "execve", 1)
        self.assertEqual(check(raw)["root_pid"], 100)

    def test_unprefixed_final_root_exit_binds_numeric_initial_root(self):
        raw = fixture(style="numeric").replace("100  +++ exited with 0 +++", "+++ exited with 0 +++")
        self.assertEqual(check(raw)["root_pid"], 100)

    def test_exact_interrupted_resumed_execve_is_reassembled(self):
        call = execution(DOTNET, [DOTNET, DLL, "legacy-diagnostic-session"])
        fragment = call[:-len(") = 0")] + " <unfinished ...>\n[pid 101] <... execve resumed>) = 0"
        evidence = check(fixture().replace(call, fragment))
        self.assertEqual(evidence["resumed_syscall_count"], 2)
        self.assertEqual(evidence["successful_execve_count"], 2)

    def test_c_escaped_unicode_quote_slash_and_control_argv_round_trip(self):
        path = '/owned/한글 "quoted" \\ tab\tline\nCHANGELOG.md'
        evidence = check(fixture(changelog=path), expected_root_argv=root_argv(changelog=path))
        self.assertEqual(evidence["executions"][0]["argv"], root_argv(changelog=path))
        self.assertNotIn("environment", evidence)
        self.assertNotIn("45 vars", json.dumps(evidence))

    def test_literal_ellipsis_inside_quoted_path_is_not_truncation(self):
        path = "/owned/.../CHANGELOG.md"
        check(fixture(changelog=path), expected_root_argv=root_argv(changelog=path))

    def test_fork_and_process_clone_forms_are_owned_process_creation(self):
        for call in ("fork()", "clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|SIGCHLD)",
                     "clone3({flags=CLONE_VM|CLONE_VFORK, exit_signal=SIGCHLD}, 88)"):
            raw = fixture().replace("vfork( <unfinished ...>", call + " = 101")
            raw = raw.replace("[pid   100] <... vfork resumed>) = 101\n", "")
            with self.subTest(call=call):
                self.assertEqual(check(raw)["process_spawn_count"], 1)

    def test_opaque_environment_pointer_and_null_forms(self):
        for value in ("NULL", "0x123abc", "0x123abc /* 1 var */", "0x123abc /* 0 vars */"):
            with self.subTest(value=value):
                check(fixture().replace("0x7ffd123abc /* 45 vars */", value))

    def test_runtime_signal_names_and_wait_restart_are_supported(self):
        insertion = "[pid 101] --- SIGRT_6 {si_signo=SIGRT_6, si_code=SI_TKILL, si_pid=101} ---\n"
        check(fixture().replace("[pid   101] exit_group", insertion + "[pid   101] exit_group"))
        raw = fixture().replace("[pid   100] wait4(101,", "[pid 100] wait4(101, 0x1234, 0, NULL) = ? ERESTARTSYS (To be restarted if SA_RESTART is set)\n[pid   100] wait4(101,")
        check(raw)

    def test_repeated_attachment_and_pid_reuse_fail_closed(self):
        for raw in (fixture().replace("strace: Process 102 attached", "strace: Process 102 attached\nstrace: Process 102 attached"),
                    fixture().replace("[pid   101] exit_group", "[pid 100] clone(child_stack=NULL, flags=CLONE_VM|CLONE_THREAD) = 102\n[pid   101] exit_group")):
            with self.subTest(raw=raw), self.assertRaises(TraceValidationError):
                check(raw)

    def test_bytes_and_text_have_identical_evidence(self):
        raw = fixture()
        self.assertEqual(check(raw), check(raw.encode()))

    def test_no_prefix_worker_exec_cannot_prove_separate_ownership(self):
        raw = fixture(style="mixed-root").replace("[pid   101] execve", "execve")
        with self.assertRaises(TraceValidationError):
            check(raw)

    def test_root_cannot_exec_replace_itself_instead_of_spawning_worker(self):
        raw = fixture().replace("[pid   101] execve", "[pid   100] execve")
        with self.assertRaises(TraceValidationError):
            check(raw)

    def test_empty_truncated_or_oversized_capture_is_not_evidence(self):
        for raw in (b"", "\n", fixture()[:-1], "x" * (MAX_TRACE_BYTES + 1),
                    "x" * (MAX_LINE_BYTES + 1) + "\n"):
            with self.subTest(length=len(raw)), self.assertRaises(TraceValidationError):
                check(raw)

    def test_collection_denial_diagnostics_and_detach_fail(self):
        for extra in ("strace: ptrace(PTRACE_TRACEME, ...): Operation not permitted",
                      "strace: Process 101 detached", "strace: invalid system call 'process'",
                      "strace: attach: ptrace(PTRACE_SEIZE, 101): EPERM", "arbitrary application stderr"):
            with self.subTest(extra=extra), self.assertRaises(TraceValidationError):
                check(fixture() + extra + "\n")

    def test_reject_failed_or_unexpected_execve_and_execveat(self):
        child_call = execution(DOTNET, [DOTNET, DLL, "legacy-diagnostic-session"])
        mutations = [child_call.replace(" = 0", " = -1 ENOENT (No such file or directory)"),
                     child_call.replace("execve(", "execveat(AT_FDCWD, "),
                     execution("/bin/sh", ["/bin/sh", "-c", "dotnet host.dll"]),
                     execution("/owned/powershell.exe", ["/owned/powershell.exe", "anything"]),
                     execution("/owned/pwsh", ["/owned/pwsh"]),
                     execution("/other/dotnet", ["/other/dotnet", DLL, "legacy-diagnostic-session"]),
                     execution(DOTNET, [DOTNET, "/other/host.dll", "legacy-diagnostic-session"]),
                     execution(DOTNET, [DOTNET, DLL, "legacy-execution-session"]),
                     execution(DOTNET, [DOTNET, DLL, "legacy-diagnostic-session", "--allow-live-control"])]
        for replacement in mutations:
            with self.subTest(replacement=replacement), self.assertRaises(TraceValidationError):
                check(fixture().replace(child_call, replacement))
        with self.assertRaisesRegex(TraceValidationError, "extra executable"):
            check(fixture().replace("[pid   101] exit_group", "[pid 101] " + child_call + "\n[pid   101] exit_group"))

    def test_every_root_argument_and_executable_must_match(self):
        original = execution(PYTHON, root_argv())
        alternatives = [execution("/other/python", root_argv()), execution(PYTHON, root_argv()[:-1]),
                        execution(PYTHON, [*root_argv(), "--version", "3.0.0"]),
                        execution(PYTHON, ["spoofed-argv0", *root_argv()[1:]])]
        for other in alternatives:
            with self.subTest(other=other), self.assertRaises(TraceValidationError):
                check(fixture().replace(original, other))

    def test_reject_argv_abbreviation_and_environment_expansion(self):
        original = execution(DOTNET, [DOTNET, DLL, "legacy-diagnostic-session"])
        for other in (original.replace('"legacy-diagnostic-session"', '"legacy-diagnostic"...'),
                      original.replace('"legacy-diagnostic-session"', '...'),
                      original.replace('0x7ffd123abc /* 45 vars */', '["SECRET=value"]'),
                      original.replace('0x7ffd123abc /* 45 vars */', '[/* 45 vars */]'),
                      original.replace('"legacy-diagnostic-session"', '"legacy-diagnostic-session",')):
            with self.subTest(other=other), self.assertRaises(TraceValidationError):
                check(fixture().replace(original, other))

    def test_wrong_order_missing_and_failed_exit_evidence_rejected(self):
        original = fixture()
        failures = [original.replace("[pid   101] +++ exited with 0 +++\n", ""),
                    original.replace("[pid   103] +++ exited with 0 +++\n", ""),
                    original.replace("[pid   100] +++ exited with 0 +++\n", ""),
                    original.replace("[pid   101] +++ exited with 0 +++", "[pid   101] +++ exited with 1 +++"),
                    original.replace("[pid   101] +++ exited with 0 +++", "[pid   101] +++ killed by SIGKILL +++"),
                    original.replace("[pid   101] exit_group(0)", "[pid   101] exit_group(2)"),
                    original.replace("[pid   100] +++ exited with 0 +++\n", "") + "[pid 100] +++ exited with 0 +++\n[pid 100] exit_group(0) = ?\n"]
        for raw in failures:
            with self.subTest(raw=raw), self.assertRaises(TraceValidationError):
                check(raw)
        rows = original.splitlines()
        a = rows.index("[pid   100] +++ exited with 0 +++")
        b = rows.index("[pid   101] +++ exited with 0 +++")
        rows[a], rows[b] = rows[b], rows[a]
        with self.assertRaises(TraceValidationError):
            check("\n".join(rows) + "\n")

    def test_unknown_or_incomplete_interrupted_calls_fail(self):
        for raw in (fixture().replace("<... vfork resumed>", "<... execve resumed>"),
                    fixture().replace("[pid   100] <... vfork resumed>) = 101\n", ""),
                    fixture().replace("[pid   100] vfork( <unfinished ...>\n", ""),
                    fixture().replace("[pid   100] <... vfork resumed>", "[pid 999] <... vfork resumed>"),
                    fixture().replace("[pid   100] vfork(", "[pid   100] execveat(")):
            with self.subTest(raw=raw), self.assertRaises(TraceValidationError):
                check(raw)

    def test_missing_or_extra_process_spawn_is_not_valid_worker_ownership(self):
        for raw in (fixture().replace(") = 101", ") = 999", 1),
                    fixture().replace("[pid   100] vfork( <unfinished ...>", "[pid   103] vfork( <unfinished ...>")
                             .replace("[pid   100] <... vfork resumed>", "[pid   103] <... vfork resumed>"),
                    fixture().replace("[pid   101] exit_group", "[pid 100] fork() = 104\n[pid 104] +++ exited with 0 +++\n[pid   101] exit_group"),
                    fixture().replace("[pid   101] exit_group", "strace: Process 104 attached\n[pid 104] +++ exited with 0 +++\n[pid   101] exit_group")):
            with self.subTest(raw=raw), self.assertRaises(TraceValidationError):
                check(raw)

    def test_malformed_escaping_control_characters_and_prefixes_fail(self):
        for raw in (fixture().replace("fixture.dll", r"fixture\ud800.dll"),
                    fixture().replace("fixture.dll", r"fixture\xZZ.dll"),
                    fixture().replace("fixture.dll", r"fixture\400.dll"),
                    fixture().replace("fixture.dll", r"fixture\000.dll"),
                    fixture().replace("fixture.dll", r"fixture\377.dll"),
                    fixture().replace("[pid   101] execve", "12:34:56 [pid 101] execve"),
                    fixture().replace("[pid   101] execve", "[pid 0] execve"),
                    "\ufeff" + fixture(), fixture().replace("\n", "\r\n"), fixture().encode() + b"\xff\n"):
            with self.subTest(raw=raw), self.assertRaises(TraceValidationError):
                check(raw)

    def test_untraced_clone_flag_is_rejected_even_with_thread_flag(self):
        for flags in ("CLONE_VM|CLONE_THREAD|CLONE_UNTRACED", "CLONE_THREAD|0x00800000", "0x00810000"):
            raw = fixture().replace("CLONE_VM|CLONE_THREAD|CLONE_SIGHAND", flags)
            with self.subTest(flags=flags), self.assertRaisesRegex(TraceValidationError, "CLONE_UNTRACED"):
                check(raw)

    def test_normal_owned_group_cleanup_esrch_and_thread_signals_are_accepted(self):
        calls = ["kill(-101, SIGKILL) = -1 ESRCH (No such process)",
                 "kill(101, 0) = -1 ESRCH (No such process)",
                 "tkill(102, SIGRT_6) = 0", "tgkill(101, 103, SIGRT_6) = 0",
                 "tgkill(100, 102, SIGRT_6) = 0"]
        for call in calls:
            raw = fixture().replace("[pid   100] exit_group", "[pid 100] " + call + "\n[pid   100] exit_group")
            with self.subTest(call=call):
                self.assertEqual(check(raw)["owned_signal_call_count"], 1)

    def test_unowned_and_broad_signal_targets_are_rejected(self):
        calls = ["kill(-1, SIGKILL) = 0", "kill(0, SIGKILL) = 0", "kill(-100, SIGKILL) = 0",
                 "kill(999, SIGKILL) = -1 ESRCH (No such process)",
                 "tkill(999, SIGTERM) = 0", "tgkill(101, 999, SIGRT_6) = 0",
                 "tgkill(999, 103, SIGRT_6) = 0", "tgkill(100, 103, SIGRT_6) = 0"]
        for call in calls:
            raw = fixture().replace("[pid   100] exit_group", "[pid 100] " + call + "\n[pid   100] exit_group")
            with self.subTest(call=call), self.assertRaises(TraceValidationError):
                check(raw)

    def test_expected_configuration_is_itself_a_closed_read_only_contract(self):
        for kwargs in ({"mode": "anything"}, {"expected_python": "python"},
                       {"expected_dotnet": "/bin/sh"}, {"expected_dll": "/owned/file.ps1"},
                       {"expected_root_argv": [PYTHON, "-c", "import os"]},
                       {"expected_root_argv": [*root_argv()[:3], "--allow-live-control", *root_argv()[3:]]},
                       {"expected_root_argv": root_argv("typed-child")},
                       {"expected_root_argv": root_argv("daemon")},
                       {"expected_root_argv": [*root_argv()[:3], "--brief", *root_argv()[3:]]}):
            arguments = dict(expected_python=PYTHON, expected_dotnet=DOTNET, expected_dll=DLL,
                             mode="root", expected_root_argv=root_argv())
            arguments.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(TraceValidationError):
                validate_trace(fixture(), **arguments)


if __name__ == "__main__":
    unittest.main()
