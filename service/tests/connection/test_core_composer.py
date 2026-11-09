"""Composer wire contract vectors execute the production parser."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.requests import COMPONENT_OPERATIONS, parse_request
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from test_core_messages import host

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/core-api"
VECTORS = json.loads((CONTRACTS / "composer-vectors-v1.json").read_text())


def open_composer(service, *, caller="composer-ui", legacy=False, grants=None):
    grants = grants if grants is not None else [Grant(caller, frozenset({"observe", "read", "send", "approve"}), ("local",))]
    stream = bind_service_stream(service, lambda: grants[0], private_composer_legacy=legacy)

    def exchange(operation, key=None, **params):
        value = {"api_version": 1, "request_id": "composer:1", "operation": operation, "params": params}
        if key is not None:
            value["idempotency_key"] = key
        return json.loads(stream.exchange(json.dumps(value).encode() + b"\n"))

    capabilities = exchange("runtime.capabilities")
    profile = capabilities["result"]["profiles"][0]
    peer = exchange("profile.query", profile=profile)["result"]["peers"][0]
    return exchange, {"profile": profile, "peer": peer}


def query(client, scope, revision=None):
    return client("peer.composer_query", **scope, **({"send_revision": revision} if revision else {}))


def save(client, scope, text, state=None):
    state = state or query(client, scope)["result"]
    return client("peer.composer_update", state["update_key"], **scope,
                  expected_revision=state["revision"], text=text)


def send(client, scope, revision):
    return client("message.enqueue_draft", revision, profile=scope["profile"],
                  recipient=scope["peer"], draft_revision=revision)


@pytest.mark.parametrize("vector", VECTORS)
def test_composer_schema_and_production_parser_agree(vector):
    validator = Draft202012Validator(json.loads((CONTRACTS / "request-v1.schema.json").read_text()))
    value = vector["request"]
    assert validator.is_valid(value) is vector["valid"]
    if vector["valid"]:
        assert parse_request(value, COMPONENT_OPERATIONS) == (value["operation"], value["params"])
    else:
        with pytest.raises(ApiFailure):
            parse_request(value, COMPONENT_OPERATIONS)


def test_capabilities_contract_requires_complete_bound_composer_feature():
    from copy import deepcopy
    from mesh_chat.core_api.composer import COMPOSER_LIMITS
    from mesh_chat.core_api.session import CoreSession, Grant, Ports
    from test_core_api import Observations, request

    contract = Draft202012Validator(json.loads((CONTRACTS / "observation-result-v1.schema.json").read_text()))
    session = CoreSession(lambda: Grant("composer-test", frozenset({"observe"}), ("local",)),
        Observations(), handle_key=b"c" * 32, ports=Ports(composer=object()))
    reply = session.request(request("runtime.capabilities"))
    contract.validate(reply)
    assert reply["result"]["api_minor"] == 1
    for field in COMPOSER_LIMITS:
        broken = deepcopy(reply)
        del broken["result"]["limits"][field]
        assert not contract.is_valid(broken)
    broken = deepcopy(reply)
    broken["result"]["api_minor"] = 0
    assert not contract.is_valid(broken)


def test_pure_query_update_noop_and_atomic_send_have_strict_results(host):
    service = host()
    client, scope = open_composer(service)
    before = service.store._db.execute("SELECT * FROM records").fetchall()
    initial = query(client, scope)
    assert initial["ok"], initial
    assert initial["result"]["revision"] is None and initial["result"]["text"] == ""
    assert service.store._db.execute("SELECT * FROM records").fetchall() == before
    updated = save(client, scope, "Message from persistent composer")
    assert updated["ok"], updated
    first = updated["result"]["composer"]
    unchanged = save(client, scope, first["text"], first)
    assert unchanged["ok"], unchanged
    state = unchanged["result"]["composer"]
    assert state["revision"] == first["revision"] and state["update_key"] != first["update_key"]
    accepted = send(client, scope, state["revision"])
    assert accepted["ok"], accepted
    assert accepted["result"]["composer"]["text"] == ""
    assert accepted["result"]["composer"]["revision"] != state["revision"]
    assert accepted["result"]["composer"]["last_send"]["text"] == first["text"]
    for reply, filename in [(initial, "composer-result"), (updated, "composer-update-result"),
                            (accepted, "enqueue-draft-result")]:
        Draft202012Validator(json.loads((CONTRACTS / f"{filename}-v1.schema.json").read_text())).validate(reply)
    assert send(client, scope, state["revision"])["result"]["message"] == accepted["result"]["message"]
    assert len(service.store.list("message")) == 1


def test_lost_reply_reopen_new_draft_and_same_text_deliberate_second_send(host):
    service = host()
    client, scope = open_composer(service)
    saved = save(client, scope, "same text")["result"]["composer"]
    accepted = send(client, scope, saved["revision"])
    assert accepted["ok"], accepted
    service.close()
    reopened = host()
    client, scope = open_composer(reopened)
    restored = query(client, scope)["result"]
    assert restored["text"] == "" and restored["last_send"]["acceptance"]["message"] == accepted["result"]["message"]
    newer = save(client, scope, "same text")["result"]["composer"]
    replay = send(client, scope, saved["revision"])
    assert replay["result"]["draft_disposition"] == "superseded"
    assert replay["result"]["composer"]["text"] == "same text"
    assert newer["revision"] != saved["revision"]
    assert send(client, scope, newer["revision"])["ok"]
    assert len(reopened.store.list("message")) == 2


def test_update_replay_never_overwrites_current_state_and_binds_noop_key(host):
    client, scope = open_composer(host())
    initial = query(client, scope)["result"]
    first = save(client, scope, "first", initial)
    assert first["ok"], first
    second = save(client, scope, "second")
    replay = save(client, scope, "first", initial)
    assert replay["result"]["applied_revision"] == first["result"]["applied_revision"]
    assert replay["result"]["composer"] == second["result"]["composer"]
    changed = save(client, scope, "changed under same key", initial)
    assert changed["error"]["code"] == "idempotency_conflict", changed


def test_current_authority_and_caller_isolation_precede_replay(host):
    service = host()
    client, scope = open_composer(service)
    revision = save(client, scope, "private caller draft")["result"]["applied_revision"]
    accepted = send(client, scope, revision)
    assert accepted["ok"], accepted
    other, other_scope = open_composer(service, caller="another-caller")
    assert query(other, other_scope)["result"]["last_send"] is None
    assert query(other, other_scope, revision)["error"]["code"] == "forbidden"
    contact = service.store.get("contact", "internal-peer")
    service.store.put("contact", "internal-peer", {**contact, "trust": "blocked"})
    assert query(client, scope)["error"]["code"] == "forbidden"
    assert send(client, scope, revision)["error"]["code"] == "forbidden"
