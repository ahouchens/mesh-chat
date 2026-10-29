"""Automatic reconnect state, consent, and signed signaling capabilities.

The renderer owns the ``RTCPeerConnection``; this module owns everything that
must survive a renderer restart: per-contact consent, signed connection
capabilities, the pair mailbox capability, replay state, and the last reported
attempt state. Nothing here persists SDP, ICE credentials, or DTLS keys.

Security rules enforced here:

- a reconnect document must be signed by an approved, non-blocked contact and
  addressed to this device;
- reconnect never creates a contact, approves one, or changes workspace
  authority;
- reciprocal consent is required before a request, offer, or answer is created;
- capability documents are verified before their mailbox token is stored;
- replay keys are durable across restarts.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from .errors import (
    ContactNotApproved,
    IdentityMismatch,
    ReconnectReplayed,
    ValidationError,
)
from .models import TrustState
from .reconnect import (
    MAX_CAPABILITY_SECONDS,
    DURABLE_CAPABILITIES_VERSION,
    ENCRYPTED_CAPABILITIES_VERSION,
    MAX_CLOCK_SKEW_SECONDS,
    _destination,
    create_connection_capabilities,
    create_reconnect_answer,
    create_reconnect_offer,
    create_reconnect_request,
    preferred_initiator,
    verify_connection_capabilities,
    verify_reconnect_answer,
    verify_reconnect_offer,
    verify_reconnect_request,
)
from .signal_mailbox import fetch as fetch_signal
from .signal_mailbox import publish as publish_signal
from .signal_crypto import new_secret
from .webrtc_signaling import _b64decode, _destination_for_public_key

PROFILE_KIND = "reconnect_profile"
PENDING_KIND = "reconnect_pending_capability"
REPLAY_KIND = "reconnect_replay"
STATE_KIND = "reconnect_state"
DEVICE_KIND = "reconnect_device"
PROFILE_VERSION = 1
SESSION_DOMAIN = "mesh-chat:reconnect:session:v1:"
MAX_PROFILES = 64
MAX_PENDING_CAPABILITIES = 32
MAX_DETAIL = 160
MAX_REPLAY_TTL = 3600
CONNECTED_TRUST = {TrustState.APPROVED.value, TrustState.VERIFIED.value}
STATES = {
    "idle",
    "waiting_for_peer",
    "probing",
    "offer_pending",
    "answer_pending",
    "connecting",
    "connected",
    "retry_wait",
    "peer_offline",
    "manual_required",
    "stopped",
}
ROLES = {"request", "offer", "answer"}


def reconnect_session_id(token: str) -> str:
    """Derive the mailbox session for one pair capability.

    The session is public (it appears in the mailbox URL) but unguessable
    without the token, so the operator cannot enumerate pairs from public
    destination hashes.
    """

    if not isinstance(token, str) or not token:
        raise ValidationError("Mailbox pairing token is invalid")
    return hashlib.sha256(
        (SESSION_DOMAIN + token).encode("utf-8")
    ).hexdigest()[:40]


def _now() -> int:
    return int(time.time())


def _text(value: Any, label: str, *, limit: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValidationError(f"{label} is invalid")
    if "\n" in value or "\r" in value:
        raise ValidationError(f"{label} is invalid")
    return value


def _capability_persistent(profile: dict[str, Any], side: str) -> bool:
    return bool(
        profile.get(f"{side}_capabilities")
        and profile.get(f"{side}_capabilities_persistent") is True
        and profile.get(f"{side}_capabilities_version") in {DURABLE_CAPABILITIES_VERSION, ENCRYPTED_CAPABILITIES_VERSION}
        and profile.get(f"{side}_capabilities_expires_at") == 0
    )


def _capability_active(profile: dict[str, Any], side: str) -> bool:
    return bool(profile.get(f"{side}_capabilities") and (
        _capability_persistent(profile, side)
        or int(profile.get(f"{side}_capabilities_expires_at") or 0) > _now()
    ))


class ReconnectServiceMixin:
    # ------------------------------------------------------------------ device

    def _reconnect_device_id(self) -> str:
        record = self.store.get(DEVICE_KIND, "local")
        if record is not None and isinstance(record.get("device_id"), str):
            return record["device_id"]
        device = "dev-" + secrets.token_hex(12)
        self.store.put(
            DEVICE_KIND,
            "local",
            {"v": PROFILE_VERSION, "device_id": device, "created_at": _now()},
        )
        return device

    # ---------------------------------------------------------------- profiles

    def _reconnect_profiles_raw(self) -> list[dict[str, Any]]:
        return sorted(
            self.store.list(PROFILE_KIND),
            key=lambda profile: float(profile.get("updated_at", 0)),
            reverse=True,
        )

    def _reconnect_profile(self, profile_id: Any) -> dict[str, Any]:
        profile_id = _text(profile_id, "Reconnect profile ID")
        profile = self.store.get(PROFILE_KIND, profile_id)
        if profile is None:
            raise ValidationError("Reconnect profile does not exist")
        return self._reconnect_migrate_preference(profile)

    def _reconnect_profile_for_contact(
        self,
        contact_id: str,
        remote_device_id: str | None = None,
    ) -> dict[str, Any]:
        matches = [
            profile
            for profile in self.store.list(PROFILE_KIND)
            if profile.get("contact_id") == contact_id
        ]
        if remote_device_id:
            for profile in matches:
                if profile.get("remote_device_id") == remote_device_id:
                    return self._reconnect_migrate_preference(profile)
        else:
            for profile in matches:
                if not profile.get("remote_device_id"):
                    return self._reconnect_migrate_preference(profile)
        if not matches:
            profile = self._new_profile(contact_id, remote_device_id)
            self.store.put(PROFILE_KIND, profile["id"], profile)
            return profile
        profile = dict(matches[0])
        if remote_device_id and not profile.get("remote_device_id"):
            profile["remote_device_id"] = remote_device_id
        return self._reconnect_migrate_preference(profile)

    def _reconnect_migrate_preference(self, profile: dict[str, Any]) -> dict[str, Any]:
        if profile.get("scope_kind") == "workspace" or str(profile.get("contact_id", "")).startswith("workspace:"):
            return profile
        if profile.get("auto_reconnect_preference") in {"default", "explicit", "legacy_disabled"}:
            return profile
        profile = dict(profile)
        if profile.get("auto_reconnect"):
            profile["auto_reconnect_preference"] = "explicit"
        elif not profile.get("local_capabilities") and not profile.get("last_attempt_at") and not profile.get("reciprocal_since"):
            # Every prior explicit consent/forget operation issued a local
            # capability. A profile without one is an untouched default.
            profile["auto_reconnect"] = True
            profile["auto_reconnect_preference"] = "default"
        else:
            # Old signed false values do not say whether they came from the
            # former default or a deliberate opt-out. Preserve that choice.
            profile["auto_reconnect_preference"] = "legacy_disabled"
        self.store.put(PROFILE_KIND, profile["id"], profile)
        return profile

    def _new_profile(
        self, contact_id: str, remote_device_id: str | None
    ) -> dict[str, Any]:
        if len(self.store.list(PROFILE_KIND)) >= MAX_PROFILES:
            raise ValidationError("Too many reconnect profiles")
        now = _now()
        return {
            "v": PROFILE_VERSION,
            "id": contact_id if contact_id.startswith("workspace:") or not remote_device_id else f"{contact_id}:{remote_device_id}",
            "contact_id": contact_id,
            "scope_kind": "workspace" if contact_id.startswith("workspace:") else "contact",
            "workspace_id": None,
            "workspace_name": None,
            "peer_member_id": None,
            "peer_display_name": None,
            "local_device_id": self._reconnect_device_id(),
            "remote_device_id": remote_device_id or "",
            "auto_reconnect": not contact_id.startswith("workspace:"),
            "auto_reconnect_preference": "default",
            "allow_direct_ip_disclosure": False,
            "relay_consent_scope": "contact",
            "remote_auto_reconnect": False,
            "remote_allow_direct_ip_disclosure": False,
            "mailbox_url": None,
            "mailbox_pair_token": None,
            "mailbox_expires_at": 0,
            "remote_mailbox_url": None,
            "remote_mailbox_pair_token": None,
            "remote_mailbox_expires_at": 0,
            "local_capabilities": None,
            "local_capabilities_expires_at": 0,
            "local_capabilities_persistent": False,
            "local_capabilities_version": None,
            "remote_capabilities": None,
            "remote_capabilities_expires_at": 0,
            "remote_capabilities_persistent": False,
            "remote_capabilities_version": None,
            "state": "idle",
            "active": False,
            "attempt_id": "",
            "last_attempt_at": 0,
            "last_error": "",
            "created_at": now,
            "updated_at": now,
        }

    # ---------------------------------------------------------------- mailbox

    def _profile_mailbox(self, profile: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        configured = getattr(self._call_settings, "signal_mailbox_url", None)
        local_ok = bool(
            profile.get("mailbox_url")
            and profile.get("mailbox_url") == configured
            and profile.get("mailbox_pair_token")
            and profile.get("mailbox_secret")
            and (_capability_persistent(profile, "local") and profile.get("mailbox_expires_at") == 0
                 or int(profile.get("mailbox_expires_at") or 0) > now)
        )
        remote_ok = bool(
            profile.get("remote_mailbox_url")
            and profile.get("remote_mailbox_url") == configured
            and profile.get("remote_mailbox_pair_token")
            and profile.get("remote_mailbox_secret")
            and (_capability_persistent(profile, "remote") and profile.get("remote_mailbox_expires_at") == 0
                 or int(profile.get("remote_mailbox_expires_at") or 0) > now)
        )
        local = {
            "url": profile.get("mailbox_url"),
            "token": profile.get("mailbox_pair_token"),
            "secret": profile.get("mailbox_secret"),
        }
        remote = {
            "url": profile.get("remote_mailbox_url"),
            "token": profile.get("remote_mailbox_pair_token"),
            "secret": profile.get("remote_mailbox_secret"),
        }
        local_device = str(profile.get("local_device_id") or "")
        remote_device = str(profile.get("remote_device_id") or "")
        # Until a signed peer capability arrives there is no device to compare;
        # fall back to the local mailbox so a single-sided profile is usable.
        preferred = (
            preferred_initiator(local_device, remote_device)
            if local_device and remote_device
            else False
        )
        ordered = [(local, local_ok), (remote, remote_ok)]
        if not preferred:
            ordered.reverse()
        for candidate, usable in ordered:
            if usable:
                return {
                    "configured": True,
                    "preferred": preferred,
                    "url": candidate["url"],
                    "token": candidate["token"],
                    "secret": candidate["secret"],
                    "session": reconnect_session_id(candidate["token"]),
                    "source": "local" if candidate is local else "remote",
                }
        return {
            "configured": False,
            "preferred": preferred,
            "url": None,
            "token": None,
            "secret": None,
            "session": None,
            "source": None,
        }

    def _reconnect_relay_available(self) -> bool:
        """True when a consented relay can hide direct host/srflx candidates."""

        settings = self._call_settings
        return bool(
            settings.turn_url
            or (settings.turn_broker_url and settings.turn_broker_consent)
        )

    # ------------------------------------------------------------------ public

    def _reconnect_profile_public(
        self, profile: dict[str, Any]
    ) -> dict[str, Any]:
        contact = self.store.get("contact", profile.get("contact_id", "")) or {}
        workspace_authorized = True
        if profile.get("scope_kind") == "workspace" or str(
            profile.get("contact_id", "")
        ).startswith("workspace:"):
            try:
                contact = self._workspace_reconnect_contact(profile["contact_id"])
            except Exception:
                workspace_authorized = False
                contact = {
                    "display_name": profile.get("peer_display_name")
                    or profile.get("workspace_name")
                    or "Workspace peer",
                    "destination_hash": profile.get("peer_destination"),
                    "trust": "workspace",
                }
        mailbox = self._profile_mailbox(profile)
        reasons: list[str] = []
        if not profile.get("local_capabilities"):
            reasons.append("local_capabilities_missing")
        if not profile.get("remote_capabilities"):
            reasons.append("peer_capabilities_missing")
        if profile.get("remote_capabilities") and not _capability_active(profile, "remote"):
            reasons.append("peer_capabilities_expired")
        if profile.get("local_capabilities") and not _capability_active(profile, "local"):
            reasons.append("local_capabilities_expired")
        if not profile.get("auto_reconnect"):
            reasons.append("consent_missing")
        if profile.get("remote_capabilities") and not profile.get(
            "remote_auto_reconnect"
        ):
            reasons.append("peer_consent_missing")
        if not profile.get("allow_direct_ip_disclosure") and not self._reconnect_relay_available():
            reasons.append("relay_required")
        if not mailbox["configured"]:
            reasons.append("mailbox_not_configured")
        if any(profile.get(f"{side}_capabilities") and profile.get(f"{side}_capabilities_version") != ENCRYPTED_CAPABILITIES_VERSION for side in ("local", "remote")):
            reasons.append("encrypted_capabilities_required")
        if not workspace_authorized:
            reasons.append("workspace_peer_inactive")
        return {
            "id": profile["id"],
            "contact_id": profile.get("contact_id"),
            "scope_kind": profile.get("scope_kind", "contact"),
            "workspace_id": profile.get("workspace_id"),
            "workspace_name": profile.get("workspace_name"),
            "peer_member_id": profile.get("peer_member_id"),
            "peer_display_name": profile.get("peer_display_name"),
            "display_name": contact.get("display_name"),
            "destination_hash": contact.get("destination_hash"),
            "trust": contact.get("trust"),
            "local_device_id": profile.get("local_device_id"),
            "remote_device_id": profile.get("remote_device_id") or None,
            "auto_reconnect": bool(profile.get("auto_reconnect")),
            "auto_reconnect_preference": profile.get("auto_reconnect_preference", "legacy_disabled" if not profile.get("auto_reconnect") else "explicit"),
            "allow_direct_ip_disclosure": bool(
                profile.get("allow_direct_ip_disclosure")
            ),
            "relay_consent_scope": profile.get("relay_consent_scope", "contact"),
            "peer_auto_reconnect": bool(profile.get("remote_auto_reconnect")),
            "peer_allow_direct_ip_disclosure": bool(
                profile.get("remote_allow_direct_ip_disclosure")
            ),
            "has_local_capabilities": bool(profile.get("local_capabilities")),
            "has_peer_capabilities": bool(profile.get("remote_capabilities")),
            "capabilities_persistent": _capability_persistent(profile, "local"),
            "peer_capabilities_persistent": _capability_persistent(profile, "remote"),
            "transports": list(profile.get("transports") or []),
            "peer_transports": list(profile.get("remote_transports") or []),
            "capabilities_issued_at": int(
                profile.get("local_capabilities_issued_at") or 0
            ),
            "peer_capabilities_issued_at": int(
                profile.get("remote_capabilities_issued_at") or 0
            ),
            "capabilities_expires_at": int(
                profile.get("local_capabilities_expires_at") or 0
            ),
            "peer_capabilities_expires_at": int(
                profile.get("remote_capabilities_expires_at") or 0
            ),
            "state": profile.get("state", "idle"),
            "active": bool(profile.get("active")),
            "last_attempt_at": int(profile.get("last_attempt_at") or 0),
            "last_error": profile.get("last_error", ""),
            "updated_at": int(profile.get("updated_at") or 0),
            "effective": {
                "ready": not reasons,
                "configured": mailbox["configured"],
                "preferred": mailbox["preferred"],
                "session": mailbox["session"],
                "mailbox_url": mailbox["url"],
                "source": mailbox["source"],
                "reasons": reasons,
            },
        }

    def reconnect_profiles(self) -> dict[str, Any]:
        self._reconnect_promote_all()
        # Bootstrap personal relationships after approval without changing
        # saved opt-outs, direct-IP permission, or workspace consent.
        for contact in self.store.list("contact"):
            if contact.get("trust") not in CONNECTED_TRUST:
                continue
            try:
                profile = self._reconnect_profile_for_contact(contact["id"])
                self._reconnect_ensure_local_capabilities(profile, contact)
            except Exception:
                # Identity/capacity failure for one contact must not hide the
                # reconnect state of every other approved contact.
                continue
        profile = self.store.get("profile", "local") or {}
        profiles = []
        for item in self._reconnect_profiles_raw():
            if item.get("scope_kind") == "workspace":
                try:
                    contact = self._reconnect_contact(item["contact_id"])
                    refreshed = self._reconnect_ensure_local_capabilities(item, contact)
                    if refreshed or item.get("capability_delivery_pending"):
                        self._queue_workspace_reconnect_capability(item)
                except Exception:
                    # Inactive membership never gets a new capability. A live
                    # authenticated control channel can also exchange updates.
                    pass
            public = self._reconnect_profile_public(item)
            native_session = getattr(self, "native_reconnect_session", lambda _: None)(item["id"])
            if native_session:
                public["native_session_id"] = native_session
            profiles.append(public)
        return {
            "local_device_id": self._reconnect_device_id(),
            "local_destination": profile.get("destination_hash"),
            "mailbox_configured": bool(
                getattr(self._call_settings, "signal_mailbox_url", None)
            ),
            "profiles": profiles,
        }

    # ----------------------------------------------------------------- consent

    def _reconnect_contact(self, contact_id: Any) -> dict[str, Any]:
        contact_id = _text(contact_id, "Contact ID")
        if contact_id.startswith("workspace:"):
            return self._workspace_reconnect_contact(contact_id)
        contact = self.store.get("contact", contact_id)
        if contact is None:
            raise ValidationError("Contact does not exist")
        if contact.get("trust") not in CONNECTED_TRUST:
            # Includes pending, blocked, identity-changed, and deleted contacts.
            raise ContactNotApproved(
                "Auto-reconnect requires an approved, non-blocked contact"
            )
        return contact

    def _workspace_reconnect_contact(self, contact_id: str) -> dict[str, Any]:
        parts = contact_id.split(":")
        if len(parts) != 4 or parts[0] != "workspace":
            raise ValidationError("Workspace reconnect peer is invalid")
        workspace_id, member_id, device_id = parts[1], parts[2], parts[3]
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace reconnect requires an active workspace")
        manifest = self._workspace_current_manifest(workspace)
        local_member = next(
            (item for item in manifest.members if item.member_id == workspace.get("local_member_id")),
            None,
        )
        local_device = next(
            (
                device
                for member in manifest.members
                for device in member.devices
                if device.device_id == workspace.get("local_device_id")
            ),
            None,
        )
        member = next(
            (item for item in manifest.members if item.member_id == member_id),
            None,
        )
        device = next(
            (item for item in member.devices if item.device_id == device_id), None
        ) if member is not None and member.status == "active" else None
        if (
            local_member is None
            or local_member.status != "active"
            or local_device is None
            or member is None
            or member.member_id == local_member.member_id
            or device is None
            or device.destination_hash == local_device.destination_hash
        ):
            raise ContactNotApproved("Workspace reconnect peer is not active")
        return {
            "id": contact_id,
            "destination_hash": device.destination_hash.hex(),
            "display_name": f"{member.display_name} · {workspace['name']}",
            "trust": "workspace",
            "scope_kind": "workspace",
            "workspace_id": workspace_id,
            "workspace_name": workspace["name"],
            "peer_member_id": member_id,
            "peer_device_id": device_id,
        }

    def _workspace_reconnect_contact_by_destination(
        self, destination: str
    ) -> dict[str, Any] | None:
        match = None
        for workspace in self.store.list("workspace"):
            if workspace.get("state") != "active":
                continue
            try:
                manifest = self._workspace_current_manifest(workspace)
            except Exception:
                continue
            for member in manifest.members:
                if member.status != "active":
                    continue
                for device in member.devices:
                    if device.destination_hash.hex() == destination:
                        try:
                            contact = self._workspace_reconnect_contact(
                                f"workspace:{workspace['id']}:{member.member_id}:{device.device_id}"
                            )
                        except Exception:
                            continue
                        if match is not None:
                            raise IdentityMismatch("Reconnect profile is required for this peer")
                        match = contact
        return match

    def _reconnect_contact_by_destination(
        self, destination: str
    ) -> dict[str, Any] | None:
        contact = self._contact_by_destination(destination)
        workspace_contact = self._workspace_reconnect_contact_by_destination(destination)
        if contact is not None and workspace_contact is not None:
            raise IdentityMismatch("Reconnect profile is required for this peer")
        return contact or workspace_contact

    def reconnect_consent_set(
        self,
        contact_id: Any,
        auto_reconnect: Any,
        allow_direct_ip_disclosure: Any,
        relay_consent_scope: Any = "contact",
        rotate_token: Any = False,
    ) -> dict[str, Any]:
        contact = self._reconnect_contact(contact_id)
        if not isinstance(auto_reconnect, bool) or not isinstance(
            allow_direct_ip_disclosure, bool
        ):
            raise ValidationError("Reconnect consent must be boolean")
        if relay_consent_scope not in {"contact", "session", "workspace"}:
            raise ValidationError("Relay consent scope is invalid")
        if not isinstance(rotate_token, bool):
            raise ValidationError("Reconnect token rotation must be boolean")
        profile = self._reconnect_profile_for_contact(contact["id"])
        changed = (
            bool(profile.get("auto_reconnect")) != auto_reconnect
            or bool(profile.get("allow_direct_ip_disclosure"))
            != allow_direct_ip_disclosure
            or profile.get("relay_consent_scope", "contact") != relay_consent_scope
        )
        profile["auto_reconnect"] = auto_reconnect
        profile["auto_reconnect_preference"] = "explicit"
        profile["allow_direct_ip_disclosure"] = allow_direct_ip_disclosure
        profile["relay_consent_scope"] = relay_consent_scope
        stale = (
            not profile.get("local_capabilities")
            or profile.get("mailbox_url")
            != getattr(self._call_settings, "signal_mailbox_url", None)
            or not _capability_active(profile, "local")
            or profile.get("local_capabilities_version") != ENCRYPTED_CAPABILITIES_VERSION
            or (not contact["id"].startswith("workspace:") and not _capability_persistent(profile, "local"))
        )
        if changed or rotate_token or stale:
            self._reconnect_issue_local_capabilities(
                profile, contact, rotate=changed or rotate_token
            )
        profile["updated_at"] = _now()
        self.store.put(PROFILE_KIND, profile["id"], profile)
        # Send revoked consent before retiring a native channel. The service
        # owns this exchange even when the WebView is suspended.
        native_shared = getattr(self, "_share_native_capabilities", lambda *_: False)(
            contact["id"], profile.get("local_capabilities"))
        if changed and (not auto_reconnect or not allow_direct_ip_disclosure):
            close_native = getattr(self, "close_native_reconnect_session", None)
            if close_native is not None:
                close_native(profile["id"])
        self._changed()
        return {
            "profile": self._reconnect_profile_public(profile),
            "capabilities": profile.get("local_capabilities"),
            "changed": changed,
            "native_shared": native_shared,
        }

    def reconnect_capabilities_create(
        self,
        contact_id: Any,
        rotate_token: Any = True,
    ) -> dict[str, Any]:
        contact = self._reconnect_contact(contact_id)
        if not isinstance(rotate_token, bool):
            raise ValidationError("Reconnect token rotation must be boolean")
        profile = self._reconnect_profile_for_contact(contact["id"])
        self._reconnect_issue_local_capabilities(profile, contact, rotate=rotate_token)
        profile["updated_at"] = _now()
        self.store.put(PROFILE_KIND, profile["id"], profile)
        self._changed()
        return {
            "profile": self._reconnect_profile_public(profile),
            "capabilities": profile.get("local_capabilities"),
        }

    def _reconnect_issue_local_capabilities(
        self,
        profile: dict[str, Any],
        contact: dict[str, Any],
        *,
        rotate: bool,
    ) -> None:
        identity = self._call_identity()
        mailbox_url = getattr(self._call_settings, "signal_mailbox_url", None)
        token = profile.get("mailbox_pair_token")
        secret = profile.get("mailbox_secret")
        if (
            rotate
            or not token
            or not secret
            or profile.get("mailbox_url") != mailbox_url
        ):
            token = secrets.token_urlsafe(32) if mailbox_url else None
            secret = new_secret() if mailbox_url else None
        # Capabilities can be rotated more than once within one second. Keep
        # their signed issue times ordered so a delayed document cannot undo
        # a newer token or consent change, including after a restart.
        current = _now()
        now = max(current, int(profile.get("local_capabilities_issued_at") or 0) + 1)
        if now > current + MAX_CLOCK_SKEW_SECONDS:
            raise ValidationError("Connection capability changes are too frequent")
        persistent = True
        expires_at = 0 if persistent else now + MAX_CAPABILITY_SECONDS
        mailbox_expires_at = (
            (0 if persistent else min(expires_at - 60, now + 30 * 24 * 60 * 60)) if mailbox_url else None
        )
        serialized = create_connection_capabilities(
            identity,
            peer_destination=contact["destination_hash"],
            device_id=self._reconnect_device_id(),
            transports=["webrtc"],
            auto_reconnect=bool(profile.get("auto_reconnect")),
            allow_direct_ip_disclosure=bool(
                profile.get("allow_direct_ip_disclosure")
            ),
            relay_consent_scope=profile.get("relay_consent_scope", "contact"),
            mailbox_url=mailbox_url,
            mailbox_pair_token=token,
            mailbox_secret=secret,
            mailbox_expires_at=mailbox_expires_at,
            expires_at=expires_at,
            persistent=persistent,
            encrypted=True,
            now=now,
        )
        verified = verify_connection_capabilities(serialized, now=now)
        profile["local_capabilities"] = serialized
        profile["local_capabilities_expires_at"] = verified.expires_at
        profile["local_capabilities_persistent"] = verified.persistent
        profile["local_capabilities_version"] = verified.version
        profile["local_capabilities_issued_at"] = verified.issued_at
        profile["transports"] = list(verified.transports)
        profile["mailbox_url"] = verified.mailbox_url
        profile["mailbox_pair_token"] = verified.mailbox_pair_token
        profile["mailbox_secret"] = verified.mailbox_secret
        profile["mailbox_expires_at"] = verified.mailbox_expires_at or 0
        profile["local_device_id"] = verified.device_id

    def reconnect_capabilities_store(
        self, document: Any, expected_contact_id: Any = None,
        expected_peer_destination: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(document, str):
            raise ValidationError("Connection capabilities must be text")
        unverified = verify_connection_capabilities(document)
        local = self._require_profile()
        if unverified.peer_destination != local["destination_hash"]:
            raise IdentityMismatch("Connection capabilities are for another device")
        if expected_peer_destination is not None:
            # Initial onboarding knows the identity from verified signed SDP
            # before its contact request arrives. Bind control messages to
            # that peer before storing even an inert pending capability.
            expected_peer_destination = _destination(expected_peer_destination)
            if expected_peer_destination != unverified.signer_destination:
                raise IdentityMismatch("Connection capabilities are not from this channel's peer")
        if expected_contact_id is not None:
            expected_contact_id = _text(expected_contact_id, "Expected contact ID")
            if expected_contact_id.startswith("workspace:"):
                raise ValidationError("Workspace capabilities require their workspace authorization")
            contact = self.store.get("contact", expected_contact_id)
            if contact is None or contact.get("destination_hash") != unverified.signer_destination:
                raise IdentityMismatch("Connection capabilities are not from this channel's contact")
        else:
            contact = self._contact_by_destination(unverified.signer_destination)
        if contact is None:
            # A joiner's capability can arrive over the control channel before
            # its LXMF contact request reaches this device. Hold the signed,
            # peer-bound document without granting any trust; it is promoted
            # only after a contact exists and is approved.
            pending = self._hold_pending_capability(unverified, document)
            return {"profile": None, "pending": pending}
        # A pending contact is an identity already bound by a signed invitation.
        # Storing its rendezvous capability never approves it: all reconnect
        # document verification and attempt creation still require an approved,
        # non-blocked contact.
        if contact.get("trust") not in {
            TrustState.AWAITING_CONSENT.value,
            TrustState.PENDING_REQUEST.value,
            *CONNECTED_TRUST,
        }:
            raise ContactNotApproved(
                "Connection capabilities are not from a usable contact"
            )
        verified = verify_connection_capabilities(
            document, expected_signer=contact["destination_hash"]
        )
        # A capability can arrive before the LXMF contact request. Once that
        # request creates a contact, preserve the pending document's ordering
        # before a delayed older capability can replace and delete it.
        self._reconnect_promote_pending(verified.signer_destination)
        profile = self._store_remote_capabilities(contact, verified)
        self.store.delete(PENDING_KIND, verified.signer_destination)
        self._changed()
        return {"profile": self._reconnect_profile_public(profile), "pending": False}

    def _hold_pending_capability(
        self,
        verified,
        document: str,
    ) -> bool:
        now = _now()
        for record_id, record in self.store.items(PENDING_KIND):
            if int(record.get("expires_at") or 0) <= now:
                self.store.delete(PENDING_KIND, record_id)
        existing = self.store.get(PENDING_KIND, verified.signer_destination)
        if existing is not None:
            issued_at = existing.get("issued_at")
            if issued_at is None:
                # Pending records written by older clients lack this index.
                try:
                    issued_at = verify_connection_capabilities(existing["document"]).issued_at
                except Exception:
                    issued_at = 0
            if verified.issued_at <= int(issued_at):
                return True
        if existing is None and len(self.store.items(PENDING_KIND)) >= MAX_PENDING_CAPABILITIES:
            raise ValidationError("Too many pending reconnect capabilities")
        self.store.put(
            PENDING_KIND,
            verified.signer_destination,
            {
                "v": PROFILE_VERSION,
                "signer_destination": verified.signer_destination,
                "device_id": verified.device_id,
                "document": document,
                "issued_at": verified.issued_at,
                # Unknown peers never get unbounded retained storage, even
                # when their signed pair authorization has no expiry.
                "expires_at": now + MAX_CAPABILITY_SECONDS if verified.persistent else verified.expires_at,
                "received_at": now,
            },
        )
        return True

    def _store_remote_capabilities(self, contact, verified) -> dict[str, Any]:
        profile = self._reconnect_profile_for_contact(
            contact["id"], verified.device_id
        )
        if self._reconnect_apply_remote_capabilities(profile, verified):
            self.store.put(PROFILE_KIND, profile["id"], profile)
        return profile

    def _reconnect_apply_remote_capabilities(self, profile, verified) -> bool:
        if profile.get("remote_capabilities") and verified.issued_at <= int(
            profile.get("remote_capabilities_issued_at") or 0
        ):
            # Identical documents are idempotent. Conflicting documents with
            # an equal timestamp cannot establish which consent is newer.
            return False
        now = _now()
        # A peer never changes local consent. Only its own declared consent and
        # rendezvous details are recorded, and only after signature checks.
        profile["remote_device_id"] = verified.device_id
        profile["remote_auto_reconnect"] = verified.auto_reconnect
        profile["remote_allow_direct_ip_disclosure"] = (
            verified.allow_direct_ip_disclosure
        )
        profile["remote_capabilities"] = verified.serialized
        profile["remote_capabilities_expires_at"] = verified.expires_at
        profile["remote_capabilities_persistent"] = verified.persistent
        profile["remote_capabilities_version"] = verified.version
        profile["remote_capabilities_issued_at"] = verified.issued_at
        profile["remote_transports"] = list(verified.transports)
        profile["remote_mailbox_url"] = verified.mailbox_url
        profile["remote_mailbox_pair_token"] = verified.mailbox_pair_token
        profile["remote_mailbox_secret"] = verified.mailbox_secret
        profile["remote_mailbox_expires_at"] = verified.mailbox_expires_at or 0
        if int(profile.get("reciprocal_since") or 0) == 0 and (
            profile.get("auto_reconnect") and verified.auto_reconnect
        ):
            profile["reciprocal_since"] = now
        profile["updated_at"] = now
        return True

    def _reconnect_promote_pending(self, destination: str) -> bool:
        pending = self.store.get(PENDING_KIND, destination)
        if pending is None:
            return False
        if int(pending.get("expires_at") or 0) <= _now():
            self.store.delete(PENDING_KIND, destination)
            return False
        contact = self._contact_by_destination(destination)
        if contact is None or contact.get("trust") not in {
            TrustState.AWAITING_CONSENT.value,
            TrustState.PENDING_REQUEST.value,
            *CONNECTED_TRUST,
        }:
            return False
        try:
            verified = verify_connection_capabilities(
                pending["document"], expected_signer=destination
            )
        except Exception:
            self.store.delete(PENDING_KIND, destination)
            return False
        self._store_remote_capabilities(contact, verified)
        self.store.delete(PENDING_KIND, destination)
        return True

    def _reconnect_promote_all(self) -> None:
        for record_id in [item[0] for item in self.store.items(PENDING_KIND)]:
            self._reconnect_promote_pending(record_id)

    def reconnect_capabilities_get(self, contact_id: Any) -> dict[str, Any]:
        contact = self._reconnect_contact(contact_id)
        profile = self._reconnect_profile_for_contact(contact["id"])
        self._reconnect_ensure_local_capabilities(profile, contact)
        return {
            "profile": self._reconnect_profile_public(profile),
            "local_capabilities": profile.get("local_capabilities"),
            "peer_capabilities": profile.get("remote_capabilities"),
        }

    def _reconnect_ensure_local_capabilities(self, profile, contact) -> bool:
        """Bootstrap/upgrade our signed preferences without rotating pairing.

        The renderer shares the returned document over the authenticated live
        channel. Issuing our document never extends the peer's authority.
        """
        now = _now()
        configured_mailbox = getattr(self._call_settings, "signal_mailbox_url", None)
        if (profile.get("local_capabilities")
            and _capability_persistent(profile, "local")
            and profile.get("local_capabilities_version") == ENCRYPTED_CAPABILITIES_VERSION
            and profile.get("mailbox_url") == configured_mailbox):
            return False
        self._reconnect_issue_local_capabilities(profile, contact, rotate=False)
        if profile.get("scope_kind") == "workspace":
            profile["capability_delivery_pending"] = True
        profile["updated_at"] = now
        self.store.put(PROFILE_KIND, profile["id"], profile)
        return True

    # ------------------------------------------------------------------ replay

    def reconnect_replay_check(self, key: Any, ttl: Any = 600) -> dict[str, Any]:
        key = _text(key, "Reconnect replay key")
        if len(key) < 8:
            raise ValidationError("Reconnect replay key is invalid")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= MAX_REPLAY_TTL:
            raise ValidationError("Reconnect replay lifetime is invalid")
        now = _now()
        accepted = True
        for record_id, record in self.store.items(REPLAY_KIND):
            expiry = int(record.get("expires_at") or 0)
            if expiry <= now:
                self.store.delete(REPLAY_KIND, record_id)
                continue
            if record_id == key:
                accepted = False
        if accepted:
            self.store.put(
                REPLAY_KIND,
                key,
                {"v": PROFILE_VERSION, "key": key, "expires_at": now + ttl},
            )
        return {"accepted": accepted, "key": key}

    def _reconnect_remember(self, key: str, ttl: int) -> bool:
        now = _now()
        for record_id, record in self.store.items(REPLAY_KIND):
            if int(record.get("expires_at") or 0) <= now:
                self.store.delete(REPLAY_KIND, record_id)
        if self.store.get(REPLAY_KIND, key) is not None:
            return False
        self.store.put(
            REPLAY_KIND,
            key,
            {"v": PROFILE_VERSION, "key": key, "expires_at": now + ttl},
        )
        return True

    # ------------------------------------------------------------------ status

    def reconnect_status(
        self,
        state: Any = None,
        detail: Any = None,
        attempt_id: Any = None,
    ) -> dict[str, Any]:
        record = self.store.get(STATE_KIND, "current") or {
            "v": PROFILE_VERSION,
            "state": "idle",
            "detail": "",
            "attempt_id": "",
            "updated_at": 0,
        }
        if state is not None:
            if state not in STATES:
                raise ValidationError("Reconnect state is invalid")
            if detail is not None and (
                not isinstance(detail, str) or len(detail) > MAX_DETAIL
            ):
                raise ValidationError("Reconnect detail is invalid")
            if attempt_id is not None and not isinstance(attempt_id, str):
                raise ValidationError("Reconnect attempt is invalid")
            record = {
                **record,
                "state": state,
                "detail": detail or "",
                "attempt_id": attempt_id or "",
                "updated_at": _now(),
            }
            self.store.put(STATE_KIND, "current", record)
        profile = self.store.get("profile", "local") or {}
        return {
            **record,
            "local_device_id": self._reconnect_device_id(),
            "local_destination": profile.get("destination_hash"),
            "mailbox_configured": bool(
                getattr(self._call_settings, "signal_mailbox_url", None)
            ),
            "profiles": [
                self._reconnect_profile_public(item)
                for item in self._reconnect_profiles_raw()
            ],
        }

    def reconnect_start(self, contact_id: Any = None) -> dict[str, Any]:
        targets = (
            [self._reconnect_contact(contact_id)]
            if contact_id is not None
            else [
                contact
                for contact in self.store.list("contact")
                if contact.get("trust") in CONNECTED_TRUST
            ]
        )
        changed = False
        for contact in targets:
            profile = self._reconnect_profile_for_contact(contact["id"])
            if profile.get("auto_reconnect") and profile.get("remote_auto_reconnect"):
                profile["active"] = True
                profile["state"] = "waiting_for_peer"
                profile["last_error"] = ""
                profile["updated_at"] = _now()
                self.store.put(PROFILE_KIND, profile["id"], profile)
                changed = True
        if changed:
            self._changed()
        return self.reconnect_status()

    def reconnect_stop(self, contact_id: Any = None) -> dict[str, Any]:
        if contact_id is not None:
            profile_id = _text(contact_id, "Reconnect profile ID")
            profiles = [
                profile
                for profile in self._reconnect_profiles_raw()
                if profile.get("contact_id") == profile_id
                or profile.get("id") == profile_id
            ]
        else:
            profiles = self._reconnect_profiles_raw()
        for profile in profiles:
            profile["active"] = False
            profile["state"] = "stopped"
            profile["updated_at"] = _now()
            self.store.put(PROFILE_KIND, profile["id"], profile)
            close_native = getattr(self, "close_native_reconnect_session", None)
            if close_native is not None:
                close_native(profile["id"])
        if contact_id is None:
            # A per-contact stop must not claim the whole supervisor is stopped.
            self.store.put(
                STATE_KIND,
                "current",
                {
                    "v": PROFILE_VERSION,
                    "state": "stopped",
                    "detail": "",
                    "attempt_id": "",
                    "updated_at": _now(),
                },
            )
        self._changed()
        return self.reconnect_status()

    # --------------------------------------------------------------- documents

    def _reconnect_require_consent(
        self, contact: dict[str, Any], *, profile: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if profile is None:
            profile = self._reconnect_profile_for_contact(contact["id"])
        if not profile.get("auto_reconnect"):
            raise ContactNotApproved("Auto-reconnect consent is not enabled here")
        if not profile.get("remote_auto_reconnect"):
            raise ContactNotApproved(
                "The contact has not consented to automatic reconnect"
            )
        if not _capability_active(profile, "local") or not _capability_active(profile, "remote"):
            raise ContactNotApproved("Reconnect capabilities are missing or expired")
        if any(profile.get(f"{side}_capabilities_version") != ENCRYPTED_CAPABILITIES_VERSION for side in ("local", "remote")):
            raise ValidationError("Exchange encrypted reconnect capabilities with the updated peer first")
        if self._profile_mailbox(profile)["session"] is None:
            raise ValidationError("Signaling mailbox is not configured")
        return profile

    def _reconnect_authorize(
        self, signer_destination: str, to_destination: str, *, profile_id: Any = None
    ) -> dict[str, Any]:
        local = self._require_profile()
        if to_destination != local["destination_hash"]:
            raise IdentityMismatch("Reconnect document is for another device")
        if profile_id is not None:
            profile = self._reconnect_profile(profile_id)
            contact = self._reconnect_contact(profile["contact_id"])
            if contact["destination_hash"] != signer_destination:
                raise IdentityMismatch("Reconnect document is from another peer")
        else:
            contact = self._reconnect_contact_by_destination(signer_destination)
        if contact is None:
            raise ContactNotApproved(
                "Reconnect document is not from a known contact"
            )
        if contact.get("trust") not in CONNECTED_TRUST and contact.get("trust") != "workspace":
            raise ContactNotApproved(
                "Reconnect document is not from an approved contact"
            )
        self._reconnect_require_consent(contact, profile=profile if profile_id is not None else None)
        return contact

    def reconnect_request_create(
        self, contact_id: Any, attempt_id: Any, nonce: Any = None
    ) -> dict[str, Any]:
        contact = self._reconnect_contact(contact_id)
        profile = self._reconnect_require_consent(contact)
        if nonce is None:
            nonce = secrets.token_urlsafe(18)
        document = create_reconnect_request(
            self._call_identity(),
            to_destination=contact["destination_hash"],
            device_id=self._reconnect_device_id(),
            attempt_id=attempt_id,
            nonce=nonce,
        )
        request = verify_reconnect_request(document)
        now = _now()
        profile["attempt_id"] = request.attempt_id
        profile["last_attempt_at"] = now
        profile["state"] = "probing"
        profile["updated_at"] = now
        self.store.put(PROFILE_KIND, profile["id"], profile)
        self._changed()
        return {
            "document": request.serialized,
            "attempt_id": request.attempt_id,
            "expires_at": request.expires_at,
            "profile": self._reconnect_profile_public(profile),
        }

    def reconnect_offer_create(
        self,
        contact_id: Any,
        request_document: Any,
        sdp: Any,
        dtls_fingerprint: Any,
    ) -> dict[str, Any]:
        contact = self._reconnect_contact(contact_id)
        profile = self._reconnect_require_consent(contact)
        request = self._verify_reconnect_request_document(request_document)
        self._reconnect_authorize(
            request.signer_destination, request.to_destination, profile_id=profile["id"]
        )
        if request.signer_destination != contact["destination_hash"]:
            raise IdentityMismatch("Reconnect request is from another contact")
        if request.device_id != profile.get("remote_device_id"):
            raise IdentityMismatch("Reconnect request is from another device")
        document = create_reconnect_offer(
            self._call_identity(),
            request,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
        )
        offer = verify_reconnect_offer(document)
        now = _now()
        profile["attempt_id"] = offer.attempt_id
        profile["last_attempt_at"] = now
        profile["state"] = "offer_pending"
        profile["updated_at"] = now
        self.store.put(PROFILE_KIND, profile["id"], profile)
        self._changed()
        return {
            "document": offer.serialized,
            "attempt_id": offer.attempt_id,
            "session_id": offer.session_id,
            "expires_at": offer.expires_at,
            "profile": self._reconnect_profile_public(profile),
        }

    def reconnect_answer_create(
        self,
        contact_id: Any,
        offer_document: Any,
        sdp: Any,
        dtls_fingerprint: Any,
    ) -> dict[str, Any]:
        contact = self._reconnect_contact(contact_id)
        profile = self._reconnect_require_consent(contact)
        offer = self._verify_reconnect_offer_document(offer_document)
        self._reconnect_authorize(
            offer.signer_destination, offer.to_destination, profile_id=profile["id"]
        )
        if offer.signer_destination != contact["destination_hash"]:
            raise IdentityMismatch("Reconnect offer is from another contact")
        document = create_reconnect_answer(
            self._call_identity(),
            offer,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
        )
        answer = verify_reconnect_answer(document, offer)
        profile["state"] = "answer_pending"
        profile["updated_at"] = _now()
        self.store.put(PROFILE_KIND, profile["id"], profile)
        self._changed()
        return {
            "document": answer.serialized,
            "attempt_id": answer.attempt_id,
            "session_id": answer.session_id,
            "expires_at": answer.expires_at,
            "profile": self._reconnect_profile_public(profile),
        }

    def verify_reconnect_request(self, document: Any, profile_id: Any = None) -> dict[str, Any]:
        request = self._verify_reconnect_request_document(document)
        contact = self._reconnect_authorize(
            request.signer_destination, request.to_destination, profile_id=profile_id
        )
        profile = (
            self._reconnect_profile(profile_id)
            if profile_id is not None
            else self._reconnect_profile_for_contact(contact["id"])
        )
        if request.device_id != profile.get("remote_device_id"):
            raise IdentityMismatch("Reconnect request is from another device")
        return {
            "attempt_id": request.attempt_id,
            "from_destination": request.from_destination,
            "to_destination": request.to_destination,
            "device_id": request.device_id,
            "expires_at": request.expires_at,
            "contact_id": contact["id"],
            "profile_id": profile["id"],
        }

    def verify_reconnect_offer(self, document: Any, profile_id: Any = None) -> dict[str, Any]:
        offer = self._verify_reconnect_offer_document(document)
        contact = self._reconnect_authorize(
            offer.signer_destination, offer.to_destination, profile_id=profile_id
        )
        profile = (
            self._reconnect_profile(profile_id)
            if profile_id is not None
            else self._reconnect_profile_for_contact(contact["id"])
        )
        return {
            "attempt_id": offer.attempt_id,
            "session_id": offer.session_id,
            "from_destination": offer.from_destination,
            "to_destination": offer.to_destination,
            "sdp": offer.sdp,
            "dtls_fingerprint": offer.dtls_fingerprint,
            "expires_at": offer.expires_at,
            "contact_id": contact["id"],
            "profile_id": profile["id"],
        }

    def verify_reconnect_answer(
        self, document: Any, offer_document: Any, profile_id: Any = None
    ) -> dict[str, Any]:
        offer = self._verify_reconnect_offer_document(offer_document)
        local = self._require_profile()
        # This side created the offer, so it must be the offer's sender and the
        # offer must target the peer whose answer is being verified.
        if offer.from_destination != local["destination_hash"]:
            raise IdentityMismatch("Reconnect offer was not created by this device")
        contact = self._reconnect_authorize(
            offer.to_destination, local["destination_hash"], profile_id=profile_id
        )
        if not isinstance(document, str):
            raise ValidationError("Reconnect answer must be text")
        answer = verify_reconnect_answer(document, offer)
        self._reconnect_authorize(
            answer.signer_destination, answer.to_destination, profile_id=profile_id
        )
        if answer.signer_destination != contact["destination_hash"]:
            raise IdentityMismatch("Reconnect answer is from another contact")
        key = f"answer:{answer.session_id}:{answer.offer_digest}"
        if not self._reconnect_remember(
            key, max(60, min(MAX_REPLAY_TTL, offer.expires_at - _now()))
        ):
            raise ReconnectReplayed("Reconnect answer was already accepted")
        profile = (
            self._reconnect_profile(profile_id)
            if profile_id is not None
            else self._reconnect_profile_for_contact(contact["id"])
        )
        profile["state"] = "connecting"
        profile["updated_at"] = _now()
        self.store.put(PROFILE_KIND, profile["id"], profile)
        self._changed()
        return {
            "attempt_id": answer.attempt_id,
            "session_id": answer.session_id,
            "from_destination": answer.from_destination,
            "to_destination": answer.to_destination,
            "sdp": answer.sdp,
            "dtls_fingerprint": answer.dtls_fingerprint,
            "expires_at": answer.expires_at,
            "contact_id": contact["id"],
            "profile_id": profile["id"],
        }

    @staticmethod
    def _verify_reconnect_request_document(document: Any):
        if not isinstance(document, str):
            raise ValidationError("Reconnect request must be text")
        return verify_reconnect_request(document)

    @staticmethod
    def _verify_reconnect_offer_document(document: Any):
        if not isinstance(document, str):
            raise ValidationError("Reconnect offer must be text")
        return verify_reconnect_offer(document)

    # ------------------------------------------------------------------ mailbox

    def _reconnect_publish_target(self, profile_id: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = self._reconnect_profile(profile_id)
        contact = self._reconnect_contact(profile["contact_id"])
        self._reconnect_require_consent(contact, profile=profile)
        mailbox = self._profile_mailbox(profile)
        if mailbox["session"] is None:
            raise ValidationError("Signaling mailbox is not configured")
        return profile, mailbox

    def reconnect_publish(
        self, profile_id: Any, document: Any, role: Any
    ) -> dict[str, Any]:
        if role not in ROLES:
            raise ValidationError("Signaling role is invalid")
        if not isinstance(document, str):
            raise ValidationError("Signaling document is invalid")
        self._reconnect_local_signer(document)
        profile, mailbox = self._reconnect_publish_target(profile_id)
        published = publish_signal(
            mailbox["url"],
            document,
            role,
            token=mailbox["token"],
            secret=mailbox["secret"],
            session=mailbox["session"],
        )
        return {
            "session_id": published["session_id"],
            "role": published["role"],
            "expires_in": published["expires_in"],
            "rotated": published.get("rotated", False),
            "profile_id": profile["id"],
        }

    def reconnect_fetch(self, profile_id: Any, role: Any) -> dict[str, Any]:
        if role not in ROLES:
            raise ValidationError("Signaling role is invalid")
        profile, mailbox = self._reconnect_publish_target(profile_id)
        fetched = fetch_signal(
            mailbox["url"],
            mailbox["session"],
            role,
            token=mailbox["token"],
            secret=mailbox["secret"],
            pending=True,
        )
        return {
            "document": fetched.get("document"),
            "pending": bool(fetched.get("pending")),
            "session_id": mailbox["session"],
            "role": role,
            "profile_id": profile["id"],
        }

    def reconnect_path_status(self, contact_id: Any) -> dict[str, Any]:
        """Report whether Reticulum already has a path after a reconnect.

        Announcement over the freshly attached interface is asynchronous, so
        the renderer polls this instead of declaring messaging ready as soon
        as the DataChannel opens. A missing network is distinct from a path
        that has not arrived yet.
        """

        contact = self._reconnect_contact(contact_id)
        if self.network is None:
            return {
                "state": "network_unavailable",
                "has_path": False,
                "ready": False,
                "reason": "network_unavailable",
            }
        destination = bytes.fromhex(contact["destination_hash"])
        has_path = bool(self.network.path_known(destination))
        ready = bool(self.network.recipient_ready(destination))
        if not has_path:
            try:
                self.network.request_path(destination)
            except Exception:
                pass
        return {
            "state": "path_available" if has_path else "path_pending",
            "has_path": has_path,
            "ready": ready,
            "reason": None if has_path else "path_not_ready",
        }

    def _reconnect_local_signer(self, document: str) -> None:
        try:
            import json

            value = json.loads(document)
            public_key = _b64decode(value["signer_public_key"])
            signer = _destination_for_public_key(public_key)
        except Exception as exc:
            raise ValidationError("Signaling document is invalid") from exc
        local = self._require_profile()
        if signer != local["destination_hash"]:
            raise IdentityMismatch("Signaling document is not signed by this device")

    # ------------------------------------------------------------- invitations

    def _invitation_capabilities(
        self, peer_destination: Any
    ) -> str | None:
        """Attach connection capabilities when the peer is already known."""

        if peer_destination is None or self._identity is None:
            return None
        if not isinstance(peer_destination, str):
            raise ValidationError("Peer destination is invalid")
        contact = self._contact_by_destination(peer_destination.lower())
        contact_id = (
            contact["id"]
            if contact
            else f"invitation:{peer_destination.lower()}"
        )
        profile = self._reconnect_profile_for_contact(contact_id)
        contact_view = contact or {
            "id": contact_id,
            "destination_hash": peer_destination.lower(),
        }
        self._reconnect_issue_local_capabilities(profile, contact_view, rotate=False)
        profile["updated_at"] = _now()
        self.store.put(PROFILE_KIND, profile["id"], profile)
        return profile.get("local_capabilities")

    def _contact_capabilities(self, contact: dict[str, Any]) -> str | None:
        """Create or refresh this device's capability for a known contact.

        A pending contact is allowed: the signed invitation already bound the
        peer destination, and accepting an invitation is what lets both sides
        advertise a rendezvous. Capabilities never approve anything.
        """

        if contact.get("trust") not in {
            TrustState.AWAITING_CONSENT.value,
            TrustState.PENDING_REQUEST.value,
            *CONNECTED_TRUST,
        }:
            return None
        if self._identity is None:
            # Approval must stay durable even if the service started without a
            # local identity. Capabilities are an optional transport hint and
            # are reissued on the next explicit consent action.
            return None
        profile = self._reconnect_profile_for_contact(contact["id"])
        self._reconnect_issue_local_capabilities(profile, contact, rotate=False)
        profile["updated_at"] = _now()
        self.store.put(PROFILE_KIND, profile["id"], profile)
        return profile.get("local_capabilities")
