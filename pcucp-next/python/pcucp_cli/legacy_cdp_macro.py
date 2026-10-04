"""Legacy wrapper formatting/effect plan for integration without a CLI edit.

Console JSON serialization is injected by the legacy host, which owns its exact
PowerShell-5-compatible property/depth formatting. No global stdout/query rules
are recreated or bypassed here.
"""
from __future__ import annotations
from dataclasses import dataclass
import time
from .legacy_cdp_contract import (LegacyCdpMacro, LegacyCdpResult, dom_bridge_plan,
                                 ps_string, utf16_length, utf16_slice)


@dataclass(frozen=True)
class LegacyCdpOutput:
    payload: dict
    exit_code: int
    brief_line: str
    json_depth: int
    trajectory: dict | None = None

    def render(self, *, brief=False, json_formatter=None):
        if brief: return self.brief_line + '\n'
        if json_formatter is None:
            raise ValueError('Exact legacy JSON formatter must be supplied by the host')
        return json_formatter(self.payload, self.json_depth) + '\n'


class LegacyCdpPortCache:
    """One-second cache for the exact configured endpoint, never a port scan."""
    def __init__(self): self._entries = {}

    def check(self, adapter):
        now = time.monotonic()
        old = self._entries.get(adapter.endpoint)
        if old and old[0] > now: return old[1]
        opened = adapter.port_open()
        self._entries[adapter.endpoint] = (time.monotonic() + 1, opened)
        return opened


def _subject(macro):
    action, a = macro.action, macro.args
    if action == 'cdp-detect': return f'{action} port={macro.port}'
    if action == 'cdp-eval': return action
    if action in ('cdp-type', 'cdp-click'): return f"{action} selector='{a.get('selector', '')}'"
    label = 'label' if 'type' in action else 'text'
    return f"{action} {label}='{a.get('needle', '')}'"


def _trajectory(macro, result, *, closed=False):
    action, args, p = macro.action, macro.args, result.payload
    if action not in ('cdp-type', 'cdp-click', 'cdp-smart-click', 'cdp-smart-type'): return None
    payload = dict(source=action.replace('-', '_'))
    if action in ('cdp-type', 'cdp-click'): payload['selector'] = args['selector']
    elif action == 'cdp-smart-click': payload['text'] = args['needle']
    else: payload['label'] = args['needle']
    if not closed and action == 'cdp-smart-type': payload['matched_text'] = ps_string(p.get('matched_text'))
    if action in ('cdp-type', 'cdp-smart-type'):
        payload.update(text_length=utf16_length(args.get('text', '')), sent_enter=args.get('enter', False))
    if not closed:
        if action == 'cdp-smart-click':
            payload['matched_text'] = ps_string(p.get('matched_text'))
        if action == 'cdp-smart-click': payload['score'] = p.get('score')
        payload['page_id'] = ps_string(p.get('page_id'))
    payload['exit'] = result.exit_code
    if closed: payload['reason'] = 'cdp_port_closed'
    # Deliberately retain the old cdp-type success log's "click" kind.
    kind = 'type' if action == 'cdp-smart-type' or closed and action == 'cdp-type' else 'click'
    return dict(kind=kind, payload=payload)


def port_closed_output(macro: LegacyCdpMacro) -> LegacyCdpOutput:
    action, a, port = macro.action, macro.args, macro.port
    if action in ('cdp-deep-find', 'cdp-prosemirror-insert'):
        recommendation = f'start the Electron app with --remote-debugging-port={port}' if action == 'cdp-deep-find' else f'launch chrome/electron with --remote-debugging-port={port} (see references/cdp-setup.md)'
        payload = dict(schema=f'cucp.{action}/v1', status='partial', reason='cdp_port_closed', port=port,
                       recommended_action=recommendation)
        line = f'partial {action} port={port} closed'
    else:
        payload = dict(action=action, status='partial', reason='cdp_port_closed', port=port,
                       detail='tcp_port_closed_or_timeout', source='wrapper_preflight')
        if 'smart' in action:
            payload['dom_bridge_plan'] = dom_bridge_plan('type' if 'type' in action else 'click',
                a['needle'], port, a.get('page_match', ''), a.get('text', ''), a.get('clear', False), a.get('enter', False), helper=False)
        line = 'partial ' + _subject(macro) + ' reason=cdp_port_closed'
    result = LegacyCdpResult(payload, 2)
    return LegacyCdpOutput(payload, 2, line, 8, _trajectory(macro, result, closed=True))


def macro_output(macro: LegacyCdpMacro, result: LegacyCdpResult, *, helper_present=True) -> LegacyCdpOutput:
    action, a, p = macro.action, macro.args, result.payload
    ok, reason = p.get('status') == 'ok', ps_string(p.get('reason')) if helper_present else 'helper_failed'
    value = lambda name: ps_string(p.get(name))
    subject = _subject(macro)
    depth, code, payload = 8, result.exit_code, dict(p)
    if action == 'cdp-deep-find':
        payload = {'schema': 'cucp.cdp-deep-find/v1', **p} if helper_present else dict(schema='cucp.cdp-deep-find/v1',status='error',reason='helper_failed')
        traversal = p.get('traversal') if isinstance(p.get('traversal'), dict) else {}
        line = f"ok cdp-deep-find text='{a['needle']}' found={p.get('found_count') or 0} shadow_roots={traversal.get('shadow_roots_seen') or 0} iframes={traversal.get('iframes_seen') or 0}"
        depth, code = 10, 0 if ok else 2  # Preserve even the old failure's "ok" brief prefix.
    elif action == 'cdp-prosemirror-insert':
        payload = {'schema': 'cucp.cdp-prosemirror-insert/v1', **p} if helper_present else dict(schema='cucp.cdp-prosemirror-insert/v1',status='error',reason='helper_failed')
        line = f"ok cdp-prosemirror-insert before_len={value('before_length')} after_len={value('after_length')} text='{a['text']}'" if ok and p.get('changed') else f'partial cdp-prosemirror-insert reason={(reason if helper_present else "unknown") or "unknown"}'
        depth, code = 10, 0 if ok else 3 if p.get('status') == 'blocked' else 2 if helper_present else 1
    elif not ok:
        line = f'partial {subject} reason={reason}'
    elif action == 'cdp-detect':
        line = f"ok cdp-detect port={value('port')} pages={value('page_count')} browser='{value('browser')}' protocol={value('protocol_version')}"
    elif action == 'cdp-eval':
        val = value('result_value')
        if utf16_length(val) > 80: val = utf16_slice(val, 77) + '...'
        line = f"ok cdp-eval result_type={value('result_type')} value='{val}' page='{value('page_title')}'"
    elif action == 'cdp-type':
        line = f"ok {subject} tag={value('tag_name')} ce={value('is_content_editable')} input={value('is_input')} value_len={value('current_value_length')} sent_enter={value('sent_enter')} page='{value('page_title')}'"
    elif action == 'cdp-click':
        line = f"ok {subject} tag={value('tag_name')} page='{value('page_title')}'"
    else:
        extra = f" len={value('text_length')} sent_enter={value('sent_enter')}" if action == 'cdp-smart-type' else ''
        line = f"ok {subject} matched='{value('matched_text')}' score={value('score')} tag={value('tag_name')}{extra} page='{value('page_title')}'"
    return LegacyCdpOutput(payload, code, line, depth, _trajectory(macro, result))


def execute_macro(adapter, macro: LegacyCdpMacro, *, cache=None) -> LegacyCdpOutput:
    if not 1 <= macro.port <= 65535: return port_closed_output(macro)
    if macro.port != adapter.port: raise ValueError('macro port does not match the immutable startup endpoint')
    if not (cache.check(adapter) if cache else adapter.port_open()): return port_closed_output(macro)
    return macro_output(macro, adapter.execute(macro.action, macro.args))
