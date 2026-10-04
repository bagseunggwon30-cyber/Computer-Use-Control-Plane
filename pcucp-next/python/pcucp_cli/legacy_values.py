"""Scalar conversions used at the retained wrapper's typed argument boundary."""
import math
import re
from .legacy_host_protocol import LegacyHostError


def int32(source):
    if source is None or source == '':
        return 0
    if type(source) is bool:
        return int(source)
    if type(source) is int:
        value = source
    elif type(source) is float:
        if not math.isfinite(source):
            raise LegacyHostError('Nonfinite legacy Int32 value.')
        value = round(source)
    elif type(source) is str:
        text = source.strip()
        if re.fullmatch(r'0[xX][0-9a-fA-F]+', text):
            value = int(text[2:], 16)
            if value > 0xffffffff:
                raise LegacyHostError('Legacy hexadecimal value exceeds UInt32.')
            return value if value < 0x80000000 else value - 0x100000000
        if re.fullmatch(r'[+-]?[0-9]+', text):
            value = int(text)
        elif re.fullmatch(r'[+-]?(?:[0-9]+(?:,[0-9]*)*(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', text):
            number = float(text.replace(',', ''))
            if not math.isfinite(number):
                raise LegacyHostError('Legacy floating conversion failed.')
            value = round(number)
        else:
            raise LegacyHostError('Legacy value cannot be converted to Int32.')
    else:
        raise LegacyHostError('Legacy Int32 value must be scalar.')
    if not -2147483648 <= value <= 2147483647:
        raise LegacyHostError('Legacy value exceeds Int32.')
    return value


def positive_option(rest, name, default):
    from .legacy_diagnostic_provider import option
    value = int32(option(rest, name))
    return default if value <= 0 else value
