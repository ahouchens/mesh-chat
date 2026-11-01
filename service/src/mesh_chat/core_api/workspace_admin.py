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
class ChannelEdit:
    channel: str
    name: str
    topic: str
    visibility: str
    state: str


@dataclass(frozen=True)
class DeviceLink:
    document: str
    link: str
    expires_at: float


@dataclass(frozen=True)
class DeviceLinkSubmission:
    workspace: str
    name: str
    state: str


@dataclass(frozen=True)
class DeviceLinkPreview:
    workspace: str
    name: str
    member_display_name: str
    device_count: int
    expires_at: float


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
                       operation_id: str, visibility: str = "public",
                       member_ids: tuple[str, ...] = ()) -> ChannelSummary: ...

    def channel_members(self, profile: str, workspace: str,
                        channel: str) -> tuple[str, ...]: ...

    def update_channel_members(self, profile: str, workspace: str, channel: str,
                               member_ids: tuple[str, ...],
                               operation_id: str) -> tuple[str, ...]: ...

    def update_channel(self, profile: str, workspace: str, channel: str, name: str,
                       topic: str, operation_id: str) -> ChannelEdit: ...

    def archive_channel(self, profile: str, workspace: str, channel: str,
                        operation_id: str) -> ChannelEdit: ...

    def device_link_create(self, profile: str, workspace: str,
                           operation_id: str) -> DeviceLink: ...

    def device_link_preview(self, profile: str,
                            document: str) -> DeviceLinkPreview: ...

    def device_link_submit(self, profile: str, document: str,
                           operation_id: str) -> DeviceLinkSubmission: ...

    def device_link_requests(self, profile: str, workspace: str) -> tuple[str, ...]: ...

    def device_link_ids(self, profile: str, workspace: str) -> tuple[str, ...]: ...

    def approve_device_link(self, profile: str, workspace: str, request_id: str,
                            operation_id: str) -> str: ...

    def decline_device_link(self, profile: str, workspace: str, request_id: str,
                            operation_id: str) -> str: ...

    def offer_channel_transfer(self, profile: str, workspace: str, channel: str,
                               member_id: str, operation_id: str) -> str: ...

    def accept_channel_transfer(self, profile: str, workspace: str, channel: str,
                                operation_id: str) -> str: ...
