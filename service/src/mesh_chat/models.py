from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class DeliveryState(StrEnum):
    WAITING_FOR_KEYS = "waiting_for_keys"
    QUEUED = "queued"
    SENDING = "sending"
    STORED_FOR_DELIVERY = "stored_for_delivery"
    RECEIVED_BY_ENDPOINT = "received_by_endpoint"
    DELIVERED = "delivered"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrustState(StrEnum):
    AWAITING_CONSENT = "awaiting_consent"
    PENDING_REQUEST = "pending_request"
    APPROVED = "approved"
    VERIFIED = "verified"
    IDENTITY_CHANGED = "identity_changed"
    BLOCKED = "blocked"


class MessageKind(StrEnum):
    CHAT = "chat"
    REACTION = "reaction"
    RECEIPT = "receipt"
    CONTACT_REQUEST = "contact_request"
    CONTACT_ACCEPT = "contact_accept"
    CONTACT_DECLINE = "contact_decline"
    GROUP_INVITE = "group_invite"
    GROUP_ACCEPT = "group_accept"
    GROUP_MANIFEST = "group_manifest"
    GROUP_CHAT = "group_chat"
    GROUP_REACTION = "group_reaction"
    GROUP_RECEIPT = "group_receipt"
    GROUP_LEAVE_REQUEST = "group_leave_request"


class GroupRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class GroupPostingPolicy(StrEnum):
    MEMBERS = "members"
    OWNER_ADMINS = "owner_admins"


class GroupStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceStatus(StrEnum):
    JOINING = "joining"
    ACTIVE = "active"
    LEAVING = "leaving"
    LEFT = "left"
    REMOVED = "removed"
    CLOSED = "closed"
    FORKED = "forked"
    INCOMPLETE_SYNC = "incomplete_sync"
    LOCALLY_REMOVED = "locally_removed"


class WorkspaceChannelCreationPolicy(StrEnum):
    ALL_MEMBERS = "all_members"
    OWNER_AND_ADMINS = "owner_and_admins"


class WorkspacePostingPolicy(StrEnum):
    ALL_MEMBERS = "all_members"
    OWNER_AND_ADMINS = "owner_and_admins"


class WorkspaceInvitationPolicy(StrEnum):
    OWNER_ONLY = "owner_only"
    OWNER_AND_ADMINS = "owner_and_admins"
    ALL_MEMBERS_REQUEST = "all_members_request"


@dataclass(slots=True)
class Contact:
    id: str
    display_name: str
    public_identity: str
    identity_hash: str
    destination_hash: str
    fingerprint: str
    trust: TrustState
    connection_hints: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = 0
    updated_at: float = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trust"] = self.trust.value
        return data


@dataclass(slots=True)
class Message:
    id: str
    conversation_id: str
    contact_id: str
    direction: str
    kind: MessageKind
    text: str
    state: DeliveryState
    created_at: float
    expires_at: float
    native_message_id: str | None = None
    receipt_for: str | None = None
    failure_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["state"] = self.state.value
        return data


@dataclass(slots=True)
class Profile:
    display_name: str
    public_identity: str
    identity_hash: str
    destination_hash: str
    fingerprint: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
