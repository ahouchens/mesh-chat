"""Keyed resource admission with real vaults and counted OS/network boundary fakes."""

import base64
from copy import deepcopy
import os
import time
from uuid import uuid4

import pytest
import RNS

from mesh_chat import participant_service
from mesh_chat.connectivity import MappingResult
from mesh_chat.errors import ContactNotApproved, DirectConnectionUnavailable, ValidationError
from mesh_chat.participant import create_access_document, create_route_update
from mesh_chat.participant_service import ParticipantReservationUnavailable
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


class CountedNetwork:
    def __init__(self):
        self.listeners = {}
        self.created = 0
        self.announces = 0
        self.clients = []

    def apply_participant_interfaces(self, listeners, clients):
        ids = {item["id"] for item in listeners}
        self.created += len(ids - self.listeners.keys())
        self.listeners = {identifier: [dict(item, port=45678) for item in listeners if item["id"] == identifier]
                          for identifier in ids}
        self.clients = deepcopy(clients)

    def participant_listener_bindings(self, identifier):
        return self.listeners.get(identifier, [])

    def participant_host_state(self, identifier):
        return {"listener_count": len(self.listeners.get(identifier, [])), "online": identifier in self.listeners}

    def reannounce(self):
        self.announces += 1

    def shutdown(self):
        return None


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    monkeypatch.setattr(participant_service, "default_routes", lambda: [])
    monkeypatch.setattr(participant_service, "global_ipv6_addresses", lambda **_: [])
    monkeypatch.setattr(participant_service, "public_ipv4_addresses", lambda **_: [])
    mappings, removed, lookups = [], [], []

    def map_port(port, **kwargs):
        mappings.append(port)
        return MappingResult("upnp", "93.184.216.34", 54321 + len(mappings), "192.168.1.20", port, 7200,
                             {"control_url": "http://192.168.1.1/control", "service_type": "test"})

    monkeypatch.setattr(participant_service, "create_port_mapping", map_port)
    monkeypatch.setattr(participant_service, "remove_port_mapping", lambda value: removed.append(deepcopy(value)))
    monkeypatch.setattr(participant_service, "resolve_public_endpoint", lambda value: lookups.append(deepcopy(value)) or ["93.184.216.34"])
    monkeypatch.setattr(participant_service, "candidate_connection_result", lambda *_: "connected")
    key, opened = os.urandom(32), []
    peer = RNS.Identity()

    def open_host():
        store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
        service = MeshChatService(store, tmp_path, lambda _: None)
        if store.get("profile", "local") is None:
            service.create_profile("Route owner")
        service.store.put("contact", "peer", {"id": "peer", "display_name": "Peer", "trust": "approved",
            "public_identity": base64.urlsafe_b64encode(peer.get_public_key()).decode(),
            "destination_hash": RNS.Destination.hash(peer, "lxmf", "delivery").hex()})
        service.network = CountedNetwork()
        opened.append(service)
        return service

    yield open_host, mappings, removed, lookups, peer
    for service in opened:
        service.close()


def reserve(service, operation=None, digest="a" * 64):
    canonical, audience, _, _ = service._route_update_binding("contact", "peer")
    generation_id = f"out:contact:{canonical}:{audience.hex()}"
    current = service.store.get("route_generation", generation_id) or {}
    return service.reserve_participant_host_intent(operation or str(uuid4()), digest, purpose="personal",
        scope_id=canonical, maximum_expires_at=int(time.time()) + 3600,
        relationship_scope={"kind": "contact", "id": "peer"}, peer_destination=audience.hex(),
        generation_id=generation_id, base_generation=int(current.get("generation", 0)))


def completion(service, intent, access):
    document = create_route_update(service._identity, scope_kind="contact", scope_id=intent["scope_id"],
        audience_destination=bytes.fromhex(intent["peer_destination"]), generation=intent["generation"],
        access={key: value for key, value in access.items() if key != "host_session_id"})
    outcome = {"document": document, "generation": intent["generation"], "host_session_id": intent["host_session_id"]}
    writes = [*service._prepare_participant_host_completion(intent["id"], intent["input_digest"], result=outcome),
        ("route_generation", intent["generation_id"], {"id": intent["generation_id"],
            "generation": intent["generation"], "host_session_id": intent["host_session_id"], "document": document})]
    return outcome, writes


def test_intent_commit_precedes_any_listener_or_mapping(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    original = service.store._write_records_locked

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("intent commit failed")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    operation = str(uuid4())
    with pytest.raises(OSError):
        reserve(service, operation)
    assert service.store.list("participant_host_intent") == []
    assert service.store.operation_result(operation, "a" * 64) is None
    assert service.network.created == 0 and mappings == []


@pytest.mark.parametrize("after_write", [False, True])
def test_lost_post_allocation_reply_reuses_exact_listener_mapping_and_access(hosts, monkeypatch, after_write):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    original = service.store.put

    def lost_reply(kind, identifier, value):
        if kind == "participant_host_intent" and value["state"] == "allocated":
            if after_write:
                original(kind, identifier, value)
            raise OSError("allocated reply lost")
        return original(kind, identifier, value)

    monkeypatch.setattr(service.store, "put", lost_reply)
    with pytest.raises(OSError):
        service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    monkeypatch.setattr(service.store, "put", original)
    access = service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    assert access["host_session_id"] == intent["host_session_id"]
    assert service.materialize_participant_host_intent(intent["id"], intent["input_digest"]) == access
    assert service.network.created == len(mappings) == 1


def test_lost_final_completion_reply_preserves_exact_result_and_cannot_change_it(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    access = service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    result, writes = completion(service, intent, access)
    original = service.store.put_and_delete

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("completion committed but reply lost")

    monkeypatch.setattr(service.store, "put_and_delete", lost_reply)
    with pytest.raises(OSError):
        service.store.put_and_delete(writes, [])
    monkeypatch.setattr(service.store, "put_and_delete", original)
    assert service.materialize_participant_host_intent(intent["id"], intent["input_digest"]) == access
    assert service.store.get("participant_host_completion", intent["id"])["result"] == result
    with pytest.raises(ValidationError, match="completion cannot change"):
        service._prepare_participant_host_completion(intent["id"], intent["input_digest"],
            result={**result, "document": "a different signed result"})
    assert service.network.created == len(mappings) == 1


def test_final_generation_document_and_receipt_rollback_without_duplicate_resource(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    access = service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    result, writes = completion(service, intent, access)
    original = service.store._write_records_locked

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("final commit failed")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    with pytest.raises(OSError):
        service.store.put_and_delete(writes, [])
    assert service.store.get("route_generation", intent["generation_id"]) is None
    assert service.store.get("participant_host_completion", intent["id"]) is None
    assert service.store.operation_result(intent["id"], intent["input_digest"]) == service._participant_intent_receipt(intent["id"])
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert service.materialize_participant_host_intent(intent["id"], intent["input_digest"]) == access
    service.store.put_and_delete(writes, [])
    assert service.store.get("participant_host_completion", intent["id"])["result"] == result
    assert service.materialize_participant_host_intent(intent["id"], intent["input_digest"]) == access
    assert service.network.created == len(mappings) == 1


def test_current_authority_is_checked_before_intent_replay(hosts):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    contact = service.store.get("contact", "peer")
    contact["trust"] = "blocked"
    service.store.put("contact", "peer", contact)
    with pytest.raises(ContactNotApproved):
        service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    assert service.network.listeners == {} and len(mappings) == len(removed) == 1


@pytest.mark.parametrize("cause", ["expiry", "generation"])
def test_expiry_or_stale_generation_cleans_only_its_exact_resource(hosts, cause):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    old, other = reserve(service), reserve(service)
    service.materialize_participant_host_intent(old["id"], old["input_digest"])
    service.materialize_participant_host_intent(other["id"], other["input_digest"])
    if cause == "expiry":
        persisted = service.store.get("participant_host_intent", old["id"])
        persisted["maximum_expires_at"] = int(time.time()) - 1
        service.store.put("participant_host_intent", old["id"], persisted)
    else:
        service.store.put("route_generation", old["generation_id"], {"generation": old["generation"]})
    with pytest.raises(ParticipantReservationUnavailable):
        service.materialize_participant_host_intent(old["id"], old["input_digest"])
    assert set(service.network.listeners) == {other["host_session_id"]}
    assert len(mappings) == 2 and len(removed) == 1


def test_replay_after_explicit_stop_does_not_remove_the_mapping_twice(hosts):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    service.stop_participant_host(intent["host_session_id"])
    with pytest.raises(ParticipantReservationUnavailable):
        service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    assert len(mappings) == len(removed) == 1


@pytest.mark.parametrize("held_state", ["retired", "allocating"])
def test_unknown_router_reply_never_reallocates_and_holds_capacity_past_document_expiry(hosts, monkeypatch, held_state):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    original = participant_service.create_port_mapping

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("router accepted but reply lost")

    monkeypatch.setattr(participant_service, "create_port_mapping", lost_reply)
    with pytest.raises(DirectConnectionUnavailable):
        service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    retired = service.store.get("participant_host_intent", intent["id"])
    assert retired["state"] == "retired"
    assert retired["uncertain_lease_until"] > intent["maximum_expires_at"]
    with pytest.raises(ParticipantReservationUnavailable):
        service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    assert len(mappings) == service.network.created == 1
    # An expired access document cannot release an unknown live router lease.
    retired["maximum_expires_at"] = int(time.time()) - 1
    if held_state == "allocating":
        # Simulate a crash after host deletion but before retiring the intent.
        retired["state"] = "allocating"
        retired.pop("uncertain_lease_until")
    service.store.put("participant_host_intent", intent["id"], retired)
    for _ in range(7):
        reserve(service)
    with pytest.raises(ValidationError, match="Too many participant host reservations"):
        reserve(service)


def test_restart_fences_old_receipts_and_never_allocates_again(hosts):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    access = service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    result, writes = completion(service, intent, access)
    service.store.put_and_delete(writes, [])
    service.close()
    reopened = open_host()
    with pytest.raises(ParticipantReservationUnavailable):
        reopened.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    assert len(mappings) == len(removed) == 1
    assert reopened.store.get("participant_host_completion", intent["id"])["result"] == result
    assert reopened.network.listeners == {}


def test_restore_does_not_adopt_a_previous_runtime_keyed_listener(hosts):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    service._participant_reservation_epoch = "another-runtime"
    service._restore_participant_interfaces()
    assert service.store.get("participant_host", intent["host_session_id"]) is None
    assert service.store.get("participant_host_intent", intent["id"])["state"] == "retired"
    assert service.network.listeners == {} and len(mappings) == len(removed) == 1


def test_restore_retries_retirement_after_host_deletion_commit_fault(hosts, monkeypatch):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
    original = service.store.delete

    def failed_delete(kind, identifier):
        if kind == "participant_host":
            raise OSError("host deletion commit failed")
        return original(kind, identifier)

    monkeypatch.setattr(service.store, "delete", failed_delete)
    with pytest.raises(OSError):
        service.retire_participant_host_intent(intent["id"], intent["input_digest"])
    assert service.store.get("participant_host_intent", intent["id"])["state"] == "retired"
    monkeypatch.setattr(service.store, "delete", original)
    service._restore_participant_interfaces()
    assert service.network.listeners == {} and len(mappings) == len(removed) == 1


def test_changed_payload_conflicts_before_new_allocation(hosts):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    with pytest.raises(ValidationError, match="already used with different input"):
        reserve(service, intent["id"], "b" * 64)
    assert mappings == [] and service.network.created == 0


@pytest.mark.parametrize("allocated", [False, True])
def test_route_global_reservation_blocks_another_command_before_its_effect(hosts, monkeypatch, allocated):
    open_host, mappings, removed, _, _ = hosts
    service = open_host()
    intent = reserve(service)
    if allocated:
        original = service.store.put

        def lost_reply(kind, identifier, value):
            original(kind, identifier, value)
            if kind == "participant_host_intent" and value["state"] == "allocated":
                raise OSError("allocation continuation reply lost")

        monkeypatch.setattr(service.store, "put", lost_reply)
        with pytest.raises(OSError):
            service.materialize_participant_host_intent(intent["id"], intent["input_digest"])
        monkeypatch.setattr(service.store, "put", original)
    with pytest.raises(ValidationError, match="already used with different input"):
        service.store.commit_operation(intent["id"], "b" * 64, {"action": "another-command"},
            [("another_effect", "new", {"performed": True})])
    assert service.store.get("another_effect", "new") is None
    assert service.store.get("participant_host_intent", intent["id"])["state"] == ("allocated" if allocated else "reserved")
    assert len(mappings) == int(allocated) and removed == []


def test_lost_global_reservation_reply_reuses_the_same_intent_without_allocation(hosts, monkeypatch):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    original = service.store.commit_operation
    operation = str(uuid4())

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("global reservation committed but reply lost")

    monkeypatch.setattr(service.store, "commit_operation", lost_reply)
    with pytest.raises(OSError):
        reserve(service, operation)
    stored = service.store.get("participant_host_intent", operation)
    monkeypatch.setattr(service.store, "commit_operation", original)
    assert reserve(service, operation) == stored
    assert mappings == [] and service.network.created == 0


def test_previously_consumed_global_key_cannot_create_an_intent(hosts):
    open_host, mappings, _, _, _ = hosts
    service = open_host()
    operation = str(uuid4())
    service.store.commit_operation(operation, "b" * 64, {"action": "another-command"}, [])
    with pytest.raises(ValidationError, match="already used with different input"):
        reserve(service, operation)
    assert service.store.list("participant_host_intent") == [] and mappings == []


def access_for(identity, port=4242):
    return create_access_document(identity, [{"host": "93.184.216.34", "port": port, "path": "manual"}],
        network_name="network_name_123456", passphrase="credential_1234567890123456", expires_at=int(time.time()) + 3600)


def test_replacement_is_prepare_only_and_shared_old_scopes_survive(hosts):
    open_host, _, _, lookups, peer = hosts
    service = open_host()
    old, new = access_for(peer), access_for(peer, 4243)
    old_record = {"id": old["id"], "access": old, "scopes": [{"kind": "contact", "id": "peer"},
        {"kind": "workspace", "id": "other-scope"}], "resolution_attempted": True,
        "resolved_endpoints": [], "candidate_results": []}
    service.store.put("participant_access", old["id"], old_record)
    record, writes, deletions = service._prepare_participant_scope_replacement(new, scope_kind="contact", scope_id="peer")
    assert lookups == [] and service.store.get("participant_access", old["id"]) == old_record
    assert deletions == []
    service.store.commit_operation(str(uuid4()), "d" * 64, {"id": record["id"]}, writes, deletions)
    assert service.store.get("participant_access", old["id"])["scopes"] == [{"kind": "workspace", "id": "other-scope"}]
    service.reconcile_prepared_participant_access()
    assert lookups == [{"host": "93.184.216.34", "port": 4243}]


def test_replacement_commit_failure_preserves_old_scopes_and_performs_no_dns(hosts, monkeypatch):
    open_host, _, _, lookups, peer = hosts
    service = open_host()
    old = access_for(peer)
    original_record = {"id": old["id"], "access": old, "scopes": [{"kind": "contact", "id": "peer"}]}
    service.store.put("participant_access", old["id"], original_record)
    record, writes, deletions = service._prepare_participant_scope_replacement(
        access_for(peer, 4243), scope_kind="contact", scope_id="peer")
    original = service.store._write_records_locked

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("replacement commit failed")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    operation = str(uuid4())
    with pytest.raises(OSError):
        service.store.commit_operation(operation, "f" * 64, {"id": record["id"]}, writes, deletions)
    assert service.store.get("participant_access", old["id"]) == original_record
    assert service.store.get("participant_access", record["id"]) is None
    assert service.store.operation_result(operation, "f" * 64) is None and lookups == []


def test_same_access_id_cannot_replace_changed_material_shared_by_other_scope(hosts):
    open_host, _, _, lookups, peer = hosts
    service = open_host()
    incoming = access_for(peer)
    different = access_for(peer, 4243)
    stored = {"id": incoming["id"], "access": different,
              "scopes": [{"kind": "contact", "id": "peer"}, {"kind": "workspace", "id": "other"}]}
    service.store.put("participant_access", incoming["id"], stored)
    with pytest.raises(ValidationError, match="identity changed"):
        service._prepare_participant_scope_replacement(incoming, scope_kind="contact", scope_id="peer")
    assert service.store.get("participant_access", incoming["id"]) == stored and lookups == []
    tampered = {**incoming, "passphrase": "changed_credential_123456789"}
    with pytest.raises(ValidationError):
        service._prepare_participant_scope_replacement(tampered, scope_kind="contact", scope_id="peer")


def test_post_commit_reconcile_does_not_resolve_a_revoked_scope(hosts):
    open_host, _, _, lookups, peer = hosts
    service = open_host()
    record, writes, deletions = service._prepare_participant_scope_replacement(access_for(peer), scope_kind="contact", scope_id="peer")
    service.store.commit_operation(str(uuid4()), "e" * 64, {"id": record["id"]}, writes, deletions)
    contact = service.store.get("contact", "peer")
    contact["trust"] = "blocked"
    service.store.put("contact", "peer", contact)
    service.reconcile_prepared_participant_access()
    assert service.store.get("participant_access", record["id"]) is None
    assert service.network.clients == [] and lookups == []
