"""End-to-end Python client and CLI against the real framed facade."""

import io
import json
import os
import threading

import pytest

from mesh_chat.core_api.cli import run as run_cli
from mesh_chat.core_api.client import CoreClient, CoreClientError
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from test_core_messages import host


PROFILE_PERMISSIONS = frozenset({"observe", "read", "send"})


class HostedClient:
    def __init__(self, service, permissions=PROFILE_PERMISSIONS, *, private_native=False):
        server_read, client_write = os.pipe()
        client_read, server_write = os.pipe()
        grants = [Grant("alex", permissions, ("local",))]
        session = bind_service_stream(service, lambda: grants[0], private_native=private_native)

        def serve():
            with os.fdopen(server_read, "rb", buffering=0) as reader, \
                    os.fdopen(server_write, "wb", buffering=0) as writer:
                session.serve(reader, writer)

        self.thread = threading.Thread(target=serve, name="core-api-test-host", daemon=True)
        self.reader = os.fdopen(client_read, "rb", buffering=0)
        self.writer = os.fdopen(client_write, "wb", buffering=0)
        self.thread.start()

    def close(self):
        self.reader.close()
        self.writer.close()
        self.thread.join(5)
        assert not self.thread.is_alive()


@pytest.fixture
def hosted(host):
    client = HostedClient(host())
    yield client
    client.close()


def test_client_round_trip_against_the_real_facade(hosted):
    client = CoreClient.open(hosted.reader.readline, hosted.writer.write)
    assert "message.received" in client.capabilities["operations"]
    profile = client.capabilities["profiles"][0]
    peers = client.profile(profile)["peers"]
    assert peers, "the fixture contact must be visible"
    accepted = client.enqueue(profile, peers[0], "Hello over a real frame", "enqueue-key-0001")
    assert accepted["accepted"] is True
    queried = client.request("message.query", {"profile": profile, "message": accepted["message"]})
    assert queried["text"] == "Hello over a real frame"
    assert client.received(profile)["messages"] == []
    snapshot = client.request("message.list", {"profile": profile, "cursor": None, "limit": 128})
    replay = client.poll(profile, snapshot["events_cursor"])
    assert isinstance(replay["events"], list)
    with pytest.raises(CoreClientError) as raised:
        client.poll(profile)
    assert raised.value.code == "resync_required"


def test_cli_runs_against_the_real_facade(hosted):
    class Transport:
        readline = staticmethod(hosted.reader.readline)
        write = staticmethod(hosted.writer.write)

        @staticmethod
        def close():
            return None

    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "capabilities"], Transport(), out, err) == 0
    result = json.loads(out.getvalue())
    assert "connection.start" in result["operations"]
    assert err.getvalue() == ""


def test_cli_lists_and_creates_a_workspace_invitation(host):
    service = host()
    workspace = service.create_workspace("00000000-0000-4000-8000-000000000001", "CLI workspace", "")
    owner_permissions = frozenset({"observe", "read", "approve"})
    listed = HostedClient(service, owner_permissions)
    try:
        class Transport:
            readline = staticmethod(listed.reader.readline)
            write = staticmethod(listed.writer.write)
            close = staticmethod(lambda: None)

        out, err = io.StringIO(), io.StringIO()
        assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "workspace-list"],
                       Transport(), out, err) == 0
        handle = json.loads(out.getvalue())["workspaces"][0]["workspace"]
    finally:
        listed.close()

    created = HostedClient(service, owner_permissions)
    try:
        class Transport:
            readline = staticmethod(created.reader.readline)
            write = staticmethod(created.writer.write)
            close = staticmethod(lambda: None)

        relay = "a" * 52 + ".b32.i2p"
        out, err = io.StringIO(), io.StringIO()
        assert run_cli([
            "--pipe", r"\\.\pipe\mesh-chat-test", "workspace-invitation-create",
            "--workspace", handle, "--mode", "i2p",
            "--i2p-access-point", relay, "--key", "k" * 32,
        ], Transport(), out, err) == 0
        result = json.loads(out.getvalue())
        assert result["connection_mode"] == "i2p"
        assert result["i2p_access_point"] == relay
        assert result["document"]
    finally:
        created.close()


def test_facade_peer_lifecycle_unblocks_and_deletes(host):
    service = host()
    service.block_contact("internal-peer")
    owner = HostedClient(service, frozenset({"observe", "read", "approve"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        query = client.profile(profile)
        peer = next(
            handle for handle in query["peers"]
            if client.peer_query(profile, handle)["destination"] == "ab" * 16
        )
        assert client.unblock(profile, peer)["trust"] == "approved"
        assert client.delete_peer(profile, peer)["deleted"] is True
        assert service.store.get("contact", "internal-peer") is None
    finally:
        owner.close()


def test_facade_group_query_returns_caller_scoped_handles(host):
    service = host()
    service.store.put("group", "group-1", {
        "id": "group-1", "title": "Team", "posting_policy": "members",
        "members": [], "epoch": 0,
    })
    owner = HostedClient(service, frozenset({"observe", "read"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        groups = client.groups(profile)["groups"]
        assert [(group["name"], group["posting_policy"]) for group in groups] == [
            ("Team", "members")]
        assert all(len(group["group"]) >= 16 for group in groups)
    finally:
        owner.close()


def test_facade_reaction_set_uses_the_message_handle(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "send", "approve"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        peers = client.profile(profile)["peers"]
        peer = next(
            handle for handle in peers
            if client.peer_query(profile, handle)["destination"] == "ab" * 16
        )
        accepted = client.enqueue(profile, peer, "React to this", "enqueue-key-0002")
        reaction = client.reaction_set(profile, accepted["message"], "👍", True)
        assert reaction["emoji"] == "👍" and reaction["active"] is True
        assert reaction["scope"] == "direct"
    finally:
        owner.close()


def test_facade_draft_round_trip_uses_the_peer_handle(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "send", "approve"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        peers = client.profile(profile)["peers"]
        peer = next(
            handle for handle in peers
            if client.peer_query(profile, handle)["destination"] == "ab" * 16
        )
        saved = client.draft_set(profile, peer, "Half-written reply")
        assert saved["text"] == "Half-written reply"
        assert client.draft_get(profile, peer)["text"] == "Half-written reply"
    finally:
        owner.close()


def test_facade_call_settings_round_trip(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "send"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        initial = client.call_settings_get(profile)["settings"]
        updated = client.call_settings_update(profile, {
            "stun_urls": initial["stun_urls"],
            "turn_url": initial["turn_url"],
            "turn_username": initial["turn_username"],
            "turn_broker_url": initial["turn_broker_url"],
            "turn_broker_consent": initial["turn_broker_consent"],
            "signal_mailbox_url": initial["signal_mailbox_url"],
            "store_call_signaling": False,
            "relay_only": False,
        })
        assert updated["settings"]["store_call_signaling"] is False
        assert service.call_settings()["store_call_signaling"] is False
    finally:
        owner.close()


def test_native_command_requires_explicit_private_host_binding_and_is_allowlisted(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "approve"}), private_native=True)
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        snapshot = client.native_command("workspace_snapshot", {})
        assert isinstance(snapshot, dict)
        with pytest.raises(CoreClientError):
            client.native_command("arbitrary_shell", {})
    finally:
        owner.close()
    consumer = HostedClient(service)
    try:
        client = CoreClient.open(consumer.reader.readline, consumer.writer.write)
        with pytest.raises(CoreClientError) as raised:
            client.native_command("workspace_snapshot", {})
        assert raised.value.code == "unsupported_operation"
    finally:
        consumer.close()


def test_facade_application_snapshot_returns_ui_state(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "approve"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        snapshot = client.request("application.snapshot", {})
        assert snapshot["profile"]["display_name"] == "Alex"
        assert isinstance(snapshot["contacts"], list)
        assert isinstance(snapshot["messages"], list)
        assert all(len(contact["core_handle"]) >= 16 for contact in snapshot["contacts"])
    finally:
        owner.close()


@pytest.mark.parametrize("message_count", [30, 256])
def test_client_accepts_real_message_history_above_request_token_budget(host, message_count):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "send", "approve"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        peer = client.profile(profile)["peers"][0]
        texts = {f"Impaired receipt {index}:" + "x" * 1024 for index in range(message_count)}
        for index, text in enumerate(sorted(texts)):
            assert client.enqueue(profile, peer, text, f"history-receipt-{index:04d}")["accepted"]
        snapshot = client.application_snapshot()
        assert {item["text"] for item in snapshot["messages"]} == texts
        assert len(json.dumps(snapshot).encode()) < 4 * 1024 * 1024
        assert client.request("runtime.capabilities")["api_major"] == 1
    finally:
        owner.close()


def test_call_control_executes_real_signed_invite_and_hangup_through_core(host):
    service = host()
    owner = HostedClient(service)
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    sdp = "\r\n".join(["v=0", "o=- 1 2 IN IP4 127.0.0.1", "s=-", "t=0 0",
                         "a=fingerprint:" + fingerprint,
                         "m=audio 9 UDP/TLS/RTP/SAVPF 111", "a=mid:0"]) + "\r\n"
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        started = client.request("call.control", {"profile": profile, "action": "start",
            "contact_id": "internal-peer", "media": "audio", "sdp": sdp,
            "dtls_fingerprint": fingerprint}, idempotency_key="start-call-core-key")
        call = started["result"]
        assert call["state"] == "dialing"
        assert service.store.get("call", call["id"])["state"] == "dialing"
        invites = service.store.list("message")
        assert len(invites) == 1 and invites[0]["kind"] == "call_signal"
        document = json.loads(invites[0]["text"])
        assert document["call_id"] == call["id"]
        ended = client.request("call.control", {"profile": profile, "action": "end",
            "call_id": call["id"], "reason": "completed"}, idempotency_key="end-call-core-key00")
        assert ended["result"]["state"] == "ended"
        assert service.store.get("call", call["id"])["state"] == "ended"
        assert len(service.store.list("message")) == 2
    finally:
        owner.close()


def test_facade_workspace_create_returns_workspace_summary(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "approve"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        workspace = client.request(
            "workspace.create",
            {"profile": profile, "name": "Lakewatcher", "description": "Field"},
            idempotency_key="create-workspace-1",
        )
        assert workspace["name"] == "Lakewatcher"
        assert workspace["id"]
    finally:
        owner.close()


def test_facade_invitation_create_returns_complete_ui_material(host):
    service = host()
    owner = HostedClient(service, frozenset({"observe", "read", "approve", "pair"}))
    try:
        client = CoreClient.open(owner.reader.readline, owner.writer.write)
        profile = client.capabilities["profiles"][0]
        invitation = client.pairing_create(profile)
        assert invitation["text"].startswith("MESHCHAT1:")
        assert invitation["file"] and invitation["link"]
        assert invitation["expires_at"] > 0
    finally:
        owner.close()


def test_unknown_profile_handle_is_rejected_as_forbidden(hosted):
    client = CoreClient.open(hosted.reader.readline, hosted.writer.write)
    with pytest.raises(CoreClientError) as raised:
        client.received("a" * 64)
    assert raised.value.code == "forbidden"


def test_malformed_handle_is_rejected_as_invalid(hosted):
    client = CoreClient.open(hosted.reader.readline, hosted.writer.write)
    with pytest.raises(CoreClientError) as raised:
        client.received("not-a-handle")
    assert raised.value.code == "invalid_request"
