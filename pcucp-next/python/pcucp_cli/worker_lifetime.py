"""Parent-liveness handle for Windows workers, without owning user applications.

Only SYNCHRONIZE access is inherited, via an explicit handle allow-list. The
native worker watches this kernel object even while a UIA provider is blocked.
"""
from contextlib import contextmanager
import os
import subprocess


@contextmanager
def guarded_launch(command):
    if os.name != 'nt':
        yield list(command), {'start_new_session': True}
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, True, os.getpid())  # SYNCHRONIZE only
    if not handle:
        raise OSError(ctypes.get_last_error(), 'Cannot establish native parent-liveness guard')
    try:
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {'handle_list': [handle]}
        yield [*command, '--parent-handle', str(handle)], {
            'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP,
            'startupinfo': startup, 'close_fds': True,
        }
    finally:
        kernel.CloseHandle(handle)
