"""Lost renderer tickets recover through real framed Core and encrypted rows."""
from dataclasses import replace
import json

import pytest
from jsonschema import Draft202012Validator

from mesh_chat.core_api.call_operations import (CALL_OPERATION_LIMITS, CallRetirementAcknowledgment,
                                                CallRetirementTicket, acknowledge_call_retirement)
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from test_core_messages import host
from test_core_call_idempotency import FINGERPRINT, SDP
from test_contracts import CONTRACTS
from test_core_sdk_distribution import installed_consumer, run_consumer


def client(service, caller="recovery-ui"):
    grants = [Grant(caller, frozenset({"observe", "send", "read"}), ("local",))]
    stream = bind_service_stream(service, lambda: grants[0], call_retirement=getattr(service, "_test_call_retirement", None))
    def invoke(operation, params=None, key=None):
        value = {"api_version": 1, "request_id": "call:recover", "operation": operation, "params": params or {}}
        if key is not None:
            value["idempotency_key"] = key
        return decode_frame(stream.exchange(encode_frame(value)))
    caps = invoke("runtime.capabilities")
    assert caps["ok"], caps
    return invoke, grants, caps["result"]["profiles"][0]


def start(invoke, profile, key="lost-start-caller-key"):
    return invoke("call.control", {"profile": profile, "action": "start", "contact_id": "internal-peer",
                  "media": "audio", "sdp": SDP, "dtls_fingerprint": FINGERPRINT}, key)


def listing(invoke, profile):
    reply = invoke("call.operation_list", {"profile": profile})
    assert reply["ok"], reply
    Draft202012Validator(json.loads((CONTRACTS / "core-api/call-operation-result-v1.schema.json").read_text())).validate(reply)
    return reply["result"]["operations"]


def abandon(invoke, profile, operation, key="abandon-caller-key-001"):
    return invoke("call.operation_abandon", {"profile": profile, "operation": operation}, key)


@pytest.fixture
def recovery_host(host):
    class PendingRetirement:
        owner_incarnation = "test-renderer-owner-0001"
        def request_retirement(self, ticket): return None
    def open_service():
        service = host()
        service._test_call_retirement = PendingRetirement()
        return service
    return open_service


def test_committed_lost_reply_is_discoverable_without_the_renderer_key_or_sdp(recovery_host, monkeypatch):
    service = recovery_host()
    invoke, _, profile = client(service)
    monkeypatch.setattr(service, "_attempt", lambda *_: (_ for _ in ()).throw(OSError("lost reply")))
    assert start(invoke, profile)["error"]["code"] == "unavailable"
    again, _, same_profile = client(service)
    rows = listing(again, same_profile)
    assert len(rows) == 1 and rows[0]["disposition"] == "live"
    assert not rows[0]["replacement_safe"]
    raw = service.store.list("api_call_operation")[0]
    serialized = json.dumps(rows)
    assert raw["call_id"] not in serialized and raw["operation_id"] not in serialized
    assert raw["runtime_epoch"] not in serialized and "internal-peer" not in serialized
    assert SDP not in serialized and FINGERPRINT not in serialized
    assert SDP not in json.dumps(service.store.list("api_call_operation"))
    assert len(service.store.list("message")) == len(service.store.list("workspace_operation")) == 1
    reply = again("call.operation_query", {"profile": profile, "operation": rows[0]["operation"]})
    assert reply["result"]["operation"] == rows[0]


@pytest.mark.parametrize("persist", [True, False])
def test_reopen_never_claims_media_retired_and_abandonment_survives_another_reopen(recovery_host, persist):
    service = recovery_host()
    service.update_call_settings({**service._call_settings.to_dict(), "store_call_signaling": persist})
    invoke, _, profile = client(service)
    assert start(invoke, profile)["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    old_signals = {item["id"] for item in service.store.list("message")}
    service.close()
    reopened = recovery_host()
    invoke, _, same_profile = client(reopened)
    row = listing(invoke, same_profile)[0]
    assert row["operation"] == operation and row["disposition"] == "unknown_runtime"
    assert not row["current_runtime"] and not row["replacement_safe"]
    assert start(invoke, same_profile)["error"]["code"] == "resync_required"
    assert start(invoke, same_profile, "replacement-start-key00")["error"]["code"] == "resync_required"
    result = abandon(invoke, same_profile, operation)
    assert result["ok"], result
    assert result["result"]["operation"]["disposition"] == "cleanup_pending"
    assert not result["result"]["operation"]["replacement_safe"]
    assert old_signals.isdisjoint(item["id"] for item in reopened.store.list("message"))
    assert len(reopened.store.list("call")) == int(persist)
    messages = dict(reopened.store.items("message"))
    reopened.close()
    resumed = recovery_host()
    invoke, _, same_profile = client(resumed)
    assert abandon(invoke, same_profile, operation)["result"]["operation"]["disposition"] == "cleanup_pending"
    assert dict(resumed.store.items("message")) == messages
    assert start(invoke, same_profile, "replacement-start-key00")["error"]["code"] == "resync_required"


@pytest.mark.parametrize("ack_kind", ["none", "boolean", "wrong_call", "wrong_epoch", "wrong_owner", "wrong_caller", "not_retired", "exact"])
def test_only_exact_trusted_retirement_acknowledgment_releases_replacement(recovery_host, ack_kind):
    service = recovery_host()
    seen = []
    class Retirement:
        owner_incarnation = "test-renderer-owner-0001"
        def request_retirement(self, ticket):
            seen.append(ticket)
            if ack_kind == "none": return None
            if ack_kind == "boolean": return True
            if ack_kind == "wrong_call": ticket = replace(ticket, call_id="wrong-call")
            if ack_kind == "wrong_epoch": ticket = replace(ticket, runtime_epoch="old-epoch")
            if ack_kind == "wrong_owner": ticket = replace(ticket, owner_incarnation="other-renderer-owner")
            if ack_kind == "wrong_caller": ticket = replace(ticket, caller="other-caller")
            return CallRetirementAcknowledgment(ticket, ack_kind != "not_retired")
    service._test_call_retirement = Retirement()
    invoke, _, profile = client(service)
    assert start(invoke, profile)["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    reply = abandon(invoke, profile, operation)
    assert reply["ok"], reply
    row = reply["result"]["operation"]
    assert row["replacement_safe"] == (ack_kind == "exact")
    assert row["disposition"] == ("retired" if ack_kind == "exact" else "cleanup_pending")
    assert isinstance(seen[0], CallRetirementTicket)
    assert start(invoke, profile)["error"]["code"] == "resync_required"  # Old key is permanently fenced.
    replacement = start(invoke, profile, "new-explicit-start-key")
    assert replacement["ok"] if ack_kind == "exact" else replacement["error"]["code"] == "resync_required"


def test_abandon_rollback_has_no_cleanup_effect_or_native_retirement_request(recovery_host, monkeypatch):
    service = recovery_host()
    requests = []
    class Retirement:
        owner_incarnation = "test-renderer-owner-0001"
        def request_retirement(self, ticket): requests.append(ticket)
    service._test_call_retirement = Retirement()
    invoke, _, profile = client(service)
    started = start(invoke, profile)
    assert started["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    original = service.store._write_records_locked
    def fail(*args):
        original(*args)
        raise OSError("injected abandonment commit failure")
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert abandon(invoke, profile, operation)["error"]["code"] == "unavailable"
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before
    assert service.calls._memory[started["result"]["result"]["id"]]["state"] == "dialing"
    assert requests == []


def test_catalog_is_caller_scoped_and_every_request_rechecks_grants(recovery_host):
    service = recovery_host()
    invoke, grants, profile = client(service)
    assert start(invoke, profile)["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    other, _, other_profile = client(service, "other-caller")
    assert listing(other, other_profile) == []
    for op in ("call.operation_query", "call.operation_abandon"):
        reply = other(op, {"profile": other_profile, "operation": operation}, "foreign-abandon-key00" if op.endswith("abandon") else None)
        assert reply["error"]["code"] == "forbidden"
    grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    assert invoke("call.operation_list", {"profile": profile})["error"]["code"] == "forbidden"
    assert abandon(invoke, profile, operation)["error"]["code"] == "forbidden"
    assert service.store.list("api_call_operation")[0]["abandon_requested_at"] is None


def test_catalog_capacity_blocks_before_signing_and_accepted_keys_still_replay(recovery_host, monkeypatch):
    service = recovery_host()
    invoke, _, profile = client(service)
    accepted = start(invoke, profile)
    assert accepted["ok"]
    monkeypatch.setitem(CALL_OPERATION_LIMITS, "call_operations_per_caller_profile", 1)
    assert start(invoke, profile) == accepted
    monkeypatch.setattr(service.calls, "prepare_control", lambda *_: pytest.fail("capacity must be checked before signing"))
    assert start(invoke, profile, "another-start-key0000")["error"]["code"] == "resource_exhausted"
    assert len(service.store.list("api_call_operation")) == 1


def test_terminal_call_state_alone_does_not_release_native_resource_barrier(recovery_host):
    service = recovery_host()
    invoke, _, profile = client(service)
    created = start(invoke, profile)
    identifier = created["result"]["result"]["id"]
    assert invoke("call.control", {"profile": profile, "action": "end", "call_id": identifier, "reason": "completed"}, "end-known-call-key000")["ok"]
    row = listing(invoke, profile)[0]
    assert row["state"] == "ended" and row["disposition"] == "terminal_unretired"
    assert not row["replacement_safe"]
    assert start(invoke, profile, "terminal-replacement-key")["error"]["code"] == "resync_required"


def test_unbound_host_preserves_repeated_legacy_calls_and_does_not_advertise_recovery(host):
    service = host()
    invoke, _, profile = client(service)
    caps = invoke("runtime.capabilities")["result"]
    assert not any(operation.startswith("call.operation_") for operation in caps["operations"])
    first = start(invoke, profile)
    assert first["ok"], first
    identifier = first["result"]["result"]["id"]
    ended = invoke("call.control", {"profile": profile, "action": "end", "call_id": identifier, "reason": "completed"}, "legacy-end-call-key00")
    assert ended["ok"], ended
    assert start(invoke, profile, "legacy-next-call-key00")["ok"]
    assert service.store.list("api_call_operation") == []
    assert invoke("call.operation_list", {"profile": profile})["error"]["code"] == "unsupported_operation"


def test_expired_catalog_query_is_read_only_and_never_proves_retirement(recovery_host):
    service = recovery_host()
    invoke, _, profile = client(service)
    assert start(invoke, profile)["ok"]
    identifier, row = service.store.items("api_call_operation")[0]
    service.store.put("api_call_operation", identifier, {**row, "expires_at": 0})
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    result = listing(invoke, profile)[0]
    assert result["expired"] and not result["replacement_safe"]
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before


def test_revoked_peer_can_be_abandoned_without_a_new_signal_or_media_permission(recovery_host):
    service = recovery_host()
    invoke, _, profile = client(service)
    assert start(invoke, profile)["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    peer = service.store.get("contact", "internal-peer")
    service.store.put("contact", "internal-peer", {**peer, "trust": "blocked"})
    assert abandon(invoke, profile, operation)["ok"]
    assert service.store.list("message") == []
    assert listing(invoke, profile)[0]["disposition"] == "cleanup_pending"


def test_installed_public_sdk_recovers_and_abandons_without_renderer_call_ticket(recovery_host, installed_consumer):
    service = recovery_host()
    invoke, _, profile = client(service, "sdk-distribution-qualification")
    assert start(invoke, profile)["ok"]
    session = bind_service_stream(service, lambda: Grant("sdk-distribution-qualification",
        frozenset({"observe", "send", "read"}), ("local",)), call_retirement=service._test_call_retirement)
    report = run_consumer(installed_consumer, service, "--recover-call", session=session)
    assert all(report[name] for name in ("sdk_only", "recovered", "cleanup_pending", "replacement_blocked", "same_operation"))
    assert len(service.store.list("api_call_operation")) == 1
    assert len(service.store.list("workspace_operation")) == 2
    assert len(service.store.list("message")) == 1  # Only the durable cancellation signal remains.


@pytest.mark.parametrize("persist", [True, False])
def test_lost_abandon_commit_return_reconciles_memory_and_replays_one_cleanup_intent(recovery_host, monkeypatch, persist):
    service = recovery_host()
    service.update_call_settings({**service._call_settings.to_dict(), "store_call_signaling": persist})
    invoke, _, profile = client(service)
    created = start(invoke, profile)
    identifier = created["result"]["result"]["id"]
    operation = listing(invoke, profile)[0]["operation"]
    original = service.store.conditional_put_and_delete
    lost = []
    def commit_then_lose(*args, **kwargs):
        result = original(*args, **kwargs)
        if not lost:
            lost.append(True)
            raise OSError("injected lost abandonment commit return")
        return result
    monkeypatch.setattr(service.store, "conditional_put_and_delete", commit_then_lose)
    assert abandon(invoke, profile, operation)["error"]["code"] == "unavailable"
    rows = dict(service.store.items("message"))
    assert abandon(invoke, profile, operation)["result"]["operation"]["disposition"] == "cleanup_pending"
    assert dict(service.store.items("message")) == rows
    assert service.calls._memory[identifier]["state"] == "ended"
    assert len(service.store.list("workspace_operation")) == 2
    assert set(rows) <= set(service._direct_retry_snapshot())


def test_lost_end_commit_return_reloads_committed_call_before_replay(recovery_host, monkeypatch):
    service = recovery_host()
    invoke, _, profile = client(service)
    identifier = start(invoke, profile)["result"]["result"]["id"]
    original = service.store.conditional_put_and_delete
    lost = []
    def commit_then_lose(*args, **kwargs):
        result = original(*args, **kwargs)
        if not lost:
            lost.append(True)
            raise OSError("injected lost end commit return")
        return result
    monkeypatch.setattr(service.store, "conditional_put_and_delete", commit_then_lose)
    params = {"profile": profile, "action": "end", "call_id": identifier, "reason": "completed"}
    assert invoke("call.control", params, "lost-end-caller-key00")["error"]["code"] == "unavailable"
    assert service.calls._memory[identifier]["state"] == "dialing"
    assert invoke("call.control", params, "lost-end-caller-key00")["result"]["result"]["state"] == "ended"
    assert len(service.store.list("message")) == 2


def test_new_renderer_can_recover_old_owner_but_cannot_substitute_its_own_retirement(recovery_host):
    service = recovery_host()
    invoke, _, profile = client(service)
    assert start(invoke, profile)["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    tickets = []
    class NewOwner:
        owner_incarnation = "replacement-renderer-owner"
        def request_retirement(self, ticket):
            tickets.append(ticket)
            return CallRetirementAcknowledgment(ticket, True)
    service._test_call_retirement = NewOwner()
    replacement, _, same_profile = client(service)
    assert start(replacement, same_profile, "replacement-start-key00")["error"]["code"] == "resync_required"
    assert abandon(replacement, same_profile, operation)["result"]["operation"]["replacement_safe"]
    assert tickets[0].owner_incarnation == "test-renderer-owner-0001"
    assert start(replacement, same_profile, "replacement-start-key00")["ok"]
    assert {row["owner_incarnation"] for row in service.store.list("api_call_operation")} == {
        "test-renderer-owner-0001", "replacement-renderer-owner"}


def test_incomplete_retirement_port_is_refused_by_trusted_binding(host):
    service = host()
    class Incomplete:
        def request_retirement(self, ticket): return True
    with pytest.raises(ValueError, match="trusted bound media owner"):
        bind_service_stream(service, lambda: Grant("ui", frozenset({"observe"}), ("local",)), call_retirement=Incomplete())


def test_losing_provider_cannot_reopen_legacy_route_in_an_activated_vault(recovery_host, host):
    service = recovery_host()
    del service._test_call_retirement
    legacy, _, old_profile = client(service)
    class Pending:
        owner_incarnation = "test-renderer-owner-0001"
        def request_retirement(self, ticket): return None
    service._test_call_retirement = Pending()
    protected, _, profile = client(service)
    assert start(protected, profile)["ok"]
    assert start(legacy, old_profile, "legacy-bypass-key0000")["error"]["code"] == "resync_required"
    service.close()
    reopened = host()
    unbound, _, profile = client(reopened)
    assert start(unbound, profile, "restart-bypass-key000")["error"]["code"] == "resync_required"


def test_failed_acceptance_preserves_old_vault_floor_and_success_raises_it_atomically(recovery_host, monkeypatch):
    service = recovery_host()
    invoke, _, profile = client(service)
    def floor(): return service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0]
    assert floor() == "1"
    original = service.store._write_records_locked
    def fail(*args):
        original(*args)
        raise OSError("injected acceptance failure")
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert start(invoke, profile)["error"]["code"] == "unavailable"
    assert floor() == "1"
    assert service.store.list("api_call_operation") == service.store.list("api_call_quota") == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert start(invoke, profile)["ok"]
    assert floor() == "2"


def test_async_host_completion_is_durable_and_query_observes_it_without_another_cancel(recovery_host):
    service = recovery_host()
    tickets = []
    class Deferred:
        owner_incarnation = "test-renderer-owner-0001"
        def request_retirement(self, ticket): tickets.append(ticket)
    service._test_call_retirement = Deferred()
    invoke, _, profile = client(service)
    assert start(invoke, profile)["ok"]
    operation = listing(invoke, profile)[0]["operation"]
    assert abandon(invoke, profile, operation)["result"]["operation"]["disposition"] == "cleanup_pending"
    ticket = tickets[0]
    service.close()
    reopened = recovery_host()
    invoke, _, profile = client(reopened)
    assert not acknowledge_call_retirement(reopened, CallRetirementAcknowledgment(replace(ticket, profile="other-profile"), True))
    assert listing(invoke, profile)[0]["disposition"] == "cleanup_pending"
    events = []
    reopened.emit = events.append
    assert acknowledge_call_retirement(reopened, CallRetirementAcknowledgment(ticket, True))
    assert events == [{"type": "event", "event": "state_changed"}]
    assert listing(invoke, profile)[0]["replacement_safe"]
    assert len(reopened.store.list("workspace_operation")) == 2
    assert start(invoke, profile, "after-async-drain-key")["ok"]
