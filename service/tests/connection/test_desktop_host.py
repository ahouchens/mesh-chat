"""Private inherited-pipe contract; no browser or packaged-host claims."""

import json
import io
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mesh_chat.desktop_transport_host import DesktopTransportHost
from mesh_chat.errors import NativeUnavailable, ValidationError
from mesh_chat.direct_native import NativeChannel, NativeFrameReader
from mesh_chat.ipc import encode_frame


def reply(request, result):
    return {"v": 1, "type": "desktop_transport_reply", "epoch": request["epoch"],
            "id": request["id"], "ok": True, "result": result}


def fixture(**options):
    outgoing, events = queue.Queue(), []
    host = DesktopTransportHost(outgoing.put_nowait, lambda *event: events.append(event), **options)
    return host, outgoing, events


def test_host_translates_native_contract_and_reordered_replies():
    host, outgoing, _ = fixture()
    with ThreadPoolExecutor(2) as pool:
        offer = pool.submit(host.createOffer, "native-one", '{"iceTransportPolicy":"relay"}',
                            '[{"label":"mesh-reticulum","binary":true,"ordered":true}]')
        first = outgoing.get(timeout=1)
        stats = pool.submit(host.stats, "native-two")
        second = outgoing.get(timeout=1)
        assert first["request"]["options"]["ice"] == {"iceTransportPolicy": "relay"}
        assert first["request"]["options"]["resource"] == "native-one"
        assert second["request"] == {"op": "inspect", "resource": "native-two"}
        host.receive(reply(second, {"data_channel_state": "open"}))
        host.receive(reply(first, {"sdp": "private", "fingerprint": "bound"}))
        assert json.loads(offer.result()) == {"ok": True, "sdp": "private", "fingerprint": "bound"}
        assert json.loads(stats.result()) == {"ok": True, "result": {"data_channel_state": "open"}}
        assert not host.receive(reply(first, {"sdp": "duplicate"}))
    host.shutdown()


def test_foreign_epochs_cannot_complete_current_work_or_inject_observations():
    host, outgoing, events = fixture()
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(host.applyAnswer, "native-one", "answer")
        request = outgoing.get(timeout=1)
        assert not host.receive({**reply(request, None), "epoch": "old"})
        assert not pending.done()
        event = {"v": 1, "type": "desktop_transport_event", "epoch": request["epoch"],
                 "event": "ice", "resource": "native-one", "data": "connected"}
        assert not host.receive({**event, "epoch": "old"})
        assert host.receive(event)
        assert events == [("ice", "native-one", "connected")]
        host.receive(reply(request, None))
        assert json.loads(pending.result()) == {"ok": True}
    host.shutdown()


def test_timeout_quarantines_unknown_outcome_and_rejects_late_reply():
    host, outgoing, events = fixture(timeout=.05)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(host.createOffer, "native-one", '{}', '[]')
        request = outgoing.get(timeout=1)
        with pytest.raises(NativeUnavailable, match="timed out"):
            pending.result(timeout=1)
        assert outgoing.get(timeout=1)["request"] == {"op": "reset"}
        assert not host.receive(reply(request, {"sdp": "late"}))
        assert events == [("overflow", "", "")]
        with pytest.raises(NativeUnavailable, match="closed"):
            host.stats("native-one")


def test_blocked_writer_does_not_block_deadline_or_shutdown():
    entered, release = threading.Event(), threading.Event()
    def blocked(_):
        entered.set()
        assert release.wait(2)
    host = DesktopTransportHost(blocked, lambda *_: None, timeout=.05)
    try:
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(host.stats, "native-one")
            assert entered.wait(1)
            with pytest.raises(NativeUnavailable, match="timed out"):
                pending.result(timeout=1)
            host.shutdown()
    finally:
        release.set()


def test_capacity_rejects_work_without_allocating_an_extra_request():
    host, outgoing, _ = fixture()
    with ThreadPoolExecutor(16) as pool:
        pending = [pool.submit(host.stats, f"native-{index}") for index in range(16)]
        for _ in pending:
            outgoing.get(timeout=1)
        with pytest.raises(NativeUnavailable, match="capacity"):
            host.stats("overflow")
        assert outgoing.empty()
        host.shutdown()
        for operation in pending:
            with pytest.raises(NativeUnavailable, match="closed"):
                operation.result(timeout=1)


@pytest.mark.parametrize("change", [
    {"v": 2}, {"ok": 1}, {"result": "x" * 262144}, {"extra": "private"},
])
def test_malformed_current_reply_quarantines_and_wakes_waiters(change):
    host, outgoing, events = fixture()
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(host.stats, "native-one")
        request = outgoing.get(timeout=1)
        with pytest.raises(ValidationError):
            host.receive({**reply(request, None), **change})
        with pytest.raises(NativeUnavailable):
            pending.result(timeout=1)
        assert events == [("overflow", "", "")]


def test_private_errors_are_redacted_and_send_requires_boolean_acknowledgment():
    host, outgoing, _ = fixture()
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(host.send, "native-one", bytes([1, 2]))
        request = outgoing.get(timeout=1)
        assert request["request"] == {"op": "send", "resource": "native-one", "packet": "AQI="}
        host.receive({**reply(request, "private ICE credential"), "ok": False})
        with pytest.raises(NativeUnavailable, match="^Desktop transport operation failed$"):
            pending.result(timeout=1)
        pending = pool.submit(host.sendControl, "native-one", "meshchat-reconnect", "control")
        request = outgoing.get(timeout=1)
        host.receive(reply(request, "truthy"))
        with pytest.raises(NativeUnavailable, match="acknowledgment"):
            pending.result(timeout=1)
    host.shutdown()


def test_packet_size_and_type_are_rejected_before_private_write():
    host, outgoing, _ = fixture()
    for packet in (b"", b"x" * 1065, "AQI=", None):
        assert host.send("native-one", packet) is False
    assert outgoing.empty()
    host.shutdown()


def test_inherited_reader_routes_transport_while_dispatch_is_waiting():
    host, outgoing, events = fixture()
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as stream, os.fdopen(write_fd, "wb", buffering=0) as writer:
        reader = NativeFrameReader(stream, NativeChannel(), desktop_transport=host)
        try:
            writer.write(encode_frame({"command": "snapshot"}))
            assert reader.read() == {"command": "snapshot"}
            with ThreadPoolExecutor() as pool:
                pending = pool.submit(host.stats, "native-one")
                request = outgoing.get(timeout=1)
                writer.write(encode_frame({"v": 1, "type": "desktop_transport_event", "epoch": request["epoch"],
                                          "resource": "native-one", "event": "open", "data": ""}))
                writer.write(encode_frame(reply(request, {"data_channel_state": "open"})))
                assert json.loads(pending.result(timeout=1))["result"]["data_channel_state"] == "open"
                assert events == [("open", "native-one", "")]
        finally:
            reader.close()
            writer.close()
            reader._thread.join(timeout=1)
            assert not reader._thread.is_alive()


@pytest.mark.parametrize("kind", ["desktop_transport_reply", "desktop_transport_event"])
def test_unregistered_transport_frames_cannot_fall_through_to_public_dispatch(kind):
    channel = NativeChannel()
    reader = NativeFrameReader(io.BytesIO(encode_frame({"type": kind})), channel)
    reader._thread.join(timeout=1)
    with pytest.raises(ValidationError, match="not registered"):
        reader.read()
    assert channel.closed
