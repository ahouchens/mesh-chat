"""Private adapter: workspace invitation preview and join over domain rules."""

from ..errors import InvitationExpired, InvitationInvalid, ValidationError
from .errors import ApiFailure
from .service_messages import storage_errors
from .workspace_relationship import WorkspaceJoin, WorkspacePreview


MAX_DOCUMENT = 1048576
JOIN_STATES = {"joining", "active", "pending", "left"}


class ServiceWorkspace:
    def __init__(self, service):
        self._service = service

    def _document(self, profile, document):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        if (not isinstance(document, str) or not 1 <= len(document) <= MAX_DOCUMENT):
            raise ApiFailure("invalid_request")

    def preview(self, profile, document):
        self._document(profile, document)
        with storage_errors():
            try:
                preview = self._service.preview_workspace_invitation(document)
            except (ValidationError, InvitationInvalid, InvitationExpired) as error:
                raise ApiFailure("invalid_request") from error
            name, description = preview.get("name"), preview.get("description", "")
            members, retention, expires = (preview.get("member_count"),
                                            preview.get("retention_days"),
                                            preview.get("expires_at"))
            if (not isinstance(name, str) or not name
                    or not isinstance(description, str)
                    or type(members) is not int or members < 1
                    or type(retention) is not int or not 1 <= retention <= 3650
                    or type(expires) not in {int, float}):
                raise ApiFailure("internal")
            return WorkspacePreview(name, description, members, retention, float(expires),
                                    bool(preview.get("requires_i2p_consent", False)))

    def join(self, profile, document, operation_id):
        self._document(profile, document)
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                workspace = self._service.submit_workspace_join(document, operation_id)
            except (ValidationError, InvitationInvalid, InvitationExpired) as error:
                raise ApiFailure("invalid_request") from error
            workspace_id, name, state = (workspace.get("id"), workspace.get("name"),
                                         workspace.get("state"))
            if (not isinstance(workspace_id, str) or not isinstance(name, str)
                    or state not in JOIN_STATES):
                raise ApiFailure("internal")
            return WorkspaceJoin(workspace_id, name, state)
