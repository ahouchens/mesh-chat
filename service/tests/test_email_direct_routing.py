from __future__ import annotations

import json
import os
import time
import uuid

import pytest
import RNS

from mesh_chat.connectivity import ConnectivityError
from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.participant import (
    connection_response_formats,
    create_access_document,
    create_connection_response,
    create_email_invitation,
    create_route_update,
    email_invitation_formats,
    route_update_formats,
    verify_connection_response,
    verify_email_invitation,
    verify_route_update,
)
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


NOW = 1_800_000_000


def callback_access(identity: RNS.Identity, *, port: int = 4242) -> dict[str, object]:
    return create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": port, "path": "pcp"}],
        network_name="callback_network_123456",
        passphrase="callback_passphrase_123456789",
        mode="participant_callback",
        now=NOW,
        expires_at=NOW + 3600,
    )


def test_v4_round_trip_with_and_without_inviter_candidates() -> None:
    inviter = RNS.Identity()
    inner = create_invitation(inviter, "Inviter", now=NOW)["file"]
    direct = create_access_document(
        inviter,
        [{"host": "93.184.216.34", "port": 4242, "path": "upnp"}],
        network_name="inviter_network_123456",
        passphrase="inviter_passphrase_123456789",
        now=NOW,
        expires_at=NOW + 3600,
    )

    for access in (direct, None):
        raw = create_email_invitation(
            inviter,
            "personal",
            inner,
            access,
            now=NOW,
            reply_challenge=b"r" * 32,
        )
        formats = email_invitation_formats(raw, "personal")
        assert formats["text"].startswith("MESHCHAT4:")
        for encoded in (raw, formats["text"], formats["link"]):
            verified = verify_email_invitation(encoded, "personal", now=NOW + 1)
            assert verified is not None
            assert verified.inner == inner
            assert (verified.inviter_access is None) == (access is None)
            assert len(bytes.fromhex(verified.digest)) == 32

    tampered = json.loads(raw)
    tampered["reply_challenge"] = "YQ"
    with pytest.raises(ValidationError):
        verify_email_invitation(json.dumps(tampered), "personal", now=NOW + 1)


def test_connection_response_is_bound_to_exact_invitation_challenge_and_identities() -> None:
    inviter = RNS.Identity()
    responder = RNS.Identity()
    inner = create_invitation(inviter, "Inviter", now=NOW)["file"]
    first = create_email_invitation(
        inviter, "personal", inner, None, now=NOW, reply_challenge=b"a" * 32
    )
    second = create_email_invitation(
        inviter, "personal", inner, None, now=NOW, reply_challenge=b"b" * 32
    )
    first_verified = verify_email_invitation(first, "personal", now=NOW)
    second_verified = verify_email_invitation(second, "personal", now=NOW)
    assert first_verified is not None and second_verified is not None
    response = create_connection_response(
        responder, first, "personal", callback_access(responder), now=NOW
    )
    formats = connection_response_formats(response)
    assert formats["text"].startswith("MESHCONNECT1:")
    verified = verify_connection_response(
        formats["text"], invitation=first_verified, now=NOW + 1
    )
    assert verified.responder_destination == RNS.Destination.hash(
        responder, "lxmf", "delivery"
    )
    with pytest.raises(IdentityMismatch):
        verify_connection_response(
            response, invitation=second_verified, now=NOW + 1
        )

    tampered = json.loads(response)
    tampered["reply_challenge"] = second_verified.reply_challenge
    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_connection_response(json.dumps(tampered), now=NOW + 1)
    with pytest.raises(InvitationExpired, match="expired"):
        verify_connection_response(response, invitation=first_verified, now=NOW + 3601)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update({"generation": "1"}),
        lambda value: value["access"].update({"mode": "participant_direct"}),
    ],
)
def test_route_update_rejects_unknown_fields_types_and_wrong_access_mode(mutation) -> None:
    issuer = RNS.Identity()
    audience = RNS.Destination.hash(RNS.Identity(), "lxmf", "delivery")
    raw = create_route_update(
        issuer,
        scope_kind="contact",
        scope_id="a" * 64,
        audience_destination=audience,
        generation=1,
        access=callback_access(issuer),
        now=NOW,
    )
    assert route_update_formats(raw)["text"].startswith("MESHROUTE1:")
    value = json.loads(raw)
    mutation(value)
    with pytest.raises(ValidationError):
        verify_route_update(json.dumps(value), now=NOW + 1)


def test_connection_documents_reject_oversize_and_excessive_nesting() -> None:
    with pytest.raises(ValidationError):
        verify_connection_response("MESHCONNECT1:" + "a" * (90 * 1024))
    nested: object = "leaf"
    for _ in range(12):
        nested = {"x": nested}
    with pytest.raises(ValidationError, match="nesting"):
        verify_connection_response(json.dumps({"v": 1, "x": nested}))


class FakeNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.applied: list[tuple[list[dict], list[dict]]] = []
        self.remembered: list[bytes] = []

    def invitation_hints(self):
        return []

    def apply_participant_interfaces(self, listeners, clients):
        self.applied.append((list(listeners), list(clients)))

    def reannounce(self):
        return None

    def remember_contact(self, _public_key, destination):
        self.remembered.append(destination)

    def shutdown(self):
        return True

    def snapshot(self):
        return {"interface_available": True, "interfaces": []}


def service(tmp_path, name: str) -> MeshChatService:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    result = MeshChatService(store, tmp_path, lambda _event: None)
    result._start_network = lambda _name: None  # type: ignore[method-assign]
    result.create_profile(name)
    result.network = FakeNetwork()  # type: ignore[assignment]
    return result


def test_service_reply_preview_is_side_effect_free_and_import_is_single_use(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inviter = service(tmp_path / "inviter", "Inviter")
    responder = service(tmp_path / "responder", "Responder")
    calls = {"resolve": 0}

    monkeypatch.setattr(
        "mesh_chat.participant_service.public_ipv4_addresses", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.global_ipv6_addresses", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.create_port_mapping",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ConnectivityError("pcp", "pcp_no_response")
        ),
    )
    invitation = inviter.invitation(connection_mode="email")
    assert invitation["text"].startswith("MESHCHAT4:")
    assert verify_email_invitation(invitation["text"], "personal").inviter_access is None  # type: ignore[union-attr]

    monkeypatch.setattr(
        "mesh_chat.participant_service.public_ipv4_addresses",
        lambda **_kwargs: ["93.184.216.34"],
    )
    reply = responder.create_connection_reply(invitation["text"], "personal")
    assert reply["text"].startswith("MESHCONNECT1:")

    def resolve(endpoint):
        calls["resolve"] += 1
        return [endpoint["host"]]

    monkeypatch.setattr("mesh_chat.participant_service.resolve_public_endpoint", resolve)
    monkeypatch.setattr(
        "mesh_chat.participant_service.candidate_connection_result",
        lambda *_args, **_kwargs: "connected",
    )
    before = inviter.store.list("participant_access")
    preview = inviter.preview_connection_reply(reply["text"])
    assert preview["responder_destination"]
    assert calls["resolve"] == 0
    assert inviter.store.list("participant_access") == before
    assert inviter.store.list("contact") == []
    rendered = json.dumps(inviter.snapshot(), sort_keys=True)
    assert "93.184.216.34" not in rendered
    assert "callback_passphrase" not in rendered

    connected = inviter.connect_using_reply(reply["text"])
    assert connected["connection_results"][0]["result"] == "connected"
    assert calls["resolve"] == 1
    assert inviter.store.list("contact") == []
    with pytest.raises(ValidationError, match="already used"):
        inviter.connect_using_reply(reply["text"])
    inviter.close()
    responder.close()


def test_workspace_v4_callback_does_not_admit_the_joiner(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = service(tmp_path / "workspace-owner", "Owner")
    joiner = service(tmp_path / "workspace-joiner", "Joiner")
    monkeypatch.setattr(
        "mesh_chat.participant_service.public_ipv4_addresses", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.global_ipv6_addresses", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.create_port_mapping",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ConnectivityError("pcp", "pcp_no_response")
        ),
    )
    workspace = owner.create_workspace(str(uuid.uuid4()), "Route lab", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], str(uuid.uuid4()), connection_mode="email"
    )
    assert invitation["text"].startswith("MESHWORKSPACE4:")
    verified_invitation = verify_email_invitation(
        invitation["text"], "workspace"
    )
    assert verified_invitation is not None
    with pytest.raises(IdentityMismatch):
        create_email_invitation(
            RNS.Identity(), "workspace", verified_invitation.inner
        )
    assert owner.preview_workspace_invitation(invitation["text"])[
        "connection_reply_available"
    ] is True

    monkeypatch.setattr(
        "mesh_chat.participant_service.public_ipv4_addresses",
        lambda **_kwargs: ["93.184.216.34"],
    )
    reply = joiner.create_connection_reply(invitation["text"], "workspace")
    preview = owner.preview_connection_reply(reply["text"])
    assert preview["purpose"] == "workspace"
    assert owner.workspace_snapshot()["workspace_join_requests"] == []
    manifest = owner._workspace_current_manifest(owner._require_workspace(workspace["id"]))
    assert len(manifest.members) == 1

    monkeypatch.setattr(
        "mesh_chat.participant_service.resolve_public_endpoint",
        lambda endpoint: [endpoint["host"]],
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.candidate_connection_result",
        lambda *_args, **_kwargs: "connected",
    )
    owner.connect_using_reply(reply["text"])
    manifest_after = owner._workspace_current_manifest(owner._require_workspace(workspace["id"]))
    assert len(manifest_after.members) == 1
    assert owner.workspace_snapshot()["workspace_join_requests"] == []
    owner.close()
    joiner.close()


def test_route_refresh_preserves_contact_approval_and_rejects_stale_generation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = service(tmp_path / "alice", "Alice")
    bob = service(tmp_path / "bob", "Bob")
    alice_invite = alice.invitation()
    bob_invite = bob.invitation()
    alice_contact = alice.accept_invitation(bob_invite["text"])
    bob_contact = bob.accept_invitation(alice_invite["text"])
    for owner, contact in ((alice, alice_contact), (bob, bob_contact)):
        stored = owner.store.get("contact", contact["id"])
        stored["trust"] = "verified"
        owner.store.put("contact", contact["id"], stored)

    monkeypatch.setattr(
        "mesh_chat.participant_service.public_ipv4_addresses",
        lambda **_kwargs: ["93.184.216.34"],
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.global_ipv6_addresses", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.resolve_public_endpoint",
        lambda endpoint: [endpoint["host"]],
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.candidate_connection_result",
        lambda *_args, **_kwargs: "connected",
    )
    update = bob.create_route_update_command("contact", bob_contact["id"])
    preview = alice.preview_route_update(update["text"])
    assert preview["issuer_display_name"] == "Bob"
    applied = alice.apply_route_update(update["text"])
    assert applied["generation"] == 1
    assert alice.store.get("contact", alice_contact["id"])["trust"] == "verified"
    with pytest.raises(ValidationError, match="stale"):
        alice.apply_route_update(update["text"])
    current = int(time.time())
    wrong_access = create_access_document(
        bob._identity,
        [{"host": "93.184.216.34", "port": 4243, "path": "pcp"}],
        network_name="wrong_scope_network_123456",
        passphrase="wrong_scope_passphrase_123456789",
        mode="participant_callback",
        now=current,
        expires_at=current + 3600,
    )
    wrong_scope = create_route_update(
        bob._identity,
        scope_kind="contact",
        scope_id="b" * 64,
        audience_destination=bytes.fromhex(alice._require_profile()["destination_hash"]),
        generation=2,
        access=wrong_access,
        now=current,
    )
    with pytest.raises(ValidationError, match="scope"):
        alice.preview_route_update(wrong_scope)
    alice.close()
    bob.close()
