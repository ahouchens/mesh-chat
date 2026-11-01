"""Private adapter: workspace listing and join approval over domain transactions."""

import uuid

from ..errors import ContactNotApproved, InvitationExpired, InvitationInvalid, ValidationError
from .errors import ApiFailure
from .service_messages import storage_errors
from .workspace_admin import (ChannelEdit, ChannelSummary, DeviceLink, DeviceLinkPreview,
                              DeviceSummary,
                              WorkspacePolicies,
                              DeviceLinkSubmission,
                              JoinApproval, JoinRequestSummary,
                              MemberRoleChange, MemberSummary, WorkspaceSummary)


MAX_WORKSPACES = 16
MAX_JOIN_REQUESTS = 32
MAX_REQUEST_IDS = 64
MAX_CHANNELS = 32
MAX_DOCUMENT_BYTES = 65536
CHANNEL_STATES = {"active", "archived", "left"}
ROLES = {"owner", "admin", "member"}
STATES = {"active", "joining", "linking", "left", "removed", "device_removed",
          "revoked", "archived"}
MEMBER_STATES = {"active", "invited", "leaving", "left", "removed"}
ROLES_ASSIGNABLE = {"admin", "member"}


class ServiceWorkspaceAdmin:
    def __init__(self, service):
        self._service = service
        self._store = service.store

    def _require_local(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")

    def _workspace(self, workspace_id):
        # Workspace records are stored under a hashed record id; the public id
        # is a field, so resolve by scanning the bounded workspace collection.
        for workspace in self._store.list("workspace"):
            if workspace.get("id") == workspace_id:
                return workspace
        raise ApiFailure("forbidden")

    def list(self, profile):
        self._require_local(profile)
        with storage_errors():
            summaries = []
            for item in self._store.list("workspace")[:MAX_WORKSPACES]:
                workspace_id, name = item.get("id"), item.get("name")
                role, state = item.get("local_role"), item.get("state")
                if (not isinstance(workspace_id, str) or not isinstance(name, str)
                        or role not in ROLES or state not in STATES):
                    raise ApiFailure("internal")
                summaries.append(WorkspaceSummary(workspace_id, name, role, state))
            return tuple(summaries)

    def requests(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            found = []
            for item in self._store.list("workspace_join_request"):
                if item.get("workspace_id") != workspace_id or item.get("state") != "pending":
                    continue
                request_id, name = item.get("id"), item.get("display_name")
                created = item.get("created_at")
                if (not isinstance(request_id, str) or not isinstance(name, str)
                        or type(created) not in {int, float}):
                    raise ApiFailure("internal")
                found.append(JoinRequestSummary(request_id, name, float(created)))
                if len(found) >= MAX_JOIN_REQUESTS:
                    break
            return tuple(sorted(found, key=lambda item: (item.created_at, item.request)))

    def request_ids(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            self._workspace(workspace_id)
            found = [item.get("id") for item in self._store.list("workspace_join_request")
                     if item.get("workspace_id") == workspace_id
                     and isinstance(item.get("id"), str)]
            return tuple(found[:MAX_REQUEST_IDS])

    def approve(self, profile, workspace_id, request_id, operation_id):
        self._require_local(profile)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            request = self._store.get("workspace_join_request", request_id)
            if request is None or request.get("workspace_id") != workspace_id:
                raise ApiFailure("not_found")
            try:
                outcome = self._service.approve_workspace_join(
                    workspace_id, request_id, operation_id)
            except (ValidationError, ContactNotApproved, InvitationInvalid,
                    InvitationExpired) as error:
                raise ApiFailure("invalid_request") from error
            workspace = outcome.get("workspace") if isinstance(outcome, dict) else None
            state = workspace.get("state") if isinstance(workspace, dict) else None
            if state not in STATES:
                raise ApiFailure("internal")
            return JoinApproval(workspace_id, state)

    def decline(self, profile, workspace_id, request_id, operation_id):
        self._require_local(profile)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            request = self._store.get("workspace_join_request", request_id)
            if request is None or request.get("workspace_id") != workspace_id:
                raise ApiFailure("not_found")
            try:
                outcome = self._service.decline_workspace_join(
                    workspace_id, request_id, operation_id)
            except (ValidationError, ContactNotApproved, InvitationInvalid,
                    InvitationExpired) as error:
                raise ApiFailure("invalid_request") from error
            state = outcome.get("state") if isinstance(outcome, dict) else None
            if state != "declined":
                raise ApiFailure("internal")
            return JoinApproval(workspace_id, state)

    def members(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin", "member"}:
                raise ApiFailure("forbidden")
            members = workspace.get("members")
            if not isinstance(members, list) or len(members) > 8:
                raise ApiFailure("internal")
            found = []
            for item in members:
                member_id, name = item.get("id"), item.get("display_name")
                role, status = item.get("role"), item.get("status")
                if (not isinstance(member_id, str) or not isinstance(name, str)
                        or role not in {"owner"} | ROLES_ASSIGNABLE
                        or status not in MEMBER_STATES):
                    raise ApiFailure("internal")
                found.append(MemberSummary(member_id, name, role, status))
            return tuple(sorted(found, key=lambda item: (item.role != "owner", item.member)))

    def change_role(self, profile, workspace_id, member_id, role, operation_id):
        self._require_local(profile)
        if role not in ROLES_ASSIGNABLE or not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            members = [item for item in workspace.get("members", [])
                       if isinstance(item, dict) and item.get("id") == member_id]
            if not members:
                raise ApiFailure("not_found")
            current = members[0]
            if current.get("role") == "owner":
                raise ApiFailure("invalid_request")
            if current.get("role") == role:
                return MemberRoleChange(member_id, role)
            try:
                self._service.change_workspace_role(workspace_id, member_id, role, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            updated = self._workspace(workspace_id)
            found = [item for item in updated.get("members", [])
                     if isinstance(item, dict) and item.get("id") == member_id]
            if not found or found[0].get("role") != role:
                raise ApiFailure("internal")
            return MemberRoleChange(member_id, role)

    def channels(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            self._workspace(workspace_id)
            found = []
            for item in self._store.list("workspace_channel"):
                if item.get("workspace_id") != workspace_id:
                    continue
                channel_id, name = item.get("id"), item.get("name")
                visibility, state = item.get("visibility"), item.get("state")
                if (not isinstance(channel_id, str) or not isinstance(name, str)
                        or visibility not in {"public", "private"} or state not in CHANNEL_STATES):
                    raise ApiFailure("internal")
                found.append(ChannelSummary(channel_id, name, visibility, state))
                if len(found) >= MAX_CHANNELS:
                    break
            return tuple(sorted(found, key=lambda item: (item.name, item.channel)))

    def _channel(self, workspace_id, channel_id):
        for item in self._store.list("workspace_channel"):
            if item.get("workspace_id") == workspace_id and item.get("id") == channel_id:
                return item
        raise ApiFailure("not_found")

    def channel_members(self, profile, workspace_id, channel_id):
        self._require_local(profile)
        with storage_errors():
            channel = self._channel(workspace_id, channel_id)
            if channel.get("visibility") != "private":
                raise ApiFailure("invalid_request")
            member_ids = channel.get("member_ids")
            if not isinstance(member_ids, list) or len(member_ids) > 8:
                raise ApiFailure("internal")
            return tuple(item for item in member_ids if isinstance(item, str))

    def update_channel_members(self, profile, workspace_id, channel_id, member_ids,
                               operation_id):
        self._require_local(profile)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            channel = self._channel(workspace_id, channel_id)
            if channel.get("visibility") != "private":
                raise ApiFailure("invalid_request")
            requested = tuple(dict.fromkeys(member_ids))
            if not 1 <= len(requested) <= 8:
                raise ApiFailure("invalid_request")
            try:
                self._service.update_workspace_private_channel_members(
                    workspace_id, channel_id, list(requested), operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            updated = self._channel(workspace_id, channel_id)
            current = updated.get("member_ids")
            if not isinstance(current, list) or set(requested) != set(current):
                raise ApiFailure("internal")
            return tuple(requested)

    def update_channel(self, profile, workspace_id, channel_id, name, topic, operation_id):
        self._require_local(profile)
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 64
                or not isinstance(topic, str) or len(topic) > 1024
                or not isinstance(operation_id, str) or not operation_id):
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            try:
                self._service.update_workspace_channel(
                    workspace_id, channel_id, name.strip(), topic, False, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            updated = self._channel(workspace_id, channel_id)
            visibility, state = updated.get("visibility"), updated.get("state")
            if visibility not in {"public", "private"} or state not in CHANNEL_STATES:
                raise ApiFailure("internal")
            return ChannelEdit(channel_id, name.strip(), topic, visibility, state)

    def create_channel(self, profile, workspace_id, name, operation_id, visibility="public",
                       member_ids=()):
        self._require_local(profile)
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 64
                or visibility not in {"public", "private"}
                or not isinstance(operation_id, str) or not operation_id):
            raise ApiFailure("invalid_request")
        if visibility == "private" and not 1 <= len(tuple(member_ids)) <= 8:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("state") != "active":
                raise ApiFailure("conflict")
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            try:
                self._service.create_workspace_channel(
                    workspace_id, name.strip(), "", operation_id, visibility,
                    list(member_ids) if visibility == "private" else None)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            candidates = [item for item in self._store.list("workspace_channel")
                          if item.get("workspace_id") == workspace_id
                          and item.get("name") == name.strip()]
            if not candidates:
                raise ApiFailure("internal")
            created = max(candidates, key=lambda item: float(item.get("created_at", 0)))
            channel_id, state = created.get("id"), created.get("state")
            visibility = created.get("visibility")
            if (not isinstance(channel_id, str) or state not in CHANNEL_STATES
                    or visibility not in {"public", "private"}):
                raise ApiFailure("internal")
            return ChannelSummary(channel_id, name.strip(), visibility, state)

    def archive_channel(self, profile, workspace_id, channel_id, operation_id):
        self._require_local(profile)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            channel = self._channel(workspace_id, channel_id)
            name, topic = channel.get("name"), channel.get("topic", "")
            if not isinstance(name, str) or not isinstance(topic, str):
                raise ApiFailure("internal")
            try:
                self._service.update_workspace_channel(
                    workspace_id, channel_id, name, topic, True, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            updated = self._channel(workspace_id, channel_id)
            state, visibility = updated.get("state"), updated.get("visibility")
            if state != "archived" or visibility not in {"public", "private"}:
                raise ApiFailure("internal")
            return ChannelEdit(channel_id, name, topic, visibility, state)

    def device_link_create(self, profile, workspace_id, operation_id):
        self._require_local(profile)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("state") != "active":
                raise ApiFailure("conflict")
            try:
                outcome = self._service.create_workspace_device_link(
                    workspace_id, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            document, link = outcome.get("value"), outcome.get("link")
            expires = outcome.get("expires_at")
            if (not isinstance(document, str) or not 1 <= len(document) <= MAX_DOCUMENT_BYTES
                    or not isinstance(link, str) or not 1 <= len(link) <= MAX_DOCUMENT_BYTES
                    or type(expires) not in {int, float}):
                raise ApiFailure("internal")
            return DeviceLink(document, link, float(expires))

    def device_link_preview(self, profile, document):
        self._require_local(profile)
        if (not isinstance(document, str) or not 1 <= len(document) <= MAX_DOCUMENT_BYTES):
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                preview = self._service.preview_workspace_device_link(document)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            workspace_id, name = preview.get("workspace_id"), preview.get("name")
            member_name, count = preview.get("member_display_name"), preview.get("device_count")
            expires = preview.get("expires_at")
            if (not isinstance(workspace_id, str) or not isinstance(name, str)
                    or not isinstance(member_name, str) or type(count) is not int
                    or not 1 <= count <= 24 or type(expires) not in {int, float}):
                raise ApiFailure("internal")
            return DeviceLinkPreview(workspace_id, name, member_name, count, float(expires))

    def device_link_submit(self, profile, document, operation_id):
        self._require_local(profile)
        if (not isinstance(document, str) or not 1 <= len(document) <= MAX_DOCUMENT_BYTES
                or not isinstance(operation_id, str) or not operation_id):
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                outcome = self._service.submit_workspace_device_link(document, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            workspace_id, name = outcome.get("id"), outcome.get("name")
            state = outcome.get("state")
            if (not isinstance(workspace_id, str) or not isinstance(name, str)
                    or state != "linking"):
                raise ApiFailure("internal")
            return DeviceLinkSubmission(workspace_id, name, state)

    def _device_transition_entries(self, workspace_id):
        entries = []
        for item in self._store.list("workspace_device_transition"):
            if (item.get("workspace_id") == workspace_id
                    and item.get("transition_kind") == "link"
                    and item.get("state") in {"pending", "approved", "declined"}):
                transition_id, state = item.get("id"), item.get("state")
                if not isinstance(transition_id, str):
                    raise ApiFailure("internal")
                entries.append((transition_id, state))
        return tuple(sorted(entries))

    def _device_transitions(self, workspace_id):
        return tuple(item for item, state in self._device_transition_entries(workspace_id)
                     if state == "pending")

    def device_link_ids(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            return tuple(item for item, _ in self._device_transition_entries(workspace_id))

    def device_link_requests(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            return self._device_transitions(workspace_id)

    def _decide_device_link(self, profile, workspace_id, request_id, operation_id, approve):
        self._require_local(profile)
        if not isinstance(request_id, str) or not request_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            states = dict(self._device_transition_entries(workspace_id))
            if request_id not in states:
                raise ApiFailure("forbidden")
            expected = "approved" if approve else "declined"
            if states[request_id] == expected:
                return expected
            if states[request_id] != "pending":
                raise ApiFailure("invalid_request")
            try:
                if approve:
                    outcome = self._service.approve_workspace_device_link(
                        workspace_id, request_id, operation_id)
                else:
                    outcome = self._service.decline_workspace_device_link(
                        workspace_id, request_id, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            state = outcome.get("state")
            expected = "approved" if approve else "declined"
            if state != expected or outcome.get("id") != request_id:
                raise ApiFailure("internal")
            return expected

    def approve_device_link(self, profile, workspace_id, request_id, operation_id):
        return self._decide_device_link(profile, workspace_id, request_id, operation_id, True)

    def decline_device_link(self, profile, workspace_id, request_id, operation_id):
        return self._decide_device_link(profile, workspace_id, request_id, operation_id, False)

    def offer_channel_transfer(self, profile, workspace_id, channel_id, member_id,
                               operation_id):
        self._require_local(profile)
        if (not isinstance(member_id, str) or not isinstance(operation_id, str)
                or not operation_id):
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") not in {"owner", "admin"}:
                raise ApiFailure("forbidden")
            try:
                outcome = self._service.offer_workspace_channel_transfer(
                    workspace_id, channel_id, member_id, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            state = outcome.get("state")
            if state not in {"offered", "pending", "accepted"}:
                raise ApiFailure("internal")
            return "offered"

    def accept_channel_transfer(self, profile, workspace_id, channel_id, operation_id):
        self._require_local(profile)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            local_member = workspace.get("local_member_id")
            transfer = None
            for item in self._store.list("workspace_channel_transfer"):
                if (item.get("workspace_id") == workspace_id
                        and item.get("channel_id") == channel_id
                        and item.get("successor_member_id") == local_member
                        and item.get("state") == "offered"):
                    transfer = item
                    break
            if transfer is None or not isinstance(transfer.get("id"), str):
                channel = self._channel(workspace_id, channel_id)
                if channel.get("manager_member_id") == local_member:
                    return "accepted"
                raise ApiFailure("forbidden")
            try:
                accepted = self._service.accept_workspace_channel_transfer(
                    workspace_id, transfer["id"], operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            if accepted.get("manager_member_id") != local_member:
                raise ApiFailure("internal")
            return "accepted"

    def update_policies(self, profile, workspace_id, channel_creation, posting,
                        invitation_requests, operation_id):
        self._require_local(profile)
        if (channel_creation not in {"all_members", "owner_and_admins"}
                or posting not in {"all_members", "owner_and_admins"}
                or invitation_requests not in {"owner_only", "owner_and_admins",
                                               "all_members_request"}
                or not isinstance(operation_id, str) or not operation_id):
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            try:
                self._service.update_workspace_policies(
                    workspace_id, channel_creation, posting, operation_id,
                    invitation_requests)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            updated = self._workspace(workspace_id)
            policies = updated.get("policies")
            if not isinstance(policies, dict):
                raise ApiFailure("internal")
            applied = WorkspacePolicies(
                policies.get("channel_creation"), policies.get("posting"),
                policies.get("invitation_requests"))
            if applied != WorkspacePolicies(channel_creation, posting,
                                             invitation_requests):
                raise ApiFailure("internal")
            return applied

    def devices(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            workspace = self._workspace(workspace_id)
            snapshot = self._service.workspace_snapshot()
            summaries = snapshot.get("workspaces", [])
            if not isinstance(summaries, list):
                raise ApiFailure("internal")
            summary = next(
                (item for item in summaries
                 if isinstance(item, dict) and item.get("id") == workspace_id),
                None)
            if summary is None:
                raise ApiFailure("internal")
            members = summary.get("members", [])
            if not isinstance(members, list):
                raise ApiFailure("internal")
            found = []
            for member in members:
                member_id = member.get("id")
                devices = member.get("devices", [])
                if not isinstance(member_id, str) or not isinstance(devices, list):
                    raise ApiFailure("internal")
                for item in devices:
                    device_id = item.get("id")
                    if not isinstance(device_id, str):
                        raise ApiFailure("internal")
                    found.append(DeviceSummary(
                        device_id, member_id,
                        device_id == workspace.get("local_device_id")))
                if len(found) > 24:
                    raise ApiFailure("internal")
            return tuple(sorted(found, key=lambda item: item.device))

    def device_ids(self, profile, workspace_id):
        self._require_local(profile)
        with storage_errors():
            self._workspace(workspace_id)
            found = {item.device for item in self.devices(profile, workspace_id)}
            for item in self._store.list("workspace_device_transition"):
                if (item.get("workspace_id") == workspace_id
                        and item.get("transition_kind") == "removal"
                        and item.get("state") in {"pending", "approved", "declined"}
                        and isinstance(item.get("device_id"), str)):
                    found.add(item["device_id"])
            return tuple(sorted(found))

    def remove_device(self, profile, workspace_id, device_id, operation_id):
        self._require_local(profile)
        if (not isinstance(device_id, str) or not isinstance(operation_id, str)
                or not operation_id):
            raise ApiFailure("invalid_request")
        with storage_errors():
            workspace = self._workspace(workspace_id)
            if workspace.get("local_role") != "owner":
                raise ApiFailure("forbidden")
            if device_id == workspace.get("local_device_id"):
                raise ApiFailure("invalid_request")
            known = {item.device for item in self.devices(profile, workspace_id)}
            if device_id not in known:
                settled = any(
                    item.get("workspace_id") == workspace_id
                    and item.get("transition_kind") == "removal"
                    and item.get("device_id") == device_id
                    and item.get("state") == "approved"
                    for item in self._store.list("workspace_device_transition"))
                if settled:
                    return "removed"
                raise ApiFailure("forbidden")
            try:
                requested = self._service.request_workspace_device_removal(
                    workspace_id, device_id, operation_id)
            except (ValidationError, ContactNotApproved) as error:
                raise ApiFailure("invalid_request") from error
            state, removal_id = requested.get("state"), requested.get("id")
            if not isinstance(removal_id, str) or state not in {"pending", "approved"}:
                raise ApiFailure("internal")
            if state == "pending":
                approval_id = str(uuid.uuid5(uuid.UUID(operation_id),
                                             "device-removal-approve"))
                try:
                    outcome = self._service.approve_workspace_device_removal(
                        workspace_id, removal_id, approval_id)
                except (ValidationError, ContactNotApproved) as error:
                    raise ApiFailure("invalid_request") from error
                if outcome.get("state") != "approved":
                    raise ApiFailure("internal")
            remaining = {item.device for item in self.devices(profile, workspace_id)}
            if device_id in remaining:
                raise ApiFailure("internal")
            return "removed"
