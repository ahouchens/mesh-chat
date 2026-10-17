import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from mesh_chat.direct_native import NativeChannel, NativeFrameReader
from mesh_chat.errors import ValidationError
from mesh_chat.ipc import encode_frame
from mesh_chat import mobile_bridge


def reply(request, result=None, ok=True):
    return {"type": "direct_native_reply", "id": request["id"], "ok": ok, "result": result}


def wait_requests(channel, count=1):
    requests = []
    deadline = time.monotonic() + 2
    while len(requests) < count and time.monotonic() < deadline:
        requests.extend(channel.drain())
        time.sleep(.001)
    assert len(requests) == count
    return requests


def test_native_reordered_duplicate_and_foreign_replies():
    channel = NativeChannel()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(channel.request, "poll", id=1)
        second = pool.submit(channel.request, "poll", id=2)
        requests = wait_requests(channel, 2)
        assert not channel.receive({"type": "direct_native_reply", "id": "foreign", "ok": True, "result": None})
        for request in reversed(requests):
            response = reply(request, request["request"]["id"])
            assert channel.receive(response)
            assert not channel.receive(response)
        assert first.result() == 1 and second.result() == 2


def test_native_request_budgets_and_shutdown_wake_waiters():
    channel = NativeChannel()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(channel.request, "poll", id=i) for i in range(8)]
        wait_requests(channel, 8)
        with pytest.raises(ValidationError, match="budget"):
            channel.request("poll", id=9)
        channel.close()
        channel.close()
        assert [item["request"]["op"] for item in channel.drain()] == ["reset"]
        for future in futures:
            with pytest.raises(ValidationError, match="closed"):
                future.result(timeout=1)
    with pytest.raises(ValidationError, match="closed"):
        channel.request("prepare")


@pytest.mark.parametrize("response", [{}, {"type": "event"},
    {"type": "direct_native_reply", "id": "x", "ok": 1, "result": None},
    {"type": "direct_native_reply", "id": "x", "ok": True, "result": "x"*65536}])
def test_invalid_private_response_fails_closed(response):
    channel = NativeChannel()
    with pytest.raises(ValidationError):
        channel.receive(response)
    with pytest.raises(ValidationError, match="closed"):
        channel.request("poll", id=1)


def test_native_timeout_resets_unknown_outcome_and_rejects_late_reply():
    channel = NativeChannel()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(channel.request, "prepare", timeout=.05)
        request = wait_requests(channel)[0]
        with pytest.raises(ValidationError, match="timed out"):
            future.result()
        assert channel.drain()[0]["request"] == {"op": "reset"}
        assert not channel.receive(reply(request, {"id": 42}))


def test_native_transport_failure_and_oversized_request():
    def broken(_request):
        raise BrokenPipeError()
    channel = NativeChannel(broken)
    with pytest.raises(BrokenPipeError):
        channel.request("poll", id=1)
    with pytest.raises(ValidationError, match="closed"):
        channel.request("poll", id=1)
    for operation, payload in [("renderer_command", {}), ("send", {"packets": ["x"*65536]})]:
        with pytest.raises(ValidationError):
            NativeChannel().request(operation, **payload)


def test_suspension_retires_pending_work_without_reviving_old_handles():
    channel = NativeChannel()
    with ThreadPoolExecutor() as pool:
        first = pool.submit(channel.request, "poll", id=1)
        old = wait_requests(channel)[0]
        channel.retire()
        with pytest.raises(ValidationError, match="retired"):
            first.result(timeout=1)
        assert channel.drain()[0]["request"] == {"op": "reset"}
        assert not channel.receive(reply(old, "late"))
        fresh = pool.submit(channel.request, "prepare")
        request = wait_requests(channel)[0]
        assert channel.receive(reply(request, {"id": 2}))
        assert fresh.result(timeout=1) == {"id": 2}


def test_close_never_waits_for_a_blocked_private_writer():
    entered, release = threading.Event(), threading.Event()
    def send(_request):
        entered.set()
        assert release.wait(2)
    channel = NativeChannel(send)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(channel.request, "poll", id=1)
        assert entered.wait(1)
        try:
            before = time.monotonic()
            channel.close()
            assert time.monotonic()-before < .1
            with pytest.raises(ValidationError, match="closed"):
                channel.request("poll", id=2)
        finally:
            release.set()
        with pytest.raises(ValidationError, match="closed"):
            future.result(timeout=1)


def test_desktop_reader_delivers_private_result_during_dispatch_wait():
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as stream, os.fdopen(write_fd, "wb", buffering=0) as writer:
        channel = NativeChannel()
        reader = NativeFrameReader(stream, channel)
        writer.write(encode_frame({"command": "ordinary"}))
        assert reader.read() == {"command": "ordinary"}
        with ThreadPoolExecutor() as pool:
            future = pool.submit(channel.request, "poll", id=1)
            request = wait_requests(channel)[0]
            writer.write(encode_frame(reply(request, "private")))
            assert future.result(timeout=1) == "private"
        reader.close()
        writer.close()
        reader._thread.join(timeout=1)
        assert not reader._thread.is_alive()


def test_desktop_eof_drains_commands_and_overflow_fails_closed():
    channel = NativeChannel()
    reader = NativeFrameReader(io.BytesIO(encode_frame({"command": "snapshot"})), channel)
    reader._thread.join(timeout=1)
    assert reader.read() == {"command": "snapshot"}
    with pytest.raises(EOFError):
        reader.read()
    reader = NativeFrameReader(io.BytesIO(encode_frame({"command": "snapshot"})*9), NativeChannel())
    reader._thread.join(timeout=1)
    with pytest.raises(Exception):
        reader.read()


def test_mobile_private_exchange_bypasses_command_lock_and_events(monkeypatch):
    channel = NativeChannel()
    monkeypatch.setattr(mobile_bridge, "_native_channel", channel)
    with ThreadPoolExecutor() as pool:
        with mobile_bridge._service_lock:
            future = pool.submit(channel.request, "poll", id=1)
            deadline = time.monotonic()+2
            requests = []
            while not requests and time.monotonic()<deadline:
                requests = json.loads(mobile_bridge.direct_exchange('{"responses":[]}'))["result"]
                time.sleep(.001)
            assert len(requests) == 1
            assert json.loads(mobile_bridge.drain_events())["result"] == []
            result = mobile_bridge.direct_exchange(json.dumps({"responses": [reply(requests[0], "native only")]}))
            assert json.loads(result)["ok"]
            assert future.result(timeout=1) == "native only"
    assert not json.loads(mobile_bridge.direct_exchange('{"responses":[],"extra":1}'))["ok"]
