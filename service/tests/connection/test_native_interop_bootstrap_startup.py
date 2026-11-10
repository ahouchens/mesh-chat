"""Interop composition guard and offline factory path; no JVM/native qualification."""
import base64
import json
import os
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
import urllib.request
from uuid import uuid4

import pytest

from mesh_chat.core_api import qualification_host as private
from mesh_chat.direct_bootstrap_mobile import AndroidBootstrapProcess
from test_pairing_runtime import native_pairing, run_until

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline startup control attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    yield
    assert not attempts


def test_fresh_instrumentation_configures_bootstrap_before_runtime_start():
    # Source composition guard only: the platform run must still execute this
    # initialization in the optimized APK. No client is opened as a probe.
    path = ROOT / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt"
    source = path.read_text(encoding="utf-8")
    configure = "BootstrapClient.configure(context)"
    assert configure in source, "Fresh interop host must supply the isolated bootstrap context"
    assert source.index(configure) < source.index("NativeWebRtcBridge.attach(context)")
    assert source.index(configure) < source.index("Python.start(AndroidPlatform(context))")
    assert source.index(configure) < source.index('qualification.callAttr("android_initialize"')


def qualified(create, directory):
    key = os.urandom(32)
    initial = {"v": 1, "command": "initialize", "payload": {"profile_dir": str(directory),
        "vault_key": base64.b64encode(key).decode(), "display_name": "Mesh qualification", "parent_pid": os.getpid()}}
    private.reserve_fresh_profile(initial)
    service, _, created, closed, *_ = create(directory, key)
    private.mark_initialized_profile(initial)
    service.update_call_settings({**service._call_settings.to_dict(), "stun_urls": [],
        "turn_url": None, "turn_username": None, "turn_credential": None,
        "turn_broker_url": None, "turn_broker_consent": False})
    return private.QualificationControl(lambda: service), service, created, closed


@pytest.mark.parametrize("configured", [False, True])
def test_actual_answer_bind_reaches_context_bound_android_factory(native_pairing, tmp_path, monkeypatch, configured):
    create, documents = native_pairing
    operations, opens = [], []
    class Client:
        def call(self, raw):
            operation = json.loads(raw)["operation"]
            operations.append(operation)  # Retain enums, never identity payloads.
            result = {"packets": [], "events": [], "recipient_ready": False} if operation == "exchange" else None
            return json.dumps({"ok": True, "result": result})
        def close(self): pass
    class ContextBoundBootstrap:
        # Java context/open are doubles; AndroidBootstrapProcess itself is real.
        context = None
        @classmethod
        def configure(cls, value): cls.context = value.applicationContext
        @classmethod
        def open(cls):
            opens.append(True)
            if cls.context is None:
                raise RuntimeError("Synthetic missing bootstrap application context")
            return Client()
    java = ModuleType("java")
    def jclass(name):
        assert name == "com.meshchat.runtime.BootstrapClient"
        return ContextBoundBootstrap
    java.jclass = jclass
    monkeypatch.setitem(sys.modules, "java", java)
    if configured:
        ContextBoundBootstrap.configure(SimpleNamespace(applicationContext=object()))
    offer_port, offer_service, *_ = qualified(create, tmp_path / "mesh-qualification-offer")
    offer_id = str(uuid4())
    offer_port.dispatch("qualification.pairing_begin", {"operation_id": offer_id,
                        "role": "offer", "allow_direct_ip_disclosure": True})
    def status(port, operation):
        return port.dispatch("qualification.pairing_status", {"operation_id": operation})
    run_until(offer_service, lambda: bool(status(offer_port, offer_id)["pairing_code"]))
    code = status(offer_port, offer_id)["pairing_code"]
    port, service, created, closed = qualified(create, tmp_path / "mesh-qualification-answer")
    # The ordinary component fixture has network=None, which skips begin().
    # An inert sentinel exercises the real pending carrier/factory branch.
    service.network = SimpleNamespace(_direct_bootstrap=None, shutdown=lambda: True)
    service._direct_bootstrap_factory = AndroidBootstrapProcess
    operation = str(uuid4())
    port.dispatch("qualification.pairing_begin", {"operation_id": operation, "role": "answer",
                  "pairing_code": code, "allow_direct_ip_disclosure": True})
    expected = "awaiting_approval" if configured else "retired"
    run_until(service, lambda: status(port, operation)["state"] == expected)
    observed = status(port, operation)
    context = next(iter(service._native_pairing_contexts.values()))
    assert len(created) == len(opens) == 1 and "answer" in context
    if configured:
        assert "retirement" not in observed
        assert operations == ["initialize_contact"]
        assert any(role == "answer" for _, role in documents)
        assert len(service._pending_contact_carriers) == 1 and not closed
    else:
        assert observed["retirement"] == {"phase": "gather_answer", "event": "failed", "reason": "transient"}
        assert operations == [] and not service._pending_contact_carriers
        assert len(set(closed)) == 1
