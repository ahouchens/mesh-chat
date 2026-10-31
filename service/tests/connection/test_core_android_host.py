"""Android Binder host binding: one fixed grant per authenticated caller."""

import base64
import json

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
