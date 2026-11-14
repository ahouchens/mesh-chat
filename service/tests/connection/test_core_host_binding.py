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


def test_private_host_authorization_rechecks_before_a_real_mutation(service_host):
    service = service_host()
    admitted = [True]
    checks = []

    def authorize():
        checks.append(admitted[0])
        return admitted[0]

    session = host.bind_host_stream(service, caller="mesh-chat-desktop",
                                    permissions=("observe", "read", "send"),
                                    authorize=authorize)

    def exchange(value):
        return json.loads(session.exchange(frame(value)))

    capabilities = exchange(request("runtime.capabilities"))
    assert capabilities["ok"]
    profile = capabilities["result"]["profiles"][0]
    view = exchange(request("profile.query", profile=profile))
    assert view["ok"]
    recipient = view["result"]["peers"][0]

    def enqueue(text, key):
        value = request("message.enqueue", profile=profile, recipient=recipient,
                        kind="text", text=text)
        value["idempotency_key"] = key
        return exchange(value)

    assert enqueue("Admitted", "host-hook-allowed-0001")["ok"]
    assert [item["text"] for item in service.store.list("message")] == ["Admitted"]
    admitted[0] = False
    denied = enqueue("Revoked", "host-hook-revoked-0001")
    assert denied["error"]["code"] == "unauthenticated"
    assert [item["text"] for item in service.store.list("message")] == ["Admitted"]
    assert checks == [True, True, True, False]


def test_private_host_authorization_failure_closes_session_before_effect(service_host):
    service = service_host()
    checks = [0]

    def authorize():
        checks[0] += 1
        if checks[0] > 2:
            raise OSError("private authority query failed")
        return True

    session = host.bind_host_stream(service, caller="mesh-chat-desktop",
                                    permissions=("observe", "read", "send"),
                                    authorize=authorize)

    def exchange(value):
        return json.loads(session.exchange(frame(value)))

    profile = exchange(request("runtime.capabilities"))["result"]["profiles"][0]
    recipient = exchange(request("profile.query", profile=profile))["result"]["peers"][0]
    value = request("message.enqueue", profile=profile, recipient=recipient,
                    kind="text", text="Must not send")
    value["idempotency_key"] = "host-hook-failed-0001"
    assert exchange(value)["error"]["code"] == "unauthenticated"
    assert service.store.list("message") == []
    assert exchange(request("runtime.capabilities"))["error"]["code"] == "unauthenticated"
    assert checks == [3]


def test_private_host_authorization_accepts_only_a_callable_and_literal_true(service_host):
    service = service_host()
    with pytest.raises(ValueError):
        host.bind_host_stream(service, caller="mesh-chat-desktop", permissions=("observe",),
                              authorize=True)
    session = host.bind_host_stream(service, caller="mesh-chat-desktop",
                                    permissions=("observe",), authorize=lambda: 1)
    denied = json.loads(session.exchange(frame(request("runtime.capabilities"))))
    assert denied["error"]["code"] == "unauthenticated"


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
