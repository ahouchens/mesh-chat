"""Strict UTF-8 JSON frames; validation happens before session dispatch."""

import json
import math

from .limits import MAX_FRAME_BYTES, MAX_REQUEST_JSON_DEPTH, MAX_REQUEST_JSON_TOKENS, MAX_SAFE_INTEGER


def decode_frame(frame):
    if (not isinstance(frame, bytes) or not frame or len(frame) > MAX_FRAME_BYTES
            or not frame.endswith(b"\n") or b"\n" in frame[:-1]):
        raise ValueError("Invalid frame boundary")
    payload = frame[:-1].decode("utf-8", errors="strict")
    _check_structure(payload)
    value = json.loads(payload, object_pairs_hook=_unique_object,
                       parse_constant=_invalid_number, parse_int=_integer, parse_float=_number)
    _check_unicode(value)
    return value


def encode_frame(value):
    frame = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError("Response frame exceeds its budget")
    return frame


def _check_structure(payload):
    depth = tokens = 0
    quoted = escaped = False
    for character in payload:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character in "{}[]:,":
            tokens += 1
            if character in "{[": depth += 1
            elif character in "}]": depth -= 1
            if not 0 <= depth <= MAX_REQUEST_JSON_DEPTH or tokens > MAX_REQUEST_JSON_TOKENS:
                raise ValueError("Request JSON exceeds its structural budget")
    if depth or quoted:
        raise ValueError("Incomplete JSON structure")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _invalid_number(_):
    raise ValueError("Non-finite JSON number")


def _integer(value):
    if len(value) > 17:
        raise ValueError("JSON integer exceeds the portable range")
    number = int(value)
    if abs(number) > MAX_SAFE_INTEGER:
        raise ValueError("JSON integer exceeds the portable range")
    return number


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _check_unicode(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            item.encode("utf-8", errors="strict")
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
