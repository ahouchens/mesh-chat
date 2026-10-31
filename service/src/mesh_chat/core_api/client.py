"""Strict synchronous client for the private core API frame contract.

Hosts and tools supply the stream; this module never opens a socket, starts a
runtime or authenticates a caller. It exists so the production CLI and Python
tooling can use the same versioned frames as any other consumer.
"""

from .compatibility import check_capabilities
from .limits import MAX_FRAME_BYTES
from .wire_codec import decode_frame, encode_frame


class CoreClientError(Exception):
    """A typed failure from the facade or from the frame contract."""

    def __init__(self, code, request_id=None, retry_after_ms=None):
        super().__init__(code)
        self.code = code
        self.request_id = request_id
        self.retry_after_ms = retry_after_ms


class CoreClient:
    def __init__(self, readline, write):
        if not callable(readline) or not callable(write):
            raise ValueError("A core client needs stream callbacks")
        self._readline = readline
        self._write = write
        self._sequence = 0
        self._capabilities = None

    @classmethod
    def open(cls, readline, write):
        client = cls(readline, write)
        capabilities = client.request("runtime.capabilities", {})
        try:
            check_capabilities(capabilities)
        except ValueError as error:
            raise CoreClientError("incompatible_version") from error
        client._capabilities = capabilities
        return client

    @property
    def capabilities(self):
        if self._capabilities is None:
            raise CoreClientError("unauthenticated")
        return self._capabilities

    def request(self, operation, params=None, *, idempotency_key=None):
        if not isinstance(operation, str) or not operation:
            raise ValueError("Operation name is required")
        self._sequence += 1
        request_id = f"client:{self._sequence}"
        value = {"api_version": 1, "request_id": request_id, "operation": operation,
                 "params": {} if params is None else params}
        if idempotency_key is not None:
            value["idempotency_key"] = idempotency_key
        self._write(encode_frame(value))
        frame = self._readline(MAX_FRAME_BYTES + 1)
        if not frame:
            raise CoreClientError("transport_closed", request_id)
        try:
            response = decode_frame(frame)
        except (TypeError, ValueError) as error:
            raise CoreClientError("protocol", request_id) from error
        if (not isinstance(response, dict) or response.get("api_version") != 1
                or response.get("request_id") != request_id
                or type(response.get("ok")) is not bool):
            raise CoreClientError("protocol", request_id)
        if response["ok"]:
            if "result" not in response:
                raise CoreClientError("protocol", request_id)
            return response["result"]
        error = response.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise CoreClientError("protocol", request_id)
        raise CoreClientError(error["code"], request_id, error.get("retry_after_ms"))

    def profile(self, handle=None):
        profile = handle or self.capabilities["profiles"][0]
        return self.request("profile.query", {"profile": profile})

    def received(self, handle, cursor=None, limit=128):
        return self.request("message.received", {"profile": handle, "cursor": cursor, "limit": limit})

    def poll(self, handle, cursor=None, limit=128):
        return self.request("events.poll", {"profile": handle, "cursor": cursor, "limit": limit})

    def enqueue(self, handle, recipient, text, key):
        return self.request("message.enqueue",
                            {"profile": handle, "recipient": recipient, "kind": "text", "text": text},
                            idempotency_key=key)

    def acknowledge(self, handle, cursor, key):
        return self.request("events.ack", {"profile": handle, "cursor": cursor}, idempotency_key=key)

    def diagnostics(self, handle, limit=256):
        return self.request("diagnostics.query", {"profile": handle, "limit": limit})
