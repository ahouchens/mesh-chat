from __future__ import annotations

import io
import struct

import pytest

from mesh_chat.errors import ValidationError
from mesh_chat.ipc import MAX_FRAME_BYTES, decode_all, encode_frame, read_frame


def test_frame_round_trip_and_concatenation() -> None:
    first = {"v": 1, "id": "a", "command": "snapshot", "payload": {}}
    second = {"type": "event", "event": "state_changed"}
    assert decode_all(encode_frame(first) + encode_frame(second)) == [first, second]


def test_frame_supports_snapshot_larger_than_legacy_limit() -> None:
    snapshot = {
        "type": "response",
        "result": {"messages": [{"text": "x" * (128 * 1024)}]},
    }
    encoded = encode_frame(snapshot)
    assert len(encoded) > 64 * 1024
    assert read_frame(io.BytesIO(encoded)) == snapshot


def test_encoder_retains_an_explicit_upper_bound() -> None:
    with pytest.raises(ValidationError):
        encode_frame({"payload": "x" * MAX_FRAME_BYTES})


@pytest.mark.parametrize(
    "raw",
    [
        struct.pack(">I", 0),
        struct.pack(">I", MAX_FRAME_BYTES + 1),
        struct.pack(">I", 2) + b"[]",
        struct.pack(">I", 2) + b"\xff\xff",
    ],
)
def test_rejects_invalid_frames(raw: bytes) -> None:
    with pytest.raises(ValidationError):
        read_frame(io.BytesIO(raw))


def test_rejects_truncated_frame() -> None:
    with pytest.raises(EOFError):
        read_frame(io.BytesIO(struct.pack(">I", 20) + b"{}"))
