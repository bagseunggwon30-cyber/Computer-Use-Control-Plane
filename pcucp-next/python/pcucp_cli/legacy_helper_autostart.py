"""Bounded staged helper autostart, with explicit invocation-time authority.

Pure planning plus a fixed-path controller. Production mutations use create-new
and existing Windows handle-CAS deletion; no unknown file is overwritten. Test
stores/launch captures operate only in owned temporary directories. A caller may
not supply a command, path, authority or bootstrap through request JSON.
"""
from __future__ import annotations

import hashlib
import ctypes
from contextlib import contextmanager
import json
import os
from pathlib import Path

from .legacy_helper_client import _json, _idle_timeout

SHIM_NAME = 'cucp-helper-autostart.cmd'
MANIFEST_NAME = '.cucp-helper-autostart.json'
SCHEMA = 'cucp.staged-helper-autostart-owner/v1'
MAX_BYTES = 16384
NOTE = '다음 로그인부터 helper-server 가 자동 기동됩니다. 지금 바로 띄우려면 macro session start-helper.'


def _path(value):
    text = os.path.abspath(value)
    if any(c in text for c in ('"', '\x00', '\r', '\n')):
        raise ValueError('invalid_autostart_path')
    return text


def _quoted(value):
    return '"' + value.replace('%', '%%') + '"'


def plan_autostart(startup_dir, python_exe, bootstrap, *, idle_timeout_ms=28800000, desktop=False, metadata_directory=None, startup_identity=None):
    _idle_timeout(idle_timeout_ms)
    if type(desktop) is not bool: raise ValueError('desktop authority must be boolean')
    directory, python_exe, bootstrap = _path(startup_dir), _path(python_exe), _path(bootstrap)
    metadata_directory=_path(metadata_directory if metadata_directory is not None else Path(directory).parent)
    if startup_identity is not None and (not isinstance(startup_identity,(tuple,list)) or len(startup_identity)!=3
            or any(type(v) is not int or not 0<=v<2**32 for v in startup_identity)):
        raise ValueError('invalid_startup_identity')
    command = (python_exe, '-E', '-s', bootstrap, '--staged-unqualified', '--idle-timeout-ms', str(idle_timeout_ms))
    if desktop: command += ('--allow-readonly-desktop',)
    command_line = ' '.join(_quoted(item) for item in command)
    if len(command_line.encode('utf-16-le')) // 2 > 8191: raise ValueError('autostart_command_too_long')
    # UTF-8 is selected on an ASCII-only line, outside a parenthesized block.
    # No Start/call/%* layer and no user-controlled text outside quoted argv.
    text = ('@echo off\r\nsetlocal EnableExtensions DisableDelayedExpansion\r\n'
            'rem CUCP staged helper autostart; generated, owned, unqualified.\r\n'
            'set "_CUCP_CP="\r\nset "ERRORLEVEL="\r\n'
            'for /f "tokens=2 delims=:" %%C in (\'chcp\') do set "_CUCP_CP=%%C"\r\n'
            'chcp 65001 >nul\r\n' + command_line + '\r\n'
            'set "_CUCP_EXIT=%errorlevel%"\r\n'
            'if defined _CUCP_CP chcp %_CUCP_CP% >nul\r\n'
            'exit /b %_CUCP_EXIT%\r\n')
    shim = text.encode('utf-8')
    manifest = dict(schema=SCHEMA, startup_directory=directory, startup_identity=list(startup_identity) if startup_identity is not None else None, python_exe=python_exe, bootstrap=bootstrap,
                    idle_timeout_ms=idle_timeout_ms, desktop=desktop,
                    shim_sha256=hashlib.sha256(shim).hexdigest())
    metadata = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    if max(len(shim), len(metadata)) > MAX_BYTES: raise ValueError('autostart_artifact_too_large')
    return dict(shim_path=str(Path(directory) / SHIM_NAME), manifest_path=str(Path(metadata_directory) / MANIFEST_NAME),
                shim=shim, manifest=metadata, command=command, idle_timeout_ms=idle_timeout_ms, desktop=desktop)


class _MarkerLease:
    def __init__(self, snapshot, delete): self.snapshot, self._delete = snapshot, delete
    def delete(self): return self._delete()


class WindowsAutostartStore:
    """Fixed basenames, retained ancestor directories, and one metadata lease."""
    def __init__(self, directory, metadata_directory, authority):
        self.directory, self.metadata_directory = Path(_path(directory)), Path(_path(metadata_directory))
        self.authority, self._active, self.startup_identity = authority, False, None
        from ctypes import wintypes as w
        k=authority.k
        k.WriteFile.argtypes=[w.HANDLE,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.LPVOID];k.WriteFile.restype=w.BOOL
        k.FlushFileBuffers.argtypes=[w.HANDLE];k.FlushFileBuffers.restype=w.BOOL

    def _path(self, name):
        if name==SHIM_NAME: return self.directory/name
        if name==MANIFEST_NAME: return self.metadata_directory/name
        raise ValueError('unknown_autostart_artifact')

    def _require_operation(self):
        if not self._active: raise ValueError('autostart_operation_lease_required')

    @contextmanager
    def operation(self):
        from .legacy_helper_runtime import _FileInfo
        if self._active: raise ValueError('nested_autostart_operation')
        k=self.authority.k;handles=[];seen=set();identities={}
        try:
            for directory in (self.directory,self.metadata_directory):
                if str(directory).startswith('\\\\') or k.GetDriveTypeW(directory.anchor)!=3:
                    raise ValueError('autostart_requires_local_fixed_ntfs')
                for component in [*reversed(directory.parents),directory]:
                    key=os.path.normcase(str(component))
                    if key in seen: continue
                    handle=k.CreateFileW(str(component),0x80000000,1,None,3,0x02000000|0x00200000,None)
                    if handle==ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
                    handles.append(handle)
                    info=_FileInfo();filesystem=ctypes.create_unicode_buffer(32)
                    if not k.GetFileInformationByHandle(handle,ctypes.byref(info)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not info.attributes & 0x10 or info.attributes & 0x400:
                        raise ValueError('autostart_directory_missing_or_reparse')
                    if not k.GetVolumeInformationByHandleW(handle,None,0,None,None,None,filesystem,len(filesystem)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if filesystem.value!='NTFS': raise ValueError('autostart_requires_local_fixed_ntfs')
                    identities[key]=(info.volume,info.index_high,info.index_low);seen.add(key)
            self.startup_identity=identities[os.path.normcase(str(self.directory))]
            # Filesystem identities, not lexical spelling, enforce the outside-
            # Startup invariant even for Win32 short-name/path aliases.
            for component in [*self.metadata_directory.parents,self.metadata_directory]:
                if identities[os.path.normcase(str(component))]==self.startup_identity:
                    raise ValueError('autostart_metadata_must_be_outside_startup')
            self._active=True
            yield
        finally:
            self._active=False;self.startup_identity=None
            for handle in reversed(handles): k.CloseHandle(handle)

    def exists(self,name): self._require_operation();return os.path.lexists(self._path(name))
    def read(self,name):
        self._require_operation()
        if name!=SHIM_NAME: raise ValueError('metadata_requires_retained_lease')
        return self.authority.lock(self._path(name))
    def create_new(self,name,raw):
        self._require_operation()
        if name!=SHIM_NAME or type(raw) is not bytes or len(raw)>MAX_BYTES: raise ValueError('invalid_shim_create')
        with self._path(name).open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    def compare_delete(self,name,expected):
        self._require_operation()
        if name!=SHIM_NAME: raise ValueError('metadata_requires_retained_lease')
        return self.authority.lock(self._path(name),expected)

    def replace_known(self, expected, raw):
        """Rewrite only the acquired known shim, retaining its file handle.

        Identity and bytes are checked under a write-exclusive handle. A failed
        write restores the original bytes through that same handle; no pathname
        reopen, unowned overwrite, or delete/create publication gap is used.
        """
        from ctypes import wintypes as w
        from .legacy_helper_runtime import _FileInfo
        from .legacy_helper_client import LockSnapshot
        self._require_operation()
        if type(raw) is not bytes or len(raw)>MAX_BYTES: raise ValueError('invalid_shim_replacement')
        k=self.authority.k
        k.SetFilePointerEx.argtypes=[w.HANDLE,ctypes.c_longlong,ctypes.POINTER(ctypes.c_longlong),w.DWORD]
        k.SetFilePointerEx.restype=w.BOOL
        k.SetEndOfFile.argtypes=[w.HANDLE];k.SetEndOfFile.restype=w.BOOL
        handle=k.CreateFileW(str(self._path(SHIM_NAME)),0xc0000000,1,None,3,0x00200000,None)
        if handle==ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        try:
            info=_FileInfo()
            if not k.GetFileInformationByHandle(handle,ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
            size=info.size_high*2**32+info.size_low
            if info.attributes & (0x400|0x10) or size>MAX_BYTES: raise ValueError('invalid_shim_replacement_target')
            buffer=ctypes.create_string_buffer(size+1);read=w.DWORD()
            if not k.ReadFile(handle,buffer,size+1,ctypes.byref(read),None): raise ctypes.WinError(ctypes.get_last_error())
            if read.value!=size: raise OSError('shim_changed_during_acquisition')
            acquired=LockSnapshot(buffer.raw[:size],(info.volume,info.index_high,info.index_low))
            if acquired!=expected: return False
            def write(value):
                if not k.SetFilePointerEx(handle,0,None,0): raise ctypes.WinError(ctypes.get_last_error())
                data=ctypes.create_string_buffer(value);written=w.DWORD()
                if not k.WriteFile(handle,data,len(value),ctypes.byref(written),None): raise ctypes.WinError(ctypes.get_last_error())
                if written.value!=len(value): raise OSError('shim_short_write')
                if not k.SetEndOfFile(handle) or not k.FlushFileBuffers(handle): raise ctypes.WinError(ctypes.get_last_error())
            try: write(raw)
            except OSError:
                write(acquired.raw)
                raise
            return True
        finally: k.CloseHandle(handle)

    @contextmanager
    def marker(self,create=None):
        """No reopen gap: READ|DELETE/share-READ is held through publication."""
        from ctypes import wintypes as w
        from .legacy_helper_runtime import _FileInfo
        from .legacy_helper_client import LockSnapshot
        self._require_operation()
        if create is not None and (type(create) is not bytes or len(create)>MAX_BYTES):
            raise ValueError('invalid_metadata_create')
        k=self.authority.k
        access=0x80000000|0x10000|(0x40000000 if create is not None else 0)
        handle=k.CreateFileW(str(self._path(MANIFEST_NAME)),access,1,None,1 if create is not None else 3,0x00200000,None)
        if handle==ctypes.c_void_p(-1).value:
            error=ctypes.get_last_error()
            if create is None and error in (2,3): yield None;return
            raise ctypes.WinError(error)
        try:
            info=_FileInfo()
            if not k.GetFileInformationByHandle(handle,ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & (0x400|0x10): raise ValueError('autostart_metadata_reparse_or_directory')
            if create is not None:
                buffer=ctypes.create_string_buffer(create);written=w.DWORD()
                if not k.WriteFile(handle,buffer,len(create),ctypes.byref(written),None): raise ctypes.WinError(ctypes.get_last_error())
                if written.value!=len(create): raise OSError('autostart_metadata_short_write')
                if not k.FlushFileBuffers(handle): raise ctypes.WinError(ctypes.get_last_error())
                raw=create
            else:
                size=info.size_high*2**32+info.size_low
                if size>MAX_BYTES: raise ValueError('autostart_metadata_too_large')
                buffer=ctypes.create_string_buffer(size+1);read=w.DWORD()
                if not k.ReadFile(handle,buffer,size+1,ctypes.byref(read),None): raise ctypes.WinError(ctypes.get_last_error())
                if read.value!=size: raise OSError('autostart_metadata_changed')
                raw=buffer.raw[:size]
            snapshot=LockSnapshot(raw,(info.volume,info.index_high,info.index_low))
            def delete():
                disposition=ctypes.c_ubyte(1)
                return bool(k.SetFileInformationByHandle(handle,4,ctypes.byref(disposition),1))
            yield _MarkerLease(snapshot,delete)
        finally: k.CloseHandle(handle)


class AutostartController:
    def __init__(self,directory,python_exe,bootstrap,*,metadata_directory,store,allow_change,desktop=False,validate_install=None):
        if type(allow_change) is not bool or type(desktop) is not bool: raise ValueError('invalid_autostart_authority')
        self.directory,self.metadata_directory=_path(directory),_path(metadata_directory)
        try: inside=os.path.commonpath((self.directory,self.metadata_directory))==self.directory
        except ValueError: inside=False
        if inside: raise ValueError('autostart_metadata_must_be_outside_startup')
        self.python_exe,self.bootstrap=_path(python_exe),_path(bootstrap)
        self.store,self.allow_change,self.desktop=store,allow_change,desktop
        self.validate_install=validate_install or (lambda:None)
        self.shim_path=str(Path(self.directory)/SHIM_NAME)

    def _plan(self,idle_timeout_ms=28800000,**values):
        return plan_autostart(self.directory,values.get('python_exe',self.python_exe),values.get('bootstrap',self.bootstrap),
            idle_timeout_ms=idle_timeout_ms,desktop=values.get('desktop',self.desktop),
            metadata_directory=self.metadata_directory,startup_identity=self.store.startup_identity)

    def _owned(self,lease):
        if lease is None: raise ValueError('shim_unowned_or_legacy_preserved')
        metadata=lease.snapshot;value=_json(metadata.raw)
        required={'schema','python_exe','bootstrap','idle_timeout_ms','desktop','shim_sha256','startup_directory','startup_identity'}
        if not isinstance(value,dict) or set(value)!=required or value['schema']!=SCHEMA:
            raise ValueError('shim_ownership_invalid')
        if value['startup_directory']!=self.directory or value['startup_identity']!=list(self.store.startup_identity):
            raise ValueError('shim_startup_target_changed')
        expected=self._plan(value['idle_timeout_ms'],python_exe=value['python_exe'],bootstrap=value['bootstrap'],desktop=value['desktop'])
        if expected['manifest']!=metadata.raw: raise ValueError('shim_ownership_invalid')
        shim=self.store.read(SHIM_NAME)
        if shim is not None and shim.raw!=expected['shim']: raise ValueError('shim_changed_preserved')
        return shim,expected

    def _failure(self,reason,detail): return dict(status='error',reason=reason,detail=str(detail)[:512],path=self.shim_path)
    def status(self):
        with self.store.operation(): installed=bool(self.store.exists(SHIM_NAME))
        return dict(status='ok',installed=installed,shim_path=self.shim_path)

    def install(self,idle_timeout_ms=28800000):
        if not self.allow_change: raise PermissionError('session install-autostart requires -AllowLiveControl')
        try:
            _idle_timeout(idle_timeout_ms);self.validate_install()
            with self.store.operation():
                plan=self._plan(idle_timeout_ms)
                if self.store.exists(SHIM_NAME) or self.store.exists(MANIFEST_NAME):
                    with self.store.marker() as lease:
                        shim,previous=self._owned(lease)
                        if previous['manifest']!=plan['manifest']: raise ValueError('shim_configuration_changed_uninstall_then_install')
                        if shim is None: self.store.create_new(SHIM_NAME,plan['shim'])
                else:
                    with self.store.marker(create=plan['manifest']):
                        self.store.create_new(SHIM_NAME,plan['shim'])
            return dict(status='ok',action='install-autostart',shim_path=self.shim_path,idle_timeout_ms=idle_timeout_ms,note=NOTE)
        except (OSError,ValueError,TypeError) as exc: return self._failure('shim_write_failed',exc)

    def uninstall(self):
        if not self.allow_change: raise PermissionError('session uninstall-autostart requires -AllowLiveControl')
        try:
            with self.store.operation():
                if not self.store.exists(SHIM_NAME) and not self.store.exists(MANIFEST_NAME):
                    return dict(status='ok',action='uninstall-autostart',shim_path=self.shim_path,removed=False)
                with self.store.marker() as lease:
                    shim,_=self._owned(lease)
                    if shim is not None and not self.store.compare_delete(SHIM_NAME,shim): raise ValueError('shim_changed_or_not_removable')
                    if not lease.delete(): raise ValueError('ownership_changed_or_not_removable')
            return dict(status='ok',action='uninstall-autostart',shim_path=self.shim_path,removed=shim is not None)
        except (OSError,ValueError,TypeError) as exc: return self._failure('shim_remove_failed',exc)

    def handle(self,request):
        if not isinstance(request,dict) or set(request)!={'operation','arguments'}: raise ValueError('invalid_autostart_request')
        op,args=request['operation'],request['arguments']
        fields={'autostart-install':{'idle_timeout_ms'},'autostart-uninstall':set(),'autostart-status':set()}
        if not isinstance(op,str) or op not in fields or not isinstance(args,dict) or set(args)!=fields[op]: raise ValueError('invalid_autostart_request')
        if op=='autostart-install': return self.install(args['idle_timeout_ms'])
        if op=='autostart-uninstall': return self.uninstall()
        return self.status()
