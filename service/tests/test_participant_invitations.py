from __future__ import annotations

import json
import os
import socket
import struct
import uuid

import pytest
import RNS

from mesh_chat import connectivity
from mesh_chat.connectivity import MappingResult
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.models import WorkspaceRole
from mesh_chat.participant import (
    create_access_document,
    create_participant_personal_invitation,
    create_participant_workspace_invitation,
    participant_invitation_formats,
    verify_participant_invitation,
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


def access(identity: RNS.Identity) -> dict[str, object]:
    return create_access_document(
        identity,
        [{"host": "93.184.216.34", "port": 4242, "path": "upnp"}],
        network_name="network_name_123456",
        passphrase="invitation_credential_123456789",
        now=NOW,
        expires_at=NOW + 3600,
    )


def workspace_invitation(owner: RNS.Identity) -> str:
    created = create_workspace_genesis(
        owner,
        "Participant workspace",
        "Direct owner path",
        "Owner",
        now=NOW,
        nonce=b"p" * 32,
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
        nonce=b"j" * 32,
    )


def test_v3_round_trip_binds_participant_endpoint_to_inviter() -> None:
    identity = RNS.Identity()
    inner = create_invitation(identity, "Alex", now=NOW)["file"]
    envelope = create_participant_personal_invitation(
        identity, inner, access(identity), now=NOW
    )
    formats = participant_invitation_formats(envelope, "personal")

    assert formats["text"].startswith("MESHCHAT3:")
    for raw in (envelope, formats["text"], formats["link"]):
        verified = verify_participant_invitation(raw, "personal", now=NOW + 1)
        assert verified is not None
        assert verified.inner == inner
        assert verified.access["operator_destination"] == RNS.Destination.hash(
            identity, "lxmf", "delivery"
        ).hex()
        assert verified.access["endpoints"][0]["path"] == "upnp"


def test_v3_rejects_tampering_and_a_different_operator() -> None:
    identity = RNS.Identity()
    inner = create_invitation(identity, "Alex", now=NOW)["file"]
    with pytest.raises(IdentityMismatch):
        create_participant_personal_invitation(
            identity, inner, access(RNS.Identity()), now=NOW
        )

    value = json.loads(
        create_participant_personal_invitation(
            identity, inner, access(identity), now=NOW
        )
    )
    value["access"]["endpoints"][0]["port"] = 4343
    with pytest.raises(ValidationError):
        verify_participant_invitation(json.dumps(value), "personal", now=NOW + 1)


def test_workspace_v3_binds_the_current_authority_and_preserves_the_inner_invite() -> None:
    owner = RNS.Identity()
    inner = workspace_invitation(owner)
    envelope = create_participant_workspace_invitation(
        owner, inner, access(owner), now=NOW
    )
    verified = verify_participant_invitation(
        participant_invitation_formats(envelope, "workspace")["text"],
        "workspace",
        now=NOW + 1,
    )
    assert verified is not None
    assert verified.inner == inner

    wrong_authority = RNS.Identity()
    with pytest.raises(IdentityMismatch):
        create_participant_workspace_invitation(
            wrong_authority, inner, access(wrong_authority), now=NOW
        )


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.4", "192.0.2.1"])
def test_participant_access_rejects_non_public_candidates(host: str) -> None:
    with pytest.raises(ValidationError):
        create_access_document(
            RNS.Identity(),
            [{"host": host, "port": 4242, "path": "upnp"}],
            network_name="network_name_123456",
            passphrase="invitation_credential_123456789",
            now=NOW,
        )


class _HostNetwork:
    def __init__(self) -> None:
        self.applied: list[tuple[list[dict[str, object]], list[dict[str, object]]]] = []

    def invitation_hints(self) -> list[dict[str, object]]:
        return []

    def apply_participant_interfaces(
        self, listeners: list[dict[str, object]], clients: list[dict[str, object]]
    ) -> None:
        self.applied.append((listeners, clients))

    def reannounce(self) -> None:
        return None

    def shutdown(self) -> bool:
        return True


def test_service_creates_participant_host_without_a_transport_profile(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed_mappings: list[dict[str, object]] = []
    mapping = MappingResult(
        "upnp",
        "93.184.216.34",
        54321,
        "192.168.1.20",
        45678,
        7200,
        {"control_url": "http://192.168.1.1/control", "service_type": "wan"},
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.select_available_port", lambda **_kwargs: 45678
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.create_port_mapping", lambda *_args, **_kwargs: mapping
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.global_ipv6_addresses", lambda: []
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.remove_port_mapping",
        lambda value, **_kwargs: removed_mappings.append(value),
    )
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _display_name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Inviter")
        host_network = _HostNetwork()
        service.network = host_network  # type: ignore[assignment]
        invitation = service.invitation(connection_mode="participant")

        assert invitation["text"].startswith("MESHCHAT3:")
        assert invitation["connection_mode"] == "participant"
        assert service.store.list("remote_profile") == []
        assert len(service.store.list("participant_host")) == 1
        listeners, clients = host_network.applied[-1]
        assert clients == []
        assert listeners[0]["network_name"]
        assert listeners[0]["passphrase"]
        preview = service.preview_invitation(invitation["text"])
        assert preview["participant_access"]["operator"] == "inviter"
        assert "remote_profile" not in preview
    finally:
        service.close()
    assert host_network.applied[-1][0] == []
    assert len(removed_mappings) == 1


def test_nat_pmp_mapping_uses_router_reported_public_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = struct.pack(
        "!BBHII", 0, 128, 0, 10, struct.unpack("!I", socket.inet_aton("93.184.216.34"))[0]
    )
    mapped = struct.pack("!BBHIHHI", 0, 130, 0, 10, 45678, 54321, 7200)
    responses = iter((public, mapped))
    monkeypatch.setattr(connectivity, "gateway_candidates", lambda: ["192.168.1.1"])
    monkeypatch.setattr(
        connectivity,
        "_gateway_exchange",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(
        connectivity, "_local_address_for", lambda *_args: "192.168.1.20"
    )

    result = connectivity.map_nat_pmp(45678)
    assert result.external_host == "93.184.216.34"
    assert result.external_port == 54321
    assert result.method == "nat_pmp"
