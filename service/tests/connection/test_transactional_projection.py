"""Storage projections participate in the original encrypted transaction."""

import os

import pytest

from mesh_chat.errors import StorageUnavailable
from mesh_chat.vault import VaultStore


@pytest.fixture
def store(tmp_path):
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as vault:
        yield vault


def install_projection(store):
    from mesh_chat.record_projection import Projection
    observed = []
    def project(changes):
        writes = []
        for change in changes:
            observed.append(change)
            writes.append(("journal", change.identifier, {"removed": change.after is None}))
        return Projection(tuple(writes))
    store.register_projection("source", project)
    return observed


@pytest.mark.parametrize("method", ["put", "put_many", "put_and_delete", "update_record", "update_records", "commit_operation", "delete"])
def test_every_record_mutation_projects_its_committed_change(store, method):
    store.put("source", "one", {"version": 1})
    observed = install_projection(store)
    value = {"version": 2}
    if method == "put": store.put("source", "one", value)
    if method == "put_many": store.put_many([("source", "one", value)])
    if method == "put_and_delete": store.put_and_delete([("source", "one", value)])
    if method == "update_record": store.update_record("source", "one", lambda _: value)
    if method == "update_records": store.update_records([("source", "one")], lambda _: {("source", "one"): value})
    if method == "commit_operation": store.commit_operation("operation", "ab" * 32, {}, [("source", "one", value)])
    if method == "delete": store.delete("source", "one")
    assert store.get("journal", "one") == {"removed": method == "delete"}
    assert len(observed) == 1
    assert observed[0].before == {"version": 1}
    assert observed[0].after == (None if method == "delete" else value)


@pytest.mark.parametrize("failure", ["projection", "seal", "commit"])
def test_source_and_projection_roll_back_together(store, monkeypatch, failure):
    store.put("source", "one", {"version": 1})
    install_projection(store)
    if failure == "projection":
        def fail(_):
            raise StorageUnavailable("projection failed")
        store.register_projection("other", fail)
    if failure == "seal":
        original = store._seal
        def seal(kind, *args):
            if kind == "journal": raise StorageUnavailable("journal failed")
            return original(kind, *args)
        monkeypatch.setattr(store, "_seal", seal)
    if failure == "commit":
        database = store._db
        class FailCommit:
            def execute(self, sql, *args):
                if sql == "COMMIT": raise StorageUnavailable("commit failed")
                return database.execute(sql, *args)
            def __getattr__(self, name): return getattr(database, name)
        monkeypatch.setattr(store, "_db", FailCommit())
    with pytest.raises(StorageUnavailable):
        store.put_many([("source", "one", {"version": 2}), ("other", "two", {})])
    assert store.get("source", "one") == {"version": 1}
    assert store.get("other", "two") is None
    assert not store.list("journal")


def test_replayed_operation_does_not_project_twice(store):
    observed = install_projection(store)
    for _ in range(2):
        store.commit_operation("operation", "ab" * 32, {}, [("source", "one", {})])
    assert len(observed) == 1


def test_projection_sees_final_batch_state_and_cannot_replace_source(store):
    from mesh_chat.record_projection import Projection
    from mesh_chat.errors import ValidationError
    observed = install_projection(store)
    store.put_and_delete([("source", "one", {"version": 1}), ("source", "one", {"version": 2})], [("source", "one")])
    assert len(observed) == 1 and observed[0].after == {"version": 2}
    store.register_projection("attack", lambda _: Projection((("source", "one", {}),)))
    with pytest.raises(ValidationError):
        store.put_many([("source", "one", {"version": 3}), ("attack", "one", {})])
    assert store.get("source", "one") == {"version": 2}
