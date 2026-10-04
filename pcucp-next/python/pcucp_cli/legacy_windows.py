"""Preserved Win32 windows macro and optional desktop CLI enrichment."""
import time
from .legacy_diagnostic_provider import option, timestamp


def observe_windows(runtime, rest):
    match = option(rest, '--match')
    flags = {value.casefold() for value in rest}
    rich, hidden = '--rich' in flags, '--include-hidden' in flags
    started = time.monotonic()
    windows = runtime._windows(match)
    if not hidden:
        windows = [row for row in windows if row['visible'] and not row['minimized']]
    elapsed = round((time.monotonic() - started) * 1000)
    items, helper_ok, helper_ms, helper_reason = [], None, None, ''
    sources = ['win32']
    if rich:
        started = time.monotonic()
        result = runtime._cli(['observe', 'windows', *(['--match', match] if match else [])])
        helper_ms = round((time.monotonic() - started) * 1000)
        data = result['json']
        if result['exit'] == 0 and data and data.get('status') == 'ok':
            helper_ok = True
            artifact = next((item for item in data.get('artifacts') or [] if item.get('type') == 'windows'), {})
            items = artifact.get('items') or []
            sources.append('helper')
        else:
            helper_ok = False
            status = str(data.get('status') or '') if data else 'no-json'
            helper_reason = f"exit={result['exit']} status={status}"
    foreground = next((row for row in windows if row['foreground']), None)
    if foreground:
        foreground = {key: foreground[key] for key in ('title', 'hwnd', 'pid', 'process', 'class', 'rect')}
    provenance = dict(foreground='win32', items='win32+helper' if rich and items else 'win32',
                      helper_status='ok' if rich and helper_ok else 'degraded' if rich else 'skipped')
    warnings, recoverable = [], []
    degraded, status = False, 'ok'
    if rich and helper_ok is True and not items and windows:
        degraded = True
        warnings.append(f'degraded_helper_empty: helper returned 0 windows but win32 sees {len(windows)}. Using win32 evidence.')
    if rich and helper_ok is False:
        warnings.append(f'helper_unavailable: {helper_reason}. Using win32 only.')
        recoverable.append(dict(code='helper_unavailable', message=helper_reason,
            recommended_action="Run 'cucp macro ensure-helper' or proceed with win32-only enumeration."))
    if not windows:
        status = 'partial'
        if match:
            recoverable.append(dict(code='no_window', message=f"no top-level visible window matches '{match}'",
                recommended_action='Verify the app is running, or call without --match to list everything, or use --include-hidden.'))
        else:
            recoverable.append(dict(code='no_visible_windows', message='no visible top-level windows found (locked/secure desktop?)',
                recommended_action='Re-try after unlocking the workstation or use --include-hidden.'))
    data = dict(match=match, fast=not rich, include_hidden=hidden, helper_elapsed_ms=helper_ms,
                helper_ok=helper_ok, helper_reason=helper_reason, helper_count=len(items), helper_items=items, count=len(windows))
    payload = dict(schema='cucp.observation/v1', kind='windows', status=status, collected_at=timestamp(), elapsed_ms=elapsed,
        sources=sources, provenance=provenance, observation_id='', foreground=foreground,
        active_hwnd=foreground['hwnd'] if foreground else 0, focused_title=foreground['title'] if foreground else '',
        desktop=runtime._read('desktop-size'), windows=windows, data=data,
        cache=dict(hit=False, age_ms=None, max_age_ms=0, key=f'windows::match={match}' if match else 'windows::all', reason='live_enumerate'),
        stale=False, confidence='high', warnings=warnings, recoverable_errors=recoverable, degraded_helper_empty=degraded)
    tag = 'ok-fallback' if degraded else status
    line = f"{tag} windows count={len(windows)} foreground='{payload['focused_title']}' sources={'+'.join(sources)} elapsed_ms={elapsed}"
    return 0 if status == 'ok' else 2, payload, line
