"""Inbound signed-invitation pairing through the private facade."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
import RNS

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant
from mesh_chat.invitations import create_invitation
from test_core_messages import host, request


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"


def open_client(service, permissions=("observe", "read", "pair"), caller="alex"):
    grants = [Grant(caller, frozenset(permissions), ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    return session, profile, capabilities["result"]["operations"]


def invitation_document(name="Blair"):
    return create_invitation(RNS.Identity(), name)["file"]


def accept(session, profile, document):
    return session.request(request("peer.pairing_accept", profile=profile, document=document))


def test_signed_invitation_is_accepted_into_a_pending_contact(host):
    service = host()
    session, profile, operations = open_client(service)
    assert "peer.pairing_accept" in operations
    document = invitation_document()
    first = accept(session, profile, document)
    assert first["ok"], first
    assert first["result"]["trust"] == "awaiting_consent"
    peers = session.request(request("profile.query", profile=profile))["result"]["peers"]
    assert first["result"]["peer"] in peers
    assert len(peers) == 2
    assert accept(session, profile, document) == first
    schema = json.loads((CONTRACTS / "pairing-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_invalid_or_self_invitation_is_rejected(host):
    service = host()
    session, profile, _ = open_client(service)
    assert accept(session, profile, "not-a-signed-document")["error"]["code"] == "invalid_request"
    own = service.invitation()["file"]
    assert accept(session, profile, own)["error"]["code"] == "invalid_request"
    assert accept(session, profile, "x" * 1048577)["error"]["code"] == "invalid_request"


def test_pairing_requires_the_pair_grant_and_caller_scope(host):
    service = host()
    reader, profile, _ = open_client(service, permissions=("observe", "read"))
    assert accept(reader, profile, invitation_document())["error"]["code"] == "forbidden"
    alex, alex_profile, _ = open_client(service)
    _, blair_profile, _ = open_client(service, caller="blair")
    assert accept(alex, blair_profile, invitation_document())["error"]["code"] == "forbidden"


def test_capabilities_advertise_pairing_only_with_the_port(host):
    service = host()
    _, _, operations = open_client(service)
    assert "peer.pairing_accept" in operations
