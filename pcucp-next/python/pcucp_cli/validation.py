"""Validation for the small JSON-schema subset used by the tool contracts.

Unknown schema keywords are not dynamically executed. No network schema fetching.
"""
import math


class ValidationError(ValueError):
    code = 'invalid_argument'
    status = 'error'


def validate(value, schema, *, allow_references=False, path='$', depth=0):
    if depth > 32:
        raise ValidationError('Arguments exceed maximum nesting depth')
    if allow_references and isinstance(value, dict) and set(value) == {'$ref'}:
        return
    if 'oneOf' in schema:
        successes = 0
        for option in schema['oneOf']:
            try:
                validate(value, option, allow_references=allow_references, path=path, depth=depth + 1)
                successes += 1
            except ValidationError:
                pass
        if successes != 1:
            raise ValidationError(f'{path}: expected exactly one supported shape')
        return
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise ValidationError(f'{path}: unexpected constant')
    if 'enum' in schema and not any(type(value) is type(v) and value == v for v in schema['enum']):
        raise ValidationError(f'{path}: unsupported choice')
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'integer': type(value) is int,
             'number': type(value) in (int, float) and math.isfinite(value),
             'boolean': type(value) is bool, 'null': value is None}
    if kind and not valid.get(kind, False):
        raise ValidationError(f'{path}: expected {kind}')
    if kind == 'object':
        props = schema.get('properties', {})
        if set(schema.get('required', [])) - set(value):
            raise ValidationError(f'{path}: required fields missing')
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise ValidationError(f'{path}: unknown fields')
        for key, item in value.items():
            if key in props:
                validate(item, props[key], allow_references=allow_references, path=f'{path}.{key}', depth=depth + 1)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 10000):
            raise ValidationError(f'{path}: array size out of range')
        for i, item in enumerate(value):
            validate(item, schema.get('items', {}), allow_references=allow_references, path=f'{path}[{i}]', depth=depth + 1)
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 1024 * 1024):
            raise ValidationError(f'{path}: string length out of range')
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ValidationError(f'{path}: invalid Unicode') from None
    elif kind in ('integer', 'number'):
        if not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
            raise ValidationError(f'{path}: number out of range')
