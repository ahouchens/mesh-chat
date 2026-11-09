"""Private pairing policy traces; these are simulated, not transport evidence."""
from dataclasses import replace
import json
import os
from threading import Event
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.connection.model import (
    Adopted, Authority, ConnectionKey, ConnectionState, ContextChanged, Desired, Failed,
    Failure, Phase, Resource, Result, Retire, Tick, Work,
)
from mesh_chat.connection.projection import snapshot
from mesh_chat.connection.reducer import transition
from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.connection.model import Execution
from mesh_chat.connection.supervisor import ConnectionSupervisor
from mesh_chat.call_manager import CallOutcomeRequiresResync
from mesh_chat.errors import ContactNotApproved, NativeUnavailable, ValidationError
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def pairing(preferred=True):
    return ConnectionState(ConnectionKey("pairing", "intent", "local", None), "epoch",
                           Authority(1, True, True, preferred), Desired.ENABLED)


@pytest.mark.parametrize("preferred", [False, True])
def test_initial_pairing_uses_owner_phases_then_releases_without_claiming_message_readiness(preferred):
    state = pairing(preferred)
    expected = ([Phase.DISCOVER, Phase.GATHER_OFFER, Phase.PUBLISH_OFFER, Phase.WAIT_ANSWER,
                 Phase.APPLY_ANSWER, Phase.CHECKING] if preferred else
                [Phase.DISCOVER, Phase.WAIT_OFFER, Phase.GATHER_ANSWER, Phase.PUBLISH_ANSWER, Phase.CHECKING])
    result = transition(state, Tick(0))
    for index, phase in enumerate(expected):
        work, = result.effects
        assert isinstance(work, Work) and work.phase is phase
        result = transition(result.state, Result(work.operation, (index + 1) / 10,
            allocated=work.resource if phase is Phase.CHECKING else None,
            verified=phase is Phase.CHECKING, handoff=phase is Phase.CHECKING))
    state = result.state
    assert state.pairing_terminal and state.reason == "pairing_ready"
    assert state.carrier is None and state.negotiation is None and result.effects == ()
    assert not snapshot(state, 1)["messaging_ready"]
    resumed = transition(state, ContextChanged(2, authority=Authority(2, True, True, preferred), desired=Desired.ENABLED))
    assert transition(resumed.state, Tick(100)).effects == ()


def test_pairing_phase_timeout_is_terminal_and_never_reallocates_behind_uncertain_reply():
    start = transition(pairing(), Tick(0))
    work, = start.effects
    failed = transition(start.state, Tick(work.deadline))
    assert failed.state.pairing_terminal and failed.state.desired is Desired.STOPPED
    assert Retire(work.resource) in failed.effects
    for now in (100, 1000):
        failed = transition(failed.state, ContextChanged(now, desired=Desired.ENABLED))
        assert transition(failed.state, Tick(now)).effects == ()


def test_pairing_poll_reuses_one_resource_and_owner_deadline():
    result = transition(pairing(), Tick(0))
    for index in range(3):
        work, = result.effects
        result = transition(result.state, Result(work.operation, (index + 1) / 10))
    work, = result.effects
    assert work.phase is Phase.WAIT_ANSWER
    pending = transition(result.state, Result(work.operation, 0.5, pending=True))
    assert pending.effects == ()
    polled = transition(pending.state, Tick(pending.state.negotiation.poll_at))
    next_work, = polled.effects
    assert next_work.resource == work.resource and next_work.deadline == work.deadline


def test_pairing_revocation_retires_late_exact_allocation_and_cannot_transfer():
    result = transition(pairing(), Tick(0))
    work, = result.effects
    revoked = transition(result.state, ContextChanged(0.1, authority=Authority(2, False, False, True)))
    late = transition(revoked.state, Result(work.operation, 0.2, allocated=work.resource, verified=True, handoff=True))
    assert late.reason == "stale_completion" and late.effects == (Retire(work.resource),)
    assert not snapshot(late.state, 1)["messaging_ready"]


def test_ordinary_reconnect_cannot_skip_attachment_and_path_with_pairing_handoff():
    state = replace(pairing(), key=ConnectionKey("contact", "peer", "local", "remote"))
    result = transition(state, Tick(0))
    work, = result.effects
    failed = transition(result.state, Result(work.operation, 0.1, allocated=work.resource, handoff=True))
    assert failed.reason == "invalid_handoff" and failed.state.blocked
    assert Retire(work.resource) in failed.effects


def test_pairing_actor_cannot_adopt_a_carrier_and_bypass_checked_handoff():
    start = transition(pairing(), Tick(0))
    work, = start.effects
    physical = Resource("native", "physical-peer")
    rejected = transition(start.state, Adopted(work.operation, 0.1, physical))
    assert rejected.reason == "invalid_adoption"
    assert rejected.state.carrier is None and rejected.state.pairing_terminal
    assert Retire(physical) in rejected.effects
    assert not any(isinstance(effect, Work) for effect in rejected.effects)
    assert not snapshot(rejected.state, 0.2)["messaging_ready"]


@pytest.mark.parametrize("handoff_fails", [False, True])
def test_actual_runtime_handoff_is_once_and_exception_keeps_exact_cleanup(handoff_fails):
    results, retired, attempts = [], [], []
    profile = {"id": "intent", "scope_kind": "pairing", "local_device_id": "local",
               "active": True, "effective": {"ready": True, "preferred": True}}
    class Executor:
        def execute(self, work, cancellation):
            result = Result(work.operation, monotonic(),
                allocated=work.resource if work.phase is Phase.CHECKING else None,
                verified=work.phase is Phase.CHECKING, handoff=work.phase is Phase.CHECKING)
            results.append(result)
            return result
        def retire(self, resource): retired.append(resource)
    def handoff(operation, resource, commit):
        attempts.append((operation, resource))
        if handoff_fails: raise OSError("handoff failed after owner release")
        assert commit(resource, ConnectionKey("contact", "peer", "local", "remote"))
    runtime = ConnectionRuntime("epoch", lambda *_: Executor(), profiles=lambda: {"profiles": [profile]},
        execution=lambda: Execution.AVAILABLE, activate=lambda _: pytest.fail("Pairing activated reconnect"), handoff=handoff)
    try:
        deadline = monotonic() + 3
        while not attempts and monotonic() < deadline:
            runtime.step()
            Event().wait(0.002)
        assert len(attempts) == 1
        handed = next(result for result in results if result.handoff)
        # Duplicate handoff and an older allocation result exercise the real
        # completion queue after the original actor has surrendered its lease.
        runtime.runner._completed.put(handed)
        runtime.runner._completed.put(replace(results[1], allocated=handed.allocated))
        for _ in range(10):
            runtime.step()
            Event().wait(0.002)
        assert len(attempts) == 1
        if handoff_fails:
            assert attempts[0][1] in retired
        else:
            assert retired == []
        assert not runtime.snapshots()["intent"]["messaging_ready"]
    finally:
        runtime.stop()
        runtime.wait()


def ready_handoff():
    owner = ConnectionSupervisor("epoch")
    owner.register(pairing())
    owner.tick(0)
    while True:
        work, = owner.drain()
        owner.dispatch(work.operation.key, Result(work.operation, 0.1,
            allocated=work.resource if work.phase is Phase.CHECKING else None,
            verified=work.phase is Phase.CHECKING, handoff=work.phase is Phase.CHECKING))
        if work.phase is Phase.CHECKING:
            return owner, work


def test_committed_handoff_lease_survives_lost_return_and_target_adoption_then_old_results():
    owner, source = ready_handoff()
    physical = Resource("native", "physical-peer")
    target = ConnectionKey("contact", "peer", "local", "remote")
    assert owner.commit_handoff(source.operation, physical, target, 0.2)
    owner.register(ConnectionState(target, "epoch", Authority(1, True, True, True), Desired.ENABLED))
    owner.tick(0.2)
    work, = owner.drain()
    owner.dispatch(target, Adopted(work.operation, 0.3, physical))
    assert owner.handoff_committed(source.operation)
    owner.reject_handoff(source.operation)  # callback exception after adoption
    for resource in (physical, source.resource):
        owner.dispatch(source.operation.key, Result(source.operation, 0.4, allocated=resource))
    assert not any(isinstance(effect, Retire) for effect in owner.drain())
    assert owner.snapshot(target).carrier.resource == physical
    owner.retire(target, 0.5)
    assert Retire(physical) in owner.drain()


@pytest.mark.parametrize("committed", [False, True])
def test_unadopted_handoff_has_bounded_owner_cleanup_and_late_adoption_is_denied(committed):
    owner, source = ready_handoff()
    target = ConnectionKey("contact", "peer", "local", "remote")
    physical = Resource("native", "physical-peer") if committed else source.resource
    if committed:
        assert owner.commit_handoff(source.operation, physical, target, 0.2)
    owner.tick(100)
    assert Retire(physical) in owner.drain()
    assert physical in owner._retiring
    owner.register(ConnectionState(target, "epoch", Authority(1, True, True, True), Desired.ENABLED))
    owner.tick(100)
    work, = owner.drain()
    owner.dispatch(target, Adopted(work.operation, 100.1, physical))
    assert owner.snapshot(target).carrier is None


@pytest.mark.parametrize("fence", [False, True])
def test_handoff_commit_after_deadline_or_explicit_stop_cannot_publish_custody(fence):
    owner, source = ready_handoff()
    target = ConnectionKey("contact", "peer", "local", "remote")
    if fence:
        owner.revoke_handoffs({source.operation.key})
    assert not owner.commit_handoff(source.operation, Resource("native", "physical-peer"), target,
                                    0.2 if fence else 100)
    assert not owner.handoff_committed(source.operation)
    assert Retire(source.resource) in owner.drain()


def test_handoff_adoption_after_deadline_is_denied_even_without_a_tick():
    owner, source = ready_handoff()
    target = ConnectionKey("contact", "peer", "local", "remote")
    physical = Resource("native", "physical-peer")
    assert owner.commit_handoff(source.operation, physical, target, 0.2)
    owner.register(ConnectionState(target, "epoch", Authority(1, True, True, True), Desired.ENABLED))
    owner.tick(0.3)
    work, = owner.drain()
    owner.dispatch(target, Adopted(work.operation, 100, physical))
    assert owner.snapshot(target).carrier is None
    assert Retire(physical) in owner.drain()


@pytest.mark.parametrize("adopt_before_exception", [False, True])
def test_runtime_commit_then_callback_exception_keeps_transfer_receipt(adopt_before_exception):
    profile = {"id": "intent", "scope_kind": "pairing", "local_device_id": "local",
               "active": True, "effective": {"ready": True, "preferred": True}}
    physical = Resource("native", "physical-peer")
    target = ConnectionKey("contact", "peer", "local", "remote")
    attempts, retired = [], []
    class Executor:
        def execute(self, work, cancellation):
            return Result(work.operation, monotonic(), allocated=work.resource if work.phase is Phase.CHECKING else None,
                          verified=work.phase is Phase.CHECKING, handoff=work.phase is Phase.CHECKING)
        def retire(self, resource): retired.append(resource)
    def handoff(operation, resource, commit):
        attempts.append(operation)
        assert commit(physical, target)
        if adopt_before_exception:
            runtime.owner.register(ConnectionState(target, "epoch", Authority(1, True, True, True), Desired.ENABLED))
            runtime.owner.tick(monotonic())
            work, = runtime.owner.drain()
            runtime.owner.dispatch(target, Adopted(work.operation, monotonic(), physical))
        raise OSError("return lost after transfer commit")
    runtime = ConnectionRuntime("epoch", lambda *_: Executor(), profiles=lambda: {"profiles": [profile]},
        execution=lambda: Execution.AVAILABLE, activate=lambda _: None, handoff=handoff)
    try:
        deadline = monotonic() + 3
        while not attempts and monotonic() < deadline:
            runtime.step()
            Event().wait(0.002)
        assert len(attempts) == 1
        assert runtime.owner.handoff_committed(attempts[0])
        assert not any(isinstance(effect, Retire) for effect in runtime.owner.drain())
        assert retired == []
    finally:
        runtime.stop()
        runtime.wait()


FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:" + FINGERPRINT + "\r\n"


@pytest.fixture
def native_pairing(tmp_path, monkeypatch):
    """Actual vault/signatures/runtime; native and mailbox boundaries are doubles."""
    from mesh_chat import service as service_module
    opened, documents = [], {}
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    monkeypatch.setattr(ConnectionRuntime, "start", lambda *_: None)
    def publish(base, document, role, *, session, **_):
        assert any(item.store.list("workspace_operation") for item in opened)
        documents[session, role] = document
        return {"session_id": session, "role": role}
    def fetch(base, session, role, *, pending=False, **_):
        document = documents.get((session, role))
        assert document or pending
        return {"document": document, "pending": not bool(document)}
    monkeypatch.setattr(service_module, "publish_signal", publish)
    monkeypatch.setattr(service_module, "fetch_signal", fetch)
    def create(directory=None, key=None):
        directory = directory or tmp_path / str(len(opened))
        key = key or os.urandom(32)
        created, closed, controls = [], [], []
        def offer(physical, ice, channels):
            created.append((physical, json.loads(ice)))
            return json.dumps({"ok": True, "sdp": SDP})
        host = SimpleNamespace(createOffer=offer, acceptOffer=lambda physical, sdp, ice, channels: offer(physical, ice, channels),
            applyAnswer=lambda *_: json.dumps({"ok": True}), send=lambda *_: True,
            sendControl=lambda physical, label, text: controls.append((physical, label, json.loads(text))) or True,
            stats=lambda _: json.dumps({"ok": True, "result": {"ice_connection_state": "connected", "data_channel_state": "open"}}),
            close=closed.append)
        service = MeshChatService(VaultStore(directory, key, allow_unprotected_for_tests=True), directory,
            lambda _: None, connection_policy="shared-native", native_webrtc_host=host)
        opened.append(service)
        service.create_profile("Synthetic")
        service.update_call_settings({**service._call_settings.to_dict(), "signal_mailbox_url": "https://signal.example.test",
                                      "turn_url": "turn:relay.example.test"})
        return service, host, created, closed, controls, key
    yield create, documents
    for service in opened:
        service.close()


def run_until(service, condition, timeout=3):
    deadline = monotonic() + timeout
    while not condition() and monotonic() < deadline:
        service._connection_runtime.step()
        Event().wait(0.002)
    assert condition(), (service._connection_runtime.owner.diagnostics.snapshot()[0][-15:])


@pytest.mark.parametrize("trust", ["awaiting_consent", "pending_request", "blocked", "identity_changed"])
def test_pending_device_profile_denies_authority_without_faulting_whole_runtime(native_pairing, trust):
    from mesh_chat.models import TrustState
    from test_reconnect_service import _add_contact
    create, _ = native_pairing
    service, *_ = create()
    peer, *_ = create()
    contact = _add_contact(service, "pending-peer", peer._identity,
        peer._require_profile()["destination_hash"])
    profile_id = service.reconnect_capabilities_get(contact["id"])["profile"]["id"]
    contact["trust"] = TrustState(trust).value
    service.store.put("contact", contact["id"], contact)
    runtime = service._connection_runtime
    runtime.step()
    state = next(state for state in runtime.owner.snapshots() if state.key.profile_id == profile_id)
    assert not state.authority.authorized and state.desired is Desired.STOPPED
    assert state.carrier is None and runtime._failure is None


def test_actual_pairing_composition_exchanges_signed_offer_answer_without_granting_contact_trust(native_pairing):
    create, _ = native_pairing
    first, _, created, _, controls, _ = create()
    offer_id, answer_id = str(uuid4()), str(uuid4())
    first.native_pairing_begin(offer_id, role="offer", authorized=lambda: True)
    run_until(first, lambda: first.native_pairing_status(offer_id)["pairing_code"] is not None)
    code = first.native_pairing_status(offer_id)["pairing_code"]
    second, _, accepted, _, _, _ = create()
    second.native_pairing_begin(answer_id, role="answer", pairing_code=code, authorized=lambda: True)
    run_until(second, lambda: second.native_pairing_status(answer_id)["state"] == "awaiting_approval")
    # Pending WAIT_ANSWER is driven by the owner's existing cadence.
    first._connection_runtime.now = lambda: monotonic() + 6
    run_until(first, lambda: first.native_pairing_status(offer_id)["state"] == "awaiting_approval")
    assert len(created) == len(accepted) == 1
    assert created[0][1]["iceTransportPolicy"] == accepted[0][1]["iceTransportPolicy"] == "relay"
    for service, intent in ((first, offer_id), (second, answer_id)):
        context = service._native_pairing_contexts[intent]
        assert service._native_webrtc_peers[context["session"]]
        assert not service._native_webrtc_profile_sessions and not service._native_webrtc_sessions
        assert not service._connection_runtime.snapshots()[intent]["messaging_ready"]
        receipts = str(service.store.list("workspace_operation"))
        assert code not in receipts and SDP not in receipts and FINGERPRINT not in receipts
        assert service.store.list("contact") == []
    run_until(first, lambda: any(message[2].get("type") == "contact_invitation" for message in controls))
    assert not first._connection_runtime.snapshots()[offer_id]["messaging_ready"]


def test_native_pairing_replay_never_reallocates_and_restart_requires_resync(native_pairing, tmp_path):
    create, _ = native_pairing
    service, _, created, _, _, key = create(tmp_path / "persistent")
    operation = str(uuid4())
    service.native_pairing_begin(operation, role="offer", authorized=lambda: True)
    run_until(service, lambda: service.native_pairing_status(operation)["pairing_code"] is not None)
    same = service.native_pairing_begin(operation, role="offer", authorized=lambda: True)
    assert same["pairing_code"] and len(created) == 1
    with pytest.raises(ValidationError):
        service.native_pairing_begin(operation, role="offer", authorized=lambda: True, allow_direct_ip_disclosure=True)
    service.close()
    reopened, _, created_again, *_ = create(tmp_path / "persistent", key)
    with pytest.raises(CallOutcomeRequiresResync):
        reopened.native_pairing_begin(operation, role="offer", authorized=lambda: True)
    assert created_again == []


@pytest.mark.parametrize("cancel_before_allocation", [False, True])
def test_pairing_cancellation_closes_only_its_exact_peer_without_replacement(native_pairing, cancel_before_allocation):
    create, _ = native_pairing
    service, _, created, closed, _, _ = create()
    operation = str(uuid4())
    service.native_pairing_begin(operation, role="offer", authorized=lambda: True)
    if not cancel_before_allocation:
        run_until(service, lambda: service.native_pairing_status(operation)["pairing_code"] is not None)
    service.native_pairing_cancel(operation)
    run_until(service, lambda: service._native_pairing_contexts[operation]["state"] == "retired")
    for _ in range(6):
        service._connection_runtime.step()
        Event().wait(0.002)
    assert len(created) == (0 if cancel_before_allocation else 1)
    assert not service._native_webrtc_live
    assert not created or created[0][0] in closed


@pytest.mark.parametrize("allocated", [False, True])
@pytest.mark.parametrize("cancel_read_fails", [False, True])
def test_durable_cancel_callback_retires_without_a_cancel_api_call(native_pairing, allocated, cancel_read_fails):
    create, _ = native_pairing
    service, _, created, closed, *_ = create()
    cancelled, terminal = [False], []
    def requested():
        if cancelled[0] and cancel_read_fails:
            raise OSError("Protected cancellation read failed")
        return cancelled[0]
    def checkpoint(state):
        context = service._native_pairing_contexts[operation]
        assert context["state"] == state == "retired"
        assert context["physical"] is None or context["physical"] in closed
        terminal.append(state)
    operation = str(uuid4())
    service.native_pairing_begin(operation, role="offer", authorized=lambda: True,
        cancel_requested=requested, on_terminal=checkpoint)
    if allocated:
        run_until(service, lambda: service.native_pairing_status(operation)["pairing_code"] is not None)
    cancelled[0] = True  # Core committed this before its API return was lost.
    run_until(service, lambda: service._native_pairing_contexts[operation]["state"] == "retired")
    for _ in range(3): service._connection_runtime.step()
    assert terminal == ["retired"]
    assert len(created) == len(closed) == int(allocated)
    assert service.native_pairing_status(operation)["state"] == "retired"
    replacement = service.native_pairing_begin(str(uuid4()), role="offer", authorized=lambda: True)
    assert replacement["state"] == "reserved"


def test_failed_terminal_checkpoint_retries_without_repeating_native_disposal(native_pairing):
    create, _ = native_pairing
    service, _, _, closed, *_ = create()
    attempts = []
    def checkpoint(state):
        attempts.append(state)
        if len(attempts) == 1: raise OSError("Protected checkpoint unavailable")
    operation = str(uuid4())
    service.native_pairing_begin(operation, role="offer", authorized=lambda: True, on_terminal=checkpoint)
    run_until(service, lambda: service.native_pairing_status(operation)["pairing_code"] is not None)
    service.native_pairing_cancel(operation)
    run_until(service, lambda: len(attempts) >= 2)
    assert attempts == ["retired", "retired"] and len(closed) == 1


def test_current_caller_revocation_during_native_create_prevents_publish_and_retires_exact_allocation(native_pairing):
    create, documents = native_pairing
    service, host, created, closed, _, _ = create()
    allowed = [True]
    original = host.createOffer
    def revoke(*args):
        result = original(*args)
        allowed[0] = False
        return result
    host.createOffer = revoke
    operation = str(uuid4())
    service.native_pairing_begin(operation, role="offer", authorized=lambda: allowed[0])
    run_until(service, lambda: service._native_pairing_contexts[operation]["state"] == "retired")
    assert len(created) == 1 and created[0][0] in closed
    assert documents == {}
    with pytest.raises(ContactNotApproved):
        service.native_pairing_status(operation)


@pytest.mark.parametrize("checkpoint_fails", [False, True])
def test_domain_checked_handoff_adopts_only_actual_physical_peer_then_requires_normal_path(native_pairing, checkpoint_fails):
    """Approval/contact rows are explicit component fixtures, not bootstrap qualification."""
    from test_reconnect_service import _add_contact
    create, _ = native_pairing
    first, _, created, _, _, _ = create()
    second, _, _, _, _, _ = create()
    first_id, second_id = str(uuid4()), str(uuid4())
    attempts = []
    def checkpoint(state):
        assert state == "transferred"
        assert first._native_pairing_contexts[first_id]["state"] == state
        operation = next(iter(first._connection_runtime._handoff_attempts.values()))
        assert first._connection_runtime.owner.handoff_committed(operation)
        attempts.append(state)
        if checkpoint_fails and len(attempts) == 1:
            raise OSError("Protected terminal checkpoint return lost")
    first.native_pairing_begin(first_id, role="offer", authorized=lambda: True, on_terminal=checkpoint)
    run_until(first, lambda: first.native_pairing_status(first_id)["pairing_code"] is not None)
    code = first.native_pairing_status(first_id)["pairing_code"]
    second.native_pairing_begin(second_id, role="answer", pairing_code=code, authorized=lambda: True)
    run_until(second, lambda: second.native_pairing_status(second_id)["state"] == "awaiting_approval")
    first._connection_runtime.now = lambda: monotonic() + 6
    run_until(first, lambda: first.native_pairing_status(first_id)["state"] == "awaiting_approval")
    _add_contact(first, "contact-second", second._identity, second._require_profile()["destination_hash"])
    _add_contact(second, "contact-first", first._identity, first._require_profile()["destination_hash"])
    for service, intent, other, contact in ((first, first_id, second, "contact-first"), (second, second_id, first, "contact-second")):
        context = service._native_pairing_contexts[intent]
        document = other.reconnect_capabilities_create(contact)["capabilities"]
        service._native_control_receive(context["session"], "mesh-onboarding",
            json.dumps({"type": "connection_capabilities", "document": document}))
        assert service._native_webrtc_controls[context["session"]].get("profile_id")
        assert not service.native_manual_carrier_authorized(service._native_webrtc_controls[context["session"]]["profile_id"])
    context = first._native_pairing_contexts[first_id]
    physical, session = context["physical"], context["session"]
    profile_id = first._native_webrtc_controls[session]["profile_id"]
    assert first._native_pairing_ready(context), first._reconnect_profile_public(first._reconnect_profile(profile_id))["effective"]["reasons"]
    attached = []
    def attach(logical, *, expected_physical):
        assert logical == session and expected_physical == physical
        attached.append(expected_physical)
        return {"bridge_id": "fixture-bridge"}
    first.webrtc_attach_native = attach
    first.reconnect_path_status = lambda _: {"has_path": True, "ready": True}
    # The native bindings are captured at construction; attachment resolves the
    # current trusted service method, as production does.
    first._connection_runtime.now = lambda: monotonic() + 12
    run_until(first, lambda: first._native_pairing_contexts[first_id]["state"] == "transferred")
    first._connection_runtime.now = monotonic
    run_until(first, lambda: first._native_webrtc_profile_sessions.get(profile_id) == session)
    run_until(first, lambda: any(state.carrier is not None for state in first._connection_runtime.owner.snapshots()
                               if state.key.profile_id == profile_id))
    state = next(state for state in first._connection_runtime.owner.snapshots() if state.key.profile_id == profile_id)
    assert state.carrier.resource == Resource("native", physical)
    assert first._connection_runtime.owner.handoff_committed(next(iter(first._connection_runtime._handoff_attempts.values())))
    assert len(created) == 1
    assert not first._connection_runtime.snapshots()[first_id]["messaging_ready"]
    # Original intent cancellation has surrendered cleanup authority.
    assert first.native_pairing_cancel(first_id)["state"] == "transferred"
    assert session in first._native_webrtc_live
    assert attempts == ["transferred"] * (2 if checkpoint_fails else 1)
    # The new owner's later cleanup does not rewrite the surrendered intent.
    first._native_pairing_retire(context, Resource("native", physical))
    assert context["state"] == "transferred"
    assert attempts == ["transferred"] * (2 if checkpoint_fails else 1)


def test_completed_lock_drops_pairing_capabilities_and_identity_references(native_pairing):
    create, _ = native_pairing
    service, *_ = create()
    intent = str(uuid4())
    service.native_pairing_begin(intent, role="offer", authorized=lambda: True)
    run_until(service, lambda: service.native_pairing_status(intent)["pairing_code"] is not None)
    context = service._native_pairing_contexts[intent]
    assert context["identity"]() is service._identity
    service.close()
    assert service._store_closed and service._identity is None
    assert context == {} and service._core_signal_attempts == {} and service._core_signal_results == {}


def test_pairing_parent_receipt_rollback_prevents_native_and_signaling_effects(native_pairing, monkeypatch):
    create, documents = native_pairing
    service, _, created, _, _, _ = create()
    original = service.store._write_records_locked
    def fail(*args):
        original(*args)
        raise OSError("admission transaction rolled back")
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    with pytest.raises(OSError):
        service.native_pairing_begin(str(uuid4()), role="offer", authorized=lambda: True)
    assert not service._native_pairing_contexts and not created and not documents
    assert service.store.list("workspace_operation") == []


def test_late_failed_native_create_retains_exact_close_until_acknowledged(native_pairing):
    create, documents = native_pairing
    service, host, created, closed, _, _ = create()
    offer = host.createOffer
    def unknown(*args):
        offer(*args)
        raise OSError("create reply lost after allocation")
    host.createOffer = unknown
    close_attempts = []
    def close(physical):
        close_attempts.append(physical)
        if len(close_attempts) < 3:
            raise OSError("close acknowledgement unavailable")
        closed.append(physical)
    host.close = close
    intent, terminal = str(uuid4()), []
    service.native_pairing_begin(intent, role="offer", authorized=lambda: True, on_terminal=terminal.append)
    run_until(service, lambda: bool(service._connection_runtime._cleanup_failed))
    assert len(created) == 1 and not closed and not documents
    physical = created[0][0]
    assert set(close_attempts) == {physical}
    assert terminal == []
    service._connection_runtime.now = lambda: monotonic() + 6
    run_until(service, lambda: service._native_pairing_contexts[intent]["state"] == "retired")
    assert closed == [physical] and set(close_attempts) == {physical}
    assert len(created) == 1 and not service._native_webrtc_live
    assert terminal == ["retired"]
