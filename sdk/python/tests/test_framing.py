import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_chat_core_client.framing import decode_frame, encode_frame


@pytest.mark.parametrize("value", [
    b'{"a":1,"a":2}\n', b'{"a":1,"\\u0061":2}\n', b'{"x":1e999}\n',
    b'{"x":9007199254740992}\n', b'{"x":"\\ud800"}\n', b'{"x":"\xff"}\n',
    b'{}', b'{}\n{}\n', b'[' * 17 + b']' * 17 + b'\n',
])
def test_ambiguous_or_nonportable_frames_are_rejected(value):
    with pytest.raises((TypeError, ValueError)):
        decode_frame(value)


def test_roundtrip_unicode_and_literal_brackets_is_portable():
    value = {"text": "é → []{}", "integer": 9007199254740991}
    assert decode_frame(encode_frame(value)) == value
