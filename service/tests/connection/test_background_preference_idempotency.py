"""Background intent replay over the real service and encrypted vault.

Only network startup and the external supervisor are replaced. Preference and
operation receipts use the production vault transaction, including fault tests.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
import threading
from uuid import uuid4

import pytest

from mesh_chat.background_availability import KIND
from mesh_chat.errors import ValidationError
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    native = {"enabled": False, "service_running": False, "runtime_initialized": False}
    monkeypatch.setattr(MeshChatService, "_native_background_status", lambda _: dict(native))
    effects = []
    events = []

    class Supervisor:
        def __init__(self, service):
            self.service = service

        def start(self):
            effects.append(("start", self.service._background_availability_record(),
                            self.service.store.list("workspace_operation")))

        def stop(self):
            effects.append(("stop", self.service._background_availability_record(),
                            self.service.store.list("workspace_operation")))

    monkeypatch.setattr("mesh_chat.background_reconnect.BackgroundReconnectSupervisor", Supervisor)
    key = os.urandom(32)
    opened = []

    def open_host():
        store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
        service = MeshChatService(store, tmp_path, events.append)
        if store.get("profile", "local") is None:
            service.create_profile("Background owner")
        opened.append(service)
        return service

    yield open_host, effects, events, native
    for service in opened:
        service.close()


def preference(service):
    return service.store.get(KIND, service._background_availability_id())


@pytest.mark.parametrize("enabled", [False, True])
def test_preference_and_intent_receipt_commit_before_runtime_effects(hosts, enabled):
    open_host, effects, events, _ = hosts
    service = open_host()
    operation = str(uuid4())
    first = service.set_background_availability(enabled, operation_id=operation)
    record = preference(service)
    receipt = service.store.list("workspace_operation")
    assert first["enabled"] is enabled
    assert record["last_reason"] == ("user_enabled" if enabled else "user_disabled")
    assert len(receipt) == 1 and receipt[0]["outcome"] == {"enabled": enabled}
    if enabled:
        assert len(effects) == 1 and effects[0] == ("start", record, receipt)
    else:
        assert effects == []
    event_count = len(events)
    assert service.set_background_availability(enabled, operation_id=operation) == first
    assert preference(service) == record
    assert service.store.list("workspace_operation") == receipt
    assert len(events) == event_count
    assert len(effects) == int(enabled)


def test_same_key_cannot_change_payload(hosts):
    open_host, effects, _, _ = hosts
    service = open_host()
    operation = str(uuid4())
    service.set_background_availability(True, operation_id=operation)
    before = preference(service)
    with pytest.raises(ValidationError, match="already used with different input"):
        service.set_background_availability(False, operation_id=operation)
    assert preference(service) == before
    assert len(service.store.list("workspace_operation")) == 1
    assert [effect[0] for effect in effects] == ["start"]


@pytest.mark.parametrize("enabled", [False, True])
def test_failed_real_commit_rolls_back_preference_and_receipt_before_effects(hosts, monkeypatch, enabled):
    open_host, effects, events, _ = hosts
    service = open_host()
    service.set_background_availability(not enabled)
    before = preference(service)
    settings = deepcopy(service.settings.to_dict())
    settings_record = service.store.get("settings", "network")
    event_count, effect_count = len(events), len(effects)
    original = service.store._write_records_locked

    def fail_after_writes(*args):
        original(*args)
        raise OSError("injected background transaction failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail_after_writes)
    operation = str(uuid4())
    with pytest.raises(OSError, match="injected"):
        service.set_background_availability(enabled, operation_id=operation)
    assert preference(service) == before
    assert service.store.list("workspace_operation") == []
    assert service.settings.to_dict() == settings
    assert service.store.get("settings", "network") == settings_record
    assert (len(events), len(effects)) == (event_count, effect_count)
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert service.set_background_availability(enabled, operation_id=operation)["enabled"] is enabled
    assert len(service.store.list("workspace_operation")) == 1


@pytest.mark.parametrize("failure", ["_changed", "_sync_background_reconnect"])
def test_post_commit_failure_replays_current_intent_without_another_commit(hosts, monkeypatch, failure):
    open_host, effects, _, _ = hosts
    service = open_host()
    original = getattr(service, failure)

    def fail_effect():
        raise RuntimeError("injected after commit")

    monkeypatch.setattr(service, failure, fail_effect)
    operation = str(uuid4())
    with pytest.raises(RuntimeError, match="after commit"):
        service.set_background_availability(True, operation_id=operation)
    record = preference(service)
    receipt = service.store.list("workspace_operation")
    assert record["enabled"] and len(receipt) == 1
    assert effects == []
    monkeypatch.setattr(service, failure, original)
    assert service.set_background_availability(True, operation_id=operation)["enabled"]
    assert preference(service) == record
    assert service.store.list("workspace_operation") == receipt
    assert [effect[0] for effect in effects] == ["start"]


@pytest.mark.parametrize("superseding", ["keyed_disable", "keyless_disable", "lock"])
def test_old_enable_replay_cannot_override_later_disable_or_lock(hosts, superseding):
    open_host, effects, _, native = hosts
    service = open_host()
    operation = str(uuid4())
    service.set_background_availability(True, operation_id=operation)
    if superseding == "keyed_disable":
        service.set_background_availability(False, operation_id=str(uuid4()))
    elif superseding == "keyless_disable":
        service.set_background_availability(False)
    else:
        service.lock_background_availability()
    record = preference(service)
    native.update(enabled=True, service_running=True, runtime_initialized=True)
    again = service.set_background_availability(True, operation_id=operation)
    assert again["enabled"] is False and again["health"] == "off"
    assert again["state"] == ("locked" if superseding == "lock" else "disabled")
    assert preference(service) == record
    assert [effect[0] for effect in effects] == ["start", "stop"]


def test_old_disable_replay_projects_a_newer_enabled_preference(hosts):
    open_host, effects, _, _ = hosts
    service = open_host()
    operation = str(uuid4())
    service.set_background_availability(False, operation_id=operation)
    service.set_background_availability(True, operation_id=str(uuid4()))
    record = preference(service)
    assert service.set_background_availability(False, operation_id=operation)["enabled"] is True
    assert preference(service) == record
    assert [effect[0] for effect in effects] == ["start"]


@pytest.mark.parametrize("revocation", ["identity_locked", "shutdown", "missing_profile"])
def test_current_local_authority_is_checked_before_replay(hosts, revocation):
    open_host, effects, _, _ = hosts
    service = open_host()
    operation = str(uuid4())
    service.set_background_availability(False, operation_id=operation)
    receipt = service.store.list("workspace_operation")
    if revocation == "identity_locked":
        service._identity = None
    elif revocation == "shutdown":
        service._shutdown.set()
    else:
        service.store.delete("profile", "local")
    with pytest.raises(ValidationError):
        service.set_background_availability(False, operation_id=operation)
    assert service.store.list("workspace_operation") == receipt
    assert effects == []


def test_orderly_close_and_reopen_supersedes_old_enable_receipt(hosts):
    open_host, effects, _, native = hosts
    service = open_host()
    operation = str(uuid4())
    service.set_background_availability(True, operation_id=operation)
    service.close()
    reopened = open_host()
    record = preference(reopened)
    native.update(enabled=True, service_running=True, runtime_initialized=True)
    assert reopened.set_background_availability(True, operation_id=operation)["enabled"] is False
    assert preference(reopened) == record and record["last_reason"] == "service_closed"
    assert len(reopened.store.list("workspace_operation")) == 1
    assert [effect[0] for effect in effects] == ["start", "stop"]


def test_post_commit_failure_and_process_loss_preserve_receipt_and_current_runtime(hosts, monkeypatch):
    open_host, effects, _, native = hosts
    service = open_host()
    operation = str(uuid4())

    def fail_sync():
        raise RuntimeError("injected after preference commit")

    monkeypatch.setattr(service, "_sync_background_reconnect", fail_sync)
    with pytest.raises(RuntimeError, match="after preference commit"):
        service.set_background_availability(True, operation_id=operation)
    record = preference(service)
    receipt = service.store.list("workspace_operation")
    # Emulate process loss without close() committing its intentional disable.
    # Resource cleanup still runs; persisted records remain real vault writes.
    monkeypatch.setattr(service, "_background_availability_enabled", lambda: False)
    service.close()
    reopened = open_host()
    native.update(enabled=False, failure="foreground_start_denied")
    reopened.store.put("workspace_lifecycle_state", reopened._workspace_lifecycle_id(), {"state": "suspended"})
    result = reopened.set_background_availability(True, operation_id=operation)
    assert result["enabled"] is True and result["health"] == "failed"
    assert result["lifecycle_state"] == "suspended"
    assert preference(reopened) == record
    assert reopened.store.list("workspace_operation") == receipt
    assert [effect[0] for effect in effects] == ["start"]


def test_concurrent_same_key_enables_once(hosts):
    open_host, effects, _, _ = hosts
    service = open_host()
    operation = str(uuid4())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.set_background_availability(True, operation_id=operation), range(8)))
    assert all(result["enabled"] for result in results)
    assert len(service.store.list("workspace_operation")) == 1
    assert [effect[0] for effect in effects] == ["start"]


def test_lock_serializes_a_waiting_old_enable_replay(hosts):
    open_host, effects, _, _ = hosts
    service = open_host()
    operation = str(uuid4())
    service.set_background_availability(True, operation_id=operation)
    entered = threading.Event()

    def retry():
        entered.set()
        return service.set_background_availability(True, operation_id=operation)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with service._dispatch_lock:
            pending = pool.submit(retry)
            assert entered.wait(timeout=2)
            service.lock_background_availability()
        result = pending.result(timeout=2)
    assert result["enabled"] is False and result["state"] == "locked"
    assert [effect[0] for effect in effects] == ["start", "stop"]


@pytest.mark.parametrize("enabled", [0, 1, None, "true"])
def test_keyed_input_stays_boolean_and_does_not_commit(hosts, enabled):
    open_host, effects, _, _ = hosts
    service = open_host()
    with pytest.raises(ValidationError):
        service.set_background_availability(enabled, operation_id=str(uuid4()))
    assert preference(service) is None
    assert service.store.list("workspace_operation") == []
    assert effects == []


@pytest.mark.parametrize("operation", ["", "not-a-uuid", 1])
def test_invalid_operation_identity_does_not_commit(hosts, operation):
    open_host, effects, _, _ = hosts
    service = open_host()
    with pytest.raises(ValidationError, match="Operation ID"):
        service.set_background_availability(True, operation_id=operation)
    assert preference(service) is None
    assert service.store.list("workspace_operation") == []
    assert effects == []
