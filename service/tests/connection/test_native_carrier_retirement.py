"""Private retirement primitives and boundary controls; no platform qualification."""
import json
import socket
import threading
import time
import urllib.request
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.connection.model import Adopted, Bridge, Desired, Execution, Health, Phase, Resource, Result
from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.core_api.qualification_host import QualificationControl, mark_initialized_profile, reserve_fresh_profile
from mesh_chat.errors import ContactNotApproved, NativeUnavailable, ValidationError
from test_core_qualification_host import initial
from test_native_path_evidence import REQUEST, evidence
from test_pairing_runtime import native_pairing, run_until


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []
    def denied(*_args, **_kwargs):
        attempts.append(True)
        raise AssertionError("Retirement unit control attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    yield
    assert attempts == []


def pump(runtime, condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        runtime.step()
        threading.Event().wait(.002)
    assert condition()


@pytest.fixture
def owned_runtime():
    facts = SimpleNamespace(live=True, clear=False, failures=0, closes=[], entered=threading.Event(),
                            release=threading.Event())
    facts.release.set()
    resource = Resource("native", "physical-original")
    profile = {"id": "profile", "contact_id": "contact", "local_device_id": "local",
               "remote_device_id": "remote", "active": False, "state": "waiting_for_peer",
               "auto_reconnect": False, "manual_carrier_authorized": True,
               "effective": {"ready": False, "reasons": ["consent_missing"]}}
    class Executor:
        def execute(self, work, _cancelled):
            if work.phase is Phase.DISCOVER:
                return Adopted(work.operation, time.monotonic(), resource)
            return Result(work.operation, time.monotonic(), allocated=work.resource,
                          observed_health=Health.OPEN if work.phase is Phase.INSPECT else None,
                          observed_bridge=Bridge.READY if work.phase is Phase.INSPECT else None)
        def retire(self, retired):
            facts.closes.append(retired)
            facts.entered.set()
            assert facts.release.wait(3)
            if facts.failures:
                facts.failures -= 1
                raise OSError("Controlled cleanup failure")
            facts.live = False
    def profiles():
        profile["manual_carrier_authorized"] = facts.live
        return {"profiles": [dict(profile)], "retirement_clearances": (
            runtime.cleanup_acknowledged_retirements() if facts.clear else ())}
    runtime = ConnectionRuntime("epoch", lambda *_: Executor(), profiles=profiles,
                                execution=lambda: Execution.AVAILABLE, activate=lambda _: pytest.fail("Auto start"))
    pump(runtime, lambda: runtime.snapshots().get("profile", {}).get("messaging_ready"))
    state = runtime.owner.snapshots()[0]
    facts.runtime, facts.profile, facts.resource, facts.state = runtime, profile, resource, state
    yield facts
    facts.release.set()
    runtime.stop()
    runtime.wait()


def begin(facts):
    state = facts.runtime.owner.snapshot(facts.state.key)
    return facts.runtime.begin_carrier_retirement(state.key, facts.resource,
                                                  state.generation, state.authority.revision)


def test_real_cleanup_then_fresh_projection_required_and_wait_does_not_drive_work(owned_runtime):
    f = owned_runtime
    f.release.clear()
    ticket = begin(f)
    assert f.runtime.carrier_retirement_status(ticket) == "pending"
    assert not f.runtime.permits_carrier(f.state.key.profile_id, f.resource)
    assert not f.runtime.permits_recovery(f.profile)
    assert f.runtime.profile(f.state.key) == {"state": "stopped"}
    assert f.closes == []
    f.runtime.step()
    assert f.entered.wait(2)
    assert f.live and f.runtime.carrier_retirement_status(ticket) == "pending"
    f.release.set()
    pump(f.runtime, lambda: bool(f.runtime.cleanup_acknowledged_retirements()))
    assert f.runtime.carrier_retirement_status(ticket) == "pending"
    f.clear = True
    pump(f.runtime, lambda: f.runtime.carrier_retirement_status(ticket) == "acknowledged")
    assert f.closes == [f.resource]
    assert f.profile["state"] == "waiting_for_peer" and f.profile["auto_reconnect"] is False
    assert f.runtime.permits_recovery(f.profile)


def test_failed_cleanup_retains_hold_and_existing_retry_reuses_exact_resource(owned_runtime):
    f = owned_runtime
    f.failures = 1
    f.clear = True
    ticket = begin(f)
    pump(f.runtime, lambda: bool(f.runtime._cleanup_failed))
    assert f.runtime.carrier_retirement_status(ticket) == "pending"
    assert f.runtime.cleanup_acknowledged_retirements() == ()
    f.runtime.now = lambda: time.monotonic() + 6
    pump(f.runtime, lambda: f.runtime.carrier_retirement_status(ticket) == "acknowledged")
    assert f.closes == [f.resource, f.resource]


@pytest.mark.parametrize("fence", ["stop", "all", "authority", "quarantine"])
def test_transient_clearance_never_clears_real_denial(owned_runtime, fence):
    f = owned_runtime
    ticket = begin(f)
    pump(f.runtime, lambda: bool(f.runtime.cleanup_acknowledged_retirements()))
    if fence == "stop": f.runtime.fence("contact")
    elif fence == "all": f.runtime.fence()
    elif fence == "authority": token = f.runtime.begin_authority_change("contact")
    else: f.runtime.quarantine()
    f.clear = True
    f.runtime.synchronize()
    assert f.runtime.carrier_retirement_status(ticket) == "acknowledged"
    assert not f.runtime.permits_recovery(f.profile)
    assert f.runtime.profile(f.state.key) == {"state": "stopped"}
    if fence == "authority": assert f.runtime._authority_changes["contact"] == token


def test_stale_clearance_projection_cannot_end_hold(owned_runtime):
    f = owned_runtime
    ticket = begin(f)
    pump(f.runtime, lambda: bool(f.runtime.cleanup_acknowledged_retirements()))
    f.clear = True
    original = f.runtime.profiles
    def stale():
        result = original()
        token = f.runtime.begin_authority_change("contact")
        f.runtime.commit_authority_change("contact", token)
        return result
    f.runtime.profiles = stale
    f.runtime.synchronize()
    assert f.runtime.carrier_retirement_status(ticket) == "pending"
    f.runtime.profiles = original
    f.runtime.synchronize()
    assert f.runtime.carrier_retirement_status(ticket) == "acknowledged"


@pytest.mark.parametrize("fault", ["resource", "generation", "revision", "not_ready", "already_retiring"])
def test_atomic_owner_compare_rejects_changed_target_without_retiring_it(owned_runtime, fault):
    f = owned_runtime
    state = f.runtime.owner.snapshot(f.state.key)
    resource, generation, revision = f.resource, state.generation, state.authority.revision
    if fault == "resource": resource = Resource("native", "foreign")
    elif fault == "generation": generation += 1
    elif fault == "revision": revision += 1
    elif fault == "not_ready":
        f.runtime.owner._states[state.key] = replace(state, carrier=replace(state.carrier, bridge=Bridge.PATH_PENDING))
    else: f.runtime.owner._retiring.add(resource)
    before = f.runtime.owner.snapshot(state.key)
    assert not f.runtime.owner.retire_current_carrier(state.key, resource, generation, revision, time.monotonic())
    assert f.runtime.owner.snapshot(state.key) == before
    assert not f.closes
    f.runtime.owner._retiring.discard(resource)


def test_hold_rejects_late_target_handoff_and_duplicate_retirement(owned_runtime, monkeypatch):
    f = owned_runtime
    begin(f)
    called = []
    monkeypatch.setattr(f.runtime.owner, "commit_handoff", lambda *_: called.append(True) or True)
    assert not f.runtime._commit_handoff(object(), f.resource, f.state.key)
    assert called == []
    with pytest.raises(ValueError): begin(f)


@pytest.mark.parametrize("denial", ["hold", "shutdown", "quarantine", "all"])
def test_missing_cached_profile_cannot_bypass_target_or_terminal_hold(owned_runtime, monkeypatch, denial):
    f = owned_runtime
    if denial == "hold": begin(f)
    elif denial == "shutdown": f.runtime._stop.set()
    elif denial == "quarantine": f.runtime.quarantine()
    else: f.runtime.fence()
    f.runtime._profile_values.pop(f.state.key)
    calls = []
    monkeypatch.setattr(f.runtime.owner, "commit_handoff", lambda *_: calls.append(True) or True)
    assert not f.runtime._commit_handoff(object(), f.resource, f.state.key)
    assert calls == []
    f.runtime._profile_values[f.state.key] = f.profile


@pytest.fixture
def qualified_owner(native_pairing, tmp_path):
    """Real signed pairing/handoff, approved-contact rows; native transport is modeled."""
    from test_reconnect_service import _add_contact
    create, _ = native_pairing
    def qualified(name):
        initialization = initial(tmp_path / ("mesh-qualification-" + name))
        reserve_fresh_profile(initialization)
        import base64
        service, host, created, closed, *_ = create(
            Path(initialization["payload"]["profile_dir"]), base64.b64decode(initialization["payload"]["vault_key"]))
        mark_initialized_profile(initialization)
        return service, QualificationControl(lambda: service), host, created, closed
    first, port, host, created, closed = qualified("retirement-first")
    second, other, *_ = qualified("retirement-second")
    first_id, second_id = str(uuid4()), str(uuid4())
    port.dispatch("qualification.pairing_begin", {"operation_id": first_id, "role": "offer",
                                                "allow_direct_ip_disclosure": True})
    status = lambda: port.dispatch("qualification.pairing_status", {"operation_id": first_id})
    run_until(first, lambda: bool(status()["pairing_code"]))
    other.dispatch("qualification.pairing_begin", {"operation_id": second_id, "role": "answer",
        "pairing_code": status()["pairing_code"], "allow_direct_ip_disclosure": True})
    run_until(second, lambda: other.dispatch("qualification.pairing_status", {"operation_id": second_id})["state"] == "awaiting_approval")
    first._connection_runtime.now = lambda: time.monotonic() + 6
    run_until(first, lambda: status()["state"] == "awaiting_approval")
    _add_contact(first, "second", second._identity, second._require_profile()["destination_hash"])
    _add_contact(second, "first", first._identity, first._require_profile()["destination_hash"])
    first.reconnect_consent_set("second", False, True)
    second.reconnect_consent_set("first", False, True)
    first_context = next(iter(first._native_pairing_contexts.values()))
    second_context = next(iter(second._native_pairing_contexts.values()))
    for service, context, peer, contact in ((first, first_context, second, "first"),
                                             (second, second_context, first, "second")):
        capabilities = peer._reconnect_profile_for_contact(contact)["local_capabilities"]
        service._native_control_receive(context["session"], "mesh-onboarding",
            json.dumps({"type": "connection_capabilities", "document": capabilities}))
    first.webrtc_attach_native = lambda *_a, **_kw: {"bridge_id": "modeled-bridge"}
    first.reconnect_path_status = lambda _: {"has_path": True, "ready": True}
    first._connection_runtime.executor.reconnect.path = first.reconnect_path_status
    first._connection_runtime.now = lambda: time.monotonic() + 12
    run_until(first, lambda: first_context["state"] == "transferred")
    first._connection_runtime.now = time.monotonic
    run_until(first, lambda: first._native_carrier_authorized(first_context["session"]))
    profile_id = first._native_webrtc_controls[first_context["session"]]["profile_id"]
    run_until(first, lambda: first._connection_runtime.snapshots()[profile_id]["messaging_ready"])
    host.pathEvidence = lambda physical, challenge: json.dumps({"ok": True, "result": evidence(physical, 1, challenge)})
    first._native_bridge_attached = lambda _: True
    sample = first.native_webrtc_path_evidence(first_context["session"], first_context["physical"], REQUEST)
    payload = {"operation_id": first_id, "request_id": "b" * 32,
        "logical_session": sample["logical_session"], "expected_physical": sample["resource"],
        "expected_service_incarnation": sample["service_incarnation"], "expected_adapter_epoch": sample["adapter_epoch"]}
    return SimpleNamespace(service=first, port=port, context=first_context, host=host, created=created,
                           closed=closed, payload=payload, sample=sample)


def observation(facts, port=None):
    return (port or facts.port).dispatch("qualification.inventory", {
        key: facts.payload[key] for key in ("operation_id", "request_id")})["carrier_retirement"]


def test_private_request_uses_owner_cleanup_and_survives_control_reconstruction(qualified_owner):
    f = qualified_owner
    from mesh_chat.core_api.native_commands import ServiceNativeCommands
    assert ServiceNativeCommands(f.service).command("native_webrtc_close", {
        "session_id": f.payload["logical_session"]}) == {"state": "managed"}
    assert f.closed == []
    before = deepcopy(f.service._reconnect_profiles_raw())
    assert f.port.dispatch("qualification.retire_carrier", f.payload) == {"request_id": "b" * 32, "state": "pending"}
    reconstructed = QualificationControl(lambda: f.service)
    assert observation(f, reconstructed)["state"] == "pending"
    run_until(f.service, lambda: observation(f, reconstructed)["state"] == "acknowledged")
    assert f.closed == [f.payload["expected_physical"]]
    assert f.service._reconnect_profiles_raw() == before
    assert f.port.dispatch("qualification.retire_carrier", dict(f.payload))["state"] == "acknowledged"
    assert f.closed == [f.payload["expected_physical"]]
    assert "carrier_retirement" not in reconstructed.dispatch("qualification.inventory", {})


def test_expired_transferred_code_does_not_remove_current_cleanup_authority(qualified_owner):
    f = qualified_owner
    f.context["expires_at"] = time.time() - 1
    assert f.port.dispatch("qualification.retire_carrier", f.payload)["state"] == "pending"
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")


@pytest.mark.parametrize("fault", ["logical", "physical", "service", "adapter", "automatic", "owner", "control", "trust", "authority", "source"])
def test_private_target_rejections_have_no_cleanup_effect(qualified_owner, fault):
    f = qualified_owner
    payload = dict(f.payload)
    if fault in {"logical", "physical", "service", "adapter"}:
        field = {"logical": "logical_session", "physical": "expected_physical",
                 "service": "expected_service_incarnation", "adapter": "expected_adapter_epoch"}[fault]
        payload[field] = "c" * 32
    elif fault == "automatic":
        profile = f.service._reconnect_profile_for_contact("second")
        f.service.store.put("reconnect_profile", profile["id"], {**profile, "auto_reconnect": True})
    elif fault == "owner": f.service._native_webrtc_profile_sessions["foreign"] = payload["logical_session"]
    elif fault == "control": f.service._native_webrtc_controls[payload["logical_session"]]["profile_binding"] = None
    elif fault == "trust":
        contact = f.service.store.get("contact", "second")
        f.service.store.put("contact", "second", {**contact, "trust": "blocked"})
    elif fault == "authority": f.context["authorized"] = lambda: False
    else: f.context["state"] = "awaiting_approval"
    with pytest.raises((ValidationError, ContactNotApproved)):
        f.port.dispatch("qualification.retire_carrier", payload)
    assert f.closed == [] and "carrier_retirement" not in f.context


@pytest.mark.parametrize("field,value", [("extra", True), ("request_id", True), ("request_id", "A" * 32),
    ("expected_adapter_epoch", "x" * 32), ("logical_session", "x" * 129), ("operation_id", "not-a-uuid")])
def test_private_wire_rejects_malformed_fields_before_retirement(qualified_owner, field, value):
    f = qualified_owner
    with pytest.raises(ValidationError):
        f.port.dispatch("qualification.retire_carrier", {**f.payload, field: value})
    assert "carrier_retirement" not in f.context and f.closed == []


def test_pending_cleanup_blocks_new_pairing_and_conflicting_replay(qualified_owner):
    f = qualified_owner
    f.port.dispatch("qualification.retire_carrier", f.payload)
    with pytest.raises(ContactNotApproved):
        f.port.dispatch("qualification.pairing_begin", {"operation_id": str(uuid4()), "role": "offer"})
    with pytest.raises(ValidationError):
        f.port.dispatch("qualification.retire_carrier", {**f.payload, "request_id": "c" * 32})
    assert f.closed == []


def test_pending_check_and_new_admission_share_service_dispatch_lock(qualified_owner, monkeypatch):
    f = qualified_owner
    checked = []
    pending = f.service.native_pairing_retirement_pending
    admission = f.service.native_pairing_begin
    def check():
        checked.append(("pending", f.service._dispatch_lock._is_owned()))
        return pending()
    def admit(*args, **kwargs):
        checked.append(("begin", f.service._dispatch_lock._is_owned()))
        return admission(*args, **kwargs)
    monkeypatch.setattr(f.service, "native_pairing_retirement_pending", check)
    monkeypatch.setattr(f.service, "native_pairing_begin", admit)
    result = f.port.dispatch("qualification.pairing_begin", {"operation_id": str(uuid4()), "role": "offer"})
    assert result["state"] == "reserved"
    assert checked == [("pending", True), ("begin", True)]


def test_foreign_caller_and_revoked_observer_cannot_borrow_acknowledgment(qualified_owner):
    f = qualified_owner
    foreign = QualificationControl(lambda: f.service, caller="foreign-controller")
    with pytest.raises(ContactNotApproved): foreign.dispatch("qualification.retire_carrier", f.payload)
    f.port.dispatch("qualification.retire_carrier", f.payload)
    denied = QualificationControl(lambda: f.service, authorize=lambda: False)
    with pytest.raises(ContactNotApproved): observation(f, denied)
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    with pytest.raises(ContactNotApproved): observation(f, foreign)


def test_projection_error_keeps_ack_pending_without_repeating_native_cleanup(qualified_owner, monkeypatch):
    f = qualified_owner
    f.port.dispatch("qualification.retire_carrier", f.payload)
    original = f.service._native_retirement_cleared
    def failed(_): raise OSError("Controlled private projection failure")
    monkeypatch.setattr(f.service, "_native_retirement_cleared", failed)
    run_until(f.service, lambda: bool(f.service._connection_runtime.cleanup_acknowledged_retirements()))
    f.service._connection_runtime.step()
    assert observation(f)["state"] == "pending"
    assert f.closed == [f.payload["expected_physical"]]
    monkeypatch.setattr(f.service, "_native_retirement_cleared", original)
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    assert len(f.closed) == 1


def test_failed_native_ack_retains_exact_reservation_until_existing_owner_retry(qualified_owner, monkeypatch):
    f = qualified_owner
    original = f.host.close
    attempts = []
    def close(physical):
        attempts.append(physical)
        if len(attempts) == 1:
            raise OSError("Controlled native acknowledgment failure")
        original(physical)
    monkeypatch.setattr(f.host, "close", close)
    f.port.dispatch("qualification.retire_carrier", f.payload)
    runtime = f.service._connection_runtime
    run_until(f.service, lambda: bool(runtime._cleanup_failed))
    assert f.service._native_resources.resolve(f.payload["expected_physical"]) == f.payload["logical_session"]
    assert observation(f)["state"] == "pending"
    assert f.closed == []
    # The signed-pairing fixture previously advanced its existing scheduler by12s.
    runtime.now = lambda: time.monotonic() + 30
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    assert attempts == [f.payload["expected_physical"]] * 2
    assert f.closed == [f.payload["expected_physical"]]


def test_failed_checkpoint_cannot_be_acknowledged_by_successful_native_close(qualified_owner):
    f = qualified_owner
    class Journal:
        retained = True
        attempts = 0
        def retire(self, physical):
            assert physical == f.payload["expected_physical"]
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("Controlled protected checkpoint failure")
            self.retained = False
        def bindings(self):
            return [SimpleNamespace(resource=f.payload["expected_physical"])] if self.retained else []
    journal = f.service._carrier_journal = Journal()
    f.port.dispatch("qualification.retire_carrier", f.payload)
    runtime = f.service._connection_runtime
    run_until(f.service, lambda: bool(runtime._cleanup_failed))
    assert f.closed == [f.payload["expected_physical"]]
    assert observation(f)["state"] == "pending"
    assert journal.retained and f.service._native_resources.physical(f.payload["logical_session"])
    runtime.now = lambda: time.monotonic() + 30
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    assert journal.attempts == 2 and not journal.retained
    assert f.closed == [f.payload["expected_physical"]] * 2 and len(f.created) == 1


def test_completed_hold_does_not_wait_for_next_pairing_or_block_cold_consent_transition(qualified_owner):
    f = qualified_owner
    f.port.dispatch("qualification.retire_carrier", f.payload)
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    profile = f.service._reconnect_profile_for_contact("second")
    assert f.service._connection_runtime.permits_recovery(profile)
    assert profile["auto_reconnect"] is False and profile["state"] != "stopped"
    result = f.port.dispatch("qualification.pairing_begin", {"operation_id": str(uuid4()), "role": "offer"})
    assert result["state"] == "reserved"
    # This is the existing cold-workload consent action, not an implicit resume.
    assert f.service.reconnect_consent_set("second", True, True)["profile"]["auto_reconnect"] is True


@pytest.mark.parametrize("command", ["qualification.retire_carrier", "qualification.inventory"])
def test_android_retirement_and_correlated_inventory_require_actual_uid(qualified_owner, monkeypatch, command):
    import weakref
    from mesh_chat import mobile_bridge
    from mesh_chat.core_api import qualification_host as private
    f = qualified_owner
    payload = f.payload if command.endswith("retire_carrier") else {
        key: f.payload[key] for key in ("operation_id", "request_id")}
    monkeypatch.setattr(mobile_bridge, "_service", f.service)
    monkeypatch.setattr(private, "_android_service", weakref.ref(f.service))
    def denied(): raise ValidationError("Controlled foreign UID")
    monkeypatch.setattr(private, "_android_own_uid", denied)
    assert json.loads(private.android_control(json.dumps({"command": command, "payload": payload})))["ok"] is False
    assert f.closed == [] and "carrier_retirement" not in f.context
