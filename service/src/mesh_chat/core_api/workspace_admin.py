"""Narrow ports for workspace administration through the private facade."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WorkspaceMetadata:
    name: str
    description: str


@dataclass(frozen=True)
class WorkspaceRetention:
    retention_days: int | None


@dataclass(frozen=True)
class DeviceSummary:
    device: str
    member: str
    current: bool


@dataclass(frozen=True)
class WorkspacePolicies:
    channel_creation: str
    posting: str
    invitation_requests: str


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
    posting: str | None = None


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


@dataclass(frozen=True)
class WorkspaceInvitation:
    document: str
    link: str
    expires_at: float
    connection_mode: str | None = None
    i2p_access_point: str | None = None


class WorkspaceAdmin(Protocol):
    def list(self, profile: str) -> tuple[WorkspaceSummary, ...]: ...

    def requests(self, profile: str, workspace: str) -> tuple[JoinRequestSummary, ...]: ...

    def request_ids(self, profile: str, workspace: str) -> tuple[str, ...]: ...

    def create_invitation(self, profile: str, workspace: str,
                          operation_id: str,
                          connection_mode: str | None = None,
                          i2p_access_point: str | None = None,
                          i2p_label: str | None = None) -> WorkspaceInvitation: ...

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
                       topic: str, operation_id: str,
                       posting: str | None = None) -> ChannelEdit: ...

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

    def decide_admin_request(self, profile: str, workspace: str, request: str,
                             approve: bool, operation_id: str) -> str: ...

    def cancel_admin_request(self, profile: str, workspace: str, request: str,
                             operation_id: str) -> str: ...

    def dismiss_admin_request(self, profile: str, workspace: str, request: str,
                              operation_id: str) -> str: ...

    def offer_authority_transition(self, profile: str, workspace: str, transition_kind: str,
                                   member_id: str, device_id: str, outgoing_owner_role: str,
                                   operation_id: str) -> str: ...

    def authority_transition_ids(self, profile: str, workspace: str) -> tuple[str, ...]: ...

    def accept_authority_transition(self, profile: str, workspace: str, transition: str,
                                    operation_id: str) -> str: ...

    def finalize_authority_transition(self, profile: str, workspace: str, transition: str,
                                      operation_id: str) -> str: ...

    def report_authority_loss(self, profile: str, workspace: str, operation_id: str) -> str: ...

    def close_workspace(self, profile: str, workspace: str, operation_id: str) -> str: ...

    def leave_workspace(self, profile: str, workspace: str, operation_id: str) -> str: ...

    def remove_workspace_data(self, profile: str, workspace: str, confirmation: str,
                              operation_id: str) -> str: ...

    def update_metadata(self, profile: str, workspace: str, name: str,
                        description: str, operation_id: str) -> WorkspaceMetadata: ...

    def update_retention(self, profile: str, workspace: str, retention_days: int | None,
                         operation_id: str) -> WorkspaceRetention: ...

    def update_policies(self, profile: str, workspace: str, channel_creation: str,
                        posting: str, invitation_requests: str,
                        operation_id: str) -> WorkspacePolicies: ...

    def devices(self, profile: str, workspace: str) -> tuple[DeviceSummary, ...]: ...

    def remove_device(self, profile: str, workspace: str, device_id: str,
                      operation_id: str) -> str: ...

    def device_ids(self, profile: str, workspace: str) -> tuple[str, ...]: ...
