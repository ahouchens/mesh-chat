"""Host-supplied caller binding over a private stream pair."""

import io
import json
import uuid

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


def test_owner_scope_may_administrate_while_consumer_scope_may_not(service_host):
    service = service_host()
    service.create_workspace(str(uuid.uuid4()), "Owner workspace", "")
    owner_permissions = ("observe", "read", "send", "approve", "pair", "connect")
    capabilities = serve(
        service, [frame(request("runtime.capabilities"))],
        caller="mesh-chat-desktop", permissions=owner_permissions, scope="owner")[0]
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    listing = serve(
        service, [frame(request("runtime.capabilities")),
                  frame(request("workspace.query", profile=profile))],
        caller="mesh-chat-desktop", permissions=owner_permissions, scope="owner")[1]
    assert listing["ok"], listing
    workspace = listing["result"]["workspaces"][0]["workspace"]
    created = serve(
        service, [frame(request("runtime.capabilities")),
                  frame({"api_version": 1, "request_id": "request:1",
                         "operation": "workspace.channel_create",
                         "params": {"profile": profile, "workspace": workspace,
                                    "name": "Owner channel"},
                         "idempotency_key": "o" * 32})],
        caller="mesh-chat-desktop", permissions=owner_permissions, scope="owner")[1]
    assert created["ok"], created
    consumer = serve(
        service, [frame(request("runtime.capabilities")),
                  frame({"api_version": 1, "request_id": "request:1",
                         "operation": "workspace.channel_create",
                         "params": {"profile": profile, "workspace": workspace,
                                    "name": "Consumer channel"},
                         "idempotency_key": "c" * 32})],
        caller="mesh-chat-desktop", permissions=("observe", "read"))[1]
    assert consumer["error"]["code"] == "forbidden"


def test_owner_scope_cannot_request_runtime_ownership():
    with pytest.raises(ValueError):
        host.host_grant("mesh-chat-desktop", ("runtime_owner",), scope="owner")
    with pytest.raises(ValueError):
        host.host_grant("mesh-chat-desktop", ("approve",), scope="consumer")
    with pytest.raises(ValueError):
        host.host_grant("mesh-chat-desktop", ("observe",), scope="administrator")


def test_public_owner_cannot_attach_or_invoke_the_private_native_port(service_host):
    service = service_host()
    permissions = tuple(host.OWNER_PERMISSIONS)
    command = request("native.command", command="workspace_snapshot", payload={})
    public = host.bind_host_stream(service, caller="external-owner", permissions=permissions,
                                   scope="owner")
    capabilities = json.loads(public.exchange(frame(request("runtime.capabilities"))))
    assert "native.command" not in capabilities["result"]["operations"]
    assert json.loads(public.exchange(frame(command)))["error"]["code"] == "unsupported_operation"
    injected = {**command, "private_native": True}
    assert json.loads(public.exchange(frame(injected)))["error"]["code"] == "invalid_request"
    private = host.bind_host_stream(service, caller="mesh-chat-desktop", permissions=permissions,
                                    scope="owner", private_native=True)
    capabilities = json.loads(private.exchange(frame(request("runtime.capabilities"))))
    assert "native.command" in capabilities["result"]["operations"]
    assert json.loads(private.exchange(frame(command)))["ok"]
    with pytest.raises(ValueError):
        host.bind_host_stream(service, caller="external-consumer", permissions=("observe",),
                               private_native=True)
