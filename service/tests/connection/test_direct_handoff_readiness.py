"""Required handoff checks for main RNS acceptance and bounded confirmation."""
import threading
import time
from types import SimpleNamespace

import RNS
import pytest

from mesh_chat import direct_handoff
from mesh_chat.direct_admitted_carrier import AdmittedCarrier
from mesh_chat.direct_handoff import AdmissionHandoff


def test_native_sighting_and_bootstrap_keys_cannot_confirm_main_path(monkeypatch):
    carrier = object.__new__(AdmittedCarrier)
    carrier.peer_seen = threading.Event()
    carrier.peer_seen.set()
    carrier._stop = threading.Event()
    carrier._peer = b"p" * 16
    carrier._interface = object()
    state = {"main_keys": False, "path": carrier._interface}
    carrier.service = SimpleNamespace(network=SimpleNamespace(
        recipient_ready=lambda _peer: True,  # Isolated bootstrap is ready.
        _main_recipient_ready=lambda _peer: state["main_keys"],
        path_known=lambda _peer: True,
    ))
    monkeypatch.setattr(RNS.Transport, "next_hop_interface", lambda _peer: state["path"])

    assert carrier.main_rns_ready() is False
    state["main_keys"] = True
    state["path"] = object()
    assert carrier.main_rns_ready() is False
    assert carrier.main_rns_ready(require_selected_path=False) is True
    state["path"] = carrier._interface
    assert carrier.main_rns_ready() is True


def test_initial_admitted_carrier_keeps_announcing_for_other_handoff():
    carrier = object.__new__(AdmittedCarrier)
    carrier.recovery = False
    carrier._announce_until = 130
    assert carrier._announce_active(129) is True
    assert carrier._announce_active(130) is False
    carrier.recovery = True
    assert carrier._announce_active(130) is True


@pytest.mark.parametrize("ready_duration", [0, 1])
def test_handoff_rejects_readiness_at_or_after_deadline(monkeypatch, ready_duration):
    clock = [10 if ready_duration == 0 else 9.5]
    monkeypatch.setattr(direct_handoff.time, "monotonic", lambda: clock[0])
    def ready():
        clock[0] += ready_duration
        return True
    carrier = SimpleNamespace(_stop=threading.Event(), main_rns_ready=ready)
    handoff = object.__new__(AdmissionHandoff)
    assert handoff._await_main_ready(carrier, deadline=10) is False


def test_handoff_keeps_announcing_until_main_acceptance_or_existing_deadline():
    state = {"ready": False, "announces": 0, "refreshes": 0, "waits": 0}

    class Stop:
        def is_set(self): return False
        def wait(self, _duration):
            state["waits"] += 1
            if state["waits"] == 2:
                state["ready"] = True

    carrier = SimpleNamespace(_stop=Stop(), main_rns_ready=lambda: state["ready"],
        refresh_path=lambda: state.__setitem__("refreshes", state["refreshes"] + 1))
    network = SimpleNamespace(destination_hash=b"l" * 16,
        router=SimpleNamespace(announce=lambda _hash: state.__setitem__("announces", state["announces"] + 1)))
    handoff = object.__new__(AdmissionHandoff)
    handoff.service = SimpleNamespace(network=network)

    assert handoff._await_main_ready(carrier, deadline=float("inf"), announce_interval=0) is True
    assert state["announces"] >= 1 and state["refreshes"] >= 1
    state["ready"] = False
    assert handoff._await_main_ready(carrier, deadline=0, announce_interval=0) is False


@pytest.mark.parametrize("main_ready", [False, True])
def test_signed_native_sighting_alone_cannot_commit_handoff(monkeypatch, main_ready):
    events = []
    accepted = SimpleNamespace(digest="accepted")
    prepared = SimpleNamespace(handle=7, close=lambda: events.append("prepared_closed"),
        document_fields=lambda: {})
    fields = {"session_id": "session", "generation": 1, "expires_at": int(time.time()) + 60,
        "candidates": []}
    authority = SimpleNamespace(stage="admission_handoff", transition_deadline=time.monotonic() + .15,
        workspace_id="00000000-0000-4000-8000-000000000001", peer_identity=b"p", check=lambda: None,
        admitted_authority=lambda: SimpleNamespace())
    bootstrap = SimpleNamespace(_stop=threading.Event(), ready=True, peer=b"p" * 16,
        send=lambda **_kwargs: events.append("bootstrap_send"),
        close=lambda: events.append("bootstrap_closed"))
    network = SimpleNamespace(destination_hash=b"l" * 16,
        router=SimpleNamespace(announce=lambda _hash: events.append("announce")))
    native = SimpleNamespace(request=lambda operation, **_kwargs: (
        {"state": 1, "packets": []} if operation == "poll" else None))
    service = SimpleNamespace(_dispatch_lock=threading.RLock(), network=network,
        _identity=object(),
        _direct_native=native, _accept_direct_workspace_binding=lambda *_: accepted,
        _direct_recovery=SimpleNamespace(adopt=lambda *_: events.append("adopt")),
        _check_direct_runtime_available=lambda: None,
        _direct_workspace_binding_authority=lambda expected: expected, store=object())
    state = {"ready": main_ready}

    class FakeAdmitted:
        def __init__(self, *_args, **_kwargs):
            self._stop = threading.Event()
            self.peer_seen = threading.Event()
        def start(self):
            self.peer_seen.set()  # The native boundary saw a signed announce.
            events.append("signed_native_announce")
        def main_rns_ready(self): return state["ready"]
        def refresh_path(self): events.append("refresh_path")
        def close(self):
            self._stop.set()
            if "admitted_closed" not in events: events.append("admitted_closed")

    monkeypatch.setattr(direct_handoff, "AdmittedCarrier", FakeAdmitted)
    monkeypatch.setattr(direct_handoff.direct_admission, "decode", lambda _doc: ("peer binding", b"cert"))
    monkeypatch.setattr(direct_handoff, "native_parameters", lambda *_args, **_kwargs: {"remaining_ms": 60_000})
    from mesh_chat import direct_relationship
    monkeypatch.setattr(direct_relationship, "record_success", lambda *_args, **_kwargs: events.append("success"))
    handoff = AdmissionHandoff(service, authority, lambda _carrier, stage: events.append(stage))
    handoff.carrier = bootstrap
    handoff._remote = "remote document"
    monkeypatch.setattr(handoff, "_prepare", lambda: (prepared, fields, "our document"))

    handoff._run()
    assert "signed_native_announce" in events
    if main_ready:
        assert "success" in events and "adopt" in events
        assert "admitted_closed" not in events
    else:
        assert "success" not in events and "adopt" not in events
        assert "admitted_closed" in events
    assert "bootstrap_closed" in events
