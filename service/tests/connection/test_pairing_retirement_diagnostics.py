"""Bounded private causal observations; injected native/mailbox, no platform proof."""
from dataclasses import replace
import base64
import json
import os
import socket
from threading import Event
from time import monotonic
import urllib.request
from uuid import uuid4

import pytest

from mesh_chat.connection.diagnostics import (
    PAIRING_RETIREMENT_EVENTS, PAIRING_RETIREMENT_PHASES, PAIRING_RETIREMENT_REASONS,
    gather_failure_at_deadline, validated_gather_failure, validated_pairing_retirement,
)
from mesh_chat.connection.model import (
    Adopted, Authority, ConnectionKey, ConnectionState, ContextChanged, Desired,
    Execution, Failed, Failure, Phase, Policy, Resource, Result, Tick, Work,
)
from mesh_chat.connection.supervisor import CapacityExceeded, ConnectionSupervisor
from mesh_chat.core_api import qualification_host as private
from mesh_chat.call_manager import CallOutcomeRequiresResync
from mesh_chat.errors import ValidationError
from test_pairing_runtime import native_pairing, run_until

UNKNOWN = {"phase": "unknown", "event": "unknown", "reason": "unknown"}
GATHER = {"as_of": "phase_deadline", "worker": "started", "stage": "native_accept",
          "stage_state": "entered", "last_completed": "ice_config", "queue_age": "lt1s",
          "stage_age": "20to25s"}


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Diagnostic component test attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    yield
    assert not attempts


@pytest.mark.parametrize("value", [
    None, [], "private-error", {}, {"phase": "discover"},
    {**UNKNOWN, "identity": "PRIVATE_ID"}, {**UNKNOWN, "resource": "PRIVATE_RESOURCE"},
    {**UNKNOWN, "phase": "PRIVATE_SDP"}, {**UNKNOWN, "event": "acceptOffer failed"},
    {**UNKNOWN, "reason": "PRIVATE_KEY"}, {**UNKNOWN, "reason": None},
    {**UNKNOWN, "phase": Phase.DISCOVER}, {**UNKNOWN, "event": False},
    {**UNKNOWN, "reason": ["ineligible"]},
])
def test_sanitizer_rejects_nonliteral_or_extra_fields(value):
    assert validated_pairing_retirement(value) is None


def test_sanitizer_selects_exact_literals_and_returns_a_copy():
    value = {"phase": "gather_answer", "event": "failed", "reason": "invalid_document"}
    assert validated_pairing_retirement(value) == value
    assert validated_pairing_retirement(value) is not value
    assert validated_pairing_retirement(UNKNOWN) == UNKNOWN
    for phase in PAIRING_RETIREMENT_PHASES:
        for event in PAIRING_RETIREMENT_EVENTS:
            for reason in PAIRING_RETIREMENT_REASONS:
                dto = {"phase": phase, "event": event, "reason": reason}
                assert validated_pairing_retirement(dto) == dto
                assert len(json.dumps(dto).encode()) < 512


@pytest.mark.parametrize("bad", [None, {}, {**GATHER, "sdp": "PRIVATE_SDP"},
    {**GATHER, "stage": "PRIVATE_NATIVE_ERROR"}, {**GATHER, "stage_age": 21.0},
    {**GATHER, "worker": ["started"]}])
def test_gather_failure_validator_is_exact_and_payload_free(bad):
    assert validated_gather_failure(bad) is None
    assert validated_gather_failure(GATHER) == GATHER
    assert validated_gather_failure(GATHER) is not GATHER


def test_deadline_selection_excludes_late_stage_and_worker_completion():
    worker = (("queued", 10.0), ("started", 10.2), ("completed", 36.0))
    stages = (("ice_config", "entered", 10.4), ("ice_config", "completed", 10.5),
              ("native_accept", "entered", 11.0), ("native_accept", "completed", 35.1),
              ("answer_sign", "entered", 35.2))
    observed = gather_failure_at_deadline(35.0, worker, stages)
    assert observed == {"as_of": "phase_deadline", "worker": "started", "stage": "native_accept",
        "stage_state": "entered", "last_completed": "ice_config", "queue_age": "lt1s",
        "stage_age": "20to25s"}
    assert gather_failure_at_deadline(35.0, (("queued", 10.0),), ()) == {
        "as_of": "phase_deadline", "worker": "queued", "stage": "not_started",
        "stage_state": "unknown", "last_completed": "none", "queue_age": "gte25s",
        "stage_age": "unknown"}
    assert gather_failure_at_deadline(35.0, (("queued", 12.0), ("started", 11.0)), ())[
        "worker"] == "unknown"
    completed = gather_failure_at_deadline(35.0,
        (("queued", 10.0), ("started", 12.0), ("completed", 15.0)),
        (("ice_config", "entered", 12.1), ("ice_config", "completed", 13.0),
         ("native_accept", "entered", 13.1), ("native_accept", "completed", 14.0),
         ("answer_sign", "entered", 14.1), ("answer_sign", "completed", 14.2),
         ("bind_onboarding", "entered", 14.3), ("bind_onboarding", "completed", 14.4),
         ("complete", "completed", 14.5)))
    assert (completed["worker"], completed["stage"], completed["last_completed"],
            completed["queue_age"]) == ("completed", "complete", "bind_onboarding", "1to5s")


def test_missing_stage_entry_never_reuses_previous_stage_age():
    observed = gather_failure_at_deadline(35.0, (("queued", 10.0), ("started", 10.1)), (
        ("ice_config", "entered", 10.2), ("ice_config", "completed", 10.3),
        ("native_accept", "completed", 15.0)))
    assert observed["stage"] == "native_accept" and observed["stage_state"] == "completed"
    assert observed["stage_age"] == "unknown"
    assert gather_failure_at_deadline(35.0, (("queued", float("nan")),), None)["worker"] == "unknown"
    assert gather_failure_at_deadline(35.0, (("queued", 10.0),), None)["stage"] == "unknown"
    started_empty = gather_failure_at_deadline(35.0, (("queued", 10.0), ("started", 11.0)), ())
    assert (started_empty["stage"], started_empty["last_completed"]) == ("unknown", "unknown")
    malformed = gather_failure_at_deadline(35.0, (("queued", 10.0), ("started", 11.0)), (
        ("native_accept", "entered", 12.0), ("ice_config", "completed", 13.0)))
    assert (malformed["stage"], malformed["stage_age"]) == ("unknown", "unknown")
    no_ice_marker = gather_failure_at_deadline(35.0, (("queued", 10.0), ("started", 11.0)), (
        ("native_accept", "entered", 12.0),))
    assert no_ice_marker["stage"] == "native_accept" and no_ice_marker["last_completed"] == "unknown"
    invalid_start = gather_failure_at_deadline(35.0, (("queued", 10.0), ("invalid", 0.0)), ())
    assert invalid_start["worker"] == "unknown" and invalid_start["stage"] == "unknown"
    late_observer_error = gather_failure_at_deadline(35.0,
        (("queued", 10.0), ("started", 11.0), ("invalid", 36.0)),
        (("ice_config", "entered", 11.1), ("ice_config", "completed", 11.2),
         ("native_accept", "entered", 12.0), ("invalid", "invalid", 36.0)))
    assert (late_observer_error["worker"], late_observer_error["stage"],
            late_observer_error["stage_state"]) == ("started", "native_accept", "entered")


def start(owner, name):
    key = ConnectionKey("pairing", name, "PRIVATE_IDENTITY", None)
    owner.register(ConnectionState(key, owner.runtime_epoch, Authority(1, True, True, False), Desired.ENABLED))
    owner.dispatch(key, Tick(0))
    return next(effect for effect in owner.drain() if isinstance(effect, Work))


def advance(owner, work, now=0.1, *, pending=False):
    owner.dispatch(work.operation.key, Result(work.operation, now, pending=pending, allocated=work.resource))
    return next((effect for effect in owner.drain() if isinstance(effect, Work)), None)


def observation(owner, work, **changes):
    return owner.pairing_retirement_diagnostic(**{
        "key": work.operation.key, "runtime_epoch": work.operation.runtime_epoch,
        "source": work.resource, **changes})


def test_first_exact_cause_survives_reconciliation_and_global_ring_eviction():
    owner = ConnectionSupervisor("PRIVATE_RUNTIME")
    discover = start(owner, "PRIVATE_INTENT")
    wait_offer = advance(owner, discover)
    gather = advance(owner, wait_offer, 0.2)
    assert gather.phase is Phase.GATHER_ANSWER
    owner.dispatch(gather.operation.key, Failed(gather.operation, 0.3, Failure.INVALID_DOCUMENT,
                                               allocated=gather.resource))
    expected = {"phase": "gather_answer", "event": "failed", "reason": "invalid_document"}
    assert observation(owner, gather) == expected
    for index in range(300):
        owner.dispatch(gather.operation.key, ContextChanged(index + 1, desired=Desired.STOPPED))
    assert owner.snapshot(gather.operation.key).reason == "ineligible"
    assert not any(row.reason == "invalid_document" for row in owner.diagnostics.snapshot()[0])
    assert observation(owner, gather) == expected
    assert owner._pairing_traces[gather.operation.key].retirement.operation == gather.operation
    encoded = json.dumps(observation(owner, gather))
    assert "PRIVATE_" not in encoded and "connection-" not in encoded


def test_interleaved_foreign_actor_never_supplies_the_selected_cause():
    owner = ConnectionSupervisor("epoch", Policy(max_workers=4))
    first = advance(owner, start(owner, "first"))
    second = advance(owner, start(owner, "second"))
    owner.dispatch(first.operation.key, Failed(first.operation, 0.2, Failure.INVALID_DOCUMENT,
                                              allocated=first.resource))
    owner.dispatch(second.operation.key, Tick(second.deadline))
    assert observation(owner, first) == {"phase": "wait_offer", "event": "failed", "reason": "invalid_document"}
    assert observation(owner, second) == {"phase": "wait_offer", "event": "tick", "reason": "phase_timeout"}
    assert observation(owner, first, source=second.resource) == UNKNOWN
    assert observation(owner, first, key=second.operation.key) == UNKNOWN
    assert observation(owner, first, runtime_epoch="old-runtime") == UNKNOWN


@pytest.mark.parametrize("field,value", [
    ("runtime_epoch", "old-runtime"), ("generation", 9),
    ("policy_revision", 9), ("sequence", 900),
])
def test_stale_operation_cleanup_cannot_latch_or_replace_current_cause(field, value):
    owner = ConnectionSupervisor("epoch")
    work = advance(owner, start(owner, "intent"))
    stale = replace(work.operation, **{field: value})
    owner.dispatch(work.operation.key, Failed(stale, 0.2, Failure.REVOKED,
                                            allocated=Resource("native", "PRIVATE_OLD_RESOURCE")))
    assert observation(owner, work) == UNKNOWN
    owner.dispatch(work.operation.key, Failed(work.operation, 0.3, Failure.TRANSIENT, allocated=work.resource))
    expected = {"phase": "wait_offer", "event": "failed", "reason": "transient"}
    assert observation(owner, work) == expected
    owner.dispatch(work.operation.key, Failed(stale, 0.4, Failure.REVOKED, allocated=work.resource))
    assert observation(owner, work) == expected


def test_poll_wait_timeout_uses_exact_last_admitted_work_without_fabricating_operation():
    owner = ConnectionSupervisor("epoch")
    work = advance(owner, start(owner, "intent"))
    assert advance(owner, work, 0.2, pending=True) is None
    assert owner.snapshot(work.operation.key).negotiation.operation is None
    owner.dispatch(work.operation.key, Tick(work.deadline))
    assert observation(owner, work) == {"phase": "wait_offer", "event": "tick", "reason": "phase_timeout"}
    assert owner._pairing_traces[work.operation.key].retirement.operation == work.operation


def test_gather_deadline_custody_exposes_only_exact_original_work():
    owner = ConnectionSupervisor("epoch")
    discover = start(owner, "intent")
    wait_offer = advance(owner, discover)
    gather = advance(owner, wait_offer, 0.2)
    assert gather.phase is Phase.GATHER_ANSWER
    owner.dispatch(gather.operation.key, Tick(gather.deadline + 1))
    exact = {"key": gather.operation.key, "runtime_epoch": "epoch", "source": gather.resource}
    assert owner.pairing_gather_deadline_diagnostic(**exact) == (gather, gather.deadline)
    assert owner.pairing_gather_deadline_diagnostic(**{**exact, "source": Resource("native", "foreign")}) is None
    assert owner.pairing_gather_deadline_diagnostic(**{**exact, "runtime_epoch": "stale"}) is None
    trace = owner._pairing_traces[gather.operation.key]
    cause = trace.retirement
    for field, value in (("sequence", gather.operation.sequence + 1),
                         ("generation", gather.operation.generation + 1),
                         ("policy_revision", gather.operation.policy_revision + 1)):
        trace.retirement = replace(cause, gather_work=replace(gather,
            operation=replace(gather.operation, **{field: value})))
        assert owner.pairing_gather_deadline_diagnostic(**exact) is None
    trace.retirement = replace(cause, gather_work=replace(gather,
        resource=Resource("native", "foreign")))
    assert owner.pairing_gather_deadline_diagnostic(**exact) is None
    trace.retirement = cause
    owner.dispatch(gather.operation.key, ContextChanged(gather.deadline + 2, desired=Desired.STOPPED))
    assert owner.pairing_gather_deadline_diagnostic(**exact) == (gather, gather.deadline)


def test_late_current_completion_records_deadline_transition_not_native_failure_guess():
    owner = ConnectionSupervisor("epoch")
    work = advance(owner, start(owner, "intent"))
    owner.dispatch(work.operation.key, Result(work.operation, work.deadline, allocated=work.resource))
    assert observation(owner, work) == {"phase": "wait_offer", "event": "result", "reason": "phase_timeout"}


def checking(owner):
    work = start(owner, "intent")
    now = 0
    while work.phase is not Phase.CHECKING:
        now += 0.1
        work = advance(owner, work, now)
    owner.dispatch(work.operation.key, Result(work.operation, now + 0.1,
        allocated=work.resource, verified=True, handoff=True))
    return work


def test_successful_handoff_and_adoption_do_not_become_retirement_failure():
    owner = ConnectionSupervisor("epoch")
    work = checking(owner)
    assert observation(owner, work) == UNKNOWN
    physical = Resource("native", "PRIVATE_PHYSICAL")
    target = ConnectionKey("contact", "PRIVATE_CONTACT", "PRIVATE_IDENTITY", "PRIVATE_PEER")
    assert owner.commit_handoff(work.operation, physical, target, 1)
    owner.register(ConnectionState(target, "epoch", Authority(1, True, True, True), Desired.ENABLED))
    owner.dispatch(target, Tick(1))
    adopted_work = next(effect for effect in owner.drain() if isinstance(effect, Work))
    owner.dispatch(target, Adopted(adopted_work.operation, 1.1, physical))
    owner.reject_handoff(work.operation)
    assert observation(owner, work) == UNKNOWN


def test_uncommitted_handoff_rejection_latches_only_exact_source_once():
    owner = ConnectionSupervisor("epoch")
    work = checking(owner)
    owner.reject_handoff(work.operation)
    expected = {"phase": "checking", "event": "handoff_rejected", "reason": "handoff_rejected"}
    assert observation(owner, work) == expected
    owner.reject_handoff(work.operation)
    assert observation(owner, work) == expected


def test_storage_is_per_registered_pairing_actor_and_never_per_poll():
    owner = ConnectionSupervisor("epoch", Policy(max_actors=2, max_workers=2, phase_timeout=1000, poll_interval=1))
    work = advance(owner, start(owner, "intent"))
    start(owner, "second")
    for index in range(100):
        assert advance(owner, work, index * 2 + 0.2, pending=True) is None
        step = owner.snapshot(work.operation.key).negotiation
        owner.dispatch(work.operation.key, Tick(step.poll_at))
        work = next(effect for effect in owner.drain() if isinstance(effect, Work))
    assert len(owner._pairing_traces) == 2
    with pytest.raises(CapacityExceeded):
        start(owner, "third")
    before = owner.snapshot(work.operation.key)
    observation(owner, work)
    assert owner.snapshot(work.operation.key) == before


def qualified(create, directory):
    key = os.urandom(32)
    initial = {"v": 1, "command": "initialize", "payload": {"profile_dir": str(directory),
        "vault_key": base64.b64encode(key).decode(), "display_name": "Mesh qualification", "parent_pid": os.getpid()}}
    private.reserve_fresh_profile(initial)
    service, host, created, closed, *_ = create(directory, key)
    private.mark_initialized_profile(initial)
    service.update_call_settings({**service._call_settings.to_dict(), "turn_broker_url": None,
        "turn_broker_consent": False, "turn_url": None, "turn_username": None,
        "turn_credential": None, "stun_urls": []})
    return private.QualificationControl(lambda: service), service, host, created, closed


@pytest.mark.parametrize("case", ["invalid_offer", "native_answer", "ice_deadline",
                                  "ice_marker_fail",
                                  "gather_deadline", "gather_deadline_late", "sign_deadline",
                                  "bind_deadline", "pause", "cancel"])
def test_actual_qualified_terminal_paths_preserve_the_bound_first_cause(native_pairing, tmp_path, case):
    create, _ = native_pairing
    offer_port, offer_service, *_ = qualified(create, tmp_path / "mesh-qualification-offer")
    offer_id = str(uuid4())
    begin = offer_port.dispatch("qualification.pairing_begin", {"operation_id": offer_id, "role": "offer"})
    assert "retirement" not in begin
    def status(port, operation):
        return port.dispatch("qualification.pairing_status", {"operation_id": operation})
    run_until(offer_service, lambda: bool(status(offer_port, offer_id)["pairing_code"]))
    offered = status(offer_port, offer_id)
    assert "retirement" not in offered
    port, service, host, _, _ = qualified(create, tmp_path / "mesh-qualification-answer")
    entered, release = Event(), Event()
    offset = [0.0]
    if case in {"ice_deadline", "ice_marker_fail", "gather_deadline_late", "sign_deadline", "bind_deadline"}:
        shared_now = lambda: monotonic() + offset[0]
        service._connection_runtime.now = shared_now
        service._connection_runtime.runner._now = shared_now
    if case == "invalid_offer":
        def invalid(*args, **kwargs): raise ValidationError("PRIVATE_INVALID_DOCUMENT")
        service.signal_fetch = invalid
    elif case == "native_answer":
        host.acceptOffer = lambda *args: '{"ok":false,"error":"PRIVATE_NATIVE_ANSWER_ERROR"}'
    elif case in {"gather_deadline", "gather_deadline_late"}:
        accept = host.acceptOffer
        def blocked(*args):
            entered.set()
            assert release.wait(3)
            return accept(*args)
        host.acceptOffer = blocked
    elif case in {"ice_deadline", "ice_marker_fail", "sign_deadline", "bind_deadline"}:
        method = {"ice_deadline": "call_ice_servers", "ice_marker_fail": "call_ice_servers",
                  "sign_deadline": "webrtc_onboarding_answer",
                  "bind_deadline": "native_webrtc_bind_onboarding"}[case]
        original = getattr(service, method)
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return original(*args, **kwargs)
        setattr(service, method, blocked)
        if case == "ice_marker_fail":
            marker = service._native_pairing_stage
            def broken_marker(context, label, state):
                if (label, state) == ("ice_config", "entered"):
                    raise RuntimeError("PRIVATE_OBSERVER_ERROR")
                marker(context, label, state)
            service._native_pairing_stage = broken_marker
    operation = str(uuid4())
    port.dispatch("qualification.pairing_begin", {"operation_id": operation, "role": "answer",
                  "pairing_code": offered["pairing_code"]})
    try:
        if case in {"ice_deadline", "ice_marker_fail", "gather_deadline", "gather_deadline_late",
                    "sign_deadline", "bind_deadline"}:
            run_until(service, entered.is_set)
            if case == "gather_deadline_late":
                offset[0] = 26.0
                service._connection_runtime.step()
                release.set()
                run_until(service, lambda: service._connection_runtime.runner.active == 0)
            else:
                offset[0] = 26.0
                if case == "gather_deadline":
                    service._connection_runtime.now = lambda: monotonic() + 26
        elif case in {"pause", "cancel"}:
            run_until(service, lambda: bool(next(iter(service._native_pairing_contexts.values()))["source"]))
            if case == "pause":
                service._workspace_lifecycle_state = lambda: {"state": "background"}
                service._background_availability_enabled = lambda: False
            else:
                port.dispatch("qualification.pairing_cancel", {"operation_id": operation})
        run_until(service, lambda: status(port, operation)["state"] == "retired")
        observed = status(port, operation)
        retirement = observed["retirement"]
        assert validated_pairing_retirement(retirement) == retirement and retirement != UNKNOWN
        expected = {"invalid_offer": ("wait_offer", "failed", "invalid_document"),
                    "native_answer": ("gather_answer", "failed", "invalid_document"),
                    "gather_deadline": ("gather_answer", "tick", "phase_timeout"),
                    "gather_deadline_late": ("gather_answer", "tick", "phase_timeout"),
                    "ice_deadline": ("gather_answer", "tick", "phase_timeout"),
                    "ice_marker_fail": ("gather_answer", "tick", "phase_timeout"),
                    "sign_deadline": ("gather_answer", "tick", "phase_timeout"),
                    "bind_deadline": ("gather_answer", "tick", "phase_timeout")}
        if case in expected:
            assert tuple(retirement[key] for key in ("phase", "event", "reason")) == expected[case]
        else:
            assert retirement["event"] == "context_changed" and retirement["reason"] == "ineligible"
        if case in {"ice_deadline", "ice_marker_fail", "gather_deadline", "gather_deadline_late",
                    "sign_deadline", "bind_deadline"}:
            gather = observed["gather_failure"]
            assert gather["as_of"] == "phase_deadline" and gather["worker"] == "started"
            stage, completed = {"ice_deadline": ("ice_config", "none"),
                "ice_marker_fail": ("unknown", "unknown"),
                "gather_deadline": ("native_accept", "ice_config"),
                "gather_deadline_late": ("native_accept", "ice_config"),
                "sign_deadline": ("answer_sign", "native_accept"),
                "bind_deadline": ("bind_onboarding", "answer_sign")}[case]
            assert (gather["stage"], gather["stage_state"], gather["last_completed"]) == (
                stage, "unknown" if case == "ice_marker_fail" else "entered", completed)
            assert validated_gather_failure(gather) == gather
        else:
            assert "gather_failure" not in observed
        service._connection_runtime.step()
        assert next(iter(service._connection_runtime.snapshots().values()))["reason"] == "ineligible"
        assert status(port, operation)["retirement"] == retirement
        if case in {"ice_deadline", "ice_marker_fail", "gather_deadline", "gather_deadline_late",
                    "sign_deadline", "bind_deadline"}:
            assert status(port, operation)["gather_failure"] == gather
        internal = next(iter(service._native_pairing_contexts))
        assert "retirement" not in service.native_pairing_status(internal)
        encoded = json.dumps(retirement)
        assert "PRIVATE_" not in encoded and operation not in encoded and offered["pairing_code"] not in encoded
        assert set(retirement) == {"phase", "event", "reason"} and len(encoded.encode()) < 512
    finally:
        release.set()


def test_pre_actor_cancel_is_unknown_and_wrong_qualification_caller_cannot_borrow_it(native_pairing, tmp_path):
    create, _ = native_pairing
    port, service, *_ = qualified(create, tmp_path / "mesh-qualification-cancel")
    operation = str(uuid4())
    payload = {"operation_id": operation}
    port.dispatch("qualification.pairing_begin", {**payload, "role": "offer"})
    port.dispatch("qualification.pairing_cancel", payload)
    assert port.dispatch("qualification.pairing_status", payload)["retirement"] == UNKNOWN
    other = private.QualificationControl(lambda: service, caller="other-controller")
    with pytest.raises(CallOutcomeRequiresResync):
        other.dispatch("qualification.pairing_status", payload)
