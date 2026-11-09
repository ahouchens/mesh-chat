"""Independent framed callers and signed removal constrain optional-key replay."""

import json
from pathlib import Path
import sys

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.service import MeshChatService

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_group_service import _deliver, _joined_pair, _sent_values


@pytest.fixture
def signed_group(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    pair = _joined_pair(tmp_path)
    for service in (pair.owner, pair.member):
        service._retry_thread.join(timeout=2)
        assert not service._retry_thread.is_alive()
        service._shutdown.clear()
    streams = []
    def client(service, caller):
        stream = bind_service_stream(service, lambda: Grant(
            caller, frozenset({"observe", "read", "send", "approve"}), ("local",)))
        streams.append(stream)
        def exchange(operation, params=None, key=None):
            frame = {"api_version": 1, "request_id": "independent-group:1",
                     "operation": operation, "params": params or {}}
            if key is not None: frame["idempotency_key"] = key
            return json.loads(stream.exchange(json.dumps(frame).encode() + b"\n"))
        caps = exchange("runtime.capabilities")["result"]
        assert set(caps["optional_keyed_operations"]) == {"group.create", "group.message_enqueue"}
        profile = caps["profiles"][0]
        peer = exchange("profile.query", {"profile": profile})["result"]["peers"][0]
        group = exchange("group.query", {"profile": profile})["result"]["groups"][0]["group"]
        return exchange, profile, peer, group
    try:
        yield pair, client
    finally:
        for stream in streams: stream.close()
        pair.close()


def params(client, operation):
    _, profile, peer, group = client
    return ({"profile": profile, "title": "Independent caller group", "members": [peer], "posting_policy": "members"}
            if operation == "group.create" else {"profile": profile, "group": group, "text": "Independent caller message"})


@pytest.mark.parametrize("operation", ["group.create", "group.message_enqueue"])
def test_same_external_key_is_scoped_to_authenticated_caller_and_foreign_handles_never_replay(signed_group, operation):
    pair, client = signed_group
    left, right = client(pair.owner, "independent-left"), client(pair.owner, "independent-right")
    assert left[1:] != right[1:]
    key = "same-user-selected-group-key-0001"
    namespace = "group" if operation == "group.create" else "group_message"
    baseline = pair.owner.store.record_count(namespace)
    accepted = left[0](operation, params(left, operation), key)
    assert accepted["ok"], accepted
    before = pair.owner.store._db.total_changes
    forbidden = right[0](operation, params(left, operation), key)
    assert forbidden["ok"] is False and forbidden["error"]["code"] == "forbidden"
    assert "result" not in forbidden and pair.owner.store._db.total_changes == before
    separate = right[0](operation, params(right, operation), key)
    assert separate["ok"] and separate["result"] != accepted["result"]
    assert pair.owner.store.record_count(namespace) == baseline + 2
    for scoped, reply in ((left, accepted), (right, separate)):
        assert scoped[0](operation, params(scoped, operation), key) == reply
    assert pair.owner.store.record_count(namespace) == baseline + 2
    receipts = pair.owner.store.list("api_optional_mutation")
    assert {item["caller"] for item in receipts} == {"independent-left", "independent-right"}
    assert len(receipts) == 2 and all(item["count"] == 1 for item in pair.owner.store.list("api_optional_quota"))


def test_actual_signed_group_removal_denies_accepted_key_replay_and_fresh_send_without_effects(signed_group):
    pair, client = signed_group
    member = client(pair.member, "independent-removed-member")
    request = params(member, "group.message_enqueue")
    key = "signed-group-removal-replay-0001"
    accepted = member[0]("group.message_enqueue", request, key)
    assert accepted["ok"], accepted
    pair.owner.remove_group_member(pair.group_id, pair.member_profile["destination_hash"])
    removal = _sent_values(pair.owner_network, "group_manifest",
        recipient=bytes.fromhex(pair.member_profile["destination_hash"]), epoch=3)[-1]
    _deliver(pair.member, removal, source_profile=pair.owner_profile, destination_profile=pair.member_profile)
    assert pair.member.snapshot()["groups"][0]["status"] == "removed"
    namespaces = ("group_message", "group_delivery", "workspace_operation", "api_optional_mutation", "api_optional_quota")
    before = {name: pair.member.store.items(name) for name in namespaces}
    writes = pair.member.store._db.total_changes
    for caller_key in (key, key + "-fresh", None):
        reply = member[0]("group.message_enqueue", request, caller_key)
        assert reply["ok"] is False and reply["error"]["code"] == "forbidden"
        assert "result" not in reply
    assert {name: pair.member.store.items(name) for name in namespaces} == before
    assert pair.member.store._db.total_changes == writes
