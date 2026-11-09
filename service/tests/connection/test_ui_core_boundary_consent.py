"""Explicit network/disclosure consent requires current host approval authority."""

import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.host import (CONSUMER_PERMISSIONS, OWNER_PERMISSIONS,
                                     bind_host_stream, host_grant)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_workspace_service import _deliver_all, _flush, _joined_pair

ENDPOINTS = [{"host": "93.184.216.34", "port": 4242}]
NODE = "ad" * 16
ACTIONS = (
    ("remote_profile.mutate", "create"),
    ("remote_profile.mutate", "approve_propagation"),
    ("remote_profile.mutate", "remove"),
    ("remote_profile.mutate", "remove_propagation"),
    ("workspace.access_recommendation", "apply"),
    ("workspace.access_recommendation", "apply_by_id"),
    ("workspace.connection", "reconnect_consent"),
)


def exchange(session, operation, params=None, key=None):
    request = {"api_version": 1, "request_id": "consent-boundary:1",
               "operation": operation, "params": params or {}}
    if key is not None:
        request["idempotency_key"] = key
    return json.loads(session.exchange(json.dumps(request).encode("utf-8") + b"\n"))


@pytest.fixture
def consent_host(tmp_path, request):
    operation, action = request.param
    owner, network, owner_profile, member, member_network, member_profile, workspace, *_ = _joined_pair(
        tmp_path, base=192_000)
    owner._shutdown.clear()
    member._shutdown.clear()
    # Exercise real consent/storage/queue logic with transport unavailable.
    # The workspace recording carrier intentionally has no remote-profile API.
    member.network = None
    sessions = []
    try:
        details = {}
        if operation == "remote_profile.mutate":
            remote = member.create_manual_remote_profile("Existing consent", ENDPOINTS, NODE)
            details["remote_profile_id"] = remote["id"]
            if action == "remove_propagation":
                member.approve_remote_propagation(remote["id"])
            if action == "create":
                details = {"label": "New approved route", "endpoints": ENDPOINTS,
                           "propagation_node": NODE, "allow_private": False}
        elif operation == "workspace.access_recommendation":
            remote = owner.create_manual_remote_profile("Signed workspace route", ENDPOINTS)
            signed = owner.create_workspace_access_recommendation(workspace["id"], remote["id"], 7)
            owner.send_workspace_access_recommendation(workspace["id"], signed["text"], str(uuid4()))
            _deliver_all(member, _flush(owner, network),
                         source_profile=owner_profile, recipient_profile=member_profile)
            received = member.list_workspace_access_recommendations(workspace["id"])["recommendations"]
            assert len(received) == 1
            details = {"consent": True, **({"recommendation": signed["text"]} if action == "apply"
                       else {"recommendation_id": received[0]["id"]})}
        else:
            details = {"auto_reconnect": True, "allow_direct_ip_disclosure": True,
                       "relay_consent_scope": "workspace"}

        consumer = bind_host_stream(member, caller="boundary-consumer", scope="consumer",
                                    permissions=CONSUMER_PERMISSIONS)
        current = [host_grant("boundary-owner", OWNER_PERMISSIONS, scope="owner")]
        privileged = bind_service_stream(member, lambda: current[0])
        sessions.extend((consumer, privileged))

        def client(session):
            capability = exchange(session, "runtime.capabilities")
            assert capability["ok"], capability
            profile = capability["result"]["profiles"][0]
            listed = exchange(session, "workspace.query", {"profile": profile})
            assert listed["ok"], listed
            handle = listed["result"]["workspaces"][0]["workspace"]
            scope = {"profile": profile}
            if operation != "remote_profile.mutate":
                scope["workspace"] = handle

            def mutate(key):
                return exchange(session, operation, {**scope, "action": action, **details}, key)

            # Prove this is a usable, negotiated grant with a genuine scoped target.
            if operation == "remote_profile.mutate":
                control = exchange(session, "remote_profile.query", {"profile": profile})
            elif operation == "workspace.connection":
                control = exchange(session, operation, {**scope, "action": "reconnect_status"})
            else:
                control = exchange(session, operation, {**scope, "action": "list"})
            assert control["ok"], control
            return mutate

        consumer_mutate, owner_mutate = client(consumer), client(privileged)

        def state():
            return (member.store._db.total_changes, member.settings.to_dict(), len(member_network.sent),
                    {kind: member.store.list(kind) for kind in
                     ("remote_profile", "reconnect_profile", "workspace_access_recommendation", "workspace_delivery")})

        def check_effect(reply):
            assert reply["ok"], reply
            if operation == "remote_profile.mutate":
                if action == "create":
                    assert len(member.store.list("remote_profile")) == 2
                elif action == "remove":
                    assert member.store.get("remote_profile", remote["id"]) is None
                else:
                    record = member.store.get("remote_profile", remote["id"])
                    approved = action == "approve_propagation"
                    assert (record["propagation_approved_at"] is not None) == approved
                    assert (NODE in member.settings.approved_propagation_nodes) == approved
            elif operation == "workspace.access_recommendation":
                record = member.store.get("remote_profile", remote["id"])
                assert {"kind": "workspace", "id": workspace["id"]} in record["scopes"]
                if action == "apply_by_id":
                    assert member.store.get("workspace_access_recommendation", received[0]["id"])["state"] == "applied"
            else:
                profiles = member.store.list("reconnect_profile")
                assert profiles and all(item["auto_reconnect"] and item["allow_direct_ip_disclosure"] for item in profiles)

        def revoke_approve():
            current[0] = host_grant("boundary-owner", CONSUMER_PERMISSIONS, scope="owner")

        yield consumer_mutate, owner_mutate, check_effect, revoke_approve, state
    finally:
        for session in sessions:
            session.close()
        owner.close()
        member.close()


@pytest.mark.parametrize("consent_host", ACTIONS, indirect=True, ids=[action for _, action in ACTIONS])
def test_valid_consumer_cannot_administer_explicit_consent(consent_host):
    consumer, _, _, _, state = consent_host
    before = state()
    denied = consumer("consumer-consent-denied-0001")
    assert denied["ok"] is False, denied
    assert denied["error"]["code"] == "forbidden", denied
    assert state() == before


@pytest.mark.parametrize("consent_host", ACTIONS, indirect=True, ids=[action for _, action in ACTIONS])
def test_owner_consent_success_cannot_replay_after_approve_grant_revocation(consent_host):
    _, owner, check_effect, revoke, state = consent_host
    key = "owner-consent-replay-key-0001"
    check_effect(owner(key))
    revoke()
    before = state()
    denied = owner(key)
    assert denied["ok"] is False, denied
    assert denied["error"]["code"] == "forbidden", denied
    assert state() == before
