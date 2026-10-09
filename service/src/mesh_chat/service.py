from __future__ import annotations

import base64
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
)
from .invitations import (
    MAX_HINTS,
    InvitationFormats,
    VerifiedInvitation,
    create_invitation,
    readable_fingerprint,
    verify_invitation,
)
from .group_service import GroupServiceMixin
from .models import Contact, DeliveryState, Message, MessageKind, Profile, TrustState
from .network import ReticulumNetwork, select_lan_listener_port
from .reactions import ReactionServiceMixin
from .reticulum_config import NetworkSettings
from .vault import VaultStore
from .workspace_service import WorkspaceServiceMixin
from .workspace_wire import is_workspace_payload, parse_workspace_payload

EventCallback = Callable[[dict[str, Any]], None]
CONTACT_REQUEST_WINDOW_SECONDS = 60 * 60
CONTACT_REQUESTS_PER_IDENTITY = 5
MAX_PENDING_REQUESTS = 100
CONTACT_FLUSH_ATTEMPTS = 4
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


class MeshChatService(ReactionServiceMixin, GroupServiceMixin, WorkspaceServiceMixin):
    COMMANDS = {
        "snapshot",
        "workspace_snapshot",
        "create_profile",
        "create_invitation",
        "preview_invitation",
        "accept_invitation",
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
        "update_workspace_metadata",
        "update_workspace_policies",
        "remove_workspace_member",
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
        "edit_workspace_message",
        "delete_workspace_message",
        "set_workspace_reaction",
        "list_workspace_messages",
        "list_workspace_direct_messages",
        "mark_workspace_read",
        "mark_workspace_direct_read",
        "hide_workspace_message",
        "save_workspace_draft",
        "save_workspace_direct_draft",
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
        "snapshot",
        "workspace_snapshot",
        "search",
        "connection_help",
        "preview_workspace_invitation",
        "list_workspace_messages",
        "list_workspace_direct_messages",
    }

    def __init__(self, store: VaultStore, profile_dir: Path, emit: EventCallback):
        self.store = store
        self.profile_dir = profile_dir
        self.emit = emit
        self.network: ReticulumNetwork | None = None
        self._identity: RNS.Identity | None = None
        self._shutdown = threading.Event()
        self._dispatch_lock = threading.RLock()
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
            self._prepare_lan_fallback()
            self._start_network(profile_record["display_name"])
            with self._dispatch_lock:
                self._recover_outbox()

        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self._retry_thread.start()

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

    def invitation(self) -> InvitationFormats:
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
        return create_invitation(self._identity, profile["display_name"], hints=hints)

    def preview_invitation(self, raw: str) -> dict[str, Any]:
        try:
            return verify_invitation(raw).preview()
        except ValidationError as exc:
            raise InvitationInvalid("Invitation could not be validated") from exc

    def accept_invitation(self, raw: str) -> dict[str, Any]:
        try:
            invitation = verify_invitation(raw)
        except ValidationError as exc:
            raise InvitationInvalid("Invitation could not be validated") from exc
        profile = self._require_profile()
        if invitation.destination_hash.hex() == profile["destination_hash"]:
            raise ValidationError("Cannot connect to the local identity")
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
            return existing

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
        return contact

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
                    self._flush_contact(contact["id"])
                    self._changed()
                return
            if app.kind == MessageKind.CONTACT_DECLINE:
                if contact["trust"] == TrustState.AWAITING_CONSENT.value:
                    contact["trust"] = TrustState.BLOCKED.value
                    contact["updated_at"] = time.time()
                    self.store.put("contact", contact["id"], contact)
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
            "settings": self.settings.to_dict(),
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
        self.settings = settings
        self._prepare_lan_fallback()
        self.store.put("settings", "network", self.settings.to_dict())
        self._changed()
        return {"settings": self.settings.to_dict(), "restart_required": True}

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
            _payload(value, allowed=set())
            return self.invitation()
        if command in {"preview_invitation", "accept_invitation"}:
            body = _payload(value, allowed={"invitation"}, required={"invitation"})
            if not isinstance(body["invitation"], str):
                raise ValidationError("Invitation must be text")
            return (
                self.preview_invitation(body["invitation"])
                if command == "preview_invitation"
                else self.accept_invitation(body["invitation"])
            )
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
                allowed={"operation_id", "workspace_id", "lifetime_days"},
                required={"operation_id", "workspace_id"},
            )
            return self.create_workspace_invitation_command(
                body["workspace_id"],
                body["operation_id"],
                body.get("lifetime_days", 7),
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
            )
        if command == "edit_workspace_message":
            body = _payload(
                value,
                allowed={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id", "text",
                },
                required={
                    "operation_id", "workspace_id", "event_id",
                    "mutation_event_id", "text",
                },
            )
            return self.edit_workspace_message(
                body["workspace_id"], body["event_id"], body["text"],
                body["mutation_event_id"], body["operation_id"],
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
                allowed={"operation_id", "workspace_id", "channel_id", "text"},
                required={"operation_id", "workspace_id", "channel_id", "text"},
            )
            return self.save_workspace_draft(
                body["workspace_id"],
                body["channel_id"],
                body["text"],
                body["operation_id"],
            )
        if command == "save_workspace_direct_draft":
            body = _payload(
                value,
                allowed={
                    "operation_id",
                    "workspace_id",
                    "conversation_id",
                    "text",
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
        workers_stopped = callbacks_stopped and not self._retry_thread.is_alive()
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
