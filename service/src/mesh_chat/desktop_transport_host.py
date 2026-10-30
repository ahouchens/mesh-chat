"""Private WebView transport binding over the app-owned inherited pipe.

The host implements the existing native mechanism contract. It cannot select
peers, verify consent, sign documents or decide reconnect policy.
"""

import base64
import json
import re
from collections import deque
from concurrent.futures import Future, TimeoutError
from threading import Condition, Thread
from uuid import uuid4

from .errors import NativeUnavailable, ValidationError
from .native_carrier_evidence import validate_inventory


MAX_FRAME_BYTES = 256 * 1024
EVENTS = frozenset({"open", "closed", "ice", "channel", "signaling", "gathering", "message", "control"})


def _encode(value):
    try:
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) <= MAX_FRAME_BYTES:
            return encoded
    except (ValueError, TypeError):
        pass
    raise ValidationError("Desktop transport frame is invalid")


class DesktopTransportHost:
    def __init__(self, send, event, *, timeout=30):
        if not 0 < timeout <= 30:
            raise ValueError("Desktop transport timeout is invalid")
        self._send = send
        self._event = event
        self._timeout = timeout
        self._epoch = uuid4().hex
        self._sequence = 0
        self._condition = Condition()
        self._pending = {}
        self._outgoing = deque()
        self._closed = False
        self._adapter_epoch = None
        # One bounded writer prevents a stalled pipe from defeating deadlines
        # or accumulating a thread per blocked request.
        self._writer = Thread(target=self._write, daemon=True, name="mesh-chat-desktop-transport")
        self._writer.start()

    def createOffer(self, resource, ice, channels):
        result = self._request("createOffer", options=self._options(resource, ice, channels))
        return self._description(result)

    def acceptOffer(self, resource, offer, ice, channels):
        result = self._request("acceptOffer", options=self._options(resource, ice, channels), offer=offer)
        return self._description(result)

    def applyAnswer(self, resource, answer):
        self._request("applyAnswer", resource=resource, answer=answer)
        return '{"ok":true}'

    def stats(self, resource):
        result = self._request("inspect", resource=resource)
        if not isinstance(result, dict):
            raise NativeUnavailable("Desktop transport resource is unavailable")
        return _encode({"ok": True, "result": result})

    def inventory(self):
        result = self._request("inventory")
        try:
            inventory = validate_inventory(result)
            with self._condition:
                if self._closed or self._adapter_epoch not in (None, inventory["adapter_epoch"]):
                    raise NativeUnavailable("Desktop transport adapter identity changed")
                self._adapter_epoch = inventory["adapter_epoch"]
            return inventory
        except NativeUnavailable:
            self.shutdown()
            raise

    def send(self, resource, packet):
        if not isinstance(packet, (bytes, bytearray)) or not 1 <= len(packet) <= 1064:
            return False
        encoded = base64.b64encode(packet).decode("ascii")
        return self._acknowledged(self._request("send", resource=resource, packet=encoded))

    def sendControl(self, resource, label, text):
        return self._acknowledged(self._request("sendControl", resource=resource, label=label, text=text))

    def close(self, resource):
        self._request("close", resource=resource)

    def activate(self, resource):
        self._request("activate", resource=resource)

    @staticmethod
    def _options(resource, ice, channels):
        try:
            return {"resource": resource, "ice": json.loads(ice), "channels": json.loads(channels)}
        except (TypeError, ValueError) as error:
            raise ValidationError("Desktop transport configuration is invalid") from error

    @staticmethod
    def _description(result):
        if (not isinstance(result, dict) or set(result) != {"sdp", "fingerprint"}
                or not all(isinstance(value, str) and value for value in result.values())):
            raise NativeUnavailable("Desktop transport description is invalid")
        return _encode({"ok": True, **result})

    @staticmethod
    def _acknowledged(result):
        if type(result) is not bool:
            raise NativeUnavailable("Desktop transport acknowledgment is invalid")
        return result

    def _frame(self, operation, **payload):
        self._sequence += 1
        return {"v": 1, "type": "desktop_transport", "epoch": self._epoch,
                "id": str(self._sequence), "request": {"op": operation, **payload}}

    def _request(self, operation, **payload):
        future = Future()
        with self._condition:
            if self._closed:
                raise NativeUnavailable("Desktop transport channel is closed")
            if len(self._pending) >= 16:
                raise NativeUnavailable("Desktop transport capacity exhausted")
            frame = self._frame(operation, **payload)
            _encode(frame)
            self._pending[frame["id"]] = future
            self._outgoing.append(frame)
            self._condition.notify()
        try:
            return future.result(timeout=self._timeout)
        except TimeoutError as error:
            self.shutdown()
            raise NativeUnavailable("Desktop transport request timed out") from error
        finally:
            with self._condition:
                self._pending.pop(frame["id"], None)

    def _write(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._outgoing or self._closed)
                if not self._outgoing:
                    return
                frame = self._outgoing.popleft()
            try:
                self._send(frame)
            except Exception:
                self.shutdown()
                return
            if frame["request"]["op"] == "reset":
                return

    def receive(self, value):
        if (isinstance(value, dict) and isinstance(value.get("epoch"), str)
                and re.fullmatch(r"[a-f0-9]{32}", value["epoch"]) and value["epoch"] != self._epoch):
            return False
        try:
            self._validate(value)
        except ValidationError:
            self.shutdown()
            raise
        if value["type"] == "desktop_transport_fault":
            self.shutdown()
            return True
        with self._condition:
            if self._closed:
                return False
            if value["type"] == "desktop_transport_reply":
                future = self._pending.pop(value["id"], None)
                if future is None:
                    return False
                if value["ok"]:
                    future.set_result(value["result"])
                else:
                    future.set_exception(NativeUnavailable("Desktop transport operation failed"))
                return True
        try:
            self._event(value["event"], value["resource"], value["data"])
        except Exception:
            self.shutdown()
            raise NativeUnavailable("Desktop transport observation failed") from None
        return True

    @staticmethod
    def _validate(value):
        _encode(value)
        if (not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1
                or not isinstance(value.get("epoch"), str) or not re.fullmatch(r"[a-f0-9]{32}", value["epoch"])):
            raise ValidationError("Desktop transport version is invalid")
        if value.get("type") == "desktop_transport_fault" and set(value) == {"v", "type", "epoch"}:
            return
        if value.get("type") == "desktop_transport_reply":
            if (set(value) == {"v", "type", "epoch", "id", "ok", "result"}
                    and isinstance(value["id"], str) and len(value["id"]) <= 128
                    and type(value["ok"]) is bool):
                return
        elif value.get("type") == "desktop_transport_event":
            if (set(value) == {"v", "type", "epoch", "event", "resource", "data"}
                    and isinstance(value["event"], str) and value["event"] in EVENTS
                    and isinstance(value["resource"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["resource"])
                    and isinstance(value["data"], str)
                    and len(value["data"]) <= (1500 if value["event"] == "message" else 90000)):
                return
        raise ValidationError("Desktop transport response is invalid")

    def shutdown(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            pending, self._pending = self._pending, {}
            self._outgoing.clear()
            self._outgoing.append(self._frame("reset"))
            for future in pending.values():
                future.set_exception(NativeUnavailable("Desktop transport channel is closed"))
            self._condition.notify_all()
        # Existing ingress turns this into a sticky owner quarantine. Never
        # acquire the service dispatch lock on the private reader/writer thread.
        try:
            self._event("overflow", "", "")
        except Exception:
            pass
