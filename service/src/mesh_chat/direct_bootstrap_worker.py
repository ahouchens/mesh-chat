"""Private process boundary shared by the desktop child and Android service.

The Android entry point must run in its own OS process. There is deliberately no
renderer registration, control listener, profile vault or general service dispatch.
"""
from __future__ import annotations

import base64
import json
import sys

from .direct_bootstrap import BootstrapEngine
from .contact_bootstrap import ContactBootstrapEngine
from .errors import ValidationError
from .ipc import read_frame, encode_frame

MAX_BYTES = 800 * 1024


class BootstrapWorker:
    def __init__(self, directory):
        self.directory = directory
        self.engine = None
        self.retired = False

    def dispatch(self, request):
        if not isinstance(request, dict) or set(request) != {"operation", "payload"}:
            raise ValidationError("Bootstrap request is invalid")
        operation, payload = request["operation"], request["payload"]
        schemas = {
            "initialize": {"private_identity", "peer_identity", "workspace_id", "expires_at"},
            "initialize_contact": {"private_identity", "peer_identity", "expires_at"},
            "activate": set(), "exchange": {"packets"},
            "send": {"kind", "logical_id", "document", "expires_at"}, "close": set(),
        }
        if not isinstance(operation, str) or operation not in schemas or not isinstance(payload, dict) or set(payload) != schemas[operation]:
            raise ValidationError("Bootstrap operation is invalid")
        if operation == "close":
            self.close()
            return None
        if self.retired:
            raise ValidationError("Bootstrap worker is retired")
        if operation in {"initialize", "initialize_contact"}:
            if self.engine is not None:
                raise ValidationError("Bootstrap worker already initialized")
            identities = (bytes.fromhex(payload["private_identity"]), bytes.fromhex(payload["peer_identity"]))
            if operation == "initialize":
                self.engine = BootstrapEngine(*identities, payload["workspace_id"], payload["expires_at"], directory=self.directory)
            else:
                self.engine = ContactBootstrapEngine(*identities, payload["expires_at"], directory=self.directory)
            return None
        if self.engine is None:
            raise ValidationError("Bootstrap worker is not initialized")
        if operation == "exchange":
            packets = payload["packets"]
            if (not isinstance(packets, list) or len(packets) > 32
                    or any(not isinstance(packet, str) or not 2 <= len(packet) <= 1032 for packet in packets)):
                raise ValidationError("Bootstrap packet batch is invalid")
            result = self.engine.exchange([bytes.fromhex(packet) for packet in packets])
            result["packets"] = [packet.hex() for packet in result["packets"]]
            for event in result["events"]:
                if event["kind"] == "inbound":
                    event["packed"] = base64.b64encode(event["packed"]).decode("ascii")
            return result
        return getattr(self.engine, operation)(**payload)

    def call(self, raw):
        try:
            if not isinstance(raw, str) or not 1 <= len(raw.encode("utf-8")) <= MAX_BYTES:
                raise ValidationError("Bootstrap request is too large")
            result = self.dispatch(json.loads(raw))
            response = json.dumps({"ok":True,"result":result}, separators=(",", ":"))
            if len(response.encode("utf-8")) > MAX_BYTES:
                raise ValidationError("Bootstrap response is too large")
            return response
        except Exception:
            # Any protocol or engine failure retires the dedicated interpreter.
            # Never serialize private identity, packet or endpoint exceptions.
            self.close()
            return '{"ok":false,"error":"bootstrap_unavailable"}'

    def close(self):
        self.retired = True
        engine, self.engine = self.engine, None
        if engine is not None:
            engine.close()


def main(directory=None):
    worker = BootstrapWorker(directory)
    try:
        while not worker.retired:
            request = read_frame(sys.stdin.buffer, max_bytes=MAX_BYTES)
            response = worker.call(json.dumps(request, separators=(",", ":")))
            sys.stdout.buffer.write(encode_frame(json.loads(response), max_bytes=MAX_BYTES))
            sys.stdout.buffer.flush()
    except (EOFError, OSError, ValidationError):
        pass
    finally:
        worker.close()
    return 0
