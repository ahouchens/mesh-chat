"""Typed group port."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GroupObservation:
    group_id: str
    name: str
    posting_policy: str


@dataclass(frozen=True)
class GroupMessageObservation:
    text: str


@dataclass(frozen=True)
class GroupMembershipObservation:
    state: str


@dataclass(frozen=True)
class GroupInvitationObservation:
    invitation_id: str
    group_id: str
    title: str


class Groups(Protocol):
    def list(self, profile: str) -> Sequence[GroupObservation]: ...

    def create(self, profile: str, title: str, member_ids: Sequence[str],
               posting_policy: str) -> GroupObservation: ...

    def send(self, profile: str, group_id: str, text: str) -> GroupMessageObservation: ...

    def leave(self, profile: str, group_id: str) -> GroupMembershipObservation: ...

    def close(self, profile: str, group_id: str) -> GroupMembershipObservation: ...

    def save_draft(self, profile: str, group_id: str, text: str) -> str: ...

    def remove(self, profile: str, group_id: str,
               contact_id: str) -> GroupMembershipObservation: ...

    def retry_invitation(self, profile: str, group_id: str,
                         contact_id: str) -> GroupMembershipObservation: ...

    def invitations(self, profile: str) -> Sequence[GroupInvitationObservation]: ...

    def accept_invitation(self, profile: str,
                          invitation_id: str) -> GroupMembershipObservation: ...

    def decline_invitation(self, profile: str,
                           invitation_id: str) -> GroupMembershipObservation: ...
