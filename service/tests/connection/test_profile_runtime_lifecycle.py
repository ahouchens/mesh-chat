"""Trusted host slot factories with actual protected vaults and service owners."""
import os
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.errors import NativeUnavailable, ValidationError
from mesh_chat.native_profile_lifecycle import ProfileLifecycleResync, ProfileRuntimeLifecycle, ProfileSlot
from mesh_chat.native_webrtc_host import HOST_METHODS
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    monkeypatch.setattr(ConnectionRuntime, "start", lambda *_: None)
    native = SimpleNamespace(**{name: lambda *_: pytest.fail("Lifecycle allocated a peer") for name in HOST_METHODS})
    keys = {name: os.urandom(32) for name in ("alpha", "beta")}
    opened, published, selected = [], [], []

    def open_profile(name):
        directory = tmp_path / name
        store = VaultStore(directory, keys[name], allow_unprotected_for_tests=True)
        service = MeshChatService(store, directory, lambda _: None,
                                  connection_policy="shared-native", native_webrtc_host=native)
        opened.append(service)
        if store.get("profile", "local") is None:
            service.create_profile(name, operation_id=str(uuid4()))
        return service

    initial = open_profile("alpha")
    manager = ProfileRuntimeLifecycle(tuple(ProfileSlot(name, lambda name=name: open_profile(name)) for name in keys),
        "alpha", active=initial, publish=published.append, remember_selection=selected.append)
    yield manager, open_profile, opened, published, selected
    for service in opened:
        service.close()


def request(manager, action, profile=None):
    state = manager.query()
    return dict(action=action, profile_id=profile or state["selected_profile"], operation_id=str(uuid4()),
                host_incarnation=state["host_incarnation"], expected_revision=state["revision"])


def test_select_locks_exact_current_owner_before_new_profile_can_unlock(profiles):
    manager, _, opened, published, selected = profiles
    old = manager.active
    assert manager.mutate(**request(manager, "select", "beta"))["state"] == "locked"
    assert old._store_closed and old._identity is None and old.network is None
    assert manager.active is None and selected == ["beta"] and len(opened) == 1
    unlocked = manager.mutate(**request(manager, "unlock"))
    assert unlocked["state"] == "unlocked" and manager.active is opened[1]
    assert unlocked["service_incarnation"] != old._runtime_incarnation
    assert published == [None, opened[1]]


def test_unlock_reply_replay_never_reopens_after_later_explicit_lock(profiles):
    manager, _, opened, _, _ = profiles
    intent = request(manager, "unlock")
    first = manager.mutate(**intent)
    assert manager.mutate(**intent) == first and len(opened) == 1
    identity = manager.active._require_profile()["identity_hash"]
    manager.mutate(**request(manager, "lock"))
    with pytest.raises(ProfileLifecycleResync):
        manager.mutate(**intent)
    assert len(opened) == 1
    manager.mutate(**request(manager, "unlock"))
    assert len(opened) == 2 and manager.active._require_profile()["identity_hash"] == identity


def test_failed_close_keeps_instance_and_denies_competing_open_until_reconciled(profiles, monkeypatch):
    manager, _, opened, _, _ = profiles
    old = manager.active
    original = old.close
    def failed_close(): raise OSError("close failed")
    monkeypatch.setattr(old, "close", failed_close)
    intent = request(manager, "lock")
    with pytest.raises(NativeUnavailable): manager.mutate(**intent)
    assert manager.query()["state"] == "retiring" and old._shutdown.is_set()
    with pytest.raises(NativeUnavailable): manager.mutate(**request(manager, "unlock"))
    assert len(opened) == 1 and not old._store_closed
    monkeypatch.setattr(old, "close", original)
    assert manager.reconcile()["state"] == "locked"
    assert old._store_closed and manager.mutate(**intent)["state"] == "locked"


def test_deferred_retirement_cannot_admit_another_profile_and_reconcile_does_not_open(profiles):
    manager, _, opened, _, _ = profiles
    old, released = manager.active, threading.Event()
    old._pending_contact_carriers = {"pending": SimpleNamespace(close=lambda: None, wait=released.wait)}
    try:
        assert manager.mutate(**request(manager, "lock"))["state"] == "retiring"
        with pytest.raises(NativeUnavailable): manager.mutate(**request(manager, "select", "beta"))
        assert not old._store_closed and len(opened) == 1
    finally:
        released.set()
        old._close_finalizer.join(3)
    assert manager.reconcile()["state"] == "locked" and len(opened) == 1


def test_failed_selection_persistence_cannot_switch_or_open_target(profiles, monkeypatch):
    manager, _, opened, _, selected = profiles
    def failed_remember(_): raise OSError("metadata commit failed")
    monkeypatch.setattr(manager, "_remember_selection", failed_remember)
    intent = request(manager, "select", "beta")
    with pytest.raises(NativeUnavailable): manager.mutate(**intent)
    assert manager.query()["selected_profile"] == "alpha" and manager.active is None
    assert len(opened) == 1
    monkeypatch.setattr(manager, "_remember_selection", selected.append)
    assert manager.mutate(**intent)["selected_profile"] == "beta" and selected == ["beta"]
    assert len(opened) == 1


def test_open_publication_failure_retains_new_instance_and_needs_fresh_authorized_retry(profiles, monkeypatch):
    manager, _, opened, published, _ = profiles
    manager.mutate(**request(manager, "lock"))
    def failed_publish(value):
        if value is not None: raise OSError("publish failed")
        published.append(value)
    monkeypatch.setattr(manager, "_publish", failed_publish)
    intent = request(manager, "unlock")
    with pytest.raises(NativeUnavailable): manager.mutate(**intent)
    failed = opened[-1]
    assert failed._shutdown.is_set() and manager.query()["state"] == "retiring"
    assert manager.reconcile()["state"] == "locked"
    assert failed._store_closed and len(opened) == 2
    monkeypatch.setattr(manager, "_publish", published.append)
    assert manager.mutate(**intent)["state"] == "unlocked" and len(opened) == 3


def test_old_host_incarnation_or_stale_revision_never_calls_key_provider(profiles):
    manager, _, opened, _, _ = profiles
    old = request(manager, "unlock")
    old["host_incarnation"] = uuid4().hex
    with pytest.raises(ProfileLifecycleResync): manager.mutate(**old)
    stale = request(manager, "unlock")
    manager.mutate(**request(manager, "lock"))
    with pytest.raises(ProfileLifecycleResync): manager.mutate(**stale)
    assert len(opened) == 1


def test_same_operation_changed_action_is_conflict_without_effect(profiles):
    manager, _, opened, _, _ = profiles
    intent = request(manager, "unlock")
    manager.mutate(**intent)
    with pytest.raises(ValidationError, match="different input"):
        manager.mutate(**{**intent, "action": "lock"})
    assert manager.active is opened[0] and not opened[0]._shutdown.is_set()


def test_failed_clear_publication_still_closes_exact_old_owner_and_retains_transition(profiles, monkeypatch):
    manager, _, opened, published, _ = profiles
    old = manager.active
    def failed_publish(_): raise OSError("clear publication failed")
    monkeypatch.setattr(manager, "_publish", failed_publish)
    with pytest.raises(NativeUnavailable): manager.mutate(**request(manager, "lock"))
    assert old._store_closed and old._identity is None
    assert manager.query()["state"] == "retiring" and len(opened) == 1
    monkeypatch.setattr(manager, "_publish", published.append)
    assert manager.reconcile()["state"] == "locked" and len(opened) == 1


def test_selection_committed_return_loss_is_confirmed_without_second_write_or_open(profiles, monkeypatch):
    manager, _, opened, _, selected = profiles
    def committed_then_lost(target):
        selected.append(target)
        raise OSError("selection committed but return lost")
    monkeypatch.setattr(manager, "_remember_selection", committed_then_lost)
    monkeypatch.setattr(manager, "_read_selection", lambda: selected[-1])
    intent = request(manager, "select", "beta")
    result = manager.mutate(**intent)
    assert result["state"] == "locked" and result["selected_profile"] == "beta"
    assert manager.mutate(**intent) == result
    assert selected == ["beta"] and len(opened) == 1


def test_deferred_selection_persists_new_slot_only_after_old_workers_drain(profiles):
    manager, _, opened, _, selected = profiles
    old, released = manager.active, threading.Event()
    old._pending_contact_carriers = {"pending": SimpleNamespace(close=lambda: None, wait=released.wait)}
    intent = request(manager, "select", "beta")
    try:
        pending = manager.mutate(**intent)
        assert pending["state"] == "retiring" and pending["selected_profile"] == "alpha"
        assert not selected and not old._store_closed
        with pytest.raises(NativeUnavailable): manager.mutate(**request(manager, "unlock", "beta"))
    finally:
        released.set()
        old._close_finalizer.join(3)
    result = manager.reconcile()
    assert result["state"] == "locked" and result["selected_profile"] == "alpha"
    assert selected == [] and len(opened) == 1
    assert manager.mutate(**intent)["selected_profile"] == "beta"
    assert selected == ["beta"]
    manager.mutate(**request(manager, "unlock", "beta"))
    assert len(opened) == 2 and old._store_closed


def test_host_restart_replay_uses_original_incarnation_and_never_opens(profiles):
    manager, _, opened, _, _ = profiles
    intent = request(manager, "unlock")
    manager.mutate(**intent)
    manager.mutate(**request(manager, "lock"))
    replacement = ProfileRuntimeLifecycle((ProfileSlot("alpha", lambda: pytest.fail("Replayed old host open")),),
        "alpha", publish=lambda _: None, remember_selection=lambda _: None)
    with pytest.raises(ProfileLifecycleResync): replacement.mutate(**intent)
    assert len(opened) == 1 and replacement.query()["state"] == "locked"


def test_close_can_wait_for_dispatch_worker_that_reads_lifecycle_without_lock_inversion(profiles, monkeypatch):
    manager, _, _, _, _ = profiles
    old = manager.active
    original = old.close
    observed = threading.Event()
    def close_with_dispatch_reader():
        def reader():
            with old._dispatch_lock:
                assert manager.query()["state"] == "retiring"
                observed.set()
        thread = threading.Thread(target=reader)
        thread.start()
        assert observed.wait(1), "Lifecycle state lock blocked dispatch callback during close"
        thread.join(1)
        original()
    monkeypatch.setattr(old, "close", close_with_dispatch_reader)
    assert manager.mutate(**request(manager, "lock"))["state"] == "locked"
    monkeypatch.setattr(old, "close", original)


def test_native_event_worker_must_drain_before_identity_and_vault_release(profiles):
    manager, _, _, _, _ = profiles
    old = manager.active
    original = old._native_webrtc_event_thread
    released = threading.Event()
    worker = threading.Thread(target=released.wait)
    worker.start()
    old._native_webrtc_event_thread = worker
    try:
        assert manager.mutate(**request(manager, "lock"))["state"] == "retiring"
        assert not old._store_closed and old._identity is not None
    finally:
        released.set()
        old._close_finalizer.join(3)
        original.join(1)
    assert old._store_closed and old._identity is None
    assert manager.reconcile()["state"] == "locked"


def test_existing_profile_outbox_recovery_failure_closes_unpublished_network_and_keys(profiles, monkeypatch):
    manager, _, _, _, _ = profiles
    old = manager.active
    key, directory = old.store._key, old.profile_dir
    manager.mutate(**request(manager, "lock"))
    captured, shutdown = [], []
    def start_network(service, _name):
        captured.append(service)
        service.network = SimpleNamespace(shutdown=lambda: shutdown.append(True) or True)
    def failed_recovery(_): raise OSError("outbox recovery unavailable")
    monkeypatch.setattr(MeshChatService, "_start_network", start_network)
    monkeypatch.setattr(MeshChatService, "_recover_outbox", failed_recovery)
    store = VaultStore(directory, key, allow_unprotected_for_tests=True)
    with pytest.raises(OSError, match="outbox recovery"):
        MeshChatService(store, directory, lambda _: None)
    failed, = captured
    assert shutdown == [True]
    assert failed._store_closed and failed._identity is None and failed.network is None


def test_malformed_trusted_opener_fails_typed_and_cannot_repeat_unknown_open(profiles):
    manager, _, opened, _, _ = profiles
    manager.mutate(**request(manager, "lock"))
    calls = []
    manager._slots["alpha"] = ProfileSlot("alpha", lambda: calls.append(True))
    intent = request(manager, "unlock")
    with pytest.raises(NativeUnavailable, match="ownership contract"):
        manager.mutate(**intent)
    assert manager.query()["state"] == "retiring" and manager.active is None
    with pytest.raises(NativeUnavailable): manager.mutate(**intent)
    with pytest.raises(NativeUnavailable): manager.reconcile()
    assert calls == [True] and len(opened) == 1
