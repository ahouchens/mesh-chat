"""Intent batches use real vault commits; native disposal is observed separately."""

import os
from types import SimpleNamespace

import pytest

from mesh_chat.carrier_journal import CarrierBinding, CarrierJournal
from mesh_chat.reconnect_service import ReconnectServiceMixin
from mesh_chat.vault import VaultStore


@pytest.fixture
def intents(tmp_path):
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        profiles = [{"id": name, "contact_id": name, "active": False, "state": "stopped",
                     "auto_reconnect": True, "remote_auto_reconnect": True} for name in ("a", "b")]
        for profile in profiles:
            store.put("reconnect_profile", profile["id"], profile)
            store.put("contact", profile["id"], {"id": profile["id"], "trust": "approved"})
        calls = []
        service = ReconnectServiceMixin()
        service.store = store
        service._connection_runtime = SimpleNamespace(
            fence=lambda target: calls.append(("fence", target)),
            committed_start=lambda target: calls.append(("resume", target)))
        service._reconnect_contact = lambda target: store.get("contact", target)
        service._reconnect_profile_for_contact = lambda target: store.get("reconnect_profile", target)
        service._changed = lambda: calls.append(("changed", None))
        service.reconnect_status = lambda: {"profiles": store.list("reconnect_profile")}
        service.retire_unmanaged_native_connections = lambda targets: calls.append(("retire", targets))
        service._carrier_journal = CarrierJournal(store)
        binding = CarrierBinding("resource", "a" * 32, "a", "a", "contact", None,
                                 "local", "remote", "b" * 32, "relay", "offer", "c" * 64, "d" * 64)
        service._carrier_journal.save(binding, service._carrier_journal.revision())
        yield service, calls


def fail_sealing_second_profile(store, monkeypatch):
    original = store._seal
    def seal(kind, identifier, value):
        if kind == "reconnect_profile" and identifier == "b":
            raise OSError("profile encryption failed")
        return original(kind, identifier, value)
    monkeypatch.setattr(store, "_seal", seal)


def test_start_batch_failure_cannot_commit_a_subset_or_release_a_fence(intents, monkeypatch):
    service, calls = intents
    before = service.store.list("reconnect_profile")
    fail_sealing_second_profile(service.store, monkeypatch)
    with pytest.raises(OSError): service.reconnect_start()
    assert service.store.list("reconnect_profile") == before
    assert not calls


def test_stop_batch_failure_preserves_old_intent_but_fences_and_invalidates_recovery(intents, monkeypatch):
    service, calls = intents
    service.reconnect_start()
    calls.clear()
    before = service.store.list("reconnect_profile")
    fail_sealing_second_profile(service.store, monkeypatch)
    with pytest.raises(OSError): service.reconnect_stop()
    assert service.store.list("reconnect_profile") == before
    assert calls == [("fence", None), ("retire", {"a", "b"})]
    assert not service._carrier_journal.bindings()
    assert service.store.get("reconnect_state", "current") is None


def test_global_stop_state_commits_in_the_same_batch_as_every_profile(intents, monkeypatch):
    service, _ = intents
    service.reconnect_start()
    before = service.store.list("reconnect_profile")
    original = service.store._seal
    def seal(kind, identifier, value):
        if kind == "reconnect_state": raise OSError("global intent encryption failed")
        return original(kind, identifier, value)
    monkeypatch.setattr(service.store, "_seal", seal)
    with pytest.raises(OSError): service.reconnect_stop()
    assert service.store.list("reconnect_profile") == before
    assert service.store.get("reconnect_state", "current") is None


def test_start_without_reciprocal_consent_cannot_clear_an_explicit_stop(intents):
    service, calls = intents
    profile = service.store.get("reconnect_profile", "a")
    service.store.put("reconnect_profile", "a", {**profile, "remote_auto_reconnect": False})
    service.reconnect_start("a")
    assert not calls
    assert service.store.get("reconnect_profile", "a")["state"] == "stopped"


def test_start_all_releases_only_the_contacts_with_committed_start_intent(intents):
    service, calls = intents
    profile = service.store.get("reconnect_profile", "b")
    service.store.put("reconnect_profile", "b", {**profile, "auto_reconnect": False})
    service.reconnect_start()
    assert [(kind, target) for kind, target in calls if kind == "resume"] == [("resume", "a")]
    assert service.store.get("reconnect_profile", "b")["state"] == "stopped"


def test_automatic_activation_cannot_release_fences_or_restart_explicit_stop(intents):
    service, calls = intents
    service.reconnect_start("a", automatic=True)
    assert not calls
    profile = service.store.get("reconnect_profile", "a")
    service.store.put("reconnect_profile", "a", {**profile, "state": "idle"})
    service.reconnect_start("a", automatic=True)
    assert calls == [("changed", None)]
    assert service.store.get("reconnect_profile", "a")["active"]


def test_legacy_native_closure_observes_the_whole_durable_stop_batch(intents):
    service, calls = intents
    service.reconnect_start()
    service._connection_runtime = None
    closed = []
    def close(profile):
        assert all(row["state"] == "stopped" for row in service.store.list("reconnect_profile"))
        assert service.store.get("reconnect_state", "current")["state"] == "stopped"
        closed.append(profile)
    service.close_native_reconnect_session = close
    service.reconnect_stop()
    assert set(closed) == {"a", "b"}


def test_per_contact_stop_does_not_change_other_intents_or_global_status(intents):
    service, calls = intents
    service.reconnect_start()
    service.store.put("reconnect_state", "current", {"state": "connected"})
    calls.clear()
    service.reconnect_stop("a")
    assert service.store.get("reconnect_profile", "a")["state"] == "stopped"
    assert service.store.get("reconnect_profile", "b")["active"]
    assert service.store.get("reconnect_state", "current") == {"state": "connected"}
    assert calls[:2] == [("fence", "a"), ("retire", {"a"})]


@pytest.mark.parametrize("operation", ["start", "stop"])
def test_commit_failure_rolls_back_the_complete_intent_batch(intents, operation):
    service, calls = intents
    if operation == "stop": service.reconnect_start()
    before = service.store.list("reconnect_profile")
    calls.clear()
    database = service.store._db
    class FailIntentCommit:
        def execute(self, statement, *args):
            if statement == "COMMIT" and self.intent_written:
                raise OSError("intent commit failed")
            return database.execute(statement, *args)
        def executemany(self, statement, rows):
            rows = list(rows)
            if any(row[0] == "reconnect_profile" for row in rows): self.intent_written = True
            return database.executemany(statement, rows)
        def __getattr__(self, name): return getattr(database, name)
        intent_written = False
    service.store._db = FailIntentCommit()
    try:
        with pytest.raises(OSError): getattr(service, "reconnect_" + operation)()
    finally:
        service.store._db = database
    assert service.store.list("reconnect_profile") == before
    assert not any(kind in {"changed", "resume"} for kind, _ in calls)
    if operation == "stop":
        assert calls[0] == ("fence", None)
        assert not service._carrier_journal.bindings()


def test_failed_global_stop_then_start_cannot_resume_an_unconsented_manual_peer(intents, monkeypatch):
    from mesh_chat.connection.model import Execution
    from mesh_chat.connection.runtime import ConnectionRuntime
    from test_runtime import Executor
    service, _ = intents
    for name in ("a", "b"):
        profile = service.store.get("reconnect_profile", name)
        service.store.put("reconnect_profile", name, {
            **profile, "active": True, "state": "connected", "auto_reconnect": name == "a",
            "local_device_id": "local", "remote_device_id": "remote",
            "manual_carrier_authorized": name == "b", "effective": {"ready": name == "a"},
        })
    owner = ConnectionRuntime("intent-test", lambda *_: Executor(),
        profiles=lambda: {"profiles": service.store.list("reconnect_profile")},
        execution=lambda: Execution.AVAILABLE, activate=lambda _: pytest.fail("Unexpected automatic start"))
    service._connection_runtime = owner
    try:
        owner.synchronize()
        assert all(item["desired"] == "enabled" for item in owner.snapshots().values())
        with monkeypatch.context() as fault:
            fail_sealing_second_profile(service.store, fault)
            with pytest.raises(OSError): service.reconnect_stop()
        owner.synchronize()
        assert all(item["desired"] == "stopped" for item in owner.snapshots().values())
        service.reconnect_start()
        owner.synchronize()
        assert owner.snapshots()["a"]["desired"] == "enabled"
        assert owner.snapshots()["b"]["desired"] == "stopped"
        assert not owner.permits_recovery(service.store.get("reconnect_profile", "b"))
        assert not service._carrier_journal.bindings()
    finally:
        owner.stop()
        owner.wait()


def test_profile_read_failure_still_fences_stop_before_storage_access(intents):
    service, calls = intents
    def fail(): raise OSError("profile read failed")
    service._reconnect_profiles_raw = fail
    with pytest.raises(OSError): service.reconnect_stop("a")
    assert calls == [("fence", "a")]


def test_legacy_native_failure_occurs_after_all_stop_intent_is_durable(intents):
    service, calls = intents
    service.reconnect_start()
    service._connection_runtime = None
    closed = []
    def fail(profile):
        closed.append(profile)
        if len(closed) == 1: raise OSError("native disposal failed")
    service.close_native_reconnect_session = fail
    with pytest.raises(OSError): service.reconnect_stop()
    assert all(row["state"] == "stopped" for row in service.store.list("reconnect_profile"))
    assert service.store.get("reconnect_state", "current")["state"] == "stopped"
    assert not service._carrier_journal.bindings()
    assert set(closed) == {"a", "b"}
