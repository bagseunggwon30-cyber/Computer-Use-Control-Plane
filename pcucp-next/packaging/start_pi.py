"""Start Pi with the CUCP extension, optionally elevating the whole session via UAC."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def resolve_executable(value):
    executable = shutil.which(str(value))
    if not executable:
        raise ValueError('Executable not found: ' + str(value))
    return str(Path(executable).resolve())


def session_environment(root, python, native, inherited=None):
    environment = dict(os.environ if inherited is None else inherited)
    environment.update(CUCP_ROOT=str(root), CUCP_PYTHON=python, CUCP_NATIVE_HOST=str(native))
    return environment


def pi_command(pi, extension, environment):
    """Fixed argv; npm batch shims use single-pass environment substitution.

    Avoid CRT escaping a cmd /c tail, CALL's second expansion, and interpolation
    of paths containing %, !, & or spaces into command-language source.
    """
    if any(c in str(value) for value in (pi, extension) for c in ('"', '\0', '\r', '\n')):
        raise ValueError('Invalid executable or extension path')
    if Path(pi).suffix.casefold() in ('.cmd', '.bat'):
        environment['CUCP_PI_EXECUTABLE'] = str(pi)
        environment['CUCP_PI_EXTENSION'] = str(extension)
        comspec = environment.get('COMSPEC', str(Path(environment.get('SystemRoot', r'C:\Windows')) / 'System32/cmd.exe'))
        return '"' + comspec + '" /d /s /c ""%CUCP_PI_EXECUTABLE%" --extension "%CUCP_PI_EXTENSION%""'
    return [str(pi), '--extension', str(extension)]


def elevate(arguments, working_directory):
    """ShellExecuteExW owns one UAC-launched Python process and preserves its exit."""
    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
            ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
            ('dwHotKey', wintypes.DWORD), ('hIconOrMonitor', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    info = SHELLEXECUTEINFOW()
    info.cbSize, info.fMask, info.lpVerb = ctypes.sizeof(info), 0x40, 'runas'
    info.lpFile, info.lpParameters = sys.executable, subprocess.list2cmdline(arguments)
    info.lpDirectory, info.nShow = str(working_directory), 1  # The requested interactive Pi window.
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(info.hProcess, 0xffffffff) != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        kernel.CloseHandle(info.hProcess)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elevated', '-Elevated', action='store_true')
    parser.add_argument('--python-exe', '-PythonExe', default=sys.executable)
    parser.add_argument('--pi-executable', '-PiExecutable', default='pi')
    args = parser.parse_args(argv)
    if sys.platform != 'win32':
        parser.error('This launcher requires an interactive Windows desktop')
    try:
        native = ROOT / 'pcucp-next/bin/native/PcuCp.NativeHost.exe'
        extension = ROOT / 'integrations/pi/src/index.ts'
        if not native.is_file():
            raise ValueError('Publish the native host first: python pcucp-next/packaging/publish_native.py')
        if not extension.is_file():
            raise ValueError('CUCP Pi extension is missing')
        python, pi = resolve_executable(args.python_exe), resolve_executable(args.pi_executable)
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.IsUserAnAdmin.argtypes, shell.IsUserAnAdmin.restype = [], wintypes.BOOL
        admin = bool(shell.IsUserAnAdmin())
        if args.elevated and not admin:
            return elevate(['-X', 'utf8', str(Path(__file__).resolve()), '--python-exe', python, '--pi-executable', pi], Path.cwd())
        environment = session_environment(ROOT, python, native)
        if admin:
            print('Pi and its tools/extensions run as administrator. CUCP live control still starts off.', flush=True)
        return subprocess.run(pi_command(pi, extension, environment), env=environment, shell=False).returncode
    except (OSError, ValueError) as error:
        print('CUCP Pi launcher: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
