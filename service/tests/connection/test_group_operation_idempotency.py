"""Group preparation must have no delivery scheduling before atomic commit."""
import sys
from pathlib import Path

import RNS
import base64
import json
from dataclasses import replace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_group_service import _contact, _service, _joined_pair
from mesh_chat.models import MessageKind
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from test_core_sdk_distribution import installed_consumer, run_consumer
from test_core_sdk_upgrade import pinned_install, old_consumer


def test_pure_delivery_builder_does_not_schedule_or_persist_before_commit(tmp_path):
    member = _contact(RNS.Identity(), "Synthetic member", "member")
    service, network = _service(tmp_path, RNS.Identity(), "Synthetic owner", member)
    try:
        group = {"id": "synthetic-group", "epoch": 1, "manifest_hash": "a" * 64}
        current = service._group_retry_snapshot()
        prepared = service._delivery_record(group=group, recipient=member,
            kind=MessageKind.GROUP_CHAT, text="Synthetic prepared message", queue_retry=False)
        assert service._group_retry_snapshot() == current
        assert service.store.get("group_delivery", prepared["id"]) is None
        assert not network.sent
        legacy = service._delivery_record(group=group, recipient=member, kind=MessageKind.GROUP_CHAT)
        assert legacy["id"] in service._group_retry_snapshot()
    finally:
        service.close()


@pytest.fixture
def group_host(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    pair = _joined_pair(tmp_path)
    for service, identity in [(pair.owner, pair.owner_identity), (pair.member, pair.member_identity)]:
        service._retry_thread.join(timeout=2)
        assert not service._retry_thread.is_alive()
        service.store.put("identity", "local", {"private_key": base64.urlsafe_b64encode(identity.get_private_key()).decode()})
        service._shutdown.clear()
    key = pair.owner.store._key
    reopened = []
    def reopen():
        pair.owner.close()
        root = pair.owner.profile_dir
        service = MeshChatService(VaultStore(root, key, allow_unprotected_for_tests=True), root, lambda _: None)
        reopened.append(service)
        return service
    yield pair, reopen
    for service in reopened:
        service.close()
    pair.close()


def public(service, caller="group-qualified-caller"):
    grants = [Grant(caller, frozenset({"observe", "read", "send", "approve"}), ("local",))]
    stream = bind_service_stream(service, lambda: grants[0])
    def invoke(operation, params=None, key=None):
        frame = {"api_version": 1, "request_id": "group:test", "operation": operation, "params": params or {}}
        if key is not None:
            frame["idempotency_key"] = key
        return decode_frame(stream.exchange(encode_frame(frame)))
    caps = invoke("runtime.capabilities")
    assert caps["ok"], caps
    profile = caps["result"]["profiles"][0]
    peer = invoke("profile.query", {"profile": profile})["result"]["peers"][0]
    group = invoke("group.query", {"profile": profile})["result"]["groups"][0]["group"]
    return invoke, grants, profile, peer, group


def mutation(invoke, profile, peer, group, operation, key="explicit-group-key-0001", text="Synthetic keyed group"):
    params = ({"profile": profile, "title": text, "posting_policy": "members", "members": [peer]}
              if operation == "group.create" else {"profile": profile, "group": group, "text": text})
    return invoke(operation, params, key)


@pytest.mark.parametrize("operation", ["group.create", "group.message_enqueue"])
def test_keyed_group_acceptance_emits_committed_state_invalidation_while_offline(group_host, operation):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    observed = []
    namespaces = ("group", "group_message", "group_delivery", "workspace_operation", "api_optional_mutation", "api_optional_quota")
    def observe(event):
        if event == {"type": "event", "event": "state_changed"}:
            observed.append({name: dict(service.store.items(name)) for name in namespaces})
    service.emit = observe
    before_packets = list(pair.owner_network.sent)
    first = mutation(invoke, profile, peer, group, operation)
    assert first["ok"], first
    committed = {name: dict(service.store.items(name)) for name in namespaces}
    assert observed == [committed]  # Synchronous event observes the entire durable acceptance.
    assert committed["api_optional_mutation"] and committed["workspace_operation"]
    assert mutation(invoke, profile, peer, group, operation) == first
    assert observed == [committed, committed]
    assert {name: dict(service.store.items(name)) for name in namespaces} == committed
    assert pair.owner_network.sent == before_packets


@pytest.mark.parametrize("operation", ["group.create", "group.message_enqueue"])
def test_keyed_group_lost_reply_reopen_and_replay_preserve_one_domain_mutation(group_host, operation):
    pair, reopen = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    before_groups, before_messages = service.store.record_count("group"), service.store.record_count("group_message")
    before_packets = len(pair.owner_network.sent)
    first = mutation(invoke, profile, peer, group, operation)
    assert first["ok"], first
    assert mutation(invoke, profile, peer, group, operation) == first
    assert len(pair.owner_network.sent) == before_packets  # Acceptance queues, never sends a peer packet.
    assert service.store.record_count("group") == before_groups + (operation == "group.create")
    assert service.store.record_count("group_message") == before_messages + (operation == "group.message_enqueue")
    assert service.store.record_count("api_optional_mutation") == 1
    assert service.store.list("api_optional_quota")[0]["count"] == 1
    receipts = service.store.list("workspace_operation")
    assert "Synthetic keyed group" not in json.dumps(receipts)
    if operation == "group.message_enqueue":
        assert first["result"]["accepted"] and len(first["result"]["message"]) == 64
    service = reopen()
    again, _, same_profile, same_peer, same_group = public(service)
    assert (profile, peer, group) == (same_profile, same_peer, same_group)
    assert mutation(again, profile, peer, group, operation) == first
    assert service.store.record_count("api_optional_mutation") == 1


@pytest.mark.parametrize("operation", ["group.create", "group.message_enqueue"])
def test_keyed_group_transaction_failure_rolls_back_domain_quota_receipt_and_retry_hint(group_host, monkeypatch, operation):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    namespaces = ["group", "group_message", "group_delivery", "workspace_operation", "api_optional_mutation", "api_optional_quota"]
    before = {name: dict(service.store.items(name)) for name in namespaces}
    hints = service._group_retry_snapshot()
    original = service.store._write_records_locked
    def fail(*args):
        original(*args)
        raise OSError("injected optional mutation transaction failure")
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert mutation(invoke, profile, peer, group, operation)["error"]["code"] == "unavailable"
    assert {name: dict(service.store.items(name)) for name in namespaces} == before
    assert service._group_retry_snapshot() == hints
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert mutation(invoke, profile, peer, group, operation)["ok"]


@pytest.mark.parametrize("operation", ["group.create", "group.message_enqueue"])
def test_keyed_group_lost_commit_return_does_not_repeat_create_or_sequence(group_host, monkeypatch, operation):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    original = service.store.conditional_put_and_delete
    failed = []
    def lost(*args, **kwargs):
        result = original(*args, **kwargs)
        if not failed:
            failed.append(True)
            raise OSError("injected committed reply loss")
        return result
    monkeypatch.setattr(service.store, "conditional_put_and_delete", lost)
    assert mutation(invoke, profile, peer, group, operation)["error"]["code"] == "unavailable"
    groups, messages = service.store.list("group"), service.store.list("group_message")
    replay = mutation(invoke, profile, peer, group, operation)
    assert replay["ok"], replay
    assert service.store.list("group") == groups and service.store.list("group_message") == messages
    assert service.store.list("api_optional_quota")[0]["count"] == 1


def test_optional_key_conflicts_globally_before_group_preparation(group_host, monkeypatch):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    key = "global-optional-key-0001"
    assert invoke("workspace.create", {"profile": profile, "name": "Synthetic workspace", "description": ""}, key)["ok"]
    calls = []
    monkeypatch.setattr(service, "prepare_group_create", lambda *_: calls.append(True))
    reply = mutation(invoke, profile, peer, group, "group.create", key)
    assert reply["error"]["code"] == "idempotency_conflict"
    assert calls == [] and service.store.record_count("api_optional_mutation") == 0


def test_same_optional_key_different_payload_and_operation_conflict_without_effects(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["ok"]
    assert mutation(invoke, profile, peer, group, "group.message_enqueue", text="Changed text")["error"]["code"] == "idempotency_conflict"
    assert mutation(invoke, profile, peer, group, "group.create")["error"]["code"] == "idempotency_conflict"
    assert service.store.record_count("group_message") == 1 and service.store.record_count("group") == 1


def test_optional_key_replay_rechecks_permissions_and_membership(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, grants, profile, peer, group = public(service)
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["ok"]
    original = grants[0]
    grants[0] = replace(original, permissions=frozenset({"observe", "read"}))
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["error"]["code"] == "forbidden"
    grants[0] = original
    record = service.store.get("group", pair.group_id)
    record["status"] = "removed"
    service.store.put("group", pair.group_id, record)
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["error"]["code"] == "forbidden"
    assert service.store.record_count("group_message") == 1


@pytest.mark.parametrize("mode", ["--exercise-keyed-group-create", "--exercise-keyed-group-send"])
def test_installed_public_sdk_explicit_group_key_reaches_atomic_core(group_host, installed_consumer, mode):
    pair, _ = group_host
    report = run_consumer(installed_consumer, pair.owner, mode)
    assert report["sdk_only"]
    if mode == "--exercise-keyed-group-create":
        assert report["same_group"] and pair.owner.store.record_count("group") == 2
    else:
        assert report["accepted"] and report["same_message"] and pair.owner.store.record_count("group_message") == 1
    assert pair.owner.store.record_count("api_optional_mutation") == 1


def test_expired_key_or_erased_primary_never_becomes_a_new_send(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["ok"]
    for identifier, _ in service.store.items("group_message"):
        service.store.delete("group_message", identifier)
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["error"]["code"] == "idempotency_expired"
    assert service.store.record_count("group_message") == 0
    identifier, receipt = service.store.items("api_optional_mutation")[0]
    receipt["expires_at"] = receipt["accepted_at"] - 1
    service.store.put("api_optional_mutation", identifier, receipt)
    assert mutation(invoke, profile, peer, group, "group.message_enqueue")["error"]["code"] == "idempotency_expired"
    assert mutation(invoke, profile, peer, group, "group.message_enqueue", text="Changed after expiry")["error"]["code"] == "idempotency_conflict"


def test_key_capacity_and_group_capacity_refuse_before_preparation_but_allow_existing_replay(group_host, monkeypatch):
    from mesh_chat.core_api.optional_mutations import OPTIONAL_KEY_LIMITS
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    monkeypatch.setitem(OPTIONAL_KEY_LIMITS, "optional_keys_per_caller_profile", 1)
    first = mutation(invoke, profile, peer, group, "group.message_enqueue")
    assert first["ok"]
    calls = []
    monkeypatch.setattr(service, "prepare_group_send", lambda *_: calls.append(True))
    assert mutation(invoke, profile, peer, group, "group.message_enqueue", key="another-caller-key-0001")["error"]["code"] == "resource_exhausted"
    assert calls == [] and mutation(invoke, profile, peer, group, "group.message_enqueue") == first


def test_create_replay_rechecks_local_owner_identity(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    created = mutation(invoke, profile, peer, group, "group.create")
    assert created["ok"]
    stored = service.store.get("profile", "local")
    stored["destination_hash"] = "cd" * 16
    service.store.put("profile", "local", stored)
    assert mutation(invoke, profile, peer, group, "group.create")["error"]["code"] == "forbidden"
    assert service.store.record_count("group") == 2


def test_keyed_group_profile_capacity_is_checked_before_crypto_preparation(group_host, monkeypatch):
    import mesh_chat.group_service as domain
    pair, _ = group_host
    service = pair.owner
    invoke, _, profile, peer, group = public(service)
    service.store.put_many(("group", f"capacity-{index}", {"id": f"capacity-{index}"}) for index in range(255))
    calls = []
    monkeypatch.setattr(domain, "create_group_genesis", lambda *_args, **_kwargs: calls.append(True))
    response = mutation(invoke, profile, peer, group, "group.create")
    assert response["error"]["code"] == "resource_exhausted"
    assert calls == [] and service.store.record_count("api_optional_mutation") == 0


@pytest.mark.parametrize("language", ["python", "typescript"])
@pytest.mark.parametrize("mode", ["--old-group-create", "--old-group-send"])
def test_actual_pinned_old_sdk_legacy_group_semantics_remain_available(group_host, pinned_install, language, mode):
    pair, _ = group_host
    report = run_consumer(old_consumer(pinned_install, language), pair.owner, mode)
    assert report["accepted"]
    assert pair.owner.store.record_count("api_optional_mutation") == 0
    if mode == "--old-group-create":
        assert pair.owner.store.record_count("group") == 2
    else:
        assert pair.owner.store.record_count("group_message") == 1


def test_optional_feature_is_advertised_only_by_complete_bound_port_and_never_discards_key(group_host, monkeypatch):
    pair, _ = group_host
    service = pair.owner
    monkeypatch.setattr(service, "prepare_group_send", None)
    invoke, _, profile, peer, group = public(service)
    caps = invoke("runtime.capabilities")["result"]
    assert caps["optional_keyed_operations"] == ["group.create"]
    response = mutation(invoke, profile, peer, group, "group.message_enqueue")
    assert response["error"]["code"] == "unsupported_operation"
    assert service.store.record_count("group_message") == 0
    assert mutation(invoke, profile, peer, group, "group.message_enqueue", key=None)["ok"]
    assert service.store.record_count("group_message") == 1
