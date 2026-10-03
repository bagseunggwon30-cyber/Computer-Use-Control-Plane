"""File OCR compatibility entry point using the shared migrated text matcher."""
from __future__ import annotations
from typing import Any
from .native_host import run_native
from .observation_processing import match_ocr_candidates, score_ocr_text


def _score_text(needle: str, candidate: str, mode: str) -> int:
    return score_ocr_text(needle, candidate, mode)


def ocr_find_text(path: str, text: str, match: str = 'contains', language: str | None = None) -> tuple[int, dict[str, Any]]:
    route = {'primary': 'python-router', 'observation': 'dotnet-native-host/ocr-image', 'fallback': None}
    base = {'schema': 'pcucp.ocr-find-text/v1', 'kind': 'ocr-find-text', 'query': {'text': text, 'match': match},
            'route': route, 'matching_engine': 'legacy-compatible-python/v2', 'automatic_action': False}
    try:
        match_ocr_candidates({}, text, match)  # Validate text/mode before native work.
    except ValueError as exc:
        return 2, {**base, 'status': 'error', 'top': None, 'candidates': [], 'errors': [str(exc)]}
    native_args = ['--path', path]
    if language:
        native_args += ['--language', language]
    code, payload, error = run_native('ocr-image', native_args)
    if payload is None:
        return code or 1, {**base, 'status': 'error', 'top': None, 'candidates': [], 'errors': [error]}
    if code != 0 or payload.get('status') != 'ok':
        return code or 1, {**base, 'status': 'error', 'top': None, 'candidates': [],
                          'errors': payload.get('errors', []) or [error or 'OCR provider did not complete successfully'],
                          'provider_status': payload.get('status'), 'provider_exit_code': code}
    body = payload.get('data', payload)
    try:
        matches = match_ocr_candidates(body, text, match)
    except ValueError as exc:
        return 2, {**base, 'status': 'error', 'top': None, 'candidates': [], 'errors': [str(exc)]}
    return (0 if matches['status'] == 'ok' else 2), {**base, **matches,
        'ocr': {k: body.get(k) for k in ('engine_language', 'line_count', 'word_count')},
        'errors': [] if matches['candidates'] else ['no_text_match']}
