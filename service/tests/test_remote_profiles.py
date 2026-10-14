from __future__ import annotations

import json
import os
import socket
import time
import uuid

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.models import WorkspaceRole
from mesh_chat.remote import (
    add_profile_scope,
    create_profile_document,
    create_remote_personal_invitation,
    create_remote_workspace_invitation,
    new_profile_record,
    remote_invitation_formats,
    remove_profile_scope,
    resolve_public_endpoint,
    retry_delay,
    sanitized_profile,
    verify_remote_invitation,
)
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_manifest,
    verify_workspace_genesis,
    verify_workspace_manifest_transition,
)

NOW = 1_800_000_000


def profile() -> dict[str, object]:
    return create_profile_document(
        "Field relay",
        [
            {"host": "relay.example.net", "port": 4242},
            {"host": "93.184.216.34", "port": 4243},
        ],
        propagation_node="ab" * 16,
        now=NOW,
        expires_at=NOW + 10_000,
    )


def workspace_invitation(owner: RNS.Identity) -> str:
    created = create_workspace_genesis(
        owner,
        "Remote workspace",
        "Isolated topology",
        "Owner",
        now=NOW,
        nonce=b"r" * 32,
        owner_member_id=str(uuid.UUID(int=1)),
        authority_device_id=str(uuid.UUID(int=2)),
    )
    genesis = verify_workspace_genesis(created.serialized, now=NOW)
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name=genesis.name,
        description=genesis.description,
        authority_device_id=genesis.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                genesis.owner_device.display_name,
                WorkspaceRole.OWNER,
                [created.device_card],
            )
        ],
        now=NOW,
    )
    manifest = verify_workspace_manifest_transition(manifest_raw, genesis, now=NOW)
    return create_workspace_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=manifest.serialized,
        now=NOW,
        nonce=b"i" * 32,
    )


def test_personal_v2_round_trip_preserves_exact_v1_inner() -> None:
    identity = RNS.Identity()
    inner = create_invitation(identity, "Alex", now=NOW)["file"]
    envelope = create_remote_personal_invitation(identity, inner, profile(), now=NOW)

    for raw in (
        envelope,
        remote_invitation_formats(envelope, "personal")["text"],
        remote_invitation_formats(envelope, "personal")["link"],
    ):
        verified = verify_remote_invitation(raw, "personal", now=NOW + 1)
        assert verified is not None
        assert verified.inner == inner
        assert verified.profile["label"] == "Field relay"


def test_configured_remote_profile_does_not_change_default_personal_invitation(
    tmp_path,
) -> None:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _display_name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Inviter")
        remote = service.create_manual_remote_profile(
            "Optional relay", [{"host": "93.184.216.34", "port": 4242}]
        )

        direct = service.invitation()
        assert direct["text"].startswith("MESHCHAT1:")
        assert "remote_profile_id" not in direct

        opted_in = service.invitation(remote["id"])
        assert opted_in["text"].startswith("MESHCHAT2:")
        assert opted_in["remote_profile_id"] == remote["id"]
    finally:
        service.close()


def test_workspace_v2_cross_checks_current_authority() -> None:
    owner = RNS.Identity()
    inner = workspace_invitation(owner)
    envelope = create_remote_workspace_invitation(owner, inner, profile(), now=NOW)
    verified = verify_remote_invitation(
        remote_invitation_formats(envelope, "workspace")["text"],
        "workspace",
        now=NOW + 1,
    )
    assert verified is not None
    assert verified.inner == inner

    with pytest.raises(IdentityMismatch):
        create_remote_workspace_invitation(RNS.Identity(), inner, profile(), now=NOW)


def test_tampered_profile_and_inner_digest_fail_closed() -> None:
    identity = RNS.Identity()
    inner = create_invitation(identity, "Alex", now=NOW)["file"]
    value = json.loads(
        create_remote_personal_invitation(identity, inner, profile(), now=NOW)
    )
    value["profile"]["label"] = "Changed"
    with pytest.raises(ValidationError):
        verify_remote_invitation(json.dumps(value), "personal", now=NOW + 1)

    value = json.loads(
        create_remote_personal_invitation(identity, inner, profile(), now=NOW)
    )
    value["inner_digest"] = "00" * 32
    with pytest.raises(ValidationError):
        verify_remote_invitation(json.dumps(value), "personal", now=NOW + 1)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "localhost",
        "relay.local",
    ],
)
def test_imported_profiles_reject_non_public_literals_and_local_names(host: str) -> None:
    with pytest.raises(ValidationError):
        create_profile_document(
            "Unsafe", [{"host": host, "port": 4242}], now=NOW
        )


def test_dns_rebinding_and_mixed_answers_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def answers(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 4242)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 4242)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", answers)
    with pytest.raises(ValidationError, match="non-public"):
        resolve_public_endpoint({"host": "relay.example.net", "port": 4242})


def test_private_manual_flow_is_separately_labeled() -> None:
    checked = create_profile_document(
        "Lab relay",
        [{"host": "10.0.0.4", "port": 4242}],
        now=NOW,
        allow_private=True,
    )
    record = new_profile_record(
        checked,
        origin="manual",
        scope_kind="manual",
        scope_id=checked["id"],
        consented_at=NOW,
        allow_private=True,
    )
    assert sanitized_profile(record)["allow_private"] is True


def test_profile_scope_reference_counting_is_independent() -> None:
    checked = profile()
    record = new_profile_record(
        checked,
        origin="personal_invitation",
        scope_kind="contact",
        scope_id="contact-a",
        consented_at=NOW,
    )
    add_profile_scope(record, "workspace", "workspace-a")
    assert remove_profile_scope(record, "contact", "contact-a") is False
    assert record["scopes"] == [{"kind": "workspace", "id": "workspace-a"}]
    assert remove_profile_scope(record, "workspace", "workspace-a") is True


def test_profile_retry_backoff_is_bounded_and_jittered() -> None:
    assert retry_delay(1, random_value=0.0) == 1.5
    assert retry_delay(5, random_value=0.0) == 24.0
    assert retry_delay(5, random_value=1.0) == 40.0
    assert retry_delay(12, random_value=1.0) == 300


def test_remote_preview_is_cryptographic_only_and_makes_no_network_request(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = int(time.time())
    inviter = RNS.Identity()
    remote_profile = create_profile_document(
        "Consent relay",
        [{"host": "relay.example.net", "port": 4242}],
        now=now,
    )
    inner = create_invitation(inviter, "Inviter", now=now)["file"]
    envelope = create_remote_personal_invitation(
        inviter, inner, remote_profile, now=now
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("preview attempted DNS")
        ),
    )
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    try:
        preview = service.preview_invitation(envelope)
        assert preview["requires_network_consent"] is True
        assert preview["remote_profile"]["label"] == "Consent relay"
        assert service.store.list("remote_profile") == []
    finally:
        service.close()


def test_accept_is_the_explicit_consent_boundary_and_persists_before_attach(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = int(time.time())
    inviter = RNS.Identity()
    remote_profile = create_profile_document(
        "Consent relay",
        [{"host": "relay.example.net", "port": 4242}],
        now=now,
    )
    inner = create_invitation(inviter, "Inviter", now=now)["file"]
    envelope = create_remote_personal_invitation(
        inviter, inner, remote_profile, now=now
    )
    lookups: list[str] = []

    def safe_answer(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", safe_answer)
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _display_name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Recipient")
        assert lookups == []
        contact = service.accept_invitation(envelope)
        assert lookups == ["relay.example.net"]
        record = service.store.get("remote_profile", remote_profile["id"])
        assert record is not None
        assert {"kind": "contact", "id": contact["id"]} in record["scopes"]
        assert record["resolved_endpoints"][0]["host"] == "93.184.216.34"
    finally:
        service.close()


def test_propagation_requires_separate_approval_and_removal(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def safe_answer(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", safe_answer)
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _display_name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Recipient")
        created = service.create_manual_remote_profile(
            "Offline relay",
            [{"host": "relay.example.net", "port": 4242}],
            "ab" * 16,
        )
        assert created["offline_delivery_approved"] is False
        assert service.settings.approved_propagation_nodes == []

        approved = service.approve_remote_propagation(created["id"])
        assert approved["offline_delivery_approved"] is True
        assert service.settings.approved_propagation_nodes == ["ab" * 16]
        with pytest.raises(ValidationError, match="offline delivery"):
            service.remove_remote_profile(created["id"])

        removed = service.remove_remote_propagation(created["id"])
        assert removed["offline_delivery_approved"] is False
        assert service.settings.approved_propagation_nodes == []
        assert service.remove_remote_profile(created["id"])["removed"] is True
    finally:
        service.close()
