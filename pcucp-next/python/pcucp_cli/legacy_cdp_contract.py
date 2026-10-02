"""Legacy CDP pure contracts. No sockets, browser launch, or page execution."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
import ctypes
import json
import os
from typing import Any

ACTIONS = frozenset(('cdp-detect', 'cdp-eval', 'cdp-type', 'cdp-click', 'cdp-smart-find',
                     'cdp-smart-type-find', 'cdp-smart-click', 'cdp-smart-type',
                     'cdp-deep-find', 'cdp-prosemirror-insert'))
LIVE_ACTIONS = ACTIONS - {'cdp-detect', 'cdp-smart-find', 'cdp-smart-type-find', 'cdp-deep-find'}


@dataclass(frozen=True)
class LegacyCdpResult:
    payload: dict[str, Any]
    exit_code: int = 0


def ps_string(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, list):
        return ' '.join(ps_string(v) for v in value)
    if isinstance(value, dict):
        return '@{' + '; '.join(f'{k}={"System.Object[]" if isinstance(v, list) else ps_string(v)}' for k, v in value.items()) + '}'
    return str(value)


def utf16_length(text: str) -> int:
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def utf16_slice(text: str, count: int) -> str:
    return text.encode('utf-16-le', errors='surrogatepass')[:count * 2].decode('utf-16-le', errors='surrogatepass')


def _invariant_lower(text: str) -> str:
    if os.name == 'nt' and text:
        lower = ctypes.WinDLL('kernel32', use_last_error=True).LCMapStringEx
        lower.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_int,
                          ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        lower.restype = ctypes.c_int
        size = lower('', 0x100, text, utf16_length(text), None, 0, None, None, None)
        if size == 0: raise ctypes.WinError(ctypes.get_last_error())
        output = ctypes.create_unicode_buffer(size)
        count = lower('', 0x100, text, utf16_length(text), output, size, None, None, None)
        if count == 0: raise ctypes.WinError(ctypes.get_last_error())
        return output[:count]
    # Portable fixture fallback; Windows NLS supplies exact Framework casing.
    return ''.join(c.lower() if len(c.lower()) == 1 else c for c in text)


def _nls_compare(left: str, right: str, locale=None) -> int:
    if os.name == 'nt':
        compare = ctypes.WinDLL('kernel32', use_last_error=True).CompareStringEx
        compare.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_int,
                            ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        compare.restype = ctypes.c_int
        result = compare(locale, 1, left, utf16_length(left), right, utf16_length(right), None, None, 0)
        if result == 0: raise ctypes.WinError(ctypes.get_last_error())
        return result - 2
    a, b = _invariant_lower(left), _invariant_lower(right)
    return (a > b) - (a < b)


def _title_compare(left: str, right: str) -> int:
    return _nls_compare(left, right)


def _ps_equal(left: str, right: str) -> bool:
    return _nls_compare(left, right, '') == 0


def score_pages(detect: dict, page_match: str | None = '') -> list[dict]:
    pages = detect.get('pages', [])
    if not isinstance(pages, list):
        raise ValueError('pages must be an actual array')
    needle = _invariant_lower(page_match or '')
    output = []
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError('page must be an object')
        title, url, kind = (ps_string(page.get(key)) for key in ('title', 'url', 'type'))
        title_lower, url_lower = _invariant_lower(title), _invariant_lower(url)
        score, reasons = 0, []
        def add(points, reason):
            nonlocal score
            score += points
            reasons.append(reason)
        if page_match:
            if _ps_equal(needle, title_lower) or _ps_equal(needle, url_lower): add(140, 'exact_page_match')
            elif needle in title_lower or needle in url_lower: add(105, 'substring_page_match')
            else: add(-100, 'page_match_miss')
        kind_lower = _invariant_lower(kind)
        if kind_lower == 'page': add(45, 'type_page')
        elif kind_lower == 'webview': add(42, 'type_webview')
        elif kind_lower == 'iframe': add(-20, 'type_iframe')
        elif kind_lower in ('worker', 'service_worker'): add(-60, 'type_worker')
        if title: add(12, 'has_title')
        if url_lower.startswith('devtools://'): add(-80, 'devtools_page_penalty')
        elif url_lower.startswith(('http', 'file:', 'app:')): add(8, 'document_url')
        output.append(dict(id=page.get('id'), title=title, url=url, type=kind,
                           score=score, reasons=reasons, page=page))
    def compare(a, b):
        return (b['score'] > a['score']) - (b['score'] < a['score']) or _title_compare(a['title'], b['title'])
    return sorted(output, key=cmp_to_key(compare))


def find_page(detect: dict, page_match: str | None = '') -> tuple[dict | None, dict | None]:
    if not detect.get('available') or not detect.get('pages'):
        return None, None
    scores = score_pages(detect, page_match)
    if not scores:
        return None, None
    summarize = lambda item: {key: item[key] for key in ('id', 'title', 'url', 'type', 'score', 'reasons')}
    selected = scores[0]
    missed = bool(page_match and 'page_match_miss' in selected['reasons'])
    selection = dict(page_match=page_match or '', selected=None if missed else summarize(selected),
                     candidates=[summarize(item) for item in scores[:8]])
    return (None if missed else selected['page']), selection


def dom_bridge_plan(dom_action: str, query: str, port=9222, page_match='', text='', clear=False,
                    enter=False, *, helper=True) -> dict:
    if dom_action not in ('click', 'type', 'find'):
        raise ValueError('dom_action must be click, type, or find')
    typing = dom_action == 'type'
    read = ['macro', 'cdp-smart-type-find' if typing else 'cdp-smart-find', '--label' if typing else '--text', query]
    live = ['macro', 'cdp-smart-type' if typing else 'cdp-smart-click', '--label' if typing else '--text', query]
    if typing:
        if text: live.extend(('--text', text))
        if clear: live.append('--clear-first')
        if enter: live.append('--press-enter')
    for command in (read, live):
        command.extend(('--port', str(port)))
        if page_match: command.extend(('--page-match', page_match))
    result = dict(schema='cucp.cdp-dom-bridge-plan/v1', route='cdp_dom', dom_action=dom_action,
                  query=query, port=port, page_match=page_match or '', read_only_command=read, live_command=live)
    if helper:
        hints = [('playwright_label', 'page.getByLabel(<query>)', 100),
                 ('playwright_placeholder', 'page.getByPlaceholder(<query>)', 92),
                 ('css_textbox', "[role='textbox'], input, textarea, [contenteditable='true']", 70)] if typing else [
                 ('playwright_role_button', "page.getByRole('button', { name: <query> })", 100),
                 ('playwright_role_link', "page.getByRole('link', { name: <query> })", 88),
                 ('playwright_text', 'page.getByText(<query>)', 72)]
        result['locator_hints'] = [dict(kind=k, template=t, priority=p) for k, t, p in hints]
    result['selector_ranking'] = [dict(signal=s, priority=p) for s, p in (
        ('test_id_or_data_attr', 100), ('aria_label_or_label_control', 94),
        ('role_plus_accessible_name', 90), ('placeholder_or_name', 82), ('visible_text', 70), ('css_fallback', 50))]
    result['fallback_order'] = ['cdp_dom', 'uia_pattern', 'ocr_uia', 'target_validate_precision_point', 'vision']
    return result


@dataclass(frozen=True)
class LegacyCdpMacro:
    action: str
    port: int
    args: dict


def prepare_macro(action: str, argv: list[str], *, allow_live_control=False) -> LegacyCdpMacro:
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError('unsupported legacy CDP action')
    if type(allow_live_control) is not bool:
        raise ValueError('allow_live_control must be boolean startup authority')
    if action in LIVE_ACTIONS and not allow_live_control:
        raise PermissionError(f'macro {action} requires -AllowLiveControl')
    if not isinstance(argv, list) or any(not isinstance(v, str) for v in argv):
        raise ValueError('argv must be an array of strings')
    def opt(name):
        return next((argv[i + 1] for i, item in enumerate(argv[:-1]) if item.lower() == name), '')
    def switch(name):
        return name in [item.lower() for item in argv]
    port_text = opt('--port')
    try:
        port = int(port_text or '0')
        if not -(2**31) <= port < 2**31: raise ValueError('32-bit integer overflow')
    except ValueError:
        if action not in ('cdp-deep-find', 'cdp-prosemirror-insert'): raise
        port = 9222
    if port <= 0 and action != 'cdp-prosemirror-insert': port = 9222
    if not port_text and action == 'cdp-prosemirror-insert': port = 9222
    args = dict(page_match=opt('--page-match'))
    if action == 'cdp-eval':
        args.update(expression=opt('--expr'), expression_b64=opt('--expr-b64'))
        if not args['expression'] and not args['expression_b64']:
            raise ValueError('macro cdp-eval requires --expr or --expr-b64')
    if action in ('cdp-click', 'cdp-type', 'cdp-prosemirror-insert'):
        args['selector'] = opt('--selector')
        if not args['selector']:
            suffix = " (CSS, e.g. '.ProseMirror')" if action == 'cdp-prosemirror-insert' else ''
            raise ValueError(f'macro {action} requires --selector{suffix}')
    if 'smart' in action or action == 'cdp-deep-find':
        label = action in ('cdp-smart-type', 'cdp-smart-type-find')
        name = '--label' if label else '--text'
        args['needle'] = opt(name)
        if not args['needle']: raise ValueError(f'macro {action} requires {name}')
    if action in ('cdp-type', 'cdp-smart-type', 'cdp-prosemirror-insert'):
        args.update(text=opt('--text'))
        if action != 'cdp-prosemirror-insert':
            args.update(clear=switch('--clear-first'), enter=switch('--press-enter'))
        if action == 'cdp-smart-type' and not any((args['text'], args['clear'], args['enter'])):
            raise ValueError('macro cdp-smart-type requires --text or --clear-first/--press-enter')
        if action == 'cdp-prosemirror-insert' and not args['text']:
            raise ValueError('macro cdp-prosemirror-insert requires --text')
    return LegacyCdpMacro(action, port, args)


def native_arguments(macro: LegacyCdpMacro) -> list[str]:
    """Exact legacy Invoke-NativeHelper argv; host may retain this acquisition seam."""
    action, a = macro.action, macro.args
    if action == 'cdp-prosemirror-insert':
        result=['-Action',action,'-CdpSelector',a['selector'],'-CdpText',a['text'],'-CdpPort',str(macro.port)]
    else:
        result=['-Action',action]
        if action in ('cdp-type','cdp-click'): result.extend(('-CdpSelector',a['selector']))
        if 'smart' in action or action=='cdp-deep-find': result.extend(('-CdpText',a['needle']))
        result.extend(('-CdpPort',str(macro.port)))
        if action=='cdp-eval':
            result.extend(('-CdpExpr',a['expression']) if a.get('expression') else ('-CdpExprB64',a['expression_b64']))
        if action in ('cdp-type','cdp-smart-type') and a.get('text'): result.extend(('-Text',a['text']))
    if a.get('page_match'): result.extend(('-CdpPageMatch',a['page_match']))
    if a.get('enter'): result.append('-PressEnter')
    if a.get('clear'): result.append('-ClearFirst')
    return result


def prepare_native(argv: list[str]) -> LegacyCdpMacro:
    """Closed native argv parser: option-looking values are consumed only as data.

    Authority is deliberately absent from this grammar. The trusted host passes
    its existing startup authority separately when executing the resulting frame.
    """
    if not isinstance(argv, list) or len(argv) > 64 or any(not isinstance(v, str) or len(v) > 65536 for v in argv):
        raise ValueError('native argv must be a bounded array of strings')
    names = {'-action':'action','-cdpport':'port','-cdppagematch':'page_match',
             '-cdpexpr':'expression','-cdpexprb64':'expression_b64','-cdpselector':'selector',
             '-cdptext':'needle','-text':'text','-clearfirst':'clear','-pressenter':'enter'}
    values = {}
    index = 0
    while index < len(argv):
        token = argv[index].lower()
        if token not in names:
            raise ValueError('unsupported native CDP parameter')
        key = names[token]
        if key in values:
            raise ValueError('duplicate native CDP parameter')
        if key in ('clear','enter'):
            values[key] = True
            index += 1
        else:
            if index + 1 >= len(argv):
                raise ValueError('native CDP parameter requires a value')
            values[key] = argv[index + 1]
            index += 2
    action = values.pop('action', '')
    if action not in ACTIONS:
        raise ValueError('unsupported native CDP action')
    try:
        port = int(values.pop('port', '9222'))
    except ValueError as exc:
        raise ValueError('native CDP port must be an integer') from exc
    if not 1 <= port <= 65535:
        raise ValueError('native CDP endpoint port is outside 1..65535')
    if action == 'cdp-prosemirror-insert':
        values['text'] = values.pop('needle', '')
    from .legacy_cdp import _ARGUMENTS
    if values.keys() - (_ARGUMENTS[action] | {'page_match'}):
        raise ValueError('native parameter is not supported by this CDP action')
    return LegacyCdpMacro(action, port, values)
