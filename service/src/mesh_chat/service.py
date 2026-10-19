from __future__ import annotations

import base64
import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import LXMF
import RNS

from .app_protocol import (
    DELIVERY_WINDOW_SECONDS,
    GROUP_KINDS,
    MAX_TEXT_BYTES,
    conversation_id,
    parse_payload,
)
from .errors import (
    ContactInUse,
    ContactNotApproved,
    InvitationInvalid,
    MeshChatError,
    NetworkUnavailable,
    ValidationError,
    DirectConnectionUnavailable,
)
from .invitations import (
    MAX_HINTS,
    InvitationFormats,
    VerifiedInvitation,
    create_invitation,
    readable_fingerprint,
    verify_invitation,
)
from .direct_runtime import SessionRegistry
from .direct_packets import PacketRuntime
from .direct_packet_adapter import ProfileBudget
from .group_service import GroupServiceMixin
from .models import Contact, DeliveryState, Message, MessageKind, Profile, TrustState
from .network import ReticulumNetwork, select_lan_listener_port
from .participant import (
    connection_response_formats,
    create_connection_response,
    create_email_invitation,
    create_participant_personal_invitation,
    create_route_update as create_signed_route_update,
    email_invitation_formats,
    participant_invitation_formats,
    preview_participant_access,
    route_update_formats,
    verify_connection_response,
    verify_email_invitation,
    verify_participant_invitation,
    verify_route_update,
)
from .participant_service import ParticipantAccessServiceMixin
from .reactions import ReactionServiceMixin
from .remote import (
    create_remote_personal_invitation,
    remote_invitation_formats,
    sanitized_profile,
    verify_remote_invitation,
)
from .remote_service import RemoteProfileServiceMixin
from .reticulum_config import NetworkSettings
from .vault import VaultStore
from .workspace_protocol import verify_workspace_invitation
from .workspace_service import WorkspaceServiceMixin
from .workspace_wire import is_workspace_payload, parse_workspace_payload

EventCallback = Callable[[dict[str, Any]], None]
CONTACT_REQUEST_WINDOW_SECONDS = 60 * 60
CONTACT_REQUESTS_PER_IDENTITY = 5
MAX_PENDING_REQUESTS = 100
CONTACT_FLUSH_ATTEMPTS = 4
ROUTE_REFRESH_MARGIN_SECONDS = 10 * 60
ROUTE_REFRESH_RETRY_SECONDS = 5 * 60
DELETED_MESSAGE_REPLAY_GRACE_SECONDS = 24 * 60 * 60

DIRECT_RETRY_STATES = {
    DeliveryState.QUEUED.value,
    DeliveryState.WAITING_FOR_KEYS.value,
    DeliveryState.FAILED.value,
}
DIRECT_PROGRESS_RANK = {
    DeliveryState.SENDING.value: 1,
    DeliveryState.STORED_FOR_DELIVERY.value: 2,
    DeliveryState.RECEIVED_BY_ENDPOINT.value: 3,
    DeliveryState.DELIVERED.value: 4,
}
DIRECT_ENDPOINT_EVIDENCE = {
    DeliveryState.STORED_FOR_DELIVERY.value,
    DeliveryState.RECEIVED_BY_ENDPOINT.value,
    DeliveryState.DELIVERED.value,
}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value)
    except Exception as exc:
        raise ValidationError("Stored identity encoding is invalid") from exc


def _new_id() -> str:
    return str(uuid.uuid4())


def _contact_id(destination: bytes) -> str:
    return str(uuid.UUID(bytes=RNS.Identity.full_hash(b"mesh-chat:contact:" + destination)[:16]))


def _display_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Display name is required")
    checked = " ".join(value.strip().split())
    if not 1 <= len(checked) <= 64 or any(ord(char) < 32 for char in checked):
        raise ValidationError("Display name is invalid")
    return checked


def _payload(
    value: Any, *, allowed: set[str], required: set[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
        raise ValidationError("Command payload is invalid")
    return value


class MeshChatService(
    ReactionServiceMixin,
    GroupServiceMixin,
    WorkspaceServiceMixin,
    RemoteProfileServiceMixin,
    ParticipantAccessServiceMixin,
):
    COMMANDS = {
        "resume_direct_setup",
        "connection_diagnostics", "clear_connection_diagnostics",
        "preview_direct_connection", "prepare_direct_offer", "prepare_direct_answer",
        "prepare_direct_ready", "accept_direct_ready", "connect_direct_setup",
        "configure_direct_firewall",
        "direct_setup_status", "cancel_direct_setup", "check_direct_setup", "retry_direct_setup",
        "direct_recovery_status", "export_recovery_update", "import_recovery_update",
        "pause_direct_recovery", "resume_direct_recovery",
        "snapshot",
        "workspace_snapshot",
        "create_profile",
        "create_invitation",
        "preview_invitation",
        "accept_invitation",
        "create_connection_reply",
        "preview_connection_reply",
        "connect_using_reply",
        "create_route_update",
        "preview_route_update",
        "apply_route_update",
        "preview_remote_profile",
        "create_manual_remote_profile",
        "approve_remote_profile",
        "test_remote_profile",
        "list_remote_profiles",
        "retry_remote_profile",
        "remove_remote_profile",
        "approve_remote_propagation",
        "remove_remote_propagation",
        "check_direct_connection",
        "prepare_manual_participant_host",
        "configure_participant_firewall",
        "stop_participant_host",
        "approve_request",
        "decline_request",
        "update_contact",
        "rename_contact",
        "delete_contact",
        "send_message",
        "set_message_reaction",
        "save_draft",
        "delete_conversation",
        "restore_conversation",
        "retry_message",
        "verify_contact",
        "unverify_contact",
        "block_contact",
        "unblock_contact",
        "connection_help",
        "search",
        "update_settings",
        "create_group",
        "send_group_message",
        "save_group_draft",
        "accept_group_invitation",
        "decline_group_invitation",
        "retry_group_invitation",
        "remove_group_member",
        "leave_group",
        "close_group",
        "create_workspace",
        "create_workspace_invitation",
        "preview_workspace_invitation",
        "revoke_workspace_invitation",
        "submit_workspace_join",
        "approve_workspace_join",
        "decline_workspace_join",
        "create_workspace_device_link",
        "preview_workspace_device_link",
        "submit_workspace_device_link",
        "approve_workspace_device_link",
        "decline_workspace_device_link",
        "request_workspace_device_removal",
        "approve_workspace_device_removal",
        "decline_workspace_device_removal",
        "update_workspace_metadata",
        "update_workspace_policies",
        "update_workspace_retention",
        "prune_workspace_history",
        "get_workspace_history_status",
        "start_workspace_history",
        "cancel_workspace_history",
        "list_workspace_history_gaps",
        "remove_workspace_member",
        "change_workspace_role",
        "submit_workspace_admin_request",
        "submit_workspace_invitation_request",
        "submit_workspace_member_removal_request",
        "submit_workspace_role_change_request",
        "list_workspace_members",
        "list_workspace_admin_requests",
        "list_workspace_admin_history",
        "get_workspace_admin_request",
        "approve_workspace_admin_request",
        "decline_workspace_admin_request",
        "cancel_workspace_admin_request",
        "dismiss_workspace_admin_request",
        "offer_workspace_authority_transition",
        "accept_workspace_authority_transition",
        "finalize_workspace_authority_transition",
        "list_workspace_authority_transitions",
        "report_workspace_authority_loss",
        "request_workspace_display_name",
        "decide_workspace_display_name",
        "create_workspace_channel",
        "update_workspace_channel",
        "update_workspace_private_channel_members",
        "leave_workspace_private_channel",
        "set_workspace_channel_subscription",
        "offer_workspace_channel_transfer",
        "accept_workspace_channel_transfer",
        "recover_workspace_channel",
        "sync_workspace_channels",
        "send_workspace_message",
        "open_workspace_direct",
        "hide_workspace_direct",
        "send_workspace_direct_message",
        "send_workspace_thread_reply",
        "edit_workspace_message",
        "delete_workspace_message",
        "set_workspace_reaction",
        "list_workspace_messages",
        "list_workspace_direct_messages",
        "list_workspace_mentions",
        "list_workspace_threads",
        "list_workspace_thread_messages",
        "list_workspace_message_revisions",
        "list_workspace_tombstones",
        "list_workspace_authority_transitions",
        "list_workspace_members",
        "list_workspace_admin_requests",
        "list_workspace_admin_history",
        "get_workspace_admin_request",
        "get_workspace_history_status",
        "list_workspace_history_gaps",
        "mark_workspace_read",
        "set_workspace_read_hint_sync",
        "mark_workspace_direct_read",
        "mark_workspace_mentions_read",
        "mark_workspace_thread_read",
        "set_workspace_channel_mentions_muted",
        "get_notification_state",
        "set_hide_notification_previews",
        "set_workspace_notification_preference",
        "open_notification_target",
        "reconcile_mobile_lifecycle",
        # Native-only mobile bridge commands. Rust never exposes these names
        # through the renderer allowlist.
        "native_notification_state",
        "mobile_lifecycle_transition",
        "drain_native_notification_work",
        "acknowledge_native_notification",
        "hide_workspace_message",
        "save_workspace_draft",
        "save_workspace_direct_draft",
        "save_workspace_thread_draft",
        "leave_workspace",
        "close_workspace",
        "remove_workspace_data",
        "shutdown",
    }
    # These commands are observational and safe to repeat. Persisting their
    # often-large responses provides no idempotency benefit and historically
    # allowed snapshot polling to grow the encrypted command table without a
    # useful bound.
    UNCACHED_COMMANDS = {
        "resume_direct_setup",
        "connection_diagnostics", "clear_connection_diagnostics",
        "preview_direct_connection", "prepare_direct_offer", "prepare_direct_answer",
        "prepare_direct_ready", "accept_direct_ready", "connect_direct_setup",
        "configure_direct_firewall",
        "direct_setup_status", "cancel_direct_setup", "check_direct_setup", "retry_direct_setup",
        "direct_recovery_status", "export_recovery_update", "import_recovery_update",
        "pause_direct_recovery", "resume_direct_recovery",
        "snapshot",
        "workspace_snapshot",
        "search",
        "connection_help",
        "preview_invitation",
        "preview_connection_reply",
        "preview_route_update",
        "preview_remote_profile",
        "list_remote_profiles",
        "preview_workspace_invitation",
        "preview_workspace_device_link",
        "list_workspace_messages",
        "list_workspace_direct_messages",
        "list_workspace_mentions",
        "list_workspace_threads",
        "list_workspace_thread_messages",
        "list_workspace_message_revisions",
        "list_workspace_tombstones",
        "get_notification_state",
        "open_notification_target",
        "reconcile_mobile_lifecycle",
        "native_notification_state",
        "mobile_lifecycle_transition",
        "drain_native_notification_work",
        "acknowledge_native_notification",
    }

    def __init__(self, store: VaultStore, profile_dir: Path, emit: EventCallback, *, direct_native=None):
        self.store = store
        self.profile_dir = profile_dir
        self.emit = emit
        self._direct_native = direct_native
        self.network: ReticulumNetwork | None = None
        self._identity: RNS.Identity | None = None
        self._shutdown = threading.Event()
        self._dispatch_lock = threading.RLock()
        self._direct_sessions = SessionRegistry()
        self._direct_packets = PacketRuntime()
        self._direct_packet_budget = ProfileBudget()
        from .direct_setup import DirectSetup
        self._direct_setup = DirectSetup(self)
        from .direct_recovery import DirectRecovery
        self._direct_recovery = DirectRecovery(self)
        self._close_lock = threading.Lock()
        self._close_started = False
        self._store_closed = False
        self._close_finalizer: threading.Thread | None = None
        self._network_error: str | None = None
        self._connection_settings_dirty = False

        settings_record = store.get("settings", "network")
        self.settings = NetworkSettings.from_dict(settings_record)
        identity_record = store.get("identity", "local")
        profile_record = store.get("profile", "local")
        if identity_record is not None or profile_record is not None:
            if identity_record is None or profile_record is None:
                raise ValidationError("Local profile is incomplete")
            self._identity = RNS.Identity.from_bytes(_unb64(identity_record["private_key"]))
            if self._identity is None:
                raise ValidationError("Stored private identity is invalid")
            self._restore_participant_interfaces()
            self._prepare_lan_fallback()
            self._start_network(profile_record["display_name"])
            with self._dispatch_lock:
                self._recover_outbox()

        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self._retry_thread.start()
        self._direct_recovery.start()

    def _start_network(self, display_name: str) -> None:
        if self._identity is None or self.network is not None:
            return
        try:
            self.network = ReticulumNetwork(
                self.profile_dir,
                self._identity,
                display_name,
                self.settings,
                self._on_inbound,
                self._on_native_status,
            )
            for contact in self.store.list("contact"):
                self.network.remember_contact(
                    _unb64(contact["public_identity"]), bytes.fromhex(contact["destination_hash"])
                )
            for group in self.store.list("group"):
                self._remember_group_members(group)
            for workspace in self.store.list("workspace"):
                self._remember_workspace_devices(workspace)
            self.reconcile_remote_profiles(force_dns=True)
            # Interface availability can change after startup (for example when
            # a Wi-Fi interface appears or an approved TCP hint is attached),
            # so snapshot() derives that health live instead of latching it.
            self._network_error = None
        except Exception:
            # Detailed upstream exceptions may contain addresses or paths. Keep a
            # stable redacted code for the UI and diagnostics.
            self._network_error = "network_start_failed"
            self.network = None

    def _prepare_lan_fallback(self) -> None:
        """Allocate a stable app-owned listener port before RNS starts."""

        previous = self.settings.lan_listener_port
        if not self.settings.lan_fallback:
            self.settings.lan_listener_port = None
        elif self._identity is not None:
            # Do not probe an already-running listener owned by this service.
            if self.network is None:
                try:
                    self.settings.lan_listener_port = select_lan_listener_port(
                        self._identity.hash, previous
                    )
                except NetworkUnavailable:
                    self.settings.lan_listener_port = None
        if self.settings.lan_listener_port != previous:
            self.store.put("settings", "network", self.settings.to_dict())

    def create_profile(self, display_name: str) -> dict[str, Any]:
        name = _display_name(display_name)
        existing = self.store.get("profile", "local")
        if existing is not None:
            if existing["display_name"] != name or self._identity is None:
                raise ValidationError("A different local profile already exists")
            return existing
        identity = RNS.Identity()
        destination = RNS.Destination.hash(identity, "lxmf", "delivery")
        now = time.time()
        profile = Profile(
            display_name=name,
            public_identity=_b64(identity.get_public_key()),
            identity_hash=identity.hash.hex(),
            destination_hash=destination.hex(),
            fingerprint=readable_fingerprint(identity.get_public_key()),
            created_at=now,
        )
        self._identity = identity
        self._prepare_lan_fallback()
        self.store.put_many(
            [
                ("identity", "local", {"private_key": _b64(identity.get_private_key())}),
                ("profile", "local", profile.to_dict()),
                ("settings", "network", self.settings.to_dict()),
            ]
        )
        self._start_network(name)
        self._changed()
        return profile.to_dict()

    def invitation(
        self,
        profile_id: str | None = None,
        connection_mode: str | None = None,
        manual_setup_id: str | None = None,
        external_host: str | None = None,
        external_port: int | None = None,
    ) -> InvitationFormats:
        profile = self._require_profile()
        if self._identity is None:
            raise ValidationError("Local identity is unavailable")
        hints: list[dict[str, Any]] = []
        if self.network is not None:
            hints = self.network.invitation_hints()
        else:
            listener = self.settings.tcp_listener
            if listener and listener["host"] not in {
                "0.0.0.0",
                "::",
                "127.0.0.1",
                "::1",
            }:
                hints.append({"type": "tcp", **listener})
        local = create_invitation(self._identity, profile["display_name"], hints=hints)
        if connection_mode == "email":
            scope_id = str(uuid.uuid4())
            access: dict[str, Any] | None = None
            host_session_id: str | None = None
            try:
                hosted = self.create_participant_host_access(
                    purpose="personal", scope_id=scope_id,
                    maximum_expires_at=local["expires_at"],
                )
                host_session_id = hosted.pop("host_session_id")
                access = hosted
            except DirectConnectionUnavailable:
                # Role reversal is the explicit fallback. The v4 capability is
                # still useful when this device cannot accept an inbound path.
                access = None
            serialized = create_email_invitation(
                self._identity, "personal", local["file"], access
            )
            verified = verify_email_invitation(serialized, "personal")
            if verified is None:
                raise ValidationError("Email-ready invitation could not be created")
            self.store.put("email_invitation", verified.digest, {
                "id": verified.digest,
                "purpose": "personal",
                "scope_id": scope_id,
                "document": verified.serialized,
                "state": "active",
                "created_at": float(verified.created_at),
                "expires_at": float(verified.expires_at),
                "host_session_id": host_session_id,
            })
            formats = email_invitation_formats(serialized, "personal")
            return {
                **formats,
                "expires_at": verified.expires_at,
                "connection_mode": "email",
                "host_session_id": host_session_id,
                "methods": sorted({item["path"] for item in access["endpoints"]})
                if access else [],
                "connection_reply_available": True,
            }
        if connection_mode in {"participant", "manual"}:
            scope_id = str(uuid.uuid4())
            if connection_mode == "manual":
                access = self.finalize_manual_participant_host(
                    manual_setup_id, purpose="personal", scope_id=scope_id,
                    maximum_expires_at=local["expires_at"],
                    external_host=external_host, external_port=external_port,
                )
            else:
                access = self.create_participant_host_access(
                    purpose="personal", scope_id=scope_id,
                    maximum_expires_at=local["expires_at"],
                )
            host_session_id = access.pop("host_session_id")
            serialized = create_participant_personal_invitation(
                self._identity, local["file"], access
            )
            formats = participant_invitation_formats(serialized, "personal")
            return {
                **formats,
                "expires_at": min(local["expires_at"], access["expires_at"]),
                "connection_mode": "participant",
                "host_session_id": host_session_id,
                "methods": sorted({item["path"] for item in access["endpoints"]}),
            }
        if connection_mode not in {None, "nearby", "remote"}:
            raise ValidationError("Invitation connection mode is invalid")
        if profile_id is None:
            return local
        remote = self._require_remote_profile(profile_id)
        if remote.get("state") == "expired":
            raise ValidationError("Remote profile has expired")
        serialized = create_remote_personal_invitation(
            self._identity, local["file"], remote["profile"]
        )
        formats = remote_invitation_formats(serialized, "personal")
        return {
            **formats,
            "expires_at": min(local["expires_at"], remote["profile"]["expires_at"]),
            "remote_profile_id": profile_id,
            "access_point_reachable": int(remote.get("connected_endpoints", 0)) > 0,
        }

    def preview_invitation(self, raw: str) -> dict[str, Any]:
        try:
            email = verify_email_invitation(raw, "personal")
            participant = None if email else verify_participant_invitation(raw, "personal")
            remote = None if email or participant else verify_remote_invitation(raw, "personal")
            invitation = verify_invitation(
                email.inner if email else participant.inner if participant else remote.inner if remote else raw
            )
            preview = invitation.preview()
            if email is not None:
                preview["connection_reply_available"] = True
                preview["invitation_digest"] = email.digest
                if email.inviter_access is not None:
                    preview["participant_access"] = preview_participant_access(
                        email.inviter_access
                    )
            elif participant is not None:
                preview["participant_access"] = preview_participant_access(
                    participant.access
                )
            elif remote is not None:
                preview["remote_profile"] = self.preview_remote_profile(remote.profile)
                preview["requires_network_consent"] = True
            return preview
        except ValidationError as exc:
            raise InvitationInvalid("Invitation could not be validated") from exc

    def accept_invitation(self, raw: str) -> dict[str, Any]:
        try:
            email = verify_email_invitation(raw, "personal")
            participant = None if email else verify_participant_invitation(raw, "personal")
            remote = None if email or participant else verify_remote_invitation(raw, "personal")
            invitation = verify_invitation(
                email.inner if email else participant.inner if participant else remote.inner if remote else raw
            )
        except ValidationError as exc:
            raise InvitationInvalid("Invitation could not be validated") from exc
        profile = self._require_profile()
        if invitation.destination_hash.hex() == profile["destination_hash"]:
            raise ValidationError("Cannot connect to the local identity")
        contact_id = _contact_id(invitation.destination_hash)
        participant_connection_results: list[dict[str, Any]] = []
        email_access = email.inviter_access if email is not None else None
        if participant is not None or email_access is not None:
            participant_record = self.approve_participant_access(
                participant.access if participant is not None else email_access,
                scope_kind="contact",
                scope_id=contact_id,
            )
            participant_connection_results = [
                dict(item) for item in participant_record.get("candidate_results", [])
            ]
        elif remote is not None:
            self._approve_remote_document(
                remote.profile,
                origin="personal_invitation",
                scope_kind="contact",
                scope_id=contact_id,
            )
        existing = self._contact_by_destination(invitation.destination_hash.hex())
        if existing:
            if existing["public_identity"] != _b64(invitation.public_identity):
                existing["trust"] = TrustState.IDENTITY_CHANGED.value
                self.store.put("contact", existing["id"], existing)
                raise ValidationError("A known contact presented a different identity")
            # A freshly signed invitation can carry a usable route that was not
            # present when this contact was first imported. Keep the contact's
            # hints in sync with the latest invitation, attach any new TCP peers
            # before retrying, and preserve the existing trust decision.
            previous_clients = [dict(hint) for hint in self.settings.tcp_clients]
            previous_hints = [dict(hint) for hint in existing.get("connection_hints", [])]
            existing["connection_hints"] = [dict(hint) for hint in invitation.hints]
            existing["updated_at"] = time.time()
            self.store.put("contact", existing["id"], existing)
            for hint in previous_hints:
                still_used = any(
                    hint in contact.get("connection_hints", [])
                    for contact in self.store.list("contact")
                    if contact["id"] != existing["id"]
                )
                if not still_used and hint in self.settings.tcp_clients:
                    self.settings.tcp_clients.remove(hint)
            self._apply_contact_hints(existing, previous_clients=previous_clients)
            if existing["trust"] == TrustState.AWAITING_CONSENT.value:
                self._ensure_contact_request(existing)
            # Importing a fresh signed invitation is an explicit way to reopen
            # a locally deleted conversation without replacing its trust or
            # cryptographic identity.
            self._unhide_conversation("direct", existing["id"])
            self._changed()
            return {
                **existing,
                **(
                    {"connection_results": participant_connection_results}
                    if participant_connection_results else {}
                ),
            }

        now = time.time()
        contact = Contact(
            id=_contact_id(invitation.destination_hash),
            display_name=invitation.display_name,
            public_identity=_b64(invitation.public_identity),
            identity_hash=invitation.identity_hash.hex(),
            destination_hash=invitation.destination_hash.hex(),
            fingerprint=invitation.fingerprint,
            trust=TrustState.AWAITING_CONSENT,
            connection_hints=invitation.hints,
            created_at=now,
            updated_at=now,
        ).to_dict()
        # Keep the signed profile name separately from the local label. Older
        # vaults do not have this field, so readers treat it as optional.
        contact["profile_name"] = invitation.display_name
        self.store.put("contact", contact["id"], contact)
        if self.network:
            self.network.remember_contact(invitation.public_identity, invitation.destination_hash)
        self._apply_contact_hints(contact)
        self._ensure_contact_request(contact)
        self._changed()
        return {
            **contact,
            **(
                {"connection_results": participant_connection_results}
                if participant_connection_results else {}
            ),
        }

    def create_connection_reply(self, raw: Any, purpose: Any) -> dict[str, Any]:
        if not isinstance(raw, str) or purpose not in {"personal", "workspace"}:
            raise ValidationError("Connection reply request is invalid")
        if self._identity is None:
            raise ValidationError("Local identity is unavailable")
        invitation = verify_email_invitation(raw, purpose)
        if invitation is None:
            raise ValidationError("A connection reply requires a v4 invitation")
        workspace_id = (
            verify_workspace_invitation(invitation.inner).workspace_id
            if purpose == "workspace"
            else None
        )
        previous = self.store.get("connection_response", invitation.digest)
        access = self.create_participant_host_access(
            purpose=purpose,
            scope_id=invitation.digest,
            maximum_expires_at=invitation.expires_at,
            access_mode="participant_callback",
        )
        host_session_id = access.pop("host_session_id")
        serialized = create_connection_response(
            self._identity, invitation.serialized, purpose, access
        )
        formats = connection_response_formats(serialized)
        response_record = {
            "id": invitation.digest,
            "purpose": purpose,
            "invitation_digest": invitation.digest,
            "peer_destination": invitation.signer_destination.hex(),
            "document": serialized,
            "host_session_id": host_session_id,
            "state": "ready",
            "preferred_external_port": next((
                int(item["port"]) for item in access["endpoints"]
                if item.get("path") in {"pcp", "upnp", "nat_pmp"}
            ), None),
            "created_at": time.time(),
            "expires_at": float(min(invitation.expires_at, access["expires_at"])),
        }
        if workspace_id is not None:
            response_record["workspace_id"] = workspace_id
        self.store.put("connection_response", invitation.digest, response_record)
        previous_host = previous.get("host_session_id") if previous else None
        if isinstance(previous_host, str) and previous_host != host_session_id:
            try:
                self.stop_participant_host(previous_host)
            except Exception:
                pass
        return {
            **formats,
            "purpose": purpose,
            "expires_at": min(invitation.expires_at, access["expires_at"]),
            "host_session_id": host_session_id,
            "methods": sorted({item["path"] for item in access["endpoints"]}),
        }

    def _verified_pending_response(self, raw: Any) -> tuple[Any, dict[str, Any], Any]:
        if not isinstance(raw, str):
            raise ValidationError("Connection reply must be text")
        unbound = verify_connection_response(raw)
        pending = self.store.get("email_invitation", unbound.invitation_digest)
        if pending is None:
            raise ValidationError("The original invitation is not available on this device")
        if pending.get("state") == "consumed":
            raise ValidationError("This connection reply was already used")
        if pending.get("state") != "active" or float(pending.get("expires_at", 0)) < time.time():
            raise ValidationError("The original invitation is no longer active")
        invitation = verify_email_invitation(
            pending.get("document", ""), pending.get("purpose")
        )
        if invitation is None:
            raise ValidationError("The original invitation is invalid")
        response = verify_connection_response(raw, invitation=invitation)
        profile = self._require_profile()
        if response.signer_destination.hex() != profile["destination_hash"]:
            raise ValidationError("Connection reply is for another profile")
        return response, pending, invitation

    def preview_connection_reply(self, raw: Any) -> dict[str, Any]:
        response, _pending, _invitation = self._verified_pending_response(raw)
        # Verification and preview intentionally perform no DNS lookup, socket
        # probe, interface attachment or trust mutation.
        return response.preview()

    def connect_using_reply(self, raw: Any) -> dict[str, Any]:
        response, pending, _invitation = self._verified_pending_response(raw)
        access = response.access
        scope = {"kind": "pending_invitation", "id": response.invitation_digest}
        access_record = {
            "id": access["id"], "access": access, "scopes": [scope],
            "resolved_endpoints": [], "candidate_results": [],
            "resolution_attempted": False,
            "consented_at": float(time.time()),
        }
        pending = dict(pending)
        pending.update({
            "state": "consumed",
            "consumed_at": time.time(),
            "responder_destination": response.responder_destination.hex(),
            "response_digest": hashlib.sha256(
                response.serialized.encode("utf-8")
            ).hexdigest(),
        })
        # Replay state and the exact scoped credential become durable in one
        # vault transaction before DNS, probing, or interface attachment.
        self.store.put_and_delete(
            [
                ("email_invitation", response.invitation_digest, pending),
                ("participant_access", access["id"], access_record),
            ],
            [],
            redact_command_cache=True,
        )
        original_host = pending.get("host_session_id")
        if isinstance(original_host, str):
            try:
                self.stop_participant_host(original_host)
            except Exception:
                pass
        resolved, results = self._resolved_participant_endpoints(access)
        access_record["resolved_endpoints"] = resolved
        access_record["candidate_results"] = results
        access_record["resolution_attempted"] = True
        self.store.put("participant_access", access["id"], access_record)
        self._apply_participant_interfaces()
        if self.network is not None:
            self.network.remember_contact(
                response.responder_public_identity, response.responder_destination
            )
            self.network.reannounce()
        self._changed()
        return {**response.preview(), "connection_results": results}

    def _bind_callback_host(
        self, purpose: str, peer_destination: str, *, scope_kind: str, scope_id: str
    ) -> None:
        relationship = {"kind": scope_kind, "id": scope_id}
        for response_id, response in self.store.items("connection_response"):
            if (
                response.get("purpose") != purpose
                or response.get("peer_destination") != peer_destination
                or response.get("state") not in {"ready", "shared", "active"}
            ):
                continue
            response["relationship_scope"] = relationship
            response["state"] = "active"
            response["updated_at"] = time.time()
            self.store.put("connection_response", response_id, response)
            host_id = response.get("host_session_id")
            host = self.store.get("participant_host", host_id) if isinstance(host_id, str) else None
            if host is not None:
                host["relationship_scope"] = relationship
                host["peer_destination"] = peer_destination
                self.store.put("participant_host", host_id, host)

    def _bind_workspace_callback_host(self, workspace_id: str) -> None:
        relationship = {"kind": "workspace_device", "id": workspace_id}
        for response_id, response in self.store.items("connection_response"):
            if response.get("purpose") != "workspace" or response.get("workspace_id") != workspace_id:
                continue
            response["relationship_scope"] = relationship
            response["state"] = "active"
            response["updated_at"] = time.time()
            self.store.put("connection_response", response_id, response)
            host_id = response.get("host_session_id")
            host = self.store.get("participant_host", host_id) if isinstance(host_id, str) else None
            if host is not None:
                host["relationship_scope"] = relationship
                host["peer_destination"] = response.get("peer_destination")
                self.store.put("participant_host", host_id, host)

    def _release_callback_hosts(self, scope_kind: str, scope_id: str) -> None:
        relationship = {"kind": scope_kind, "id": scope_id}
        host_ids: set[str] = set()
        response_ids: list[str] = []
        for response_id, response in self.store.items("connection_response"):
            if response.get("relationship_scope") != relationship:
                continue
            if isinstance(response.get("host_session_id"), str):
                host_ids.add(response["host_session_id"])
            response_ids.append(response_id)
        generation_ids: list[str] = []
        for generation_id, generation in self.store.items("route_generation"):
            if generation.get("relationship_scope") != relationship:
                continue
            if isinstance(generation.get("host_session_id"), str):
                host_ids.add(generation["host_session_id"])
            generation_ids.append(generation_id)
        for host_id in host_ids:
            try:
                self.stop_participant_host(host_id)
            except Exception:
                pass
        for response_id in response_ids:
            self.store.delete("connection_response", response_id)
        for generation_id in generation_ids:
            self.store.delete("route_generation", generation_id)

    def _stop_pending_callback_for_peer(self, purpose: str, peer_destination: str) -> None:
        for response_id, response in list(self.store.items("connection_response")):
            if response.get("purpose") != purpose or response.get("peer_destination") != peer_destination:
                continue
            host_id = response.get("host_session_id")
            if isinstance(host_id, str):
                try:
                    self.stop_participant_host(host_id)
                except Exception:
                    pass
            self.store.delete("connection_response", response_id)

    def _contact_route_scope(self, peer_destination: bytes) -> str:
        profile = self._require_profile()
        local = bytes.fromhex(profile["destination_hash"])
        first, second = sorted((local, peer_destination))
        return hashlib.sha256(
            b"mesh-chat:contact-route:v1:" + first + second
        ).hexdigest()

    def _route_update_binding(
        self, scope_kind: Any, scope_id: Any, peer_destination: Any = None
    ) -> tuple[str, bytes, bytes, str]:
        if scope_kind == "contact":
            contact = self._require_contact(scope_id)
            if contact["trust"] not in {TrustState.APPROVED.value, TrustState.VERIFIED.value}:
                raise ContactNotApproved("Reconnect updates require an approved contact")
            peer = bytes.fromhex(contact["destination_hash"])
            return self._contact_route_scope(peer), peer, _unb64(contact["public_identity"]), contact["display_name"]
        if scope_kind != "workspace_device" or not isinstance(scope_id, str) or not isinstance(peer_destination, str):
            raise ValidationError("Route update scope is invalid")
        workspace = self._require_workspace(scope_id)
        if workspace.get("state") != "active":
            raise ValidationError("Workspace is not active")
        manifest = self._workspace_current_manifest(workspace)
        for member in manifest.members:
            if member.status != "active":
                continue
            for device in member.devices:
                if device.destination_hash.hex() == peer_destination:
                    return scope_id, device.destination_hash, device.public_identity, member.display_name
        raise ValidationError("Workspace device is not admitted")

    def create_route_update_command(
        self, scope_kind: Any, scope_id: Any, peer_destination: Any = None,
        *, preferred_external_port: int | None = None,
    ) -> dict[str, Any]:
        if self._identity is None:
            raise ValidationError("Local identity is unavailable")
        canonical_scope, audience, _public_key, _label = self._route_update_binding(
            scope_kind, scope_id, peer_destination
        )
        generation_id = f"out:{scope_kind}:{canonical_scope}:{audience.hex()}"
        generation_record = self.store.get("route_generation", generation_id) or {"generation": 0}
        generation = int(generation_record.get("generation", 0)) + 1
        access = self.create_participant_host_access(
            purpose="personal" if scope_kind == "contact" else "workspace",
            scope_id=canonical_scope,
            maximum_expires_at=int(time.time()) + 24 * 60 * 60,
            access_mode="participant_callback",
            preferred_external_port=preferred_external_port,
        )
        host_session_id = access.pop("host_session_id")
        serialized = create_signed_route_update(
            self._identity,
            scope_kind=scope_kind,
            scope_id=canonical_scope,
            audience_destination=audience,
            generation=generation,
            access=access,
        )
        self.store.put("route_generation", generation_id, {
            "id": generation_id, "generation": generation,
            "updated_at": time.time(), "host_session_id": host_session_id,
            "relationship_scope": {"kind": scope_kind, "id": scope_id},
            "peer_destination": audience.hex(),
            "preferred_external_port": next((
                int(item["port"]) for item in access["endpoints"]
                if item.get("path") in {"pcp", "upnp", "nat_pmp"}
            ), None),
        })
        host_record = self.store.get("participant_host", host_session_id)
        if host_record is not None:
            host_record["relationship_scope"] = {"kind": scope_kind, "id": scope_id}
            host_record["peer_destination"] = audience.hex()
            self.store.put("participant_host", host_session_id, host_record)
        delivered_live = self._send_live_route_update(
            serialized, audience=audience, recipient_public_key=_public_key,
            expires_at=int(access["expires_at"]),
        )
        return {
            **route_update_formats(serialized),
            "expires_at": access["expires_at"],
            "generation": generation,
            "host_session_id": host_session_id,
            "methods": sorted({item["path"] for item in access["endpoints"]}),
            "delivery_mode": "automatic" if delivered_live else "share_required",
        }

    def _send_live_route_update(
        self, serialized: str, *, audience: bytes,
        recipient_public_key: bytes, expires_at: int,
    ) -> bool:
        if self.network is None:
            return False
        path_known = getattr(self.network, "path_known", None)
        recipient_ready = getattr(self.network, "recipient_ready", None)
        if (
            not callable(path_known)
            or not callable(recipient_ready)
            or not path_known(audience)
            or not recipient_ready(audience)
        ):
            return False
        try:
            profile = self._require_profile()
            local = bytes.fromhex(profile["destination_hash"])
            self.network.send(
                logical_id=_new_id(),
                conversation_id=conversation_id(local, audience),
                recipient_public_key=recipient_public_key,
                recipient_destination=audience,
                kind=MessageKind.ROUTE_UPDATE,
                text="",
                expires_at=expires_at,
                route_update=serialized,
                propagated=False,
            )
            return True
        except Exception:
            return False

    def _refresh_callback_routes(self) -> None:
        """Refresh an expiring hosted route over an already usable Reticulum path."""

        if self.network is None:
            return
        path_known = getattr(self.network, "path_known", None)
        recipient_ready = getattr(self.network, "recipient_ready", None)
        if not callable(path_known) or not callable(recipient_ready):
            return
        now = time.time()
        for host_id, host in list(self.store.items("participant_host")):
            relationship = host.get("relationship_scope")
            peer_text = host.get("peer_destination")
            if (
                not isinstance(relationship, dict)
                or relationship.get("kind") not in {"contact", "workspace_device"}
                or not isinstance(relationship.get("id"), str)
                or not isinstance(peer_text, str)
                or host.get("refresh_superseded") is True
                or (
                    host.get("state") != "unavailable"
                    and float(host.get("expires_at", 0))
                    > now + ROUTE_REFRESH_MARGIN_SECONDS
                )
                or now - float(host.get("refresh_attempted_at", 0))
                < ROUTE_REFRESH_RETRY_SECONDS
            ):
                continue
            try:
                peer = bytes.fromhex(peer_text)
            except ValueError:
                continue
            if not path_known(peer) or not recipient_ready(peer):
                continue
            host["refresh_attempted_at"] = now
            self.store.put("participant_host", host_id, host)
            try:
                refreshed = self.create_route_update_command(
                    relationship["kind"],
                    relationship["id"],
                    peer_text if relationship["kind"] == "workspace_device" else None,
                    preferred_external_port=next((
                        int(item["port"])
                        for item in (host.get("access") or {}).get("endpoints", [])
                        if item.get("path") in {"pcp", "upnp", "nat_pmp"}
                    ), None),
                )
            except Exception:
                continue
            if refreshed.get("delivery_mode") == "automatic":
                host["refresh_superseded"] = True
                host["refreshed_at"] = now
                self.store.put("participant_host", host_id, host)
                for response_id, response in self.store.items("connection_response"):
                    if response.get("host_session_id") == host_id:
                        response["state"] = "route_refreshed"
                        response["updated_at"] = now
                        self.store.put("connection_response", response_id, response)

        # A clean shutdown removes actual listeners and router mappings, but
        # retains only encrypted relationship metadata. On restart, rebuild a
        # listener only when another Reticulum path is already usable, asking
        # the router for the prior external port as a preference. The returned
        # signed update contains the actual restored mapping, never the wish.
        restart_candidates = [
            record for _record_id, record in self.store.items("route_generation")
            if str(record.get("id", "")).startswith("out:")
            and isinstance(record.get("relationship_scope"), dict)
        ]
        restart_candidates.extend(
            response for _response_id, response in self.store.items("connection_response")
            if response.get("state") == "active"
            and isinstance(response.get("relationship_scope"), dict)
        )
        for candidate in restart_candidates:
            host_id = candidate.get("host_session_id")
            if isinstance(host_id, str) and self.store.get("participant_host", host_id) is not None:
                continue
            relationship = candidate.get("relationship_scope")
            peer_text = candidate.get("peer_destination")
            if (
                not isinstance(relationship, dict)
                or relationship.get("kind") not in {"contact", "workspace_device"}
                or not isinstance(relationship.get("id"), str)
                or not isinstance(peer_text, str)
            ):
                continue
            try:
                peer = bytes.fromhex(peer_text)
            except ValueError:
                continue
            if not path_known(peer) or not recipient_ready(peer):
                continue
            try:
                refreshed = self.create_route_update_command(
                    relationship["kind"],
                    relationship["id"],
                    peer_text if relationship["kind"] == "workspace_device" else None,
                    preferred_external_port=candidate.get("preferred_external_port"),
                )
            except Exception:
                continue
            if (
                refreshed.get("delivery_mode") == "automatic"
                and isinstance(candidate.get("invitation_digest"), str)
            ):
                response_id = candidate["invitation_digest"]
                response = self.store.get("connection_response", response_id)
                if response is not None:
                    response["state"] = "route_refreshed"
                    response["updated_at"] = now
                    self.store.put("connection_response", response_id, response)

    def _verified_scoped_route_update(self, raw: Any) -> tuple[Any, str, str]:
        if not isinstance(raw, str):
            raise ValidationError("Reconnect update must be text")
        update = verify_route_update(raw)
        profile = self._require_profile()
        if update.audience_destination.hex() != profile["destination_hash"]:
            raise ValidationError("Reconnect update is for another profile")
        label = ""
        durable_scope = update.scope_id
        if update.scope_kind == "contact":
            contact = self._contact_by_destination(update.issuer_destination.hex())
            if contact is None or contact["trust"] not in {
                TrustState.APPROVED.value, TrustState.VERIFIED.value
            }:
                raise ContactNotApproved("Reconnect update issuer is not an approved contact")
            if _unb64(contact["public_identity"]) != update.issuer_public_identity:
                raise ValidationError("Reconnect update identity changed")
            durable_scope = contact["id"]
            label = contact["display_name"]
            if update.scope_id != self._contact_route_scope(update.issuer_destination):
                raise ValidationError("Reconnect update contact scope is invalid")
        else:
            workspace = self._require_workspace(update.scope_id)
            if workspace.get("state") != "active":
                raise ValidationError("Workspace is not active")
            manifest = self._workspace_current_manifest(workspace)
            device_match = next((
                (member, device)
                for member in manifest.members if member.status == "active"
                for device in member.devices
                if device.destination_hash == update.issuer_destination
            ), None)
            if device_match is None or device_match[1].public_identity != update.issuer_public_identity:
                raise ValidationError("Reconnect update issuer is not an admitted device")
            label = device_match[0].display_name
        generation_id = f"in:{update.scope_kind}:{update.scope_id}:{update.issuer_destination.hex()}"
        previous = self.store.get("route_generation", generation_id)
        if previous is not None and update.generation <= int(previous.get("generation", 0)):
            raise ValidationError("Reconnect update is stale or was already used")
        return update, durable_scope, label

    def preview_route_update(self, raw: Any) -> dict[str, Any]:
        update, _scope, label = self._verified_scoped_route_update(raw)
        return {**update.preview(), "issuer_display_name": label}

    def apply_route_update(self, raw: Any) -> dict[str, Any]:
        update, durable_scope, label = self._verified_scoped_route_update(raw)
        generation_id = f"in:{update.scope_kind}:{update.scope_id}:{update.issuer_destination.hex()}"
        generation_record = {
            "id": generation_id, "generation": update.generation,
            "updated_at": time.time(),
        }
        record = self.replace_participant_scope_access(
            update.access,
            scope_kind="contact" if update.scope_kind == "contact" else "workspace_device",
            scope_id=durable_scope,
            additional_writes=[("route_generation", generation_id, generation_record)],
        )
        if self.network is not None:
            self.network.remember_contact(
                update.issuer_public_identity, update.issuer_destination
            )
            self.network.reannounce()
        self._changed()
        return {
            **update.preview(), "issuer_display_name": label,
            "connection_results": record.get("candidate_results", []),
        }

    def _ensure_contact_request(self, contact: dict[str, Any]) -> dict[str, Any]:
        for message in self.store.list("message"):
            if (
                message["contact_id"] == contact["id"]
                and message["direction"] == "outbound"
                and message["kind"] == MessageKind.CONTACT_REQUEST.value
                and message["expires_at"] > time.time()
            ):
                self._attempt(message["id"])
                return message
        request = self._create_outbound(
            contact,
            MessageKind.CONTACT_REQUEST,
            "",
            invitation=self.invitation()["file"],
        )
        self._attempt(request["id"])
        return request

    def approve_request(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] != TrustState.PENDING_REQUEST.value:
            raise ValidationError("Contact request is no longer pending")
        contact["trust"] = TrustState.APPROVED.value
        contact["updated_at"] = time.time()
        # Make the acceptance durable before touching live interfaces. If an
        # optional route cannot be activated, the joining device can still be
        # answered by the retryable outbox instead of being left waiting on an
        # Approved contact that has no acceptance record.
        accepted = self._outbound_record(contact, MessageKind.CONTACT_ACCEPT, "")
        self.store.put_many(
            [
                ("contact", contact_id, contact),
                ("message", accepted["id"], accepted),
            ]
        )
        self.promote_pending_callback(
            contact["destination_hash"],
            scope_kind="contact",
            scope_id=contact_id,
            purpose="personal",
        )
        self._apply_contact_hints(contact)
        # Flush once. Calling _attempt() first would change the acceptance to
        # `sending`, then immediately submit the same durable packet again.
        self._flush_contact(contact_id)
        self._changed()
        return contact

    def decline_request(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] == TrustState.PENDING_REQUEST.value:
            declined = self._create_outbound(contact, MessageKind.CONTACT_DECLINE, "")
            self._attempt(declined["id"])
        contact["trust_before_block"] = contact["trust"]
        contact["trust"] = TrustState.BLOCKED.value
        contact["updated_at"] = time.time()
        self.store.put("contact", contact_id, contact)
        self.decline_pending_callbacks(
            contact["destination_hash"],
            purpose="personal",
            legacy_scope_kind="contact",
            legacy_scope_id=contact_id,
        )
        self._changed()
        return contact

    def update_contact(self, contact_id: str, display_name: Any) -> dict[str, Any]:
        """Change the label shown for a contact on this device only."""

        contact = self._require_contact(contact_id)
        contact.setdefault("profile_name", contact["display_name"])
        contact["display_name"] = _display_name(display_name)
        contact["updated_at"] = time.time()
        self.store.put("contact", contact_id, contact)
        self._changed()
        return contact

    def verify_contact(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] not in {
            TrustState.APPROVED.value,
            TrustState.VERIFIED.value,
        }:
            raise ContactNotApproved("Only approved contacts can be verified")
        contact["trust"] = TrustState.VERIFIED.value
        contact.pop("trust_before_block", None)
        contact["updated_at"] = time.time()
        self.store.put("contact", contact_id, contact)
        self._changed()
        return contact

    def unverify_contact(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] not in {
            TrustState.APPROVED.value,
            TrustState.VERIFIED.value,
        }:
            raise ContactNotApproved("Contact is not currently approved")
        contact["trust"] = TrustState.APPROVED.value
        contact.pop("trust_before_block", None)
        contact["updated_at"] = time.time()
        self.store.put("contact", contact_id, contact)
        self._changed()
        return contact

    def block_contact(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] != TrustState.BLOCKED.value:
            contact["trust_before_block"] = contact["trust"]
            contact["trust"] = TrustState.BLOCKED.value
            contact["updated_at"] = time.time()
            self.store.put("contact", contact_id, contact)
            self._changed()
        return contact

    def unblock_contact(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] != TrustState.BLOCKED.value:
            raise ValidationError("Contact is not blocked")
        previous = contact.get("trust_before_block")
        if previous not in {
            TrustState.AWAITING_CONSENT.value,
            TrustState.PENDING_REQUEST.value,
            TrustState.APPROVED.value,
            TrustState.VERIFIED.value,
            TrustState.IDENTITY_CHANGED.value,
        }:
            raise ValidationError("This blocked contact cannot be restored safely")
        contact["trust"] = previous
        contact.pop("trust_before_block", None)
        contact["updated_at"] = time.time()
        self.store.put("contact", contact_id, contact)
        if previous == TrustState.AWAITING_CONSENT.value:
            self._ensure_contact_request(contact)
        elif previous in {TrustState.APPROVED.value, TrustState.VERIFIED.value}:
            self._flush_contact(contact_id)
        self._changed()
        return contact

    def delete_contact(self, contact_id: str) -> dict[str, Any]:
        """Forget a contact and all of its direct-chat state on this device.

        Group membership is independent from direct-contact trust. Embedded
        member identity cards remain usable; only their local address-book
        link is removed.
        """

        contact = self._require_contact(contact_id)
        if any(
            member.get("contact_id") == contact_id
            and member.get("status") in {"invited", "joining"}
            for group in self.store.list("group")
            for member in group.get("members", [])
        ):
            raise ContactInUse(
                "Remove the contact from pending group invitations before deleting it"
            )
        deleted = self.delete_conversation("direct", contact_id)
        remaining_messages = [
            message
            for message in self.store.list("message")
            if message.get("contact_id") == contact_id
        ]
        outbound_ids = {
            message["id"]
            for message in remaining_messages
            if message.get("direction") == "outbound"
        }
        writes: list[tuple[str, str, dict[str, Any]]] = []
        for group in self.store.list("group"):
            changed = False
            for member in group.get("members", []):
                if member.get("contact_id") == contact_id:
                    member.pop("contact_id", None)
                    changed = True
            if changed:
                writes.append(("group", group["id"], group))
        previous_clients = [dict(hint) for hint in self.settings.tcp_clients]
        desired_clients = [dict(hint) for hint in self.settings.tcp_clients]
        remaining_contacts = [
            other
            for other in self.store.list("contact")
            if other.get("id") != contact_id
        ]
        for hint in contact.get("connection_hints", []):
            still_used = any(
                hint in other.get("connection_hints", [])
                for other in remaining_contacts
            )
            if not still_used and hint in desired_clients:
                desired_clients.remove(hint)
        settings_changed = desired_clients != previous_clients
        if settings_changed:
            settings_record = self.settings.to_dict()
            settings_record["tcp_clients"] = desired_clients
            writes.append(("settings", "network", settings_record))
        deletions = [
            ("message", message["id"]) for message in remaining_messages
        ]
        deletions.extend(
            [
                ("contact", contact_id),
                ("draft", contact_id),
                (
                    "conversation_hidden",
                    self._conversation_marker_id("direct", contact_id),
                ),
            ]
        )
        deletions.extend(self._reaction_deletions("direct", contact_id))
        self.store.put_and_delete(writes, deletions, redact_command_cache=True)
        self.release_remote_scope("contact", contact_id)
        self.release_participant_scope("contact", contact_id)
        self._release_callback_hosts("contact", contact_id)
        for record_id, record in list(self.store.items("route_generation")):
            if (
                contact["destination_hash"] in record_id
                or record.get("relationship_scope") == {"kind": "contact", "id": contact_id}
            ):
                self.store.delete("route_generation", record_id)

        if settings_changed:
            self.settings.tcp_clients = desired_clients
            if self.network:
                try:
                    self.network.apply_connection_settings(self.settings)
                    self._connection_settings_dirty = False
                except Exception:
                    self._connection_settings_dirty = True
        if self.network is not None and outbound_ids:
            cancel_outbound = getattr(self.network, "cancel_outbound", None)
            if callable(cancel_outbound):
                try:
                    cancel_outbound(outbound_ids)
                except Exception:
                    pass
        self._changed()
        return {
            "contact_id": contact_id,
            "deleted_messages": deleted["deleted_messages"],
        }

    def send_message(self, contact_id: str, text: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if contact["trust"] in {
            TrustState.BLOCKED.value,
            TrustState.IDENTITY_CHANGED.value,
            TrustState.PENDING_REQUEST.value,
        }:
            raise ContactNotApproved("Contact is not approved for outbound chat")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Message is empty")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValidationError("Message exceeds the 16 KiB limit")
        message = self._create_outbound(contact, MessageKind.CHAT, text)
        if contact["trust"] in {TrustState.APPROVED.value, TrustState.VERIFIED.value}:
            self._attempt(message["id"])
        self._changed()
        return self.store.get("message", message["id"]) or message

    @staticmethod
    def _conversation_marker_id(kind: str, target_id: str) -> str:
        digest = RNS.Identity.full_hash(
            b"mesh-chat:hidden-conversation:v1:" + kind.encode("ascii") + b":" + target_id.encode("utf-8")
        )
        return str(uuid.UUID(bytes=digest[:16]))

    @staticmethod
    def _discard_marker_id(kind: str, target_id: str, message_id: str) -> str:
        digest = RNS.Identity.full_hash(
            b"mesh-chat:discarded-message:v1:"
            + kind.encode("ascii")
            + b":"
            + target_id.encode("utf-8")
            + b":"
            + message_id.encode("utf-8")
        )
        return str(uuid.UUID(bytes=digest[:16]))

    @staticmethod
    def _discarded_target_id(kind: str, target_id: str, message_id: str) -> str:
        digest = RNS.Identity.full_hash(
            b"mesh-chat:discarded-reaction-target:v1:"
            + kind.encode("ascii")
            + b":"
            + target_id.encode("utf-8")
            + b":"
            + message_id.encode("utf-8")
        )
        return str(uuid.UUID(bytes=digest[:16]))

    def _discarded_target_marker(
        self, kind: str, target_id: str, message_id: str
    ) -> tuple[str, str, dict[str, Any]]:
        marker_id = self._discarded_target_id(kind, target_id, message_id)
        return (
            "discarded_target",
            marker_id,
            {
                "id": marker_id,
                "kind": kind,
                "target_id": target_id,
                "message_id": message_id,
            },
        )

    def _unhide_conversation(self, kind: str, target_id: str) -> None:
        self.store.delete(
            "conversation_hidden", self._conversation_marker_id(kind, target_id)
        )

    def _message_was_discarded(
        self, kind: str, target_id: str, message_id: str
    ) -> bool:
        target_marker = self.store.get(
            "discarded_target",
            self._discarded_target_id(kind, target_id, message_id),
        )
        if target_marker is not None:
            return (
                target_marker.get("kind") == kind
                and target_marker.get("target_id") == target_id
                and target_marker.get("message_id") == message_id
            )
        marker_id = self._discard_marker_id(kind, target_id, message_id)
        marker = self.store.get("discarded_message", marker_id)
        if marker is None:
            return False
        if int(marker.get("expires_at", 0)) < int(time.time()):
            self.store.delete("discarded_message", marker_id)
            return False
        return marker.get("kind") == kind and marker.get("target_id") == target_id

    def _discard_marker(
        self, kind: str, target_id: str, message: dict[str, Any], now: float
    ) -> tuple[str, str, dict[str, Any]] | None:
        # Protocol validation rejects packets more than one day beyond their
        # delivery window. Keep only the small replay marker needed until then;
        # the deleted plaintext and other message metadata are not retained.
        expires_at = int(float(message.get("expires_at", 0))) + DELETED_MESSAGE_REPLAY_GRACE_SECONDS
        if expires_at < int(now):
            return None
        message_id = message["id"]
        marker_id = self._discard_marker_id(kind, target_id, message_id)
        return (
            "discarded_message",
            marker_id,
            {
                "id": marker_id,
                "kind": kind,
                "target_id": target_id,
                "message_id": message_id,
                "expires_at": expires_at,
            },
        )

    def _prune_discarded_messages(self) -> None:
        now = time.time()
        for marker in self.store.list("discarded_message"):
            if int(marker.get("expires_at", 0)) < int(now):
                self.store.delete("discarded_message", marker["id"])

    def delete_conversation(self, kind: str, target_id: str) -> dict[str, Any]:
        """Erase local chat content while preserving trust and group state.

        Deletion cannot recall packets which Reticulum/LXMF already handed to
        another device. It does stop retrying chat payloads still in this
        device's outbox. Membership manifests and contact-control records stay
        intact so deleting history never changes cryptographic identity or
        silently leaves/closes a group.
        """

        if (
            not isinstance(kind, str)
            or not isinstance(target_id, str)
            or kind not in {"direct", "group"}
        ):
            raise ValidationError("Conversation target is invalid")
        now = time.time()
        writes: list[tuple[str, str, dict[str, Any]]] = []
        deletions: list[tuple[str, str]] = []
        removed_ids: set[str] = set()
        native_chat_ids: set[str] = set()
        if kind == "direct":
            self._require_contact(target_id)
            records = [
                message
                for message in self.store.list("message")
                if message.get("contact_id") == target_id
                and (
                    message.get("kind")
                    in {MessageKind.CHAT.value, MessageKind.REACTION.value}
                    or message.get("reaction_receipt") is True
                )
            ]
            messages = [
                message
                for message in records
                if message.get("kind") == MessageKind.CHAT.value
            ]
            removed_ids = {message["id"] for message in messages}
            native_chat_ids.update(
                message["id"]
                for message in records
                if message.get("direction") == "outbound"
            )
            for message in records:
                deletions.append(("message", message["id"]))
                if message.get("kind") == MessageKind.CHAT.value:
                    writes.append(
                        self._discarded_target_marker(
                            kind, target_id, message["id"]
                        )
                    )
                if (
                    message.get("kind") == MessageKind.CHAT.value
                    and message.get("direction") == "inbound"
                ):
                    marker = self._discard_marker(kind, target_id, message, now)
                    if marker is not None:
                        writes.append(marker)
            deletions.append(("draft", target_id))
            deletions.extend(self._reaction_deletions(kind, target_id))
        else:
            self._require_group(target_id)
            messages = [
                message
                for message in self.store.list("group_message")
                if message.get("group_id") == target_id
            ]
            removed_ids = {message["id"] for message in messages}
            for message in messages:
                deletions.append(("group_message", message["id"]))
                writes.append(
                    self._discarded_target_marker(kind, target_id, message["id"])
                )
                if message.get("direction") == "inbound":
                    marker = self._discard_marker(kind, target_id, message, now)
                    if marker is not None:
                        writes.append(marker)
            for delivery in self.store.list("group_delivery"):
                if delivery.get("group_id") != target_id:
                    continue
                if delivery.get("kind") in {
                    MessageKind.GROUP_CHAT.value,
                    MessageKind.GROUP_REACTION.value,
                } or delivery.get("reaction_receipt") is True:
                    deletions.append(("group_delivery", delivery["id"]))
                    native_chat_ids.add(delivery["id"])
            deletions.append(("group_draft", target_id))
            deletions.extend(self._reaction_deletions(kind, target_id))

        notification_ids = {
            self._personal_notification_id(kind, target_id, message_id)
            for message_id in removed_ids
        }
        for notification_id in notification_ids:
            deletions.extend(
                [
                    ("workspace_notification_ledger", notification_id),
                    ("workspace_notification_route", notification_id),
                    ("workspace_notification_work", notification_id),
                ]
            )
        notification_queue_id = self._workspace_notification_queue_id()
        notification_queue = self.store.get(
            "workspace_notification_queue", notification_queue_id
        )
        if notification_queue is not None and notification_ids:
            notification_queue["entries"] = [
                item
                for item in notification_queue.get("entries", ())
                if item not in notification_ids
            ]
            notification_queue["updated_at"] = now
            writes.append(
                (
                    "workspace_notification_queue",
                    notification_queue_id,
                    notification_queue,
                )
            )

        hidden_id = self._conversation_marker_id(kind, target_id)
        writes.append(
            (
                "conversation_hidden",
                hidden_id,
                {"id": hidden_id, "kind": kind, "target_id": target_id, "hidden_at": now},
            )
        )
        self.store.put_and_delete(writes, deletions, redact_command_cache=True)
        # Change transport state only after the privacy mutation is durable. A
        # storage failure leaves the original message/outbox untouched and
        # reportable instead of stranding a SENDING record. Late native
        # callbacks after this commit safely find no application record.
        if self.network is not None and native_chat_ids:
            cancel_outbound = getattr(self.network, "cancel_outbound", None)
            if callable(cancel_outbound):
                try:
                    cancel_outbound(native_chat_ids)
                except Exception:
                    # The vault deletion has already committed. Treat native
                    # cancellation as best-effort cleanup so a misbehaving
                    # adapter cannot turn a successful privacy mutation into
                    # a misleading failure (or invite a destructive retry).
                    pass
        self._changed()
        return {"kind": kind, "id": target_id, "deleted_messages": len(removed_ids)}

    def restore_conversation(self, kind: str, target_id: str) -> dict[str, Any]:
        if not isinstance(kind, str) or not isinstance(target_id, str):
            raise ValidationError("Conversation target is invalid")
        if kind == "direct":
            self._require_contact(target_id)
        elif kind == "group":
            self._require_group(target_id)
        else:
            raise ValidationError("Conversation target is invalid")
        self._unhide_conversation(kind, target_id)
        self._changed()
        return {"kind": kind, "id": target_id, "restored": True}

    def _create_outbound(
        self,
        contact: dict[str, Any],
        kind: MessageKind,
        text: str,
        *,
        receipt_for: str | None = None,
        invitation: str | None = None,
    ) -> dict[str, Any]:
        message = self._outbound_record(
            contact,
            kind,
            text,
            receipt_for=receipt_for,
            invitation=invitation,
        )
        if kind == MessageKind.CHAT:
            self.store.put_and_delete(
                [("message", message["id"], message)],
                [
                    (
                        "conversation_hidden",
                        self._conversation_marker_id("direct", contact["id"]),
                    )
                ],
            )
        else:
            self.store.put("message", message["id"], message)
        return message

    def _outbound_record(
        self,
        contact: dict[str, Any],
        kind: MessageKind,
        text: str,
        *,
        receipt_for: str | None = None,
        invitation: str | None = None,
    ) -> dict[str, Any]:
        """Build an outbound record without committing it.

        Approval uses this to atomically commit its trust transition and the
        matching CONTACT_ACCEPT job. Other callers use ``_create_outbound``
        for the ordinary single-record transaction.
        """
        profile = self._require_profile()
        now = time.time()
        message = Message(
            id=_new_id(),
            conversation_id=conversation_id(
                bytes.fromhex(profile["destination_hash"]),
                bytes.fromhex(contact["destination_hash"]),
            ),
            contact_id=contact["id"],
            direction="outbound",
            kind=kind,
            text=text,
            state=DeliveryState.QUEUED,
            created_at=now,
            expires_at=now + DELIVERY_WINDOW_SECONDS,
            receipt_for=receipt_for,
        ).to_dict()
        if invitation is not None:
            message["invitation"] = invitation
        return message

    def _attempt(self, message_id: str) -> None:
        message = self.store.get("message", message_id)
        if not message or message["direction"] != "outbound":
            return
        # Only durable retry states may create a new native LXMF handoff. An
        # in-flight packet (or one already accepted by an endpoint/propagation
        # node) remains pending until its callback, app receipt, expiry, or
        # explicit recovery after restart changes it back to a retry state.
        if message["state"] not in DIRECT_RETRY_STATES:
            return
        if message["expires_at"] <= time.time():
            if (
                message.get("kind") == MessageKind.REACTION.value
                or message.get("reaction_receipt") is True
            ):
                self.store.delete("message", message_id)
                return
            message["state"] = DeliveryState.EXPIRED.value
            self.store.put("message", message_id, message)
            return
        contact = self._require_contact(message["contact_id"])
        kind = MessageKind(message["kind"])
        allowed = contact["trust"] in {TrustState.APPROVED.value, TrustState.VERIFIED.value}
        if kind == MessageKind.CONTACT_REQUEST:
            allowed = contact["trust"] == TrustState.AWAITING_CONSENT.value
        elif kind == MessageKind.CONTACT_DECLINE:
            allowed = contact["trust"] == TrustState.PENDING_REQUEST.value
        if not allowed or self.network is None:
            return
        # The persisted client list is bounded. A newly approved contact can
        # therefore displace an older contact's direct route. Bring the contact
        # currently being used back to the front before checking keys or
        # attempting delivery; `_apply_contact_hints` is a no-op while its
        # preferred hints are already active.
        contact_hints = contact.get("connection_hints", [])
        if self._connection_settings_dirty or (
            contact_hints
            and any(hint not in self.settings.tcp_clients for hint in contact_hints)
        ):
            self._apply_contact_hints(contact)
        try:
            destination = bytes.fromhex(contact["destination_hash"])
            prefer_signed_route = getattr(self.network, "prefer_signed_route", None)
            if callable(prefer_signed_route):
                # A route learned earlier over nearby discovery can remain
                # selected even after the signed TCP hint connects. Give the
                # exact contact client a short, targeted chance to replace it,
                # but allow normal Reticulum fallback when it does not respond
                # so one bad hint cannot pin the durable outbox indefinitely.
                prefer_signed_route(destination, contact_hints)
            if not self.network.recipient_ready(destination):
                message["state"] = DeliveryState.WAITING_FOR_KEYS.value
                self.store.put("message", message_id, message)
                self.network.request_path(destination)
                return
            propagated = bool(
                self.settings.approved_propagation_nodes
            ) and not self.network.path_known(destination)
            send_values: dict[str, Any] = {
                "logical_id": message["id"],
                "conversation_id": message["conversation_id"],
                "recipient_public_key": _unb64(contact["public_identity"]),
                "recipient_destination": destination,
                "kind": kind,
                "text": message["text"],
                "expires_at": int(message["expires_at"]),
                "receipt_for": message.get("receipt_for"),
                "invitation": message.get("invitation"),
                "propagated": propagated,
            }
            if kind == MessageKind.REACTION:
                send_values.update(
                    {
                        "reaction_for": message.get("reaction_for"),
                        "reaction_emoji": message.get("reaction_emoji"),
                        "reaction_active": message.get("reaction_active"),
                        "reaction_revision": message.get("reaction_revision"),
                    }
                )
            native_id = self.network.send(
                **send_values,
            )
            # ``ReticulumNetwork.send`` reports SENDING before it returns, and
            # a fast endpoint can report stronger evidence (or even an app
            # receipt) before this frame resumes. Re-read the durable record so
            # this call cannot overwrite that callback with its stale QUEUED
            # copy. Networks used by tests or future adapters may not emit the
            # initial callback, so fill in SENDING only when this native handoff
            # has not already been observed.
            current = self.store.get("message", message_id)
            if current is not None:
                callback_observed = current.get("native_message_id") == native_id
                if not callback_observed:
                    current["native_message_id"] = native_id
                    if current["state"] in DIRECT_RETRY_STATES:
                        current["state"] = DeliveryState.SENDING.value
                    self.store.put("message", message_id, current)
        except MeshChatError as exc:
            current = self.store.get("message", message_id)
            if current is None:
                return
            # A native adapter can report endpoint/storage evidence from a
            # synchronous callback and then raise while unwinding its local
            # handoff. The callback is stronger than the send-frame error; do
            # not retract it into a retry state.
            if current["state"] not in DIRECT_ENDPOINT_EVIDENCE:
                current["state"] = (
                    DeliveryState.WAITING_FOR_KEYS.value
                    if exc.code == "recipient_keys_unavailable"
                    else DeliveryState.QUEUED.value
                )
                self.store.put("message", message_id, current)
        except Exception:
            # RNS/LXMF can surface raw transport exceptions. The message is
            # already durable, so keep it queued for the bounded retry worker
            # instead of failing the renderer command after state was saved.
            current = self.store.get("message", message_id)
            if current is None:
                return
            if current["state"] not in DIRECT_ENDPOINT_EVIDENCE:
                current["state"] = DeliveryState.QUEUED.value
                self.store.put("message", message_id, current)

    def _on_native_status(
        self, logical_id: str, state: DeliveryState, native_id: str | None
    ) -> None:
        with self._dispatch_lock:
            self._on_native_status_locked(logical_id, state, native_id)

    def _on_native_status_locked(
        self, logical_id: str, state: DeliveryState, native_id: str | None
    ) -> None:
        message = self.store.get("message", logical_id)
        if message is None or message.get("direction") != "outbound":
            if not self._on_group_native_status(logical_id, state, native_id):
                self._on_workspace_native_status(logical_id, state, native_id)
            return
        if message["state"] == DeliveryState.DELIVERED.value:
            if (
                message.get("kind") == MessageKind.REACTION.value
                or message.get("reaction_receipt") is True
            ):
                self.store.delete("message", logical_id)
            return
        cleanup_reaction_operation = bool(
            state
            in {DeliveryState.RECEIVED_BY_ENDPOINT, DeliveryState.DELIVERED}
            and (
                message.get("kind") == MessageKind.REACTION.value
                or message.get("reaction_receipt") is True
            )
        )
        if (
            message.get("kind") == MessageKind.REACTION.value
            and state == DeliveryState.RECEIVED_BY_ENDPOINT
        ):
            # Reactions are an optional v1 extension. An older endpoint can
            # authenticate and receive the LXMF packet but intentionally ignore
            # the unknown kind, so requiring an app receipt would resend it on
            # every restart until the seven-day window closed. Endpoint proof
            # is final for this ephemeral mutation only; chats still require
            # their application receipt.
            state = DeliveryState.DELIVERED
        current_state = message["state"]
        current_native_id = message.get("native_message_id")

        # A retry keeps the durable application ID but creates a new native
        # LXMF packet. Once that newer packet is registered, callbacks from an
        # older attempt must not queue or otherwise rewrite its state. A
        # progress callback may introduce a new native ID only while the
        # durable record is in a retryable state.
        if (
            native_id
            and current_native_id
            and native_id != current_native_id
            and not (
                current_state in DIRECT_RETRY_STATES
                and state.value in DIRECT_PROGRESS_RANK
            )
        ):
            return

        # Preserve the strongest evidence for the current native handoff.
        # Native failure can requeue SENDING, but it cannot retract proof that
        # a propagation node stored the packet or the endpoint received it.
        incoming_rank = DIRECT_PROGRESS_RANK.get(state.value)
        current_rank = DIRECT_PROGRESS_RANK.get(current_state)
        if (
            incoming_rank is not None
            and current_rank is not None
            and incoming_rank < current_rank
        ):
            return
        if state.value in DIRECT_RETRY_STATES and current_state in DIRECT_ENDPOINT_EVIDENCE:
            return
        message["state"] = state.value
        if native_id:
            message["native_message_id"] = native_id
        if cleanup_reaction_operation:
            self.store.delete("message", logical_id)
        else:
            self.store.put("message", logical_id, message)
        self.emit(
            {
                "type": "event",
                "event": "message_status",
                "message_id": logical_id,
                "state": state.value,
            }
        )

    def _on_inbound(self, native: LXMF.LXMessage) -> None:
        with self._dispatch_lock:
            self._on_inbound_locked(native)

    def _on_inbound_locked(self, native: LXMF.LXMessage) -> None:
        try:
            if is_workspace_payload(native):
                self._receive_workspace_payload(native, parse_workspace_payload(native))
                return
            app = parse_payload(native)
            source = native.source_hash.hex()
            contact = self._contact_by_destination(source)
            if app.kind == MessageKind.ROUTE_UPDATE:
                if app.route_update is None:
                    return
                update, _scope, _label = self._verified_scoped_route_update(
                    app.route_update
                )
                profile = self._require_profile()
                if (
                    update.issuer_destination != native.source_hash
                    or app.conversation_id != conversation_id(
                        bytes.fromhex(profile["destination_hash"]), native.source_hash
                    )
                ):
                    return
                self.apply_route_update(app.route_update)
                return
            if app.kind in GROUP_KINDS:
                self._receive_group_payload(native, app, contact)
                return
            if app.kind == MessageKind.CONTACT_REQUEST:
                self._receive_contact_request(native, app, contact)
                return
            if contact is None or contact["trust"] in {
                TrustState.BLOCKED.value,
                TrustState.IDENTITY_CHANGED.value,
            }:
                return
            profile = self._require_profile()
            expected_conversation = conversation_id(
                bytes.fromhex(profile["destination_hash"]), bytes.fromhex(source)
            )
            if app.conversation_id != expected_conversation:
                return
            if app.kind == MessageKind.CONTACT_ACCEPT:
                if contact["trust"] == TrustState.AWAITING_CONSENT.value:
                    contact["trust"] = TrustState.APPROVED.value
                    contact["updated_at"] = time.time()
                    self.store.put("contact", contact["id"], contact)
                    self._bind_callback_host(
                        "personal", source, scope_kind="contact", scope_id=contact["id"]
                    )
                    self._flush_contact(contact["id"])
                    self._changed()
                return
            if app.kind == MessageKind.CONTACT_DECLINE:
                if contact["trust"] == TrustState.AWAITING_CONSENT.value:
                    contact["trust"] = TrustState.BLOCKED.value
                    contact["updated_at"] = time.time()
                    self.store.put("contact", contact["id"], contact)
                    self._stop_pending_callback_for_peer("personal", source)
                    self._changed()
                return
            if app.kind == MessageKind.RECEIPT:
                self._receive_receipt(contact, app.receipt_for)
                return
            if contact["trust"] not in {
                TrustState.APPROVED.value,
                TrustState.VERIFIED.value,
            }:
                return
            if app.kind == MessageKind.REACTION:
                self._receive_direct_reaction(contact, native, app)
            elif app.kind == MessageKind.CHAT:
                self._receive_chat(contact, native, app)
        except Exception:
            # Malformed, unauthenticated, unknown and mismatched messages fail
            # closed without a reply that could be abused as an oracle.
            return

    def _receive_contact_request(
        self, native: LXMF.LXMessage, app: Any, existing: dict[str, Any] | None
    ) -> None:
        invitation = verify_invitation(app.invitation)
        if invitation.destination_hash != native.source_hash:
            return
        profile = self._require_profile()
        expected = conversation_id(
            bytes.fromhex(profile["destination_hash"]), invitation.destination_hash
        )
        if app.conversation_id != expected:
            return
        if existing and existing["trust"] == TrustState.BLOCKED.value:
            return
        if existing is None:
            now = time.time()
            rate_id = invitation.identity_hash.hex()
            rate = self.store.get("request_rate", rate_id) or {
                "window_started_at": now,
                "attempts": 0,
            }
            if now - float(rate["window_started_at"]) >= CONTACT_REQUEST_WINDOW_SECONDS:
                rate = {"window_started_at": now, "attempts": 0}
            if int(rate["attempts"]) >= CONTACT_REQUESTS_PER_IDENTITY:
                return
            if sum(
                contact["trust"] == TrustState.PENDING_REQUEST.value
                for contact in self.store.list("contact")
            ) >= MAX_PENDING_REQUESTS:
                return
            rate["attempts"] = int(rate["attempts"]) + 1
            self.store.put("request_rate", rate_id, rate)
            contact = Contact(
                id=_contact_id(invitation.destination_hash),
                display_name=invitation.display_name,
                public_identity=_b64(invitation.public_identity),
                identity_hash=invitation.identity_hash.hex(),
                destination_hash=invitation.destination_hash.hex(),
                fingerprint=invitation.fingerprint,
                trust=TrustState.PENDING_REQUEST,
                connection_hints=invitation.hints,
                created_at=now,
                updated_at=now,
            ).to_dict()
            contact["profile_name"] = invitation.display_name
            self.store.put("contact", contact["id"], contact)
            if self.network:
                self.network.remember_contact(invitation.public_identity, invitation.destination_hash)
        elif existing["public_identity"] != _b64(invitation.public_identity):
            existing["trust"] = TrustState.IDENTITY_CHANGED.value
            self.store.put("contact", existing["id"], existing)
            return
        received_contact = contact if existing is None else existing
        if received_contact["trust"] != TrustState.PENDING_REQUEST.value:
            self.promote_pending_callback(
                invitation.destination_hash.hex(),
                scope_kind="contact",
                scope_id=received_contact["id"],
                purpose="personal",
            )
        self._changed()

    def _receive_chat(self, contact: dict[str, Any], native: LXMF.LXMessage, app: Any) -> None:
        if self._message_was_discarded("direct", contact["id"], app.logical_id):
            self._ensure_receipt(contact, app.logical_id, app.conversation_id)
            return
        existing = self.store.get("message", app.logical_id)
        if existing:
            self._ensure_receipt(contact, app.logical_id, app.conversation_id)
            return
        inbound = Message(
            id=app.logical_id,
            conversation_id=app.conversation_id,
            contact_id=contact["id"],
            direction="inbound",
            kind=MessageKind.CHAT,
            text=app.text,
            state=DeliveryState.DELIVERED,
            created_at=float(native.timestamp or time.time()),
            expires_at=float(app.expires_at),
            native_message_id=native.hash.hex() if native.hash else None,
        ).to_dict()
        receipt = self._receipt_record(contact, app.logical_id, app.conversation_id)
        reaction_writes, reaction_deletions = self._pending_reaction_changes(
            "direct", contact["id"], inbound
        )
        # The visible message and its receipt job commit atomically.
        self.store.put_and_delete(
            [
                ("message", inbound["id"], inbound),
                ("message", receipt["id"], receipt),
                *self._personal_notification_records(
                    "direct", contact["id"], contact, inbound
                ),
                *reaction_writes,
            ],
            [
                (
                    "conversation_hidden",
                    self._conversation_marker_id("direct", contact["id"]),
                ),
                *reaction_deletions,
            ],
        )
        self._attempt(receipt["id"])
        self._changed()

    def _receipt_record(
        self, contact: dict[str, Any], received_id: str, conv_id: str
    ) -> dict[str, Any]:
        now = time.time()
        return Message(
            id=_new_id(),
            conversation_id=conv_id,
            contact_id=contact["id"],
            direction="outbound",
            kind=MessageKind.RECEIPT,
            text="",
            state=DeliveryState.QUEUED,
            created_at=now,
            expires_at=now + DELIVERY_WINDOW_SECONDS,
            receipt_for=received_id,
        ).to_dict()

    def _ensure_receipt(self, contact: dict[str, Any], received_id: str, conv_id: str) -> None:
        for message in self.store.list("message"):
            if message.get("kind") == MessageKind.RECEIPT.value and message.get(
                "receipt_for"
            ) == received_id:
                if message["state"] not in {
                    DeliveryState.DELIVERED.value,
                    DeliveryState.EXPIRED.value,
                }:
                    self._attempt(message["id"])
                return
        receipt = self._receipt_record(contact, received_id, conv_id)
        self.store.put("message", receipt["id"], receipt)
        self._attempt(receipt["id"])

    def _receive_receipt(self, contact: dict[str, Any], receipt_for: str | None) -> None:
        if receipt_for is None:
            return
        message = self.store.get("message", receipt_for)
        if (
            message is None
            or message["direction"] != "outbound"
            or message["contact_id"] != contact["id"]
            or message["kind"] == MessageKind.RECEIPT.value
        ):
            return
        if message.get("kind") == MessageKind.REACTION.value:
            self.store.delete("message", message["id"])
        else:
            message["state"] = DeliveryState.DELIVERED.value
            self.store.put("message", message["id"], message)
        self.emit(
            {
                "type": "event",
                "event": "message_status",
                "message_id": message["id"],
                "state": DeliveryState.DELIVERED.value,
            }
        )

    def _recover_outbox(self) -> None:
        now = time.time()
        for message in self.store.list("message"):
            if message["direction"] != "outbound":
                continue
            reaction_only = bool(
                message.get("kind") == MessageKind.REACTION.value
                or message.get("reaction_receipt") is True
            )
            if message["state"] == DeliveryState.DELIVERED.value:
                if reaction_only:
                    self.store.delete("message", message["id"])
                continue
            if (
                message["expires_at"] <= now
                and reaction_only
            ):
                self.store.delete("message", message["id"])
                continue
            message["state"] = (
                DeliveryState.EXPIRED.value
                if message["expires_at"] <= now
                else DeliveryState.QUEUED.value
            )
            self.store.put("message", message["id"], message)
        self._recover_group_outbox()

    def _retry_loop(self) -> None:
        while not self._shutdown.wait(3):
            if not self.network:
                continue
            # Do not own the command/callback lock for an entire durable
            # backlog. A signed-route probe has a small bounded wait of its own,
            # and multiplying that wait by many historical messages can exceed
            # the desktop IPC deadline even without a transport fault. Lock one
            # record at a time and yield between records so a waiting user
            # command or deferred native callback can make progress.
            for message in self.store.list("message"):
                if message["direction"] == "outbound" and message["state"] in {
                    DeliveryState.QUEUED.value,
                    DeliveryState.WAITING_FOR_KEYS.value,
                }:
                    with self._dispatch_lock:
                        try:
                            self._attempt(message["id"])
                        except Exception:
                            # A single upstream transport failure must not kill
                            # the only retry worker.
                            pass
                    if self._shutdown.wait(0.01):
                        return
            with self._dispatch_lock:
                try:
                    self._expire_group_invitation_state(time.time())
                except Exception:
                    pass
            for delivery in self.store.list("group_delivery"):
                with self._dispatch_lock:
                    try:
                        self._retry_group_delivery_if_due(delivery["id"])
                    except Exception:
                        pass
                if self._shutdown.wait(0.01):
                    return
            with self._dispatch_lock:
                try:
                    self._retry_workspace_outbox()
                except Exception:
                    pass
                try:
                    self.reconcile_remote_profiles()
                except Exception:
                    pass
                try:
                    self.reconcile_participant_access()
                except Exception:
                    pass
                try:
                    self._refresh_callback_routes()
                except Exception:
                    pass

    def _flush_contact(self, contact_id: str) -> None:
        attempted = 0
        for message in self.store.list("message"):
            if message["contact_id"] == contact_id and message["direction"] == "outbound":
                if message["state"] in DIRECT_RETRY_STATES:
                    if attempted >= CONTACT_FLUSH_ATTEMPTS:
                        continue
                    attempted += 1
                self._attempt(message["id"])

    def snapshot(self) -> dict[str, Any]:
        self._prune_discarded_messages()
        self._prune_pending_reactions()
        profile = self.store.get("profile", "local")
        # Snapshot annotations must not become part of the persisted contact
        # record.  In particular, request delivery is message state and can
        # continue changing while the contact remains awaiting consent.
        contacts = [dict(contact) for contact in self.store.list("contact")]
        all_messages = self.store.list("message")
        reaction_index = self._reaction_index()
        latest_requests: dict[str, dict[str, Any]] = {}
        for message in all_messages:
            if (
                message["direction"] != "outbound"
                or message["kind"] != MessageKind.CONTACT_REQUEST.value
            ):
                continue
            current = latest_requests.get(message["contact_id"])
            if current is None or float(message["created_at"]) > float(current["created_at"]):
                latest_requests[message["contact_id"]] = message
        for contact in contacts:
            if self.network is not None:
                try:
                    contact["route_kind"] = self.network.route_kind(
                        bytes.fromhex(contact["destination_hash"])
                    )
                except Exception:
                    contact["route_kind"] = "unavailable"
            if contact.get("trust") in {
                TrustState.APPROVED.value, TrustState.VERIFIED.value
            } and contact.get("route_kind") == "unavailable":
                has_stored_route = any(
                    {"kind": "contact", "id": contact["id"]}
                    in record.get("scopes", [])
                    for record in self._participant_access_records()
                )
                contact["route_status"] = (
                    "reconnecting_automatically"
                    if has_stored_route
                    else "reconnect_update_required"
                )
            if contact["trust"] != TrustState.AWAITING_CONSENT.value:
                continue
            request = latest_requests.get(contact["id"])
            if request is not None:
                contact["request_state"] = request["state"]
        visible_messages = [
            self._public_direct_message(message, reaction_index)
            for message in all_messages
            if message["kind"] == MessageKind.CHAT.value
        ]
        visible_messages.sort(key=lambda item: item["created_at"])
        snapshot = {
            "profile": profile,
            "contacts": contacts,
            "messages": visible_messages,
            "drafts": self.store.list("draft"),
            "hidden_conversations": [
                {
                    "kind": marker["kind"],
                    "id": marker["target_id"],
                }
                for marker in self.store.list("conversation_hidden")
            ],
            "settings": self._public_network_settings(),
            "remote_profiles": [
                sanitized_profile(record) for record in self._remote_profiles()
            ],
            "participant_hosting": self.participant_hosting_snapshot(),
            "participant_connections": self.participant_connection_snapshot(),
            "network": self.network.snapshot() if self.network else None,
            "service_error": (
                self._network_error
                or (
                    "network_interface_unavailable"
                    if self.network is not None and not self.network.interface_available
                    else None
                )
            ),
        }
        snapshot.update(self.group_snapshot(reaction_index))
        snapshot.update(self.workspace_snapshot())
        return snapshot

    def connection_help(self, contact_id: str) -> dict[str, Any]:
        contact = self._require_contact(contact_id)
        if self.network is None or not self.network.interface_available:
            return {"code": "service_unavailable", "action": "restart_app"}
        destination = bytes.fromhex(contact["destination_hash"])
        if not self.network.recipient_ready(destination):
            self.network.request_path(destination)
            return {"code": "waiting_for_keys", "action": "ask_contact_to_open_app"}
        if not self.network.path_known(destination):
            return {"code": "no_route", "action": "check_network_or_fresh_invite"}
        return {"code": "connecting", "action": None}

    def search(self, query: str) -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 200:
            raise ValidationError("Search query is invalid")
        needle = query.casefold().strip()
        if not needle:
            return []
        direct_results = [
            message
            for message in self.snapshot()["messages"]
            if needle in message["text"].casefold()
        ]
        group_results = [
            message
            for message in self.snapshot()["group_messages"]
            if needle in message["text"].casefold()
        ]
        return sorted(
            [*direct_results, *group_results], key=lambda item: item["created_at"]
        )[-100:]

    def update_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        settings = NetworkSettings.from_dict(value)
        # The renderer controls user-facing role toggles only. Native listener
        # addresses, direct peers, remote profiles and propagation allowlists
        # remain service-owned and cannot be injected through update_settings.
        settings.lan_listener_port = self.settings.lan_listener_port
        settings.tcp_clients = [dict(item) for item in self.settings.tcp_clients]
        settings.tcp_listener = (
            dict(self.settings.tcp_listener) if self.settings.tcp_listener else None
        )
        settings.approved_propagation_nodes = list(
            self.settings.approved_propagation_nodes
        )
        settings.remote_tcp_clients = [
            dict(item) for item in self.settings.remote_tcp_clients
        ]
        settings.participant_listeners = [
            dict(item) for item in self.settings.participant_listeners
        ]
        settings.participant_clients = [
            dict(item) for item in self.settings.participant_clients
        ]
        self.settings = settings
        self._prepare_lan_fallback()
        self.store.put("settings", "network", self.settings.to_dict())
        self._changed()
        return {"settings": self.settings.to_dict(), "restart_required": True}

    def _public_network_settings(self) -> dict[str, Any]:
        value = self.settings.to_dict()
        value.update(
            {
                "lan_listener_port": None,
                "tcp_clients": [],
                "tcp_listener": None,
                "approved_propagation_nodes": [],
                "remote_tcp_clients": [],
                "participant_listeners": [],
                "participant_clients": [],
            }
        )
        return value

    def dispatch(self, request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._dispatch_lock:
            if request.get("v") != 1:
                raise ValidationError("IPC version mismatch")
            command_id = request.get("id")
            command = request.get("command")
            if (
                not isinstance(command_id, str)
                or not 1 <= len(command_id) <= 80
                or not isinstance(command, str)
                or command not in self.COMMANDS
            ):
                raise ValidationError("Command envelope is invalid")
            cache_response = command not in self.UNCACHED_COMMANDS
            if cache_response:
                cached = self.store.command_response(command_id)
                if cached is not None:
                    return cached, command == "shutdown"
            data = self._execute(command, request.get("payload", {}))
            response = {"ok": True, "result": data}
            if cache_response:
                self.store.remember_command(command_id, response)
            return response, command == "shutdown"

    def _execute(self, command: str, value: Any) -> Any:
        if command in {"connection_diagnostics", "clear_connection_diagnostics"}:
            _payload(value, allowed=set())
            from .connection_diagnostics import report
            if command == "clear_connection_diagnostics":
                self.store.delete("connection_diagnostics", "history")
            return report(self)
        recovery_commands = {
            "direct_recovery_status": ("status",set()),
            "export_recovery_update": ("export",{"identifier"}),
            "import_recovery_update": ("receive",{"document","workspace_id"}),
            "pause_direct_recovery": ("pause",{"identifier"}),
            "resume_direct_recovery": ("resume",{"identifier"}),
        }
        if command in recovery_commands:
            method, fields = recovery_commands[command]
            body = _payload(value,allowed=fields,required=fields)
            return getattr(self._direct_recovery,method)(**body)
        direct_commands = {
            "preview_direct_connection": ("preview", {"document"}, {"document"}),
            "prepare_direct_offer": ("offer", {"invitation_id","manual_host","manual_port"}, {"invitation_id"}),
            "prepare_direct_answer": ("answer", {"document","operation_id","manual_host","manual_port"}, {"document","operation_id"}),
            "prepare_direct_ready": ("ready", {"document"}, {"document"}),
            "accept_direct_ready": ("accept_ready", {"document"}, {"document"}),
            "connect_direct_setup": ("connect", {"setup_id","document"}, {"setup_id","document"}),
            "configure_direct_firewall": ("configure_firewall", {"setup_id"}, {"setup_id"}),
            "direct_setup_status": ("status", {"setup_id"}, {"setup_id"}),
            "check_direct_setup": ("readiness", {"setup_id"}, {"setup_id"}),
            "retry_direct_setup": ("retry", {"setup_id"}, {"setup_id"}),
            "cancel_direct_setup": ("cancel", {"setup_id"}, {"setup_id"}),
            "resume_direct_setup": ("resume", {"workspace_id","invitation_id"}, set()),
        }
        if command in direct_commands:
            method, fields, required = direct_commands[command]
            body = _payload(value, allowed=fields, required=required)
            from .connection_diagnostics import record
            try:
                result = getattr(self._direct_setup, method)(**body)
            except Exception as exc:
                record(self, "import_rejected" if method == "preview" else "action_failed", {
                    "state":"failed", "command":command,
                    "error_code":exc.code if isinstance(exc, MeshChatError) else "internal_error",
                    "failure_stage":getattr(exc, "direct_setup_failure_stage", None),
                    "failure_reason":getattr(exc, "reason", None),
                    "workspace_state":getattr(exc, "direct_setup_workspace_state", None),
                    "setup_id":body.get("setup_id"),
                })
                raise
            if method == "readiness":
                record(self, "state", {**result, "state":result["readiness"]})
            if method == "preview":
                existing = result.get("existing_workspace") or {}
                record(self, "import_verified", {"state":"verified", "kind":result.get("kind"),
                    "workspace_state":existing.get("state", "none")})
            return result
        if command == "snapshot":
            _payload(value, allowed=set())
            return self.snapshot()
        if command == "workspace_snapshot":
            _payload(value, allowed=set())
            return self.workspace_snapshot()
        if command == "create_profile":
            body = _payload(value, allowed={"display_name"}, required={"display_name"})
            return self.create_profile(body["display_name"])
        if command == "create_invitation":
            body = _payload(
                value, allowed={
                    "remote_profile_id", "connection_mode", "manual_setup_id",
                    "external_host", "external_port",
                }
            )
            return self.invitation(
                body.get("remote_profile_id"), body.get("connection_mode"),
                body.get("manual_setup_id"), body.get("external_host"),
                body.get("external_port"),
            )
        if command in {"preview_invitation", "accept_invitation"}:
            body = _payload(value, allowed={"invitation"}, required={"invitation"})
            if not isinstance(body["invitation"], str):
                raise ValidationError("Invitation must be text")
            return (
                self.preview_invitation(body["invitation"])
                if command == "preview_invitation"
                else self.accept_invitation(body["invitation"])
            )
        if command == "create_connection_reply":
            body = _payload(
                value,
                allowed={"invitation", "purpose"},
                required={"invitation", "purpose"},
            )
            return self.create_connection_reply(body["invitation"], body["purpose"])
        if command in {"preview_connection_reply", "connect_using_reply"}:
            body = _payload(value, allowed={"response"}, required={"response"})
            return (
                self.preview_connection_reply(body["response"])
                if command == "preview_connection_reply"
                else self.connect_using_reply(body["response"])
            )
        if command == "create_route_update":
            body = _payload(
                value,
                allowed={"scope_kind", "scope_id", "peer_destination"},
                required={"scope_kind", "scope_id"},
            )
            return self.create_route_update_command(
                body["scope_kind"], body["scope_id"], body.get("peer_destination")
            )
        if command in {"preview_route_update", "apply_route_update"}:
            body = _payload(value, allowed={"update"}, required={"update"})
            return (
                self.preview_route_update(body["update"])
                if command == "preview_route_update"
                else self.apply_route_update(body["update"])
            )
        if command == "preview_remote_profile":
            body = _payload(
                value,
                allowed={"profile", "allow_private"},
                required={"profile"},
            )
            return self.preview_remote_profile(
                body["profile"], body.get("allow_private", False)
            )
        if command == "create_manual_remote_profile":
            body = _payload(
                value,
                allowed={"label", "endpoints", "propagation_node", "allow_private"},
                required={"label", "endpoints"},
            )
            return self.create_manual_remote_profile(
                body["label"], body["endpoints"], body.get("propagation_node"),
                body.get("allow_private", False),
            )
        if command == "approve_remote_profile":
            body = _payload(
                value,
                allowed={"profile", "origin", "scope_kind", "scope_id", "allow_private"},
                required={"profile", "origin", "scope_kind", "scope_id"},
            )
            return self.approve_remote_profile(
                body["profile"], origin=body["origin"],
                scope_kind=body["scope_kind"], scope_id=body["scope_id"],
                allow_private=body.get("allow_private", False),
            )
        if command == "list_remote_profiles":
            _payload(value, allowed=set())
            return self.list_remote_profiles()
        if command in {"test_remote_profile", "retry_remote_profile", "remove_remote_profile", "approve_remote_propagation", "remove_remote_propagation"}:
            body = _payload(value, allowed={"profile_id"}, required={"profile_id"})
            method = {
                "test_remote_profile": self.test_remote_profile,
                "retry_remote_profile": self.retry_remote_profile,
                "remove_remote_profile": self.remove_remote_profile,
                "approve_remote_propagation": self.approve_remote_propagation,
                "remove_remote_propagation": self.remove_remote_propagation,
            }[command]
            return method(body["profile_id"])
        if command == "stop_participant_host":
            body = _payload(value, allowed={"access_id"}, required={"access_id"})
            outcome = self.stop_participant_host(body["access_id"])
            self._changed()
            return outcome
        if command == "check_direct_connection":
            _payload(value, allowed=set())
            return self.check_direct_connection()
        if command == "prepare_manual_participant_host":
            body = _payload(value, allowed={"purpose"}, required={"purpose"})
            return self.prepare_manual_participant_host(body["purpose"])
        if command == "configure_participant_firewall":
            body = _payload(value, allowed={"access_id"}, required={"access_id"})
            return self.configure_participant_firewall(body["access_id"])
        if command in {
            "approve_request",
            "decline_request",
            "verify_contact",
            "unverify_contact",
            "block_contact",
            "unblock_contact",
            "connection_help",
        }:
            body = _payload(value, allowed={"contact_id"}, required={"contact_id"})
            contact_id = body["contact_id"]
            if not isinstance(contact_id, str):
                raise ValidationError("Contact ID is invalid")
            if command == "approve_request":
                return self.approve_request(contact_id)
            if command == "decline_request":
                return self.decline_request(contact_id)
            if command == "connection_help":
                return self.connection_help(contact_id)
            if command == "verify_contact":
                return self.verify_contact(contact_id)
            if command == "unverify_contact":
                return self.unverify_contact(contact_id)
            if command == "unblock_contact":
                return self.unblock_contact(contact_id)
            return self.block_contact(contact_id)
        if command in {"update_contact", "rename_contact"}:
            body = _payload(
                value,
                allowed={"contact_id", "display_name"},
                required={"contact_id", "display_name"},
            )
            return self.update_contact(body["contact_id"], body["display_name"])
        if command == "delete_contact":
            body = _payload(value, allowed={"contact_id"}, required={"contact_id"})
            return self.delete_contact(body["contact_id"])
        if command == "send_message":
            body = _payload(
                value, allowed={"contact_id", "text"}, required={"contact_id", "text"}
            )
            return self.send_message(body["contact_id"], body["text"])
        if command == "set_message_reaction":
            body = _payload(
                value,
                allowed={"kind", "message_id", "emoji", "active"},
                required={"kind", "message_id", "emoji", "active"},
            )
            return self.set_message_reaction(
                body["kind"], body["message_id"], body["emoji"], body["active"]
            )
        if command in {"delete_conversation", "restore_conversation"}:
            body = _payload(
                value, allowed={"kind", "id"}, required={"kind", "id"}
            )
            return (
                self.delete_conversation(body["kind"], body["id"])
                if command == "delete_conversation"
                else self.restore_conversation(body["kind"], body["id"])
            )
        if command == "create_group":
            body = _payload(
                value,
                allowed={"title", "member_ids", "posting_policy"},
                required={"title", "member_ids", "posting_policy"},
            )
            return self.create_group(
                body["title"], body["member_ids"], body["posting_policy"]
            )
        if command == "send_group_message":
            body = _payload(
                value, allowed={"group_id", "text"}, required={"group_id", "text"}
            )
            return self.send_group_message(body["group_id"], body["text"])
        if command == "save_group_draft":
            body = _payload(
                value, allowed={"group_id", "text"}, required={"group_id", "text"}
            )
            return self.save_group_draft(body["group_id"], body["text"])
        if command in {"accept_group_invitation", "decline_group_invitation"}:
            body = _payload(
                value,
                allowed={"invitation_id"},
                required={"invitation_id"},
            )
            if not isinstance(body["invitation_id"], str):
                raise ValidationError("Group invitation ID is invalid")
            return (
                self.accept_group_invitation(body["invitation_id"])
                if command == "accept_group_invitation"
                else self.decline_group_invitation(body["invitation_id"])
            )
        if command == "retry_group_invitation":
            body = _payload(
                value,
                allowed={"group_id", "destination_hash"},
                required={"group_id", "destination_hash"},
            )
            return self.retry_group_invitation(
                body["group_id"], body["destination_hash"]
            )
        if command == "remove_group_member":
            body = _payload(
                value,
                allowed={"group_id", "destination_hash"},
                required={"group_id", "destination_hash"},
            )
            return self.remove_group_member(
                body["group_id"], body["destination_hash"]
            )
        if command in {"leave_group", "close_group"}:
            body = _payload(value, allowed={"group_id"}, required={"group_id"})
            return (
                self.leave_group(body["group_id"])
                if command == "leave_group"
                else self.close_group(body["group_id"])
            )
        if command == "create_workspace":
            body = _payload(
                value,
                allowed={"operation_id", "name", "description"},
                required={"operation_id", "name"},
            )
            return self.create_workspace(
                body["operation_id"], body["name"], body.get("description", "")
            )
        if command == "create_workspace_invitation":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "lifetime_days",
                    "remote_profile_id",
                    "connection_mode",
                    "manual_setup_id",
                    "external_host",
                    "external_port",
                },
                required={"operation_id", "workspace_id"},
            )
            return self.create_workspace_invitation_command(
                body["workspace_id"],
                body["operation_id"],
                body.get("lifetime_days", 7),
                body.get("remote_profile_id"),
                body.get("connection_mode"),
                body.get("manual_setup_id"),
                body.get("external_host"),
                body.get("external_port"),
            )
        if command == "preview_workspace_invitation":
            body = _payload(
                value, allowed={"invitation"}, required={"invitation"}
            )
            return self.preview_workspace_invitation(body["invitation"])
        if command == "revoke_workspace_invitation":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "invitation_id"},
                required={"operation_id", "workspace_id", "invitation_id"},
            )
            return self.revoke_workspace_invitation(
                body["workspace_id"], body["invitation_id"], body["operation_id"]
            )
        if command == "submit_workspace_join":
            body = _payload(
                value,
                allowed={"operation_id", "invitation"},
                required={"operation_id", "invitation"},
            )
            return self.submit_workspace_join(
                body["invitation"], body["operation_id"]
            )
        if command in {"approve_workspace_join", "decline_workspace_join"}:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "request_id"},
                required={"operation_id", "workspace_id", "request_id"},
            )
            return (
                self.approve_workspace_join(
                    body["workspace_id"], body["request_id"], body["operation_id"]
                )
                if command == "approve_workspace_join"
                else self.decline_workspace_join(
                    body["workspace_id"], body["request_id"], body["operation_id"]
                )
            )
        if command == "create_workspace_device_link":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id"},
                required={"operation_id", "workspace_id"},
            )
            return self.create_workspace_device_link(
                body["workspace_id"], body["operation_id"]
            )
        if command == "preview_workspace_device_link":
            body = _payload(
                value, allowed={"device_link"}, required={"device_link"}
            )
            return self.preview_workspace_device_link(body["device_link"])
        if command == "submit_workspace_device_link":
            body = _payload(
                value,
                allowed={"operation_id", "device_link"},
                required={"operation_id", "device_link"},
            )
            return self.submit_workspace_device_link(
                body["device_link"], body["operation_id"]
            )
        if command in {
            "approve_workspace_device_link",
            "decline_workspace_device_link",
        }:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "link_id"},
                required={"operation_id", "workspace_id", "link_id"},
            )
            method = (
                self.approve_workspace_device_link
                if command == "approve_workspace_device_link"
                else self.decline_workspace_device_link
            )
            return method(
                body["workspace_id"], body["link_id"], body["operation_id"]
            )
        if command == "request_workspace_device_removal":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "target_device_id"},
                required={"operation_id", "workspace_id", "target_device_id"},
            )
            return self.request_workspace_device_removal(
                body["workspace_id"],
                body["target_device_id"],
                body["operation_id"],
            )
        if command in {
            "approve_workspace_device_removal",
            "decline_workspace_device_removal",
        }:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "removal_id"},
                required={"operation_id", "workspace_id", "removal_id"},
            )
            method = (
                self.approve_workspace_device_removal
                if command == "approve_workspace_device_removal"
                else self.decline_workspace_device_removal
            )
            return method(
                body["workspace_id"], body["removal_id"], body["operation_id"]
            )
        if command == "update_workspace_metadata":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "name", "description"},
                required={
                    "operation_id",
                    "workspace_id",
                    "name",
                    "description",
                },
            )
            return self.update_workspace_metadata(
                body["workspace_id"],
                body["name"],
                body["description"],
                body["operation_id"],
            )
        if command == "update_workspace_policies":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "channel_creation",
                    "posting",
                    "invitation_requests",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "channel_creation",
                    "posting",
                },
            )
            return self.update_workspace_policies(
                body["workspace_id"],
                body["channel_creation"],
                body["posting"],
                body["operation_id"],
                body.get("invitation_requests"),
            )
        if command == "update_workspace_retention":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "retention_days"},
                required={"operation_id", "workspace_id", "retention_days"},
            )
            return self.update_workspace_retention(
                body["workspace_id"],
                body["retention_days"],
                body["operation_id"],
            )
        if command == "prune_workspace_history":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "max_events"},
                required={"operation_id", "workspace_id"},
            )
            return self.prune_workspace_history(
                body["workspace_id"],
                body["operation_id"],
                body.get("max_events", 500),
            )
        if command == "remove_workspace_member":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "member_id"},
                required={"operation_id", "workspace_id", "member_id"},
            )
            return self.remove_workspace_member(
                body["workspace_id"], body["member_id"], body["operation_id"]
            )
        if command == "change_workspace_role":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "member_id", "role"},
                required={"operation_id", "workspace_id", "member_id", "role"},
            )
            return self.change_workspace_role(
                body["workspace_id"], body["member_id"], body["role"],
                body["operation_id"],
            )
        if command in {
            "submit_workspace_admin_request",
            "submit_workspace_invitation_request",
            "submit_workspace_member_removal_request",
            "submit_workspace_role_change_request",
        }:
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "request_kind",
                    "target_member_id", "requested_role", "note",
                },
                required={"operation_id", "workspace_id"},
            )
            fixed_kind = {
                "submit_workspace_invitation_request": "invitation",
                "submit_workspace_member_removal_request": "member_removal",
                "submit_workspace_role_change_request": "role_change",
            }.get(command)
            request_kind = fixed_kind or body.get("request_kind")
            if request_kind is None:
                raise ValidationError("Administrative request kind is required")
            return self.submit_workspace_admin_request(
                body["workspace_id"], request_kind, body["operation_id"],
                body.get("target_member_id"), body.get("requested_role"),
                body.get("note", ""),
            )
        if command == "list_workspace_members":
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            workspace = self._require_workspace(body["workspace_id"])
            return {"members": self._public_workspace(workspace)["members"]}
        if command in {"list_workspace_admin_requests", "list_workspace_admin_history"}:
            body = _payload(
                value,
                allowed={"workspace_id", "direction", "cursor", "limit"},
                required={"workspace_id"},
            )
            direction = (
                "history"
                if command == "list_workspace_admin_history"
                else body.get("direction", "outgoing")
            )
            return self.list_workspace_admin_requests(
                body["workspace_id"], direction, body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "get_workspace_admin_request":
            body = _payload(
                value,
                allowed={"workspace_id", "request_id"},
                required={"workspace_id", "request_id"},
            )
            return self.get_workspace_admin_request(
                body["workspace_id"], body["request_id"]
            )
        if command in {"approve_workspace_admin_request", "decline_workspace_admin_request"}:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "request_id"},
                required={"operation_id", "workspace_id", "request_id"},
            )
            return self.decide_workspace_admin_request(
                body["workspace_id"], body["request_id"],
                command == "approve_workspace_admin_request",
                body["operation_id"],
            )
        if command in {"cancel_workspace_admin_request", "dismiss_workspace_admin_request"}:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "request_id"},
                required={"operation_id", "workspace_id", "request_id"},
            )
            method = (
                self.cancel_workspace_admin_request
                if command == "cancel_workspace_admin_request"
                else self.dismiss_workspace_admin_request
            )
            return method(
                body["workspace_id"], body["request_id"], body["operation_id"]
            )
        if command == "offer_workspace_authority_transition":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "transition_kind",
                    "successor_member_id", "successor_device_id",
                    "outgoing_owner_role",
                },
                required={
                    "operation_id", "workspace_id", "transition_kind",
                    "successor_member_id", "successor_device_id",
                },
            )
            return self.offer_workspace_authority_transition(
                body["workspace_id"],
                body["transition_kind"],
                body["successor_member_id"],
                body["successor_device_id"],
                body.get("outgoing_owner_role"),
                body["operation_id"],
            )
        if command in {
            "accept_workspace_authority_transition",
            "finalize_workspace_authority_transition",
        }:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "transition_id"},
                required={"operation_id", "workspace_id", "transition_id"},
            )
            method = (
                self.accept_workspace_authority_transition
                if command == "accept_workspace_authority_transition"
                else self.finalize_workspace_authority_transition
            )
            return method(
                body["workspace_id"], body["transition_id"], body["operation_id"]
            )
        if command == "list_workspace_authority_transitions":
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            return self.list_workspace_authority_transitions(body["workspace_id"])
        if command == "report_workspace_authority_loss":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id"},
                required={"operation_id", "workspace_id"},
            )
            return self.report_workspace_authority_loss(
                body["workspace_id"], body["operation_id"]
            )
        if command == "request_workspace_display_name":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "display_name"},
                required={"operation_id", "workspace_id", "display_name"},
            )
            return self.request_workspace_display_name(
                body["workspace_id"],
                body["display_name"],
                body["operation_id"],
            )
        if command == "decide_workspace_display_name":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "request_id",
                    "approve",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "request_id",
                    "approve",
                },
            )
            return self.decide_workspace_display_name(
                body["workspace_id"],
                body["request_id"],
                body["approve"],
                body["operation_id"],
            )
        if command == "create_workspace_channel":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "name",
                    "topic",
                    "visibility",
                    "member_ids",
                },
                required={"operation_id", "workspace_id", "name", "topic"},
            )
            return self.create_workspace_channel(
                body["workspace_id"],
                body["name"],
                body["topic"],
                body["operation_id"],
                body.get("visibility", "public"),
                body.get("member_ids"),
            )
        if command == "update_workspace_channel":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "name",
                    "topic",
                    "archived",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "name",
                    "topic",
                    "archived",
                },
            )
            return self.update_workspace_channel(
                body["workspace_id"],
                body["channel_id"],
                body["name"],
                body["topic"],
                body["archived"],
                body["operation_id"],
            )
        if command == "update_workspace_private_channel_members":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "channel_id", "member_ids"},
                required={"operation_id", "workspace_id", "channel_id", "member_ids"},
            )
            return self.update_workspace_private_channel_members(
                body["workspace_id"],
                body["channel_id"],
                body["member_ids"],
                body["operation_id"],
            )
        if command == "leave_workspace_private_channel":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "channel_id"},
                required={"operation_id", "workspace_id", "channel_id"},
            )
            return self.leave_workspace_private_channel(
                body["workspace_id"],
                body["channel_id"],
                body["operation_id"],
            )
        if command == "set_workspace_channel_subscription":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "subscribed",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "subscribed",
                },
            )
            return self.set_workspace_channel_subscription(
                body["workspace_id"],
                body["channel_id"],
                body["subscribed"],
                body["operation_id"],
            )
        if command == "offer_workspace_channel_transfer":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "successor_member_id",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "successor_member_id",
                },
            )
            return self.offer_workspace_channel_transfer(
                body["workspace_id"],
                body["channel_id"],
                body["successor_member_id"],
                body["operation_id"],
            )
        if command == "accept_workspace_channel_transfer":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "transfer_id"},
                required={"operation_id", "workspace_id", "transfer_id"},
            )
            return self.accept_workspace_channel_transfer(
                body["workspace_id"],
                body["transfer_id"],
                body["operation_id"],
            )
        if command == "recover_workspace_channel":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "channel_id"},
                required={"operation_id", "workspace_id", "channel_id"},
            )
            return self.recover_workspace_channel(
                body["workspace_id"], body["channel_id"], body["operation_id"]
            )
        if command == "sync_workspace_channels":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id"},
                required={"operation_id", "workspace_id"},
            )
            return self.sync_workspace_channels(
                body["workspace_id"], body["operation_id"]
            )
        if command == "send_workspace_message":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "event_id",
                    "text",
                    "mention_member_ids",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "channel_id",
                    "event_id",
                    "text",
                },
            )
            return self.send_workspace_message(
                body["workspace_id"],
                body["channel_id"],
                body["text"],
                body["event_id"],
                body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command == "open_workspace_direct":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "member_id"},
                required={"operation_id", "workspace_id", "member_id"},
            )
            return self.open_workspace_direct(
                body["workspace_id"], body["member_id"], body["operation_id"]
            )
        if command == "hide_workspace_direct":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "conversation_id"},
                required={"operation_id", "workspace_id", "conversation_id"},
            )
            return self.hide_workspace_direct(
                body["workspace_id"],
                body["conversation_id"],
                body["operation_id"],
            )
        if command == "send_workspace_direct_message":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "event_id",
                    "text",
                    "mention_member_ids",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "event_id",
                    "text",
                },
            )
            return self.send_workspace_direct_message(
                body["workspace_id"],
                body["conversation_id"],
                body["text"],
                body["event_id"],
                body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command == "send_workspace_thread_reply":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "conversation_id",
                    "thread_root_id", "event_id", "text", "mention_member_ids",
                },
                required={
                    "operation_id", "workspace_id", "conversation_id",
                    "thread_root_id", "event_id", "text",
                },
            )
            return self.send_workspace_thread_reply(
                body["workspace_id"],
                body["conversation_id"],
                body["thread_root_id"],
                body["text"],
                body["event_id"],
                body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command == "edit_workspace_message":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id", "text", "mention_member_ids",
                },
                required={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id", "text",
                },
            )
            return self.edit_workspace_message(
                body["workspace_id"], body["event_id"], body["text"],
                body["mutation_event_id"], body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command == "delete_workspace_message":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id",
                },
                required={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id",
                },
            )
            return self.delete_workspace_message(
                body["workspace_id"], body["event_id"],
                body["mutation_event_id"], body["operation_id"],
            )
        if command == "set_workspace_reaction":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id", "emoji", "active",
                },
                required={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id", "emoji", "active",
                },
            )
            return self.set_workspace_reaction(
                body["workspace_id"], body["event_id"], body["emoji"],
                body["active"], body["mutation_event_id"], body["operation_id"],
            )
        if command == "list_workspace_messages":
            body = _payload(
                value,
                allowed={"workspace_id", "channel_id", "cursor", "limit"},
                required={"workspace_id", "channel_id"},
            )
            return self.list_workspace_messages(
                body["workspace_id"],
                body["channel_id"],
                body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "get_workspace_history_status":
            body = _payload(
                value,
                allowed={"workspace_id", "conversation_id"},
                required={"workspace_id", "conversation_id"},
            )
            return self.get_workspace_history_status(
                body["workspace_id"], body["conversation_id"]
            )
        if command == "start_workspace_history":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "conversation_id"},
                required={"operation_id", "workspace_id", "conversation_id"},
            )
            return self.start_workspace_history(
                body["workspace_id"], body["conversation_id"], body["operation_id"]
            )
        if command == "cancel_workspace_history":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "conversation_id"},
                required={"operation_id", "workspace_id", "conversation_id"},
            )
            return self.cancel_workspace_history(
                body["workspace_id"], body["conversation_id"], body["operation_id"]
            )
        if command == "list_workspace_history_gaps":
            body = _payload(
                value,
                allowed={"workspace_id", "conversation_id", "cursor", "limit"},
                required={"workspace_id", "conversation_id"},
            )
            return self.list_workspace_history_gaps(
                body["workspace_id"], body["conversation_id"],
                body.get("cursor"), body.get("limit", 32),
            )
        if command == "search_workspace":
            body = _payload(
                value,
                allowed={"workspace_id", "query", "scope", "cursor", "limit"},
                required={"workspace_id", "query"},
            )
            return self.search_workspace(
                body["workspace_id"],
                body["query"],
                body.get("scope", "all"),
                body.get("cursor"),
                body.get("limit", 25),
            )
        if command == "list_workspace_direct_messages":
            body = _payload(
                value,
                allowed={"workspace_id", "conversation_id", "cursor", "limit"},
                required={"workspace_id", "conversation_id"},
            )
            return self.list_workspace_messages(
                body["workspace_id"],
                body["conversation_id"],
                body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "set_workspace_read_hint_sync":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "enabled"},
                required={"operation_id", "workspace_id", "enabled"},
            )
            return self.set_workspace_read_hint_sync(
                body["workspace_id"], body["enabled"], body["operation_id"]
            )
        if command == "mark_workspace_read":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "channel_id", "high_water"},
                required={"operation_id", "workspace_id", "channel_id", "high_water"},
            )
            return self.mark_workspace_read(
                body["workspace_id"],
                body["channel_id"],
                body["high_water"],
                body["operation_id"],
            )
        if command == "mark_workspace_direct_read":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "high_water",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "high_water",
                },
            )
            return self.mark_workspace_read(
                body["workspace_id"],
                body["conversation_id"],
                body["high_water"],
                body["operation_id"],
            )
        if command == "list_workspace_mentions":
            body = _payload(
                value,
                allowed={"workspace_id", "cursor", "limit"},
                required={"workspace_id"},
            )
            return self.list_workspace_mentions(
                body["workspace_id"],
                body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "list_workspace_threads":
            body = _payload(
                value,
                allowed={"workspace_id", "cursor", "limit"},
                required={"workspace_id"},
            )
            return self.list_workspace_threads(
                body["workspace_id"], body.get("cursor"), body.get("limit", 50)
            )
        if command == "list_workspace_thread_messages":
            body = _payload(
                value,
                allowed={"workspace_id", "thread_root_id", "cursor", "limit"},
                required={"workspace_id", "thread_root_id"},
            )
            return self.list_workspace_thread_messages(
                body["workspace_id"],
                body["thread_root_id"],
                body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "list_workspace_message_revisions":
            body = _payload(
                value,
                allowed={"workspace_id", "event_id", "cursor", "limit"},
                required={"workspace_id", "event_id"},
            )
            return self.list_workspace_message_revisions(
                body["workspace_id"],
                body["event_id"],
                body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "list_workspace_tombstones":
            body = _payload(
                value,
                allowed={"workspace_id", "conversation_id", "cursor", "limit"},
                required={"workspace_id", "conversation_id"},
            )
            return self.list_workspace_tombstones(
                body["workspace_id"],
                body["conversation_id"],
                body.get("cursor"),
                body.get("limit", 50),
            )
        if command == "mark_workspace_mentions_read":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "high_water"},
                required={"operation_id", "workspace_id", "high_water"},
            )
            return self.mark_workspace_mentions_read(
                body["workspace_id"],
                body["high_water"],
                body["operation_id"],
            )
        if command == "mark_workspace_thread_read":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "thread_root_id", "high_water"},
                required={"operation_id", "workspace_id", "thread_root_id", "high_water"},
            )
            return self.mark_workspace_thread_read(
                body["workspace_id"],
                body["thread_root_id"],
                body["high_water"],
                body["operation_id"],
            )
        if command == "set_workspace_channel_mentions_muted":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "channel_id", "muted"},
                required={"operation_id", "workspace_id", "channel_id", "muted"},
            )
            return self.set_workspace_channel_mentions_muted(
                body["workspace_id"],
                body["channel_id"],
                body["muted"],
                body["operation_id"],
            )
        if command == "get_notification_state":
            _payload(value, allowed=set())
            return self.notification_state()
        if command == "set_hide_notification_previews":
            body = _payload(
                value,
                allowed={"operation_id", "hidden"},
                required={"operation_id", "hidden"},
            )
            return self.set_hide_notification_previews(
                body["hidden"], body["operation_id"]
            )
        if command == "set_workspace_notification_preference":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "mode",
                },
                required={"operation_id", "workspace_id", "mode"},
            )
            return self.set_workspace_notification_preference(
                body["workspace_id"],
                body.get("conversation_id"),
                body["mode"],
                body["operation_id"],
            )
        if command == "open_notification_target":
            body = _payload(
                value,
                allowed={"notification_id"},
                required={"notification_id"},
            )
            return self.open_notification_target(body["notification_id"])
        if command == "reconcile_mobile_lifecycle":
            _payload(value, allowed=set())
            return self.mobile_lifecycle_transition(
                "foreground", "renderer_recovery"
            )
        if command == "native_notification_state":
            body = _payload(
                value,
                allowed={"platform", "supported", "permission_state"},
                required={"platform", "supported", "permission_state"},
            )
            return self.set_native_notification_state(
                body["platform"], body["supported"], body["permission_state"]
            )
        if command == "mobile_lifecycle_transition":
            body = _payload(
                value,
                allowed={"state", "reason"},
                required={"state"},
            )
            return self.mobile_lifecycle_transition(
                body["state"], body.get("reason")
            )
        if command == "drain_native_notification_work":
            body = _payload(value, allowed={"limit"})
            return self.drain_native_notification_work(body.get("limit", 16))
        if command == "acknowledge_native_notification":
            body = _payload(
                value,
                allowed={"notification_id", "outcome"},
                required={"notification_id", "outcome"},
            )
            return self.acknowledge_native_notification(
                body["notification_id"], body["outcome"]
            )
        if command == "hide_workspace_message":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "event_id"},
                required={"operation_id", "workspace_id", "event_id"},
            )
            return self.hide_workspace_message(
                body["workspace_id"], body["event_id"], body["operation_id"]
            )
        if command == "save_workspace_draft":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "channel_id", "text", "mention_member_ids"},
                required={"operation_id", "workspace_id", "channel_id", "text"},
            )
            return self.save_workspace_draft(
                body["workspace_id"],
                body["channel_id"],
                body["text"],
                body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command == "save_workspace_direct_draft":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "text",
                    "mention_member_ids",
                },
                required={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "text",
                },
            )
            return self.save_workspace_draft(
                body["workspace_id"],
                body["conversation_id"],
                body["text"],
                body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command == "save_workspace_thread_draft":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "conversation_id",
                    "thread_root_id", "text", "mention_member_ids",
                },
                required={
                    "operation_id", "workspace_id", "conversation_id",
                    "thread_root_id", "text",
                },
            )
            return self.save_workspace_thread_draft(
                body["workspace_id"],
                body["conversation_id"],
                body["thread_root_id"],
                body["text"],
                body["operation_id"],
                body.get("mention_member_ids"),
            )
        if command in {"leave_workspace", "close_workspace"}:
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id"},
                required={"operation_id", "workspace_id"},
            )
            return (
                self.leave_workspace(body["workspace_id"], body["operation_id"])
                if command == "leave_workspace"
                else self.close_workspace(body["workspace_id"], body["operation_id"])
            )
        if command == "remove_workspace_data":
            body = _payload(
                value,
                allowed={"operation_id", "workspace_id", "confirmation"},
                required={"operation_id", "workspace_id", "confirmation"},
            )
            return self.remove_workspace_data(
                body["workspace_id"], body["confirmation"], body["operation_id"]
            )
        if command == "save_draft":
            body = _payload(
                value, allowed={"contact_id", "text"}, required={"contact_id", "text"}
            )
            self._require_contact(body["contact_id"])
            if not isinstance(body["text"], str) or len(body["text"].encode("utf-8")) > MAX_TEXT_BYTES:
                raise ValidationError("Draft is invalid")
            draft = {"contact_id": body["contact_id"], "text": body["text"]}
            self.store.put("draft", body["contact_id"], draft)
            return draft
        if command == "retry_message":
            body = _payload(value, allowed={"message_id"}, required={"message_id"})
            self._attempt(body["message_id"])
            return self.store.get("message", body["message_id"])
        if command == "search":
            body = _payload(value, allowed={"query"}, required={"query"})
            return self.search(body["query"])
        if command == "update_settings":
            body = _payload(value, allowed={"settings"}, required={"settings"})
            return self.update_settings(body["settings"])
        if command == "shutdown":
            _payload(value, allowed=set())
            return {"stopping": True}
        raise ValidationError("Unsupported command")

    def _require_profile(self) -> dict[str, Any]:
        profile = self.store.get("profile", "local")
        if profile is None:
            raise ValidationError("Create a local profile first")
        return profile

    def _require_contact(self, contact_id: str) -> dict[str, Any]:
        if not isinstance(contact_id, str):
            raise ValidationError("Contact ID is invalid")
        contact = self.store.get("contact", contact_id)
        if contact is None:
            raise ValidationError("Contact does not exist")
        return contact

    def _contact_by_destination(self, destination: str) -> dict[str, Any] | None:
        for contact in self.store.list("contact"):
            if contact["destination_hash"] == destination:
                return contact
        return None

    def _apply_contact_hints(
        self,
        contact: dict[str, Any],
        *,
        previous_clients: list[dict[str, Any]] | None = None,
    ) -> None:
        """Apply a contact's newest routes without creating invalid settings.

        Invitations and persisted network settings share the same bounded hint
        format. Put the route the user just approved first, retain other known
        routes when space permits, and never persist more than ``MAX_HINTS``.
        ``previous_clients`` lets invitation refreshes persist pure removals.
        """

        before = (
            [dict(hint) for hint in previous_clients]
            if previous_clients is not None
            else [dict(hint) for hint in self.settings.tcp_clients]
        )
        candidates = [
            *[dict(hint) for hint in contact.get("connection_hints", [])],
            *[dict(hint) for hint in self.settings.tcp_clients],
        ]
        desired: list[dict[str, Any]] = []
        for hint in candidates:
            if hint not in desired:
                desired.append(hint)
            if len(desired) == MAX_HINTS:
                break
        self.settings.tcp_clients = desired
        if desired == before and not self._connection_settings_dirty:
            return
        if desired != before:
            self.store.put("settings", "network", self.settings.to_dict())
        if self.network:
            try:
                self.network.apply_connection_settings(self.settings)
                self._connection_settings_dirty = False
            except Exception:
                # Route activation is a recoverable transport side effect. The
                # signed hints and outbox are already durable; a later delivery
                # attempt retries activation without failing the user action
                # after its trust state has committed.
                self._connection_settings_dirty = True

    def _changed(self) -> None:
        self.emit({"type": "event", "event": "state_changed"})

    def close(self) -> None:
        with self._close_lock:
            if self._close_started:
                return
            self._close_started = True
        self._shutdown.set()
        if self._direct_native is not None:
            self._direct_native.close()
        self._direct_recovery.retire(close=True)
        if self._direct_setup is not None:
            self._direct_setup.retire(close=True)
        self._direct_sessions.retire_all("closed", close=True)
        self._direct_packets.retire_all(close=True)
        packets_stopped = self._direct_packets.wait(timeout=0.1)
        try:
            self.close_participant_hosts()
        except Exception:
            pass
        # Stop application retries first so they cannot enter LXMF while its
        # router is unwinding. Both waits are bounded for desktop's two-second
        # sidecar shutdown deadline.
        if self._retry_thread.is_alive() and self._retry_thread is not threading.current_thread():
            self._retry_thread.join(timeout=0.75)
        callbacks_stopped = True
        if self.network:
            # Older/narrow test adapters return None; only an explicit False
            # means a real callback is still executing.
            callbacks_stopped = self.network.shutdown() is not False
        # Never close the encrypted vault underneath an already-running
        # callback or retry. If the bounded foreground shutdown expires, a
        # daemon finalizer waits for that worker and closes the vault exactly
        # once without delaying desktop's sidecar deadline.
        workers_stopped = self._direct_recovery.wait(timeout=0.1) and packets_stopped and callbacks_stopped and not self._retry_thread.is_alive()
        if not workers_stopped:
            finalizer = threading.Thread(
                target=self._finish_deferred_close,
                name="mesh-chat-service-close",
                daemon=True,
            )
            with self._close_lock:
                self._close_finalizer = finalizer
            finalizer.start()
            return
        self._close_store_once()

    def _finish_deferred_close(self) -> None:
        """Close the vault after bounded shutdown had to leave a worker active."""

        try:
            self._direct_packets.wait()
            self._direct_recovery.wait()
            if (
                self._retry_thread.is_alive()
                and self._retry_thread is not threading.current_thread()
            ):
                self._retry_thread.join()
            if self.network:
                wait_for_callbacks = getattr(
                    self.network, "wait_for_callback_shutdown", None
                )
                if callable(wait_for_callbacks):
                    wait_for_callbacks()
            self._close_store_once()
        except Exception:
            # Shutdown cleanup must remain content-free and must not terminate
            # an embedded mobile host. The process-level owner can still
            # release resources during its own teardown.
            pass

    def _close_store_once(self) -> None:
        with self._close_lock:
            if self._store_closed:
                return
            with self._dispatch_lock:
                self.store.close()
                self._store_closed = True
