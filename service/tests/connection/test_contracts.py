from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.connection.projection import snapshot
from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.requests import (COMPONENT_OPERATIONS, KEYED_OPERATIONS,
                                         KEYED_ACTIONS, OPTIONAL_KEY_OPERATIONS, parse_request)
from tools.connection_harness.simulation import Simulation


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


@lru_cache
def validator(relative):
    schema = json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_executing_policy_observations_follow_the_versioned_contract():
    contract = validator("connection/snapshot-v1.schema.json")
    sim = Simulation()
    sim.advance(0)
    sim.complete(adopt=True)
    for _ in range(15):
        contract.validate(snapshot(sim.owner.snapshot(sim.key), sim.now))
        sim.complete()
        sim.advance(1)
    sim.network(False)
    contract.validate(snapshot(sim.owner.snapshot(sim.key), sim.now))
    sim.close()
    contract.validate(snapshot(sim.owner.snapshot(sim.key), sim.now))


@pytest.mark.parametrize("field,value", [("sdp", "secret"), ("resource_id", "native-private"),
    ("mailbox_secret", "secret"), ("delivered", True), ("runtime_epoch", "x" * 65),
    ("sequence", -1), ("retry_in", -1), ("messaging_ready", True)])
def test_observations_reject_private_leaks_and_false_readiness(field, value):
    sim = Simulation()
    observation = snapshot(sim.owner.snapshot(sim.key), sim.now)
    observation[field] = value
    assert not validator("connection/snapshot-v1.schema.json").is_valid(observation)


def enqueue_request():
    return {"api_version": 1, "request_id": "client:request-1", "operation": "message.enqueue",
            "idempotency_key": "mutation-key-0001",
            "params": {"profile": "authorizedProfile1", "recipient": "authorizedPeer0001",
                       "kind": "text", "text": "Hello"}}


def test_public_request_contract_has_explicit_mutation_identity():
    contract = validator("core-api/request-v1.schema.json")
    request = enqueue_request()
    contract.validate(request)
    del request["idempotency_key"]
    assert not contract.is_valid(request)
    request = {"api_version": 1, "request_id": "query:1", "operation": "runtime.capabilities", "params": {}}
    contract.validate(request)
    request["idempotency_key"] = "query-cache-key-1"
    assert not contract.is_valid(request)


def request_vectors():
    handle = "callerScopedHandle1"
    examples = {
        "runtime.capabilities": {}, "runtime.stop": {}, "application.snapshot": {},
        "native.command": {"command": "workspace_snapshot", "payload": {}},
        "profile.create": {"display_name": "Alex"},
        "bootstrap.preview": {"kind": "personal", "document": "signed-invitation"},
        "workspace.create": {"name": "Lake", "description": ""}, "profile.select": {},
        "profile.unlock": {"credential_handle": handle}, "profile.lock": {}, "profile.query": {},
        "peer.pairing_create": {},
        "workspace.invitation_preview": {"document": "workspace-invitation"},
        "workspace.join": {"document": "workspace-invitation"},
        "workspace.query": {},
        "workspace.join_requests": {"workspace": handle},
        "workspace.join_approve": {"workspace": handle, "request": handle},
        "workspace.members": {"workspace": handle},
        "workspace.join_decline": {"workspace": handle, "request": handle},
        "workspace.member_role": {"workspace": handle, "member": handle, "role": "admin"},
        "workspace.invitation_create": {"workspace": handle},
        "workspace.channels": {"workspace": handle},
        "workspace.channel_create": {"workspace": handle, "name": "Core Chat"},
        "workspace.channel_members": {"workspace": handle, "channel": handle},
        "workspace.channel_members_update": {"workspace": handle, "channel": handle,
                                             "members": [handle]},
        "workspace.channel_update": {"workspace": handle, "channel": handle,
                                     "name": "Renamed", "topic": ""},
        "workspace.channel_archive": {"workspace": handle, "channel": handle},
        "workspace.device_link_create": {"workspace": handle},
        "workspace.device_link_preview": {"document": "device-link"},
        "workspace.device_link_submit": {"document": "device-link"},
        "workspace.device_links": {"workspace": handle},
        "workspace.device_link_approve": {"workspace": handle, "request": handle},
        "workspace.device_link_decline": {"workspace": handle, "request": handle},
        "workspace.channel_transfer_offer": {"workspace": handle, "channel": handle,
                                            "member": handle},
        "workspace.channel_transfer_accept": {"workspace": handle, "channel": handle},
        "workspace.devices": {"workspace": handle},
        "workspace.device_remove": {"workspace": handle, "device": handle},
        "workspace.close": {"workspace": handle},
        "workspace.leave": {"workspace": handle},
        "workspace.remove_data": {"workspace": handle, "confirmation": "DELETE"},
        "workspace.authority_loss_report": {"workspace": handle},
        "workspace.authority_accept": {"workspace": handle, "transition": handle},
        "workspace.admin_request_submit": {"workspace": handle, "request_kind": "invitation"},
        "workspace.display_name_request": {"workspace": handle, "display_name": "Alex"},
        "workspace.read_hint_sync": {"workspace": handle, "enabled": True},
        "workspace.invitation_revoke": {"workspace": handle, "invitation": handle},
        "workspace.admission_grant_list": {"workspace": handle},
        "workspace.admission_grant_create": {"workspace": handle, "admin_member": handle,
          "admin_device": handle, "max_admissions": 5, "lifetime_days": 7,
          "v2_ready": True},
        "workspace.admission_grant_accept": {"workspace": handle, "grant": handle},
        "workspace.admission_grant_end": {"workspace": handle, "grant": handle},
        "workspace.snapshot": {},
        "workspace.channel_recover": {"workspace": handle, "channel": handle},
        "workspace.channel_state": {"workspace": handle, "channel": handle,
          "action": "subscribe", "subscribed": True},
        "workspace.member_remove": {"workspace": handle, "member": handle},
        "group.draft_set": {"group": handle, "text": "draft"},
        "workspace.draft_set": {"workspace": handle, "conversation": "c1",
          "text": "draft"},
        "remote_profile.mutate": {"action": "remove", "remote_profile_id": "r1"},
        "workspace.display_name_decide": {"workspace": handle, "request": "r1",
          "approve": True},
        "workspace.direct_open": {"workspace": handle, "member": handle},
        "route.update": {"action": "create", "scope_kind": "contact",
          "scope_id": "c1"},
        "peer.update": {"peer": handle, "action": "verify"},
        "conversation.mutate": {"action": "delete", "kind": "direct",
          "target_id": "c1"},
        "peer.decide": {"peer": handle, "accept": False},
        "link.preview": {"provider": "youtube", "identifier": "abc"},
        "contact.invitation": {"action": "receive", "document": "doc",
          "peer": "p1"},
        "recovery.transfer": {"action": "export", "identifier": "r1"},
        "connection.support": {"action": "diagnostics"},
        "remote_profile.query": {},
        "connection.document": {"action": "preview_direct", "document": "doc"},
        "peer.pairing_preview": {"document": "doc"},
        "workspace.join_prompt": {"prompt": "p1"},
        "runtime.query": {"action": "background"},
        "runtime.mutate": {"action": "notification_previews",
          "hidden": True},
        "workspace.access_recommendation": {"workspace": handle, "action": "list"},
        "workspace.connection": {"workspace": handle, "action": "reconnect_status"},
        "workspace.history": {"workspace": handle, "action": "prune",
          "max_events": 100},
        "workspace.timeline_query": {"workspace": handle, "view": "threads",
          "limit": 50},
        "workspace.timeline_mutation": {"workspace": handle, "action": "mentions_read",
          "high_water": "m" * 20},
        "workspace.authority_offer": {"workspace": handle,
          "transition_kind": "ownership_transfer",
          "successor_member": handle, "successor_device": handle,
          "outgoing_owner_role": "admin"},
        "workspace.authority_finalize": {"workspace": handle, "transition": handle},
        "workspace.device_removal_request": {"workspace": handle, "device": handle},
        "workspace.device_removal_approve": {"workspace": handle, "request": handle},
        "workspace.device_removal_decline": {"workspace": handle, "request": handle},
        "workspace.policy_update": {"workspace": handle,
                                  "channel_creation": "owner_and_admins",
                                  "posting": "owner_and_admins",
                                  "invitation_requests": "owner_only"},
        "workspace.metadata_update": {"workspace": handle, "name": "Team",
                                        "description": "A team"},
        "workspace.retention_update": {"workspace": handle, "retention_days": 30},
        "workspace.admin_request_approve": {"workspace": handle, "request": handle},
        "workspace.admin_request_decline": {"workspace": handle, "request": handle},
        "workspace.admin_request_cancel": {"workspace": handle, "request": handle},
        "workspace.admin_request_dismiss": {"workspace": handle, "request": handle},
        "workspace.channels": {"workspace": handle},
        "workspace.channel_create": {"workspace": handle, "name": "Core Chat"},
        "peer.pairing_accept": {"document": "signed-pairing-document"},
        "peer.pairing_request": {"peer": handle},
        "peer.query": {"peer": handle},
        "peer.approve": {"peer": handle},
        "peer.revoke": {"peer": handle},
        "peer.unblock": {"peer": handle},
        "peer.delete": {"peer": handle},
        "peer.draft_get": {"peer": handle},
        "peer.composer_query": {"peer": handle},
        "peer.composer_update": {"peer": handle, "expected_revision": None, "text": "draft"},
        "message.enqueue_draft": {"recipient": handle, "draft_revision": "a" * 64},
        "peer.draft_set": {"peer": handle, "text": "draft"},
        "call.settings_query": {},
        "call.ice_servers": {},
        "call.media_query": {"call": handle},
        "call.control": {"action": "end", "call_id": "c" * 20, "reason": "completed"},
        "call.settings_update": {"settings": {"relay_only": True}},
        "settings.query": {},
        "settings.update": {"settings": {}},
        "message.reaction_set": {"message": handle, "emoji": "👍", "active": True},
        "group.query": {},
        "group.create": {"title": "Team", "posting_policy": "members",
                          "members": [handle]},
        "group.message_enqueue": {"group": handle, "text": "Hello"},
        "group.leave": {"group": handle},
        "group.close": {"group": handle},
        "group.member_remove": {"group": handle, "member": handle},
        "group.invitation_accept": {"invitation": handle},
        "group.invitation_decline": {"invitation": handle},
        "group.invitation_retry": {"group": handle, "member": handle},
        "group.create": {"title": "Team", "posting_policy": "members",
                          "members": [handle]},

        "connection.start": {"connection": handle}, "connection.stop": {"connection": handle},
        "connection.retry": {"connection": handle}, "connection.snapshot": {"connection": handle},
        "message.enqueue": {"recipient": handle, "kind": "text", "text": "Hello"},
        "message.query": {"message": handle}, "message.list": {"cursor": None, "limit": 128},
        "message.received": {"cursor": None, "limit": 128},
        "connection.start": {"peer": handle}, "connection.stop": {"peer": handle},
        "events.poll": {"cursor": None, "limit": 128}, "events.ack": {"cursor": handle},
        "diagnostics.query": {"limit": 256},
    }
    manifest = json.loads((CONTRACTS / "core-api/operations-v1.json").read_text())
    assert manifest["implemented_operations"] == []  # Schema availability is not API implementation.
    assert set(examples) == {operation["operation"] for operation in manifest["operations"]}
    vectors = {}
    for operation in manifest["operations"]:
        params = dict(examples[operation["operation"]])
        assert operation["scope"] in {"runtime", "profile"}
        assert operation["permission"] in {"observe", "runtime_owner", "profile_owner", "pair",
                                            "approve", "connect", "send", "read", "diagnose"}
        if operation["scope"] == "profile":
            params["profile"] = handle
        request = {"api_version": 1, "request_id": "vector:1", "operation": operation["operation"], "params": params}
        if operation["idempotency"] == "caller_profile_operation_key":
            request["idempotency_key"] = ("a" * 64 if operation["operation"] in
                {"peer.composer_update", "message.enqueue_draft"} else "operation-key-0001")
        vectors[operation["operation"]] = request
    return vectors


@pytest.mark.parametrize("operation,value", request_vectors().items())
def test_each_designed_operation_has_an_executable_request_vector_and_permission(operation, value):
    contract = {"native.command": "core-api/private-host-request-v1.schema.json",
                "bootstrap.preview": "core-api/private-bootstrap-request-v1.schema.json"}.get(
                    operation, "core-api/request-v1.schema.json")
    validator(contract).validate(value)
    if operation in COMPONENT_OPERATIONS:
        assert parse_request(value, COMPONENT_OPERATIONS) == (operation, value["params"])


def test_keyed_operation_inventory_matches_the_public_manifest_and_schema():
    vectors = request_vectors()
    assert KEYED_OPERATIONS == {operation for operation, value in vectors.items()
                                if "idempotency_key" in value}
    contract = validator("core-api/request-v1.schema.json")
    for operation, value in vectors.items():
        changed = deepcopy(value)
        if operation in KEYED_OPERATIONS:
            del changed["idempotency_key"]
        else:
            changed["idempotency_key"] = "unexpected-key-0001"
        if operation in OPTIONAL_KEY_OPERATIONS:
            if contract.is_valid(changed):
                if operation in COMPONENT_OPERATIONS:
                    assert parse_request(changed, COMPONENT_OPERATIONS) == (operation, changed["params"])
                continue
        assert not contract.is_valid(changed), operation
        if operation in COMPONENT_OPERATIONS:
            with pytest.raises(ApiFailure, match="invalid_request"):
                parse_request(changed, COMPONENT_OPERATIONS)


def test_composite_action_key_requirements_are_shared_with_the_contract():
    manifest = json.loads((CONTRACTS / "core-api/operations-v1.json").read_text())
    assert {operation: sorted(actions) for operation, actions in KEYED_ACTIONS.items()} == manifest["keyed_actions"]
    schema = validator("core-api/request-v1.schema.json").schema
    for operation, actions in KEYED_ACTIONS.items():
        branch = next(item for item in schema["oneOf"] if item["properties"]["operation"]["const"] == operation)
        condition = branch["allOf"][0]
        assert condition["if"]["properties"]["params"]["properties"]["action"]["enum"] == sorted(actions)
        assert condition["then"] == {"required": ["idempotency_key"]}


@pytest.mark.parametrize("key", [None, [], {}, True, 123, "short", "x" * 129, "/" * 20])
def test_every_keyed_component_rejects_malformed_envelope_keys(key):
    for operation, value in request_vectors().items():
        if operation not in COMPONENT_OPERATIONS or operation not in KEYED_OPERATIONS:
            continue
        changed = {**value, "idempotency_key": key}
        with pytest.raises(ApiFailure, match="invalid_request"):
            parse_request(changed, COMPONENT_OPERATIONS)


@pytest.mark.parametrize("params", [None, [], "params", 1, True])
def test_every_component_rejects_non_object_params(params):
    for operation, value in request_vectors().items():
        if operation in COMPONENT_OPERATIONS:
            with pytest.raises(ApiFailure, match="invalid_request"):
                parse_request({**value, "params": params}, COMPONENT_OPERATIONS)


@pytest.mark.parametrize("bad", [None, [], {}, True, 3, "", "x" * 2000])
def test_malformed_component_fields_are_rejected_at_the_parser_boundary(bad):
    schema = validator("core-api/request-v1.schema.json").schema
    branches = {item["properties"]["operation"]["const"]:
                Draft202012Validator({**item, "$defs": schema["$defs"]})
                for item in schema["oneOf"]}
    branches["native.command"] = validator("core-api/private-host-request-v1.schema.json")
    branches["bootstrap.preview"] = validator("core-api/private-bootstrap-request-v1.schema.json")
    for operation, value in request_vectors().items():
        if operation not in COMPONENT_OPERATIONS:
            continue
        for field in value["params"]:
            changed = deepcopy(value)
            changed["params"][field] = bad
            if branches[operation].is_valid(changed):
                continue
            with pytest.raises(ApiFailure, match="invalid_request"):
                parse_request(changed, COMPONENT_OPERATIONS)


def test_private_native_commands_are_not_public_contract_requests():
    value = request_vectors()["native.command"]
    assert not validator("core-api/request-v1.schema.json").is_valid(value)
    validator("core-api/private-host-request-v1.schema.json").validate(value)


@pytest.mark.parametrize("operation,extra", [
    ("workspace.timeline_mutation", {"action": "notification_preference", "conversation": None,
                                     "mode": "mentions"}),
    ("workspace.history", {"action": "start", "conversation": "channel1"}),
    ("workspace.history", {"action": "cancel", "conversation": "channel1"}),
    ("workspace.history", {"action": "prune"}),
    ("workspace.history", {"action": "revisions", "event_id": "event1"}),
    ("workspace.history", {"action": "tombstones", "conversation": "channel1"}),
    ("workspace.access_recommendation", {"action": "create", "remote_profile_id": None}),
    ("workspace.timeline_mutation", {"action": "workspace_read", "channel": "channel1", "high_water": 0}),
])
def test_workspace_wide_notifications_and_history_targets_match_runtime(operation, extra):
    value = {"api_version": 1, "request_id": "action:1", "operation": operation,
             "idempotency_key": "composite-action-key", "params": {
                 "profile": "p" * 32, "workspace": "w" * 32, **extra}}
    validator("core-api/request-v1.schema.json").validate(value)
    assert parse_request(value, COMPONENT_OPERATIONS) == (operation, value["params"])


@pytest.mark.parametrize("operation,extra", [
    ("remote_profile.mutate", {"action": "create", "label": "Relay",
                               "endpoints": [{"host": "relay.example", "port": 4242}]}),
    ("route.update", {"action": "create", "scope_kind": "contact", "scope_id": "c1",
                      "peer_destination": "ab" * 16}),
    ("call.control", {"action": "signal_publish", "document": "signed", "role": "offer"}),
    ("call.control", {"action": "signal_fetch", "session": "pairing", "role": "answer"}),
])
def test_optional_component_fields_and_domain_signaling_roles(operation, extra):
    value = {"api_version": 1, "request_id": "action:1", "operation": operation,
             "idempotency_key": "composite-action-key", "params": {"profile": "p" * 32, **extra}}
    validator("core-api/request-v1.schema.json").validate(value)
    assert parse_request(value, COMPONENT_OPERATIONS) == (operation, value["params"])



@pytest.mark.parametrize("field,value", [("caller_id", "owner"), ("permissions", ["approve"]),
    ("runtime_epoch", "spoofed"), ("resource_id", "native-private"), ("authenticated_receipt", True),
    ("vault_key", "secret"), ("profile_dir", "C:/private"), ("delivered", True)])
def test_public_requests_cannot_supply_private_authority(field, value):
    contract = validator("core-api/request-v1.schema.json")
    for where in ("envelope", "params"):
        request = enqueue_request()
        (request if where == "envelope" else request["params"])[field] = value
        assert not contract.is_valid(request)


@pytest.mark.parametrize("mutation", [
    {"api_version": 2}, {"operation": "native_webrtc_event"},
    {"operation": "receipt.confirm"}, {"request_id": "x" * 81},
    {"params": {"profile": "../../vault", "recipient": "authorizedPeer0001", "kind": "text", "text": "Hello"}},
])
def test_incompatible_versions_private_operations_and_unbounded_ids_are_rejected(mutation):
    request = {**enqueue_request(), **deepcopy(mutation)}
    assert not validator("core-api/request-v1.schema.json").is_valid(request)


def test_public_errors_have_no_exception_or_unbounded_diagnostic_channel():
    contract = validator("core-api/error-v1.schema.json")
    response = {"api_version": 1, "request_id": "request:1", "ok": False,
                "error": {"code": "forbidden", "retry_after_ms": None}}
    contract.validate(response)
    response["error"]["exception"] = "private SDP"
    assert not contract.is_valid(response)
