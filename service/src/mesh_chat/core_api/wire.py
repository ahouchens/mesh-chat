"""One framed connection to an already authenticated, host-bound session.

No socket listener, identity selection, retry policy or runtime ownership lives
here. Hosts own binary streams, their access controls, deadlines and worker limits.
"""

from threading import RLock
from typing import Protocol

from .limits import MAX_FRAME_BYTES
from .requests import REQUEST_ID
from .wire_codec import decode_frame, encode_frame


class RequestSession(Protocol):
    @property
    def stopped(self): ...
    def request(self, value): ...
    def detach(self): ...


def _error(code, request_id=None):
    return {"api_version": 1, "request_id": request_id, "ok": False,
            "error": {"code": code, "retry_after_ms": None}}


def _correlation(value):
    identifier = value.get("request_id") if isinstance(value, dict) else None
    return identifier if isinstance(identifier, str) and REQUEST_ID.fullmatch(identifier) else None


class FramedSession:
    def __init__(self, session: RequestSession):
        self._session = session
        self._closed = False
        self._lock = RLock()

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._session.detach()

    def exchange(self, frame):
        with self._lock:
            if self._closed:
                return encode_frame(_error("unauthenticated"))
            try:
                value = decode_frame(frame)
            except (ValueError, TypeError, RecursionError):
                self.close()
                return encode_frame(_error("invalid_request"))
            try:
                return encode_frame(self._session.request(value))
            except Exception:
                self.close()
                return encode_frame(_error("internal", _correlation(value)))

    def serve(self, reader, writer):
        """Drive one binary stream serially, without queuing work or responses.

        Blocking I/O occurs outside the facade's service dispatch lock. If a
        reply cannot be written, do not execute another request or retry a write
        at the domain layer: the caller must resolve that unknown outcome.
        """
        try:
            while not self._closed:
                frame = reader.readline(MAX_FRAME_BYTES + 1)
                if frame == b"":
                    return
                response = self.exchange(frame)
                self._write(writer, response)
                if self._session.stopped:
                    return
        finally:
            self.close()

    @staticmethod
    def _write(writer, response):
        remaining = memoryview(response)
        while remaining:
            count = writer.write(remaining)
            if type(count) is not int or not 0 < count <= len(remaining):
                raise OSError("Response stream did not accept the frame")
            remaining = remaining[count:]
        writer.flush()
