from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import RNS
import pytest

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.i2p_invitation import create_i2p_invitation, verify_i2p_invitation
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore

B32 = "a" * 52 + ".b32.i2p"


class RecordingNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def invitation_hints(self) -> list[dict[str, Any]]:
        return []

    def remember_contact(self, _public_key: bytes, _destination: bytes) -> None:
        pass

    def recipient_ready(self, _destination: bytes) -> bool:
        return True

    def path_known(self, _destination: bytes) -> bool:
        return True

    def request_path(self, _destination: bytes) -> None:
        pass

    def send_with_fields(self, **value: Any) -> str:
        self.sent.append(value)
        return f"native-{len(self.sent)}"

    def apply_connection_settings(self, _settings: Any) -> None:
        pass

    def cancel_outbound(self, _logical_ids: set[str]) -> int:
        return 0

    def shutdown(self) -> None:
        pass


def _profile(identity: RNS.Identity, display_name: str) -> dict[str, Any]:
    public_key = identity.get_public_key()
    destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    return {
        "display_name": display_name,
        "public_identity": base64.urlsafe_b64encode(public_key).decode("ascii"),
        "identity_hash": identity.hash.hex(),
        "destination_hash": destination.hex(),
        "fingerprint": readable_fingerprint(public_key),
        "created_at": time.time(),
    }


def _service(root: Path, identity: RNS.Identity) -> MeshChatService:
    store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, root, lambda _event: None)
    store.put(
        "identity",
        "local",
        {"private_key": base64.urlsafe_b64encode(identity.get_private_key()).decode("ascii")},
    )
    store.put("profile", "local", _profile(identity, "Owner"))
    service._shutdown.set()
    service._identity = identity
    service.network = RecordingNetwork()  # type: ignore[assignment]
    return service


def _op(seed: int) -> str:
    return f"00000000-0000-4000-8000-{seed:012d}"


def test_personal_i2p_invitation_previews_and_adopts_the_route(tmp_path) -> None:
    owner = _service(tmp_path / "owner", RNS.Identity())
    joiner = _service(tmp_path / "joiner", RNS.Identity())
    try:
        created = owner.invitation(connection_mode="i2p", i2p_access_point=B32, i2p_label="Relay")
        assert created["connection_mode"] == "i2p"
        assert created["text"].startswith("MESHI2P1:")

        preview = joiner.preview_invitation(created["text"])
        assert preview["i2p_access_point"]["b32"] == B32
        assert preview["requires_i2p_consent"] is True

        joiner.accept_invitation(created["text"])
        assert joiner.settings.i2p_enabled is True
        assert B32 in joiner.settings.i2p_peers
        config = (tmp_path / "joiner" / "reticulum" / "config").read_text(encoding="utf-8")
        assert "[[I2P]]" in config
        assert "type = I2PInterface" in config
        assert f"peers = {B32}" in config
    finally:
        owner.close()
        joiner.close()


def test_normal_personal_invitation_is_not_treated_as_i2p(tmp_path) -> None:
    owner = _service(tmp_path / "owner", RNS.Identity())
    joiner = _service(tmp_path / "joiner", RNS.Identity())
    try:
        created = owner.invitation()
        preview = joiner.preview_invitation(created["text"])
        assert "i2p_access_point" not in preview
        assert joiner.settings.i2p_enabled is False
    finally:
        owner.close()
        joiner.close()


def test_workspace_i2p_invitation_previews_with_the_signed_route(tmp_path) -> None:
    owner = _service(tmp_path / "owner", RNS.Identity())
    joiner = _service(tmp_path / "joiner", RNS.Identity())
    try:
        workspace = owner.create_workspace(_op(1), "I2P workspace", "")
        created = owner.create_workspace_invitation_command(
            workspace["id"],
            _op(2),
            connection_mode="i2p",
            i2p_access_point=B32,
        )
        assert created["connection_mode"] == "i2p"
        assert created["text"].startswith("MESHI2P1W:")

        preview = joiner.preview_workspace_invitation(created["text"])
        assert preview["i2p_access_point"]["b32"] == B32
        assert preview["requires_i2p_consent"] is True
    finally:
        owner.close()
        joiner.close()


def test_workspace_wrapper_rejects_a_foreign_signer_and_excess_expiry(tmp_path) -> None:
    owner = _service(tmp_path / "owner", RNS.Identity())
    try:
        workspace = owner.create_workspace(_op(3), "I2P workspace", "")
        created = owner.create_workspace_invitation_command(
            workspace["id"],
            _op(4),
            connection_mode="i2p",
            i2p_access_point=B32,
        )
        verified = verify_i2p_invitation(created["text"], "workspace")
        assert verified is not None
        inner = verified.inner

        attacker = RNS.Identity()
        foreign = create_i2p_invitation(
            attacker,
            inner,
            "workspace",
            B32,
            expires_at=verified.expires_at,
        )
        with pytest.raises(IdentityMismatch):
            verify_i2p_invitation(foreign, "workspace")

        excessive = create_i2p_invitation(
            owner._identity,
            inner,
            "workspace",
            B32,
            expires_at=verified.expires_at + 86_400,
        )
        with pytest.raises(ValidationError):
            verify_i2p_invitation(excessive, "workspace")
    finally:
        owner.close()
