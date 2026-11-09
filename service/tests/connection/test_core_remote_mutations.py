"""Serialized Core remote mutations execute C's actual durable domain hooks."""

from dataclasses import replace
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from test_remote_profile_idempotency import hosts, ENDPOINTS, NODE


def client(service, grants=None):
    grants = grants or [Grant("remote-ui", frozenset({"observe", "read", "send", "approve"}), ("local",))]
    session = bind_service_stream(service, lambda: grants[0])
    cap = decode_frame(session.exchange(encode_frame({"api_version": 1, "request_id": "remote:1",
        "operation": "runtime.capabilities", "params": {}})))
    return session, cap["result"]["profiles"][0]


def mutate(opened, action, key, **params):
    session, profile = opened
    return decode_frame(session.exchange(encode_frame({"api_version": 1, "request_id": "remote:1",
        "operation": "remote_profile.mutate", "idempotency_key": key,
        "params": {"profile": profile, "action": action, **params}})))


def create(opened, label="Relay"):
    return mutate(opened, "create", "core-remote-create-key", label=label,
                   endpoints=ENDPOINTS, propagation_node=NODE, allow_private=False)


def test_all_remote_actions_reach_real_keyed_domain_without_repeating_effects(hosts):
    open_host, lookups = hosts
    service = open_host()
    opened = client(service)
    created = create(opened)
    assert created["ok"], created
    identifier = created["result"]["remote_profile"]["id"]
    count = len(lookups)
    assert create(opened)["result"]["remote_profile"]["id"] == identifier
    assert len(lookups) == count and len(service.store.list("remote_profile")) == 1
    assert create(opened, "Changed")["error"]["code"] == "idempotency_conflict"
    for action in ("test", "retry", "approve_propagation", "remove_propagation", "remove"):
        reply = mutate(opened, action, f"core-remote-{action}-key", remote_profile_id=identifier)
        assert reply["ok"], (action, reply)
        count = len(lookups)
        again = mutate(opened, action, f"core-remote-{action}-key", remote_profile_id=identifier)
        assert again["ok"], (action, again)
        assert len(lookups) == count
    assert service.store.list("remote_profile") == []
    assert create(opened)["ok"] is False
    assert service.settings.approved_propagation_nodes == []


def test_remote_create_lost_reply_reopen_and_revoked_consent_do_not_restore_grants(hosts):
    open_host, lookups = hosts
    service = open_host()
    opened = client(service)
    created = create(opened)
    assert created["ok"], created
    identifier = created["result"]["remote_profile"]["id"]
    approved = mutate(opened, "approve_propagation", "core-propagation-approve", remote_profile_id=identifier)
    assert approved["ok"], approved
    assert mutate(opened, "remove_propagation", "core-propagation-remove0", remote_profile_id=identifier)["ok"]
    assert mutate(opened, "approve_propagation", "core-propagation-approve", remote_profile_id=identifier)["ok"] is False
    assert service.settings.approved_propagation_nodes == []
    service.close()
    reopened = open_host()
    count = len(lookups)
    again = create(client(reopened))
    assert again["ok"] and again["result"]["remote_profile"]["id"] == identifier, again
    assert len(lookups) == count


def test_remote_consent_requires_approve_and_rechecks_it_before_replay(hosts):
    open_host, lookups = hosts
    service = open_host()
    grants = [Grant("remote-ui", frozenset({"observe", "read", "send"}), ("local",))]
    opened = client(service, grants)
    assert create(opened)["error"]["code"] == "forbidden"
    assert service.store.list("remote_profile") == [] and lookups == []
    grants[0] = replace(grants[0], permissions=grants[0].permissions | {"approve"})
    created = create(opened)
    assert created["ok"], created
    identifier = created["result"]["remote_profile"]["id"]
    grants[0] = replace(grants[0], permissions=grants[0].permissions - {"approve"})
    count = len(lookups)
    assert create(opened)["error"]["code"] == "forbidden"
    assert mutate(opened, "remove", "consumer-remove-key", remote_profile_id=identifier)["error"]["code"] == "forbidden"
    assert len(lookups) == count
    assert mutate(opened, "test", "ordinary-retry-key", remote_profile_id=identifier)["ok"]
