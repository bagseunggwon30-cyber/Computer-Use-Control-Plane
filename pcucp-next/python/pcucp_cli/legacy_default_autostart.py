"""Default login launcher migration with exact known bytes and retained-handle writes.

Only the original shim for this repository or its fixed Python replacement may
be changed. No PowerShell command is executed, and request data cannot choose
an executable, source path, Startup folder or authority.
"""
from __future__ import annotations
from pathlib import Path
import re
from .legacy_helper_autostart import AutostartController, SHIM_NAME, NOTE


def legacy_shim(server, idle_timeout_ms):
    text=('@echo off\r\n'
          'rem CUCP helper-server autostart shim (v2.2.0). Remove via: cucp macro session uninstall-autostart\r\n'
          'start "" /min powershell.exe -NoProfile -NoLogo -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden '
          '-File "'+str(server)+'" -IdleTimeoutMs '+str(idle_timeout_ms)+'\r\n')
    return text.encode('ascii',errors='replace')


class DefaultAutostartController(AutostartController):
    def __init__(self, *args, legacy_server, **kwargs):
        super().__init__(*args,**kwargs)
        self.legacy_server=str(Path(legacy_server).absolute())

    def _recognized(self, snapshot):
        # Integer text is the only variable slot. Reconstruct the entire known
        # artifact before accepting it; never parse or execute a command line.
        for match in re.finditer(rb'(?:-IdleTimeoutMs |"--idle-timeout-ms" ")(-?[0-9]+)',snapshot.raw):
            value=int(match[1])
            if not -2147483648<=value<=2147483647 or str(value).encode()!=match[1]: continue
            if snapshot.raw==legacy_shim(self.legacy_server,value): return True
            if value>=0 and snapshot.raw==self._plan(value)['shim']: return True
        return False

    def install(self,idle_timeout_ms=28800000):
        if not self.allow_change: raise PermissionError('session install-autostart requires -AllowLiveControl')
        try:
            if type(idle_timeout_ms) is not int or not -2147483648<=idle_timeout_ms<=2147483647:
                raise ValueError('idle_timeout_ms must be an Int32')
            self.validate_install()
            with self.store.operation():
                plan=self._plan(max(0,idle_timeout_ms))
                current=self.store.read(SHIM_NAME)
                if current is None: self.store.create_new(SHIM_NAME,plan['shim'])
                elif not self._recognized(current): raise ValueError('shim_changed_or_unowned_preserved')
                elif current.raw!=plan['shim'] and not self.store.replace_known(current,plan['shim']):
                    raise ValueError('shim_changed_during_replacement')
            return dict(status='ok',action='install-autostart',shim_path=self.shim_path,idle_timeout_ms=idle_timeout_ms,note=NOTE)
        except (OSError,ValueError,TypeError) as exc: return self._failure('shim_write_failed',exc)

    def uninstall(self):
        if not self.allow_change: raise PermissionError('session uninstall-autostart requires -AllowLiveControl')
        try:
            with self.store.operation():
                current=self.store.read(SHIM_NAME)
                if current is not None:
                    if not self._recognized(current): raise ValueError('shim_changed_or_unowned_preserved')
                    if not self.store.compare_delete(SHIM_NAME,current): raise ValueError('shim_changed_or_not_removable')
            return dict(status='ok',action='uninstall-autostart',shim_path=self.shim_path,removed=current is not None)
        except (OSError,ValueError,TypeError) as exc: return self._failure('shim_remove_failed',exc)
