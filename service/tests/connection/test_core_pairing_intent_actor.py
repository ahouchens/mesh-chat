"""Real framed Core/vault/crypto/supervisor with native/mailbox boundary doubles.

These producer component cases do not qualify packaged native traffic or SC21.
"""
from dataclasses import replace
import json
import sqlite3
import time
from time import monotonic

import pytest
from jsonschema import Draft202012Validator

from test_core_pairing_intents import public_client
from test_pairing_runtime import native_pairing, run_until
from test_contracts import CONTRACTS
from test_core_sdk_distribution import installed_consumer, run_consumer
from mesh_chat.connection.model import Resource
from mesh_chat.core_api.service_pairing_intents import PAIRING_INTENT_LIMITS


def begin(invoke, profile, key="public-offer-caller-key01", **options):
    return invoke("peer.pairing_begin", {"profile": profile, "role": "offer", **options}, key)


def query(invoke, profile, pairing):
    reply = invoke("peer.pairing_query", {"profile": profile, "pairing": pairing})
    assert reply["ok"], reply
    Draft202012Validator(json.loads((CONTRACTS / "core-api/pairing-intent-result-v1.schema.json").read_text())).validate(reply)
    return reply["result"]


def cancel(invoke, profile, pairing, key="public-cancel-caller-key1"):
    return invoke("peer.pairing_cancel", {"profile": profile, "pairing": pairing}, key)


def row(service):
    return service.store.list("api_pairing_intent")[0]


def test_actual_actor_admission_and_same_key_replay_have_one_exact_child_and_no_raw_ids(native_pairing):
    create, _ = native_pairing
    service, host, created, _, _, _ = create()
    invoke, _, profile = public_client(service)
    original = host.createOffer
    def observe(*args):
        assert len(service.store.list("api_pairing_intent")) == 1
        assert len(service.store.list("workspace_operation")) == 2  # Core intent then native admission.
        return original(*args)
    host.createOffer = observe
    first = begin(invoke, profile)
    assert first["ok"], first
    pairing = first["result"]["pairing"]
    assert first["result"]["state"] == "reserved" and created == []
    accepted = row(service)
    assert service._native_pairing_contexts[accepted["native_id"]]["expires_at"] == accepted["expires_at"]
    run_until(service, lambda: query(invoke, profile, pairing)["state"] == "offer_ready")
    observed = query(invoke, profile, pairing)
    assert observed["pairing_code"] and observed["expires_at"] == accepted["expires_at"]
    assert begin(invoke, profile)["result"] == observed
    assert len(created) == 1 and created[0][1]["iceTransportPolicy"] == "relay"
    assert all(raw not in json.dumps(observed) for raw in (accepted["native_id"], accepted["operation_id"]))
    assert set(observed) == {"profile", "pairing", "state", "expires_at", "pairing_code"}
    assert len(service.store.list("api_pairing_intent")) == 1
    assert all(quota["count"] == 1 for quota in service.store.list("api_pairing_quota"))


def test_failed_public_parent_rolls_back_scope_quota_receipt_and_vault_floor_before_admission(native_pairing, monkeypatch):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    invoke, _, profile = public_client(service)
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    original = service.store._write_records_locked
    def fail(*args):
        original(*args)
        raise OSError("public parent rolled back")
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert begin(invoke, profile)["error"]["code"] == "unavailable"
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before
    assert service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == "1"
    assert created == [] and not getattr(service, "_native_pairing_contexts", {})
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert begin(invoke, profile)["ok"]
    assert service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == "2"


def test_lost_public_commit_return_resumes_original_child_without_replacement(native_pairing, monkeypatch):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    invoke, _, profile = public_client(service)
    original, lost = service.store.conditional_put_and_delete, []
    def lose(*args, **kwargs):
        result = original(*args, **kwargs)
        if not lost:
            lost.append(True)
            raise OSError("public reservation committed before reply loss")
        return result
    monkeypatch.setattr(service.store, "conditional_put_and_delete", lose)
    assert begin(invoke, profile)["error"]["code"] == "unavailable"
    accepted = row(service)
    assert not getattr(service, "_native_pairing_contexts", {})
    assert begin(invoke, profile, "replacement-offer-key00")["error"]["code"] == "resource_exhausted"
    replay = begin(invoke, profile)
    assert replay["ok"] and replay["result"]["pairing"] == accepted["pairing"]
    assert list(service._native_pairing_contexts) == [accepted["native_id"]]
    run_until(service, lambda: query(invoke, profile, accepted["pairing"])["state"] == "offer_ready")
    assert len(created) == 1 and len(service.store.list("api_pairing_intent")) == 1


@pytest.mark.parametrize("allocated", [False, True])
def test_committed_cancel_return_loss_is_reconciled_without_renderer_retry(native_pairing, monkeypatch, allocated):
    create, _ = native_pairing
    service, _, created, closed, _, _ = create()
    invoke, _, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    if allocated:
        run_until(service, lambda: query(invoke, profile, pairing)["state"] == "offer_ready")
    original, lost = service.store.conditional_put_and_delete, []
    def lose(*args, **kwargs):
        result = original(*args, **kwargs)
        if not lost:
            lost.append(True)
            raise OSError("cancel flag committed before effect/reply")
        return result
    monkeypatch.setattr(service.store, "conditional_put_and_delete", lose)
    assert cancel(invoke, profile, pairing)["error"]["code"] == "unavailable"
    assert query(invoke, profile, pairing)["state"] == "retiring"
    assert query(invoke, profile, pairing)["pairing_code"] is None
    run_until(service, lambda: row(service)["terminal_state"] == "retired")
    assert query(invoke, profile, pairing)["state"] == "retired"
    assert len(created) == int(allocated)
    assert not created or created[0][0] in closed
    assert service.store.get("api_pairing_owner", "active") is None
    before = len(service.store.list("workspace_operation"))
    assert cancel(invoke, profile, pairing)["result"]["state"] == "retired"
    assert len(service.store.list("workspace_operation")) == before
    assert all(quota["count"] == 2 for quota in service.store.list("api_pairing_quota"))


@pytest.mark.parametrize("allocated", [False, True])
def test_original_deadline_fences_an_admitted_child_and_never_renews_on_replay(native_pairing, monkeypatch, allocated):
    create, _ = native_pairing
    service, _, created, closed, _, _ = create()
    invoke, _, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    if allocated:
        run_until(service, lambda: query(invoke, profile, pairing)["state"] == "offer_ready")
    accepted = row(service)
    assert service._native_pairing_contexts[accepted["native_id"]]["expires_at"] == accepted["expires_at"]
    monkeypatch.setattr(time, "time", lambda: accepted["expires_at"] + 1)
    replay = begin(invoke, profile)
    assert replay["ok"], replay
    assert replay["result"]["state"] == "retiring" and replay["result"]["pairing_code"] is None
    assert replay["result"]["expires_at"] == accepted["expires_at"]
    assert len(created) == int(allocated)
    run_until(service, lambda: row(service)["terminal_state"] == "retired")
    assert query(invoke, profile, pairing)["state"] == "retired"
    assert begin(invoke, profile)["result"]["state"] == "retired"
    assert len(created) == int(allocated) and (not created or created[0][0] in closed)


def test_foreign_caller_and_revoked_grants_cannot_query_code_replay_or_cancel(native_pairing):
    create, _ = native_pairing
    service, _, created, closed, _, _ = create()
    invoke, grants, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    run_until(service, lambda: query(invoke, profile, pairing)["state"] == "offer_ready")
    other, _, other_profile = public_client(service, "different-sdk-owner")
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    assert other("peer.pairing_query", {"profile": other_profile, "pairing": pairing})["error"]["code"] == "forbidden"
    assert cancel(other, other_profile, pairing)["error"]["code"] == "forbidden"
    grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    assert begin(invoke, profile)["error"]["code"] == "forbidden"
    assert cancel(invoke, profile, pairing)["error"]["code"] == "forbidden"
    assert invoke("peer.pairing_query", {"profile": profile, "pairing": pairing})["error"]["code"] == "forbidden"
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before
    run_until(service, lambda: row(service)["terminal_state"] == "retired")
    assert len(created) == 1 and created[0][0] in closed


def test_key_conflicts_before_actor_and_no_replacement_for_another_active_intent(native_pairing, monkeypatch):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    invoke, _, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    def forbidden(*args, **kwargs): pytest.fail("Conflicting key reached native actor")
    monkeypatch.setattr(service, "native_pairing_begin", forbidden)
    assert begin(invoke, profile, allow_direct_ip_disclosure=True)["error"]["code"] == "idempotency_conflict"
    assert cancel(invoke, profile, pairing, "public-offer-caller-key01")["error"]["code"] == "idempotency_conflict"
    assert begin(invoke, profile, "new-active-caller-key00")["error"]["code"] == "resource_exhausted"
    assert len(service.store.list("api_pairing_intent")) == 1 and created == []


def test_acknowledged_terminal_checkpoint_survives_reopen_without_native_readmission(native_pairing, tmp_path):
    create, _ = native_pairing
    root = tmp_path / "reopen"
    service, _, _, _, _, key = create(root)
    invoke, _, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    assert cancel(invoke, profile, pairing)["result"]["state"] == "retired"
    service.close()
    reopened, _, created, _, _, _ = create(root, key)
    invoke, _, same_profile = public_client(reopened)
    assert same_profile == profile
    assert query(invoke, same_profile, pairing)["state"] == "retired"
    assert begin(invoke, same_profile)["result"]["state"] == "retired"
    assert not created and not getattr(reopened, "_native_pairing_contexts", {})


def test_pre_retirement_vault_snapshot_reopens_as_unknown_without_new_admission(native_pairing, tmp_path):
    create, _ = native_pairing
    service, _, _, _, _, key = create()
    invoke, _, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    # A source component snapshot models interrupted durable receipts; this is
    # not a packaged process-crash or physical cleanup qualification.
    copied = tmp_path / "interrupted-receipts"
    copied.mkdir()
    with service._dispatch_lock, sqlite3.connect(copied / "mesh-chat.vault") as destination:
        service.store._db.backup(destination)
    service.close()
    reopened, _, created, _, _, _ = create(copied, key)
    invoke, _, same_profile = public_client(reopened)
    assert invoke("peer.pairing_query", {"profile": same_profile, "pairing": pairing})["error"]["code"] == "resync_required"
    assert begin(invoke, same_profile)["error"]["code"] == "resync_required"
    assert begin(invoke, same_profile, "restart-replacement-key")["error"]["code"] == "resync_required"
    assert not created and not getattr(reopened, "_native_pairing_contexts", {})


def test_current_core_grant_revoked_during_native_create_cannot_publish_admission_code(native_pairing):
    create, documents = native_pairing
    service, host, created, closed, _, _ = create()
    invoke, grants, profile = public_client(service)
    original = host.createOffer
    def revoke(*args):
        result = original(*args)
        grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
        return result
    host.createOffer = revoke
    assert begin(invoke, profile)["ok"]
    run_until(service, lambda: row(service)["terminal_state"] == "retired")
    assert len(created) == 1 and created[0][0] in closed and documents == {}
    assert begin(invoke, profile)["error"]["code"] == "forbidden"


@pytest.mark.parametrize("checkpoint_return_lost", [False, True])
def test_public_cancel_after_exact_transfer_never_reclaims_adopted_carrier(native_pairing, monkeypatch, checkpoint_return_lost):
    """Signed contact/capability rows and attachment/path are component fixtures."""
    from test_reconnect_service import _add_contact
    create, _ = native_pairing
    first, _, created, closed, _, _ = create()
    second, _, _, _, _, _ = create()
    offer, _, offer_profile = public_client(first)
    answer, _, answer_profile = public_client(second)
    offer_handle = begin(offer, offer_profile)["result"]["pairing"]
    run_until(first, lambda: query(offer, offer_profile, offer_handle)["state"] == "offer_ready")
    code = query(offer, offer_profile, offer_handle)["pairing_code"]
    accepted = answer("peer.pairing_begin", {"profile": answer_profile, "role": "answer", "pairing_code": code}, "public-answer-caller-key1")
    assert accepted["ok"], accepted
    answer_handle = accepted["result"]["pairing"]
    run_until(second, lambda: query(answer, answer_profile, answer_handle)["state"] == "awaiting_approval")
    first._connection_runtime.now = lambda: monotonic() + 6
    run_until(first, lambda: query(offer, offer_profile, offer_handle)["state"] == "awaiting_approval")
    _add_contact(first, "contact-second", second._identity, second._require_profile()["destination_hash"])
    _add_contact(second, "contact-first", first._identity, first._require_profile()["destination_hash"])
    for service, other, contact in ((first, second, "contact-first"), (second, first, "contact-second")):
        context = service._native_pairing_contexts[row(service)["native_id"]]
        document = other.reconnect_capabilities_create(contact)["capabilities"]
        service._native_control_receive(context["session"], "mesh-onboarding",
            json.dumps({"type": "connection_capabilities", "document": document}))
    context = first._native_pairing_contexts[row(first)["native_id"]]
    physical, logical = context["physical"], context["session"]
    profile_id = first._native_webrtc_controls[logical]["profile_id"]
    assert first._native_pairing_ready(context)
    def attach(session, *, expected_physical):
        assert session == logical and expected_physical == physical
        return {"bridge_id": "component-bridge"}
    monkeypatch.setattr(first, "webrtc_attach_native", attach)
    monkeypatch.setattr(first, "reconnect_path_status", lambda _: {"has_path": True, "ready": True})
    original, lost = first.store.conditional_put_and_delete, []
    def checkpoint(*args, **kwargs):
        result = original(*args, **kwargs)
        records = args[1]
        if checkpoint_return_lost and not lost and any(kind == "api_pairing_intent" and data.get("terminal_state") == "transferred"
                                                       for kind, _, data in records):
            lost.append(True)
            raise OSError("terminal checkpoint committed before return loss")
        return result
    monkeypatch.setattr(first.store, "conditional_put_and_delete", checkpoint)
    first._connection_runtime.now = lambda: monotonic() + 12
    run_until(first, lambda: row(first)["terminal_state"] == "transferred")
    first._connection_runtime.now = monotonic
    run_until(first, lambda: first._native_webrtc_profile_sessions.get(profile_id) == logical)
    run_until(first, lambda: any(state.carrier is not None and state.key.profile_id == profile_id
                                for state in first._connection_runtime.owner.snapshots()))
    state = next(state for state in first._connection_runtime.owner.snapshots() if state.key.profile_id == profile_id)
    assert state.carrier.resource == Resource("native", physical)
    assert cancel(offer, offer_profile, offer_handle)["result"]["state"] == "transferred"
    assert query(offer, offer_profile, offer_handle)["state"] == "transferred"
    assert logical in first._native_webrtc_live and physical not in closed and len(created) == 1
    assert first.store.get("api_pairing_owner", "active") is None
    assert not first._connection_runtime.snapshots()[row(first)["native_id"]]["messaging_ready"]
    assert bool(lost) == checkpoint_return_lost


def test_actual_installed_sdk_begins_queries_and_cancels_real_actor(native_pairing, installed_consumer):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    report = run_consumer(installed_consumer, service, "--exercise-pairing-owner")
    assert all(report[name] for name in ("sdk_only", "began", "same_pairing", "queried", "cancelled", "cancel_replayed"))
    assert row(service)["terminal_state"] == "retired" and not created
    assert len(service.store.list("workspace_operation")) == 3
    assert all(quota["count"] == 2 for quota in service.store.list("api_pairing_quota"))


def test_key_quota_refuses_new_admission_before_actor_but_original_keys_still_replay(native_pairing, monkeypatch):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    invoke, _, profile = public_client(service)
    pairing = begin(invoke, profile)["result"]["pairing"]
    assert cancel(invoke, profile, pairing)["result"]["state"] == "retired"
    monkeypatch.setitem(PAIRING_INTENT_LIMITS, "pairing_keys_per_caller_profile", 2)
    def forbidden(*args, **kwargs): pytest.fail("Key capacity reached native admission")
    monkeypatch.setattr(service, "native_pairing_begin", forbidden)
    assert begin(invoke, profile)["result"]["state"] == "retired"
    assert begin(invoke, profile, "capacity-replacement-key")["error"]["code"] == "resource_exhausted"
    assert len(service.store.list("api_pairing_intent")) == 1 and not created
    assert service.store.get("api_pairing_owner", "active") is None


def test_cancel_key_cannot_target_a_replacement_and_keys_conflict_across_core_operations(native_pairing):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    invoke, _, profile = public_client(service)
    workspace_key = "cross-core-operation-key"
    assert invoke("workspace.create", {"profile": profile, "name": "Synthetic", "description": ""}, workspace_key)["ok"]
    assert begin(invoke, profile, workspace_key)["error"]["code"] == "idempotency_conflict"
    first = begin(invoke, profile)["result"]["pairing"]
    assert cancel(invoke, profile, first)["result"]["state"] == "retired"
    second = begin(invoke, profile, "second-public-offer-key")["result"]["pairing"]
    before = len(service.store.list("workspace_operation"))
    assert cancel(invoke, profile, second)["error"]["code"] == "idempotency_conflict"
    pending = next(item for item in service.store.list("api_pairing_intent") if item["pairing"] == second)
    assert pending["cancel_requested"] is False and pending["terminal_state"] is None
    assert len(service.store.list("workspace_operation")) == before and not created
