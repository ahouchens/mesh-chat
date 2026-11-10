"""Offline allocation observations, not Android/JVM or native transport proof."""
import json
import socket
from threading import Event
import urllib.request
from uuid import uuid4

import pytest

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.qualification_host import QualificationControl
from mesh_chat.core_api.session import Grant
from mesh_chat.errors import NativeUnavailable
from test_native_profile_lifecycle import profile_runtime
from test_pairing_runtime import native_pairing, run_until


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline allocation control attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    yield
    assert not attempts


def frame(operation, **params):
    return {"api_version": 1, "request_id": "allocation:1", "operation": operation, "params": params}


def stats_frame(logical):
    return frame("native.command", command="native_webrtc_stats", payload={"session_id": logical})


def core(service, *, permissions=frozenset({"observe", "approve", "read"}), private_native=True):
    session = bind_service_session(service,
        lambda: Grant("offline-allocation", permissions, ("local",)), private_native=private_native)
    assert session.request(frame("runtime.capabilities"))["ok"]
    return session


def stats_result():
    return json.dumps({"ok": True, "result": {
        "ice_connection_state": "connected", "data_channel_state": "open"}})


@pytest.mark.parametrize("mode", [
    "success", "retired_before_stats", "host_missing", "retired_during_stats",
    "wrong_session_type", "host_runtime_error", "malformed_host_json",
])
def test_core_stats_preserves_failures_across_inventory_and_native_lifecycle(profile_runtime, mode):
    create, host = profile_runtime
    service = create()
    service.create_profile("Synthetic")
    logical = "allocation-observation"
    physical = service._native_resources.reserve(logical)
    service._native_webrtc_live.add(logical)
    host.close = lambda _: None
    host.stats = lambda _: stats_result()
    inventory = QualificationControl(lambda: service).dispatch("qualification.inventory", {})
    assert any(row["logical_session"] == logical and row["physical_resource"] == physical
               for row in inventory["resources"])
    if mode == "retired_before_stats":
        service.native_webrtc_close(logical, expected_physical=physical)
    elif mode == "host_missing":
        host.stats = lambda _: json.dumps({"ok": False, "error": "native_webrtc_session_missing"})
    elif mode == "retired_during_stats":
        def retired(resource):
            service.native_webrtc_close(logical, expected_physical=resource)
            return stats_result()
        host.stats = retired
    elif mode == "host_runtime_error":
        def runtime_error(_):
            raise RuntimeError("Synthetic native exception")
        host.stats = runtime_error
    elif mode == "malformed_host_json":
        host.stats = lambda _: "not-json"
    reply = core(service).request(stats_frame(None if mode == "wrong_session_type" else logical))
    assert reply["ok"] is (mode == "success")
    if mode != "success":
        expected = "internal" if mode in {"host_runtime_error", "malformed_host_json"} else "invalid_request"
        assert reply["error"]["code"] == expected
    if mode in {"retired_before_stats", "host_missing"}:
        with pytest.raises(NativeUnavailable) as error:
            service.native_webrtc_stats(logical)
        assert error.value.code == "native_unavailable"


@pytest.mark.parametrize("private_native,permissions,code", [
    (True, frozenset({"observe", "read"}), "forbidden"),
    (False, frozenset({"observe", "approve", "read"}), "unsupported_operation"),
])
def test_native_stats_never_borrows_private_capability_or_permission(profile_runtime, private_native, permissions, code):
    create, host = profile_runtime
    service = create()
    service.create_profile("Synthetic")
    calls = []
    host.stats = lambda resource: calls.append(resource) or stats_result()
    reply = core(service, permissions=permissions, private_native=private_native).request(stats_frame("unclaimed"))
    assert reply["ok"] is False and reply["error"]["code"] == code
    assert not calls


def test_reserved_inventory_precedes_native_publication_without_pairing_retirement(native_pairing, monkeypatch):
    """Real vault/signatures/runtime/Core; mailbox/native allocation are doubles."""
    create, _ = native_pairing
    first, *_ = create()
    second, host, *_ = create()
    for service in (first, second):
        service.update_call_settings({**service._call_settings.to_dict(), "stun_urls": [],
            "turn_url": None, "turn_username": None, "turn_credential": None,
            "turn_broker_url": None, "turn_broker_consent": False})
    offer_id, answer_id = str(uuid4()), str(uuid4())
    first.native_pairing_begin(offer_id, role="offer", authorized=lambda: True,
                               allow_direct_ip_disclosure=True)
    run_until(first, lambda: bool(first.native_pairing_status(offer_id)["pairing_code"]))
    code = first.native_pairing_status(offer_id)["pairing_code"]
    entered, release = Event(), Event()
    published = set()
    original_accept, original_stats = host.acceptOffer, host.stats
    def accept(physical, *args):
        # Model Android requireFactory/createPeerConnection before sessions[id]
        # publication, after the real Python reservation becomes inspectable.
        entered.set()
        assert release.wait(3), "Bounded native publication gate exceeded"
        published.add(physical)
        return original_accept(physical, *args)
    def stats(physical):
        if physical not in published:
            return json.dumps({"ok": False, "error": "native_webrtc_session_missing"})
        return original_stats(physical)
    monkeypatch.setattr(host, "acceptOffer", accept)
    monkeypatch.setattr(host, "stats", stats)
    session = core(second)
    inspector = QualificationControl(lambda: second)
    second.native_pairing_begin(answer_id, role="answer", pairing_code=code, authorized=lambda: True,
                                allow_direct_ip_disclosure=True)
    try:
        run_until(second, entered.is_set)
        inventory = inspector.dispatch("qualification.inventory", {})
        assert len(inventory["resources"]) == 1
        row, = inventory["resources"]
        logical, physical = row["logical_session"], row["physical_resource"]
        assert logical in second._native_webrtc_creating and physical not in published
        context = second._native_pairing_contexts[answer_id]
        assert second.native_pairing_status(answer_id)["state"] == "reserved"
        assert context["physical"] == physical and "answer" not in context
        request = stats_frame(logical)
        reply = session.request(request)
        assert reply["ok"] is False and reply["error"]["code"] == "invalid_request"
        assert second._native_resources.current(logical, physical)
        assert context["state"] not in {"retired", "retiring"}
    finally:
        release.set()
    run_until(second, lambda: second.native_pairing_status(answer_id)["state"] == "awaiting_approval")
    assert second._native_resources.current(logical, physical)
    reply = session.request(request)
    assert reply["ok"] is True and reply["result"]["data_channel_state"] == "open"
    assert reply["result"]["attached"] is False and len(published) == 1
    assert second.store.list("contact") == []
    assert not second._native_webrtc_profile_sessions and not second._native_webrtc_sessions
    assert all(state.carrier is None for state in second._connection_runtime.owner.snapshots())
