"""Explicit peer approval and revocation through the private facade."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant
from mesh_chat.errors import StorageUnavailable
from test_core_messages import host, request


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
CONTACT = "internal-peer"


def open_client(service, permissions=("observe", "read", "approve"), caller="alex"):
    grants = [Grant(caller, frozenset(permissions), ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    peer = session.request(request("profile.query", profile=profile))["result"]["peers"][0]
    return session, profile, peer


def relationship(session, profile, peer, operation):
    return session.request(request(operation, profile=profile, peer=peer))


def set_trust(service, trust):
    record = service.store.get("contact", CONTACT)
    service.store.put("contact", CONTACT, {**record, "trust": trust})


def test_pending_request_is_approved_once_and_converges(host):
    service = host()
    set_trust(service, "pending_request")
    session, profile, peer = open_client(service)
    first = relationship(session, profile, peer, "peer.approve")
    assert first["ok"], first
    assert first["result"] == {"profile": profile, "peer": peer, "trust": "approved"}
    assert service.store.get("contact", CONTACT)["trust"] == "approved"
    assert [message["kind"] for message in service.store.list("message")] == ["contact_accept"]
    assert relationship(session, profile, peer, "peer.approve") == first
    schema = json.loads((CONTRACTS / "relationship-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_an_already_verified_peer_is_reported_without_change(host):
    service = host()
    set_trust(service, "verified")
    session, profile, peer = open_client(service)
    reply = relationship(session, profile, peer, "peer.approve")
    assert reply["result"]["trust"] == "verified"
    assert service.store.get("contact", CONTACT)["trust"] == "verified"
    assert service.store.list("message") == []


def test_approval_refuses_states_it_cannot_approve(host):
    service = host()
    session, profile, peer = open_client(service)
    for trust in ("blocked", "awaiting_consent", "identity_changed"):
        set_trust(service, trust)
        assert relationship(session, profile, peer, "peer.approve")["error"]["code"] == "forbidden"
        assert service.store.get("contact", CONTACT)["trust"] == trust


def test_revocation_blocks_and_converges(host):
    service = host()
    session, profile, peer = open_client(service)
    first = relationship(session, profile, peer, "peer.revoke")
    assert first["result"] == {"profile": profile, "peer": peer, "trust": "blocked"}
    assert service.store.get("contact", CONTACT)["trust"] == "blocked"
    assert relationship(session, profile, peer, "peer.revoke") == first


def test_relationship_requires_the_approve_grant_and_caller_scope(host):
    service = host()
    reader, profile, peer = open_client(service, permissions=("observe", "read"))
    assert relationship(reader, profile, peer, "peer.approve")["error"]["code"] == "forbidden"
    alex, alex_profile, _ = open_client(service)
    _, _, blair_peer = open_client(service, caller="blair")
    assert relationship(alex, alex_profile, blair_peer, "peer.revoke")["error"]["code"] == "forbidden"


def test_failed_revocation_never_claims_blocked(host, monkeypatch):
    service = host()
    session, profile, peer = open_client(service)

    def failed(_contact_id):
        raise StorageUnavailable("private storage failure")

    monkeypatch.setattr(service, "block_contact", failed)
    reply = relationship(session, profile, peer, "peer.revoke")
    assert reply["error"]["code"] == "unavailable"
    monkeypatch.undo()
    assert service.store.get("contact", CONTACT)["trust"] == "approved"


def test_capabilities_advertise_relationships_only_with_the_port(host):
    service = host()
    session, _, _ = open_client(service)
    operations = session.request(request("runtime.capabilities"))["result"]["operations"]
    assert {"peer.approve", "peer.revoke"} <= set(operations)
