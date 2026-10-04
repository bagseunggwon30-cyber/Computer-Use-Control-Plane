"""Typed stdin entry to the existing closed C# compatibility kernels."""
import json
from . import native_host
from .legacy_host_protocol import parse_json, require
from .legacy_host_session import _coordinator_argv
from .legacy_process import capture


def ocr_match(body, needle, mode, *, culture='en-US', timeout_s=15, cancelled=None):
    request = dict(schema='cucp.legacy-ocr-match/v1', body=body, needle=needle, mode=mode, culture=culture)
    data = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    require(len(data) <= 1024 * 1024, 'Legacy OCR request exceeds 1 MiB.')
    code, stdout, stderr = capture([*_coordinator_argv(), 'legacy-ocr-match'], timeout_s,
        input_bytes=data, native_guard=True, cancelled=cancelled)
    result = parse_json(stdout)
    error = native_host._validate_payload('legacy-ocr-match', result)
    require(not error and code == 0 and result['status'] == 'ok', error or 'Legacy OCR kernel failed.')
    return result['data']['candidates']


def compatibility(operation, args, *, culture='en-US', timeout_s=15, cancelled=None):
    request = dict(schema='cucp.legacy-compat/v1', operation=operation, args=args, culture=culture)
    data = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    require(len(data) <= 1024 * 1024, 'Legacy compatibility request exceeds 1 MiB.')
    code, stdout, stderr = capture([*_coordinator_argv(), 'legacy-compat'], timeout_s,
        input_bytes=data, native_guard=True, cancelled=cancelled)
    result = parse_json(stdout)
    error = native_host._validate_payload('legacy-compat', result)
    require(not error and code == 0 and result['status'] == 'ok', error or 'Legacy compatibility kernel failed.')
    return result['data']
