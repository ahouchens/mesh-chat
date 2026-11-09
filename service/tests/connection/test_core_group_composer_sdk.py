"""Standalone SDK gating and actual installed group composer consumers."""
import json
from copy import deepcopy

import pytest

from mesh_chat_core_client import CoreClient, CoreClientError
from mesh_chat.core_api.service_group_composer import GROUP_COMPOSER_LIMITS
from test_core_client import Scripted, reply, CAPABILITIES
from test_core_sdk_distribution import installed_consumer, run_consumer
from test_group_operation_idempotency import group_host

OPERATIONS = ["group.composer_query", "group.composer_update", "group.message_enqueue_draft"]


def capabilities():
    return {**deepcopy(CAPABILITIES), "api_minor": 1, "operations": OPERATIONS, "limits": dict(GROUP_COMPOSER_LIMITS)}


@pytest.mark.parametrize("broken", ["minor", "fraction", "boolean", "string", "operation", "limit", "limit_bool", "limit_unsafe"])
def test_python_group_composer_requires_complete_safe_feature_before_io(broken):
    caps = capabilities()
    if broken in {"minor", "fraction", "boolean", "string"}:
        caps["api_minor"] = {"minor": 0, "fraction": 1.5, "boolean": True, "string": "1"}[broken]
    elif broken == "operation":
        caps["operations"] = OPERATIONS[:-1]
    else:
        caps["limits"]["group_composer_text_utf8_bytes"] = {"limit": 0, "limit_bool": True, "limit_unsafe": 2**53}[broken]
    transport = Scripted(reply(caps))
    if broken in {"fraction", "boolean", "string", "limit_unsafe"}:
        with pytest.raises(CoreClientError) as raised:
            CoreClient.open(transport.readline, transport.write)
        assert raised.value.code == ("protocol" if broken == "limit_unsafe" else "incompatible_version")
        assert len(transport.written) == 1
        return
    client = CoreClient.open(transport.readline, transport.write)
    for call in (lambda: client.group_composer_query("p"*64, "g"*64),
                 lambda: client.group_composer_update("p"*64, "g"*64, None, "text", "b"*64),
                 lambda: client.group_enqueue_draft("p"*64, "g"*64, "a"*64)):
        with pytest.raises(CoreClientError) as raised:
            call()
        assert raised.value.code == "unsupported_operation"
    assert len(transport.written) == 1


def test_python_group_composer_preserves_issued_tokens_and_refuses_local_bad_input():
    transport = Scripted(reply(capabilities()), reply({}, "client:2"), reply({}, "client:3"), reply({}, "client:4"))
    client = CoreClient.open(transport.readline, transport.write)
    with pytest.raises(ValueError):
        client.group_enqueue_draft("p"*64, "g"*64, "caller-random-key-0001")
    with pytest.raises(ValueError):
        client.group_composer_update("p"*64, "g"*64, None, "é"*8193, "b"*64)
    client.group_composer_query("p"*64, "g"*64, "a"*64)
    client.group_composer_update("p"*64, "g"*64, None, "draft", "b"*64)
    client.group_enqueue_draft("p"*64, "g"*64, "a"*64)
    frames = [json.loads(frame) for frame in transport.written]
    assert len(frames) == 4
    assert frames[1]["params"]["send_revision"] == "a"*64
    assert frames[2]["idempotency_key"] == "b"*64 and frames[2]["params"]["expected_revision"] is None
    assert frames[3]["idempotency_key"] == frames[3]["params"]["draft_revision"] == "a"*64
    assert "text" not in frames[3]["params"]


def test_installed_sdk_group_composer_preserves_new_draft_and_original_acceptance(group_host, installed_consumer, record_property):
    pair, _ = group_host
    record_property("sdk_sha256", installed_consumer[-1])
    report = run_consumer(installed_consumer, pair.owner, "--exercise-group-composer")
    assert all(report[name] for name in ("sdk_only", "accepted", "draft_empty", "same_message", "newer_preserved", "superseded"))
    assert pair.owner.store.record_count("group_message") == pair.owner.store.record_count("api_group_composer_send") == 1


def test_installed_sdk_group_composer_lost_reply_reopens_without_renderer_key(group_host, installed_consumer, record_property):
    pair, reopen = group_host
    record_property("sdk_sha256", installed_consumer[-1])
    lost = run_consumer(installed_consumer, pair.owner, "--exercise-group-composer",
                        drop_commit_reply=True, drop_operation="group.message_enqueue_draft")
    assert lost["uncertain"]
    original = pair.owner.store.list("group_message")
    service = reopen()
    report = run_consumer(installed_consumer, service, "--recover-group-composer")
    assert report["sdk_only"] and report["recovered_acceptance"] and report["draft_empty"]
    assert [row["id"] for row in service.store.list("group_message")] == [row["id"] for row in original]
