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
def android_fixture(tmp_path):
    source = ANDROID_TEST.read_text(encoding="utf-8")
    embedded = re.search(r'private val FIXTURE = """(.*?)"""\.trimIndent\(\)', source, re.S)
    assert embedded is not None, "The executed Android fixture must remain available to the component test"
    fixture = ModuleType("typed_core_boundary_fixture")
    exec(compile(dedent(embedded.group(1)), str(ANDROID_TEST) + ":FIXTURE", "exec"), fixture.__dict__)
    fixture.setup(str(tmp_path))
    try:
        yield fixture
    finally:
        fixture.close()


def exchange(operation, params=None, key=None):
    value = {"api_version": 1, "request_id": "android-boundary:1",
             "operation": operation, "params": params or {}}
    if key is not None:
        value["idempotency_key"] = key
    frame = json.dumps(value).encode("utf-8") + b"\n"
    reply = mobile_bridge.core_exchange("typed-boundary-app", base64.b64encode(frame).decode("ascii"), "owner")
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
