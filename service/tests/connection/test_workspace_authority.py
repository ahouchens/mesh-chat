"""Workspace persistence must fence cached connection authority before mutation."""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from mesh_chat.workspace_authority import WorkspaceAuthorityStore


class Store:
    def __init__(self):
        self.values = {("workspace", "sealed-key"): {
            "id": "workspace-a", "state": "active", "manifest_hash": "old"}}
        self.before_write = lambda: None
        self.replay = None

    def get(self, kind, key):
        return deepcopy(self.values.get((kind, key)))

    def put_and_delete(self, records, deletions=(), **kwargs):
        self.before_write()
        for kind, key, value in records:
            self.values[kind, key] = deepcopy(value)
        for key in deletions:
            self.values.pop(key, None)

    def put_many(self, records):
        self.put_and_delete(records)

    def commit_operation(self, operation_id, digest, outcome, records, deletions=(), **kwargs):
        self.put_and_delete(records, deletions, **kwargs)
        return outcome

    def operation_result(self, operation_id, digest):
        return self.replay


@pytest.fixture
def persistence():
    store = Store()
    fenced = set()
    @contextmanager
    def guard(scope):
        fenced.add(scope)
        yield
        fenced.remove(scope)
    return WorkspaceAuthorityStore(store, guard), store, fenced


@pytest.mark.parametrize("write", ["put", "put_many", "commit_operation", "put_and_delete", "delete"])
def test_every_workspace_write_form_denies_old_authority_before_durable_work(persistence, write):
    guarded, store, fenced = persistence
    def verify_fence():
        assert fenced == {("workspace", "workspace-a")}
    store.before_write = verify_fence
    record = ("workspace", "sealed-key", {"id": "workspace-a", "state": "removed"})
    if write == "put":
        guarded.put(*record)
    elif write == "delete":
        guarded.delete("workspace", "sealed-key")
    elif write == "commit_operation":
        assert guarded.commit_operation("op", "digest", {"done": True}, [record]) == {"done": True}
    else:
        getattr(guarded, write)(iter([record]))
    assert not fenced


def test_failed_revocation_keeps_denial_and_unrelated_write_cannot_clear_it(persistence):
    guarded, store, fenced = persistence
    def fail():
        assert fenced == {("workspace", "workspace-a")}
        raise OSError("write failed")
    store.before_write = fail
    changed = {**store.get("workspace", "sealed-key"), "state": "leaving"}
    with pytest.raises(OSError):
        guarded.put("workspace", "sealed-key", changed)
    store.before_write = lambda: None
    guarded.put("workspace", "sealed-key", {**store.get("workspace", "sealed-key"), "unread_count": 9})
    assert fenced == {("workspace", "workspace-a")}
    guarded.put("workspace", "sealed-key", changed)
    assert not fenced


def test_metadata_and_non_authority_records_do_not_interrupt_connections(persistence):
    guarded, store, fenced = persistence
    def verify_unfenced():
        assert not fenced
    store.before_write = verify_unfenced
    guarded.put_many([
        ("workspace", "sealed-key", {**store.get("workspace", "sealed-key"), "unread_count": 1}),
        ("workspace_message", "message", {"workspace_id": "workspace-a", "text": "hello"}),
    ])


def test_cached_mutation_result_cannot_release_a_failed_authority_fence(persistence):
    guarded, store, fenced = persistence
    fenced.add(("workspace", "workspace-a"))
    store.replay = {"saved": True}
    result = guarded.commit_operation("op", "digest", {}, [
        ("workspace", "sealed-key", {"id": "workspace-a", "state": "removed"})])
    assert result == {"saved": True}
    assert fenced == {("workspace", "workspace-a")}
