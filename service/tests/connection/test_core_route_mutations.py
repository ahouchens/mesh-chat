"""Framed route parents over real signed documents, receipts and sealed storage.

Listener/router/DNS boundaries are counted fakes; no physical NAT claim.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.participant import create_access_document, create_route_update, verify_route_update
from mesh_chat import participant_service
from test_participant_keyed_preparation import hosts
from test_reconnect_prepared_mutations import prepared_pair
from test_workspace_service import _deliver_all, _flush


def client(service):
    session = bind_service_stream(service, lambda: Grant(
        "route-owner", frozenset({"observe", "read", "send", "approve"}), ("local",)))

    def exchange(operation, key=None, **params):
        value = {"api_version": 1, "request_id": "route:1", "operation": operation, "params": params}
        if key is not None:
            value["idempotency_key"] = key
        return json.loads(session.exchange(json.dumps(value).encode() + b"\n"))

    profile = exchange("runtime.capabilities")["result"]["profiles"][0]

    def route(action, key="route-create-stable-key", **params):
        if action == "create":
            params = {"scope_kind": "contact", "scope_id": "peer", **params}
        return exchange("route.update", key, profile=profile, action=action, **params)

    return route, exchange, profile


def incoming(service, peer, generation=1):
    access = create_access_document(peer, [{"host": "93.184.216.34", "port": 4242, "path": "upnp"}],
        network_name="route_test_network_123456", passphrase="route_test_passphrase_123456789",
        mode="participant_callback", expires_at=int(time.time()) + 3600)
    return create_route_update(peer, scope_kind="contact",
        scope_id=service._contact_route_scope(bytes.fromhex(service.store.get("contact", "peer")["destination_hash"])),
        audience_destination=bytes.fromhex(service._require_profile()["destination_hash"]),
        generation=generation, access=access)


def test_create_exact_completion_and_global_key_replay(hosts):
    open_host, mappings, _, _, peer = hosts
    service = open_host()
    route, exchange, profile = client(service)
    first = route("create")
    assert first["ok"], first
    result = first["result"]["route"]
    signed = verify_route_update(result["file"])
    intent = service.store.list("participant_host_intent")[0]
    receipt = service.store.operation_result(intent["id"], intent["input_digest"])
    assert receipt == {"action": "participant_host", "intent_id": intent["id"]}
    assert signed.generation == result["generation"] == 1
    assert service.store.get("participant_host_completion", intent["id"])["result"]["file"] == result["file"]
    assert service.store.get("route_update_outbox", intent["id"])["document"] == result["file"]
    assert route("create") == first
    assert len(mappings) == service.network.created == 1
    assert len(service.store.list("route_generation")) == 1
    conflict = route("apply", update=incoming(service, peer))
    assert conflict["error"]["code"] == "idempotency_conflict", conflict
    assert service.store.list("participant_access") == []
    conflict = exchange("runtime.mutate", "route-create-stable-key", profile=profile,
        action="notification_previews", hidden=True)
    assert conflict["error"]["code"] == "idempotency_conflict", conflict
    assert service.notification_state()["hide_previews"] is False


@pytest.mark.parametrize("phase", ["reservation", "completion"])
def test_create_commit_fault_never_allocates_another_resource(hosts, monkeypatch, phase):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    route, _, _ = client(service)
    original = service.store._write_records_locked

    def fail(records, deletions=()):
        records = list(records)
        original(records, deletions)
        target = "participant_host_intent" if phase == "reservation" else "participant_host_completion"
        if any(kind == target for kind, _, _ in records):
            raise OSError("injected route parent commit fault")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    reply = route("create")
    assert reply["error"]["code"] == "unavailable", reply
    assert service.store.list("route_generation") == service.store.list("route_update_outbox") == []
    assert service.store.list("participant_host_completion") == []
    assert len(mappings) == (0 if phase == "reservation" else 1)
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    reply = route("create")
    assert reply["ok"] and reply["result"]["route"]["generation"] == 1, reply
    assert len(mappings) == service.network.created == 1


def test_live_delivery_is_after_completion_and_uncertain_handoff_reuses_exact_job(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    attempts = []
    monkeypatch.setattr(service.network, "path_known", lambda *_: True, raising=False)
    monkeypatch.setattr(service.network, "recipient_ready", lambda *_: True, raising=False)

    def send(**values):
        assert service.store.list("participant_host_completion")
        assert service.store.list("route_generation")[0]["generation"] == 1
        assert service.store.list("route_update_outbox")[0]["document"] == values["route_update"]
        attempts.append(values)
        if len(attempts) == 1:
            raise OSError("lost native handoff reply")
        return "native-route-job"

    monkeypatch.setattr(service.network, "send", send, raising=False)
    route, _, _ = client(service)
    first = route("create")
    assert first["ok"] and first["result"]["route"]["delivery_mode"] == "share_required", first
    assert route("create") == first and len(attempts) == 1
    service._retry_route_update_outbox()
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    again = route("create")
    assert again["ok"] and again["result"]["route"]["delivery_mode"] == "automatic", again
    assert len(attempts) == 2 and len(mappings) == 1


def test_lost_completed_reply_recovers_same_runtime_and_restart_fences_resource(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    route, _, _ = client(service)

    def fail(*_):
        raise OSError("injected after route completion")

    monkeypatch.setattr(service, "_retry_route_update_outbox", fail)
    reply = route("create")
    assert reply["error"]["code"] == "unavailable", reply
    completed = service.store.list("participant_host_completion")[0]
    assert route("create")["result"]["route"]["file"] == completed["result"]["file"]
    service.close()
    reopened = open_host()
    route, _, _ = client(reopened)
    reply = route("create")
    assert reply["error"]["code"] == "resync_required", reply
    assert len(mappings) == 1 and reopened.network.created == 0


@pytest.mark.parametrize("revoke", [False, True])
def test_create_replay_checks_current_generation_and_consent(hosts, revoke):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    route, _, _ = client(service)
    assert route("create")["ok"]
    if revoke:
        contact = service.store.get("contact", "peer")
        service.store.put("contact", "peer", {**contact, "trust": "blocked"})
    else:
        assert route("create", "route-create-newer-key")["ok"]
    reply = route("create")
    assert reply["error"]["code"] == ("forbidden" if revoke else "resync_required"), reply
    assert len(mappings) == (1 if revoke else 2)


def test_apply_access_generation_and_receipt_are_atomic_before_dns(hosts, monkeypatch):
    open_host, _, _, lookups, peer = hosts
    service = open_host()
    raw = incoming(service, peer)
    old_access = create_access_document(peer, [{"host": "93.184.216.34", "port": 4243, "path": "upnp"}],
        network_name="old_route_network_123456", passphrase="old_route_passphrase_123456789",
        mode="participant_callback", expires_at=int(time.time()) + 3600)
    old_record = {"id": old_access["id"], "access": old_access,
        "scopes": [{"kind": "contact", "id": "peer"}, {"kind": "workspace", "id": "other"}],
        "resolution_attempted": True, "resolved_endpoints": [], "candidate_results": []}
    service.store.put("participant_access", old_access["id"], old_record)
    route, _, _ = client(service)
    original = service.store._write_records_locked

    def fail(records, deletions=()):
        original(records, deletions)
        raise OSError("injected route apply commit fault")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    reply = route("apply", "route-apply-stable-key", update=raw)
    assert reply["error"]["code"] == "unavailable", reply
    assert service.store.list("participant_access") == [old_record]
    assert service.store.list("route_generation") == []
    assert service.store.list("workspace_operation") == [] and lookups == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    monkeypatch.setattr(service.network, "remember_contact", lambda *_: None, raising=False)
    reply = route("apply", "route-apply-stable-key", update=raw)
    assert reply["ok"], reply
    assert service.store.get("participant_access", old_access["id"])["scopes"] == [{"kind": "workspace", "id": "other"}]
    count = len(lookups)
    assert route("apply", "route-apply-stable-key", update=raw) == reply
    assert len(lookups) == count
    changed = route("apply", "route-apply-stable-key", update=incoming(service, peer, 2))
    assert changed["error"]["code"] == "idempotency_conflict", changed
    service.close()
    reopened = open_host()
    reopened.network = None
    route, _, _ = client(reopened)
    replay = route("apply", "route-apply-stable-key", update=raw)
    assert replay["ok"] and replay["result"]["route"]["connection_results"] == [], replay
    access_id = verify_route_update(raw).access["id"]
    reopened.store.delete("participant_access", access_id)
    assert route("apply", "route-apply-stable-key", update=raw)["error"]["code"] == "forbidden"


def test_capacity_and_current_resource_errors_are_typed_before_allocation(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    route, _, _ = client(service)
    monkeypatch.setattr(participant_service, "MAX_PARTICIPANT_INTENTS", 0)
    reply = route("create")
    assert reply["error"]["code"] == "resource_exhausted", reply
    assert mappings == [] and service.store.list("workspace_operation") == []


def test_expired_create_intent_requires_resync_without_new_resource(hosts):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    route, _, _ = client(service)
    assert route("create")["ok"]
    intent = service.store.list("participant_host_intent")[0]
    service.store.put("participant_host_intent", intent["id"], {**intent, "maximum_expires_at": int(time.time()) - 1})
    reply = route("create")
    assert reply["error"]["code"] == "resync_required", reply
    assert len(mappings) == len(removed) == 1


def test_apply_postcommit_failure_and_superseded_generation_never_restore_access(hosts, monkeypatch):
    open_host, _, _, lookups, peer = hosts
    service = open_host()
    route, _, _ = client(service)
    raw = incoming(service, peer)
    reconcile = service.reconcile_prepared_participant_access

    def fail():
        raise OSError("injected after committed access replacement")

    monkeypatch.setattr(service, "reconcile_prepared_participant_access", fail)
    reply = route("apply", "route-postcommit-key", update=raw)
    assert reply["error"]["code"] == "unavailable", reply
    assert service.store.list("participant_reconcile") and service.store.list("workspace_operation")
    assert route("apply", "route-postcommit-key", update=raw)["ok"]
    assert lookups == []
    monkeypatch.setattr(service, "reconcile_prepared_participant_access", reconcile)
    monkeypatch.setattr(service.network, "remember_contact", lambda *_: None, raising=False)
    newer = incoming(service, peer, 2)
    assert route("apply", "route-apply-newer-key", update=newer)["ok"]
    reply = route("apply", "route-postcommit-key", update=raw)
    assert reply["error"]["code"] == "resync_required", reply
    assert service.store.list("route_generation")[0]["generation"] == 2


def test_two_framed_sessions_converge_on_one_resource_and_document(hosts):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    first, _, _ = client(service)
    second, _, _ = client(service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda route: route("create"), [first, second]))
    assert replies[0]["ok"] and replies[0] == replies[1], replies
    assert len(mappings) == service.network.created == 1
    assert len(service.store.list("route_generation")) == 1


def test_workspace_apply_replay_rechecks_signed_local_membership(prepared_pair):
    owner, network, member, workspace = prepared_pair
    member.network = None
    access = create_access_document(owner._identity,
        [{"host": "93.184.216.34", "port": 4242, "path": "upnp"}],
        network_name="workspace_route_123456789", passphrase="workspace_route_passphrase_123456789",
        mode="participant_callback", expires_at=int(time.time()) + 3600)
    raw = create_route_update(owner._identity, scope_kind="workspace_device", scope_id=workspace["id"],
        audience_destination=bytes.fromhex(member._require_profile()["destination_hash"]), generation=1, access=access)
    route, _, _ = client(member)
    assert route("apply", "workspace-route-replay-key", update=raw)["ok"]
    local = member._require_workspace(workspace["id"])["local_member_id"]
    owner.remove_workspace_member(workspace["id"], local, str(uuid4()))
    _deliver_all(member, _flush(owner, network), source_profile=owner._require_profile(),
        recipient_profile=member._require_profile())
    assert member._require_workspace(workspace["id"])["state"] == "removed"
    reply = route("apply", "workspace-route-replay-key", update=raw)
    assert reply["error"]["code"] == "forbidden", reply
