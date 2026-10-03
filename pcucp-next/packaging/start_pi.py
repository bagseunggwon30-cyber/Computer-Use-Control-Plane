"""Start the optional Pi host with the Python/C# core. UAC requires --elevated."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def executable(value):
    selected = shutil.which(str(value))
    if not selected or not Path(selected).is_file():
        raise ValueError(f'Executable not found: {value}')
    path = Path(selected).resolve()
    if path.suffix.lower() in {'.ps1', '.cmd', '.bat'}:
        raise ValueError('Select a native executable, not a shell wrapper')
    return path


def pi_command(value, *, node_exe='node'):
    selected = shutil.which(str(value))
    if not selected or not Path(selected).is_file():
        raise ValueError(f'Pi executable not found: {value}')
    shim = Path(selected).resolve()
    if shim.suffix.lower() not in {'.cmd', '.bat', '.ps1'}:
        return [str(executable(shim))]
    # npm's Windows shims are not executed or parsed as code. Resolve the Pi
    # package's declared JS entry and pass it directly to the selected Node.
    for name in ('@earendil-works/pi-coding-agent', '@mariozechner/pi-coding-agent'):
        package = shim.parent / 'node_modules' / name
        manifest = package / 'package.json'
        if not manifest.is_file():
            continue
        with manifest.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Pi package manifest exceeds 64 KiB')
        data = json.loads(raw.decode('utf-8-sig'))
        declared = data.get('bin') if isinstance(data, dict) else None
        entry = declared.get('pi') if isinstance(declared, dict) else declared
        if not isinstance(entry, str) or '\0' in entry:
            raise ValueError('Pi package has no declared pi entrypoint')
        target = (package / entry).resolve()
        if not target.is_relative_to(package.resolve()) or target.suffix.lower() not in {'.js', '.mjs', '.cjs'} or not target.is_file():
            raise ValueError('Pi entrypoint must be an existing JS file inside its package')
        return [str(executable(node_exe)), str(target)]
    raise ValueError('Pi npm package not found beside its shim; select its native executable or reinstall Pi')


def prepare(root, python_exe, pi_exe, node_exe='node'):
    root = Path(root).resolve()
    native = root / 'pcucp-next/bin/native/PcuCp.NativeHost.exe'
    extension = root / 'integrations/pi/src/index.ts'
    if not native.is_file() or not extension.is_file():
        raise ValueError('Publish the native host first: python pcucp-next/packaging/publish_native.py')
    python = executable(python_exe)
    command = [*pi_command(pi_exe, node_exe=node_exe), '--extension', str(extension)]
    env = dict(os.environ, CUCP_ROOT=str(root), CUCP_PYTHON=str(python), CUCP_NATIVE_HOST=str(native))
    env.pop('CUCP_EXECUTABLE', None)
    return command, env


def is_admin():
    return bool(ctypes.WinDLL('shell32', use_last_error=True).IsUserAnAdmin())


def elevate(command, cwd):
    """Own and wait on the single UAC-created Python process; return its exit."""
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    info = ExecuteInfo(cbSize=ctypes.sizeof(ExecuteInfo), fMask=0x40 | 0x100,
                       lpVerb='runas', lpFile=command[0], lpParameters=subprocess.list2cmdline(command[1:]),
                       lpDirectory=str(cwd), nShow=1)
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not info.hProcess:
        raise OSError('UAC did not return an owned process handle')
    try:
        if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        kernel.CloseHandle(info.hProcess)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--elevated', action='store_true')
    parser.add_argument('--python-exe', default=sys.executable)
    parser.add_argument('--pi-executable', default='pi')
    parser.add_argument('--node-exe', default='node')
    original = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(original)
    if sys.platform != 'win32':
        parser.error('This launcher requires Windows')
    try:
        command, env = prepare(ROOT, args.python_exe, args.pi_executable, args.node_exe)
        admin = is_admin()
        if args.elevated and not admin:
            return elevate([sys.executable, str(Path(__file__).resolve()), *original], Path.cwd())
        if admin:
            print('Pi and its tools run as administrator. CUCP live control still starts off.', file=sys.stderr)
        return subprocess.run(command, env=env, shell=False).returncode
    except (OSError, ValueError) as exc:
        print('CUCP Pi launcher: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
