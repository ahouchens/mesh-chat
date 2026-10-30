"""Host-supplied caller binding over a private stream pair."""

import io
import json

import pytest

from mesh_chat.core_api import host
from test_core_messages import client, host as service_host, request


def frame(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def serve(service, frames, **grant):
    writer = io.BytesIO()
    host.serve_host(service, io.BytesIO(b"".join(frames)), writer, **grant)
    return [json.loads(line) for line in writer.getvalue().splitlines()]


def test_host_binding_serves_negotiated_requests_for_its_caller(service_host):
    service = service_host()
    replies = serve(service, [frame(request("runtime.capabilities")),
                              frame(request("profile.query", profile="f" * 64))],
                    caller="mesh-chat-desktop", permissions=("observe", "read", "send", "diagnose"))
    assert [reply["ok"] for reply in replies] == [True, False]
    assert replies[1]["error"]["code"] == "forbidden"
    assert "message.received" in replies[0]["result"]["operations"]


def test_frames_cannot_select_or_change_the_caller_identity(service_host):
    service = service_host()
    injected = {"api_version": 1, "request_id": "request:1", "operation": "runtime.capabilities",
                "params": {"caller": "attacker", "permissions": ["send"]}}
    replies = serve(service, [frame(injected)], caller="mesh-chat-desktop",
                    permissions=("observe",))
    assert replies[0]["error"]["code"] == "invalid_request"
    handles = []
    for caller in ("mesh-chat-desktop", "other-application"):
        value = serve(service, [frame(request("runtime.capabilities"))], caller=caller,
                      permissions=("observe",))
        handles.append(value[0]["result"]["profiles"][0])
    assert handles[0] != handles[1]


def test_permission_set_bounds_every_operation(service_host):
    service = service_host()
    observe = serve(service, [frame(request("runtime.capabilities")),
                              frame({"api_version": 1, "request_id": "request:1",
                                     "operation": "message.received",
                                     "params": {"profile": "x" * 64, "cursor": None, "limit": 8}})],
                    caller="mesh-chat-desktop", permissions=("observe",))
    assert observe[1]["error"]["code"] == "forbidden"
    with pytest.raises(ValueError):
        host.host_grant("mesh-chat-desktop", ("runtime_owner",))
    with pytest.raises(ValueError):
        host.host_grant("mesh-chat-desktop", ("read",), profiles=("workspace",))


@pytest.mark.parametrize("caller", ["short", "bad caller", "x" * 81, "", None])
def test_invalid_host_caller_identity_is_rejected(service_host, caller):
    with pytest.raises(ValueError):
        host.host_grant(caller, ("observe",))


def test_eof_detaches_the_session_without_stopping_the_service(service_host):
    service = service_host()
    session = host.bind_host_stream(service, caller="mesh-chat-desktop", permissions=("observe",))
    session.serve(io.BytesIO(b""), io.BytesIO())
    assert session.exchange(frame(request("runtime.capabilities"))) != b""
    assert json.loads(session.exchange(frame(request("runtime.capabilities"))))["error"]["code"] == "unauthenticated"
    assert not service._shutdown.is_set()


def test_malformed_frame_detaches_the_host_stream(service_host):
    service = service_host()
    writer = io.BytesIO()
    host.serve_host(service, io.BytesIO(b"{not json}\n" + frame(request("runtime.capabilities"))),
                    writer, caller="mesh-chat-desktop", permissions=("observe",))
    replies = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert len(replies) == 1 and replies[0]["error"]["code"] == "invalid_request"
