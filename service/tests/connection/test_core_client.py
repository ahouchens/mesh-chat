"""Strict Python client and CLI over the private frame contract."""

import io
import json

import pytest

from mesh_chat.core_api.cli import main, run as run_cli
from mesh_chat.core_api.client import CoreClient, CoreClientError
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame

PROFILE = "p" * 64
PEER = "q" * 64
MESSAGE = "m" * 64


class Scripted:
    def __init__(self, *frames):
        self.frames = list(frames)
        self.written = []
        self.closed = False

    def readline(self, limit=0):
        return self.frames.pop(0) if self.frames else b""

    def write(self, payload):
        self.written.append(payload)
        return len(payload)

    def close(self):
        self.closed = True


def reply(result, request_id="client:1"):
    return encode_frame({"api_version": 1, "request_id": request_id, "ok": True, "result": result})


def failure(code, request_id="client:1", retry=None):
    return encode_frame({"api_version": 1, "request_id": request_id, "ok": False,
                         "error": {"code": code, "retry_after_ms": retry}})


CAPABILITIES = {"api_major": 1, "api_minor": 0, "stability": "experimental",
                "operations": ["runtime.capabilities", "profile.query", "message.received"],
                "profiles": [PROFILE], "limits": {"frame_bytes": 4194304}}


def test_client_negotiates_and_sends_the_declared_envelope():
    transport = Scripted(reply(CAPABILITIES))
    client = CoreClient.open(transport.readline, transport.write)
    assert client.capabilities["profiles"] == [PROFILE]
    sent = decode_frame(transport.written[0])
    assert sent == {"api_version": 1, "request_id": "client:1",
                    "operation": "runtime.capabilities", "params": {}}


def test_client_raises_typed_errors_with_retry_hint():
    transport = Scripted(reply(CAPABILITIES), failure("resync_required", "client:2", 1500))
    client = CoreClient.open(transport.readline, transport.write)
    with pytest.raises(CoreClientError) as raised:
        client.received(PROFILE)
    assert (raised.value.code, raised.value.request_id, raised.value.retry_after_ms) == (
        "resync_required", "client:2", 1500)


@pytest.mark.parametrize("frame,code", [
    (b"{not json}\n", "protocol"),
    (encode_frame({"api_version": 2, "request_id": "client:2", "ok": True, "result": {}}), "protocol"),
    (encode_frame({"api_version": 1, "request_id": "client:9", "ok": True, "result": {}}), "protocol"),
    (b"", "transport_closed"),
])
def test_malformed_or_misrouted_responses_fail_closed(frame, code):
    transport = Scripted(reply(CAPABILITIES), frame)
    client = CoreClient.open(transport.readline, transport.write)
    with pytest.raises(CoreClientError) as raised:
        client.profile(PROFILE)
    assert raised.value.code == code


def test_helpers_send_declared_parameters_and_idempotency_keys():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "messages": [], "next_cursor": None, "more": False}, "client:2"),
        reply({"profile": PROFILE, "message": MESSAGE, "accepted": True, "accepted_at": 1,
               "idempotency_expires_at": 2}, "client:3"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    client.received(PROFILE, "cursor-token-0001", 7)
    client.enqueue(PROFILE, PEER, "Hello", "enqueue-key-0001")
    assert decode_frame(transport.written[1])["params"] == {
        "profile": PROFILE, "cursor": "cursor-token-0001", "limit": 7}
    assert decode_frame(transport.written[2])["idempotency_key"] == "enqueue-key-0001"


def test_cli_prints_the_selected_result_as_json():
    page = {"profile": PROFILE, "messages": [], "next_cursor": None, "more": False}
    transport = Scripted(reply(CAPABILITIES), reply(page, "client:2"))
    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "received", "--limit", "4"],
                   transport, out, err) == 0
    assert json.loads(out.getvalue())["messages"] == []
    assert err.getvalue() == ""
    assert decode_frame(transport.written[1])["params"]["limit"] == 4


def test_cli_maps_typed_failures_to_a_nonzero_exit_without_raising():
    transport = Scripted(reply(CAPABILITIES), failure("forbidden", "client:2"))
    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "profile"], transport, out, err) == 2
    assert json.loads(err.getvalue())["error"] == "forbidden"
    assert out.getvalue() == ""


def test_cli_rejects_unknown_commands():
    with pytest.raises(SystemExit) as raised:
        run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "explode"], Scripted(), io.StringIO(), io.StringIO())
    assert raised.value.code == 2


def test_client_relationship_and_pairing_helpers_reuse_the_contract():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "peer": PEER, "trust": "approved"}, "client:2"),
        reply({"profile": PROFILE, "peer": PEER, "trust": "blocked"}, "client:3"),
        reply({"profile": PROFILE, "file": "signed", "link": "meshchat://invite/t", "expires_at": 1},
              "client:4"),
        reply({"profile": PROFILE, "peer": PEER, "trust": "awaiting_consent"}, "client:5"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.approve(PROFILE, PEER)["trust"] == "approved"
    assert client.revoke(PROFILE, PEER)["trust"] == "blocked"
    assert client.pairing_create(PROFILE)["file"] == "signed"
    assert client.pairing_accept(PROFILE, "signed")["trust"] == "awaiting_consent"
    sent = [decode_frame(payload) for payload in transport.written]
    assert sent[1] == {"api_version": 1, "request_id": "client:2", "operation": "peer.approve",
                       "params": {"profile": PROFILE, "peer": PEER}}
    assert sent[4]["operation"] == "peer.pairing_accept"
    assert sent[4]["params"] == {"profile": PROFILE, "document": "signed"}


def test_client_refuses_to_dispatch_an_empty_pairing_document():
    transport = Scripted(reply(CAPABILITIES))
    client = CoreClient.open(transport.readline, transport.write)
    with pytest.raises(ValueError):
        client.pairing_accept(PROFILE, "")
    assert len(transport.written) == 1


def test_client_device_link_decisions_use_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64,
               "links": [{"request": "r" * 64, "state": "pending"}]}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "link": "r" * 64,
               "state": "approved"}, "client:3"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "link": "r" * 64,
               "state": "declined"}, "client:4"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_device_links(PROFILE, "w" * 64)["links"][0]["request"] == "r" * 64
    assert client.workspace_device_link_approve(
        PROFILE, "w" * 64, "r" * 64, "d" * 16)["state"] == "approved"
    assert client.workspace_device_link_decline(
        PROFILE, "w" * 64, "r" * 64, "e" * 16)["state"] == "declined"
    approve = decode_frame(transport.written[2])
    decline = decode_frame(transport.written[3])
    assert approve["operation"] == "workspace.device_link_approve"
    assert decline["operation"] == "workspace.device_link_decline"
    assert approve["params"]["request"] == "r" * 64


def test_client_device_link_submit_uses_the_declared_envelope():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64, "name": "Core",
               "state": "linking"}, "client:2"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    submitted = client.workspace_device_link_submit(PROFILE, "link-document", "s" * 16)
    assert submitted["state"] == "linking"
    sent = decode_frame(transport.written[1])
    assert sent["operation"] == "workspace.device_link_submit"
    assert sent["idempotency_key"] == "s" * 16


def test_client_device_link_helpers_use_the_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64, "document": "link-document",
               "link": "meshchat://workspace-device/token", "expires_at": 1}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "name": "Core",
               "member_display_name": "Alex", "device_count": 1, "expires_at": 1}, "client:3"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    created = client.workspace_device_link_create(PROFILE, "w" * 64, "l" * 16)
    assert created["document"] == "link-document"
    assert client.workspace_device_link_preview(PROFILE, "link-document")["device_count"] == 1
    create, preview = (decode_frame(payload) for payload in transport.written[1:])
    assert create["operation"] == "workspace.device_link_create"
    assert create["idempotency_key"] == "l" * 16
    assert preview["operation"] == "workspace.device_link_preview"


def test_client_policy_update_uses_the_declared_envelope():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64,
               "channel_creation": "owner_and_admins", "posting": "owner_and_admins",
               "invitation_requests": "owner_only"}, "client:2"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    applied = client.workspace_policy_update(
        PROFILE, "w" * 64, "owner_and_admins", "owner_and_admins", "owner_only", "y" * 16)
    assert applied["posting"] == "owner_and_admins"
    sent = decode_frame(transport.written[1])
    assert sent["operation"] == "workspace.policy_update"
    assert sent["idempotency_key"] == "y" * 16


def test_client_channel_transfer_helpers_use_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "member": "m" * 64, "state": "offered"}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "state": "accepted"}, "client:3"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_channel_transfer_offer(
        PROFILE, "w" * 64, "c" * 64, "m" * 64, "o" * 16)["state"] == "offered"
    assert client.workspace_channel_transfer_accept(
        PROFILE, "w" * 64, "c" * 64, "a" * 16)["state"] == "accepted"
    assert decode_frame(transport.written[1])["operation"] == "workspace.channel_transfer_offer"
    assert decode_frame(transport.written[2])["operation"] == "workspace.channel_transfer_accept"


def test_client_channel_archive_uses_the_declared_envelope():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "state": "archived"}, "client:2"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_channel_archive(PROFILE, "w" * 64, "c" * 64, "r" * 16)["state"] == "archived"
    sent = decode_frame(transport.written[1])
    assert sent["operation"] == "workspace.channel_archive"
    assert sent["idempotency_key"] == "r" * 16


def test_client_channel_edit_helpers_use_the_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "members": ["m" * 64]}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "members": ["m" * 64]}, "client:3"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "name": "Renamed", "topic": "Ops", "visibility": "private"}, "client:4"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_channel_members(PROFILE, "w" * 64, "c" * 64)["members"] == ["m" * 64]
    client.workspace_channel_members_update(PROFILE, "w" * 64, "c" * 64, ["m" * 64], "m" * 16)
    edited = client.workspace_channel_update(PROFILE, "w" * 64, "c" * 64, "Renamed", "Ops", "e" * 16)
    assert edited["name"] == "Renamed"
    roster, update = (decode_frame(payload) for payload in transport.written[2:])
    assert roster["operation"] == "workspace.channel_members_update"
    assert roster["idempotency_key"] == "m" * 16
    assert update["operation"] == "workspace.channel_update"
    assert update["params"]["topic"] == "Ops"


def test_client_channel_helpers_use_the_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64,
               "channels": [{"channel": "c" * 64, "name": "General",
                             "visibility": "public", "state": "active"}]}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "channel": "c" * 64,
               "name": "Core Chat", "visibility": "public"}, "client:3"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_channels(PROFILE, "w" * 64)["channels"][0]["name"] == "General"
    created = client.workspace_channel_create(PROFILE, "w" * 64, "Core Chat", "c" * 16)
    assert created["name"] == "Core Chat"
    channels, create = (decode_frame(payload) for payload in transport.written[1:])
    assert channels["operation"] == "workspace.channels"
    assert create["operation"] == "workspace.channel_create"
    assert create["idempotency_key"] == "c" * 16
    assert create["params"]["name"] == "Core Chat"


def test_client_workspace_review_helpers_use_the_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "workspace": "w" * 64,
               "members": [{"member": "m" * 64, "display_name": "Blair",
                            "role": "member", "status": "active"}]}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "decision": "declined"}, "client:3"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "member": "m" * 64,
               "role": "admin"}, "client:4"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_members(PROFILE, "w" * 64)["members"][0]["role"] == "member"
    assert client.workspace_join_decline(PROFILE, "w" * 64, "r" * 64, "d" * 16)["decision"] == "declined"
    assert client.workspace_member_role(PROFILE, "w" * 64, "m" * 64, "admin", "r" * 16)["role"] == "admin"
    members, decline, role = (decode_frame(payload) for payload in transport.written[1:])
    assert members["operation"] == "workspace.members"
    assert decline["operation"] == "workspace.join_decline" and decline["idempotency_key"] == "d" * 16
    assert role["operation"] == "workspace.member_role"
    assert role["params"] == {"profile": PROFILE, "workspace": "w" * 64,
                              "member": "m" * 64, "role": "admin"}


def test_client_workspace_helpers_use_the_declared_envelopes():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "name": "Core", "description": "", "member_count": 1,
               "retention_days": 30, "expires_at": 1, "requires_i2p_consent": False}, "client:2"),
        reply({"profile": PROFILE, "workspace": "w" * 64, "name": "Core", "state": "joining"},
              "client:3"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    assert client.workspace_preview(PROFILE, "invitation")["name"] == "Core"
    assert client.workspace_join(PROFILE, "invitation", "k" * 16)["state"] == "joining"
    preview, join = (decode_frame(payload) for payload in transport.written[1:])
    assert preview["operation"] == "workspace.invitation_preview"
    assert preview["params"] == {"profile": PROFILE, "document": "invitation"}
    assert "idempotency_key" not in preview
    assert join["operation"] == "workspace.join"
    assert join["idempotency_key"] == "k" * 16


def test_client_pairing_request_uses_the_declared_envelope():
    transport = Scripted(reply(CAPABILITIES),
                         reply({"profile": PROFILE, "peer": PEER, "state": "requested"},
                               "client:2"))
    client = CoreClient.open(transport.readline, transport.write)
    assert client.pairing_request(PROFILE, PEER)["state"] == "requested"
    sent = decode_frame(transport.written[1])
    assert sent == {"api_version": 1, "request_id": "client:2",
                    "operation": "peer.pairing_request",
                    "params": {"profile": PROFILE, "peer": PEER}}


def test_client_stop_asks_the_owner_without_a_key():
    transport = Scripted(reply(CAPABILITIES),
                         reply({"stopping": True, "already_stopping": False}, "client:2"))
    client = CoreClient.open(transport.readline, transport.write)
    assert client.stop() == {"stopping": True, "already_stopping": False}
    sent = decode_frame(transport.written[1])
    assert sent == {"api_version": 1, "request_id": "client:2", "operation": "runtime.stop",
                    "params": {}}


def test_cli_dispatches_relationship_pairing_and_owner_commands(tmp_path):
    document = tmp_path / "invitation.txt"
    document.write_text("signed-invitation", encoding="utf-8")
    results = [
        ({"profile": PROFILE, "peer": PEER, "trust": "approved"},
         ["--pipe", "pipe", "--profile", PROFILE, "approve", "--peer", PEER]),
        ({"profile": PROFILE, "peer": PEER, "trust": "blocked"},
         ["--pipe", "pipe", "--profile", PROFILE, "revoke", "--peer", PEER]),
        ({"profile": PROFILE, "file": "signed", "link": "meshchat://invite/t", "expires_at": 1},
         ["--pipe", "pipe", "--profile", PROFILE, "pairing-create"]),
        ({"profile": PROFILE, "peer": PEER, "trust": "awaiting_consent"},
         ["--pipe", "pipe", "--profile", PROFILE, "pairing-accept",
          "--document-file", str(document)]),
        ({"stopping": True, "already_stopping": False},
         ["--pipe", "pipe", "--profile", PROFILE, "stop"]),
    ]
    sent = []
    for result, argv in results:
        transport = Scripted(reply(CAPABILITIES), reply(result, "client:2"))
        out, err = io.StringIO(), io.StringIO()
        assert run_cli(argv, transport, out, err) == 0, err.getvalue()
        sent.extend(decode_frame(payload) for payload in transport.written)
    assert [item["operation"] for item in sent if item["operation"] != "runtime.capabilities"] == [
        "peer.approve", "peer.revoke", "peer.pairing_create", "peer.pairing_accept", "runtime.stop"]
    accept = next(item for item in sent if item["operation"] == "peer.pairing_accept")
    assert accept["params"] == {"profile": PROFILE, "document": "signed-invitation"}


def test_cli_reports_an_unreadable_pairing_document():
    transport = Scripted(reply(CAPABILITIES))
    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", "pipe", "--profile", PROFILE, "pairing-accept",
                    "--document-file", "missing-invitation.txt"], transport, out, err) == 2
    assert json.loads(err.getvalue())["error"] == "invalid_document"


def test_cli_version_reports_the_component_version(capsys):
    from mesh_chat.core_api import __version__

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_cli_dispatches_workspace_and_device_commands(tmp_path):
    document = tmp_path / "device-link.txt"
    document.write_text("signed-device-link", encoding="utf-8")

    def invoke(command, body):
        transport = Scripted(reply(CAPABILITIES), reply(body, "client:2"))
        out, err = io.StringIO(), io.StringIO()
        assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", *command],
                       transport, out, err) == 0
        assert err.getvalue() == ""
        return transport, json.loads(out.getvalue())

    transport, result = invoke(["workspace-channels", "--workspace", "w" * 64],
                               {"profile": PROFILE, "workspace": "w" * 64,
                                "channels": [{"channel": "c" * 64, "name": "Core",
                                              "visibility": "public", "state": "active"}]})
    assert result["channels"][0]["name"] == "Core"
    transport, result = invoke(["workspace-channel-create", "--workspace", "w" * 64,
                                "--name", "Secret", "--visibility", "private",
                                "--member", "m" * 64, "--key", "k" * 16],
                               {"profile": PROFILE, "workspace": "w" * 64,
                                "channel": "c" * 64, "name": "Secret",
                                "visibility": "private"})
    assert decode_frame(transport.written[1])["params"]["members"] == ["m" * 64]
    transport, result = invoke(["workspace-channel-archive", "--workspace", "w" * 64,
                                "--channel", "c" * 64, "--key", "r" * 16],
                               {"profile": PROFILE, "workspace": "w" * 64,
                                "channel": "c" * 64, "state": "archived"})
    assert result["state"] == "archived"
    transport, result = invoke(["workspace-device-link-create", "--workspace", "w" * 64,
                                "--key", "l" * 16],
                               {"profile": PROFILE, "workspace": "w" * 64,
                                "document": "signed-device-link",
                                "link": "meshchat://workspace-device/token", "expires_at": 1})
    assert result["document"] == "signed-device-link"
    transport, result = invoke(["workspace-device-link-preview",
                                "--document-file", str(document)],
                               {"profile": PROFILE, "workspace": "w" * 64, "name": "Core",
                                "member_display_name": "Alex", "device_count": 1,
                                "expires_at": 1})
    assert result["device_count"] == 1
    assert decode_frame(transport.written[1])["params"]["document"] == "signed-device-link"
