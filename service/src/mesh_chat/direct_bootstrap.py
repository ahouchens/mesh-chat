"""Workspace bootstrap scope over the shared isolated packet mechanism."""
import uuid

from .direct_packet_adapter import scoped_message_allowed
from .errors import ValidationError
from .isolated_bootstrap import IsolatedBootstrapEngine
from .workspace_wire import build_workspace_fields, parse_workspace_payload


class WorkspaceBootstrapScope:
    KINDS = frozenset({"workspace_join", "workspace_join_receipt", "workspace_manifest_root", "workspace_direct_binding"})

    def __init__(self, workspace_id):
        try:
            if str(uuid.UUID(workspace_id)) != workspace_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Bootstrap workspace is invalid") from exc
        self.workspace_id = workspace_id

    def accepts(self, message, local, peer):
        return (scoped_message_allowed(message, peer, self.workspace_id, pending=True)
                and parse_workspace_payload(message).kind in self.KINDS)

    def fields(self, kind, logical_id, document, expires_at, local, peer):
        if kind not in self.KINDS:
            raise ValidationError("Bootstrap payload is not permitted")
        return build_workspace_fields(kind=kind, logical_id=logical_id, workspace_id=self.workspace_id,
                                      expires_at=expires_at, document=document)


class BootstrapEngine(IsolatedBootstrapEngine):
    KINDS = WorkspaceBootstrapScope.KINDS

    def __init__(self, private_identity, peer_identity, workspace_id, expires_at, *, directory=None):
        super().__init__(private_identity, peer_identity, expires_at,
                         WorkspaceBootstrapScope(workspace_id), directory=directory)
