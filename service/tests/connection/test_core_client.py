"""Strict Python client and CLI over the private frame contract."""

import io
import json

import pytest

from mesh_chat.core_api.cli import run as run_cli
from mesh_chat.core_api.client import CoreClient, CoreClientError
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame

PROFILE = "p" * 64
PEER = "q" * 64
MESSAGE = "m" * 64


class Scripted:
    def __init__(self, *frames):
        self.frames = list(frames)
        self.written = []
        self.closed = False

    def readline(self, limit=0):
        return self.frames.pop(0) if self.frames else b""

    def write(self, payload):
        self.written.append(payload)
        return len(payload)

    def close(self):
        self.closed = True


def reply(result, request_id="client:1"):
    return encode_frame({"api_version": 1, "request_id": request_id, "ok": True, "result": result})


def failure(code, request_id="client:1", retry=None):
    return encode_frame({"api_version": 1, "request_id": request_id, "ok": False,
                         "error": {"code": code, "retry_after_ms": retry}})


CAPABILITIES = {"api_major": 1, "api_minor": 0, "stability": "experimental",
                "operations": ["runtime.capabilities", "profile.query", "message.received"],
                "profiles": [PROFILE], "limits": {"frame_bytes": 4194304}}


def test_client_negotiates_and_sends_the_declared_envelope():
    transport = Scripted(reply(CAPABILITIES))
    client = CoreClient.open(transport.readline, transport.write)
    assert client.capabilities["profiles"] == [PROFILE]
    sent = decode_frame(transport.written[0])
    assert sent == {"api_version": 1, "request_id": "client:1",
                    "operation": "runtime.capabilities", "params": {}}


def test_client_raises_typed_errors_with_retry_hint():
    transport = Scripted(reply(CAPABILITIES), failure("resync_required", "client:2", 1500))
    client = CoreClient.open(transport.readline, transport.write)
    with pytest.raises(CoreClientError) as raised:
        client.received(PROFILE)
    assert (raised.value.code, raised.value.request_id, raised.value.retry_after_ms) == (
        "resync_required", "client:2", 1500)


@pytest.mark.parametrize("frame,code", [
    (b"{not json}\n", "protocol"),
    (encode_frame({"api_version": 2, "request_id": "client:2", "ok": True, "result": {}}), "protocol"),
    (encode_frame({"api_version": 1, "request_id": "client:9", "ok": True, "result": {}}), "protocol"),
    (b"", "transport_closed"),
])
def test_malformed_or_misrouted_responses_fail_closed(frame, code):
    transport = Scripted(reply(CAPABILITIES), frame)
    client = CoreClient.open(transport.readline, transport.write)
    with pytest.raises(CoreClientError) as raised:
        client.profile(PROFILE)
    assert raised.value.code == code


def test_helpers_send_declared_parameters_and_idempotency_keys():
    transport = Scripted(
        reply(CAPABILITIES),
        reply({"profile": PROFILE, "messages": [], "next_cursor": None, "more": False}, "client:2"),
        reply({"profile": PROFILE, "message": MESSAGE, "accepted": True, "accepted_at": 1,
               "idempotency_expires_at": 2}, "client:3"),
    )
    client = CoreClient.open(transport.readline, transport.write)
    client.received(PROFILE, "cursor-token-0001", 7)
    client.enqueue(PROFILE, PEER, "Hello", "enqueue-key-0001")
    assert decode_frame(transport.written[1])["params"] == {
        "profile": PROFILE, "cursor": "cursor-token-0001", "limit": 7}
    assert decode_frame(transport.written[2])["idempotency_key"] == "enqueue-key-0001"


def test_cli_prints_the_selected_result_as_json():
    page = {"profile": PROFILE, "messages": [], "next_cursor": None, "more": False}
    transport = Scripted(reply(CAPABILITIES), reply(page, "client:2"))
    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "received", "--limit", "4"],
                   transport, out, err) == 0
    assert json.loads(out.getvalue())["messages"] == []
    assert err.getvalue() == ""
    assert decode_frame(transport.written[1])["params"]["limit"] == 4


def test_cli_maps_typed_failures_to_a_nonzero_exit_without_raising():
    transport = Scripted(reply(CAPABILITIES), failure("forbidden", "client:2"))
    out, err = io.StringIO(), io.StringIO()
    assert run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "profile"], transport, out, err) == 2
    assert json.loads(err.getvalue())["error"] == "forbidden"
    assert out.getvalue() == ""


def test_cli_rejects_unknown_commands():
    with pytest.raises(SystemExit) as raised:
        run_cli(["--pipe", r"\\.\pipe\mesh-chat-test", "explode"], Scripted(), io.StringIO(), io.StringIO())
    assert raised.value.code == 2
