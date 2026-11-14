from __future__ import annotations

import io
import struct

import pytest

from mesh_chat.errors import ValidationError
from mesh_chat.ipc import FrameWriter, MAX_FRAME_BYTES, decode_all, encode_frame, read_frame


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


def test_writer_completes_short_writes_before_reporting_success() -> None:
    class ShortStream(io.BytesIO):
        def write(self, data):
            return super().write(data[:3])
    stream = ShortStream()
    FrameWriter(stream).write({"type": "status"})
    assert decode_all(stream.getvalue()) == [{"type": "status"}]


@pytest.mark.parametrize("result", [0, None])
def test_writer_refuses_nonprogress_without_claiming_a_complete_frame(result) -> None:
    class StalledStream(io.BytesIO):
        def write(self, data):
            return result
    stream = StalledStream()
    with pytest.raises(OSError, match="incomplete"):
        FrameWriter(stream).write({"type": "status"})
    assert stream.getvalue() == b""


def test_writer_refuses_a_stall_after_a_partial_frame() -> None:
    class PartialStream(io.BytesIO):
        def write(self, data):
            if self.tell() == 0:
                return super().write(data[:3])
            return 0
    stream = PartialStream()
    with pytest.raises(OSError, match="incomplete"):
        FrameWriter(stream).write({"type": "status"})
    assert len(stream.getvalue()) == 3
    with pytest.raises(EOFError):
        read_frame(io.BytesIO(stream.getvalue()))
