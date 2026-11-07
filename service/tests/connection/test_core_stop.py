"""Owner-authorized runtime stop through the private facade."""

import json
import os
from pathlib import Path
import threading

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.client import CoreClient, CoreClientError
from mesh_chat.core_api.composition import bind_service_session, bind_service_stream
from mesh_chat.core_api.session import Grant
from test_core_messages import host, request


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"


def open_session(service, permissions, caller="alex"):
    grants = [Grant(caller, frozenset(permissions), ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    return session, capabilities["result"]


def stop(session):
    return session.request(request("runtime.stop"))


def test_owner_stop_requests_shutdown_and_refuses_further_work(host):
    service = host()
    session, capabilities = open_session(service, ("observe", "runtime_owner"))
    assert "runtime.stop" in capabilities["operations"]
    reply = stop(session)
    assert reply["ok"], reply
    assert reply["result"] == {"stopping": True, "already_stopping": False}
    assert service._shutdown.is_set()
    assert stop(session)["error"]["code"] == "forbidden"
    schema = json.loads((CONTRACTS / "stop-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(reply)


def test_stop_observation_reports_an_existing_request(host):
    from mesh_chat.core_api.service_lifecycle import ServiceLifecycle

    service = host()
    lifecycle = ServiceLifecycle(service)
    first = lifecycle.stop()
    assert (first.stopping, first.already_stopping) == (True, False)
    second = lifecycle.stop()
    assert (second.stopping, second.already_stopping) == (True, True)


def test_a_second_owner_session_is_unauthenticated_after_shutdown(host):
    service = host()
    first, _ = open_session(service, ("observe", "runtime_owner"))
    second, _ = open_session(service, ("observe", "runtime_owner"))
    assert stop(first)["result"]["already_stopping"] is False
    assert stop(second)["error"]["code"] == "unauthenticated"


def test_only_the_owner_can_stop(host):
    service = host()
    session, _ = open_session(service, ("observe", "read"))
    assert stop(session)["error"]["code"] == "forbidden"
    assert not service._shutdown.is_set()


def test_stop_refuses_a_caller_idempotency_key(host):
    service = host()
    session, _ = open_session(service, ("observe", "runtime_owner"))
    keyed = {"api_version": 1, "request_id": "request:1", "operation": "runtime.stop",
             "params": {}, "idempotency_key": "k" * 16}
    assert session.request(keyed)["error"]["code"] == "invalid_request"
    assert not service._shutdown.is_set()


def test_framed_owner_stop_replies_then_closes_the_stream(host):
    service = host()
    grant = Grant("alex", frozenset({"observe", "runtime_owner"}), ("local",))
    framed = bind_service_stream(service, lambda: grant)
    requests_read, requests_write = os.pipe()
    responses_read, responses_write = os.pipe()

    def serve():
        with os.fdopen(requests_read, "rb", buffering=0) as reader:
            with os.fdopen(responses_write, "wb", buffering=0) as writer:
                framed.serve(reader, writer)

    thread = threading.Thread(target=serve, name="core-api-stop-host", daemon=True)
    thread.start()
    with os.fdopen(requests_write, "wb", buffering=0) as writer:
        with os.fdopen(responses_read, "rb", buffering=0) as reader:
            client = CoreClient.open(lambda limit: reader.readline(limit), writer.write)
            assert client.request("runtime.stop") == {"stopping": True, "already_stopping": False}
            assert reader.readline(4) == b""
    thread.join(5)
    assert not thread.is_alive()
