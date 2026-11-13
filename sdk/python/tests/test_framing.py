import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_chat_core_client.framing import decode_frame, decode_response, encode_frame


@pytest.mark.parametrize("value", [
    b'{"a":1,"a":2}\n', b'{"a":1,"\\u0061":2}\n', b'{"x":1e999}\n',
    b'{"x":9007199254740992}\n', b'{"x":"\\ud800"}\n', b'{"x":"\xff"}\n',
    b'{}', b'{}\n{}\n',
])
@pytest.mark.parametrize("decoder", [decode_frame, decode_response])
def test_ambiguous_or_nonportable_frames_are_rejected(value, decoder):
    with pytest.raises((TypeError, ValueError)):
        decoder(value)


def test_response_vectors_keep_request_limits_and_malformed_rejections():
    import json
    vectors = json.loads((Path(__file__).resolve().parents[3] /
        "contracts/core-api/response-framing-vectors-v1.json").read_text())
    for value in vectors["valid_results"].values():
        wire = json.dumps(value).encode() + b"\n"
        assert decode_response(wire) == value
        with pytest.raises(ValueError): decode_frame(wire)
        with pytest.raises(ValueError): encode_frame(value)
    for wire in vectors["invalid_frames"]:
        with pytest.raises(ValueError): decode_response(wire.encode())


def test_response_byte_ceiling_and_parser_capacity_fail_closed(monkeypatch):
    from mesh_chat_core_client import framing
    from mesh_chat_core_client.limits import MAX_FRAME_BYTES
    exact = b'{}' + b' ' * (MAX_FRAME_BYTES - 3) + b'\n'
    assert decode_response(exact) == {}
    with pytest.raises(ValueError): decode_response(exact[:-1] + b' \n')
    def exhausted(*args, **kwargs): raise RecursionError("parser capacity")
    monkeypatch.setattr(framing.json, "loads", exhausted)
    with pytest.raises(ValueError, match="parser capacity"): decode_response(b'{}\n')


def test_roundtrip_unicode_and_literal_brackets_is_portable():
    value = {"text": "é → []{}", "integer": 9007199254740991}
    assert decode_frame(encode_frame(value)) == value
