"""Inbound signed-invitation pairing through the private facade."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import time

import pytest
import RNS

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant
from mesh_chat.invitations import create_invitation, verify_invitation
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


def test_profile_invitation_material_is_signed_and_verifiable(host):
    service = host()
    session, profile, operations = open_client(service)
    assert "peer.pairing_create" in operations
    reply = session.request(request("peer.pairing_create", profile=profile))
    assert reply["ok"], reply
    result = reply["result"]
    assert result["profile"] == profile
    assert result["link"].startswith("meshchat://invite/")
    assert result["expires_at"] > time.time()
    verified = verify_invitation(result["file"])
    assert verified.destination_hash.hex() == service.store.get("profile", "local")["destination_hash"]
    schema = json.loads((CONTRACTS / "invitation-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(reply)
    assert session.request(request("peer.pairing_create", profile=profile))["ok"]


def test_invitation_creation_requires_the_pair_grant_and_caller_scope(host):
    service = host()
    reader, profile, _ = open_client(service, permissions=("observe", "read"))
    assert reader.request(request("peer.pairing_create", profile=profile))["error"]["code"] == "forbidden"
    alex, alex_profile, _ = open_client(service)
    _, blair_profile, _ = open_client(service, caller="blair")
    assert alex.request(request("peer.pairing_create", profile=blair_profile))["error"]["code"] == "forbidden"


def test_capabilities_advertise_pairing_only_with_the_port(host):
    service = host()
    _, _, operations = open_client(service)
    assert "peer.pairing_accept" in operations


def request_frame(profile, peer):
    return {"api_version": 1, "request_id": "request:1", "operation": "peer.pairing_request",
            "params": {"profile": profile, "peer": peer}}


def contact_requests(service):
    return [message for message in service.store.list("message")
            if message["kind"] == "contact_request" and message["direction"] == "outbound"]


def test_the_signed_contact_request_is_queued_once_and_reused(host):
    service = host()
    session, profile, _ = open_client(service)
    accepted = accept(session, profile, invitation_document())
    peer = accepted["result"]["peer"]
    before = contact_requests(service)
    assert len(before) == 1
    first = session.request(request_frame(profile, peer))
    assert first["ok"], first
    assert first["result"]["profile"] == profile and first["result"]["peer"] == peer
    assert first["result"]["state"] == "requested"
    assert verify_invitation(first["result"]["document"]).destination_hash
    assert session.request(request_frame(profile, peer)) == first
    assert len(contact_requests(service)) == len(before)
    schema = json.loads((CONTRACTS / "pairing-request-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_pairing_request_refuses_other_states_permissions_and_scope(host):
    service = host()
    session, profile, _ = open_client(service)
    peer = session.request(request("profile.query", profile=profile))["result"]["peers"][0]
    assert session.request(request_frame(profile, peer))["error"]["code"] == "invalid_request"
    reader, reader_profile, _ = open_client(service, permissions=("observe", "read"))
    assert reader.request(request_frame(reader_profile, peer))["error"]["code"] == "forbidden"
    alex, alex_profile, _ = open_client(service, caller="alex")
    _, blair_profile, _ = open_client(service, caller="blair")
    assert alex.request(request_frame(blair_profile, peer))["error"]["code"] == "forbidden"
