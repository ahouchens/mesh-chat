"""Framed runtime mutations retain their key and typed storage failures."""

import sqlite3

import pytest

from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from test_background_preference_idempotency import hosts


def open_client(service):
    client = bind_service_stream(service, lambda: Grant(
        "runtime-ui", frozenset({"observe", "read", "send"}), ("local",)))
    reply = decode_frame(client.exchange(encode_frame({
        "api_version": 1, "request_id": "runtime:1", "operation": "runtime.capabilities", "params": {},
    })))
    return client, reply["result"]["profiles"][0]


def mutate(client, profile, key, action, **params):
    return decode_frame(client.exchange(encode_frame({
        "api_version": 1, "request_id": "runtime:1", "operation": "runtime.mutate",
        "idempotency_key": key, "params": {"profile": profile, "action": action, **params},
    })))


def test_background_receipt_survives_reopen_and_projects_newer_preference(hosts):
    open_host, effects, _, _ = hosts
    service = open_host()
    client, profile = open_client(service)
    first = mutate(client, profile, "background-stable-key", "background_set", enabled=True)
    assert first["ok"], first
    assert len(service.store.list("workspace_operation")) == 1
    assert mutate(client, profile, "background-stable-key", "background_set", enabled=True) == first
    assert len(effects) == 1
    assert mutate(client, profile, "background-stable-key", "background_set", enabled=False)["error"]["code"] == "idempotency_conflict"
    assert mutate(client, profile, "background-newer-key", "background_set", enabled=False)["ok"]
    service.close()
    reopened = open_host()
    client, profile = open_client(reopened)
    replay = mutate(client, profile, "background-stable-key", "background_set", enabled=True)
    assert replay["ok"] and replay["result"]["result"]["enabled"] is False, replay
    assert len(reopened.store.list("workspace_operation")) == 2


@pytest.mark.parametrize("action,params", [
    ("background_set", {"enabled": True}), ("notification_previews", {"hidden": True}),
])
@pytest.mark.parametrize("failure", [OSError, sqlite3.OperationalError])
def test_real_commit_failure_is_unavailable_and_rolls_back(hosts, monkeypatch, action, params, failure):
    open_host, effects, _, _ = hosts
    service = open_host()
    client, profile = open_client(service)
    before = service.store.list("workspace_operation")
    original = service.store._write_records_locked

    def fail(*args):
        original(*args)
        raise failure("injected runtime commit failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    reply = mutate(client, profile, "runtime-storage-fault", action, **params)
    assert reply["error"]["code"] == "unavailable", reply
    assert service.store.list("workspace_operation") == before
    assert effects == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert mutate(client, profile, "runtime-storage-fault", action, **params)["ok"]
