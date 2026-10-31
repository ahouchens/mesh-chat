"""Contact-wide connection intent through the private facade."""

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


def open_client(service, permissions=("observe", "send", "read", "connect"), caller="alex"):
    grants = [Grant(caller, frozenset(permissions), ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    peers = session.request(request("profile.query", profile=profile))["result"]["peers"]
    return session, profile, peers[0], grants


def intent(session, profile, peer, operation):
    return session.request(request(operation, profile=profile, peer=peer))


def test_stop_is_convergent_and_reports_the_desired_state(host):
    service = host()
    session, profile, peer, _ = open_client(service)
    first = intent(session, profile, peer, "connection.stop")
    assert first["ok"], first
    assert first["result"]["desired"] == "stopped" and first["result"]["active"] is False
    assert intent(session, profile, peer, "connection.stop") == first
    schema = json.loads((CONTRACTS / "intent-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_start_reports_an_ineligible_peer_as_stopped(host):
    service = host()
    session, profile, peer, _ = open_client(service)
    result = intent(session, profile, peer, "connection.start")
    assert result["ok"], result
    assert result["result"] == {"profile": profile, "peer": peer,
                                "desired": "stopped", "active": False}


def test_start_and_stop_apply_when_both_consents_exist(host):
    service = host()
    service.reconnect_consent_set(CONTACT, True, True)
    stored = service.store.get("reconnect_profile", CONTACT)
    service.store.put("reconnect_profile", CONTACT, {**stored, "remote_auto_reconnect": True})
    session, profile, peer, _ = open_client(service)
    started = intent(session, profile, peer, "connection.start")
    assert started["ok"], started
    assert started["result"]["desired"] == "enabled" and started["result"]["active"] is True
    assert service.store.get("reconnect_profile", CONTACT)["active"] is True
    stopped = intent(session, profile, peer, "connection.stop")
    assert stopped["result"]["desired"] == "stopped" and stopped["result"]["active"] is False
    assert service.store.get("reconnect_profile", CONTACT)["active"] is False


def test_unapproved_or_unknown_peers_are_rejected(host):
    service = host()
    session, profile, peer, _ = open_client(service)
    record = service.store.get("contact", CONTACT)
    service.store.put("contact", CONTACT, {**record, "trust": "blocked"})
    assert intent(session, profile, peer, "connection.start")["error"]["code"] == "forbidden"
    assert intent(session, profile, "z" * 64, "connection.stop")["error"]["code"] == "forbidden"


def test_intent_requires_the_connect_grant_and_caller_scope(host):
    service = host()
    reader, profile, peer, _ = open_client(service, permissions=("observe", "read"))
    assert intent(reader, profile, peer, "connection.start")["error"]["code"] == "forbidden"
    alex, alex_profile, _, _ = open_client(service, permissions=("observe", "read", "connect"))
    _, _, blair_peer, _ = open_client(service, caller="blair")
    assert intent(alex, alex_profile, blair_peer, "connection.stop")["error"]["code"] == "forbidden"


def test_failed_stop_persistence_never_claims_stopped(host, monkeypatch):
    service = host()
    service.reconnect_consent_set(CONTACT, True, True)
    stored = service.store.get("reconnect_profile", CONTACT)
    service.store.put("reconnect_profile", CONTACT, {
        **stored, "remote_auto_reconnect": True, "active": True, "state": "waiting_for_peer"})
    session, profile, peer, _ = open_client(service)

    def failed(*_args, **_kwargs):
        raise StorageUnavailable("private storage failure")

    monkeypatch.setattr(service.store, "put_many", failed)
    reply = intent(session, profile, peer, "connection.stop")
    assert reply["error"]["code"] == "unavailable"
    monkeypatch.undo()
    assert service.store.get("reconnect_profile", CONTACT)["active"] is True


def test_capabilities_advertise_intent_only_with_the_port(host):
    service = host()
    session, _, _, _ = open_client(service)
    capabilities = session.request(request("runtime.capabilities"))
    assert {"connection.start", "connection.stop"} <= set(capabilities["result"]["operations"])
