from __future__ import annotations

import io
import json
import struct
import threading
from typing import Any, BinaryIO

from .errors import ValidationError

IPC_VERSION = 1
# Keep this limit in sync with src-tauri/src/lib.rs. Snapshot responses include
# message history and, for groups, one delivery record per recipient. Four MiB
# leaves useful headroom for those bounded JSON snapshots without permitting an
# untrusted length prefix to trigger an unbounded allocation.
MAX_FRAME_BYTES = 4 * 1024 * 1024
HEADER = struct.Struct(">I")


def encode_frame(value: dict[str, Any], max_bytes: int = MAX_FRAME_BYTES) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not raw or len(raw) > max_bytes:
        raise ValidationError("IPC frame is empty or too large")
    return HEADER.pack(len(raw)) + raw


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("IPC stream closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO, max_bytes: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    header = _read_exact(stream, HEADER.size)
    (length,) = HEADER.unpack(header)
    if length < 2 or length > max_bytes:
        raise ValidationError("Invalid IPC frame length")
    try:
        value = json.loads(_read_exact(stream, length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Invalid IPC JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError("IPC body must be an object")
    return value


class FrameWriter:
    def __init__(self, stream: BinaryIO):
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, value: dict[str, Any]) -> None:
        frame = encode_frame(value)
        with self._lock:
            self._stream.write(frame)
            self._stream.flush()


def decode_all(data: bytes) -> list[dict[str, Any]]:
    stream = io.BytesIO(data)
    frames: list[dict[str, Any]] = []
    while stream.tell() < len(data):
        frames.append(read_frame(stream))
    return frames
