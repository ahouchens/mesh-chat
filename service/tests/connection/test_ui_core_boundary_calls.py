"""Execute the exact Android embedded fixture through the mobile Core framing.

This fast component check catches invalid fixture/domain assumptions before the
mandatory Binder instrumentation. It does not replace that Android execution.
"""

import base64
import json
from pathlib import Path
import re
from textwrap import dedent
from types import ModuleType

import pytest

from mesh_chat import mobile_bridge

ROOT = Path(__file__).resolve().parents[3]
ANDROID_TEST = ROOT / ("plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/"
                       "com/meshchat/runtime/TypedCoreBridgeBoundaryTest.kt")


@pytest.fixture
def android_fixture(tmp_path, request):
    source = ANDROID_TEST.read_text(encoding="utf-8")
    embedded = re.search(r'private val FIXTURE = """(.*?)"""\.trimIndent\(\)', source, re.S)
    assert embedded is not None, "The executed Android fixture must remain available to the component test"
    fixture = ModuleType("typed_core_boundary_fixture")
    exec(compile(dedent(embedded.group(1)), str(ANDROID_TEST) + ":FIXTURE", "exec"), fixture.__dict__)
    fixture.setup(str(tmp_path), getattr(request, "param", True))
    try:
        yield fixture
    finally:
        fixture.close()


def exchange(operation, params=None, key=None, *, caller="typed-boundary-app"):
    value = {"api_version": 1, "request_id": "android-boundary:1",
             "operation": operation, "params": params or {}}
    if key is not None:
        value["idempotency_key"] = key
    frame = json.dumps(value).encode("utf-8") + b"\n"
    reply = mobile_bridge.core_exchange(caller, base64.b64encode(frame).decode("ascii"), "owner")
    return json.loads(base64.b64decode(reply))


def result(operation, params=None, key=None):
    reply = exchange(operation, params, key)
    assert reply["ok"], reply
    return reply["result"]


def profile():
    return result("runtime.capabilities")["profiles"][0]


def test_android_settings_mutation_fixture_asserts_real_store_readback(android_fixture):
    handle = profile()
    result("settings.update", {"profile": handle, "settings": {
        "nearby_discovery": False, "lan_fallback": False, "help_route": True}})
    assert result("settings.query", {"profile": handle})["settings"]["help_route"] is True
    result("call.settings_update", {"profile": handle, "settings": {
        "stun_urls": [], "turn_broker_url": None, "turn_broker_consent": False,
        "signal_mailbox_url": None, "relay_only": False, "store_call_signaling": False}})
    assert result("call.settings_query", {"profile": handle})["settings"]["store_call_signaling"] is False
    assert android_fixture.assert_settings_mutated() is True


def test_android_call_control_fixture_asserts_signed_start_and_end(android_fixture):
    handle = profile()
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    sdp = f"v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=fingerprint:{fingerprint}\r\n"
    started = result("call.control", {"profile": handle, "action": "start",
        "contact_id": "android-call-peer", "media": "audio", "sdp": sdp,
        "dtls_fingerprint": fingerprint}, "android-boundary-call-start-0001")["result"]
    assert started["state"] == "dialing"
    assert android_fixture.assert_call_started(started["id"]) is True
    ended = result("call.control", {"profile": handle, "action": "end",
        "call_id": started["id"], "reason": "completed"}, "android-boundary-call-end-0001")["result"]
    assert ended["state"] == "ended" and ended["id"] == started["id"]
    assert android_fixture.assert_call_ended(started["id"]) is True


@pytest.mark.parametrize("rebind", [False, True])
def test_lost_committed_call_start_resolves_original_ticket_then_cancels_once(android_fixture, rebind):
    handle = profile()
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    sdp = f"v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=fingerprint:{fingerprint}\r\n"
    params = {"profile": handle, "action": "start", "contact_id": "android-call-peer",
              "media": "audio", "sdp": sdp, "dtls_fingerprint": fingerprint}
    key = "independent-lost-start-key-0001"
    # Lose the reply only after the real Core parser/session/domain committed.
    committed = result("call.control", params, key)["result"]
    assert android_fixture.assert_call_started(committed["id"]) is True
    if rebind:
        android_fixture.close_all()
        assert profile() == handle
    recovered = result("call.control", params, key)["result"]
    assert recovered["id"] == committed["id"] and recovered["state"] == "dialing"
    assert android_fixture.assert_call_started(committed["id"]) is True
    conflict = exchange("call.control", {**params, "sdp": sdp + "a=sendrecv\r\n"}, key)
    assert conflict["error"]["code"] == "idempotency_conflict"
    cancel = {"profile": handle, "action": "end", "call_id": recovered["id"], "reason": "completed"}
    end_key = "independent-cancel-resolved-call-0001"
    ended = result("call.control", cancel, end_key)["result"]
    assert ended["id"] == committed["id"] and ended["state"] == "ended"
    assert result("call.control", cancel, end_key)["result"]["id"] == committed["id"]
    assert android_fixture.assert_call_ended(committed["id"]) is True


def test_call_media_query_rejects_other_callers_profile_and_call_handles_without_disclosure(android_fixture):
    handle = profile()
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    sdp = f"v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=fingerprint:{fingerprint}\r\n"
    started = result("call.control", {"profile": handle, "action": "start", "contact_id": "android-call-peer",
        "media": "audio", "sdp": sdp, "dtls_fingerprint": fingerprint}, "independent-media-authority-0001")["result"]
    own_call = next(item for item in result("application.snapshot")["calls"] if item["id"] == started["id"])["core_handle"]
    own_media = result("call.media_query", {"profile": handle, "call": own_call})
    assert own_media["profile"] == handle and own_media["call"] == own_call
    assert own_media["media"] == mobile_bridge._service.call_media(started["id"])
    assert own_media["media"]["local_sdp"] == sdp

    other = "other-real-host-caller"
    def other_result(operation, params=None):
        response = exchange(operation, params, caller=other)
        assert response["ok"], response
        return response["result"]
    other_profile = other_result("runtime.capabilities")["profiles"][0]
    other_call = next(item for item in other_result("application.snapshot")["calls"] if item["id"] == started["id"])["core_handle"]
    assert other_profile != handle and other_call != own_call
    assert other_result("call.media_query", {"profile": other_profile, "call": other_call})["media"] == own_media["media"]
    before = mobile_bridge._service.store._db.total_changes
    requests = [(other, other_profile, own_call), (other, handle, other_call),
                ("typed-boundary-app", handle, other_call), ("typed-boundary-app", other_profile, own_call)]
    for caller, scoped_profile, call in requests:
        denied = exchange("call.media_query", {"profile": scoped_profile, "call": call}, caller=caller)
        assert denied["ok"] is False and denied["error"]["code"] == "forbidden"
        assert "result" not in denied and sdp not in json.dumps(denied)
        assert set(denied["error"]) <= {"code", "retry_after_ms", "message"}
    assert mobile_bridge._service.store._db.total_changes == before
    assert android_fixture.assert_call_started(started["id"]) is True


@pytest.mark.parametrize("android_fixture", [False], indirect=True)
def test_android_fresh_profile_fixture_creates_only_through_keyed_core(android_fixture):
    assert android_fixture.assert_profile_absent() is True
    assert "profile.create" in result("runtime.capabilities")["operations"]
    android_fixture.capture_preview_state()
    preview = result("bootstrap.preview", {"kind": "personal", "document": android_fixture.bootstrap_document()})
    assert preview["kind"] == "personal" and preview["preview"]["display_name"] == "Pre-profile sponsor"
    assert android_fixture.assert_preview_unchanged() is True
    params, key = {"display_name": "Fresh Android owner"}, "android-fresh-profile-key-0001"
    created = result("profile.create", params, key)
    view = result("profile.query", {"profile": profile()})
    assert view["display_name"] == "Fresh Android owner"
    identity = android_fixture.profile_identity_hash()
    assert result("profile.create", params, key) == created
    conflict = exchange("profile.create", {"display_name": "Changed owner"}, key)
    assert conflict["error"]["code"] == "idempotency_conflict"
    android_fixture.reopen()
    assert "profile.create" in result("runtime.capabilities")["operations"]
    assert result("profile.create", params, key) == created
    assert result("profile.query", {"profile": profile()}) == view
    assert android_fixture.profile_identity_hash() == identity
