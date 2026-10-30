"""Exercise private service launch and inherited routing, without a real WebView."""

import base64
import os
from queue import Queue
from threading import RLock, Thread
from types import SimpleNamespace

import pytest

from mesh_chat import __main__ as entrypoint
from mesh_chat.direct_native import NativeChannel
from mesh_chat.ipc import encode_frame


def test_private_launch_routes_adapter_replies_during_dispatch(monkeypatch):
    output, events, closed = Queue(), [], []
    lock = RLock()

    class Service:
        def __init__(self, host):
            self.host = host
            self._direct_native = NativeChannel()
        def snapshot(self):
            return {}
        def native_webrtc_event(self, *event):
            events.append(event)
        def dispatch(self, request):
            with lock:
                if request["command"] == "shutdown":
                    return {"ok": True, "result": None}, True
                return {"ok": True, "result": self.host.stats("native-probe")}, False
        def close(self):
            closed.append(True)

    def initialize(_request, _writer, *, desktop_transport=None):
        assert desktop_transport is not None
        return Service(desktop_transport)

    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as incoming, os.fdopen(write_fd, "wb", buffering=0) as sender:
        monkeypatch.setattr(entrypoint, "sys", SimpleNamespace(
            argv=["mesh-chat-service", "--shared-webview"], stdin=SimpleNamespace(buffer=incoming),
            stdout=SimpleNamespace(buffer=None)))
        monkeypatch.setattr(entrypoint, "FrameWriter", lambda _: SimpleNamespace(write=output.put_nowait))
        monkeypatch.setattr(entrypoint, "_initialize", initialize)
        result = []
        worker = Thread(target=lambda: result.append(entrypoint.main()), daemon=True)
        worker.start()
        try:
            sender.write(encode_frame({"id": "init", "command": "initialize"}))
            assert output.get(timeout=2)["ok"]
            sender.write(encode_frame({"id": "probe", "command": "probe"}))
            request = output.get(timeout=2)
            assert request["type"] == "desktop_transport"
            assert request["request"] == {"op": "inspect", "resource": "native-probe"}
            sender.write(encode_frame({"v": 1, "type": "desktop_transport_event", "epoch": request["epoch"],
                                      "event": "open", "resource": "native-probe", "data": ""}))
            sender.write(encode_frame({"v": 1, "type": "desktop_transport_reply", "epoch": request["epoch"],
                                      "id": request["id"], "ok": True, "result": {"data_channel_state": "open"}}))
            response = output.get(timeout=2)
            assert response["id"] == "probe" and response["ok"]
            assert events == [("open", "native-probe", "")]
            sender.write(encode_frame({"id": "stop", "command": "shutdown"}))
            assert output.get(timeout=2)["id"] == "stop"
            worker.join(timeout=2)
            assert result == [0] and closed == [True]
        finally:
            sender.close()
            worker.join(timeout=2)
            assert not worker.is_alive()


@pytest.mark.parametrize("field,value", [("connection_policy", "shared-native"), ("desktop_transport", {}),
                                        ("native_webrtc_host", "desktop")])
def test_public_initialization_cannot_select_private_transport(field, value):
    from mesh_chat.errors import ValidationError
    request = {"v": 1, "command": "initialize", "payload": {
        "profile_dir": "unused", "vault_key": "unused", "parent_pid": 1, field: value}}
    with pytest.raises(ValidationError, match="payload"):
        entrypoint._initialize(request, SimpleNamespace(write=lambda _: None))


@pytest.mark.parametrize("registered", [False, True])
def test_private_initialization_selects_one_policy_owner(monkeypatch, registered):
    captured = []
    host = object() if registered else None
    monkeypatch.setattr(entrypoint, "_start_parent_watchdog", lambda _: None)
    monkeypatch.setattr(entrypoint, "VaultStore", lambda *_: object())
    def service(*_, **options):
        captured.append(options)
        return object()
    monkeypatch.setattr(entrypoint, "MeshChatService", service)
    request = {"v": 1, "command": "initialize", "payload": {
        "profile_dir": "unused", "vault_key": base64.b64encode(b"k" * 32).decode(),
        "parent_pid": 1 if os.getpid() != 1 else 2}}
    entrypoint._initialize(request, SimpleNamespace(write=lambda _: None), desktop_transport=host)
    if registered:
        assert captured[0]["connection_policy"] == "shared-native"
        assert captured[0]["native_webrtc_host"] is host
    else:
        assert set(captured[0]) == {"direct_native"}
