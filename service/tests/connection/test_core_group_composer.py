"""Atomic group composer through actual signed groups, vault and framing."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.requests import COMPONENT_OPERATIONS, parse_request
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.service_group_composer import STATE, UPDATES, SENDS, QUOTA
from mesh_chat.core_api.service_group_composer import GROUP_COMPOSER_BOUNDS
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.vault import RecordConflict, VaultStore
from test_group_operation_idempotency import group_host

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/core-api"


def public(service, *, caller="group-composer-owner", legacy=False):
    grants = [Grant(caller, frozenset({"observe", "read", "send", "approve"}), ("local",))]
    stream = bind_service_stream(service, lambda: grants[0], private_composer_legacy=legacy)
    def invoke(operation, params=None, key=None):
        value = {"api_version": 1, "request_id": "composer:1", "operation": operation, "params": params or {}}
        if key is not None:
            value["idempotency_key"] = key
        return decode_frame(stream.exchange(encode_frame(value)))
    caps = invoke("runtime.capabilities")
    assert caps["ok"], caps
    profile = caps["result"]["profiles"][0]
    group = invoke("group.query", {"profile": profile})["result"]["groups"][0]["group"]
    return invoke, {"profile": profile, "group": group}, grants


def query(invoke, scope, revision=None):
    return invoke("group.composer_query", {**scope, **({"send_revision": revision} if revision else {})})


def save(invoke, scope, text, state=None):
    state = state or query(invoke, scope)["result"]
    return invoke("group.composer_update", {**scope, "text": text, "expected_revision": state["revision"]}, state["update_key"])


def send(invoke, scope, revision):
    return invoke("group.message_enqueue_draft", {**scope, "draft_revision": revision}, revision)


def rows(service):
    return service.store._db.execute("SELECT * FROM records ORDER BY kind,record_id").fetchall()


@pytest.mark.parametrize("vector", json.loads((CONTRACTS / "group-composer-vectors-v1.json").read_text()))
def test_group_composer_request_contract_matches_parser(vector):
    schema = Draft202012Validator(json.loads((CONTRACTS / "request-v1.schema.json").read_text()))
    assert schema.is_valid(vector["request"]) is vector["valid"]
    if vector["valid"]:
        assert parse_request(vector["request"], COMPONENT_OPERATIONS) == (vector["request"]["operation"], vector["request"]["params"])
    else:
        with pytest.raises(ApiFailure):
            parse_request(vector["request"], COMPONENT_OPERATIONS)


def test_pure_query_noop_update_and_actual_atomic_group_send(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service)
    before, packets, hints = rows(service), list(pair.owner_network.sent), service._group_retry_snapshot()
    initial = query(invoke, scope)
    assert initial["ok"] and initial["result"]["revision"] is None, initial
    assert rows(service) == before
    first = save(invoke, scope, "Persistent signed group message")
    assert first["ok"], first
    state = first["result"]["composer"]
    noop = save(invoke, scope, state["text"], state)
    assert noop["ok"] and not noop["result"]["changed"], noop
    assert noop["result"]["applied_revision"] == state["revision"]
    observed = []
    service.emit = lambda event: observed.append((event, rows(service)))
    accepted = send(invoke, scope, state["revision"])
    assert accepted["ok"], accepted
    assert accepted["result"]["composer"]["text"] == ""
    assert service.store.record_count("group_message") == service.store.record_count(SENDS) == 1
    assert service.store.list("group_message")[0]["sender_sequence"] == 1
    assert service.store.list("group_delivery") and service._group_retry_snapshot() != hints
    assert pair.owner_network.sent == packets
    assert any(event == {"type": "event", "event": "state_changed"} and snapshot == rows(service)
               for event, snapshot in observed)
    for reply, name in ((initial, "group-composer-result"), (first, "group-composer-update-result"), (accepted, "group-enqueue-draft-result")):
        Draft202012Validator(json.loads((CONTRACTS / (name + "-v1.schema.json")).read_text())).validate(reply)
    assert send(invoke, scope, state["revision"]) == accepted


def test_lost_commit_reopen_and_old_send_preserve_newer_draft(group_host, monkeypatch):
    pair, reopen = group_host
    service = pair.owner
    invoke, scope, _ = public(service)
    revision = save(invoke, scope, "one logical send")["result"]["applied_revision"]
    original = service.store.conditional_put_and_delete
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("lost committed reply")
    monkeypatch.setattr(service.store, "conditional_put_and_delete", lost)
    assert send(invoke, scope, revision)["error"]["code"] == "unavailable"
    monkeypatch.setattr(service.store, "conditional_put_and_delete", original)
    reopened = reopen()
    invoke, scope, _ = public(reopened)
    recovered = query(invoke, scope)["result"]
    assert recovered["text"] == "" and recovered["last_send"]["status"] == "accepted"
    accepted = recovered["last_send"]["acceptance"]
    newer = save(invoke, scope, "newer draft")["result"]["composer"]
    replay = send(invoke, scope, revision)
    assert replay["result"]["message"] == accepted["message"]
    assert replay["result"]["draft_disposition"] == "superseded"
    assert replay["result"]["composer"] == newer
    assert reopened.store.record_count("group_message") == 1
    assert send(invoke, scope, newer["revision"])["ok"]
    assert reopened.store.record_count("group_message") == 2


@pytest.mark.parametrize("operation", ["update", "enqueue"])
@pytest.mark.parametrize("phase", ["seal", "write", "commit"])
def test_group_transaction_fault_rolls_back_domain_receipt_quota_clear_and_fences(group_host, monkeypatch, operation, phase):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service, legacy=True)
    service.store.put("group_draft", pair.group_id, {"group_id": pair.group_id, "text": "legacy group text"})
    state = (save(invoke, scope, "atomic group text")["result"]["composer"] if operation == "enqueue"
             else query(invoke, scope)["result"])
    before, hints, packets = rows(service), service._group_retry_snapshot(), list(pair.owner_network.sent)
    version = service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0]
    store = service.store
    if phase == "seal":
        name, original = "_seal", store._seal
        def fail(kind, identifier, value):
            if kind == STATE:
                raise OSError("injected group composer seal fault")
            return original(kind, identifier, value)
    elif phase == "write":
        name, original = "_write_records_locked", store._write_records_locked
        def fail(*args):
            original(*args)
            raise OSError("injected group composer batch fault")
    else:
        name, original = "_db", store._db
        class FailCommit:
            def execute(self, statement, *args, **kwargs):
                if statement == "COMMIT":
                    raise OSError("injected group composer commit fault")
                return original.execute(statement, *args, **kwargs)
            def __getattr__(self, name):
                return getattr(original, name)
        fail = FailCommit()
    monkeypatch.setattr(store, name, fail)
    reply = send(invoke, scope, state["revision"]) if operation == "enqueue" else save(invoke, scope, "atomic group text", state)
    assert reply["error"]["code"] == "unavailable", reply
    assert rows(service) == before and service._group_retry_snapshot() == hints and pair.owner_network.sent == packets
    assert store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == version
    monkeypatch.setattr(store, name, original)
    assert (send(invoke, scope, state["revision"]) if operation == "enqueue" else save(invoke, scope, "atomic group text", state))["ok"]


def test_private_migration_and_public_legacy_sources_are_isolated_and_durably_fenced(group_host):
    pair, _ = group_host
    service = pair.owner
    service.store.put("group_draft", pair.group_id, {"text": "private UI text"})
    external, external_scope, _ = public(service, caller="external-one")
    other, other_scope, _ = public(service, caller="external-two")
    assert query(external, external_scope)["result"]["text"] == ""
    assert external("group.draft_set", {**external_scope, "text": "private consumer text"})["ok"]
    assert query(other, other_scope)["result"]["text"] == ""
    state = query(external, external_scope)["result"]
    assert state["text"] == "private consumer text"
    assert save(external, external_scope, state["text"], state)["ok"]
    assert external("group.draft_set", {**external_scope, "text": "late legacy"})["error"]["code"] == "conflict"
    owner, scope, _ = public(service, legacy=True)
    initial = query(owner, scope)["result"]
    assert initial["text"] == "private UI text"
    assert save(owner, scope, initial["text"], initial)["ok"]
    assert service.store.get("group_draft", pair.group_id) is None
    with pytest.raises(RecordConflict):
        service.store.put("group_draft", pair.group_id, {"text": "old service writer"})
    root, key = service.profile_dir, service.store._key
    service.close()
    with VaultStore(root, key, allow_unprotected_for_tests=True) as reopened:
        with pytest.raises(RecordConflict):
            reopened.put("group_draft", pair.group_id, {"text": "writer before binding"})


def test_group_caller_tokens_authority_revocation_and_erasure_precede_replay(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, grants = public(service)
    state = save(invoke, scope, "acknowledged draft")["result"]["composer"]
    accepted = send(invoke, scope, state["revision"])
    assert accepted["ok"]
    other, other_scope, _ = public(service, caller="other-caller")
    assert query(other, other_scope, state["revision"])["error"]["code"] == "forbidden"
    assert send(other, other_scope, state["revision"])["error"]["code"] == "forbidden"
    original = grants[0]
    grants[0] = replace(original, permissions=frozenset({"observe", "send"}))
    assert query(invoke, scope, state["revision"])["error"]["code"] == "forbidden"
    before = rows(service)
    assert send(invoke, scope, state["revision"])["error"]["code"] == "forbidden"
    assert save(invoke, scope, "write without read", state)["error"]["code"] == "forbidden"
    assert rows(service) == before
    grants[0] = replace(original, permissions=frozenset({"observe", "read"}))
    assert send(invoke, scope, state["revision"])["error"]["code"] == "forbidden"
    grants[0] = original
    newer = save(invoke, scope, "erase this draft")["result"]["composer"]
    group = service.store.get("group", pair.group_id)
    service.store.put("group", pair.group_id, {**group, "status": "removed"})
    assert all(row["text"] == "" and row["revision"] != newer["revision"] for row in service.store.list(STATE))
    assert query(invoke, scope)["error"]["code"] == "forbidden"
    assert send(invoke, scope, state["revision"])["error"]["code"] == "forbidden"


def test_group_expired_or_erased_send_never_recreates_acceptance(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service)
    revision = save(invoke, scope, "erase accepted message")["result"]["applied_revision"]
    assert send(invoke, scope, revision)["ok"]
    for identifier, _ in service.store.items("group_message"):
        service.store.delete("group_message", identifier)
    assert query(invoke, scope)["result"]["last_send"]["status"] == "expired"
    assert query(invoke, scope, revision)["error"]["code"] == "idempotency_expired"
    assert send(invoke, scope, revision)["error"]["code"] == "idempotency_expired"
    assert service.store.record_count("group_message") == 0 and service.store.record_count(SENDS) == 1


def test_concurrent_framed_writers_cas_and_replay_one_send(group_host):
    pair, _ = group_host
    first, scope, _ = public(pair.owner)
    second, _, _ = public(pair.owner)
    initial = query(first, scope)["result"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: save(client, scope, "same logical update", initial), (first, second)))
    assert results[0] == results[1] and results[0]["ok"], results
    revision = results[0]["result"]["applied_revision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: send(client, scope, revision), (first, second)))
    assert results[0] == results[1] and results[0]["ok"], results
    assert pair.owner.store.record_count("group_message") == 1


def test_group_send_capacity_allows_replay_and_rejects_before_preparation(group_host, monkeypatch):
    pair, _ = group_host
    invoke, scope, _ = public(pair.owner)
    monkeypatch.setitem(GROUP_COMPOSER_BOUNDS, "composer_send_keys_per_caller_profile", 1)
    revision = save(invoke, scope, "only acceptance")["result"]["applied_revision"]
    accepted = send(invoke, scope, revision)
    assert accepted["ok"], accepted
    newer = save(invoke, scope, "refused acceptance")["result"]["applied_revision"]
    calls = []
    monkeypatch.setattr(pair.owner, "prepare_group_send", lambda *_: calls.append(True))
    refused = send(invoke, scope, newer)
    assert refused["error"]["code"] == "resource_exhausted", refused
    assert calls == [] and send(invoke, scope, revision)["result"]["message"] == accepted["result"]["message"]


def test_group_update_replay_conflict_noop_expiry_and_stale_migration(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service, legacy=True)
    service.store.put("group_draft", pair.group_id, {"text": "legacy one"})
    stale = query(invoke, scope)["result"]
    service.store.put("group_draft", pair.group_id, {"text": "legacy two"})
    assert not save(invoke, scope, "overwrite newer legacy", stale)["ok"]
    assert service.store.record_count(STATE) == 0 and service.store.get("group_draft", pair.group_id)["text"] == "legacy two"
    initial = query(invoke, scope)["result"]
    first = save(invoke, scope, "first", initial)
    newer = save(invoke, scope, "newer")["result"]["composer"]
    replay = save(invoke, scope, "first", initial)
    assert replay["result"]["composer"] == newer and replay["result"]["applied_revision"] == first["result"]["applied_revision"]
    assert save(invoke, scope, "different", initial)["error"]["code"] == "idempotency_conflict"
    for identifier, receipt in service.store.items(UPDATES):
        service.store.put(UPDATES, identifier, {**receipt, "expires_at": time.time()-1})
    assert save(invoke, scope, "first", initial)["error"]["code"] == "idempotency_expired"
    assert query(invoke, scope)["result"]["text"] == "newer"


def test_group_send_membership_readset_and_global_key_collision_fail_without_acceptance(group_host, monkeypatch):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service)
    revision = save(invoke, scope, "pending group text")["result"]["applied_revision"]
    assert invoke("workspace.create", {"profile": scope["profile"], "name": "Global collision", "description": ""}, revision)["ok"]
    assert send(invoke, scope, revision)["error"]["code"] == "idempotency_conflict"
    revision = save(invoke, scope, "another pending text")["result"]["applied_revision"]
    original = service.prepare_group_send
    def change_authority(*args):
        plan = original(*args)
        current = service.store.get("group", pair.group_id)
        service.store.put("group", pair.group_id, {**current, "status": "removed"})
        return plan
    monkeypatch.setattr(service, "prepare_group_send", change_authority)
    assert send(invoke, scope, revision)["error"]["code"] == "conflict"
    assert service.store.record_count("group_message") == service.store.record_count(SENDS) == 0
    assert all(row["text"] == "" for row in service.store.list(STATE))


def test_group_history_erasure_rotates_draft_and_expired_receipt_remains_consumed(group_host):
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service)
    revision = save(invoke, scope, "accepted group text")["result"]["applied_revision"]
    assert send(invoke, scope, revision)["ok"]
    state = save(invoke, scope, "erase unsent group text")["result"]["composer"]
    service.delete_conversation("group", pair.group_id)
    erased = query(invoke, scope)["result"]
    assert erased["text"] == "" and erased["revision"] != state["revision"]
    assert not save(invoke, scope, "late autosave", state)["ok"]
    assert query(invoke, scope, revision)["error"]["code"] == "idempotency_expired"
    assert send(invoke, scope, revision)["error"]["code"] == "idempotency_expired"
    assert service.store.record_count("group_message") == 0


def test_group_tokens_are_separate_from_direct_composer_and_group_feature_is_complete(group_host, monkeypatch):
    from mesh_chat.core_api.messages import MessageScope
    from mesh_chat.core_api.service_composer import ComposerStorage
    pair, _ = group_host
    service = pair.owner
    invoke, scope, _ = public(service)
    caps = invoke("runtime.capabilities")
    Draft202012Validator(json.loads((CONTRACTS / "observation-result-v1.schema.json").read_text())).validate(caps)
    direct = ComposerStorage(service.store).token(MessageScope("group-composer-owner", "local"), pair.group_id, "revision")
    assert query(invoke, scope, direct)["error"]["code"] == "forbidden"
    monkeypatch.setattr(service, "prepare_group_send", None)
    unsupported, _, _ = public(service)
    supported = unsupported("runtime.capabilities")["result"]["operations"]
    assert not any(operation in supported for operation in ("group.composer_query", "group.composer_update", "group.message_enqueue_draft"))


def test_actual_signed_member_removal_erases_draft_and_denies_accepted_lookup(group_host):
    from test_group_service import _sent_values, _deliver
    pair, _ = group_host
    service = pair.member
    invoke, scope, _ = public(service)
    revision = save(invoke, scope, "member acceptance")["result"]["applied_revision"]
    assert send(invoke, scope, revision)["ok"]
    state = save(invoke, scope, "member unsent draft")["result"]["composer"]
    pair.owner.remove_group_member(pair.group_id, pair.member_profile["destination_hash"])
    removal = _sent_values(pair.owner_network, "group_manifest",
        recipient=bytes.fromhex(pair.member_profile["destination_hash"]), epoch=3)[-1]
    _deliver(service, removal, source_profile=pair.owner_profile, destination_profile=pair.member_profile)
    assert service.store.get("group", pair.group_id)["status"] == "removed"
    current = service.store.list(STATE)[0]
    assert current["text"] == "" and current["revision"] != state["revision"]
    before = rows(service)
    for reply in (query(invoke, scope), query(invoke, scope, revision), send(invoke, scope, revision),
                  save(invoke, scope, "late revoked update", state)):
        assert reply["error"]["code"] == "forbidden", reply
        assert "member acceptance" not in json.dumps(reply) and "member unsent draft" not in json.dumps(reply)
    assert rows(service) == before
