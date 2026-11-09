"""Actual vault/profile commits; native ownership uses bounded recording ports."""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.connection import composition
from mesh_chat.connection.model import Execution
from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.native_webrtc_host import HOST_METHODS
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
