"""Concrete, explicitly staged Windows adapters for the detached legacy helper.

This is not NativeSession: a successful launched service survives its parent.
The fixed package is hash-checked before any process/pipe/lock operation. The
manifest is corruption detection, not authentication against a same-user attacker.
No executable or authority can be supplied in a protocol request.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from .legacy_helper_client import (LegacyHelperClient, HelperClientError, LockSnapshot,
    MAX_FRAME_BYTES, MAX_LOCK_BYTES, _json, inspect_lock, read_lock_safely)

REQUIRED_FILES = ('PcuCp.LegacyHelper.exe', 'PcuCp.LegacyHelper.exe.config', 'PcuCp.LegacyInterop.dll')
SNAPSHOT_KEY = '_cucp_staged_snapshot'


def validate_package(directory: Path) -> dict:
    """Pinned local layout, strict bounded manifest, no request-controlled paths."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or {p.name for p in directory.iterdir()} != set(REQUIRED_FILES) | {'manifest.json'}:
        raise ValueError('helper_package_layout_invalid')
    manifest_path = directory / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 16384:
        raise ValueError('helper_package_manifest_missing_or_invalid')
    manifest = _json(manifest_path.read_bytes())
    wanted = dict(schema='cucp.legacy-helper-package/v1', status='staged-unqualified',
                  helper_version='2.0.0', runtime='net48',
                  runtime_dependencies=['Windows', '.NET Framework 4.8'], entrypoint=REQUIRED_FILES[0])
    if (not isinstance(manifest, dict) or set(manifest) != set(wanted) | {'files'} or
            any(manifest.get(k) != v for k, v in wanted.items()) or
            not isinstance(manifest['files'], dict) or set(manifest['files']) != set(REQUIRED_FILES)):
        raise ValueError('helper_package_manifest_invalid')
    for name in REQUIRED_FILES:
        path, entry = directory / name, manifest['files'][name]
        if (not isinstance(entry, dict) or set(entry) != {'bytes', 'sha256'} or
                type(entry['bytes']) is not int or not 0 < entry['bytes'] <= 64 * 1024 * 1024 or
                not isinstance(entry['sha256'], str) or len(entry['sha256']) != 64 or
                path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes']):
            raise ValueError('helper_package_artifact_invalid')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('helper_package_hash_mismatch')
    return manifest


class SystemClock:
    def utcnow(self): return datetime.now(timezone.utc)
    def monotonic(self): return time.monotonic()
    def sleep(self, seconds): time.sleep(seconds)


class _FileInfo(ctypes.Structure):
    _fields_ = [('attributes', w.DWORD), ('creation', w.FILETIME), ('access', w.FILETIME),
                ('write', w.FILETIME), ('volume', w.DWORD), ('size_high', w.DWORD),
                ('size_low', w.DWORD), ('links', w.DWORD), ('index_high', w.DWORD), ('index_low', w.DWORD)]


class WindowsAuthority:
    """Read-only PID probe, real username, handle-based byte-exact lock CAS."""
    def __init__(self):
        if os.name != 'nt': raise OSError('staged_helper_requires_windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateFileW': ([w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            'GetFileInformationByHandle': ([w.HANDLE, ctypes.POINTER(_FileInfo)], w.BOOL),
            'ReadFile': ([w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL),
            'SetFileInformationByHandle': ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'GetDriveTypeW': ([w.LPCWSTR], w.UINT),
            'GetVolumeInformationByHandleW': ([w.HANDLE, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD], w.BOOL),
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'GetExitCodeProcess': ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.k, name); function.argtypes = args; function.restype = result
        a = ctypes.WinDLL('advapi32', use_last_error=True)
        a.GetUserNameW.argtypes = [w.LPWSTR, ctypes.POINTER(w.DWORD)]; a.GetUserNameW.restype = w.BOOL
        buf, length = ctypes.create_unicode_buffer(257), w.DWORD(257)
        if not a.GetUserNameW(buf, ctypes.byref(length)): raise ctypes.WinError(ctypes.get_last_error())
        self.owner_user = buf.value

    def process_alive(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only
        if not handle:
            error = ctypes.get_last_error()
            if error == 87: return False  # invalid PID
            raise ctypes.WinError(error)
        try:
            code = w.DWORD()
            if not self.k.GetExitCodeProcess(handle, ctypes.byref(code)): raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259
        finally: self.k.CloseHandle(handle)

    def lock(self, path, expected=None):
        # Share READ only: no writer, renamer or deleter may race this acquisition.
        # OPEN_REPARSE_POINT plus the attribute check refuses a symlink target.
        # This CAS identity contract is deliberately local fixed-drive NTFS only;
        # 64-bit BY_HANDLE_FILE_INFORMATION IDs are not unique on ReFS.
        if str(path).startswith('\\\\') or self.k.GetDriveTypeW(Path(path).anchor) != 3:
            raise ValueError('helper_lock_requires_local_fixed_ntfs')
        access = 0x80000000 | (0x10000 if expected is not None else 0)
        handle = self.k.CreateFileW(str(path), access, 1, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (2, 3): return False if expected is not None else None
            raise ctypes.WinError(error)
        try:
            filesystem = ctypes.create_unicode_buffer(32)
            if not self.k.GetVolumeInformationByHandleW(handle, None, 0, None, None, None, filesystem, len(filesystem)):
                raise ctypes.WinError(ctypes.get_last_error())
            if filesystem.value != 'NTFS': raise ValueError('helper_lock_requires_local_fixed_ntfs')
            info = _FileInfo()
            if not self.k.GetFileInformationByHandle(handle, ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & (0x400 | 0x10): raise ValueError('helper_lock_reparse_or_directory')
            size = info.size_high * 2**32 + info.size_low
            if size > MAX_LOCK_BYTES: raise ValueError('helper_lock_too_large')
            identity = (info.volume, info.index_high, info.index_low)
            buffer, read = ctypes.create_string_buffer(size + 1), w.DWORD()
            if not self.k.ReadFile(handle, buffer, size + 1, ctypes.byref(read), None): raise ctypes.WinError(ctypes.get_last_error())
            if read.value != size: raise ValueError('helper_lock_changed')
            snapshot = LockSnapshot(buffer.raw[:size], identity)
            if expected is None: return snapshot
            if snapshot != expected: return False
            delete = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO.BOOLEAN, exactly one byte
            # FileDispositionInfo, same open handle, never pathname unlink.
            return bool(self.k.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)))
        finally: self.k.CloseHandle(handle)


class WindowsLockStore:
    def __init__(self, path, authority): self.path, self.authority = Path(path), authority
    def read(self): return self.authority.lock(self.path)
    def compare_delete(self, expected): return self.authority.lock(self.path, expected)


def capture_exchange(argv, timeout):
    """Bound both drains; terminate only this retained exchange worker, no retry."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    output, errors, overflow = bytearray(), bytearray(), threading.Event()
    def drain(stream, target, maximum):
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk: break
                remaining = maximum - len(target)
                target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
                    try: process.kill()
                    except OSError: pass
                    break
        finally: stream.close()
    readers = [threading.Thread(target=drain, args=(stream, target, cap), daemon=True)
               for stream, target, cap in ((process.stdout, output, MAX_FRAME_BYTES), (process.stderr, errors, 65536))]
    for reader in readers: reader.start()
    try:
        process.wait(timeout=timeout)
        for reader in readers: reader.join(1)
        if overflow.is_set() or any(reader.is_alive() for reader in readers):
            raise OSError('helper_exchange_output_limit_or_incomplete_drain')
        if process.returncode: raise OSError('helper_exchange_failed')
        return bytes(output)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('helper_exchange_timeout_no_retry') from exc
    finally:
        if process.poll() is None: process.kill()
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired: pass
        for reader in readers: reader.join(.1)


class CompiledTransport:
    def __init__(self, executable): self.executable = Path(executable)
    def exchange(self, pipe_name, request, *, connect_timeout_ms, read_timeout_ms):
        with tempfile.TemporaryDirectory(prefix='cucp-helper-exchange-') as root:
            path = Path(root) / 'request.json'; path.write_bytes(request)
            return capture_exchange([str(self.executable), 'exchange', '--pipe', pipe_name, '--request-file', str(path),
                '--connect-timeout-ms', str(connect_timeout_ms), '--read-timeout-ms', str(read_timeout_ms)],
                (connect_timeout_ms + read_timeout_ms) / 1000 + 2)


class OwnedDetachedProcess:
    def __init__(self, process): self.process, self.pid = process, process.pid
    def terminate_owned(self):
        if self.process.poll() is None: self.process.kill()
        self.process.wait(timeout=1)


class CompiledLauncher:
    def __init__(self, executable, lock_path, *, desktop):
        if type(desktop) is not bool: raise ValueError('desktop authority must be boolean')
        self.executable, self.lock_path, self.desktop = Path(executable), Path(lock_path), desktop
    def launch(self, *, idle_timeout_ms):
        argv = [str(self.executable), 'serve', '--lock-file', str(self.lock_path), '--idle-timeout-ms', str(idle_timeout_ms)]
        if self.desktop: argv.append('--allow-readonly-desktop')
        # No pipes inherited from the launching wrapper; detached lifetime.
        # Never NativeSession/guarded_launch or CREATE_BREAKAWAY_FROM_JOB.
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            shell=False, close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return OwnedDetachedProcess(process)


def encode_snapshot(snapshot):
    if snapshot is None: return None
    return dict(raw=base64.b64encode(snapshot.raw).decode('ascii'), identity=list(snapshot.identity))


def decode_snapshot(value):
    if not isinstance(value, dict) or set(value) != {'raw', 'identity'}: raise ValueError('invalid_snapshot')
    if not isinstance(value['raw'], str) or len(value['raw']) > 22000: raise ValueError('invalid_snapshot')
    identity = value['identity']
    if not isinstance(identity, list) or len(identity) != 3 or any(type(v) is not int or not 0 <= v < 2**32 for v in identity):
        raise ValueError('invalid_snapshot')
    raw = base64.b64decode(value['raw'], validate=True)
    if len(raw) > MAX_LOCK_BYTES: raise ValueError('invalid_snapshot')
    return LockSnapshot(raw, tuple(identity))


class StagedHelperRuntime:
    def __init__(self, package, lock_path, *, desktop=False):
        self.manifest = validate_package(package)
        self.authority = WindowsAuthority()
        executable = Path(package) / REQUIRED_FILES[0]
        self.client = LegacyHelperClient(store=WindowsLockStore(lock_path, self.authority), transport=CompiledTransport(executable),
            clock=SystemClock(), process_alive=self.authority.process_alive, owner_user=self.authority.owner_user)
        self.launcher = CompiledLauncher(executable, lock_path, desktop=desktop)

    def handle(self, request):
        if not isinstance(request, dict) or set(request) != {'operation', 'arguments'}:
            raise ValueError('invalid_helper_bridge_envelope')
        operation, args = request['operation'], request['arguments']
        fields = {'read': set(), 'stale': {'snapshot'}, 'delete': {'snapshot'}, 'status': set(),
                  'start': {'idle_timeout_ms'}, 'stop': {'force'}, 'invoke': {'action', 'args', 'timeout_ms', 'request_id', 'snapshot'}, 'version': set()}
        if not isinstance(operation, str) or operation not in fields or not isinstance(args, dict) or set(args) != fields[operation]:
            raise ValueError('invalid_helper_bridge_operation')
        if operation == 'version': return dict(version=self.manifest['helper_version'], error=None)
        if operation == 'status': return self.client.status()
        if operation == 'start': return self.client.start(self.launcher, idle_timeout_ms=args['idle_timeout_ms'])
        if operation == 'stop': return self.client.stop(force=args['force'])
        if operation == 'invoke':
            request_id = args['request_id']
            if type(request_id) is not int or not 0 < request_id <= 2147483647: raise ValueError('invalid_request_id')
            self.client._request_id = request_id - 1
            expected = None
            if args['snapshot'] is not None:
                expected = inspect_lock(decode_snapshot(args['snapshot']), owner_user=self.client.owner_user,
                    now=self.client.clock.utcnow(), process_alive=self.client.process_alive)
            return self.client.invoke(args['action'], args['args'], timeout_ms=args['timeout_ms'], expected=expected)
        state = self.client.state()
        if operation == 'read':
            value = read_lock_safely(state.snapshot)
            # Return an internal metadata property only; public schemas select fields.
            return dict(value, **{SNAPSHOT_KEY: encode_snapshot(state.snapshot)}) if value is not None else None
        expected = decode_snapshot(args['snapshot']) if args['snapshot'] is not None else None
        if operation == 'stale': return not state.usable or expected is None or expected != state.snapshot
        return bool(state.kind == 'stale' and expected is not None and expected == state.snapshot and self.client._delete(state))
