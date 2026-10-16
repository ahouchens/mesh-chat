from __future__ import annotations

import json
import os
import time
import uuid
from types import SimpleNamespace

import pytest
import RNS

from mesh_chat.app_protocol import conversation_id
from mesh_chat.connectivity import ConnectivityError
from mesh_chat.errors import (
    DirectConnectionUnavailable,
    IdentityMismatch,
    InvitationExpired,
    ValidationError,
)
from mesh_chat.invitations import create_invitation
from mesh_chat.models import Contact, TrustState
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
from mesh_chat.workspace_wire import WorkspaceWirePayload


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


def receive_workspace_join(
    owner: MeshChatService,
    joiner: MeshChatService,
    workspace_id: str,
    invitation: str,
) -> dict[str, object]:
    joiner.submit_workspace_join(invitation, str(uuid.uuid4()))
    delivery = joiner.store.list("workspace_delivery")[0]
    owner._receive_workspace_join(
        WorkspaceWirePayload(
            kind=delivery["kind"],
            logical_id=delivery["id"],
            workspace_id=workspace_id,
            expires_at=int(delivery["expires_at"]),
            document=delivery["document"],
        ),
        bytes.fromhex(joiner._require_profile()["destination_hash"]),
    )
    return owner.workspace_snapshot()["workspace_join_requests"][0]


def install_workspace_callback(
    owner: MeshChatService,
    joiner: MeshChatService,
    workspace_id: str,
    invitation_id: str,
    *,
    port: int,
    scopes: list[dict[str, str]],
) -> tuple[str, dict[str, object]]:
    email_digest = f"{port:064x}"
    invitation = owner.store.get("workspace_invitation", invitation_id)
    assert invitation is not None
    invitation["email_invitation_digest"] = email_digest
    owner.store.put("workspace_invitation", invitation_id, invitation)
    owner.store.put(
        "email_invitation",
        email_digest,
        {
            "id": email_digest,
            "purpose": "workspace",
            "scope_id": invitation_id,
            "workspace_id": workspace_id,
            "state": "consumed",
            "responder_destination": joiner._require_profile()["destination_hash"],
        },
    )
    now = int(time.time())
    identity = joiner._identity
    assert identity is not None
    access = create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": port, "path": "pcp"}],
        network_name=f"callback_network_{port}",
        passphrase=f"callback_passphrase_{port}_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "participant_access",
        access["id"],
        {
            "id": access["id"],
            "access": access,
            "scopes": scopes,
            "resolved_endpoints": list(access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )
    return email_digest, access


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


def test_personal_callback_waits_for_contact_approval_and_ignores_workspace_routes(
    tmp_path,
) -> None:
    owner = service(tmp_path / "personal-owner", "Owner")
    responder = service(tmp_path / "personal-responder", "Responder")
    responder_profile = responder._require_profile()
    responder_identity = responder._identity
    assert responder_identity is not None
    now = int(time.time())
    personal_digest = f"{4201:064x}"
    personal_scope = {"kind": "pending_invitation", "id": personal_digest}
    personal_access = create_access_document(
        responder_identity,
        [{"host": "93.184.216.34", "port": 4201, "path": "pcp"}],
        network_name="personal_pending_network",
        passphrase="personal_pending_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "email_invitation",
        personal_digest,
        {
            "id": personal_digest,
            "purpose": "personal",
            "state": "consumed",
            "responder_destination": responder_profile["destination_hash"],
        },
    )
    owner.store.put(
        "participant_access",
        personal_access["id"],
        {
            "id": personal_access["id"],
            "access": personal_access,
            "scopes": [personal_scope],
            "resolved_endpoints": list(personal_access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )

    workspace_digest = f"{4202:064x}"
    workspace_scope = {"kind": "pending_invitation", "id": workspace_digest}
    workspace_access = create_access_document(
        responder_identity,
        [{"host": "93.184.216.34", "port": 4202, "path": "pcp"}],
        network_name="workspace_pending_network",
        passphrase="workspace_pending_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "email_invitation",
        workspace_digest,
        {
            "id": workspace_digest,
            "purpose": "workspace",
            "state": "consumed",
            "responder_destination": responder_profile["destination_hash"],
        },
    )
    owner.store.put(
        "participant_access",
        workspace_access["id"],
        {
            "id": workspace_access["id"],
            "access": workspace_access,
            "scopes": [workspace_scope],
            "resolved_endpoints": list(workspace_access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )

    invitation = responder.invitation()["file"]
    owner_profile = owner._require_profile()
    owner._receive_contact_request(
        SimpleNamespace(
            source_hash=bytes.fromhex(responder_profile["destination_hash"])
        ),
        SimpleNamespace(
            invitation=invitation,
            conversation_id=conversation_id(
                bytes.fromhex(owner_profile["destination_hash"]),
                bytes.fromhex(responder_profile["destination_hash"]),
            ),
        ),
        None,
    )
    contact = owner.store.list("contact")[0]
    assert contact["trust"] == TrustState.PENDING_REQUEST.value
    assert owner.store.get("participant_access", personal_access["id"])[
        "scopes"
    ] == [personal_scope]

    owner._apply_contact_hints = lambda _contact: None  # type: ignore[method-assign]
    owner._flush_contact = lambda _contact_id: None  # type: ignore[method-assign]
    owner.approve_request(contact["id"])
    assert owner.store.get("participant_access", personal_access["id"])[
        "scopes"
    ] == [{"kind": "contact", "id": contact["id"]}]
    assert owner.store.get("participant_access", workspace_access["id"])[
        "scopes"
    ] == [workspace_scope]
    assert "promoted_scope" not in owner.store.get(
        "email_invitation", workspace_digest
    )
    owner.close()
    responder.close()


def test_personal_decline_releases_callback_without_touching_other_scopes(
    tmp_path,
) -> None:
    owner = service(tmp_path / "personal-decline-owner", "Owner")
    responder = service(tmp_path / "personal-decline-responder", "Responder")
    responder_profile = responder._require_profile()
    responder_identity = responder._identity
    assert responder_identity is not None
    now = int(time.time())
    contact = Contact(
        id="pending-contact",
        display_name="Responder",
        public_identity=responder_profile["public_identity"],
        identity_hash=responder_profile["identity_hash"],
        destination_hash=responder_profile["destination_hash"],
        fingerprint=responder_profile["fingerprint"],
        trust=TrustState.PENDING_REQUEST,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()
    owner.store.put("contact", contact["id"], contact)
    personal_digest = f"{4211:064x}"
    pending_scope = {"kind": "pending_invitation", "id": personal_digest}
    legacy_scope = {"kind": "contact", "id": contact["id"]}
    retained_scope = {"kind": "workspace_device", "id": "other-workspace"}
    owner.store.put(
        "email_invitation",
        personal_digest,
        {
            "id": personal_digest,
            "purpose": "personal",
            "state": "consumed",
            "responder_destination": responder_profile["destination_hash"],
            "promoted_scope": legacy_scope,
        },
    )
    pending_access = create_access_document(
        responder_identity,
        [{"host": "93.184.216.34", "port": 4211, "path": "pcp"}],
        network_name="declined_pending_network",
        passphrase="declined_pending_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "participant_access",
        pending_access["id"],
        {
            "id": pending_access["id"],
            "access": pending_access,
            "scopes": [pending_scope],
            "resolved_endpoints": list(pending_access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )
    legacy_access = create_access_document(
        responder_identity,
        [{"host": "93.184.216.34", "port": 4212, "path": "pcp"}],
        network_name="declined_legacy_network",
        passphrase="declined_legacy_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "participant_access",
        legacy_access["id"],
        {
            "id": legacy_access["id"],
            "access": legacy_access,
            "scopes": [legacy_scope, retained_scope],
            "resolved_endpoints": list(legacy_access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )

    owner._attempt = lambda _message_id: None  # type: ignore[method-assign]
    declined = owner.decline_request(contact["id"])
    assert declined["trust"] == TrustState.BLOCKED.value
    assert owner.store.get("participant_access", pending_access["id"]) is None
    legacy = owner.store.get("participant_access", legacy_access["id"])
    assert legacy is not None
    assert legacy["scopes"] == [retained_scope]
    callback = owner.store.get("email_invitation", personal_digest)
    assert callback is not None and callback["state"] == "declined"
    assert owner.network is not None
    assert {item["id"] for item in owner.network.applied[-1][1]} == {
        legacy_access["id"]
    }
    owner.close()
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


def test_workspace_callback_is_promoted_only_after_exact_join_approval(
    tmp_path,
) -> None:
    owner = service(tmp_path / "promotion-owner", "Owner")
    joiner = service(tmp_path / "promotion-joiner", "Joiner")
    workspace = owner.create_workspace(str(uuid.uuid4()), "Route lab", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], str(uuid.uuid4())
    )
    pending_scope = {"kind": "pending_invitation", "id": f"{4301:064x}"}
    retained_scope = {"kind": "contact", "id": "retained-contact"}
    email_digest, access = install_workspace_callback(
        owner,
        joiner,
        workspace["id"],
        invitation["id"],
        port=4301,
        scopes=[pending_scope, retained_scope],
    )
    assert email_digest == pending_scope["id"]

    # A different consumed invitation from the same responder must not be
    # promoted merely because the device destination happens to match.
    unrelated_digest = f"{4302:064x}"
    now = int(time.time())
    identity = joiner._identity
    assert identity is not None
    unrelated_access = create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": 4302, "path": "pcp"}],
        network_name="unrelated_callback_network",
        passphrase="unrelated_callback_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "email_invitation",
        unrelated_digest,
        {
            "id": unrelated_digest,
            "purpose": "workspace",
            "scope_id": "another-invitation",
            "workspace_id": workspace["id"],
            "state": "consumed",
            "responder_destination": joiner._require_profile()["destination_hash"],
        },
    )
    owner.store.put(
        "participant_access",
        unrelated_access["id"],
        {
            "id": unrelated_access["id"],
            "access": unrelated_access,
            "scopes": [{"kind": "pending_invitation", "id": unrelated_digest}],
            "resolved_endpoints": list(unrelated_access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )

    request = receive_workspace_join(
        owner, joiner, workspace["id"], invitation["text"]
    )
    before_approval = owner.store.get("participant_access", access["id"])
    assert before_approval is not None
    assert before_approval["scopes"] == [pending_scope, retained_scope]

    owner.approve_workspace_join(
        workspace["id"], request["id"], str(uuid.uuid4())
    )
    promoted = owner.store.get("participant_access", access["id"])
    assert promoted is not None
    assert promoted["scopes"] == [
        retained_scope,
        {"kind": "workspace_device", "id": workspace["id"]},
    ]
    unrelated = owner.store.get("participant_access", unrelated_access["id"])
    assert unrelated is not None
    assert unrelated["scopes"] == [
        {"kind": "pending_invitation", "id": unrelated_digest}
    ]
    assert owner.store.get("email_invitation", email_digest)["promoted_scope"] == {
        "kind": "workspace_device",
        "id": workspace["id"],
    }
    assert "promoted_scope" not in owner.store.get(
        "email_invitation", unrelated_digest
    )
    owner.close()
    joiner.close()


def test_workspace_decline_releases_only_the_exact_pending_callback_scope(
    tmp_path,
) -> None:
    owner = service(tmp_path / "decline-owner", "Owner")
    joiner = service(tmp_path / "decline-joiner", "Joiner")
    workspace = owner.create_workspace(str(uuid.uuid4()), "Route lab", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], str(uuid.uuid4())
    )
    pending_scope = {"kind": "pending_invitation", "id": f"{4401:064x}"}
    retained_scope = {"kind": "contact", "id": "retained-contact"}
    email_digest, mixed_access = install_workspace_callback(
        owner,
        joiner,
        workspace["id"],
        invitation["id"],
        port=4401,
        scopes=[pending_scope, retained_scope],
    )
    assert email_digest == pending_scope["id"]

    now = int(time.time())
    identity = joiner._identity
    assert identity is not None
    callback_only = create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": 4402, "path": "pcp"}],
        network_name="callback_only_network",
        passphrase="callback_only_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "participant_access",
        callback_only["id"],
        {
            "id": callback_only["id"],
            "access": callback_only,
            "scopes": [pending_scope],
            "resolved_endpoints": list(callback_only["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )
    unrelated_scope = {"kind": "pending_invitation", "id": f"{4403:064x}"}
    unrelated = create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": 4403, "path": "pcp"}],
        network_name="unrelated_pending_network",
        passphrase="unrelated_pending_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    unrelated_record = {
        "id": unrelated["id"],
        "access": unrelated,
        "scopes": [unrelated_scope],
        "resolved_endpoints": list(unrelated["endpoints"]),
        "candidate_results": [],
        "resolution_attempted": True,
        "consented_at": time.time(),
    }
    owner.store.put("participant_access", unrelated["id"], unrelated_record)
    # Older builds promoted this callback before approval. Preserve any other
    # relationship scope while cleaning that legacy workspace label too.
    legacy_workspace_scope = {"kind": "workspace_device", "id": workspace["id"]}
    legacy_retained_scope = {"kind": "contact", "id": "legacy-contact"}
    legacy_access = create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": 4404, "path": "pcp"}],
        network_name="legacy_promoted_network",
        passphrase="legacy_promoted_passphrase_123456789",
        mode="participant_callback",
        now=now,
        expires_at=now + 3600,
    )
    owner.store.put(
        "participant_access",
        legacy_access["id"],
        {
            "id": legacy_access["id"],
            "access": legacy_access,
            "scopes": [legacy_workspace_scope, legacy_retained_scope],
            "resolved_endpoints": list(legacy_access["endpoints"]),
            "candidate_results": [],
            "resolution_attempted": True,
            "consented_at": time.time(),
        },
    )
    callback_record = owner.store.get("email_invitation", email_digest)
    assert callback_record is not None
    callback_record["promoted_scope"] = legacy_workspace_scope
    owner.store.put("email_invitation", email_digest, callback_record)

    request = receive_workspace_join(
        owner, joiner, workspace["id"], invitation["text"]
    )
    owner.decline_workspace_join(
        workspace["id"], request["id"], str(uuid.uuid4())
    )

    mixed = owner.store.get("participant_access", mixed_access["id"])
    assert mixed is not None
    assert mixed["scopes"] == [retained_scope]
    assert owner.store.get("participant_access", callback_only["id"]) is None
    assert owner.store.get("participant_access", unrelated["id"]) == unrelated_record
    legacy = owner.store.get("participant_access", legacy_access["id"])
    assert legacy is not None
    assert legacy["scopes"] == [legacy_retained_scope]
    assert owner.store.get("email_invitation", email_digest)["state"] == "declined"
    assert owner.network is not None
    applied_clients = owner.network.applied[-1][1]
    assert {item["id"] for item in applied_clients} == {
        mixed_access["id"],
        legacy_access["id"],
        unrelated["id"],
    }
    owner.close()
    joiner.close()


def test_workspace_reply_created_after_submit_keeps_workspace_scope(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = service(tmp_path / "submit-first-owner", "Owner")
    joiner = service(tmp_path / "submit-first-joiner", "Joiner")
    monkeypatch.setattr(
        "mesh_chat.participant_service.public_ipv4_addresses",
        lambda **_kwargs: ["93.184.216.34"],
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.global_ipv6_addresses", lambda **_kwargs: []
    )
    workspace = owner.create_workspace(str(uuid.uuid4()), "Route lab", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], str(uuid.uuid4()), connection_mode="email"
    )
    verified = verify_email_invitation(invitation["text"], "workspace")
    assert verified is not None and verified.inviter_access is not None

    monkeypatch.setattr(
        "mesh_chat.participant_service.resolve_public_endpoint",
        lambda endpoint: [endpoint["host"]],
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.candidate_connection_result",
        lambda *_args, **_kwargs: "timed_out",
    )
    joined = joiner.submit_workspace_join(invitation["text"], str(uuid.uuid4()))
    assert joined["state"] == "joining"
    assert joined["connection_results"][0]["result"] == "timed_out"
    assert joiner.store.get("connection_response", verified.digest) is None

    reply = joiner.create_connection_reply(invitation["text"], "workspace")
    response = joiner.store.get("connection_response", verified.digest)
    assert response is not None
    assert response["workspace_id"] == workspace["id"]

    joiner._bind_workspace_callback_host(workspace["id"])
    response = joiner.store.get("connection_response", verified.digest)
    assert response is not None
    assert response["state"] == "active"
    assert response["relationship_scope"] == {
        "kind": "workspace_device",
        "id": workspace["id"],
    }
    host = joiner.store.get("participant_host", reply["host_session_id"])
    assert host is not None
    assert host["relationship_scope"] == response["relationship_scope"]
    assert host["peer_destination"] == verified.signer_destination.hex()
    owner.close()
    joiner.close()


def test_workspace_reply_failure_with_both_sides_unreachable_leaves_no_joiner_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = service(tmp_path / "unreachable-owner", "Owner")
    joiner = service(tmp_path / "unreachable-joiner", "Joiner")
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
    workspace = owner.create_workspace(str(uuid.uuid4()), "Blocked route", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], str(uuid.uuid4()), connection_mode="email"
    )
    verified = verify_email_invitation(invitation["text"], "workspace")
    assert verified is not None and verified.inviter_access is None
    assert owner.store.list("participant_host") == []

    with pytest.raises(DirectConnectionUnavailable) as failure:
        joiner.create_connection_reply(invitation["text"], "workspace")
    assert failure.value.details["reason"] == "pcp_no_response"
    for kind in (
        "connection_response",
        "participant_host",
        "participant_access",
        "workspace",
        "workspace_delivery",
        "contact",
    ):
        assert joiner.store.list(kind) == []
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
