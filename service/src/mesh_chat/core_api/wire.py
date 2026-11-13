"""One framed connection to an already authenticated, host-bound session.

No socket listener, identity selection, retry policy or runtime ownership lives
here. Hosts own binary streams, their access controls, deadlines and worker limits.
"""

from threading import RLock
from typing import Protocol

from .limits import MAX_FRAME_BYTES
from .requests import REQUEST_ID
from .wire_codec import decode_frame, encode_frame
from .._qualification_failure_observer import note


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

    @property
    def stopped(self):
        return bool(getattr(self._session, "stopped", False))

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
                note("discard")
                self.close()
                return encode_frame(_error("invalid_request"))
            operation = value.get("operation") if isinstance(value, dict) else None
            note("frame", _correlation(value), operation)
            stage = "session_escape"
            try:
                result = self._session.request(value)
                stage = "frame_encode"
                response = encode_frame(result)
                # Inspect only selected source response scalars, never give the
                # diagnostic custody helper a public response or encoded bytes.
                try:
                    failure = result.get("error") if type(result) is dict and result.get("ok") is False else None
                    code = failure.get("code") if type(failure) is dict else None
                    note("seal", _correlation(result), code)
                except Exception:
                    note("discard")
                return response
            except Exception as error:
                note("wire_failure", error, stage)
                self.close()
                response = encode_frame(_error("internal", _correlation(value)))
                note("seal", _correlation(value), "internal")
                return response

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
