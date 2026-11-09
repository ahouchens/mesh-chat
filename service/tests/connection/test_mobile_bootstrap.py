"""Trusted mobile composition selects one owner before service startup."""
import base64
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from mesh_chat import mobile_bridge, native_webrtc_host
from mesh_chat.errors import ValidationError


@pytest.fixture
def mobile_request(tmp_path, monkeypatch):
    mobile_bridge.shutdown()
    monkeypatch.setattr(sys, "platform", "android")
    monkeypatch.setattr(Path, "home", classmethod(lambda _: tmp_path))

    def unexpected(*_):
        pytest.fail("An empty profile must not allocate a native peer")

    native = SimpleNamespace(**{name: unexpected for name in native_webrtc_host.HOST_METHODS})
    monkeypatch.setattr(native_webrtc_host, "android_host", lambda: native)
    yield json.dumps({"profile_dir": str(tmp_path / "files" / "profile"),
                      "vault_key": base64.b64encode(b"b" * 32).decode(),
                      "platform": "android"})
    assert json.loads(mobile_bridge.shutdown())["ok"]


@pytest.mark.parametrize("policy", ["legacy", "shared-native"])
def test_mobile_constructor_selects_one_owner_and_rejects_live_switch(mobile_request, policy):
    result = json.loads(mobile_bridge.initialize(mobile_request, connection_policy=policy))
    assert result["ok"]
    service = mobile_bridge._service
    owner = service._connection_runtime
    assert service._connection_policy == policy
    assert (owner is not None) == (policy == "shared-native")
    assert service._background_reconnect_supervisor is None
    assert json.loads(mobile_bridge.initialize(mobile_request, connection_policy=policy))["ok"]
    other = "legacy" if policy == "shared-native" else "shared-native"
    assert json.loads(mobile_bridge.initialize(mobile_request, connection_policy=other)) == {
        "ok": False, "error": {"code": "invalid_request"}}
    assert mobile_bridge._service is service
    assert service._connection_runtime is owner
    if owner is not None:
        assert owner._thread.is_alive()
        assert owner._failure is None


def test_mobile_default_remains_legacy(mobile_request):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    assert mobile_bridge._service._connection_policy == "legacy"
    assert mobile_bridge._service._connection_runtime is None


@pytest.mark.parametrize("field", ["profile_dir", "vault_key", "platform"])
def test_live_mobile_runtime_cannot_be_reused_for_another_profile_binding(mobile_request, field):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    service = mobile_bridge._service
    changed = json.loads(mobile_request)
    changed[field] = {"profile_dir": changed["profile_dir"] + "-other",
                      "vault_key": base64.b64encode(b"c" * 32).decode(), "platform": "ios"}[field]
    assert not json.loads(mobile_bridge.initialize(json.dumps(changed)))["ok"]
    assert mobile_bridge._service is service


def test_trusted_native_entry_starts_exactly_one_owner(mobile_request):
    assert json.loads(mobile_bridge.initialize_native(mobile_request))["ok"]
    owner = mobile_bridge._service._connection_runtime
    assert owner is not None
    assert json.loads(mobile_bridge.initialize_native(mobile_request))["ok"]
    assert mobile_bridge._service._connection_runtime is owner


def test_retired_mobile_emitter_cannot_publish_into_replacement_incarnation(mobile_request):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    old_emit = mobile_bridge._service.emit
    assert json.loads(mobile_bridge.shutdown())["ok"]
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    mobile_bridge.drain_events()
    old_emit({"type": "event", "event": "old-profile-secret"})
    assert json.loads(mobile_bridge.drain_events())["result"] == []


def test_failed_mobile_close_retains_exact_owner_and_blocks_other_profile(mobile_request, monkeypatch):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    service = mobile_bridge._service
    original = service.close

    def failed_close():
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(service, "close", failed_close)
    assert not json.loads(mobile_bridge.shutdown())["ok"]
    assert mobile_bridge._service is None
    assert mobile_bridge._retiring_service is service
    assert service._shutdown.is_set()
    changed = json.loads(mobile_request)
    changed["profile_dir"] += "-other"
    assert not json.loads(mobile_bridge.initialize(json.dumps(changed)))["ok"]
    assert mobile_bridge._retiring_service is service
    monkeypatch.setattr(service, "close", original)
    assert json.loads(mobile_bridge.shutdown())["ok"]
    assert service._store_closed and mobile_bridge._retiring_service is None


def test_deferred_mobile_close_blocks_replacement_until_store_and_workers_finish(mobile_request, monkeypatch):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    service = mobile_bridge._service
    released = threading.Event()
    service._pending_contact_carriers = {"pending": SimpleNamespace(close=lambda: None, wait=released.wait)}
    assert json.loads(mobile_bridge.shutdown())["ok"]
    assert mobile_bridge._retiring_service is service
    assert not json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    assert mobile_bridge._service is None
    assert not service._store_closed
    released.set()
    service._close_finalizer.join(3)
    assert service._store_closed
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    assert mobile_bridge._service is not service


def test_overflow_emitter_rechecks_incarnation_after_event_lock_release(mobile_request, monkeypatch):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    service, token = mobile_bridge._service, mobile_bridge._event_incarnation
    invalidated = []
    replacement = SimpleNamespace(_shutdown=service._shutdown,
                                  _mark_workspace_invalidation_overflow=lambda: invalidated.append("new"))
    lock = mobile_bridge._events_lock
    class ReplaceOnRelease:
        def __enter__(self): return lock.__enter__()
        def __exit__(self, *args):
            result = lock.__exit__(*args)
            mobile_bridge._service = replacement
            mobile_bridge._event_incarnation = "replacement"
            return result
    mobile_bridge._events.extend({"event": "filler"} for _ in range(mobile_bridge._events.maxlen))
    try:
        monkeypatch.setattr(mobile_bridge, "_events_lock", ReplaceOnRelease())
        service.emit({"event": "late-overflow"})
        assert invalidated == []
    finally:
        mobile_bridge._service, mobile_bridge._event_incarnation = service, token
        monkeypatch.setattr(mobile_bridge, "_events_lock", lock)


def test_failed_unpublished_constructor_retains_its_cleanup_owner(mobile_request, monkeypatch):
    from mesh_chat.connection import composition
    captured = []

    def failed_owner(service):
        captured.append(service)
        service._direct_native.close = lambda: (_ for _ in ()).throw(OSError("native close unavailable"))
        raise RuntimeError("owner construction failed")

    monkeypatch.setattr(composition, "native_runtime", failed_owner)
    try:
        assert not json.loads(mobile_bridge.initialize_native(mobile_request))["ok"]
        service, = captured
        assert mobile_bridge._service is None
        assert mobile_bridge._retiring_service is service
        assert not service._store_closed
        assert not json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    finally:
        if captured:
            from mesh_chat.direct_native import NativeChannel
            service._direct_native.close = lambda: NativeChannel.close(service._direct_native)
            assert json.loads(mobile_bridge.shutdown())["ok"]
            assert service._store_closed


def test_deferred_constructor_cleanup_retains_unpublished_instance_until_worker_drains(mobile_request, monkeypatch):
    from mesh_chat.connection import composition
    captured = []
    released = threading.Event()

    def failed_owner(service):
        captured.append(service)
        service._pending_contact_carriers = {"pending": SimpleNamespace(close=lambda: None, wait=released.wait)}
        raise RuntimeError("owner construction failed")

    monkeypatch.setattr(composition, "native_runtime", failed_owner)
    try:
        assert not json.loads(mobile_bridge.initialize_native(mobile_request))["ok"]
        service, = captured
        assert mobile_bridge._service is None and mobile_bridge._retiring_service is service
        assert not service._store_closed and service.store.get("profile", "local") is None
        assert service._close_finalizer.is_alive()
        assert not json.loads(mobile_bridge.initialize(mobile_request))["ok"]
        assert mobile_bridge._retiring_service is service and not service._store_closed
    finally:
        released.set()
        if captured:
            captured[0]._close_finalizer.join(3)
            assert captured[0]._store_closed
            assert json.loads(mobile_bridge.shutdown())["ok"]
            assert mobile_bridge._retiring_service is None


def test_mobile_publication_retires_exact_android_sessions_before_service_close(mobile_request, monkeypatch):
    from mesh_chat.core_api import android_host
    from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    service = mobile_bridge._service
    frame = encode_frame({"api_version": 1, "request_id": "host:lifecycle",
                          "operation": "runtime.capabilities", "params": {}})
    caller = "com.example.stableUID"
    assert decode_frame(android_host.exchange(service, caller, frame))["ok"]
    assert android_host.active_callers() == [caller]
    original_retire, original_close = android_host.retire, service.close
    retired = []
    def retire(exact):
        assert mobile_bridge._service is None and exact is service
        assert not exact._store_closed
        retired.append(exact)
        result = original_retire(exact)
        assert android_host.active_callers() == []
        return result
    def close():
        assert retired == [service]
        return original_close()
    monkeypatch.setattr(android_host, "retire", retire)
    monkeypatch.setattr(service, "close", close)
    assert json.loads(mobile_bridge.shutdown())["ok"]
    monkeypatch.setattr(service, "close", original_close)
    monkeypatch.setattr(android_host, "retire", original_retire)
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    replacement = mobile_bridge._service
    assert decode_frame(android_host.exchange(replacement, caller, frame))["ok"]
    current_session = android_host._sessions[caller, "consumer"]
    original_retire(service)  # An old cleanup callback cannot detach the replacement.
    assert mobile_bridge._service is replacement and not replacement._shutdown.is_set()
    assert android_host._sessions[caller, "consumer"] is current_session
    assert decode_frame(android_host.exchange(replacement, caller, frame))["ok"]


@pytest.mark.parametrize("field", ["connection_policy", "native_webrtc_host"])
def test_mobile_json_cannot_select_private_composition(mobile_request, field):
    request = json.loads(mobile_request)
    request[field] = "shared-native"
    assert json.loads(mobile_bridge.initialize(json.dumps(request))) == {
        "ok": False, "error": {"code": "invalid_request"}}
    assert mobile_bridge._service is None


def test_invalid_private_policy_fails_before_opening_vault(mobile_request, monkeypatch):
    monkeypatch.setattr(mobile_bridge, "VaultStore", lambda *_a, **_k: pytest.fail("Opened vault"))
    assert json.loads(mobile_bridge.initialize(mobile_request, connection_policy="unknown")) == {
        "ok": False, "error": {"code": "invalid_request"}}
    assert mobile_bridge._service is None


@pytest.mark.parametrize("policy", ["legacy", "shared-native"])
def test_profile_failure_closes_unpublished_service(mobile_request, monkeypatch, policy):
    constructed = []

    def fail_profile(service, _name):
        constructed.append(service)
        raise ValidationError("Profile creation failed")

    monkeypatch.setattr(mobile_bridge.MeshChatService, "create_profile", fail_profile)
    request = json.loads(mobile_request)
    request["display_name"] = "Synthetic profile"
    try:
        assert json.loads(mobile_bridge.initialize(json.dumps(request), connection_policy=policy)) == {
            "ok": False, "error": {"code": "invalid_request"}}
        service, = constructed
        assert service._shutdown.is_set()
        assert service._store_closed
        if service._connection_runtime is not None:
            assert not service._connection_runtime._thread.is_alive()
        assert mobile_bridge._service is None
        assert mobile_bridge._native_channel is None
    finally:
        for service in constructed:
            service.close()
