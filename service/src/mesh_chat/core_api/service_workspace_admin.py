"""Private adapter: workspace listing and join approval over domain transactions."""

from ..errors import ContactNotApproved, InvitationExpired, InvitationInvalid, ValidationError
from .errors import ApiFailure
from .service_messages import storage_errors
from .workspace_admin import JoinApproval, JoinRequestSummary, WorkspaceSummary


MAX_WORKSPACES = 16
MAX_JOIN_REQUESTS = 32
MAX_REQUEST_IDS = 64
ROLES = {"owner", "admin", "member"}
STATES = {"active", "joining", "left", "removed", "revoked", "archived"}


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
