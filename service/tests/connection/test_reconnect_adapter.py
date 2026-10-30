from dataclasses import replace
from threading import Event

import pytest

from mesh_chat.connection.adapters.reconnect import NativePort, ReconnectExecutor, SignalingPort
from mesh_chat.connection.model import (
    Authority, Bridge, Carrier, ConnectionKey, ConnectionState, Desired, Failed, Health, Phase, Resource,
    Tick, Work,
)
from mesh_chat.connection.reducer import transition


class Domain:
    def __init__(self, preferred):
        self.preferred = preferred
        self.documents = {}
        self.calls = []
        self.created = 0
        self.valid = True
        self.profile = {"id": "p", "contact_id": "c", "active": True,
                        "effective": {"ready": True, "preferred": preferred}}

    def request(self, contact, attempt):
        self.created += 1
        self.attempt = attempt
        return {"document": "request", "attempt_id": attempt, "expires_at": 1000}

    def offer(self, *args):
        return {"document": "offer", "attempt_id": "peer-attempt", "sdp": "offer-sdp"}

    def answer(self, *args):
        return {"document": "answer"}

    def verify_request(self, *args):
        return {"attempt_id": "peer-attempt"}

    def verify_offer(self, *args):
        return {"attempt_id": self.attempt, "sdp": "offer-sdp"}

    def verify_answer(self, *args):
        return {"sdp": "answer-sdp"}

    def publish(self, *args):
        self.calls.append(args[-1])

    def fetch(self, profile, role):
        return {"document": role}

    def native_offer(self, session, ice, channels, profile):
        self.calls.append("native_offer")
        self.ice = ice
        return {"sdp": "offer-sdp", "fingerprint": "fingerprint"}

    def native_accept(self, session, sdp, ice, channels, profile):
        self.calls.append("native_accept")
        self.ice = ice
        return {"sdp": "answer-sdp", "fingerprint": "fingerprint"}

    def executor(self, state):
        signaling = SignalingPort(self.request, self.offer, self.answer, self.verify_request,
                                  self.verify_offer, self.verify_answer, self.publish, self.fetch)
        native = NativePort(self.native_offer, self.native_accept,
                            lambda *_: self.calls.append("apply_answer"),
                            lambda _: {"data_channel_state": "open", "ice_connection_state": "connected"},
                            lambda _: self.calls.append("attach"),
                            lambda _: self.calls.append("close"))
        return ReconnectExecutor(signaling, native, profile=lambda _: self.profile,
                    ice=lambda: {"iceServers": [], "iceTransportPolicy": "all"},
                    path=lambda _: {"has_path": True, "ready": True},
                    current=lambda _: self.valid, now=lambda: 1, wall_time=lambda: 100)


def initial(preferred=True):
    return ConnectionState(ConnectionKey("personal", "p", "l", "r"), "e",
                           Authority(1, True, True, preferred), Desired.ENABLED)


@pytest.mark.parametrize("preferred", [True, False])
def test_production_reducer_drives_both_protocol_roles(preferred):
    domain = Domain(preferred)
    state = initial(preferred)
    executor = domain.executor(state)
    result = transition(state, Tick(0))
    for _ in range(12):
        state = result.state
        if not result.effects:
            break
        work = result.effects[0]
        assert isinstance(work, Work)
        event = executor.execute(work, Event())
        assert not isinstance(event, Failed)
        result = transition(state, event)
    assert result.state.carrier.bridge is Bridge.READY
    assert domain.ice["iceTransportPolicy"] == "relay"
    assert domain.calls == (["request", "native_accept", "answer", "attach"] if preferred
                             else ["native_offer", "offer", "apply_answer", "attach"])


def test_valid_signed_request_is_reused_across_local_attempts():
    domain = Domain(True)
    state = initial()
    executor = domain.executor(state)
    first = transition(state, Tick(0)).effects[0]
    executor.execute(first, Event())
    executor.retire(first.resource)
    second = transition(replace(state, generation=1), Tick(0)).effects[0]
    executor.execute(second, Event())
    assert domain.created == 1


def test_late_native_creation_reports_exact_handle_for_cleanup():
    domain = Domain(True)
    state = initial()
    executor = domain.executor(state)
    result = transition(state, Tick(0))
    for _ in range(2):
        work = result.effects[0]
        result = transition(result.state, executor.execute(work, Event()))
    work = result.effects[0]
    assert work.phase is Phase.GATHER_ANSWER
    def late(*args):
        domain.valid = False
        return {"sdp": "answer", "fingerprint": "fingerprint"}
    executor.native = replace(executor.native, accept=late)
    event = executor.execute(work, Event())
    assert isinstance(event, Failed)
    assert event.allocated == work.resource


def test_missing_path_never_claims_messaging_ready():
    domain = Domain(True)
    state = initial()
    executor = domain.executor(state)
    executor.path = lambda _: {"has_path": True, "ready": False}
    result = transition(state, Tick(0))
    for _ in range(10):
        if not result.effects:
            break
        result = transition(result.state, executor.execute(result.effects[0], Event()))
    assert result.state.carrier.bridge is Bridge.PATH_PENDING
    assert result.state.negotiation.phase is Phase.PATH


def test_inspection_checks_current_path_and_channel_not_just_ice():
    domain = Domain(True)
    resource = Resource("adapter", "carrier")
    state = replace(initial(), carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 0))
    executor = domain.executor(state)
    work = transition(state, Tick(0)).effects[0]
    executor.native = replace(executor.native, stats=lambda _: {
        "attached": True, "ice_connection_state": "connected", "data_channel_state": "open"})
    executor.path = lambda _: {"has_path": False, "ready": False}
    event = executor.execute(work, Event())
    assert event.observed_health is Health.OPEN
    assert event.observed_bridge is Bridge.PATH_PENDING
    executor.native = replace(executor.native, stats=lambda _: {
        "attached": True, "ice_connection_state": "connected", "data_channel_state": "closed"})
    assert executor.execute(work, Event()).observed_health is Health.ABSENT
