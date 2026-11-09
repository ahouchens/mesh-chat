"""Ordinary composition with actual Vault/Core; OS protection and pipe are doubles."""
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from mesh_chat import app_owned_host as host
from mesh_chat.core_api import host as core_host
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.errors import ValidationError
from mesh_chat.service import MeshChatService, NativeStartupIncomplete
from mesh_chat.vault import VaultStore


def config(directory):
    return host.AppOwnedConfig(directory, r"\\.\pipe\mesh-chat-independent-test", r"C:\App\node.exe", 42)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    opened, shutdown, keys = [], [], {}
    def key(directory):
        return keys.setdefault(directory, os.urandom(32))
    def native(notify):
        return SimpleNamespace(createOffer=lambda *_: None, acceptOffer=lambda *_: None,
            applyAnswer=lambda *_: None, send=lambda *_: False, sendControl=lambda *_: False,
            stats=lambda *_: None, close=lambda *_: None, shutdown=lambda: shutdown.append(True))
    class Endpoint:
        def __init__(self, name, options):
            self.name, self.config, self.closed = name, options, False
        def start(self, service): self.service = service
        def close(self): self.closed = True
    def start(directory=tmp_path, service_factory=MeshChatService):
        try:
            value = host.AppOwnedRuntime(config(directory), key_loader=key,
                store_factory=lambda *args: VaultStore(*args, allow_unprotected_for_tests=True),
                host_factory=native, endpoint_factory=Endpoint, service_factory=service_factory)
        except host.AppOwnedStartupIncomplete as error:
            opened.append(error.runtime)
            raise
        opened.append(value)
        return value
    yield start, shutdown, tmp_path
    for value in opened:
        assert value.close()


def exchange(session, operation, params=None, key=None):
    request = {"api_version": 1, "request_id": "independent:test", "operation": operation,
        "params": params or {}}
    if key is not None: request["idempotency_key"] = key
    return decode_frame(session.exchange(encode_frame(request)))


def test_fresh_host_is_empty_and_only_public_core_can_create_identity(runtime):
    start, shutdown, directory = runtime
    value = start()
    assert value.store.profile_dir == directory / "mesh-core-runtime" / "profile-v1"
    assert value.service._identity is None and value.store.list("contact") == []
    options = value.endpoint.config
    assert options.scope == "owner" and options.private_profile_bootstrap
    assert not options.private_native and not options.private_composer_legacy
    session = core_host.bind_host_stream(value.service, caller=options.caller,
        permissions=options.permissions, scope=options.scope,
        private_native=options.private_native, private_composer_legacy=options.private_composer_legacy,
        private_profile_bootstrap=options.private_profile_bootstrap)
    try:
        assert exchange(session, "runtime.capabilities")["ok"]
        denied = exchange(session, "native.command", {"command": "native_webrtc_offer", "payload": {}})
        assert not denied["ok"] and value.service._identity is None
        assert exchange(session, "profile.create", {"display_name": "Independent"}, "explicit-profile-key")["ok"]
        identity = value.store.get("identity", "local")
    finally:
        session.close()
    assert value.close() and value.store._key is None and shutdown == [True]
    reopened = start()
    assert reopened.store.get("identity", "local") == identity
    assert reopened.store.list("contact") == []


def test_deferred_retirement_retains_key_and_exclusive_owner_until_ack(runtime):
    start, shutdown, _ = runtime
    value = start()
    original = value.service.close
    value.service.close = lambda: value.service._shutdown.set()
    assert value.close() is False and value.store._key is not None and shutdown == []
    with pytest.raises(host.AppOwnedStartupIncomplete): start()
    value.service.close = original
    assert value.close() and value.store._key is None and shutdown == [True]
    assert start().service._identity is None


def test_incomplete_constructor_keeps_exact_service_and_key_owner(runtime):
    start, shutdown, _ = runtime
    def fail(*args, **kwargs):
        service = MeshChatService(*args, **kwargs)
        raise NativeStartupIncomplete(service)
    with pytest.raises(host.AppOwnedStartupIncomplete) as raised:
        start(service_factory=fail)
    value = raised.value.runtime
    assert value.service.store is value.store and value.store._key is not None
    assert value.close() and value.store._key is None and shutdown == [True]


@pytest.mark.parametrize("data", [b"", b'{"command":"native_webrtc_offer"}'])
def test_normal_launch_accepts_only_eof_and_returns_selected_status(tmp_path, monkeypatch, data):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
        "MESH_CHAT_CORE_API_PIPE": config(tmp_path).pipe,
        "MESH_CHAT_CORE_API_CLIENT_IMAGE": config(tmp_path).client_image, "MESH_CHAT_APP_PARENT_PID": "42"}
    messages, parents, closed = [], [], []
    runtime = SimpleNamespace(close=lambda: closed.append(True) or True)
    status = host.run(io.BytesIO(data), SimpleNamespace(write=messages.append), watch_parent=parents.append,
        environment=environment, runtime_factory=lambda _: runtime)
    assert parents == [42] and closed == [True]
    assert messages[0] == {"v": 1, "type": "runtime_started", "pipe": config(tmp_path).pipe}
    assert messages[-1] == {"v": 1, "type": "runtime_stopped"}
    assert status == (2 if data else 0)
    if data: assert messages[1]["error"] == "invalid_request"


def test_lost_status_pipe_does_not_abandon_deferred_retirement(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
        "MESH_CHAT_CORE_API_PIPE": config(tmp_path).pipe,
        "MESH_CHAT_CORE_API_CLIENT_IMAGE": config(tmp_path).client_image, "MESH_CHAT_APP_PARENT_PID": "42"}
    closes = []
    runtime = SimpleNamespace(close=lambda: closes.append(True) or len(closes) >= 3)
    def lost(_): raise BrokenPipeError()
    assert host.run(io.BytesIO(), SimpleNamespace(write=lost), watch_parent=lambda _: None,
        environment=environment, runtime_factory=lambda _: runtime) == 0
    assert len(closes) == 3


def test_actual_main_route_never_reads_a_legacy_key_initializer(monkeypatch):
    from mesh_chat import __main__ as sidecar
    observed = []
    monkeypatch.setattr(sidecar.sys, "argv", ["mesh-service", "--app-owned-native"])
    monkeypatch.setattr(sidecar.sys, "stdin", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(sidecar.sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(sidecar, "interruptible_input", lambda value: value)
    monkeypatch.setattr(sidecar, "_initialize", lambda *_: pytest.fail("Legacy key initializer was reached"))
    def run(reader, writer, *, watch_parent):
        observed.append(watch_parent)
        assert reader.read() == b""
        return 0
    monkeypatch.setattr(host, "run", run)
    assert sidecar.main() == 0 and observed == [sidecar._start_parent_watchdog]


@pytest.mark.parametrize("directory", [Path("relative"), Path("")])
def test_untrusted_relative_directory_is_rejected_before_side_effects(directory):
    with pytest.raises(ValidationError): config(directory)
