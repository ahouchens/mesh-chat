"""Production remote-profile mutations with real encrypted vault transactions."""

from copy import deepcopy
import os
import time
from uuid import uuid4

import pytest

from mesh_chat.errors import ValidationError
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


ENDPOINTS = [{"host": "relay.example.net", "port": 4242}]
NODE = "ab" * 16
METHODS = {
    "test": "test_remote_profile", "retry": "retry_remote_profile",
    "remove": "remove_remote_profile", "approve_propagation": "approve_remote_propagation",
    "remove_propagation": "remove_remote_propagation",
}


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    lookups = []

    def resolve(endpoint, **kwargs):
        lookups.append(deepcopy(endpoint))
        return ["93.184.216.34"]

    monkeypatch.setattr("mesh_chat.remote_service.resolve_public_endpoint", resolve)
    key = os.urandom(32)
    opened = []

    def open_host():
        store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
        service = MeshChatService(store, tmp_path, lambda _: None)
        if store.get("profile", "local") is None:
            service.create_profile("Remote profile owner")
        opened.append(service)
        return service

    yield open_host, lookups
    for service in opened:
        service.network = None
        service.close()


def create(service, operation_id=None, **changes):
    params = {"label": "Approved relay", "endpoints": deepcopy(ENDPOINTS), "propagation_node": NODE}
    params.update(changes)
    return service.create_manual_remote_profile(**params, operation_id=operation_id)


def prepare(service, action):
    remote = create(service)
    if action == "remove_propagation":
        service.approve_remote_propagation(remote["id"])
    return remote["id"]


def fail_writes(store, monkeypatch):
    original = store._write_records_locked

    def fail_after_writes(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected before transaction commit")

    monkeypatch.setattr(store, "_write_records_locked", fail_after_writes)
    return original


def test_create_receipt_preserves_identity_after_lost_reply_time_change_and_reopen(hosts, monkeypatch):
    open_host, lookups = hosts
    service = open_host()
    operation = str(uuid4())
    original = service.store.commit_operation

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("reply lost after commit")

    monkeypatch.setattr(service.store, "commit_operation", lost_reply)
    with pytest.raises(OSError):
        create(service, operation)
    record = service.store.list("remote_profile")[0]
    assert lookups == []  # No DNS can precede committed consent.
    assert service.store.list("workspace_operation")[0]["outcome"] == {"action": "create", "id": record["id"]}
    service.close()
    reopened = open_host()
    from mesh_chat import remote_service
    from types import SimpleNamespace
    monkeypatch.setattr(remote_service, "time", SimpleNamespace(time=lambda: time.time() + 3600))
    replay = create(reopened, operation)
    assert replay["id"] == record["id"]
    assert len(reopened.store.list("remote_profile")) == len(reopened.store.list("workspace_operation")) == 1
    assert lookups == []
    reopened.reconcile_remote_profiles()
    assert lookups == ENDPOINTS


@pytest.mark.parametrize("changes", [{"label": "Changed"}, {"allow_private": True},
    {"propagation_node": "cd" * 16}, {"endpoints": [{"host": "other.example.net", "port": 4242}]}])
def test_create_key_cannot_change_normalized_input(hosts, changes):
    open_host, lookups = hosts
    service = open_host()
    operation = str(uuid4())
    create(service, operation)
    before = len(lookups)
    with pytest.raises(ValidationError, match="already used with different input"):
        create(service, operation, **changes)
    assert len(lookups) == before
    assert len(service.store.list("remote_profile")) == len(service.store.list("workspace_operation")) == 1


def test_create_transaction_failure_leaves_no_profile_receipt_or_network_effect(hosts, monkeypatch):
    open_host, lookups = hosts
    service = open_host()
    operation = str(uuid4())
    original = fail_writes(service.store, monkeypatch)
    with pytest.raises(OSError):
        create(service, operation)
    assert service.store.list("remote_profile") == service.store.list("workspace_operation") == []
    assert lookups == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert create(service, operation)["id"]
    assert lookups == ENDPOINTS


@pytest.mark.parametrize("action", METHODS)
def test_keyed_actions_survive_reopen_without_repeating_the_mutation(hosts, action):
    open_host, lookups = hosts
    service = open_host()
    identifier = prepare(service, action)
    operation = str(uuid4())
    result = getattr(service, METHODS[action])(identifier, operation_id=operation)
    before = deepcopy(service.store.list("remote_profile"))
    count = len(lookups)
    assert service.store.list("workspace_operation")[0]["outcome"] == {"action": action, "id": identifier}
    service.close()
    reopened = open_host()
    assert getattr(reopened, METHODS[action])(identifier, operation_id=operation) == result
    assert reopened.store.list("remote_profile") == before
    assert len(lookups) == count
    assert len(reopened.store.list("workspace_operation")) == 1


@pytest.mark.parametrize("action", METHODS)
def test_each_action_rolls_back_records_settings_receipt_and_memory(hosts, monkeypatch, action):
    open_host, lookups = hosts
    service = open_host()
    identifier = prepare(service, action)
    before = deepcopy(service.store.list("remote_profile"))
    settings = service.store.get("settings", "network")
    intents = service.store.list("remote_runtime_intent")
    memory_nodes = list(service.settings.approved_propagation_nodes)
    count = len(lookups)
    fail_writes(service.store, monkeypatch)
    with pytest.raises(OSError):
        getattr(service, METHODS[action])(identifier, operation_id=str(uuid4()))
    assert service.store.list("remote_profile") == before
    assert service.store.get("settings", "network") == settings
    assert service.store.list("remote_runtime_intent") == intents
    assert service.settings.approved_propagation_nodes == memory_nodes
    assert service.store.list("workspace_operation") == []
    assert len(lookups) == count


def test_action_and_target_are_part_of_the_input_digest(hosts):
    open_host, _ = hosts
    service = open_host()
    first, second = create(service), create(service, label="Second relay")
    operation = str(uuid4())
    service.test_remote_profile(first["id"], operation_id=operation)
    with pytest.raises(ValidationError, match="already used with different input"):
        service.retry_remote_profile(first["id"], operation_id=operation)
    with pytest.raises(ValidationError, match="already used with different input"):
        service.test_remote_profile(second["id"], operation_id=operation)


@pytest.mark.parametrize("revocation", ["locked", "shutdown", "missing_profile"])
@pytest.mark.parametrize("action", ["create", *METHODS])
def test_replay_rechecks_current_local_authority(hosts, action, revocation):
    open_host, lookups = hosts
    service = open_host()
    operation = str(uuid4())
    if action == "create":
        call = lambda: create(service, operation)
    else:
        identifier = prepare(service, action)
        call = lambda: getattr(service, METHODS[action])(identifier, operation_id=operation)
    call()
    count = len(lookups)
    if revocation == "locked":
        service._identity = None
    elif revocation == "shutdown":
        service._shutdown.set()
    else:
        service.store.delete("profile", "local")
    with pytest.raises(ValidationError):
        call()
    assert len(lookups) == count


def test_replaying_create_cannot_restore_removed_consent(hosts):
    open_host, lookups = hosts
    service = open_host()
    operation = str(uuid4())
    remote = create(service, operation)
    service.remove_remote_profile(remote["id"], operation_id=str(uuid4()))
    before = len(lookups)
    with pytest.raises(ValidationError):
        create(service, operation)
    assert service.store.list("remote_profile") == []
    assert len(lookups) == before


def test_replaying_propagation_mutations_cannot_reverse_later_consent(hosts):
    open_host, _ = hosts
    service = open_host()
    identifier = create(service)["id"]
    approve_key, remove_key = str(uuid4()), str(uuid4())
    service.approve_remote_propagation(identifier, operation_id=approve_key)
    service.remove_remote_propagation(identifier, operation_id=remove_key)
    with pytest.raises(ValidationError, match="approval is no longer current"):
        service.approve_remote_propagation(identifier, operation_id=approve_key)
    assert service.settings.approved_propagation_nodes == []
    service.approve_remote_propagation(identifier, operation_id=str(uuid4()))
    with pytest.raises(ValidationError, match="removal is no longer current"):
        service.remove_remote_propagation(identifier, operation_id=remove_key)
    assert service.settings.approved_propagation_nodes == [NODE]


def test_shared_propagation_node_is_retained_until_last_approval_is_removed(hosts):
    open_host, _ = hosts
    service = open_host()
    identifiers = [create(service, label=label)["id"] for label in ("One", "Two")]
    for identifier in identifiers:
        service.approve_remote_propagation(identifier, operation_id=str(uuid4()))
    service.remove_remote_propagation(identifiers[0], operation_id=str(uuid4()))
    assert service.settings.approved_propagation_nodes == [NODE]
    service.remove_remote_propagation(identifiers[1], operation_id=str(uuid4()))
    assert service.settings.approved_propagation_nodes == []


def test_receipts_never_cache_previous_runtime_connectivity(hosts):
    open_host, _ = hosts
    service = open_host()
    operation = str(uuid4())
    identifier = create(service, operation)["id"]
    record = service.store.get("remote_profile", identifier)
    record.update(state="connected", connected_endpoints=1, path_available=True,
                  ratchet_ready=True, propagation_available=True)
    service.store.put("remote_profile", identifier, record)
    service.close()
    reopened = open_host()
    replay = create(reopened, operation)
    assert replay["state"] == "approved" and replay["connected_endpoint_count"] == 0
    assert not replay["path_available"] and not replay["ratchet_ready"] and not replay["offline_delivery_available"]
    assert reopened.list_remote_profiles()["profiles"] == [replay]


@pytest.mark.parametrize("action", ["remove", "approve_propagation", "remove_propagation"])
def test_failed_runtime_effect_is_reconciled_from_current_durable_intent_after_reopen(hosts, monkeypatch, action):
    from types import SimpleNamespace

    open_host, _ = hosts
    service = open_host()
    identifier = prepare(service, action)
    operation = str(uuid4())
    effects = []

    def failed_effect(value):
        # The domain write and receipt are already committed before effects.
        assert len(service.store.list("workspace_operation")) == 1
        effects.append(deepcopy(value))
        raise OSError("network is unavailable")

    service.network = SimpleNamespace(apply_propagation_nodes=failed_effect, apply_remote_profiles=failed_effect)
    result = getattr(service, METHODS[action])(identifier, operation_id=operation)
    kind = "transport" if action == "remove" else "propagation"
    assert len(effects) == 1
    assert service.store.get("remote_runtime_intent", kind) is not None
    if action != "remove":
        assert result["offline_delivery_available"] is False
    service.network = None
    service.close()
    reopened = open_host()
    recovered = []
    reopened.network = SimpleNamespace(apply_propagation_nodes=lambda nodes: recovered.append(deepcopy(nodes)),
                                       apply_remote_profiles=lambda endpoints: recovered.append(deepcopy(endpoints)))
    monkeypatch.setattr(reopened, "_refresh_remote_profile_states", lambda: None)
    reopened.reconcile_remote_profiles()
    assert len(recovered) == 1
    assert recovered[0] == ([NODE] if action == "approve_propagation" else [])
    assert reopened.store.get("remote_runtime_intent", kind) is None
    assert len(reopened.store.list("workspace_operation")) == 1
    getattr(reopened, METHODS[action])(identifier, operation_id=operation)
    assert len(recovered) == 1  # A replay cannot repeat an already reconciled effect.


def test_post_commit_approval_reply_loss_recovers_memory_without_duplicate_approval(hosts, monkeypatch):
    open_host, _ = hosts
    service = open_host()
    identifier = create(service)["id"]
    operation = str(uuid4())
    original = service.store.commit_operation

    def lose_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("reply lost")

    monkeypatch.setattr(service.store, "commit_operation", lose_reply)
    with pytest.raises(OSError):
        service.approve_remote_propagation(identifier, operation_id=operation)
    assert service.settings.approved_propagation_nodes == []
    assert service.store.get("settings", "network")["approved_propagation_nodes"] == [NODE]
    assert service.approve_remote_propagation(identifier, operation_id=operation)["offline_delivery_approved"]
    assert service.settings.approved_propagation_nodes == [NODE]
    assert len(service.store.list("workspace_operation")) == 1


@pytest.mark.parametrize("action", ["test", "retry", "approve_propagation"])
def test_replay_cannot_reactivate_expired_or_released_profile(hosts, action):
    open_host, lookups = hosts
    service = open_host()
    identifier = create(service)["id"]
    operation = str(uuid4())
    getattr(service, METHODS[action])(identifier, operation_id=operation)
    before = len(lookups)
    record = service.store.get("remote_profile", identifier)
    record["profile"]["expires_at"] = int(time.time()) - 1
    service.store.put("remote_profile", identifier, record)
    with pytest.raises(ValidationError, match="expired"):
        getattr(service, METHODS[action])(identifier, operation_id=operation)
    assert len(lookups) == before


def test_old_removal_receipt_cannot_remove_a_later_reconsented_profile(hosts):
    open_host, _ = hosts
    service = open_host()
    identifier = create(service)["id"]
    previous = service.store.get("remote_profile", identifier)
    operation = str(uuid4())
    service.remove_remote_profile(identifier, operation_id=operation)
    service.store.put("remote_profile", identifier, previous)
    with pytest.raises(ValidationError, match="removal is no longer current"):
        service.remove_remote_profile(identifier, operation_id=operation)
    assert service.store.get("remote_profile", identifier) == previous


def test_new_approval_uses_durable_nodes_after_another_approval_loses_its_reply(hosts, monkeypatch):
    open_host, _ = hosts
    service = open_host()
    first = create(service)["id"]
    second = create(service, label="Second", propagation_node="cd" * 16)["id"]
    original = service.store.commit_operation

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("reply lost after durable approval")

    monkeypatch.setattr(service.store, "commit_operation", lost_reply)
    with pytest.raises(OSError):
        service.approve_remote_propagation(first, operation_id=str(uuid4()))
    assert service.settings.approved_propagation_nodes == []
    monkeypatch.setattr(service.store, "commit_operation", original)
    service.approve_remote_propagation(second, operation_id=str(uuid4()))
    assert service.settings.approved_propagation_nodes == [NODE, "cd" * 16]
    assert service.store.get("settings", "network")["approved_propagation_nodes"] == [NODE, "cd" * 16]
