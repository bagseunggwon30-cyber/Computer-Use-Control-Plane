"""Legacy workflow assembly with exact read-only Windows syntax tokenization."""
import json
import os
import time
from pathlib import Path
from .legacy_host_protocol import exact, parse_json, require
from .legacy_process import capture
from .legacy_native_kernel import compatibility
from .legacy_cdp_contract import _ps_equal


def step_specs(rest):
    result, index = [], 0
    while index < len(rest):
        if not _ps_equal(rest[index], '--step'):
            index += 1
            continue
        parts, index = [], index + 1
        while index < len(rest) and not _ps_equal(rest[index], '--step'):
            parts.append(rest[index]); index += 1
        result.append(' '.join(parts))
    return result


def tokenize(steps, *, executable=None, culture='en-US', timeout_s=30, cancelled=None):
    from .protocol import repo_root, frozen
    default = (repo_root() / 'legacy-syntax' if frozen() else repo_root() / 'pcucp-next/bin/legacy-syntax') / 'PcuCp.LegacySyntax.exe'
    path = Path(executable or os.environ.get('CUCP_LEGACY_SYNTAX_EXE') or default)
    require(path.is_absolute() and path.name == 'PcuCp.LegacySyntax.exe' and path.is_file(), 'Published read-only syntax adapter is unavailable.')
    require(type(steps) is list and all(type(step) is str for step in steps), 'Workflow steps must be strings.')
    request = json.dumps(dict(schema='cucp.legacy-syntax/v1', steps=steps, culture=culture), ensure_ascii=False, allow_nan=False).encode('utf-8')
    code, stdout, stderr = capture([str(path)], timeout_s, input_bytes=request, native_guard=True, cancelled=cancelled)
    require(code == 0, 'Read-only workflow syntax adapter failed: ' + stderr.decode('utf-8', errors='replace'))
    result = parse_json(stdout)
    exact(result, ('schema', 'parsed_steps'))
    require(result['schema'] == 'cucp.legacy-syntax/v1' and type(result['parsed_steps']) is list and len(result['parsed_steps']) == len(steps),
            'Invalid owned syntax result.')
    for row in result['parsed_steps']:
        exact(row, ('ok', 'error', 'detail', 'tokens'))
        require(type(row['ok']) is bool and type(row['error']) is str and type(row['detail']) is str and
                type(row['tokens']) is list and all(type(word) is str for word in row['tokens']), 'Invalid syntax row.')
    return result['parsed_steps']


def workflow_plan(rest, *, syntax_executable=None, culture='en-US', timeout_s=30, cancelled=None):
    deadline = time.monotonic() + timeout_s
    parsed = tokenize(step_specs(rest), executable=syntax_executable, culture=culture, timeout_s=timeout_s, cancelled=cancelled)
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'Workflow syntax exhausted its inherited deadline; action not retried.')
    result = compatibility('workflow-plan-from-parsed', dict(rest=rest, parsed_steps=parsed), culture=culture, timeout_s=remaining, cancelled=cancelled)
    require(result.get('schema') == 'cucp.workflow-plan/v1' and result.get('status') in {'ok', 'partial'} and
            type(result.get('safe_to_run')) is bool and type(result.get('requires_sensitive_confirmation')) is bool, 'Invalid original workflow plan response.')
    return result
