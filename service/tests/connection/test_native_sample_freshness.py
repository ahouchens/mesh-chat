"""Actual Windows/service/controller composition; native ICE and time are modeled.

No sockets, packaged executable, Android callback, OS authentication or peer
delivery is qualified here. The fixture starts with an adopted component carrier;
it does not claim to exercise pairing or bridge creation.
"""
import json
import inspect
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
from native_interop_evidence import Samples
from mesh_chat import native_webrtc_service, native_windows_webrtc
from mesh_chat.connection.model import (
    Authority, Bridge, Carrier, ConnectionKey, ConnectionState, Desired, Health, Resource,
)
from mesh_chat.core_api.qualification_host import QualificationControl
from mesh_chat.errors import ContactNotApproved, NativeUnavailable
from test_native_profile_lifecycle import profile_runtime


@pytest.fixture
def composition(profile_runtime, monkeypatch):
    create, _ = profile_runtime
    service = create()
    service.create_profile("Synthetic sample composition")
    state = SimpleNamespace(native_now=7001.0, service_now=9001.0, controller_now=31.0,
                            requests=[], raw=[], returned=[], during_sample=None, after_native=None)
    monkeypatch.setattr(native_windows_webrtc, "time", SimpleNamespace(
        monotonic=lambda: state.native_now, monotonic_ns=lambda: int(state.native_now * 1_000_000_000)))
    monkeypatch.setattr(native_webrtc_service, "time", SimpleNamespace(monotonic=lambda: state.service_now))
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.controller_now))
    host = native_windows_webrtc.WindowsNativeWebRTCHost(lambda *_: None)
    logical = "sample-carrier"
    physical = service._native_resources.reserve(logical)
    service._native_webrtc_live.add(logical)
    service._native_host = host

    async def close_pc():
        pass

    def candidate(port):
        return SimpleNamespace(host="127.0.0.1", port=port, type="host", transport="udp")

    pair = SimpleNamespace(nominated=True, state=SimpleNamespace(name="SUCCEEDED"),
                           local_candidate=candidate(1234), remote_candidate=candidate(4321))
    dtls = SimpleNamespace(state="connected", transport=SimpleNamespace(
        _connection=SimpleNamespace(_nominated={1: pair})))
    pc = SimpleNamespace(iceConnectionState="completed", sctp=SimpleNamespace(transport=dtls), close=close_pc)
    session = native_windows_webrtc._Session(physical, pc)
    channel = SimpleNamespace(readyState="open", close=lambda: None)
    session.channels["mesh-reticulum"] = channel
    lease = host._reserve(physical)
    lease.creating, lease.started, lease.session = False, True, session
    lease.created.set()
    host._publish(lease, session)

    # Explicit initial adoption/attachment inputs. Readiness and authority are
    # computed by the actual runtime, service and Samples, never patched results.
    runtime = service._connection_runtime
    key = ConnectionKey("contact", "sample-profile", "local", "remote")
    runtime.owner.register(ConnectionState(key, service._runtime_incarnation, Authority(1, True, True, True),
        Desired.ENABLED, carrier=Carrier(Resource("native", physical), 1, Health.OPEN, Bridge.READY, 0)))
    runtime._profile_keys[key.profile_id] = {key}
    runtime._profile_values[key] = {"id": key.profile_id, "contact_id": "sample-contact"}
    service._native_webrtc_profile_sessions[key.profile_id] = logical
    bridge = SimpleNamespace(online=True)
    service._native_webrtc_sessions[logical] = "sample-bridge"
    service._webrtc_bridges["sample-bridge"] = bridge
    service.network = object()
    monkeypatch.setattr(RNS.Transport, "interfaces", [*RNS.Transport.interfaces, bridge])

    selected_pair = host._selected_pair

    def select(*args):
        result = selected_pair(*args)
        if state.during_sample is not None:
            state.during_sample()
        return result

    monkeypatch.setattr(host, "_selected_pair", select)
    native_path = host.pathEvidence

    def sample(*args):
        raw = native_path(*args)
        state.raw.append(raw)
        if state.after_native is not None:
            state.after_native()
        return raw

    monkeypatch.setattr(host, "pathEvidence", sample)
    port = QualificationControl(lambda: service)

    class Peer:
        def inventory(self):
            return port.dispatch("qualification.inventory", {})

        def path(self, logical_session, expected_physical, sample_request):
            payload = {"logical_session": logical_session, "expected_physical": expected_physical,
                       "sample_request": sample_request}
            state.requests.append(dict(payload))
            value = port.dispatch("qualification.path_evidence", payload)
            state.returned.append(value)
            return value

    observer = controller.Controller("windows", Peer(), None, None, {})
    observer.samples = Samples(monotonic=lambda: state.controller_now)
    state.service, state.host, state.port = service, host, port
    state.observer, state.session, state.logical, state.physical = observer, session, logical, physical
    try:
        yield state
    finally:
        service.network = None
        service._webrtc_bridges.clear()
        service._native_webrtc_sessions.clear()
        host.shutdown()


def test_first_actual_observation_uses_request_custody_not_another_clock_epoch(composition):
    state = composition
    value = state.observer.observe(state.logical, scenario="direct")
    assert value["sampled_at_ms"] == 7_001_000
    assert value["sample_elapsed_ms"] == 0
    assert value["adopted"] and value["attached"] and value["messaging_ready"]
    request = state.requests[0]["sample_request"]
    assert re.fullmatch(r"[0-9a-f]{32}", request)
    assert value["sample_request"] == json.loads(state.raw[0])["result"]["sample_request"] == request
    assert value["sample_sequence"] == 1
    assert state.observer.samples.previous
    second = state.observer.observe(state.logical, scenario="direct")
    assert second["sample_sequence"] == 2
    assert second["sample_request"] != request
    assert state.requests[1]["sample_request"] == second["sample_request"]
    assert len(state.raw) == len(state.requests) == 2  # No extra sample or RPC.


@pytest.mark.parametrize("replay", ["first", "after_success", "foreign_echo", "missing_echo"])
def test_cached_or_foreign_raw_observation_cannot_acquire_a_new_request(composition, monkeypatch, replay):
    state = composition
    if replay == "after_success":
        state.observer.observe(state.logical, scenario="direct")
    else:
        state.host.pathEvidence(state.physical, "a" * 32)
    cached = state.raw[-1]
    if replay in {"foreign_echo", "missing_echo"}:
        envelope = json.loads(cached)
        if replay == "foreign_echo":
            envelope["result"]["sample_request"] = "b" * 32
        else:
            del envelope["result"]["sample_request"]
        cached = json.dumps(envelope)
    state.native_now += 3
    monkeypatch.setattr(state.host, "pathEvidence", lambda *_: cached)
    before = len(state.returned)
    with pytest.raises(NativeUnavailable):
        state.observer.observe(state.logical, scenario="direct")
    assert len(state.returned) == before  # Rejected by service before consumer.
    assert len(state.raw) == 1  # No wrapper resampling or retimestamping.


@pytest.mark.parametrize("elapsed", [-0.001, 2.001])
def test_original_sampling_window_cannot_be_hidden_by_a_fresh_end_timestamp(composition, elapsed):
    state = composition
    state.during_sample = lambda: setattr(state, "native_now", state.native_now + elapsed)
    with pytest.raises(NativeUnavailable):
        state.observer.observe(state.logical, scenario="direct")
    assert json.loads(state.raw[-1])["ok"] is False
    assert not state.returned and not state.observer.samples.previous


@pytest.mark.parametrize("clock", ["service_now", "controller_now"])
def test_late_response_in_either_local_budget_does_not_qualify(composition, clock):
    state = composition
    state.after_native = lambda: setattr(state, clock, getattr(state, clock) + 2.001)
    with pytest.raises((NativeUnavailable, ValueError)):
        state.observer.observe(state.logical, scenario="direct")
    assert json.loads(state.raw[-1])["ok"] is True  # Native sample itself was prompt.
    assert not state.observer.samples.previous
    if clock == "controller_now":
        assert len(state.returned) == 1  # Actual service accepted; real Samples denied RTT.


def test_timeout_keeps_original_sample_custody_until_late_completion(composition, monkeypatch):
    state = composition
    submit = state.host._submit
    pending = []

    def timeout(coroutine, **kwargs):
        pending.append(coroutine)
        raise native_windows_webrtc._HostFailure("native_webrtc_timeout")

    try:
        monkeypatch.setattr(state.host, "_submit", timeout)
        with pytest.raises(NativeUnavailable):
            state.observer.observe(state.logical, scenario="direct")
        with pytest.raises(NativeUnavailable):
            state.observer.observe(state.logical, scenario="direct")
        assert len(pending) == 1 and state.host._sampling
        assert state.requests[0]["sample_request"] != state.requests[1]["sample_request"]
        state.native_now += 2.001
        monkeypatch.setattr(state.host, "_submit", submit)
        try:
            late = submit(pending[0])
        except native_windows_webrtc._HostFailure:
            pass
        else:
            assert json.loads(late)["ok"] is False
        assert not state.host._sampling and not state.returned
        assert not state.observer.samples.previous
        assert state.observer.observe(state.logical, scenario="direct")["sample_sequence"] > 0
    finally:
        monkeypatch.setattr(state.host, "_submit", submit)
        for coroutine in pending:
            if inspect.getcoroutinestate(coroutine) == inspect.CORO_CREATED:
                coroutine.close()


@pytest.mark.parametrize("change", ["resource", "native_closed", "host", "service", "profile", "authority"])
def test_inflight_currentness_and_authority_are_checked_after_actual_sampling(composition, change):
    state = composition
    service = state.service

    def replace():
        if change == "resource":
            service._native_resources.release(state.logical, state.physical)
        elif change == "native_closed":
            state.session.closed = True
        elif change == "host":
            service._native_host = SimpleNamespace(close=lambda _: None)
        elif change == "service":
            service._runtime_incarnation = uuid4().hex
        elif change == "profile":
            service._identity = RNS.Identity()
        else:
            service._connection_runtime.begin_authority_change("sample-contact")

    state.during_sample = replace
    with pytest.raises(ContactNotApproved if change == "authority" else NativeUnavailable):
        state.observer.observe(state.logical, scenario="direct")
    assert len(state.raw) == 1 and not state.returned
    assert not state.observer.samples.previous


@pytest.mark.parametrize("change", ["adapter_epoch", "sample_sequence"])
def test_epoch_or_sequence_reset_cannot_requalify_a_live_resource(composition, change):
    state = composition
    state.observer.observe(state.logical, scenario="direct")
    if change == "adapter_epoch":
        state.host._adapter_epoch = uuid4().hex
    else:
        state.session.sample_sequence = 0
    with pytest.raises(NativeUnavailable):
        state.observer.observe(state.logical, scenario="direct")
    assert len(state.returned) == 1


def test_selected_ice_cannot_replace_actual_service_messaging_readiness(composition):
    state = composition
    bridge = state.service._webrtc_bridges["sample-bridge"]
    state.during_sample = lambda: setattr(bridge, "online", False)
    assert state.observer.observe(state.logical, scenario="direct") is None
    assert state.returned[-1]["status"] == "selected"
    assert not state.returned[-1]["attached"] and not state.returned[-1]["messaging_ready"]
    assert not state.observer.samples.previous
