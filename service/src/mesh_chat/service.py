from __future__ import annotations

import base64
import hashlib
import json
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import LXMF
import RNS

from . import connection_diagnostics
from .background_availability import BackgroundAvailabilityMixin
from .contact_invitations import ContactInvitationsMixin
from .native_webrtc_control import NativeWebRTCControlMixin
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
    IdentityMismatch,
    InvitationInvalid,
    MeshChatError,
    MailboxNotConfigured,
    WebRTCBridgeMissing,
    NativeUnavailable,
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
from .call_manager import CallManager
from .call_settings import CallSettings
from .turn_credentials import fetch_ice_servers
from .signal_mailbox import fetch as fetch_signal
from .signal_mailbox import publish as publish_signal
from .signal_mailbox import create_pairing, parse_pairing
from .webrtc_interface import WebRTCInterface
from .webrtc_signaling import _fingerprint
from .webrtc_onboarding import (
    create_onboarding_answer,
    create_onboarding_offer,
    verify_onboarding_answer,
    verify_onboarding_offer,
)
from .direct_runtime import SessionRegistry
from .direct_packets import PacketRuntime
from .direct_packet_adapter import ProfileBudget
from .group_service import FINAL_DELIVERY_STATES, GroupServiceMixin
from .models import Contact, DeliveryState, Message, MessageKind, Profile, TrustState
from .network import ReticulumNetwork, select_lan_listener_port
from .i2p_router import I2PRouterManager
from .i2p_invitation import (
    create_i2p_invitation,
    i2p_invitation_formats,
    verify_i2p_invitation,
)
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
from .reconnect_service import ReconnectServiceMixin
from .remote import (
    create_remote_personal_invitation,
    remote_invitation_formats,
    sanitized_profile,
    verify_remote_invitation,
)
from .remote_service import RemoteProfileServiceMixin
from .reticulum_config import NetworkSettings, write_config
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
    ContactInvitationsMixin,
    NativeWebRTCControlMixin,
    BackgroundAvailabilityMixin,
    ReconnectServiceMixin,
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
        "i2p_status",
        "workspace_snapshot",
        "create_profile",
        "create_invitation",
        "preview_invitation",
        "accept_invitation",
        "receive_contact_invitation", "decide_contact_invitation",
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
        "start_call",
        "answer_call",
        "add_call_candidate",
        "end_call",
        "call_media",
        "restart_call",
        "answer_call_restart",
        "call_settings",
        "update_call_settings",
        "call_ice_servers",
        "link_preview",
        "signal_publish",
        "signal_fetch",
        "reconnect_profiles",
        "reconnect_consent_set",
        "reconnect_capabilities_create",
        "reconnect_capabilities_store",
        "reconnect_capabilities_get",
        "reconnect_replay_check",
        "reconnect_status",
        "reconnect_start",
        "reconnect_stop",
        "reconnect_request_create",
        "reconnect_offer_create",
        "reconnect_answer_create",
        "reconnect_publish",
        "reconnect_fetch",
        "reconnect_path_status",
        "verify_reconnect_request",
        "verify_reconnect_offer",
        "verify_reconnect_answer",
        "webrtc_attach",
        "webrtc_packet",
        "webrtc_detach",
        "native_webrtc_offer",
        "native_webrtc_accept",
        "native_webrtc_apply_answer",
        "native_webrtc_control",
        "native_webrtc_close",
        "native_webrtc_stats",
        "native_webrtc_bind_onboarding",
        "webrtc_onboarding_offer",
        "webrtc_onboarding_answer",
        "verify_webrtc_onboarding_offer",
        "verify_webrtc_onboarding_answer",
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
        "search_workspace",
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
        "invite_contact_to_workspace",
        "dismiss_workspace_invitation_prompt",
        "preview_workspace_invitation_prompt",
        "submit_workspace_invitation_prompt",
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
        "workspace_connectivity",
        "workspace_reconnect_status",
        "workspace_reconnect_consent_set",
        "workspace_helper_status",
        "workspace_helper_consent_set",
        "relay_workspace_connection_update",
        "create_workspace_admission_grant",
        "accept_workspace_admission_grant",
        "list_workspace_admission_grants",
        "end_workspace_admission_grant",
        "workspace_request_paths",
        "create_workspace_access_recommendation",
        "preview_workspace_access_recommendation",
        "apply_workspace_access_recommendation",
        "send_workspace_access_recommendation",
        "list_workspace_access_recommendations",
        "preview_workspace_access_recommendation_by_id",
        "apply_workspace_access_recommendation_by_id",
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
        "workspace_connectivity",
        "workspace_reconnect_status",
        "workspace_reconnect_consent_set",
        "workspace_helper_status",
        "workspace_helper_consent_set",
        "relay_workspace_connection_update",
        "create_workspace_admission_grant",
        "accept_workspace_admission_grant",
        "list_workspace_admission_grants",
        "end_workspace_admission_grant",
        "workspace_request_paths",
        "create_workspace_access_recommendation",
        "preview_workspace_access_recommendation",
        "apply_workspace_access_recommendation",
        "send_workspace_access_recommendation",
        "list_workspace_access_recommendations",
        "preview_workspace_access_recommendation_by_id",
        "apply_workspace_access_recommendation_by_id",
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
        "set_background_availability",
        "background_status",
        # Native-only mobile bridge commands. Rust never exposes these names
        # through the renderer allowlist.
        "native_notification_state",
        "native_ringing_calls",
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
        "link_preview",
        "reconnect_profiles", "reconnect_capabilities_get", "reconnect_path_status",
        "resume_direct_setup",
        "connection_diagnostics", "clear_connection_diagnostics",
        "preview_direct_connection", "prepare_direct_offer", "prepare_direct_answer",
        "prepare_direct_ready", "accept_direct_ready", "connect_direct_setup",
        "configure_direct_firewall",
        "direct_setup_status", "cancel_direct_setup", "check_direct_setup", "retry_direct_setup",
        "direct_recovery_status", "export_recovery_update", "import_recovery_update",
        "pause_direct_recovery", "resume_direct_recovery",
        "snapshot",
        "i2p_status",
        "workspace_snapshot",
        "search",
        "search_workspace",
        "connection_help",
        "preview_invitation",
        "preview_connection_reply",
        "preview_route_update",
        "preview_remote_profile",
        "list_remote_profiles",
        "preview_workspace_invitation",
        "preview_workspace_invitation_prompt",
        "invite_contact_to_workspace",
        "dismiss_workspace_invitation_prompt",
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
        "background_status",
        "native_notification_state",
        "native_ringing_calls",
        "mobile_lifecycle_transition",
        "drain_native_notification_work",
        "acknowledge_native_notification",
    }

    def __init__(self, store: VaultStore, profile_dir: Path, emit: EventCallback, *, direct_native=None,
                 connection_policy="legacy", native_webrtc_host=None):
        if connection_policy not in {"legacy", "shared-native"}:
            raise ValueError("Unsupported connection policy")
        self._native_host = native_webrtc_host
        if connection_policy == "shared-native" or native_webrtc_host is not None:
            # Private composition option, never a renderer command. Qualification
            # must explicitly select a native host before this becomes default.
            from .native_webrtc_host import require_host
            self._native_host = require_host(self._native_webrtc_host())
        self._connection_policy = connection_policy
        self._connection_runtime = None
        from .link_previews import LinkPreviews
        self._link_previews = LinkPreviews()
        self.store = store
        self.profile_dir = profile_dir
        self.emit = emit
        self._direct_native = direct_native
        self.network: ReticulumNetwork | None = None
        self._identity: RNS.Identity | None = None
        self._shutdown = threading.Event()
        self._dispatch_lock = threading.RLock()
        self._retry_queue_lock = threading.Lock()
        self._direct_retry_ids: dict[str, None] = {}
        self._group_retry_ids: dict[str, None] = {}
        self._group_retry_missing: set[str] = set()
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
        self._i2p_router = I2PRouterManager(profile_dir)
        self._call_settings = CallSettings.from_dict(store.get("call_settings", "default"))
        self.calls = CallManager(
            store,
            self._send_call_document,
            persist=self._call_settings.store_call_signaling,
        )
        self._turn_ice_lock = threading.Lock()
        self._turn_ice_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._webrtc_bridges: dict[str, WebRTCInterface] = {}
        self._native_webrtc_sessions: dict[str, str] = {}
        self._native_webrtc_lock = threading.RLock()
        from .native_resource_registry import NativeResourceRegistry
        self._native_resources = NativeResourceRegistry()
        from .native_startup_packets import NativeStartupPackets
        self._native_startup_packets = NativeStartupPackets()
        self._native_webrtc_live: set[str] = set()
        self._native_webrtc_creating: set[str] = set()
        self._native_webrtc_profile_sessions: dict[str, str] = {}
        self._native_webrtc_descriptions: dict[str, dict] = {}
        self._native_webrtc_peers: dict[str, str] = {}
        self._native_webrtc_controls: dict[str, dict] = {}
        self._background_reconnect_supervisor = None
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
            if self.settings.i2p_enabled and self.settings.i2p_managed:
                self._i2p_router.start()
            self._start_network(profile_record["display_name"])
            with self._dispatch_lock:
                self._recover_outbox()

        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self._retry_thread.start()
        from .native_webrtc_events import NativeEventInbox
        self._native_webrtc_events = NativeEventInbox()
        self._native_webrtc_event_thread = threading.Thread(
            target=self._native_webrtc_event_loop,
            daemon=True,
            name="mesh-chat-native-webrtc-events",
        )
        self._native_webrtc_event_thread.start()
        self._direct_recovery.start()
        if self._connection_policy == "shared-native":
            from .connection.composition import native_runtime
            self._connection_runtime = native_runtime(self)
            self._connection_runtime.start()
        if self._background_availability_enabled():
            self._sync_background_reconnect()

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
        i2p_access_point: str | None = None,
        i2p_label: str | None = None,
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
        if connection_mode == "i2p":
            if not isinstance(i2p_access_point, str):
                raise ValidationError("I2P access point is required")
            serialized = create_i2p_invitation(
                self._identity,
                local["file"],
                "personal",
                i2p_access_point,
                label=i2p_label if isinstance(i2p_label, str) else None,
                expires_at=local["expires_at"],
            )
            verified = verify_i2p_invitation(serialized, "personal")
            if verified is None:
                raise ValidationError("I2P invitation could not be created")
            if not self.settings.i2p_connectable:
                self._adopt_i2p_access_point(verified.access_point["b32"])
            return {
                **i2p_invitation_formats(serialized, "personal"),
                "expires_at": verified.expires_at,
                "connection_mode": "i2p",
                "i2p_access_point": verified.access_point["b32"],
            }
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
        if connection_mode not in {None, "nearby", "remote", "webrtc"}:
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
            i2p = verify_i2p_invitation(raw, "personal")
            email = None if i2p else verify_email_invitation(raw, "personal")
            participant = None if i2p or email else verify_participant_invitation(raw, "personal")
            remote = None if i2p or email or participant else verify_remote_invitation(raw, "personal")
            invitation = verify_invitation(
                i2p.inner if i2p else email.inner if email else participant.inner if participant else remote.inner if remote else raw
            )
            preview = invitation.preview()
            if i2p is not None:
                preview["i2p_access_point"] = i2p.access_point
                preview["requires_i2p_consent"] = True
                preview["expires_at"] = min(preview["expires_at"], i2p.expires_at)
            elif email is not None:
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

    def accept_invitation(self, raw: str, *, i2p_consent: bool = False) -> dict[str, Any]:
        try:
            i2p = verify_i2p_invitation(raw, "personal")
            email = None if i2p else verify_email_invitation(raw, "personal")
            participant = None if i2p or email else verify_participant_invitation(raw, "personal")
            remote = None if i2p or email or participant else verify_remote_invitation(raw, "personal")
            invitation = verify_invitation(
                i2p.inner if i2p else email.inner if email else participant.inner if participant else remote.inner if remote else raw
            )
        except ValidationError as exc:
            raise InvitationInvalid("Invitation could not be validated") from exc
        if i2p is not None:
            if not i2p_consent:
                raise ValidationError("I2P access point consent is required")
            self._adopt_i2p_access_point(i2p.access_point["b32"])
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
            self._reconnect_promote_pending(existing["destination_hash"])
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
        self._reconnect_promote_pending(contact["destination_hash"])
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
        if accepted["state"] in DIRECT_RETRY_STATES:
            self._queue_direct_retry(accepted["id"])
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
        # A capability received before the contact request arrived is held
        # pending; approval is the point where it becomes usable.
        self._reconnect_promote_pending(contact["destination_hash"])
        # The joiner knows this destination from the signed invitation, so an
        # approved contact is exactly when both sides can exchange signed
        # reconnect capabilities using the personal contact's saved/default
        # preference. Direct-IP disclosure and relay consent stay separate.
        capabilities = self._contact_capabilities(contact)
        self._native_onboarding_approval(contact, True, capabilities)
        return {
            **contact,
            **({"reconnect_capabilities": capabilities} if capabilities else {}),
        }

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
        self._native_onboarding_approval(contact, False)
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
            with self._connection_authority_update(contact_id):
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
        with self._connection_authority_update(contact_id):
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
        with self._connection_authority_update(contact_id):
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

    def _call_identity(self) -> RNS.Identity:
        if self._identity is None:
            raise NetworkUnavailable("Local identity is not ready for calls")
        return self._identity

    def _require_call_peer(self, contact_id: str) -> dict[str, Any]:
        if isinstance(contact_id, str) and contact_id.startswith("workspace:"):
            return self._workspace_reconnect_contact(contact_id)
        return self._require_contact(contact_id)

    def _send_call_document(self, contact_id: str, document: str) -> None:
        if not isinstance(document, str) or not document:
            raise ValidationError("Call document is empty")
        if len(document.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValidationError("Call document is too large")
        if contact_id.startswith("workspace:"):
            contact = self._workspace_reconnect_contact(contact_id)
            workspace = self._require_workspace(contact["workspace_id"])
            manifest = self._workspace_current_manifest(workspace)
            member = next(
                (
                    item
                    for item in manifest.members
                    if item.member_id == contact["peer_member_id"]
                ),
                None,
            )
            device = next(
                (
                    item
                    for item in (member.devices if member is not None else ())
                    if item.device_id == contact["peer_device_id"]
                ),
                None,
            )
            if member is None or device is None or member.status != "active":
                raise ContactNotApproved("Workspace call peer is not active")
            delivery = self._workspace_delivery_record(
                workspace_id=workspace["id"],
                recipient_member_id=member.member_id,
                recipient_device=device,
                kind="workspace_call_signal",
                document=document,
                priority=1,
            )
            self.store.put_many(
                [
                    ("workspace_delivery", delivery["id"], delivery),
                    *self._due_records(add=[delivery]),
                ]
            )
            self._workspace_changed(workspace["id"], resource_kind="call")
            return
        contact = self._require_contact(contact_id)
        if contact["trust"] not in {TrustState.APPROVED.value, TrustState.VERIFIED.value}:
            raise ContactNotApproved("Calls require an approved contact")
        message = self._create_outbound(contact, MessageKind.CALL_SIGNAL, document)
        connection_diagnostics.call_signal(self, "call_outbound", document, message["state"])
        self._attempt(message["id"])

    def start_call(
        self,
        contact_id: str,
        media: str,
        sdp: str,
        dtls_fingerprint: str,
    ) -> dict[str, Any]:
        contact = self._require_call_peer(contact_id)
        result = self.calls.start(
            self._call_identity(),
            contact,
            media=media,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
        )
        self._changed()
        return result

    def answer_call(
        self,
        call_id: str,
        sdp: str,
        dtls_fingerprint: str,
    ) -> dict[str, Any]:
        result = self.calls.answer(
            self._call_identity(),
            call_id,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
        )
        self._changed()
        return result

    def add_call_candidate(self, call_id: str, candidate: str) -> dict[str, Any]:
        result = self.calls.add_candidate(self._call_identity(), call_id, candidate)
        self._changed()
        return result

    def end_call(self, call_id: str, reason: str = "completed") -> dict[str, Any]:
        result = self.calls.end(self._call_identity(), call_id, reason)
        self._changed()
        return result

    def restart_call(
        self, call_id: str, sdp: str, dtls_fingerprint: str
    ) -> dict[str, Any]:
        result = self.calls.restart(
            self._call_identity(), call_id, sdp=sdp, dtls_fingerprint=dtls_fingerprint
        )
        self._changed()
        return result

    def answer_call_restart(
        self, call_id: str, sdp: str, dtls_fingerprint: str
    ) -> dict[str, Any]:
        result = self.calls.answer_restart(
            self._call_identity(), call_id, sdp=sdp, dtls_fingerprint=dtls_fingerprint
        )
        self._changed()
        return result

    def call_media(self, call_id: str) -> dict[str, Any]:
        record = self.calls._require_call(call_id)
        result = self.calls.public(record)
        result.update(
            local_sdp=record.get("local_sdp"),
            remote_sdp=record.get("remote_sdp"),
            candidates=list(record.get("candidates", [])),
            restart_offer=record.get("restart_offer"),
            restart_answer=record.get("restart_answer"),
        )
        return result

    def native_ringing_calls(self) -> dict[str, Any]:
        """Return only live inbound ring metadata for the Android service."""
        return {
            "calls": [
                {
                    "id": call["id"],
                    "media": call["media"],
                    "ring_expires_at": call["ring_expires_at"],
                }
                for call in self.calls.active()
                if call["direction"] == "inbound" and call["state"] == "ringing"
            ]
        }

    def call_settings(self) -> dict[str, Any]:
        return self._call_settings.public()

    def update_call_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        existing = self._call_settings
        if (
            not value.get("turn_credential")
            and value.get("turn_url") == existing.turn_url
            and value.get("turn_username") == existing.turn_username
            and existing.turn_credential is not None
        ):
            value = {**value, "turn_credential": existing.turn_credential}
        settings = CallSettings.from_dict(value)
        self.store.put("call_settings", "default", settings.to_dict())
        self._call_settings = settings
        self.calls.set_persist(settings.store_call_signaling)
        with self._turn_ice_lock:
            self._turn_ice_cache = None
        self._changed()
        return settings.public()

    def call_ice_servers(self) -> dict[str, Any]:
        broker = self._call_settings.turn_broker_url if self._call_settings.turn_broker_consent else None
        if broker is not None:
            try:
                servers = self._broker_ice_servers(broker)
            except NetworkUnavailable:
                if self._call_settings.turn_url is None:
                    raise
                servers = self._call_settings.ice_servers()
            return {
                "iceServers": servers,
                "iceTransportPolicy": "relay" if self._call_settings.relay_only else "all",
            }
        return self._call_settings.rtc_configuration()

    def signal_publish(
        self,
        document: str,
        role: str,
        session_id: str | None = None,
        mailbox_token: str | None = None,
    ) -> dict[str, Any]:
        base = self._call_settings.signal_mailbox_url
        if base is None:
            raise MailboxNotConfigured("Signaling mailbox is not configured")
        if mailbox_token is not None or session_id is not None:
            raise ValidationError("Use an encrypted pairing context")
        contexts = self._signal_contexts()
        if role == "offer":
            offer = verify_onboarding_offer(document)
            if offer.signer_destination != self._require_profile()["destination_hash"]:
                raise ValidationError("Only this device's offer can be published")
            code = create_pairing(base)
            contexts[offer.session_id] = {"code": code, "offer": offer, "expires_at": time.time() + 600}
        elif role == "answer":
            try:
                context = contexts[json.loads(document)["session_id"]]
            except (KeyError, TypeError, ValueError):
                raise ValidationError("Encrypted pairing context is missing; import the invitation again") from None
            offer = context["offer"]
            answer = verify_onboarding_answer(document, offer)
            if answer.signer_destination != self._require_profile()["destination_hash"]:
                raise ValidationError("Only this device's answer can be published")
            code = context["code"]
        else:
            raise ValidationError("Onboarding role is invalid")
        pairing = parse_pairing(code, base)
        result = publish_signal(base, document, role, token=pairing["token"],
                                session=pairing["session"], secret=pairing["secret"])
        # The UI shares this code explicitly, never in diagnostics or persistence.
        return {**result, "session_id": code}

    def _signal_contexts(self) -> dict[str, Any]:
        contexts = getattr(self, "_signal_pairing_contexts", {})
        for key in list(contexts):
            if contexts[key]["expires_at"] <= time.time():
                del contexts[key]
        while len(contexts) >= 32:
            del contexts[next(iter(contexts))]
        self._signal_pairing_contexts = contexts
        return contexts

    def signal_fetch(
        self,
        session: str,
        role: str,
        mailbox_token: str | None = None,
    ) -> dict[str, Any]:
        base = self._call_settings.signal_mailbox_url
        if base is None:
            raise MailboxNotConfigured("Signaling mailbox is not configured")
        if mailbox_token is not None or role not in {"offer", "answer"}:
            raise ValidationError("Use an encrypted pairing context")
        pairing = parse_pairing(session, base)
        fetched = fetch_signal(base, pairing["session"], role,
                               token=pairing["token"], secret=pairing["secret"])
        if role == "offer":
            offer = verify_onboarding_offer(fetched["document"])
            self._signal_contexts()[offer.session_id] = {
                "code": session, "offer": offer, "expires_at": pairing["expires_at"],
            }
        return {**fetched, "session_id": session}

    def _broker_ice_servers(self, broker: str) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._turn_ice_lock:
            cached = self._turn_ice_cache
            if cached is not None and cached[0] > now:
                return [dict(item) for item in cached[1]]
        servers = fetch_ice_servers(broker)
        # Cloudflare credentials are short-lived. Refresh well before the
        # requested one-hour TTL rather than keeping a stale allocation.
        with self._turn_ice_lock:
            self._turn_ice_cache = (now + 3000.0, servers)
        return [dict(item) for item in servers]

    def webrtc_onboarding_offer(self, sdp: str, dtls_fingerprint: str) -> dict[str, Any]:
        identity = self._call_identity()
        session_id = uuid.uuid4().hex
        document = create_onboarding_offer(
            identity,
            session_id=session_id,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
        )
        verified = verify_onboarding_offer(document)
        return {
            "document": document,
            "session_id": verified.session_id,
            "expires_at": verified.expires_at,
        }

    def verify_webrtc_onboarding_offer(self, document: str) -> dict[str, Any]:
        offer = verify_onboarding_offer(document)
        return {
            "document": offer.serialized,
            "session_id": offer.session_id,
            "sdp": offer.sdp,
            "dtls_fingerprint": offer.dtls_fingerprint,
            "expires_at": offer.expires_at,
            "signer_destination": offer.signer_destination,
        }

    def webrtc_onboarding_answer(
        self, offer_document: str, sdp: str, dtls_fingerprint: str
    ) -> dict[str, Any]:
        offer = verify_onboarding_offer(offer_document)
        document = create_onboarding_answer(
            self._call_identity(), offer, sdp=sdp, dtls_fingerprint=dtls_fingerprint
        )
        answer = verify_onboarding_answer(document, offer)
        return {
            "document": document,
            "session_id": answer.session_id,
            "signer_destination": answer.signer_destination,
            "expires_at": answer.expires_at,
        }

    def verify_webrtc_onboarding_answer(
        self, offer_document: str, answer_document: str
    ) -> dict[str, Any]:
        offer = verify_onboarding_offer(offer_document)
        answer = verify_onboarding_answer(answer_document, offer)
        return {
            "document": answer.serialized,
            "session_id": answer.session_id,
            "sdp": answer.sdp,
            "dtls_fingerprint": answer.dtls_fingerprint,
            "expires_at": answer.expires_at,
            "signer_destination": answer.signer_destination,
        }


    def webrtc_attach(self, bridge_id: str | None = None, peer_destination: str | None = None) -> dict[str, Any]:
        if self.network is None:
            raise NetworkUnavailable("Reticulum is not running for a WebRTC bridge")
        peer = None
        if peer_destination is not None:
            try:
                if not isinstance(peer_destination, str) or len(peer_destination) != 32:
                    raise ValueError()
                peer = bytes.fromhex(peer_destination)
                if len(peer) != 16:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ValidationError("WebRTC peer destination is invalid") from exc
        if bridge_id is not None:
            try:
                if not isinstance(bridge_id, str) or str(uuid.UUID(bridge_id)) != bridge_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValidationError("WebRTC bridge identifier is invalid") from exc
            existing = self._webrtc_bridges.get(bridge_id)
            if existing is not None and existing.online:
                if peer is not None and (not self.network.path_known(peer) or not self.network.recipient_ready(peer)):
                    # Bound repair traffic even if several callers probe at once.
                    now = time.monotonic()
                    if now >= getattr(existing, "_next_route_repair", 0):
                        existing._next_route_repair = now + 10.0
                        self._webrtc_recover_routes(bridge_id, [peer])
                return {"bridge_id": bridge_id, "max_packet": WebRTCInterface.HW_MTU, "state": "online"}
            if existing is not None:
                self.webrtc_detach(bridge_id)
        else:
            bridge_id = _new_id()
        # A renderer-owned DataChannel survives a desktop sidecar restart.
        # Reuse its handle so subscriptions and session ownership remain valid.
        interface = WebRTCInterface(
            RNS.Transport,
            lambda data: self._webrtc_outbound(bridge_id, data),
            name=f"Mesh Chat WebRTC {bridge_id[:8]}",
        )
        try:
            # Reticulum applies receive/announce defaults before publishing
            # the interface; Transport.add_interface only adds it to a list.
            self.network.reticulum._add_interface(
                interface, mode=interface.MODE_POINT_TO_POINT
            )
            if interface not in RNS.Transport.interfaces:
                raise RuntimeError("Reticulum did not register the WebRTC interface")
        except Exception as exc:
            interface.detach()
            raise NetworkUnavailable("Could not attach the WebRTC interface") from exc
        self._webrtc_bridges[bridge_id] = interface
        # The WebRTC interface is point-to-point and is added after Reticulum
        # startup. Announce the local LXMF destination on it so the peer can
        # learn a path/ratchet and the accepted contact request can leave the
        # outbox instead of waiting for an unrelated announce.
        connection_diagnostics.record(self, "transport_state", {
            "setup_id": bridge_id, "state": "open", "command": "webrtc_attach", "component": "bridge",
        })
        try:
            self.network.reannounce()
        except Exception:
            pass
        for delay in (2.0, 6.0):
            threading.Thread(
                target=self._webrtc_announce_later,
                args=(bridge_id, delay),
                daemon=True,
                name="mesh-chat-webrtc-announce",
            ).start()
        self._changed()
        return {
            "bridge_id": bridge_id,
            "max_packet": WebRTCInterface.HW_MTU,
            "state": "online",
        }

    def webrtc_packet(self, bridge_id: str, data: str) -> dict[str, Any]:
        interface = self._webrtc_bridges.get(bridge_id)
        if interface is None or not interface.online:
            raise WebRTCBridgeMissing("WebRTC bridge is not active")
        if not isinstance(data, str) or not data:
            raise ValidationError("WebRTC packet is empty")
        try:
            packet = _unb64(data)
        except Exception as exc:
            raise ValidationError("WebRTC packet is invalid") from exc
        if not 1 <= len(packet) <= WebRTCInterface.HW_MTU:
            raise ValidationError("WebRTC packet exceeds the interface MTU")
        interface.process_incoming(packet)
        return {"accepted": len(packet)}

    def webrtc_detach(self, bridge_id: str) -> dict[str, Any]:
        interface = self._webrtc_bridges.pop(bridge_id, None)
        if interface is not None:
            connection_diagnostics.record(self, "transport_state", {
                "setup_id": bridge_id, "state": "closed", "command": "webrtc_detach", "component": "bridge",
            })
            lost_destinations = interface.detach()
            router = getattr(self.network, "router", None)
            if router is not None:
                # LXMF retains even CLOSED cached links until a send notices
                # them, which adds a retry delay to both chat and its receipt.
                # Serialize with outbound selection and leave other paths alone.
                with router.outbound_processing_lock:
                    for links in (router.direct_links, router.backchannel_links):
                        for destination, link in list(links.items()):
                            if getattr(link, "attached_interface", None) is interface:
                                if links.get(destination) is link:
                                    links.pop(destination)
            survivor = next(
                (candidate for candidate, bridge in self._webrtc_bridges.items() if bridge.online),
                None,
            )
            if survivor is not None:
                # A newer failed channel may have become the selected Reticulum
                # path even while an older data channel remains healthy.
                self._webrtc_recover_routes(survivor, lost_destinations)
                for delay in (2.0, 6.0):
                    threading.Thread(
                        target=self._webrtc_recover_routes_later,
                        args=(survivor, lost_destinations, delay),
                        daemon=True,
                        name="mesh-chat-webrtc-route-recovery",
                    ).start()
        self._changed()
        return {"state": "closed"}

    def _webrtc_recover_routes(self, bridge_id: str, destinations: list[bytes]) -> None:
        if self.network is None or not self._webrtc_bridges.get(bridge_id, None):
            return
        if not self._webrtc_bridges[bridge_id].online:
            return
        try:
            self.network.reannounce()
        except Exception:
            pass
        for destination in destinations[:32]:
            try:
                self.network.request_path(destination)
            except Exception:
                pass

    def _webrtc_recover_routes_later(
        self, bridge_id: str, destinations: list[bytes], delay: float
    ) -> None:
        if not self._shutdown.wait(delay):
            self._webrtc_recover_routes(bridge_id, destinations)

    def _webrtc_announce_later(self, bridge_id: str, delay: float) -> None:
        if self._shutdown.wait(delay):
            return
        if bridge_id not in self._webrtc_bridges or self.network is None:
            return
        try:
            self.network.reannounce()
        except Exception:
            pass

    def _webrtc_outbound(self, bridge_id: str, data: bytes) -> None:
        interface = self._webrtc_bridges.get(bridge_id)
        if interface is None or not interface.online:
            return
        if not data or len(data) > WebRTCInterface.HW_MTU:
            return
        self.emit(
            {
                "type": "event",
                "event": "webrtc_packet",
                "bridge_id": bridge_id,
                "data": base64.b64encode(data).decode("ascii"),
            }
        )

    # ------------------------------------------------- native WebRTC host
    _native_answer_exchange_timeout = 120.0

    def _native_webrtc_host(self):
        from .native_webrtc_host import android_host
        host = getattr(self, "_native_host", None)
        return android_host() if host is None else host

    def webrtc_attach_native(self, session_id: str) -> dict[str, Any]:
        with self._dispatch_lock:
            return self._attach_native_bridge(session_id)

    def _attach_native_bridge(self, session_id: str) -> dict[str, Any]:
        if (getattr(self, "_connection_policy", "legacy") == "shared-native"
                and not self._shared_native_session(session_id)):
            raise ContactNotApproved("Native messaging carrier has not been adopted")
        if not self._native_carrier_authorized(session_id):
            raise ContactNotApproved("Native messaging carrier authority is unavailable")
        if session_id not in self._native_webrtc_live:
            raise NativeUnavailable("Native messaging carrier is retiring")
        if self.network is None:
            raise NetworkUnavailable("Reticulum is not running for a WebRTC bridge")
        existing = self._native_webrtc_sessions.get(session_id)
        if self._native_bridge_attached(session_id):
            return {
                "bridge_id": existing,
                "max_packet": WebRTCInterface.HW_MTU,
                "state": "online",
            }
        if existing is not None:
            self.webrtc_detach_native(session_id)
        bridge_id = _new_id()
        physical = self._native_resources.require(session_id)

        def send(data: bytes) -> None:
            if (session_id not in self._native_webrtc_live
                    or not self._native_resources.current(session_id, physical)
                    or self._native_webrtc_sessions.get(session_id) != bridge_id
                    or not self._native_bridge_attached(session_id)):
                return
            try:
                self._native_webrtc_host().send(physical, data)
            except Exception:
                pass

        interface = WebRTCInterface(
            RNS.Transport,
            send,
            name=f"Mesh Chat native WebRTC {bridge_id[:8]}",
        )
        try:
            self.network.reticulum._add_interface(
                interface, mode=interface.MODE_POINT_TO_POINT
            )
            if interface not in RNS.Transport.interfaces:
                raise RuntimeError("Reticulum did not register the native WebRTC interface")
        except Exception as exc:
            interface.detach()
            raise NetworkUnavailable("Could not attach the native WebRTC interface") from exc
        self._webrtc_bridges[bridge_id] = interface
        self._native_webrtc_sessions[session_id] = bridge_id
        self._deliver_native_startup_packets(session_id, physical, interface)
        try:
            self.network.reannounce()
        except Exception:
            pass
        for delay in (2.0, 6.0):
            threading.Thread(
                target=self._webrtc_announce_later,
                args=(bridge_id, delay),
                daemon=True,
                name="mesh-chat-native-webrtc-announce",
            ).start()
        self._changed()
        return {
            "bridge_id": bridge_id,
            "max_packet": WebRTCInterface.HW_MTU,
            "state": "online",
        }

    def _deliver_native_startup_packets(self, session_id, physical, interface):
        for packet in self._native_startup_packets.take(physical):
            if (session_id not in self._native_webrtc_live
                    or not self._native_resources.current(session_id, physical)
                    or not self._native_bridge_attached(session_id)):
                return
            try:
                interface.process_incoming(packet)
            except Exception:
                # One malformed early packet must not hide the remaining announces.
                continue

    def _retain_native_startup_packet(self, session_id, data):
        with self._native_webrtc_lock:
            if session_id not in self._native_webrtc_live or not self._shared_native_session(session_id):
                return
            physical = self._native_resources.physical(session_id)
            if physical is not None:
                self._native_startup_packets.retain(physical, data)

    def _native_bridge_attached(self, session_id: str) -> bool:
        bridge_id = self._native_webrtc_sessions.get(session_id)
        interface = self._webrtc_bridges.get(bridge_id)
        return bool(session_id in self._native_webrtc_live
                    and getattr(self, "network", None) is not None and interface is not None
                    and interface.online and any(current is interface for current in RNS.Transport.interfaces)
                    and self._native_carrier_authorized(session_id))

    def _native_carrier_authorized(self, session_id: str) -> bool:
        if getattr(self, "_connection_policy", "legacy") != "shared-native":
            return True
        runtime = getattr(self, "_connection_runtime", None)
        if runtime is None:
            return False
        with self._native_webrtc_lock:
            profile_id = next((profile for profile, current in self._native_webrtc_profile_sessions.items()
                               if current == session_id), None)
        from .connection.model import Resource
        physical = self._native_resources.physical(session_id)
        return profile_id is not None and physical is not None and (
            runtime.permits_carrier(profile_id, Resource("native", physical))
            or runtime.permits_carrier(profile_id, Resource("native", session_id)))

    def webrtc_detach_native(self, session_id: str) -> dict[str, Any]:
        bridge_id = self._native_webrtc_sessions.pop(session_id, None)
        if bridge_id is not None:
            self.webrtc_detach(bridge_id)
        return {"state": "closed"}

    def native_webrtc_event(self, event: str, session_id: str, data: str = "") -> None:
        """Queue a WebRTC callback without blocking the WebRTC/JNI thread.

        The callback can run while a Python command still owns the dispatch
        lock and is waiting for the native method to return. Taking that lock
        here would deadlock the command; the worker takes it after the command
        has unwound.
        """
        if not isinstance(event, str) or not isinstance(session_id, str):
            return
        if not isinstance(data, str):
            return
        queue_ref = getattr(self, "_native_webrtc_events", None)
        if queue_ref is None or self._shutdown.is_set():
            return
        try:
            queue_ref.put_nowait((event, session_id, data))
        except Exception:
            pass

    def _native_webrtc_event_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                with self._dispatch_lock:
                    self._expire_native_answer_exchanges()
                    self._maintain_native_controls()
            except Exception:
                pass
            try:
                item = self._native_webrtc_events.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                return
            try:
                self._handle_native_webrtc_event(*item)
            except Exception:
                pass

    def _handle_native_webrtc_event(
        self, event: str, session_id: str, data: str = ""
    ) -> None:
        with self._dispatch_lock:
            if event == "overflow":
                runtime = getattr(self, "_connection_runtime", None)
                if runtime is not None:
                    runtime.quarantine()
                for current in tuple(self._native_webrtc_live):
                    if runtime is None or not self._shared_native_session(current):
                        self.native_webrtc_close(current)
                return
            # Resolve at consumption time: a queued event from a released
            # physical peer must not target a later reuse of its public ID.
            session_id = self._native_resources.resolve(session_id)
            if session_id is None or (session_id not in self._native_webrtc_live and event != "closed"):
                return
            managed = self._shared_native_session(session_id)
            if event == "ice" or event in {"open", "closed"}:
                connection_diagnostics.record(self, "transport_state", {
                    "setup_id": session_id, "state": data if event == "ice" else event,
                    "command": "native_webrtc_event", "component": "ice" if event == "ice" else "bridge",
                })
            elif event == "channel" and data.startswith("mesh-reticulum:"):
                connection_diagnostics.record(self, "transport_state", {
                    "setup_id": session_id, "state": data.partition(":")[2],
                    "command": "native_webrtc_event", "component": "data_channel",
                })
            if event == "open":
                if session_id not in self._native_webrtc_live:
                    return
                if getattr(self, "_connection_policy", "legacy") == "shared-native":
                    # Pending onboarding retains its control channel only.
                    # The reducer admits messaging after verified discovery or CHECKING.
                    return
                self._native_webrtc_descriptions.get(session_id, {}).pop("answer_wait_until", None)
                try:
                    attached = self.webrtc_attach_native(session_id)
                except Exception:
                    return
                self.emit(
                    {
                        "type": "event",
                        "event": "webrtc_native_open",
                        "session_id": session_id,
                        "bridge_id": attached["bridge_id"],
                    }
                )
            elif event == "message":
                bridge_id = self._native_webrtc_sessions.get(session_id)
                if bridge_id is not None and self._native_bridge_attached(session_id):
                    try:
                        self.webrtc_packet(bridge_id, data)
                    except Exception:
                        pass
                elif managed:
                    self._retain_native_startup_packet(session_id, data)
            elif event == "control":
                if session_id not in self._native_webrtc_live or len(data) > 90_000:
                    return
                label, _, encoded = data.partition(":")
                if label not in {"mesh-onboarding", "meshchat-reconnect"}:
                    return
                try:
                    text = base64.b64decode(encoded, validate=True).decode("utf-8")
                except Exception:
                    return
                if len(text) <= 65_536:
                    self._native_control_receive(session_id, label, text)
                    if label == "meshchat-reconnect":
                        return
                    self.emit(
                        {
                            "type": "event",
                            "event": "webrtc_control",
                            "session_id": session_id,
                            "label": label,
                            "data": text,
                        }
                    )
            elif event == "closed":
                self._native_resources.confirm_closed(session_id, self._native_resources.physical(session_id))
                self._release_native_session(session_id)
                self.webrtc_detach_native(session_id)
                self.emit(
                    {
                        "type": "event",
                        "event": "webrtc_native_state",
                        "session_id": session_id,
                        "state": "closed",
                    }
                )
            elif event in {"ice", "channel", "signaling", "gathering"}:
                if not managed and event == "ice" and (data == "closed" or (
                    data == "failed" and not self._native_answer_exchange_pending(session_id)
                )):
                    self.native_webrtc_close(session_id)
                if event == "channel":
                    label, _, state = data.partition(":")
                    if session_id in self._native_webrtc_live and label in {"mesh-onboarding", "meshchat-reconnect"} and state == "open":
                        self._native_webrtc_controls.setdefault(session_id, {})["label"] = label
                        self._native_control_next = 0
                    if not managed and label == "mesh-reticulum" and state in {"closing", "closed"}:
                        self.native_webrtc_close(session_id)
                    if label == "mesh-onboarding" and state == "open":
                        self.emit(
                            {
                                "type": "event",
                                "event": "webrtc_control_open",
                                "session_id": session_id,
                                "label": label,
                            }
                        )
                self.emit(
                    {
                        "type": "event",
                        "event": "webrtc_native_state",
                        "session_id": session_id,
                        "state": event,
                        "detail": data[:160],
                    }
                )

    def _shared_native_session(self, session_id: str) -> bool:
        with self._native_webrtc_lock:
            return (getattr(self, "_connection_policy", "legacy") == "shared-native"
                    and session_id in self._native_webrtc_profile_sessions.values())

    def _native_answer_exchange_pending(self, session_id: str) -> bool:
        with self._native_webrtc_lock:
            deadline = self._native_webrtc_descriptions.get(session_id, {}).get("answer_wait_until", 0)
            return (session_id in self._native_webrtc_live
                    and session_id not in self._native_webrtc_sessions
                    and time.monotonic() < deadline)

    def _expire_native_answer_exchanges(self) -> None:
        # Run in the native event worker, even if the WebView is suspended.
        # Preserving a pending answer must not leave abandoned peers alive.
        now = time.monotonic()
        with self._native_webrtc_lock:
            expired = [session_id for session_id, description in self._native_webrtc_descriptions.items()
                       if session_id in self._native_webrtc_live
                       and session_id not in self._native_webrtc_sessions
                       and description.get("answer_wait_until", float("inf")) <= now]
        for session_id in expired:
            self.native_webrtc_close(session_id)

    def native_reconnect_session(self, profile_id: str) -> str | None:
        with self._native_webrtc_lock:
            current = self._native_webrtc_profile_sessions.get(profile_id)
            if current:
                return current
            # A manually paired native transport remains usable without a
            # mailbox. Reconnect must reuse it after the contact is approved.
            for session_id in self._native_webrtc_peers:
                if (session_id in self._native_webrtc_live
                        and self._native_webrtc_controls.get(session_id, {}).get("profile_id") == profile_id):
                    return session_id
            return None

    def close_native_reconnect_session(self, profile_id: str) -> None:
        session_id = self.native_reconnect_session(profile_id)
        if session_id is not None:
            self.native_webrtc_close(session_id)

    def retire_unmanaged_native_connections(self, profile_ids) -> None:
        """Explicit Stop also covers verified manual peers awaiting transfer."""
        with self._native_webrtc_lock:
            sessions = [session for session, control in self._native_webrtc_controls.items()
                        if control.get("profile_id") in profile_ids
                        and session in self._native_webrtc_peers
                        and session in self._native_webrtc_live
                        and not self._shared_native_session(session)]
        failure = None
        for session in sessions:
            try:
                self.native_webrtc_close(session)
            except Exception as error:
                # Each close removes routing in finally, even when JNI fails.
                failure = error
        if failure is not None:
            raise failure

    def _claim_native_session(self, session_id: str, profile_id: Any, *, background: bool,
                              runtime_owned: bool = False) -> bool:
        relay_only = False
        with self._dispatch_lock:
            if self._shutdown.is_set():
                raise NativeUnavailable("Native WebRTC is shutting down")
            if profile_id is not None:
                shared = getattr(self, "_connection_policy", "legacy") == "shared-native"
                if shared != runtime_owned:
                    raise NativeUnavailable("Native reconnect is owned by another policy")
                profile = self._reconnect_profile(profile_id)
                public = self._reconnect_profile_public(profile)
                if not public["effective"]["ready"] or not profile.get("active"):
                    raise ContactNotApproved("Reconnect profile is not active and ready")
                relay_only = not profile.get("allow_direct_ip_disclosure")
                in_background = self._workspace_lifecycle_state().get("state") in {
                    "background", "background_available", "suspended",
                }
                if ((not runtime_owned and background != in_background)
                        or (in_background and not self._background_availability_enabled())):
                    raise NativeUnavailable("Native reconnect ownership changed")
            with self._native_webrtc_lock:
                if session_id in self._native_webrtc_live or session_id in self._native_webrtc_creating:
                    raise NativeUnavailable("Native WebRTC session already exists")
                if profile_id is not None:
                    if self.native_reconnect_session(profile_id):
                        raise NativeUnavailable("Native reconnect profile already has a peer")
                self._native_resources.reserve(session_id)
                if profile_id is not None:
                    self._native_webrtc_profile_sessions[profile_id] = session_id
                self._native_webrtc_live.add(session_id)
                self._native_webrtc_creating.add(session_id)
        return relay_only

    def _release_native_session(self, session_id: str) -> None:
        with self._native_webrtc_lock:
            self._native_webrtc_live.discard(session_id)
            self._native_startup_packets.discard(self._native_resources.physical(session_id))
            if session_id in self._native_webrtc_creating or not self._native_resources.closed(session_id):
                return
            self._native_resources.release(session_id, self._native_resources.physical(session_id))
            self._native_webrtc_descriptions.pop(session_id, None)
            self._native_webrtc_peers.pop(session_id, None)
            self._native_webrtc_controls.pop(session_id, None)
            for profile_id, current in list(self._native_webrtc_profile_sessions.items()):
                if current == session_id:
                    del self._native_webrtc_profile_sessions[profile_id]

    def _native_sdp_result(self, session_id: str, raw: str) -> dict[str, Any]:
        result = json.loads(raw)
        if not result.get("ok"):
            raise NativeUnavailable(str(result.get("error", "native_webrtc_sdp_failed")))
        if session_id not in self._native_webrtc_live or self._shutdown.is_set():
            raise NativeUnavailable("Native WebRTC creation was cancelled")
        # The signed document must bind the fingerprint in the actual SDP.
        # Normalize here as well as in Kotlin so bridge metadata cannot drift.
        fingerprints = [line[len("a=fingerprint:"):] for line in result.get("sdp", "").splitlines()
                        if line.startswith("a=fingerprint:")]
        if len(fingerprints) != 1:
            raise ValidationError("Native WebRTC SDP fingerprint is invalid")
        result["fingerprint"] = _fingerprint(fingerprints[0])
        self._native_webrtc_descriptions.setdefault(session_id, {})["local"] = result["sdp"]
        return result

    def native_webrtc_offer(
        self, session_id: Any, ice: Any, channels: Any, profile_id: Any = None, *, background: bool = False,
        runtime_owned: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(session_id, str) or not 8 <= len(session_id) <= 128:
            raise ValidationError("Native WebRTC session is invalid")
        if not isinstance(ice, dict) or not isinstance(channels, list):
            raise ValidationError("Native WebRTC configuration is invalid")
        if self._claim_native_session(session_id, profile_id, background=background, runtime_owned=runtime_owned):
            ice = {**ice, "iceTransportPolicy": "relay"}
        self._native_webrtc_descriptions[session_id] = {"ice_policy": ice.get("iceTransportPolicy", "all")}
        try:
            return self._native_sdp_result(session_id, self._native_webrtc_host().createOffer(
                self._native_resources.require(session_id),
                json.dumps(ice, separators=(",", ":")),
                json.dumps(channels, separators=(",", ":")),
            ))
        except Exception:
            self.native_webrtc_close(session_id)
            raise
        finally:
            with self._native_webrtc_lock:
                self._native_webrtc_creating.discard(session_id)
                if session_id not in self._native_webrtc_live:
                    self._release_native_session(session_id)

    def native_webrtc_accept(
        self, session_id: Any, offer_sdp: Any, ice: Any, channels: Any, profile_id: Any = None, *, background: bool = False,
        runtime_owned: bool = False,
    ) -> dict[str, Any]:
        if (not isinstance(session_id, str) or not 8 <= len(session_id) <= 128
                or not isinstance(offer_sdp, str)):
            raise ValidationError("Native WebRTC session is invalid")
        if not isinstance(ice, dict) or not isinstance(channels, list):
            raise ValidationError("Native WebRTC configuration is invalid")
        if self._claim_native_session(session_id, profile_id, background=background, runtime_owned=runtime_owned):
            ice = {**ice, "iceTransportPolicy": "relay"}
        self._native_webrtc_descriptions[session_id] = {
            "remote_offer": offer_sdp, "ice_policy": ice.get("iceTransportPolicy", "all")}
        if profile_id is None and any(
            isinstance(channel, dict) and channel.get("label") == "mesh-onboarding" for channel in channels
        ):
            # The offerer cannot send checks to this peer until the person
            # returns its signed answer. An early ICE failure must not destroy
            # the session before binding/signing or during that manual wait.
            # Match the browser answerer's bounded exchange window; established
            # channels and automatic reconnect retain immediate failure cleanup.
            self._native_webrtc_descriptions[session_id]["answer_wait_until"] = (
                time.monotonic() + self._native_answer_exchange_timeout
            )
        try:
            return self._native_sdp_result(session_id, self._native_webrtc_host().acceptOffer(
                self._native_resources.require(session_id),
                offer_sdp,
                json.dumps(ice, separators=(",", ":")),
                json.dumps(channels, separators=(",", ":")),
            ))
        except Exception:
            self.native_webrtc_close(session_id)
            raise
        finally:
            with self._native_webrtc_lock:
                self._native_webrtc_creating.discard(session_id)
                if session_id not in self._native_webrtc_live:
                    self._release_native_session(session_id)

    def native_webrtc_apply_answer(self, session_id: Any, answer_sdp: Any) -> dict[str, Any]:
        if not isinstance(session_id, str) or not isinstance(answer_sdp, str):
            raise ValidationError("Native WebRTC answer is invalid")
        from .native_webrtc_control import normalized_sdp
        with self._native_webrtc_lock:
            physical = self._native_resources.require(session_id)
            description = self._native_webrtc_descriptions.get(session_id, {})
            bound = description.get("bound_remote_sdp")
            if bound and bound != normalized_sdp(answer_sdp):
                raise IdentityMismatch("Answer does not match the verified native binding")
        result = json.loads(
            self._native_webrtc_host().applyAnswer(physical, answer_sdp)
        )
        if not result.get("ok"):
            raise NativeUnavailable(str(result.get("error", "native_webrtc_apply_failed")))
        with self._native_webrtc_lock:
            if (not self._native_resources.current(session_id, physical)
                    or session_id not in self._native_webrtc_live):
                raise NativeUnavailable("Native answer completed after its resource was retired")
            self._native_webrtc_descriptions.setdefault(session_id, {})["remote_answer"] = answer_sdp
        return result

    def native_webrtc_control(
        self, session_id: Any, label: Any, text: Any
    ) -> dict[str, Any]:
        if (
            not isinstance(session_id, str)
            or label not in {"mesh-onboarding", "meshchat-reconnect"}
            or not isinstance(text, str)
            or not 1 <= len(text) <= 65_536
        ):
            raise ValidationError("Native WebRTC control message is invalid")
        physical = self._native_resources.require(session_id)
        accepted = bool(self._native_webrtc_host().sendControl(physical, label, text))
        accepted = (accepted and session_id in self._native_webrtc_live
                    and self._native_resources.current(session_id, physical))
        return {"accepted": accepted}

    def native_webrtc_close(self, session_id: Any, *, expected_physical: str | None = None) -> dict[str, Any]:
        if not isinstance(session_id, str):
            raise ValidationError("Native WebRTC session is invalid")
        with self._native_webrtc_lock:
            physical = self._native_resources.physical(session_id)
            if expected_physical is not None and physical != expected_physical:
                return {"state": "closed"}
            was_live = session_id in self._native_webrtc_live
            self._native_webrtc_live.discard(session_id)
            self._native_startup_packets.discard(physical)
        if was_live:
            connection_diagnostics.record(self, "transport_state", {
                "setup_id": session_id, "state": "closed", "command": "native_webrtc_close", "component": "bridge",
            })
        try:
            if physical is not None:
                self._native_webrtc_host().close(physical)
                self._native_resources.confirm_closed(session_id, physical)
        finally:
            with self._dispatch_lock, self._native_webrtc_lock:
                if self._native_resources.current(session_id, physical):
                    self._release_native_session(session_id)
                    self.webrtc_detach_native(session_id)
        return {"state": "closed"}

    def native_webrtc_stats(self, session_id: Any) -> dict[str, Any]:
        if not isinstance(session_id, str):
            raise ValidationError("Native WebRTC session is invalid")
        physical = self._native_resources.require(session_id)
        result = json.loads(self._native_webrtc_host().stats(physical))
        if not self._native_resources.current(session_id, physical):
            raise NativeUnavailable("Native inspection completed after its resource was retired")
        if not result.get("ok"):
            raise NativeUnavailable(str(result.get("error", "native_webrtc_stats_failed")))
        stats = result.get("result", {})
        if isinstance(stats, dict):
            stats["attached"] = (
                self._native_bridge_attached(session_id)
                and stats.get("data_channel_state") == "open"
                and stats.get("ice_connection_state") not in {"failed", "closed"}
            )
            stats["session_id"] = session_id
        return stats



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
        if message["state"] in DIRECT_RETRY_STATES:
            self._queue_direct_retry(message["id"])
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
        self._bound_call_signal_expiry(message)
        return message

    @staticmethod
    def _bound_call_signal_expiry(message: dict[str, Any]) -> None:
        """A queued SDP/control document cannot outlive its signed deadline.

        Apply at creation and on retry/recovery for records saved by older
        versions with the seven-day chat delivery window. These are local
        outbound records; this only shortens retention, never authenticates
        an incoming document or extends its validity.
        """
        if message.get("kind") != MessageKind.CALL_SIGNAL.value:
            return
        try:
            expiry = json.loads(message["text"])["expires_at"]
            if type(expiry) is not int or expiry <= 0:
                raise ValueError("Invalid call deadline")
        except (ValueError, TypeError, KeyError):
            expiry = 0
        message["expires_at"] = min(message["expires_at"], expiry)

    def _queue_direct_retry(self, message_id: str) -> None:
        with self._retry_queue_lock:
            self._direct_retry_ids[message_id] = None

    def _drop_direct_retry(self, message_id: str) -> None:
        with self._retry_queue_lock:
            self._direct_retry_ids.pop(message_id, None)

    def _direct_retry_snapshot(self) -> list[str]:
        with self._retry_queue_lock:
            return list(self._direct_retry_ids)

    def _queue_group_retry(self, delivery_id: str) -> None:
        with self._retry_queue_lock:
            self._group_retry_ids[delivery_id] = None
            self._group_retry_missing.discard(delivery_id)

    def _drop_group_retry(self, delivery_id: str) -> None:
        with self._retry_queue_lock:
            self._group_retry_ids.pop(delivery_id, None)
            self._group_retry_missing.discard(delivery_id)

    def _group_retry_snapshot(self) -> list[str]:
        with self._retry_queue_lock:
            return list(self._group_retry_ids)

    def _attempt(self, message_id: str) -> None:
        message = self.store.get("message", message_id)
        if not message or message["direction"] != "outbound":
            self._drop_direct_retry(message_id)
            return
        # Only durable retry states may create a new native LXMF handoff. An
        # in-flight packet (or one already accepted by an endpoint/propagation
        # node) remains pending until its callback, app receipt, expiry, or
        # explicit recovery after restart changes it back to a retry state.
        if message["state"] not in DIRECT_RETRY_STATES:
            self._drop_direct_retry(message_id)
            return
        self._queue_direct_retry(message_id)
        self._bound_call_signal_expiry(message)
        if message["expires_at"] <= time.time():
            if (
                message.get("kind") == MessageKind.REACTION.value
                or message.get("reaction_receipt") is True
            ):
                self.store.delete("message", message_id)
                self._drop_direct_retry(message_id)
                return
            message["state"] = DeliveryState.EXPIRED.value
            self.store.put("message", message_id, message)
            self._drop_direct_retry(message_id)
            return
        contact = self._require_contact(message["contact_id"])
        kind = MessageKind(message["kind"])
        allowed = contact["trust"] in {TrustState.APPROVED.value, TrustState.VERIFIED.value}
        if kind == MessageKind.CONTACT_REQUEST:
            allowed = contact["trust"] == TrustState.AWAITING_CONSENT.value
        elif kind == MessageKind.CONTACT_DECLINE:
            allowed = contact["trust"] == TrustState.PENDING_REQUEST.value
        if not allowed:
            self._drop_direct_retry(message_id)
            return
        if self.network is None:
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
            latest = self.store.get("message", message_id)
            if latest is not None and latest.get("state") in DIRECT_RETRY_STATES:
                self._queue_direct_retry(message_id)
            else:
                self._drop_direct_retry(message_id)
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
                # SENDING can have removed this ID before the native handoff
                # raised. Persisting a retry state must restore its work item.
                self._queue_direct_retry(message_id)
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
                self._queue_direct_retry(message_id)

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
        if message.get("kind") == MessageKind.CALL_SIGNAL.value:
            self._bound_call_signal_expiry(message)
            if message["expires_at"] <= time.time():
                message["state"] = DeliveryState.EXPIRED.value
                self.store.put("message", logical_id, message)
                self._drop_direct_retry(logical_id)
                return
        if message["state"] == DeliveryState.DELIVERED.value:
            if (
                message.get("kind") == MessageKind.REACTION.value
                or message.get("reaction_receipt") is True
            ):
                self.store.delete("message", logical_id)
            self._drop_direct_retry(logical_id)
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
            self._drop_direct_retry(logical_id)
        else:
            self.store.put("message", logical_id, message)
            if state.value in DIRECT_RETRY_STATES:
                self._queue_direct_retry(logical_id)
            else:
                self._drop_direct_retry(logical_id)
        if message.get("kind") == MessageKind.CALL_SIGNAL.value:
            connection_diagnostics.call_signal(self, "call_outbound", message.get("text"), state.value)
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
            elif app.kind == MessageKind.CALL_SIGNAL:
                self._receive_call_signal(contact, app.text)
            elif app.kind == MessageKind.WORKSPACE_INVITE:
                self._receive_workspace_contact_invite(contact, app)
            elif app.kind == MessageKind.CHAT:
                self._receive_chat(contact, native, app)
        except Exception:
            # Malformed, unauthenticated, unknown and mismatched messages fail
            # closed without a reply that could be abused as an oracle.
            return

    def _receive_call_signal(self, contact: dict[str, Any], document: str | None) -> None:
        if not isinstance(document, str) or not document:
            return
        if self._identity is None:
            return
        try:
            result = self.calls.receive(self._identity, contact, document)
        except Exception as exc:
            connection_diagnostics.call_signal(self, "call_rejected", document, "failed",
                                               error_code=exc.code if isinstance(exc, MeshChatError) else "internal_error")
            raise
        if result is not None:
            connection_diagnostics.call_signal(self, "call_inbound", document, result["state"])
            self._changed()

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

    def dismiss_workspace_invitation_prompt(self, prompt_id: Any) -> dict[str, Any]:
        if not isinstance(prompt_id, str):
            raise ValidationError("Workspace invitation prompt ID is invalid")
        record = self.store.get("workspace_contact_invite", prompt_id)
        if record is None:
            raise ValidationError("Workspace invitation prompt is unavailable")
        record["state"] = "dismissed"
        record["dismissed_at"] = time.time()
        self.store.put("workspace_contact_invite", prompt_id, record)
        self._changed()
        return {"dismissed": True}

    def _pending_workspace_invitation_prompt(self, prompt_id: Any) -> dict[str, Any]:
        if not isinstance(prompt_id, str):
            raise ValidationError("Workspace invitation prompt ID is invalid")
        record = self.store.get("workspace_contact_invite", prompt_id)
        if record is None or record.get("state") != "pending":
            raise ValidationError("Workspace invitation prompt is unavailable")
        if float(record.get("expires_at", 0)) <= time.time():
            raise ValidationError("Workspace invitation has expired")
        return record

    def preview_workspace_invitation_prompt(self, prompt_id: Any) -> dict[str, Any]:
        record = self._pending_workspace_invitation_prompt(prompt_id)
        return self.preview_workspace_invitation(record["invitation"])

    def submit_workspace_invitation_prompt(
        self, prompt_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        record = self._pending_workspace_invitation_prompt(prompt_id)
        return self.submit_workspace_join(record["invitation"], operation_id)

    def _receive_workspace_contact_invite(self, contact: dict[str, Any], app: Any) -> None:
        if contact.get("trust") not in {
            TrustState.APPROVED.value,
            TrustState.VERIFIED.value,
        }:
            return
        invitation_raw = getattr(app, "invitation", None)
        if not isinstance(invitation_raw, str) or not invitation_raw:
            return
        try:
            invitation = verify_workspace_invitation(invitation_raw)
        except MeshChatError:
            return
        prompt_id = self.store.opaque_id(
            "workspace-contact-invite", invitation.nonce.hex()
        )
        existing = self.store.get("workspace_contact_invite", prompt_id)
        # A dismissed prompt is a tombstone for this signed invitation nonce.
        # Retain it until expiry so LXMF retries cannot recreate the banner.
        if existing is not None:
            self._ensure_receipt(contact, app.logical_id, app.conversation_id)
            return
        now = time.time()
        for stale in self.store.list("workspace_contact_invite"):
            if float(stale.get("expires_at", 0)) <= now:
                self.store.delete("workspace_contact_invite", stale["id"])
        if len([
            item
            for item in self.store.list("workspace_contact_invite")
            if item.get("state") == "pending"
        ]) >= 32:
            return
        preview = invitation.preview()
        self.store.put(
            "workspace_contact_invite",
            prompt_id,
            {
                "id": prompt_id,
                "workspace_id": invitation.workspace_id,
                "workspace_name": preview["name"],
                "description": preview["description"],
                "owner_fingerprint": preview["owner_fingerprint"],
                "member_count": preview["member_count"],
                "retention_days": preview["retention_days"],
                "expires_at": invitation.expires_at,
                "invitation": invitation_raw,
                "contact_id": contact["id"],
                "contact_display_name": contact["display_name"],
                "received_at": now,
                "state": "pending",
            },
        )
        self._ensure_receipt(contact, app.logical_id, app.conversation_id)
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
        retry_ids: list[str] = []
        for message in self.store.list("message"):
            if message["direction"] != "outbound":
                continue
            self._bound_call_signal_expiry(message)
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
            if message["state"] in DIRECT_RETRY_STATES:
                retry_ids.append(message["id"])
        with self._retry_queue_lock:
            self._direct_retry_ids.update({message_id: None for message_id in retry_ids})
        self._recover_group_outbox()

    def _retry_loop(self) -> None:
        while not self._shutdown.wait(3):
            self._retry_once()

    def _retry_once(self) -> None:
        if not self.network:
            return
        # Do not own the command/callback lock for an entire durable backlog.
        # A signed-route probe has a small bounded wait of its own, and
        # multiplying that wait by many historical messages can exceed the
        # desktop IPC deadline even without a transport fault. Lock one record
        # at a time and yield between records so a waiting user command or
        # deferred native callback can make progress.
        for message_id in self._direct_retry_snapshot():
            message = self.store.get("message", message_id)
            if (
                message is None
                or message["direction"] != "outbound"
                or message["state"] not in {
                    DeliveryState.QUEUED.value,
                    DeliveryState.WAITING_FOR_KEYS.value,
                }
            ):
                self._drop_direct_retry(message_id)
                continue
            with self._dispatch_lock:
                try:
                    self._attempt(message_id)
                except Exception:
                    # A single upstream transport failure must not kill the
                    # only retry worker.
                    pass
            if self._shutdown.wait(0.05):
                return
        with self._dispatch_lock:
            try:
                self._expire_group_invitation_state(time.time())
            except Exception:
                pass
        for delivery_id in self._group_retry_snapshot():
            delivery = self.store.get("group_delivery", delivery_id)
            if delivery is None:
                with self._retry_queue_lock:
                    if delivery_id in self._group_retry_missing:
                        self._group_retry_ids.pop(delivery_id, None)
                        self._group_retry_missing.discard(delivery_id)
                    else:
                        # The creator may still be committing this record.
                        self._group_retry_missing.add(delivery_id)
                continue
            with self._retry_queue_lock:
                self._group_retry_missing.discard(delivery_id)
            if delivery.get("state") in FINAL_DELIVERY_STATES:
                self._drop_group_retry(delivery_id)
                continue
            with self._dispatch_lock:
                try:
                    self._retry_group_delivery_if_due(delivery_id)
                except Exception:
                    pass
            if self._shutdown.wait(0.05):
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

    def _adopt_i2p_access_point(self, b32: str) -> None:
        peers = [b32, *[item for item in self.settings.i2p_peers if item != b32]][:4]
        settings = NetworkSettings.from_dict(self.settings.to_dict())
        settings.i2p_enabled = True
        settings.i2p_peers = peers
        self.settings = settings
        self.store.put("settings", "network", settings.to_dict())
        write_config(self.profile_dir / "reticulum", settings)
        self._connection_settings_dirty = True

    def i2p_status(self) -> dict[str, Any]:
        router = self._i2p_router.status()
        if self.network is None:
            value = {
                "enabled": self.settings.i2p_enabled,
                "connectable": self.settings.i2p_connectable,
                "peer_count": len(self.settings.i2p_peers),
                "interface_count": 0,
                "online_count": 0,
                "online": False,
                "state": "unavailable",
                "b32": None,
            }
        else:
            value = self.network.i2p_status()
        value["managed"] = self.settings.i2p_managed
        value["router"] = router
        return value

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
            "contact_invitations": self.contact_invitations(),
            "messages": visible_messages,
            "workspace_invitation_prompts": [
                {
                    key: record[key]
                    for key in (
                        "id", "workspace_id", "workspace_name", "description",
                        "owner_fingerprint", "member_count", "retention_days",
                        "expires_at", "invitation", "contact_id",
                        "contact_display_name", "received_at", "state",
                    )
                }
                for record in sorted(
                    self.store.list("workspace_contact_invite"),
                    key=lambda item: float(item.get("received_at", 0)),
                    reverse=True,
                )
                if record.get("state") == "pending"
                and float(record.get("expires_at", 0)) > time.time()
            ],
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
            "calls": self.calls.active(),
            "background_availability": self.background_availability_status(),
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
        if "i2p_enabled" not in value:
            settings.i2p_enabled = self.settings.i2p_enabled
        if "i2p_connectable" not in value:
            settings.i2p_connectable = self.settings.i2p_connectable
        if "i2p_managed" not in value:
            settings.i2p_managed = self.settings.i2p_managed
        if "i2p_peers" not in value:
            settings.i2p_peers = list(self.settings.i2p_peers)
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

    def _check_connection_command_owner(self, command, payload):
        if getattr(self, "_connection_policy", "legacy") != "shared-native":
            return
        from .connection.commands import owner_only
        if owner_only(command, payload):
            raise NativeUnavailable("Connection operation is owned by the service")
        if (command in {"native_webrtc_apply_answer", "native_webrtc_control"}
                and isinstance(payload, dict) and isinstance(payload.get("session_id"), str)
                and self._shared_native_session(payload["session_id"])):
            raise NativeUnavailable("Native reconnect is owned by the service")

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
            self._check_connection_command_owner(command, request.get("payload", {}))
            cache_response = command not in self.UNCACHED_COMMANDS
            if getattr(self, "_connection_policy", "legacy") == "shared-native":
                from .connection.commands import TRANSIENT_OPERATIONS
                cache_response = cache_response and command not in TRANSIENT_OPERATIONS
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
        self._check_connection_command_owner(command, value)
        if command == "link_preview":
            body = _payload(value, allowed={"provider", "identifier"}, required={"provider", "identifier"})
            return self._link_previews.get(body["provider"], body["identifier"])
        if command == "receive_contact_invitation":
            body = _payload(value, allowed={"document", "peer_destination", "workspace_document"},
                            required={"document", "peer_destination"})
            return self.receive_contact_invitation(**body)
        if command == "decide_contact_invitation":
            body = _payload(value, allowed={"invitation_id", "accept"}, required={"invitation_id", "accept"})
            return self.decide_contact_invitation(**body)
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
        if command == "i2p_status":
            _payload(value, allowed=set())
            return self.i2p_status()
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
                    "external_host", "external_port", "i2p_access_point", "i2p_label",
                    "peer_destination",
                }
            )
            result = dict(self.invitation(
                body.get("remote_profile_id"), body.get("connection_mode"),
                body.get("manual_setup_id"), body.get("external_host"),
                body.get("external_port"), body.get("i2p_access_point"),
                body.get("i2p_label"),
            ))
            capabilities = self._invitation_capabilities(body.get("peer_destination"))
            if capabilities:
                result["reconnect_capabilities"] = capabilities
            return result
        if command in {"preview_invitation", "accept_invitation"}:
            body = _payload(
                value, allowed={"invitation", "i2p_consent"}, required={"invitation"}
            )
            if not isinstance(body["invitation"], str):
                raise ValidationError("Invitation must be text")
            if command == "preview_invitation":
                return self.preview_invitation(body["invitation"])
            accepted = dict(self.accept_invitation(
                body["invitation"], i2p_consent=body.get("i2p_consent") is True
            ))
            contact = self.store.get("contact", str(accepted.get("id", "")))
            capabilities = self._contact_capabilities(contact) if contact else None
            if capabilities:
                accepted["reconnect_capabilities"] = capabilities
            return accepted
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
        if command == "start_call":
            body = _payload(
                value,
                allowed={"contact_id", "media", "sdp", "dtls_fingerprint"},
                required={"contact_id", "media", "sdp", "dtls_fingerprint"},
            )
            return self.start_call(
                body["contact_id"], body["media"], body["sdp"], body["dtls_fingerprint"]
            )
        if command == "answer_call":
            body = _payload(
                value,
                allowed={"call_id", "sdp", "dtls_fingerprint"},
                required={"call_id", "sdp", "dtls_fingerprint"},
            )
            return self.answer_call(
                body["call_id"], body["sdp"], body["dtls_fingerprint"]
            )
        if command == "add_call_candidate":
            body = _payload(
                value, allowed={"call_id", "candidate"}, required={"call_id", "candidate"}
            )
            return self.add_call_candidate(body["call_id"], body["candidate"])
        if command == "end_call":
            body = _payload(
                value, allowed={"call_id", "reason"}, required={"call_id"}
            )
            return self.end_call(body["call_id"], body.get("reason", "completed"))
        if command == "call_media":
            body = _payload(value, allowed={"call_id"}, required={"call_id"})
            return self.call_media(body["call_id"])
        if command == "native_ringing_calls":
            _payload(value, allowed=set())
            return self.native_ringing_calls()
        if command == "restart_call":
            body = _payload(
                value,
                allowed={"call_id", "sdp", "dtls_fingerprint"},
                required={"call_id", "sdp", "dtls_fingerprint"},
            )
            return self.restart_call(body["call_id"], body["sdp"], body["dtls_fingerprint"])
        if command == "answer_call_restart":
            body = _payload(
                value,
                allowed={"call_id", "sdp", "dtls_fingerprint"},
                required={"call_id", "sdp", "dtls_fingerprint"},
            )
            return self.answer_call_restart(
                body["call_id"], body["sdp"], body["dtls_fingerprint"]
            )
        if command == "call_settings":
            _payload(value, allowed=set())
            return self.call_settings()
        if command == "update_call_settings":
            body = _payload(
                value,
                allowed={
                    "stun_urls", "turn_url", "turn_username", "turn_credential",
                    "turn_broker_url", "turn_broker_consent", "signal_mailbox_url", "relay_only",
                    "store_call_signaling",
                },
                required={"stun_urls", "relay_only"},
            )
            if "store_call_signaling" not in body:
                body["store_call_signaling"] = self._call_settings.store_call_signaling
            return self.update_call_settings(body)
        if command == "call_ice_servers":
            _payload(value, allowed=set())
            return self.call_ice_servers()
        if command == "signal_publish":
            body = _payload(
                value,
                allowed={"document", "role", "session_id", "mailbox_token"},
                required={"document", "role"},
            )
            return self.signal_publish(
                body["document"],
                body["role"],
                body.get("session_id"),
                body.get("mailbox_token"),
            )
        if command == "signal_fetch":
            body = _payload(
                value,
                allowed={"session_id", "role", "mailbox_token"},
                required={"session_id", "role"},
            )
            return self.signal_fetch(
                body["session_id"], body["role"], body.get("mailbox_token")
            )
        if command == "reconnect_profiles":
            _payload(value, allowed=set())
            return self.reconnect_profiles()
        if command == "reconnect_consent_set":
            body = _payload(
                value,
                allowed={
                    "contact_id",
                    "auto_reconnect",
                    "allow_direct_ip_disclosure",
                    "relay_consent_scope",
                    "rotate_token",
                },
                required={"contact_id", "auto_reconnect", "allow_direct_ip_disclosure"},
            )
            return self.reconnect_consent_set(
                body["contact_id"],
                body["auto_reconnect"],
                body["allow_direct_ip_disclosure"],
                body.get("relay_consent_scope", "contact"),
                body.get("rotate_token", False),
            )
        if command == "reconnect_capabilities_create":
            body = _payload(
                value,
                allowed={"contact_id", "rotate_token"},
                required={"contact_id"},
            )
            return self.reconnect_capabilities_create(
                body["contact_id"], body.get("rotate_token", True)
            )
        if command == "reconnect_capabilities_store":
            body = _payload(
                value, allowed={"document", "expected_contact_id", "expected_peer_destination"}, required={"document"}
            )
            return self.reconnect_capabilities_store(
                body["document"], body.get("expected_contact_id"), body.get("expected_peer_destination")
            )
        if command == "reconnect_capabilities_get":
            body = _payload(value, allowed={"contact_id"}, required={"contact_id"})
            return self.reconnect_capabilities_get(body["contact_id"])
        if command == "reconnect_replay_check":
            body = _payload(value, allowed={"key", "ttl"}, required={"key"})
            return self.reconnect_replay_check(body["key"], body.get("ttl", 600))
        if command == "reconnect_status":
            body = _payload(
                value, allowed={"state", "detail", "attempt_id"}, required=set()
            )
            return self.reconnect_status(
                body.get("state"), body.get("detail"), body.get("attempt_id")
            )
        if command == "reconnect_start":
            body = _payload(value, allowed={"contact_id"}, required=set())
            return self.reconnect_start(body.get("contact_id"))
        if command == "reconnect_stop":
            body = _payload(value, allowed={"contact_id"}, required=set())
            return self.reconnect_stop(body.get("contact_id"))
        if command == "reconnect_request_create":
            body = _payload(
                value,
                allowed={"contact_id", "attempt_id", "nonce"},
                required={"contact_id", "attempt_id"},
            )
            return self.reconnect_request_create(
                body["contact_id"], body["attempt_id"], body.get("nonce")
            )
        if command == "reconnect_offer_create":
            body = _payload(
                value,
                allowed={"contact_id", "request_document", "sdp", "dtls_fingerprint"},
                required={"contact_id", "request_document", "sdp", "dtls_fingerprint"},
            )
            return self.reconnect_offer_create(
                body["contact_id"],
                body["request_document"],
                body["sdp"],
                body["dtls_fingerprint"],
            )
        if command == "reconnect_answer_create":
            body = _payload(
                value,
                allowed={"contact_id", "offer_document", "sdp", "dtls_fingerprint"},
                required={"contact_id", "offer_document", "sdp", "dtls_fingerprint"},
            )
            return self.reconnect_answer_create(
                body["contact_id"],
                body["offer_document"],
                body["sdp"],
                body["dtls_fingerprint"],
            )
        if command == "reconnect_publish":
            body = _payload(
                value,
                allowed={"profile_id", "document", "role"},
                required={"profile_id", "document", "role"},
            )
            return self.reconnect_publish(
                body["profile_id"], body["document"], body["role"]
            )
        if command == "reconnect_fetch":
            body = _payload(
                value, allowed={"profile_id", "role"}, required={"profile_id", "role"}
            )
            return self.reconnect_fetch(body["profile_id"], body["role"])
        if command == "reconnect_path_status":
            body = _payload(value, allowed={"contact_id"}, required={"contact_id"})
            return self.reconnect_path_status(body["contact_id"])
        if command == "verify_reconnect_request":
            body = _payload(value, allowed={"document", "profile_id"}, required={"document"})
            return self.verify_reconnect_request(body["document"], body.get("profile_id"))
        if command == "verify_reconnect_offer":
            body = _payload(value, allowed={"document", "profile_id"}, required={"document"})
            return self.verify_reconnect_offer(body["document"], body.get("profile_id"))
        if command == "verify_reconnect_answer":
            body = _payload(
                value,
                allowed={"document", "offer_document", "profile_id"},
                required={"document", "offer_document"},
            )
            return self.verify_reconnect_answer(
                body["document"], body["offer_document"], body.get("profile_id")
            )
        if command == "webrtc_attach":
            body = _payload(value, allowed={"bridge_id", "peer_destination"})
            return self.webrtc_attach(body.get("bridge_id"), body.get("peer_destination"))
        if command == "webrtc_packet":
            body = _payload(value, allowed={"bridge_id", "data"}, required={"bridge_id", "data"})
            return self.webrtc_packet(body["bridge_id"], body["data"])
        if command == "webrtc_detach":
            body = _payload(value, allowed={"bridge_id"}, required={"bridge_id"})
            if any(bridge == body["bridge_id"] and self._shared_native_session(session)
                   for session, bridge in self._native_webrtc_sessions.items()):
                return {"state": "managed"}
            return self.webrtc_detach(body["bridge_id"])
        if command == "native_webrtc_offer":
            body = _payload(
                value,
                allowed={"session_id", "ice", "channels", "profile_id"},
                required={"session_id", "ice", "channels"},
            )
            return self.native_webrtc_offer(
                body["session_id"], body["ice"], body["channels"], body.get("profile_id")
            )
        if command == "native_webrtc_accept":
            body = _payload(
                value,
                allowed={"session_id", "offer_sdp", "ice", "channels", "profile_id"},
                required={"session_id", "offer_sdp", "ice", "channels"},
            )
            return self.native_webrtc_accept(
                body["session_id"], body["offer_sdp"], body["ice"], body["channels"], body.get("profile_id")
            )
        if command == "native_webrtc_apply_answer":
            body = _payload(
                value,
                allowed={"session_id", "answer_sdp"},
                required={"session_id", "answer_sdp"},
            )
            if self._shared_native_session(body["session_id"]):
                raise NativeUnavailable("Native reconnect is owned by the service")
            return self.native_webrtc_apply_answer(
                body["session_id"], body["answer_sdp"]
            )
        if command == "native_webrtc_control":
            body = _payload(
                value,
                allowed={"session_id", "label", "text"},
                required={"session_id", "label", "text"},
            )
            return self.native_webrtc_control(
                body["session_id"], body["label"], body["text"]
            )
        if command == "native_webrtc_close":
            body = _payload(value, allowed={"session_id"}, required={"session_id"})
            if self._shared_native_session(body["session_id"]):
                return {"state": "managed"}
            return self.native_webrtc_close(body["session_id"])
        if command == "native_webrtc_stats":
            body = _payload(value, allowed={"session_id"}, required={"session_id"})
            return self.native_webrtc_stats(body["session_id"])
        if command == "native_webrtc_bind_onboarding":
            body = _payload(value, allowed={"session_id", "offer_document", "answer_document"},
                            required={"session_id", "offer_document"})
            return self.native_webrtc_bind_onboarding(body["session_id"], body["offer_document"], body.get("answer_document"))
        if command == "webrtc_onboarding_offer":
            body = _payload(
                value,
                allowed={"sdp", "dtls_fingerprint"},
                required={"sdp", "dtls_fingerprint"},
            )
            return self.webrtc_onboarding_offer(body["sdp"], body["dtls_fingerprint"])
        if command == "webrtc_onboarding_answer":
            body = _payload(
                value,
                allowed={"offer_document", "sdp", "dtls_fingerprint"},
                required={"offer_document", "sdp", "dtls_fingerprint"},
            )
            return self.webrtc_onboarding_answer(
                body["offer_document"], body["sdp"], body["dtls_fingerprint"]
            )
        if command == "verify_webrtc_onboarding_offer":
            body = _payload(value, allowed={"document"}, required={"document"})
            return self.verify_webrtc_onboarding_offer(body["document"])
        if command == "verify_webrtc_onboarding_answer":
            body = _payload(
                value,
                allowed={"offer_document", "answer_document"},
                required={"offer_document", "answer_document"},
            )
            return self.verify_webrtc_onboarding_answer(
                body["offer_document"], body["answer_document"]
            )
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
                    "i2p_access_point",
                    "i2p_label",
                    "peer_destination",
                },
                required={"operation_id", "workspace_id"},
            )
            outcome = dict(self.create_workspace_invitation_command(
                body["workspace_id"],
                body["operation_id"],
                body.get("lifetime_days", 7),
                body.get("remote_profile_id"),
                body.get("connection_mode"),
                body.get("manual_setup_id"),
                body.get("external_host"),
                body.get("external_port"),
                body.get("i2p_access_point"),
                body.get("i2p_label"),
            ))
            capabilities = self._invitation_capabilities(body.get("peer_destination"))
            if capabilities:
                outcome["reconnect_capabilities"] = capabilities
            return outcome
        if command == "invite_contact_to_workspace":
            body = _payload(
                value,
                allowed={"workspace_id", "contact_id"},
                required={"workspace_id", "contact_id"},
            )
            return self.invite_contact_to_workspace(
                body["workspace_id"], body["contact_id"]
            )
        if command == "dismiss_workspace_invitation_prompt":
            body = _payload(
                value, allowed={"prompt_id"}, required={"prompt_id"}
            )
            return self.dismiss_workspace_invitation_prompt(body["prompt_id"])
        if command == "preview_workspace_invitation_prompt":
            body = _payload(value, allowed={"prompt_id"}, required={"prompt_id"})
            return self.preview_workspace_invitation_prompt(body["prompt_id"])
        if command == "submit_workspace_invitation_prompt":
            body = _payload(
                value,
                allowed={"prompt_id", "operation_id"},
                required={"prompt_id", "operation_id"},
            )
            return self.submit_workspace_invitation_prompt(
                body["prompt_id"], body["operation_id"]
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
                allowed={"operation_id", "invitation", "i2p_consent"},
                required={"operation_id", "invitation"},
            )
            return self.submit_workspace_join(
                body["invitation"], body["operation_id"],
                body.get("i2p_consent") is True,
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
        if command in {"workspace_connectivity", "workspace_request_paths"}:
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            if command == "workspace_connectivity":
                return self.workspace_connectivity(body["workspace_id"])
            return self.workspace_request_paths(body["workspace_id"])
        if command == "workspace_reconnect_status":
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            return self.workspace_reconnect_status(body["workspace_id"])
        if command == "workspace_reconnect_consent_set":
            body = _payload(
                value,
                allowed={
                    "workspace_id",
                    "auto_reconnect",
                    "allow_direct_ip_disclosure",
                    "relay_consent_scope",
                },
                required={
                    "workspace_id",
                    "auto_reconnect",
                    "allow_direct_ip_disclosure",
                },
            )
            return self.workspace_reconnect_consent_set(
                body["workspace_id"],
                body["auto_reconnect"],
                body["allow_direct_ip_disclosure"],
                body.get("relay_consent_scope", "workspace"),
            )
        if command == "workspace_helper_status":
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            return self.workspace_helper_status(body["workspace_id"])
        if command == "workspace_helper_consent_set":
            body = _payload(
                value,
                allowed={"workspace_id", "enabled"},
                required={"workspace_id", "enabled"},
            )
            return self.workspace_helper_consent_set(
                body["workspace_id"], body["enabled"]
            )
        if command == "relay_workspace_connection_update":
            body = _payload(
                value,
                allowed={"workspace_id", "relationship_id", "helper_device_id"},
                required={
                    "workspace_id",
                    "relationship_id",
                    "helper_device_id",
                },
            )
            return self.relay_workspace_connection_update(
                body["workspace_id"],
                body["relationship_id"],
                body["helper_device_id"],
            )
        if command == "create_workspace_admission_grant":
            body = _payload(
                value,
                allowed={
                    "workspace_id",
                    "admin_member_id",
                    "admin_device_id",
                    "max_admissions",
                    "lifetime_days",
                    "v2_ready",
                },
                required={"workspace_id", "admin_member_id", "admin_device_id"},
            )
            return self.create_workspace_admission_grant(
                body["workspace_id"],
                body["admin_member_id"],
                body["admin_device_id"],
                body.get("max_admissions", 5),
                body.get("lifetime_days", 7),
                body.get("v2_ready", False),
            )
        if command == "accept_workspace_admission_grant":
            body = _payload(
                value,
                allowed={"workspace_id", "grant_id"},
                required={"workspace_id", "grant_id"},
            )
            return self.accept_workspace_admission_grant(
                body["workspace_id"], body["grant_id"]
            )
        if command == "list_workspace_admission_grants":
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            return self.list_workspace_admission_grants(body["workspace_id"])
        if command == "end_workspace_admission_grant":
            body = _payload(
                value,
                allowed={"workspace_id", "grant_id"},
                required={"workspace_id", "grant_id"},
            )
            return self.end_workspace_admission_grant(
                body["workspace_id"], body["grant_id"]
            )
        if command == "create_workspace_access_recommendation":
            body = _payload(
                value,
                allowed={"workspace_id", "remote_profile_id", "lifetime_days"},
                required={"workspace_id", "remote_profile_id"},
            )
            return self.create_workspace_access_recommendation(
                body["workspace_id"],
                body["remote_profile_id"],
                body.get("lifetime_days", 7),
            )
        if command == "preview_workspace_access_recommendation":
            body = _payload(
                value, allowed={"recommendation"}, required={"recommendation"}
            )
            return self.preview_workspace_access_recommendation(
                body["recommendation"]
            )
        if command == "apply_workspace_access_recommendation":
            body = _payload(
                value,
                allowed={"recommendation", "consent"},
                required={"recommendation", "consent"},
            )
            return self.apply_workspace_access_recommendation(
                body["recommendation"], body["consent"]
            )
        if command == "send_workspace_access_recommendation":
            body = _payload(
                value,
                allowed={"workspace_id", "recommendation", "operation_id"},
                required={"workspace_id", "recommendation", "operation_id"},
            )
            return self.send_workspace_access_recommendation(
                body["workspace_id"], body["recommendation"], body["operation_id"]
            )
        if command == "list_workspace_access_recommendations":
            body = _payload(
                value, allowed={"workspace_id"}, required={"workspace_id"}
            )
            return self.list_workspace_access_recommendations(body["workspace_id"])
        if command == "preview_workspace_access_recommendation_by_id":
            body = _payload(
                value,
                allowed={"workspace_id", "recommendation_id"},
                required={"workspace_id", "recommendation_id"},
            )
            return self.preview_workspace_access_recommendation_by_id(
                body["workspace_id"], body["recommendation_id"]
            )
        if command == "apply_workspace_access_recommendation_by_id":
            body = _payload(
                value,
                allowed={"workspace_id", "recommendation_id", "consent"},
                required={"workspace_id", "recommendation_id", "consent"},
            )
            return self.apply_workspace_access_recommendation_by_id(
                body["workspace_id"], body["recommendation_id"], body["consent"]
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
            if getattr(self, "_connection_policy", "legacy") == "shared-native":
                # A renderer visibility event cannot assert an OS execution
                # fact. The native lifecycle binding already reports resume.
                return self.background_availability_status()
            return self.mobile_lifecycle_transition(
                "foreground", "renderer_recovery"
            )
        if command == "set_background_availability":
            body = _payload(
                value,
                allowed={"enabled"},
                required={"enabled"},
            )
            return self.set_background_availability(body["enabled"])
        if command == "background_status":
            _payload(value, allowed=set())
            return self.background_availability_status()
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
        connection_runtime = getattr(self, "_connection_runtime", None)
        connection_stopped = connection_runtime is None or connection_runtime.stop(timeout=0.5)
        getattr(self, "_signal_pairing_contexts", {}).clear()
        native_events = getattr(self, "_native_webrtc_events", None)
        if native_events is not None:
            try:
                native_events.put_nowait(None)
            except Exception:
                pass
        native_thread = getattr(self, "_native_webrtc_event_thread", None)
        if (
            native_thread is not None
            and native_thread.is_alive()
            and native_thread is not threading.current_thread()
        ):
            native_thread.join(timeout=0.75)
        supervisor = getattr(self, "_background_reconnect_supervisor", None)
        if supervisor is not None:
            try:
                supervisor.stop()
            except Exception:
                pass
            self._background_reconnect_supervisor = None
        try:
            # Shutdown means the keys are about to be released. A persisted
            # background opt-in must not survive into the next lock/unlock.
            if self._background_availability_enabled():
                self._write_background_availability(
                    enabled=False,
                    state="disabled",
                    reason="service_closed",
                )
                self._changed()
        except Exception:
            pass
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
        for interface in list(getattr(self, "_webrtc_bridges", {}).values()):
            try:
                interface.detach()
            except Exception:
                pass
        getattr(self, "_webrtc_bridges", {}).clear()
        getattr(self, "_native_webrtc_sessions", {}).clear()
        if self.network:
            # Older/narrow test adapters return None; only an explicit False
            # means a real callback is still executing.
            callbacks_stopped = self.network.shutdown() is not False
        try:
            self._i2p_router.stop()
        except Exception:
            pass
        # Never close the encrypted vault underneath an already-running
        # callback or retry. If the bounded foreground shutdown expires, a
        # daemon finalizer waits for that worker and closes the vault exactly
        # once without delaying desktop's sidecar deadline.
        workers_stopped = (connection_stopped and self._direct_recovery.wait(timeout=0.1)
                           and packets_stopped and callbacks_stopped and not self._retry_thread.is_alive())
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
            connection_runtime = getattr(self, "_connection_runtime", None)
            if connection_runtime is not None:
                connection_runtime.wait()
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
