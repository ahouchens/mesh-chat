"""Narrow ports for workspace administration through the private facade."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WorkspaceSummary:
    workspace: str
    name: str
    role: str
    state: str


@dataclass(frozen=True)
class JoinRequestSummary:
    request: str
    display_name: str
    created_at: float


@dataclass(frozen=True)
class MemberSummary:
    member: str
    display_name: str
    role: str
    status: str


@dataclass(frozen=True)
class ChannelSummary:
    channel: str
    name: str
    visibility: str
    state: str


@dataclass(frozen=True)
class MemberRoleChange:
    member: str
    role: str


@dataclass(frozen=True)
class JoinApproval:
    workspace: str
    state: str


class WorkspaceAdmin(Protocol):
    def list(self, profile: str) -> tuple[WorkspaceSummary, ...]: ...

    def requests(self, profile: str, workspace: str) -> tuple[JoinRequestSummary, ...]: ...

    def request_ids(self, profile: str, workspace: str) -> tuple[str, ...]: ...

    def approve(self, profile: str, workspace: str, request: str,
                operation_id: str) -> JoinApproval: ...

    def decline(self, profile: str, workspace: str, request: str,
                operation_id: str) -> JoinApproval: ...

    def members(self, profile: str, workspace: str) -> tuple[MemberSummary, ...]: ...

    def change_role(self, profile: str, workspace: str, member: str, role: str,
                    operation_id: str) -> MemberRoleChange: ...

    def channels(self, profile: str, workspace: str) -> tuple[ChannelSummary, ...]: ...

    def create_channel(self, profile: str, workspace: str, name: str,
                       operation_id: str) -> ChannelSummary: ...
