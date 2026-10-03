"""Strict host half of the existing legacy execution wire protocol.

This is not the modern native ``serve`` protocol. Authority is constructor-only;
wire values never grant it. No shell, effect dispatch, or reducer lives here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
from typing import Any

CHUNK_BYTES = 49152
MAX_FRAME_CHARACTERS = 66000
MAX_STARTUP_BYTES = 32 * 1024 * 1024
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
FAMILIES = {
    'execution': ('legacy-execution-session', 'cucp.execution-start/v1'),
    'interaction': ('legacy-interaction-session', 'cucp.interaction-start/v1'),
    'diagnostics': ('legacy-diagnostic-session', 'cucp.diagnostic-start/v1'),
}
EFFECT_KINDS = frozenset('WorkflowPlan Child Native LocalMacro CdpPort HistoryRead HistoryAppend '
    'TrajectoryAppend Sleep Clock Timestamp CachePath FileExists RemoveFile SendEscape Console '
    'Appshot Win32Windows UIAffordances Cucp Vision HitTestPoint PointCacheRead PointCacheWrite '
    'CoordProfile AnchorScore AnchorAppend Notice PipelineOutput ObservationId Diagnostic'.split())


class LegacyHostError(RuntimeError):
    def __init__(self, message, *, uncertain=False):
        self.uncertain = bool(uncertain)
        super().__init__(('mutation_may_have_occurred=true; automatic_retry=false; ' if uncertain else '') + message)


def require(condition, message):
    if not condition:
        raise LegacyHostError(message)


def exact(value, names):
    require(type(value) is dict and set(value) == set(names), 'Unexpected legacy protocol fields.')


def _pairs(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'Duplicate legacy JSON property.')
        result[name] = value
    return result


def parse_json(raw):
    try:
        # json.loads(bytes) auto-detects UTF-16/32; this ABI is UTF-8 only.
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode('utf-8', errors='strict')
        require(type(raw) is str, 'Legacy JSON input must be UTF-8 text.')
        return json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(LegacyHostError('Nonfinite legacy JSON number.')))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise LegacyHostError('Invalid legacy JSON.') from error


def json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    except (ValueError, TypeError, RecursionError) as error:
        raise LegacyHostError('Legacy value could not be encoded.') from error


def wire(value, depth=0):
    require(depth <= 100, 'Legacy value nesting exceeds the wire depth.')
    if value is None or type(value) in (str, bool, int, float):
        require(type(value) is not float or math.isfinite(value), 'Nonfinite legacy scalar.')
        return {'kind': 'scalar', 'value': value}
    if type(value) is list:
        return {'kind': 'array', 'items': [wire(item, depth + 1) for item in value]}
    require(type(value) is dict and all(type(key) is str for key in value), 'Unsupported legacy value type.')
    return {'kind': 'object', 'properties': [{'name': key, 'value': wire(item, depth + 1)} for key, item in value.items()]}


def unwire(value, depth=0):
    require(depth <= 100 and type(value) is dict, 'Invalid legacy tagged value.')
    kind = value.get('kind')
    if kind == 'scalar':
        exact(value, ('kind', 'value'))
        scalar = value['value']
        require(scalar is None or type(scalar) in (str, bool, int, float), 'Invalid legacy scalar.')
        require(type(scalar) is not float or math.isfinite(scalar), 'Nonfinite legacy scalar.')
        return scalar
    if kind == 'array':
        exact(value, ('kind', 'items'))
        require(type(value['items']) is list, 'Invalid legacy array.')
        return [unwire(item, depth + 1) for item in value['items']]
    require(kind == 'object', 'Unknown legacy wire tag.')
    exact(value, ('kind', 'properties'))
    require(type(value['properties']) is list, 'Invalid legacy object.')
    result = {}
    # The retained host uses an ordered, case-insensitive dictionary. Reject
    # colliding property names instead of silently dropping or unwrapping data.
    seen = set()
    for item in value['properties']:
        exact(item, ('name', 'value'))
        name = item['name']
        require(type(name) is str and name.casefold() not in seen, 'Invalid or duplicate legacy wire property.')
        seen.add(name.casefold())
        result[name] = unwire(item['value'], depth + 1)
    return result


def frames(value, sequence, *, startup=False):
    """Preflight the whole reply before writing its first frame; no report cap."""
    data = json_bytes(value)
    require(not startup or len(data) <= MAX_STARTUP_BYTES, 'Legacy startup exceeds 32 MiB.')
    return [json_bytes({'kind': 'part', 'id': sequence, 'data': base64.b64encode(data[i:i + CHUNK_BYTES]).decode('ascii')}) + b'\n'
            for i in range(0, len(data), CHUNK_BYTES)] + [json_bytes({'kind': 'end', 'id': sequence}) + b'\n']


@dataclass(frozen=True)
class Authority:
    live: bool = False
    sensitive: bool = False

    def __post_init__(self):
        require(type(self.live) is bool and type(self.sensitive) is bool, 'Authority ceilings must be booleans.')

    def restrict(self, live, sensitive):
        require(type(live) is bool and type(sensitive) is bool, 'Child authority must be boolean.')
        require(not live or self.live, 'Child exceeds immutable live startup authority.')
        require(not sensitive or self.sensitive, 'Child exceeds immutable sensitive startup authority.')
        return Authority(self.live and live, self.sensitive and sensitive)


@dataclass(frozen=True)
class Effect:
    kind: str
    name: str
    argv: tuple[str, ...]
    data: Any
    live: bool
    quiet: bool
    brief: bool
    confirm_sensitive: bool

    @classmethod
    def decode(cls, value, authority):
        exact(value, ('kind', 'name', 'argv', 'data', 'live', 'quiet', 'brief', 'confirm_sensitive'))
        require(type(value['kind']) is str and value['kind'] in EFFECT_KINDS and type(value['name']) is str,
                'Unknown legacy effect descriptor.')
        require(type(value['argv']) is list and all(type(item) is str for item in value['argv']), 'Effect argv must contain strings.')
        require(all(type(value[name]) is bool for name in ('live', 'quiet', 'brief', 'confirm_sensitive')), 'Effect flags must be booleans.')
        authority.restrict(value['live'], value['confirm_sensitive'])
        return cls(value['kind'], value['name'], tuple(value['argv']), unwire(value['data']),
                   value['live'], value['quiet'], value['brief'], value['confirm_sensitive'])

    def may_change_state(self):
        """Mirror the existing managed outcome classification; never a grant."""
        if self.live or self.kind in {'Child', 'Native', 'HistoryAppend', 'TrajectoryAppend', 'RemoveFile',
                'PointCacheWrite', 'AnchorAppend', 'Appshot', 'Vision', 'Notice', 'Cucp'}:
            return True
        if self.kind == 'LocalMacro':
            return self.name != 'icon-find'
        if self.kind == 'Diagnostic':
            if self.name in {'AuditProbe', 'ClearAppshotCache', 'Appshot', 'Notice', 'HelperUp', 'AssertAuthorized', 'Cli', 'Native'}:
                return True
            if self.name == 'Macro' and type(self.data) is dict:
                return self.data.get('name') in {'health-quick', 'find-label'} or (self.data.get('name') == 'windows' and self.argv == ('--rich',))
        return False


def completion(message, family):
    exact(message, ('payload', 'exit', 'json_depth', 'brief', 'emit_json'))
    require(type(message['exit']) is int and INT32_MIN <= message['exit'] <= INT32_MAX and
            (family == 'interaction' or 0 <= message['exit'] <= 3), 'Invalid legacy completion exit.')
    require(type(message['json_depth']) is int and 0 <= message['json_depth'] <= 100 and
            type(message['emit_json']) is bool and (message['brief'] is None or type(message['brief']) is str),
            'Invalid legacy completion output.')
    return {**message, 'payload': unwire(message['payload'])}
