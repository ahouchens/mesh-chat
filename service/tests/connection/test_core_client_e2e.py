"""End-to-end Python client and CLI against the real framed facade."""

import io
import json
import os
import threading

import pytest

from mesh_chat.core_api.cli import run as run_cli
from mesh_chat.core_api.client import CoreClient, CoreClientError
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from test_core_messages import host


PROFILE_PERMISSIONS = frozenset({"observe", "read", "send"})


class HostedClient:
    def __init__(self, service):
        server_read, client_write = os.pipe()
        client_read, server_write = os.pipe()
        grants = [Grant("alex", PROFILE_PERMISSIONS, ("local",))]
        session = bind_service_stream(service, lambda: grants[0])

        def serve():
            with os.fdopen(server_read, "rb", buffering=0) as reader, \
                    os.fdopen(server_write, "wb", buffering=0) as writer:
                session.serve(reader, writer)

        self.thread = threading.Thread(target=serve, name="core-api-test-host", daemon=True)
        self.reader = os.fdopen(client_read, "rb", buffering=0)
        self.writer = os.fdopen(client_write, "wb", buffering=0)
        self.thread.start()

    def close(self):
        self.reader.close()
        self.writer.close()
        self.thread.join(5)
        assert not self.thread.is_alive()


@pytest.fixture
def hosted(host):
    client = HostedClient(host())
    yield client
    client.close()


def test_client_round_trip_against_the_real_facade(hosted):
    client = CoreClient.open(hosted.reader.readline, hosted.writer.write)
    assert "message.received" in client.capabilities["operations"]
    profile = client.capabilities["profiles"][0]
    peers = client.profile(profile)["peers"]
    assert peers, "the fixture contact must be visible"
    accepted = client.enqueue(profile, peers[0], "Hello over a real frame", "enqueue-key-0001")
    assert accepted["accepted"] is True
    queried = client.request("message.query", {"profile": profile, "message": accepted["message"]})
    assert queried["text"] == "Hello over a real frame"
    assert client.received(profile)["messages"] == []
    snapshot = client.request("message.list", {"profile": profile, "cursor": None, "limit": 128})
    replay = client.poll(profile, snapshot["events_cursor"])
    assert isinstance(replay["events"], list)
    with pytest.raises(CoreClientError) as raised:
        client.poll(profile)
    assert raised.value.code == "resync_required"


def test_cli_runs_against_the_real_facade(hosted):
    class Transport:
        readline = staticmethod(hosted.reader.readline)
        write = staticmethod(hosted.writer.write)

        @staticmethod
        def close():
            return None

    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "capabilities"], Transport(), out, err) == 0
    result = json.loads(out.getvalue())
    assert "connection.start" in result["operations"]
    assert err.getvalue() == ""


def test_unknown_profile_handle_is_rejected_as_forbidden(hosted):
    client = CoreClient.open(hosted.reader.readline, hosted.writer.write)
    with pytest.raises(CoreClientError) as raised:
        client.received("a" * 64)
    assert raised.value.code == "forbidden"


def test_malformed_handle_is_rejected_as_invalid(hosted):
    client = CoreClient.open(hosted.reader.readline, hosted.writer.write)
    with pytest.raises(CoreClientError) as raised:
        client.received("not-a-handle")
    assert raised.value.code == "invalid_request"
