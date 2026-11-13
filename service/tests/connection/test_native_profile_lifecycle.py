"""Actual vault/profile commits; native ownership uses bounded recording ports."""
import os
from dataclasses import FrozenInstanceError, replace
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.connection import composition
from mesh_chat.connection.model import Execution
from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.native_webrtc_host import HOST_METHODS
from mesh_chat.native_profile_lifecycle import (
    CompletionFact, LifecycleRequest, ProfileLifecycleIdentityConflict,
    ProfileLifecycleResync, ProfileRuntimeLifecycle, ProfileSlot,
)
from mesh_chat.errors import NativeUnavailable, ValidationError
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


@pytest.fixture
def profile_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    monkeypatch.setattr(ConnectionRuntime, "start", lambda *_: None)
    native = SimpleNamespace(**{name: lambda *_: pytest.fail("Profile bootstrap allocated a peer") for name in HOST_METHODS})
    opened = []

    def create(directory=tmp_path):
        store = VaultStore(directory, os.urandom(32), allow_unprotected_for_tests=True)
        service = MeshChatService(store, directory, lambda _: None,
                                  connection_policy="shared-native", native_webrtc_host=native)
        opened.append(service)
        return service

    yield create, native
    for service in opened:
        service.close()


def test_keyed_profile_activates_existing_owner_once_after_committed_reply_loss(profile_runtime, monkeypatch):
    create, _ = profile_runtime
    service = create()
    owner = service._connection_runtime
    assert owner.owner.runtime_epoch == service._runtime_incarnation
    assert owner.execution() is Execution.LOCKED
    activated = []
    monkeypatch.setattr(owner, "synchronize", lambda: activated.append(service._identity.hash.hex()))
    original = service.store.commit_operation

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("profile committed but return lost")

    operation = str(uuid4())
    monkeypatch.setattr(service.store, "commit_operation", lost_reply)
    with pytest.raises(OSError, match="return lost"):
        service.create_profile("Synthetic", operation_id=operation)
    stored = service.store.get("profile", "local")
    assert activated == [stored["identity_hash"]]
    monkeypatch.setattr(service.store, "commit_operation", original)
    assert service.create_profile("Synthetic", operation_id=operation) == stored
    assert activated == [stored["identity_hash"]]
    assert service._connection_runtime is owner
    assert owner.execution() is Execution.AVAILABLE


def test_failed_profile_transaction_never_activates_identity_or_owner(profile_runtime, monkeypatch):
    create, _ = profile_runtime
    service = create()
    original = service.store._write_records_locked
    monkeypatch.setattr(service._connection_runtime, "synchronize", lambda: pytest.fail("Activated rolled back profile"))

    def failed_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("commit failed")

    monkeypatch.setattr(service.store, "_write_records_locked", failed_commit)
    with pytest.raises(OSError):
        service.create_profile("Synthetic", operation_id=str(uuid4()))
    assert service._identity is None
    assert service.store.get("profile", "local") is None
    assert service._connection_runtime.execution() is Execution.LOCKED


def test_native_owner_construction_failure_closes_started_workers_and_vault(profile_runtime, tmp_path, monkeypatch):
    _, native = profile_runtime
    captured = []

    def failed_owner(service):
        captured.append(service)
        raise RuntimeError("owner construction failed")

    monkeypatch.setattr(composition, "native_runtime", failed_owner)
    directory = tmp_path / "failed"
    store = VaultStore(directory, os.urandom(32), allow_unprotected_for_tests=True)
    with pytest.raises(RuntimeError, match="owner construction"):
        MeshChatService(store, directory, lambda _: None,
                        connection_policy="shared-native", native_webrtc_host=native)
    service, = captured
    assert service._shutdown.is_set() and service._store_closed
    assert not service._retry_thread.is_alive()
    assert not service._native_webrtc_event_thread.is_alive()


@pytest.mark.parametrize("stage", ["carrier", "owner", "native"])
def test_close_failure_retains_exact_resources_and_can_retry_before_releasing_vault(profile_runtime, monkeypatch, stage):
    create, _ = profile_runtime
    service = create()
    calls = []
    original = service._connection_runtime.stop if stage == "owner" else lambda **_: None

    def fail_once(**kwargs):
        calls.append(stage)
        if len(calls) == 1:
            raise OSError("close unavailable")
        return original(**kwargs)

    if stage == "carrier":
        service._pending_contact_carriers = {"pending": SimpleNamespace(close=fail_once, wait=lambda **_: True)}
    elif stage == "owner":
        monkeypatch.setattr(service._connection_runtime, "stop", fail_once)
    else:
        service._direct_native = SimpleNamespace(close=fail_once)
    with pytest.raises(OSError, match="close unavailable"):
        service.close()
    assert service._shutdown.is_set() and service._close_started
    assert not service._store_closed
    assert service.store.get("profile", "local") is None
    service.close()
    assert service._store_closed and calls == [stage, stage]


def test_failed_native_close_keeps_exact_physical_handle_after_logical_release(profile_runtime):
    create, native = profile_runtime
    service = create()
    physical = service._native_resources.reserve("manual")
    service._native_webrtc_live.add("manual")
    closed = []

    def fail_once(value):
        closed.append(value)
        if len(closed) == 1:
            raise OSError("native close failed")

    native.close = fail_once
    with pytest.raises(OSError, match="native close"):
        service.close()
    assert not service._store_closed
    assert service._closing_native_handles == {physical: "manual"}
    service.close()
    assert service._store_closed
    assert closed == [physical, physical] and not service._closing_native_handles


@pytest.fixture
def lifecycle_facts():
    """Actual lifecycle transitions; I/O ports record bounded component effects."""
    calls = []

    class Runtime:
        def __init__(self, name):
            self._shutdown = Event()
            self._store_closed = False
            self._runtime_incarnation = uuid4().hex
            self.name, self.can_close = name, True

        def close(self):
            calls.append(("close", self.name))
            self._store_closed = self.can_close

    def open_profile(name):
        calls.append(("open", name))
        return Runtime(name)

    current = Runtime("alpha")
    lifecycle = ProfileRuntimeLifecycle(
        tuple(ProfileSlot(name, lambda name=name: open_profile(name)) for name in ("alpha", "beta")),
        "alpha", active=current, publish=lambda value: calls.append(("publish", value)),
        remember_selection=lambda name: calls.append(("selection", name)),
        read_selection=lambda: pytest.fail("Lookup read persisted selection"),
    )
    return lifecycle, current, calls


def fact_request(lifecycle, action="unlock", profile="alpha"):
    state = lifecycle.query()
    return LifecycleRequest(str(uuid4()), action, profile, state["host_incarnation"], state["revision"])


def perform(lifecycle, request):
    return lifecycle.mutate(request.action, request.profile_id, request.operation_id,
        host_incarnation=request.core_host_incarnation, expected_revision=request.expected_revision)


def assert_pure_lookup(lifecycle, request, monkeypatch):
    before = lifecycle.query()
    # Even when the transition gate is occupied, lookup needs only the state lock.
    assert lifecycle._transition_lock.acquire(blocking=False)
    try:
        with monkeypatch.context() as guarded:
            def forbidden(*_args, **_kwargs): pytest.fail("Completion lookup performed an effect")
            for name in ("query", "mutate", "reconcile", "_advance", "_drain_retirement",
                         "_retire_active", "_publish", "_remember_selection", "_read_selection"):
                guarded.setattr(lifecycle, name, forbidden)
            result = lifecycle.lookup_exact_completion(request)
    finally:
        lifecycle._transition_lock.release()
    assert lifecycle.query() == before
    return result


def test_unknown_lookup_does_not_turn_absence_or_rejected_attempt_into_no_effect(lifecycle_facts, monkeypatch):
    lifecycle, _, calls = lifecycle_facts
    request = fact_request(lifecycle, "unlock", "beta")
    assert assert_pure_lookup(lifecycle, request, monkeypatch) == CompletionFact("unknown")
    with pytest.raises(ValidationError, match="not selected"):
        perform(lifecycle, request)
    assert assert_pure_lookup(lifecycle, request, monkeypatch) == CompletionFact("unknown")
    assert calls == []


def test_pending_lookup_does_not_finish_now_available_retirement(lifecycle_facts, monkeypatch):
    lifecycle, current, calls = lifecycle_facts
    current.can_close = False
    request = fact_request(lifecycle, "lock")
    assert perform(lifecycle, request)["state"] == "retiring"
    current.can_close = True
    before = list(calls)
    assert assert_pure_lookup(lifecycle, request, monkeypatch) == CompletionFact("pending", request)
    assert calls == before and not current._store_closed
    result = lifecycle.reconcile()
    assert result["pending_action"] is None
    assert lifecycle.lookup_exact_completion(request) == CompletionFact("applied", request, result["revision"], None)


@pytest.mark.parametrize("action,profile", [("lock", "alpha"), ("select", "beta"), ("unlock", "alpha")])
def test_applied_lookup_is_exact_and_never_replays_effect(lifecycle_facts, monkeypatch, action, profile):
    lifecycle, _, calls = lifecycle_facts
    request = fact_request(lifecycle, action, profile)
    result = perform(lifecycle, request)
    before = list(calls)
    fact = assert_pure_lookup(lifecycle, request, monkeypatch)
    assert fact == CompletionFact("applied", request, result["revision"], result["service_incarnation"])
    assert calls == before
    assert perform(lifecycle, request) == result  # Existing replay remains unchanged.
    assert calls == before
    with pytest.raises(FrozenInstanceError): fact.status = "unknown"
    with pytest.raises(FrozenInstanceError): request.expected_revision = 9


def test_actual_open_completion_remains_historical_after_shutdown(lifecycle_facts, monkeypatch):
    lifecycle, _, calls = lifecycle_facts
    perform(lifecycle, fact_request(lifecycle, "lock"))
    request = fact_request(lifecycle)
    result = perform(lifecycle, request)
    fact = lifecycle.lookup_exact_completion(request)
    assert fact.result_service_incarnation == result["service_incarnation"] is not None
    lifecycle.retire_for_host_shutdown()
    before = list(calls)
    assert lifecycle.query()["state"] == "locked"
    assert assert_pure_lookup(lifecycle, request, monkeypatch) == fact
    with pytest.raises(ProfileLifecycleResync): perform(lifecycle, request)
    assert calls == before and sum(kind == "open" for kind, _ in calls) == 1


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("changed", ["action", "profile_id", "core_host_incarnation", "expected_revision"])
def test_retained_operation_with_different_identity_is_typed_conflict(lifecycle_facts, pending, changed):
    lifecycle, current, calls = lifecycle_facts
    current.can_close = not pending
    request = fact_request(lifecycle, "lock")
    perform(lifecycle, request)
    changes = {"action": "select", "profile_id": "beta", "core_host_incarnation": uuid4().hex,
               "expected_revision": request.expected_revision + 1}
    before = list(calls)
    with pytest.raises(ProfileLifecycleIdentityConflict):
        lifecycle.lookup_exact_completion(replace(request, **{changed: changes[changed]}))
    assert lifecycle.lookup_exact_completion(replace(request, operation_id=str(uuid4()))).status == "unknown"
    assert calls == before


def test_failed_publication_and_shutdown_never_fabricate_completion(lifecycle_facts, monkeypatch):
    lifecycle, _, calls = lifecycle_facts
    perform(lifecycle, fact_request(lifecycle, "lock"))
    request = fact_request(lifecycle)
    def failed_publish(value):
        calls.append(("publish", value))
        if value is not None: raise OSError("publication unavailable")
    monkeypatch.setattr(lifecycle, "_publish", failed_publish)
    with pytest.raises(NativeUnavailable): perform(lifecycle, request)
    assert assert_pure_lookup(lifecycle, request, monkeypatch) == CompletionFact("pending", request)
    lifecycle.retire_for_host_shutdown()
    assert lifecycle.query()["state"] == "locked"
    assert assert_pure_lookup(lifecycle, request, monkeypatch) == CompletionFact("pending", request)


def test_next_completed_mutation_supersedes_retained_fact_without_release_hook(lifecycle_facts):
    lifecycle, _, _ = lifecycle_facts
    first = fact_request(lifecycle)
    perform(lifecycle, first)
    fact = lifecycle.lookup_exact_completion(first)
    second = fact_request(lifecycle, "lock")
    perform(lifecycle, second)
    assert lifecycle.lookup_exact_completion(first) == CompletionFact("unknown")
    assert lifecycle.lookup_exact_completion(second).status == "applied"
    assert fact.status == "applied" and fact.result_service_incarnation is not None


@pytest.mark.parametrize("change", [
    {"operation_id": "not-canonical"}, {"action": []}, {"profile_id": []},
    {"core_host_incarnation": None}, {"expected_revision": True}, {"expected_revision": -1},
])
def test_request_identity_rejects_mutable_or_invalid_fields(lifecycle_facts, change):
    lifecycle, _, _ = lifecycle_facts
    with pytest.raises(ValidationError): replace(fact_request(lifecycle), **change)


@pytest.mark.parametrize("fields", [
    {"status": "rejected_no_effect"}, {"status": "pending"}, {"status": "applied"},
    {"status": "unknown", "result_revision": 1},
])
def test_completion_fact_rejects_unsupported_or_inconsistent_claims(fields):
    with pytest.raises(ValidationError): CompletionFact(**fields)
