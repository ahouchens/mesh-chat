"""Durable public enqueue at the real service/vault boundary, without sockets."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def request(operation, **params):
    return {"api_version": 1, "request_id": "request:1", "operation": operation, "params": params}


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    key = os.urandom(32)
    opened = []

    def open_service():
        store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
        service = MeshChatService(store, tmp_path, lambda _: None)
        opened.append(service)
        if store.get("profile", "local") is None:
            service.create_profile("Alex")
            store.put("contact", "internal-peer", {
                "id": "internal-peer", "display_name": "Blair", "trust": "approved",
                "destination_hash": "ab" * 16,
            })
        return service

    yield open_service
    for service in opened:
        service.close()


def client(service, caller="alex", permissions=frozenset({"observe", "send", "read"})):
    grants = [Grant(caller, permissions, ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    view = session.request(request("profile.query", profile=profile))
    assert view["ok"], view
    return session, grants, profile, view["result"]["peers"][0]


def enqueue(session, profile, recipient, *, key="enqueue-key-0001", text="Hello"):
    value = request("message.enqueue", profile=profile, recipient=recipient, kind="text", text=text)
    value["idempotency_key"] = key
    return session.request(value)


def test_lost_reply_and_restart_resolve_one_durable_message(host):
    service = host()
    session, _, profile, peer = client(service)
    first = enqueue(session, profile, peer)
    assert first["ok"], first
    message_id = service.store.list("message")[0]["id"]
    assert message_id in service._direct_retry_snapshot()
    assert enqueue(session, profile, peer) == first
    service.close()
    reopened = host()
    again, _, same_profile, same_peer = client(reopened)
    assert (profile, peer) == (same_profile, same_peer)
    assert enqueue(again, profile, peer) == first
    assert [item["id"] for item in reopened.store.list("message")] == [message_id]
    assert message_id in reopened._direct_retry_snapshot()
    queried = again.request(request("message.query", profile=profile, message=first["result"]["message"]))
    assert queried["result"]["text"] == "Hello"
    assert queried["result"]["state"] == "queued"
    assert message_id not in json.dumps([first, queried])


def test_same_key_different_payload_fails_without_a_second_message(host):
    service = host()
    session, _, profile, peer = client(service)
    assert enqueue(session, profile, peer)["ok"]
    assert enqueue(session, profile, peer, text="Different")["error"]["code"] == "idempotency_conflict"
    assert len(service.store.list("message")) == 1


def test_atomic_commit_failure_leaves_no_message_receipt_or_visibility_change(host):
    service = host()
    session, _, profile, peer = client(service)
    marker = service._conversation_marker_id("direct", "internal-peer")
    service.store.put("conversation_hidden", marker, {"hidden": True})
    database = service.store._db

    class FailCommit:
        def execute(self, statement, *args, **kwargs):
            if statement == "COMMIT":
                raise OSError("private storage failure")
            return database.execute(statement, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(database, name)

    service.store._db = FailCommit()
    try:
        result = enqueue(session, profile, peer)
        assert result["error"]["code"] == "unavailable"
    finally:
        service.store._db = database
    assert not service.store.list("message")
    assert not service.store.list("api_enqueue")
    assert not service.store.list("api_message")
    assert not service.store.list("api_enqueue_quota")
    assert not service._direct_retry_snapshot()
    assert service.store.get("conversation_hidden", marker) == {"hidden": True}
    assert enqueue(session, profile, peer)["ok"]
    assert service.store.get("conversation_hidden", marker) is None


def test_concurrent_sessions_share_one_atomic_enqueue(host):
    service = host()
    sessions = [client(service) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(lambda entry: enqueue(entry[0], entry[2], entry[3]), sessions))
    assert all(reply["ok"] for reply in replies), replies
    assert len({reply["result"]["message"] for reply in replies}) == 1
    assert len(service.store.list("message")) == 1


@pytest.mark.parametrize("revocation", ["send", "profile", "caller", "blocked", "identity_changed", "locked"])
def test_replay_rechecks_current_authority_before_returning_a_message(host, revocation):
    service = host()
    session, grants, profile, peer = client(service)
    assert enqueue(session, profile, peer)["ok"]
    if revocation == "send":
        grants[0] = replace(grants[0], permissions=frozenset({"observe", "read"}))
    elif revocation == "profile":
        grants[0] = replace(grants[0], profiles=())
    elif revocation == "caller":
        grants[0] = None
    elif revocation == "locked":
        service._identity = None
    else:
        contact = service.store.get("contact", "internal-peer")
        service.store.put("contact", "internal-peer", {**contact, "trust": revocation})
    reply = enqueue(session, profile, peer)
    assert reply["error"]["code"] in {"forbidden", "locked", "unauthenticated"}
    assert len(service.store.list("message")) == 1


def test_caller_scope_applies_to_peer_message_and_idempotency_handles(host):
    service = host()
    alex, _, profile, peer = client(service)
    first = enqueue(alex, profile, peer)
    blair, _, other_profile, other_peer = client(service, "blair")
    assert enqueue(blair, profile, peer)["error"]["code"] == "forbidden"
    assert enqueue(blair, other_profile, peer)["error"]["code"] == "forbidden"
    assert blair.request(request("message.query", profile=other_profile,
                                 message=first["result"]["message"]))["error"]["code"] == "forbidden"
    second = enqueue(blair, other_profile, other_peer)
    assert second["ok"] and first["result"]["message"] != second["result"]["message"]
    assert len(service.store.list("message")) == 2


@pytest.mark.parametrize("text", ["", " \n", "é" * 8193, "x" * 16385, "\ud800", None],
                         ids=["empty", "whitespace", "utf8_bytes", "ascii_bytes", "surrogate", "null"])
def test_text_validation_cannot_commit_invalid_or_oversized_messages(host, text):
    service = host()
    session, _, profile, peer = client(service)
    assert enqueue(session, profile, peer, text=text)["error"]["code"] == "invalid_request"
    assert not service.store.list("message")


def test_deleted_message_and_expired_key_never_recreate_history(host, monkeypatch):
    from mesh_chat.core_api import service_messages
    service = host()
    session, _, profile, peer = client(service)
    assert enqueue(session, profile, peer)["ok"]
    message = service.store.list("message")[0]
    service.store.delete("message", message["id"])
    assert enqueue(session, profile, peer)["error"]["code"] == "idempotency_expired"
    assert not service.store.list("message")
    assert enqueue(session, profile, peer, key="enqueue-key-0002")["ok"]
    monkeypatch.setattr(service_messages.time, "time", lambda: message["created_at"] + 8 * 86400)
    assert enqueue(session, profile, peer, key="enqueue-key-0002")["error"]["code"] == "idempotency_expired"
    assert len(service.store.list("message")) == 1


def test_capacity_keeps_existing_keys_replayable_without_eviction(host, monkeypatch):
    from mesh_chat.core_api import service_messages
    monkeypatch.setattr(service_messages, "MAX_CALLER_ENQUEUES", 1)
    service = host()
    session, _, profile, peer = client(service)
    first = enqueue(session, profile, peer)
    assert first["ok"]
    assert enqueue(session, profile, peer, key="enqueue-key-0002")["error"]["code"] == "resource_exhausted"
    assert enqueue(session, profile, peer) == first


def test_message_results_and_requests_match_contracts(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueued = enqueue(session, profile, peer)
    queried = session.request(request("message.query", profile=profile, message=enqueued["result"]["message"]))
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    schema = json.loads((root / "message-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    for reply in (enqueued, queried):
        Draft202012Validator(schema).validate(reply)
        assert "internal-peer" not in json.dumps(reply)
    cap = session.request(request("runtime.capabilities"))
    Draft202012Validator(json.loads((root / "observation-result-v1.schema.json").read_text())).validate(cap)
    assert cap["result"]["operations"] == json.loads((root / "operations-v1.json").read_text())["experimental_component_operations"]


def test_observe_does_not_grant_send_or_read(host):
    service = host()
    observer, _, profile, peer = client(service, permissions=frozenset({"observe"}))
    assert enqueue(observer, profile, peer)["error"]["code"] == "forbidden"
    sender, _, _, _ = client(service)
    message = enqueue(sender, profile, peer)["result"]["message"]
    assert observer.request(request("message.query", profile=profile, message=message))["error"]["code"] == "forbidden"


@pytest.mark.parametrize("callback", ["_changed", "_queue_direct_retry"])
def test_notification_failure_after_commit_does_not_report_enqueue_failure(host, monkeypatch, callback):
    service = host()
    session, _, profile, peer = client(service)
    def failed_notification(*_):
        raise OSError("client detached")
    original = getattr(service, callback)
    monkeypatch.setattr(service, callback, failed_notification)
    first = enqueue(session, profile, peer)
    assert first["ok"], first
    assert enqueue(session, profile, peer) == first
    assert len(service.store.list("message")) == 1
    monkeypatch.setattr(service, callback, original)
    assert enqueue(session, profile, peer) == first
    assert service.store.list("message")[0]["id"] in service._direct_retry_snapshot()


def test_global_capacity_counts_tombstones_but_does_not_block_replay(host, monkeypatch):
    from mesh_chat.core_api import service_messages
    monkeypatch.setattr(service_messages, "MAX_VAULT_ENQUEUES", 1)
    service = host()
    alex, _, profile, peer = client(service)
    first = enqueue(alex, profile, peer)
    blair, _, other_profile, other_peer = client(service, "blair")
    assert enqueue(blair, other_profile, other_peer)["error"]["code"] == "resource_exhausted"
    assert enqueue(alex, profile, peer) == first
    service.store.delete("message", service.store.list("message")[0]["id"])
    assert enqueue(blair, other_profile, other_peer)["error"]["code"] == "resource_exhausted"


def test_peer_capacity_is_bounded_before_decryption(host, monkeypatch):
    service = host()
    session, _, profile, _ = client(service)
    service.store.put_many(("contact", f"peer-{index}", {"id": f"peer-{index}"}) for index in range(300))
    opened = []
    original = service.store._open
    def track(kind, identifier, sealed):
        if kind == "contact":
            opened.append(identifier)
        return original(kind, identifier, sealed)
    monkeypatch.setattr(service.store, "_open", track)
    assert session.request(request("profile.query", profile=profile))["error"]["code"] == "resource_exhausted"
    assert len(opened) == 257


@pytest.mark.parametrize("change", [
    {"idempotency_key": "short"}, {"idempotency_key": "x" * 129},
    {"idempotency_key": "key-with-newline\n"}, {"idempotency_key": None},
    {"caller": "owner"}, {"operation": "receipt.confirm"},
], ids=["short_key", "long_key", "newline_key", "null_key", "caller_injection", "receipt_injection"])
def test_mutation_envelope_fails_closed_without_effects(host, change):
    service = host()
    session, _, profile, peer = client(service)
    raw = request("message.enqueue", profile=profile, recipient=peer, kind="text", text="Hello")
    raw["idempotency_key"] = "enqueue-key-0001"
    result = session.request({**raw, **change})
    assert not result["ok"]
    assert not service.store.list("message")


def test_enqueue_requires_negotiation_and_cannot_inject_private_fields(host):
    service = host()
    _, _, profile, peer = client(service)
    session = bind_service_session(service, lambda: Grant("alex", frozenset({"send", "observe"}), ("local",)))
    assert enqueue(session, profile, peer)["error"]["code"] == "negotiation_required"
    session.request(request("runtime.capabilities"))
    for field in ("state", "receipt", "message_id", "resource_id", "caller"):
        raw = request("message.enqueue", profile=profile, recipient=peer, kind="text", text="Hello")
        raw["idempotency_key"] = "enqueue-key-0001"
        raw["params"][field] = "injected"
        assert session.request(raw)["error"]["code"] == "invalid_request"
    assert not service.store.list("message")


@pytest.mark.parametrize("trust", ["awaiting_consent", "pending_request", "blocked", "identity_changed"])
def test_public_enqueue_requires_explicit_current_contact_approval(host, trust):
    service = host()
    session, _, profile, peer = client(service)
    contact = service.store.get("contact", "internal-peer")
    service.store.put("contact", "internal-peer", {**contact, "trust": trust})
    assert enqueue(session, profile, peer)["error"]["code"] == "forbidden"
    assert not service.store.list("message")


def test_unbound_profile_fails_before_any_write(host):
    service = host()
    session = bind_service_session(service, lambda: Grant("alex", frozenset({"observe", "send"}), ("other-profile",)))
    profile = session.request(request("runtime.capabilities"))["result"]["profiles"][0]
    assert enqueue(session, profile, "fake-recipient-0001")["error"]["code"] == "forbidden"
    assert not service.store.list("message")


def test_query_observes_delivery_state_without_turning_endpoint_evidence_into_a_receipt(host):
    service = host()
    session, _, profile, peer = client(service)
    accepted = enqueue(session, profile, peer)
    message = service.store.list("message")[0]
    for state in ("stored_for_delivery", "received_by_endpoint", "delivered"):
        service.store.put("message", message["id"], {**message, "state": state})
        observed = session.request(request("message.query", profile=profile, message=accepted["result"]["message"]))
        assert observed["result"]["state"] == state
        assert enqueue(session, profile, peer) == accepted


def test_deleted_message_query_returns_not_found_without_cached_plaintext(host):
    service = host()
    session, _, profile, peer = client(service)
    accepted = enqueue(session, profile, peer)
    message = service.store.list("message")[0]
    service.store.delete("message", message["id"])
    reply = session.request(request("message.query", profile=profile, message=accepted["result"]["message"]))
    assert reply["error"]["code"] == "not_found"
    assert "Hello" not in json.dumps(service.store.list("api_enqueue") + service.store.list("api_message"))


def test_same_caller_different_profile_cannot_query_a_message_handle(host):
    service = host()
    session, _, profile, peer = client(service)
    accepted = enqueue(session, profile, peer)
    other = bind_service_session(service, lambda: Grant("alex", frozenset({"observe", "read"}), ("other-profile",)))
    other_profile = other.request(request("runtime.capabilities"))["result"]["profiles"][0]
    result = other.request(request("message.query", profile=other_profile, message=accepted["result"]["message"]))
    assert result["error"]["code"] == "forbidden"


def test_facade_enqueue_uses_existing_signed_delivery_and_application_receipts(tmp_path):
    from test_two_peer_service_flow import _approved_pair
    hub, receiver, _, _, sender, _, _ = _approved_pair(tmp_path)
    try:
        # The fixture disables autonomous retries; drive the production outbox
        # once, then deliver the actual signed LXMF messages deterministically.
        sender._retry_thread.join(timeout=1)
        assert not sender._retry_thread.is_alive()
        sender._shutdown.clear()
        session, _, profile, peer = client(sender)
        accepted = enqueue(session, profile, peer, text="Durable public message")
        assert accepted["ok"], accepted
        message = accepted["result"]["message"]
        assert session.request(request("message.query", profile=profile, message=message))["result"]["state"] == "queued"
        sender._retry_once()
        hub.drain()
        assert session.request(request("message.query", profile=profile, message=message))["result"]["state"] == "delivered"
        assert receiver.snapshot()["messages"][0]["text"] == "Durable public message"
        assert enqueue(session, profile, peer, text="Durable public message") == accepted
        assert not hub.pending
    finally:
        receiver.close()
        sender.close()


@pytest.mark.parametrize("field,value", [("created_at", float("nan")), ("created_at", True),
                                        ("created_at", -1), ("state", "native_ready")])
def test_malformed_message_observations_fail_closed(host, field, value):
    service = host()
    session, _, profile, peer = client(service)
    accepted = enqueue(session, profile, peer)
    message = service.store.list("message")[0]
    service.store.put("message", message["id"], {**message, field: value})
    reply = session.request(request("message.query", profile=profile, message=accepted["result"]["message"]))
    assert reply["error"]["code"] == "internal"


def test_peer_query_resolves_recipient_selection_without_exposing_private_records(host):
    service = host()
    session, _, profile, peer = client(service)
    contact = service.store.get("contact", "internal-peer")
    service.store.put("contact", "internal-peer", {**contact, "mailbox_secret": "secret", "public_identity": "private-record"})
    reply = session.request(request("peer.query", profile=profile, peer=peer))
    assert reply["result"] == {"profile": profile, "peer": peer, "display_name": "Blair",
                               "destination": "ab" * 16, "trust": "approved"}
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    Draft202012Validator(json.loads((root / "observation-result-v1.schema.json").read_text())).validate(reply)
    other, _, other_profile, _ = client(service, "blair")
    assert other.request(request("peer.query", profile=other_profile, peer=peer))["error"]["code"] == "forbidden"
