"""Fence connection leases around workspace authority transactions.

The vault remains unaware of connection policy. This application adapter selects
authority-bearing changes and preserves the vault's atomic writes and replay.
"""

from contextlib import ExitStack, contextmanager

from .errors import ValidationError


AUTHORITY_FIELDS = (
    "id", "state", "manifest_hash", "genesis_digest", "local_member_id", "local_device_id",
    "local_role", "authorization_generation",
)


def signature(workspace):
    return tuple(workspace.get(field) for field in AUTHORITY_FIELDS) if workspace else None


class WorkspaceAuthorityStore:
    def __init__(self, store, authority_update):
        self._store = store
        self._authority_update = authority_update

    def put(self, kind, record_id, value):
        self.put_many([(kind, record_id, value)])

    def put_many(self, records):
        self.put_and_delete(records)

    def put_and_delete(self, records, deletions=(), *, redact_command_cache=False):
        records, deletions = list(records), list(deletions)
        with self._guard(records, deletions):
            self._store.put_and_delete(records, deletions, redact_command_cache=redact_command_cache)

    def delete(self, kind, record_id):
        self.put_and_delete([], [(kind, record_id)])

    def commit_operation(self, operation_id, input_digest, outcome, records, deletions=(),
                         *, redact_command_cache=False):
        replay = self._store.operation_result(operation_id, input_digest)
        if replay is not None:
            return replay
        records, deletions = list(records), list(deletions)
        with self._guard(records, deletions):
            return self._store.commit_operation(operation_id, input_digest, outcome, records, deletions,
                                                redact_command_cache=redact_command_cache)

    @contextmanager
    def _guard(self, records, deletions):
        changes = [(key, value) for kind, key, value in records if kind == "workspace"]
        changes.extend((key, None) for kind, key in deletions if kind == "workspace")
        scopes = set()
        for key, value in changes:
            previous = self._store.get("workspace", key)
            if signature(previous) == signature(value):
                continue
            for workspace in (previous, value):
                if workspace is not None:
                    workspace_id = workspace.get("id")
                    if not isinstance(workspace_id, str) or not workspace_id:
                        raise ValidationError("Workspace authority identity is missing")
                    scopes.add(("workspace", workspace_id))
        with ExitStack() as stack:
            for scope in sorted(scopes):
                stack.enter_context(self._authority_update(scope))
            yield
