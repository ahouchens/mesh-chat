"""Android Binder host binding: one fixed grant per authenticated caller."""

import base64
import json
import uuid

import pytest

from mesh_chat import mobile_bridge
from mesh_chat.core_api import android_host
from mesh_chat.core_api.limits import MAX_FRAME_BYTES
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from test_core_messages import host


@pytest.fixture(autouse=True)
def clean_sessions():
    android_host.close_all()
    yield
    android_host.close_all()


def frame(operation, **params):
    return encode_frame({"api_version": 1, "request_id": "android:1",
                         "operation": operation, "params": params})


def call(service, caller, operation, **params):
    return decode_frame(android_host.exchange(service, caller, frame(operation, **params)))


def test_a_caller_negotiates_and_reads_only_its_own_profile(host):
    service = host()
    capabilities = call(service, "com.example.consumer", "runtime.capabilities")
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    view = call(service, "com.example.consumer", "profile.query", profile=profile)
    assert view["ok"] and len(view["result"]["peers"]) == 1
    other = call(service, "com.example.other", "runtime.capabilities")
    assert other["result"]["profiles"][0] != profile
    assert "runtime.stop" in capabilities["result"]["operations"]
    assert call(service, "com.example.consumer", "runtime.stop")["error"]["code"] == "forbidden"


def test_uninitialized_or_malformed_requests_fail_closed(host):
    service = host()
    assert decode_frame(android_host.exchange(None, "com.example", frame("runtime.capabilities"))
                        )["error"]["code"] == "unavailable"
    for caller in ("", "x" * 201, "bad\u0000caller", "\u00e9"):
        assert decode_frame(android_host.exchange(service, caller, frame("runtime.capabilities"))
                            )["error"]["code"] == "forbidden"
    assert decode_frame(android_host.exchange(service, "com.example", b""))["error"]["code"] == "invalid_request"
    oversized = b"x" * (MAX_FRAME_BYTES + 1)
    assert decode_frame(android_host.exchange(service, "com.example", oversized)
                        )["error"]["code"] == "invalid_request"


def test_the_caller_table_is_bounded_and_can_be_detached(host):
    service = host()
    for index in range(android_host.MAX_CALLERS):
        assert call(service, f"com.example.app{index}", "runtime.capabilities")["ok"]
    assert decode_frame(android_host.exchange(service, "com.example.overflow",
                                              frame("runtime.capabilities"))
                        )["error"]["code"] == "resource_exhausted"
    android_host.close_all()
    assert android_host.active_callers() == []
    assert call(service, "com.example.overflow", "runtime.capabilities")["ok"]


def test_mobile_bridge_forwards_frames_only_with_a_running_service(host, monkeypatch):
    encoded = base64.b64encode(frame("runtime.capabilities")).decode("ascii")
    monkeypatch.setattr(mobile_bridge, "_service", None)
    reply = decode_frame(base64.b64decode(mobile_bridge.core_exchange("com.example", encoded)))
    assert reply["error"]["code"] == "unavailable"
    service = host()
    monkeypatch.setattr(mobile_bridge, "_service", service)
    forwarded = decode_frame(base64.b64decode(mobile_bridge.core_exchange("com.example", encoded)))
    assert forwarded["ok"], forwarded
    bad = decode_frame(base64.b64decode(mobile_bridge.core_exchange("com.example", "not base64!!")))
    assert bad["error"]["code"] == "invalid_request"


def test_owner_scope_is_separate_and_may_approve(host):
    service = host()
    service.create_workspace(str(uuid.uuid4()), "Android owner", "")
    exchange = lambda caller, envelope, scope="consumer": decode_frame(
        android_host.exchange(service, caller, encode_frame(envelope), scope))
    capabilities = exchange("com.example.owner", {
        "api_version": 1, "request_id": "android:1",
        "operation": "runtime.capabilities", "params": {}}, "owner")
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    listing = exchange("com.example.owner", {
        "api_version": 1, "request_id": "android:2",
        "operation": "workspace.query", "params": {"profile": profile}}, "owner")
    assert listing["ok"], listing
    workspace = listing["result"]["workspaces"][0]["workspace"]
    created = exchange("com.example.owner", {
        "api_version": 1, "request_id": "android:3",
        "operation": "workspace.channel_create",
        "params": {"profile": profile, "workspace": workspace, "name": "Owner channel"},
        "idempotency_key": "o" * 32}, "owner")
    assert created["ok"], created
    denied = exchange("com.example.consumer", {
        "api_version": 1, "request_id": "android:4",
        "operation": "workspace.channel_create",
        "params": {"profile": profile, "workspace": workspace, "name": "Consumer channel"},
        "idempotency_key": "c" * 32})
    assert denied["error"]["code"] == "forbidden"
    assert exchange("com.example.owner", {
        "api_version": 1, "request_id": "android:5",
        "operation": "runtime.stop", "params": {}}, "owner")["error"]["code"] == "forbidden"
    assert exchange("com.example.owner", {
        "api_version": 1, "request_id": "android:6",
        "operation": "runtime.capabilities", "params": {}}, "administrator"
    )["error"]["code"] == "forbidden"


def test_service_restart_rebinds_the_same_binder_caller_and_requires_negotiation(host):
    service = host()
    caller = "com.example.consumer"
    profile = call(service, caller, "runtime.capabilities")["result"]["profiles"][0]
    assert call(service, caller, "profile.query", profile=profile)["ok"]
    service.close()
    assert call(service, caller, "runtime.capabilities")["error"]["code"] == "unavailable"
    assert android_host.active_callers() == []
    reopened = host()
    assert call(reopened, caller, "profile.query", profile=profile)["error"]["code"] == "negotiation_required"
    assert call(reopened, caller, "runtime.capabilities")["result"]["profiles"] == [profile]
    assert call(reopened, caller, "profile.query", profile=profile)["ok"]
    assert call(reopened, caller, "runtime.stop")["error"]["code"] == "forbidden"


def test_missing_service_retires_cached_sessions_before_reinitialization(host, monkeypatch):
    service = host()
    monkeypatch.setattr(mobile_bridge, "_service", service)
    encoded = base64.b64encode(frame("runtime.capabilities")).decode("ascii")
    exchange = lambda: decode_frame(base64.b64decode(
        mobile_bridge.core_exchange("com.example.consumer", encoded)))
    assert exchange()["ok"]
    service.close()
    monkeypatch.setattr(mobile_bridge, "_service", None)
    assert exchange()["error"]["code"] == "unavailable"
    assert android_host.active_callers() == []
    monkeypatch.setattr(mobile_bridge, "_service", host())
    assert exchange()["ok"]


def test_retired_service_reference_cannot_reclaim_the_new_incarnation(host):
    service = host()
    caller = "com.example.consumer"
    profile = call(service, caller, "runtime.capabilities")["result"]["profiles"][0]
    service._identity = None
    assert call(service, caller, "profile.query", profile=profile)["error"]["code"] == "locked"
    service.close()
    replacement = host()
    assert call(replacement, caller, "runtime.capabilities")["ok"]
    assert call(service, caller, "runtime.capabilities")["error"]["code"] == "unavailable"
    assert call(replacement, caller, "profile.query", profile=profile)["ok"]

    # A delayed lifecycle observer cannot make an old object current again.
    service._shutdown.clear()
    assert call(service, caller, "runtime.capabilities")["error"]["code"] == "unavailable"
    assert call(replacement, caller, "profile.query", profile=profile)["ok"]


def test_only_the_android_own_uid_host_binding_attaches_native_commands(host):
    service = host()
    command = frame("native.command", command="workspace_snapshot", payload={})
    public = call(service, "com.example.consumer", "runtime.capabilities")
    assert "native.command" not in public["result"]["operations"]
    assert decode_frame(android_host.exchange(service, "com.example.consumer", command)
                        )["error"]["code"] == "unsupported_operation"
    own_uid = decode_frame(android_host.exchange(
        service, "com.meshchat", frame("runtime.capabilities"), "owner"))
    assert "native.command" in own_uid["result"]["operations"]
    assert decode_frame(android_host.exchange(service, "com.meshchat", command, "owner"))["ok"]
