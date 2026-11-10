"""Native Windows WebRTC host conformance over real aiortc data channels."""

import base64
import asyncio
import json
import queue
import time
import socket
from threading import Event, Thread, RLock
from types import SimpleNamespace
import urllib.request

import pytest

aiortc = pytest.importorskip("aiortc")

from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
from mesh_chat.native_windows_webrtc import _HostFailure


def finish_sample(coroutine):
    """Execute the actual non-yielding sampling coroutine without native I/O."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Sampling coroutine unexpectedly suspended")


@pytest.fixture
def private_sampler(monkeypatch):
    from mesh_chat import native_windows_webrtc as module
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline native sampler attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    clock = {"now": 10_000_000_000, "ticks": []}
    def now():
        return clock["ticks"].pop(0) if clock["ticks"] else clock["now"]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic_ns=now))
    instance = object.__new__(WindowsNativeWebRTCHost)
    instance._lock, instance._sampling = RLock(), {}
    instance._adapter_epoch = "a" * 32
    session = SimpleNamespace(resource="peer", closed=False, sample_sequence=0,
        pc=SimpleNamespace(iceConnectionState="new", sctp=None), channels={},
        enqueued_packets=0, enqueued_controls=0, enqueued_bytes=0,
        received_packets=0, received_controls=0, received_bytes=0)
    instance._sessions = {"peer": session}
    instance._submit = lambda coroutine, **kwargs: finish_sample(coroutine)
    yield instance, module, clock
    assert attempts == []


@pytest.mark.parametrize("origin", [10_000_000_000, 9_000_000_000_000_000, 1_000_000_000_000_000_000])
def test_private_sample_actual_coroutine_echoes_request_without_wall_clock(private_sampler, origin):
    instance, _, clock = private_sampler
    clock["now"] = origin
    first = json.loads(instance.pathEvidence("peer", "1" * 32))["result"]
    second = json.loads(instance.pathEvidence("peer", "2" * 32))["result"]
    assert first["sample_request"] == "1" * 32 and second["sample_request"] == "2" * 32
    assert first["sampled_at_ms"] == origin // 1_000_000
    assert second["sample_sequence"] == first["sample_sequence"] + 1
    assert not instance._sampling


@pytest.mark.parametrize("start,capture,end,valid", [
    (10_000_000_000, 10_000_000_000, 12_000_000_000, True),
    (10_000_000_000, 10_000_000_000, 12_000_000_001, False),
    (10_000_000_001, 10_000_000_000, 10_000_000_002, False),
    (10_000_000_000, 10_000_000_001, 10_000_000_000, False),
    (10_000_000_000, 12_000_000_001, 12_000_000_001, False),
])
def test_private_sample_enforces_full_resolution_invocation_capture_window(private_sampler, start, capture, end, valid):
    instance, _, clock = private_sampler
    clock["ticks"] = [start, capture, end]
    result = json.loads(instance.pathEvidence("peer", "1" * 32))
    assert result["ok"] is valid
    assert not instance._sampling


@pytest.mark.parametrize("fault", ["request", "missing_request", "old_timestamp", "future_timestamp", "epoch", "sequence"])
def test_private_sample_original_observation_cannot_be_relabelled(private_sampler, monkeypatch, fault):
    instance, module, _ = private_sampler
    original = module.observation
    def corrupted(*args, **kwargs):
        value = original(*args, **kwargs)
        if fault == "request": value["sample_request"] = "2" * 32
        elif fault == "missing_request": value.pop("sample_request")
        elif fault == "old_timestamp": value["sampled_at_ms"] -= 2001
        elif fault == "future_timestamp": value["sampled_at_ms"] += 1
        elif fault == "epoch": value["adapter_epoch"] = "b" * 32
        elif fault == "sequence": value["sample_sequence"] += 1
        return value
    monkeypatch.setattr(module, "observation", corrupted)
    assert json.loads(instance.pathEvidence("peer", "1" * 32))["ok"] is False
    assert not instance._sampling


def test_private_sample_cached_timestamp_cannot_borrow_fresh_challenge(private_sampler, monkeypatch):
    instance, module, clock = private_sampler
    cached = json.loads(instance.pathEvidence("peer", "1" * 32))["result"]
    clock["now"] += 3_000_000_000
    def replay(*args, **kwargs):
        return {**cached, "sample_request": kwargs["sample_request"], "sample_sequence": args[2]}
    monkeypatch.setattr(module, "observation", replay)
    assert json.loads(instance.pathEvidence("peer", "2" * 32))["ok"] is False


def test_private_sample_timed_out_inflight_request_cannot_answer_next_call(private_sampler):
    instance, _, clock = private_sampler
    pending = []
    original = instance._submit
    def hold(coroutine, **kwargs):
        pending.append(coroutine)
        raise _HostFailure("native_webrtc_timeout")
    instance._submit = hold
    assert json.loads(instance.pathEvidence("peer", "1" * 32))["error"] == "native_webrtc_timeout"
    assert json.loads(instance.pathEvidence("peer", "2" * 32))["error"] == "native_webrtc_inspection_busy"
    assert len(pending) == 1
    clock["now"] += 2_000_000_001
    with pytest.raises(_HostFailure, match="native_webrtc_inspection_stale"):
        finish_sample(pending[0])
    assert not instance._sampling
    instance._submit = original
    value = json.loads(instance.pathEvidence("peer", "3" * 32))["result"]
    assert value["sample_request"] == "3" * 32 and value["sample_sequence"] == 2


def test_private_sample_foreign_sampling_token_is_never_released(private_sampler, monkeypatch):
    instance, module, _ = private_sampler
    original, foreign = module.observation, object()
    def replace_token(*args, **kwargs):
        value = original(*args, **kwargs)
        instance._sampling["peer"] = foreign
        return value
    monkeypatch.setattr(module, "observation", replace_token)
    assert json.loads(instance.pathEvidence("peer", "1" * 32))["ok"] is False
    assert instance._sampling["peer"] is foreign


@pytest.mark.parametrize("sample_request", [None, True, 1, [], "", "A" * 32, "1" * 31, "1" * 33])
def test_private_sample_invalid_request_never_enters_sampling_custody(private_sampler, sample_request):
    instance, _, _ = private_sampler
    assert json.loads(instance.pathEvidence("peer", sample_request))["ok"] is False
    assert not instance._sampling and instance._sessions["peer"].sample_sequence == 0


ICE = {"iceServers": [], "iceTransportPolicy": "all"}
CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
    {"label": "meshchat-reconnect", "binary": False, "ordered": True},
]


def wait_for(events, predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in list(events.queue):
            if predicate(event):
                return event
        time.sleep(0.02)
    raise AssertionError(f"event not observed: {list(events.queue)}")


def host():
    events = queue.Queue()
    return WindowsNativeWebRTCHost(lambda *event: events.put(event)), events


def establish():
    left, left_events = host()
    right, right_events = host()
    try:
        offer = json.loads(left.createOffer("left", json.dumps(ICE), json.dumps(CHANNELS)))
        assert offer["ok"], offer
        answer = json.loads(right.acceptOffer(
            "right", offer["sdp"], json.dumps(ICE), json.dumps(CHANNELS)))
        assert answer["ok"], answer
        assert json.loads(left.applyAnswer("left", answer["sdp"]))["ok"]
        wait_for(left_events, lambda event: event == ("open", "left", "mesh-reticulum"))
        wait_for(right_events, lambda event: event == ("open", "right", "mesh-reticulum"))
        return (left, left_events), (right, right_events)
    except Exception:
        left.shutdown()
        right.shutdown()
        raise


def test_native_host_exchanges_binary_packets_and_controls():
    (left, left_events), (right, right_events) = establish()
    try:
        packet = bytes(range(256)) * 4 + b"x" * 40
        assert left.send("left", packet)
        assert right.send("right", b"reply")
        assert right.sendControl("right", "mesh-onboarding", "control text")
        wait_for(left_events, lambda event: event[0] == "message"
                 and base64.b64decode(event[2]) == b"reply")
        wait_for(left_events, lambda event: event[0] == "control"
                 and event[2].startswith("mesh-onboarding:")
                 and base64.b64decode(event[2].split(":", 1)[1]) == b"control text")
        wait_for(right_events, lambda event: event[0] == "message"
                 and base64.b64decode(event[2]) == packet)
        stats = json.loads(left.stats("left"))
        assert stats["ok"] and stats["result"]["data_channel_state"] == "open"
        assert stats["result"]["received_packets"] == 1
        assert json.loads(right.stats("right"))["result"]["received_controls"] == 0
        left_path = json.loads(left.pathEvidence("left", "1" * 32))["result"]
        right_path = json.loads(right.pathEvidence("right", "2" * 32))["result"]
        assert left_path["status"] == right_path["status"] == "selected"
        assert left_path["pair"]["local"] == right_path["pair"]["remote"]
        assert left_path["pair"]["remote"] == right_path["pair"]["local"]
        assert left_path["pair"]["relay_protocol"] == "not_applicable"
        assert left_path["application"]["enqueued_bytes"] == len(packet)
        assert left_path["application"]["received_bytes"] == len(b"reply") + len(b"control text")
        assert not left_path["availability"]["pair_bytes"]
        assert left_path["pair"]["bytes_sent"] is None
    finally:
        left.shutdown()
        right.shutdown()


def test_close_is_exact_and_reports_closed_once():
    (left, left_events), (right, _right_events) = establish()
    try:
        left.close("left")
        wait_for(left_events, lambda event: event == ("closed", "left", ""))
        assert json.loads(left.stats("left"))["error"] == "native_webrtc_session_missing"
        assert json.loads(left.pathEvidence("left", "1" * 32))["error"] == "native_webrtc_session_missing"
        deadline = time.monotonic() + 5
        while right.send("right", b"after close") is not False:
            assert time.monotonic() < deadline, "remote session never observed closure"
            time.sleep(0.02)
    finally:
        left.shutdown()
        right.shutdown()


def test_missing_packet_channel_and_oversized_frames_fail_before_allocation():
    host_instance, _ = host()
    try:
        missing = json.loads(host_instance.createOffer(
            "missing", json.dumps(ICE), json.dumps([{"label": "mesh-onboarding"}])))
        assert missing == {"ok": False, "error": "native_webrtc_missing_data_channel"}
        assert host_instance.send("missing", b"x") is False
        assert host_instance.sendControl("missing", "mesh-onboarding", "x" * 65_537) is False
        assert host_instance.send("missing", b"x" * 1065) is False
    finally:
        host_instance.shutdown()


def test_inspection_submission_failure_closes_unscheduled_coroutine_and_releases_only_its_slot(monkeypatch):
    import inspect
    from mesh_chat.native_windows_webrtc import _HostFailure
    instance, _ = host()
    captured = []
    try:
        assert json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        original = instance._submit
        def unavailable(coroutine, **kwargs):
            captured.append(coroutine)
            raise _HostFailure("native_webrtc_unavailable")
        monkeypatch.setattr(instance, "_submit", unavailable)
        assert json.loads(instance.pathEvidence("peer", "1" * 32))["error"] == "native_webrtc_unavailable"
        assert inspect.getcoroutinestate(captured[0]) == inspect.CORO_CLOSED
        assert not instance._sampling
        monkeypatch.setattr(instance, "_submit", original)
        assert json.loads(instance.pathEvidence("peer", "1" * 32))["ok"]
    finally:
        monkeypatch.undo()
        instance.shutdown()


def test_inspection_timeout_retains_slot_until_actual_pending_sample_finishes(monkeypatch):
    from mesh_chat.native_windows_webrtc import _HostFailure
    instance, _ = host()
    captured = []
    try:
        assert json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        original = instance._submit
        def pending(coroutine, **kwargs):
            captured.append(coroutine)
            raise _HostFailure("native_webrtc_timeout")
        monkeypatch.setattr(instance, "_submit", pending)
        assert json.loads(instance.pathEvidence("peer", "1" * 32))["error"] == "native_webrtc_timeout"
        assert json.loads(instance.pathEvidence("peer", "1" * 32))["error"] == "native_webrtc_inspection_busy"
        assert len(captured) == 1
        monkeypatch.setattr(instance, "_submit", original)
        assert json.loads(original(captured[0]))["ok"]
        assert not instance._sampling
        assert json.loads(instance.pathEvidence("peer", "1" * 32))["ok"]
    finally:
        monkeypatch.undo()
        instance.shutdown()


def test_session_capacity_is_bounded():
    host_instance, _ = host()
    try:
        for index in range(16):
            result = json.loads(host_instance.createOffer(
                f"session-{index}", json.dumps(ICE), json.dumps(CHANNELS)))
            if not result["ok"]:
                pytest.fail(result)
        refused = json.loads(host_instance.createOffer(
            "session-overflow", json.dumps(ICE), json.dumps(CHANNELS)))
        assert refused["error"] == "native_webrtc_session_limit"
    finally:
        host_instance.shutdown()


def counts(instance):
    return json.loads(instance.resourceAccounting())["result"]


def test_failed_disposal_keeps_exact_native_capacity_and_closed_notification_until_retry(monkeypatch):
    instance, events = host()
    original = instance._close_session
    try:
        assert json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        async def failed(_): raise OSError("native close acknowledgement failed")
        monkeypatch.setattr(instance, "_close_session", failed)
        with pytest.raises(_HostFailure, match="cleanup_pending"):
            instance.close("peer")
        value = counts(instance)
        assert value["complete"] and value["reserved_count"] == value["retiring_count"] == 1
        assert value["active_count"] == 0 and not instance._sessions
        assert not any(event[0] == "closed" for event in list(events.queue))
        monkeypatch.setattr(instance, "_close_session", original)
        instance.close("peer")
        assert counts(instance)["reserved_count"] == 0
        assert [event for event in list(events.queue) if event[0] == "closed"] == [("closed", "peer", "")]
    finally:
        monkeypatch.setattr(instance, "_close_session", original)
        instance.shutdown()


def test_timed_out_disposal_keeps_one_pending_future_and_consumes_capacity(monkeypatch):
    from mesh_chat import native_windows_webrtc as native
    instance, events = host()
    original = instance._close_session
    release, entered = Event(), Event()
    async def delayed(session):
        entered.set()
        while not release.is_set(): await asyncio.sleep(0.001)
        await original(session)
    try:
        assert json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        monkeypatch.setattr(instance, "_close_session", delayed)
        monkeypatch.setattr(native, "OPERATION_TIMEOUT", 0.02)
        for _ in range(2):
            with pytest.raises(_HostFailure, match="cleanup_pending"):
                instance.close("peer")
        assert entered.is_set() and len(instance._retire_futures) == 1
        assert counts(instance)["retiring_count"] == counts(instance)["reserved_count"] == 1
        assert not any(event[0] == "closed" for event in list(events.queue))
        monkeypatch.setattr(instance, "_close_session", original)
        for index in range(15):
            assert json.loads(instance.createOffer(str(index), json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        assert counts(instance)["reserved_count"] == 16
        assert not json.loads(instance.createOffer("overflow", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        release.set()
        wait_for(events, lambda event: event == ("closed", "peer", ""))
        assert counts(instance)["reserved_count"] == 15
    finally:
        release.set()
        monkeypatch.setattr(instance, "_close_session", original)
        instance.shutdown()


def test_late_cancelled_create_retains_creation_and_physical_lease_until_actual_cleanup(monkeypatch):
    from mesh_chat import native_windows_webrtc as native
    instance, events = host()
    entered, released, cancelled = Event(), Event(), Event()
    original_gather, original_submit = instance._gather, instance._submit
    async def pending(pc):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            while not released.is_set(): await asyncio.sleep(0.001)
        await original_gather(pc)
    result = []
    worker = Thread(target=lambda: result.append(json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))))
    try:
        monkeypatch.setattr(instance, "_gather", pending)
        monkeypatch.setattr(instance, "_submit", lambda coroutine, **_: original_submit(coroutine, timeout=0.05))
        monkeypatch.setattr(native, "OPERATION_TIMEOUT", 0.02)
        worker.start()
        assert entered.wait(3)
        worker.join(3)
        assert not worker.is_alive() and not result[0]["ok"] and cancelled.wait(3)
        value = counts(instance)
        assert value["creating_count"] == value["retiring_count"] == value["reserved_count"] == 1
        with pytest.raises(_HostFailure, match="cleanup_pending"):
            instance.close("peer")
        assert counts(instance)["reserved_count"] == 1
        released.set()
        wait_for(events, lambda event: event == ("closed", "peer", ""))
        deadline = time.monotonic() + 3
        while counts(instance)["reserved_count"] and time.monotonic() < deadline: time.sleep(0.002)
        assert counts(instance)["reserved_count"] == 0
    finally:
        released.set()
        worker.join(3)
        instance.shutdown()


def test_prestart_submit_failure_and_duplicate_cannot_release_another_lease(monkeypatch):
    instance, _ = host()
    original = instance._submit
    try:
        assert json.loads(instance.createOffer("owned", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        assert not json.loads(instance.createOffer("owned", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        def unavailable(coroutine):
            coroutine.close()
            raise _HostFailure("native_webrtc_unavailable")
        monkeypatch.setattr(instance, "_submit", unavailable)
        assert not json.loads(instance.createOffer("unscheduled", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        assert set(instance._leases) == {"owned"}
        assert counts(instance)["reserved_count"] == counts(instance)["active_count"] == 1
    finally:
        monkeypatch.setattr(instance, "_submit", original)
        instance.shutdown()


def test_lost_create_return_after_publish_fences_routing_and_keeps_exact_disposal_custody(monkeypatch):
    instance, events = host()
    original = instance._submit
    try:
        def lost_reply(coroutine):
            assert json.loads(original(coroutine))["ok"]
            raise _HostFailure("native_webrtc_timeout")
        monkeypatch.setattr(instance, "_submit", lost_reply)
        assert not json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        assert "peer" not in instance._sessions
        assert json.loads(instance.stats("peer"))["error"] == "native_webrtc_session_missing"
        assert not instance.send("peer", b"after-unknown-create")
        assert not instance.sendControl("peer", "mesh-onboarding", "after-unknown-create")
        value = counts(instance)
        assert value["reserved_count"] == value["retiring_count"] == value["allocated_count"] == 1
        assert value["active_count"] == 0 and not any(event[0] == "closed" for event in list(events.queue))
        instance.close("peer")
        assert counts(instance)["reserved_count"] == 0
        assert [event for event in list(events.queue) if event[0] == "closed"] == [("closed", "peer", "")]
    finally:
        monkeypatch.setattr(instance, "_submit", original)
        instance.shutdown()


def test_failed_shutdown_keeps_native_loop_and_exact_retirement_available_for_retry(monkeypatch):
    instance, _ = host()
    original = instance._close_session
    try:
        assert json.loads(instance.createOffer("peer", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        async def failed(_): raise OSError("native close did not finish")
        monkeypatch.setattr(instance, "_close_session", failed)
        with pytest.raises(_HostFailure, match="cleanup_pending"):
            instance.shutdown()
        assert instance._thread.is_alive() and counts(instance)["retiring_count"] == 1
        assert not json.loads(instance.createOffer("replacement", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        monkeypatch.setattr(instance, "_close_session", original)
        instance.shutdown()
        assert not instance._thread.is_alive() and counts(instance)["reserved_count"] == 0
    finally:
        monkeypatch.setattr(instance, "_close_session", original)
        instance.shutdown()


def test_queued_creation_cancelled_before_first_task_step_acknowledges_without_leaking_capacity(monkeypatch):
    from mesh_chat import native_windows_webrtc as native
    instance, _ = host()
    blocked, release = Event(), Event()
    original_submit, original_pc = instance._submit, native.RTCPeerConnection
    allocated, result = [], []
    def block_loop():
        blocked.set()
        assert release.wait(3)
    def peer(*args, **kwargs):
        allocated.append(True)
        return original_pc(*args, **kwargs)
    worker = Thread(target=lambda: result.append(json.loads(instance.createOffer("queued", json.dumps(ICE), json.dumps(CHANNELS)))))
    try:
        monkeypatch.setattr(native, "RTCPeerConnection", peer)
        monkeypatch.setattr(native, "OPERATION_TIMEOUT", 0.02)
        monkeypatch.setattr(instance, "_submit", lambda coroutine, **_: original_submit(coroutine, timeout=0.03))
        instance._loop.call_soon_threadsafe(block_loop)
        assert blocked.wait(3)
        worker.start()
        worker.join(3)
        assert not worker.is_alive() and not result[0]["ok"]
        lease = instance._leases["queued"]
        assert not lease.started and counts(instance)["creating_count"] == 1
        with pytest.raises(_HostFailure, match="cleanup_pending"):
            instance.close("queued")
        assert counts(instance)["reserved_count"] == 1 and not allocated
        release.set()
        deadline = time.monotonic() + 3
        while counts(instance)["reserved_count"] and time.monotonic() < deadline: time.sleep(0.002)
        assert counts(instance)["reserved_count"] == 0
        assert lease.created.is_set() and not lease.started and not allocated
        instance.close("queued")
        instance.shutdown()
        assert not instance._thread.is_alive()
    finally:
        release.set()
        worker.join(3)
        instance.shutdown()


def test_late_old_creation_checks_exact_registered_lease_before_allocating_or_detaching_replacement():
    instance, _ = host()
    try:
        old = instance._reserve("reused")
        old.creating, old.cancelled = False, True
        instance._release_finished(old)
        assert json.loads(instance.createOffer("reused", json.dumps(ICE), json.dumps(CHANNELS)))["ok"]
        current = instance._leases["reused"]
        with pytest.raises(_HostFailure):
            instance._submit(instance._open_session(old, json.dumps(ICE), [("mesh-reticulum", True, True)]))
        assert instance._leases["reused"] is current
        assert instance._sessions["reused"] is current.session
        assert counts(instance)["reserved_count"] == counts(instance)["active_count"] == 1
    finally:
        instance.shutdown()


@pytest.mark.parametrize("phase", ["offer-created", "accepted", "answer-applied"])
def test_cancellation_at_each_handshake_phase_retires_exactly_that_session(phase):
    left, left_events = host()
    right, right_events = host()
    try:
        offer = json.loads(left.createOffer("left", json.dumps(ICE), json.dumps(CHANNELS)))
        assert offer["ok"], offer
        if phase in {"accepted", "answer-applied"}:
            answer = json.loads(right.acceptOffer(
                "right", offer["sdp"], json.dumps(ICE), json.dumps(CHANNELS)))
            assert answer["ok"], answer
        if phase == "answer-applied":
            assert json.loads(left.applyAnswer("left", answer["sdp"]))["ok"]

        left.close("left")
        if phase != "offer-created":
            right.close("right")
        for instance, session in ((left, "left"), (right, "right")):
            if phase == "offer-created" and instance is right:
                continue
            assert json.loads(instance.stats(session))["error"] == "native_webrtc_session_missing"

        replacement = json.loads(left.createOffer(
            "replacement", json.dumps(ICE), json.dumps(CHANNELS)))
        assert replacement["ok"], replacement
        left.close("replacement")
        assert json.loads(left.stats("replacement"))["error"] == "native_webrtc_session_missing"
    finally:
        left.shutdown()
        right.shutdown()


def test_shutdown_retires_live_sessions_and_refuses_further_work():
    host_instance, events = host()
    for index in range(3):
        created = json.loads(host_instance.createOffer(
            f"live-{index}", json.dumps(ICE), json.dumps(CHANNELS)))
        assert created["ok"], created
    host_instance.shutdown()
    for index in range(3):
        assert json.loads(host_instance.stats(f"live-{index}"))["error"] == (
            "native_webrtc_session_missing")
    assert host_instance.send("live-0", b"after shutdown") is False
    assert host_instance.sendControl("live-0", "mesh-onboarding", "after shutdown") is False
    host_instance.shutdown()


def test_relay_only_offer_has_no_direct_candidates_without_turn():
    host_instance, events = host()
    ice = json.dumps({"iceServers": [], "iceTransportPolicy": "relay"})
    try:
        created = json.loads(host_instance.createOffer("relay", ice, json.dumps(CHANNELS)))
        assert created["ok"], created
        candidates = [
            line for line in created["sdp"].splitlines()
            if line.startswith("a=candidate:")
        ]
        assert all(" typ relay" in line for line in candidates), candidates
    finally:
        host_instance.shutdown()


def test_relay_only_answer_filters_direct_candidates():
    left, left_events = host()
    right, right_events = host()
    ice = json.dumps({"iceServers": [], "iceTransportPolicy": "relay"})
    try:
        offer = json.loads(left.createOffer("offer", json.dumps(ICE), json.dumps(CHANNELS)))
        assert offer["ok"], offer
        answer = json.loads(right.acceptOffer(
            "answer", offer["sdp"], ice, json.dumps(CHANNELS)))
        assert answer["ok"], answer
        candidates = [
            line for line in answer["sdp"].splitlines()
            if line.startswith("a=candidate:")
        ]
        assert all(" typ relay" in line for line in candidates), candidates
    finally:
        left.shutdown()
        right.shutdown()
