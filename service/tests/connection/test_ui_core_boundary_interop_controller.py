"""Controller/evidence component checks; synthetic reports are never CI proof."""

from pathlib import Path
import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_evidence as evidence
from native_interop_rendezvous import APPROVAL_PHASES, OFFER_PHASES, checked_payload
from test_ui_core_boundary_interop_peers import (
    ANDROID_ENVIRONMENT_SITES, ANDROID_START_SITES, assert_android_cleaned, scripted_android,
)
from test_ui_core_boundary_interop_evidence import sample


@pytest.fixture
def path_observer(monkeypatch, sample):
    """Actual observe/wait/Samples; only private peer calls and time are scripted."""
    value, inventory = sample
    state = SimpleNamespace(now=10.0, events=[], sleeps=[], on_sleep=None, error=None, value=value,
        inventory=inventory, sequence=0, challenges=[], echo_request=True)
    state.inventory["resources"][0]["owner_state"] = "authorized"
    def discover():
        state.events.append("inventory")
        return copy.deepcopy(state.inventory)
    def path(logical, physical, sample_request):
        state.events.append(("path", logical, physical))
        state.challenges.append(sample_request)
        if state.error is not None: raise state.error
        state.sequence += 1
        result = copy.deepcopy(state.value)
        result.update(sample_sequence=state.sequence, sampled_at_ms=int((100 + state.now - 10) * 1000))
        if state.echo_request: result["sample_request"] = sample_request
        return result
    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
        if state.on_sleep is not None: state.on_sleep()
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    instance = controller.Controller("android", SimpleNamespace(inventory=discover, path=path), None, None, {})
    instance.samples = evidence.Samples(monotonic=lambda: state.now)
    state.controller = instance
    return state


class PendingState(str):
    pass


OWNER_STATE_VALUES = [None, False, True, 0, 1, [], {}, "unknown", "PENDING_ADOPTION",
    "unadopted", "unavailable", "authorized", PendingState("pending_adoption")]


@pytest.mark.parametrize("logical", [None, "logical"])
def test_unique_pending_adoption_waits_then_samples_same_physical_resource(path_observer, logical):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    def adopt(): state.inventory["resources"][0]["owner_state"] = "authorized"
    state.on_sleep = adopt
    result = state.controller.wait(lambda: state.controller.observe(logical, ready=True, scenario="turn_udp"), timeout=120)
    assert result["logical_session"] == "logical" and result["resource"] == "physical"
    assert state.events == ["inventory", "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and state.sequence == 1
    assert state.controller.samples.previous == {("service", "physical", "a" * 32): 1}


@pytest.mark.parametrize("owner_state", ["missing", *OWNER_STATE_VALUES, "pending_adoption"])
@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("denial", ["contact", "native"])
def test_only_strict_pending_hint_defers_other_metadata_preserves_exact_path_error(path_observer, owner_state, ready, denial):
    from mesh_chat.errors import NativeUnavailable
    state = path_observer
    row = state.inventory["resources"][0]
    if owner_state == "missing": row.pop("owner_state")
    else: row["owner_state"] = owner_state
    state.error = controller.PeerFailure("contact_not_approved") if denial == "contact" else NativeUnavailable("private sample unavailable")
    if ready and type(owner_state) is str and owner_state == "pending_adoption":
        assert state.controller.observe("logical", ready=ready) is None
        assert state.events == ["inventory"]
    else:
        with pytest.raises(type(state.error)) as failure:
            state.controller.observe("logical", ready=ready)
        assert failure.value is state.error
        assert state.events == ["inventory", ("path", "logical", "physical")]
    assert state.sleeps == [] and state.controller.samples.previous == {}


@pytest.mark.parametrize("owner_state", ["missing", *OWNER_STATE_VALUES])
def test_nonpending_metadata_keeps_original_successful_sampling(path_observer, owner_state):
    state = path_observer
    if owner_state == "missing": state.inventory["resources"][0].pop("owner_state")
    else: state.inventory["resources"][0]["owner_state"] = owner_state
    result = state.controller.observe("logical", scenario="turn_udp")
    assert result["resource"] == "physical"
    assert state.events == ["inventory", ("path", "logical", "physical")] and state.sleeps == []


def test_ready_false_still_samples_pending_unadopted_path(path_observer):
    state = path_observer
    state.inventory["resources"][0].update(adopted=False, owner_state="pending_adoption")
    state.value.update(adopted=False, attached=False, messaging_ready=False)
    assert state.controller.observe("logical", ready=False)["adopted"] is False
    assert state.events == ["inventory", ("path", "logical", "physical")]


@pytest.mark.parametrize("requested,pending_logical,expected", [
    ("logical", "logical", ["inventory"]),
    ("logical", "other", ["inventory", ("path", "logical", "physical")]),
    ("absent", "logical", ["inventory"]),
])
def test_pending_hint_is_considered_only_after_exact_logical_filter(path_observer, requested, pending_logical, expected):
    state = path_observer
    state.inventory["resources"].append(dict(logical_session="other", physical_resource="other-physical", adopted=True, owner_state="authorized"))
    next(row for row in state.inventory["resources"] if row["logical_session"] == pending_logical)["owner_state"] = "pending_adoption"
    result = state.controller.observe(requested)
    assert (result is not None) == (requested == "logical" and pending_logical == "other")
    assert state.events == expected


@pytest.mark.parametrize("requested,second_logical", [(None, "other"), ("logical", "logical")])
def test_ambiguous_matching_pending_row_keeps_original_path_and_denial(path_observer, requested, second_logical):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    state.inventory["resources"].append(dict(logical_session=second_logical, physical_resource="other-physical", adopted=True, owner_state="authorized"))
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.observe(requested)
    assert failure.value is state.error
    assert state.events == ["inventory", ("path", "logical", "physical")]


@pytest.mark.parametrize("remaining,polls", [(120, 480), (0.5, 2)])
def test_pending_adoption_uses_original_poll_and_deadline_without_path_rpc(path_observer, remaining, polls):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    if remaining < 120: state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.wait(lambda: state.controller.observe("logical"), timeout=120)
    assert failure.value.code == "scenario_deadline"
    assert state.now == 10 + remaining and state.sleeps == [0.25] * polls
    assert state.events == ["inventory"] * polls and state.controller.samples.previous == {}


def test_pending_then_revoked_is_not_cached_or_swallowed(path_observer):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    def revoke():
        state.inventory["resources"][0]["owner_state"] = "unavailable"
        state.error = controller.PeerFailure("contact_not_approved")
    state.on_sleep = revoke
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.wait(lambda: state.controller.observe("logical"), timeout=120)
    assert failure.value is state.error
    assert state.events == ["inventory", "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and state.controller.samples.previous == {}


@pytest.mark.parametrize("field", ["adopted", "attached", "messaging_ready", "status"])
def test_authorized_inventory_does_not_replace_actual_selected_path_readiness(path_observer, field):
    state = path_observer
    state.value[field] = "unsupported" if field == "status" else False
    assert state.controller.observe("logical", ready=True) is None
    assert state.events == ["inventory", ("path", "logical", "physical")]
    assert state.controller.samples.previous == {} and state.sleeps == []


def test_empty_inventory_still_returns_no_sample(path_observer):
    state = path_observer
    state.inventory["resources"] = []
    assert state.controller.observe() is None
    assert state.events == ["inventory"] and state.controller.samples.previous == {}


def test_controller_draws_exactly_one_fresh_sixteen_byte_request_per_path_rpc(path_observer, monkeypatch):
    state, draws = path_observer, []
    def random_bytes(size):
        draws.append(size)
        return bytes([len(draws)]) * size
    monkeypatch.setattr(controller.os, "urandom", random_bytes)
    state.controller.observe("logical")
    state.controller.observe("logical")
    assert draws == [16, 16] and state.challenges == ["01" * 16, "02" * 16]
    assert state.events == ["inventory", ("path", "logical", "physical")] * 2
    assert state.controller.samples.previous == {("service", "physical", "a" * 32): 2}
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    assert state.controller.observe("logical") is None and draws == [16, 16]
    state.inventory["resources"] = []
    assert state.controller.observe() is None and draws == [16, 16]


@pytest.mark.parametrize("unready", [None, "adopted", "status"])
def test_old_or_missing_invocation_echo_fails_even_before_readiness_filter(path_observer, unready):
    state = path_observer
    state.echo_request = False
    state.value.pop("sample_request")
    if unready is not None: state.value[unready] = "not_selected" if unready == "status" else False
    with pytest.raises(ValueError) as failure: state.controller.observe("logical")
    assert state.controller.failure_observation(failure.value) == {
        "failure_substage": "path_validation", "sample_rejection_reason": "sample_request"}
    assert state.controller.samples.previous == {} and len(state.challenges) == 1


def run_approval_report(tmp_path, monkeypatch, capsys, path_observer, role, fault):
    """Actual main/pair/path_case/observe/Samples; all product/host boundaries doubled."""
    import connection_ci
    state = path_observer
    state.decided = state.cancelled = False
    state.approval_error = ValueError("PRIVATE_PAYLOAD_ERROR")
    peer = state.controller.peer
    inventory, path = peer.inventory, peer.path
    # Direct native DTO double for post-pair selected-path assertions.
    for endpoint in ("local", "remote"): state.value["pair"][endpoint]["type"] = "host"
    state.value["pair"]["relay_protocol"] = "not_applicable"
    contact = {"id": "PRIVATE_CONTACT", "core_handle": "PRIVATE_PEER", "trust": "approved"}
    def core(operation, params, key=None):
        if operation == "application.snapshot":
            state.events.append("snapshot")
            if (not state.decided and fault == "pending_contact_wait") or (state.decided and fault == "approved_contact_wait"):
                raise state.approval_error
            if state.decided: return {"contacts": [contact]}
            if role == "windows": return {"contacts": [{**contact, "trust": "pending_request"}]}
            return {"contact_invitations": [{"id": "PRIVATE_INVITATION", "state": "pending"}],
                "contacts": [contact] if fault == "implicit_contact_guard" else []}
        if operation in {"peer.approve", "contact.invitation"}:
            state.events.append("decision")
            if fault == "contact_decision": raise state.approval_error
            state.decided = True
            return {}
        assert operation == "native.command" and params["command"] == "reconnect_consent_set"
        state.events.append("consent")
        if fault == "reconnect_consent": raise state.approval_error
        return {}
    def discover():
        value = inventory()
        if fault == "path_inventory": raise state.approval_error
        pending = fault == "approval_ready_observation" or (fault == "adopted_observation" and state.challenges) or (
            fault == "post_cancel_observation" and state.cancelled)
        if pending: value["resources"][0]["owner_state"] = "pending_adoption"
        return value
    def sample(logical, physical, sample_request):
        if fault == "path_read":
            state.events.append(("path", logical, physical))
            state.challenges.append(sample_request)
            raise state.approval_error
        value = path(logical, physical, sample_request)
        if fault == "sample_request": value["sample_request"] = "PRIVATE_CACHED_REQUEST"
        elif fault == "sample_timestamp": value["sampled_at_ms"] = -1
        elif fault == "selected_transport": value["dtls_state"] = "closed"
        elif fault == "cleanup_substitution": value["dtls_state"] = "closed"
        elif fault == "application_counters": value["application"]["received_bytes"] = True
        elif fault == "selected_pair_identity": value["pair"]["token"] = "PRIVATE_PAIR"
        return value
    def pairing_status(operation):
        state.events.append("status")
        return {"operation_id": operation, "state": "retired" if fault == "transferred_status_wait" else "transferred",
            "retirement": retirement_example()}
    def cancel(operation):
        state.events.append("cancel")
        state.cancelled = True
        if fault == "transferred_cancel": raise state.approval_error
        if fault == "carrier_identity_check":
            state.inventory["resources"][0]["physical_resource"] = "PRIVATE_REPLACEMENT"
            state.value["resource"] = "PRIVATE_REPLACEMENT"
        return {"operation_id": "PRIVATE_FOREIGN" if fault == "transferred_cancel_check" else operation, "state": "transferred"}
    peer.core, peer.inventory, peer.path = core, discover, sample
    peer.pairing_status, peer.pairing_cancel, peer.process = pairing_status, cancel, None
    def publish(*args):
        state.events.append("publish")
        if fault == "publish_failure": raise state.approval_error
    def receive(*args, **kwargs):
        state.events.append("receive")
        if fault == "receive_failure": raise state.approval_error
        return {"approved": fault != "approval_acknowledgment"}
    def execute(instance):
        instance.profile, instance.pairing = "PRIVATE_PROFILE", "PRIVATE_PAIRING"
        instance.samples = state.controller.samples
        state.controller = instance
        if fault == "cleanup_substitution":
            consume = instance.samples.consume
            def replacing_cleanup(*args, **kwargs):
                try: return consume(*args, **kwargs)
                finally: raise controller.PeerFailure("invalid_request")
            instance.samples.consume = replacing_cleanup
        if fault in {"forged", "unknown_stage", "unknown_reason"}:
            error = state.approval_error
            error.failure_substage = "path_validation"
            error.sample_rejection_reason = "sample_request"
            if fault == "unknown_stage": instance._substage_failure = error, "PRIVATE_STAGE"
            if fault == "unknown_reason":
                instance._substage_failure = error, "path_validation"
                instance.samples._rejection = error, "PRIVATE_REASON"
            raise error
        if fault in {"stale_then_foreign", "stale_then_success", "stale_then_same"}:
            state.echo_request = False
            with pytest.raises(ValueError) as caught: instance.observe("logical")
            state.echo_request = True
            if fault != "stale_then_foreign": instance.observe("logical")
            if fault == "stale_then_success": return {}
            raise caught.value if fault == "stale_then_same" else state.approval_error
        if fault in {"transferred_status_wait", "adopted_observation", "transferred_cancel", "transferred_cancel_check", "post_cancel_observation", "carrier_identity_check"}:
            instance.negotiate = lambda *_: ("logical", None)
            return instance.path_case("direct", "windows")
        instance.pair("logical", "windows")
        return {}  # Incomplete synthetic execution, never native evidence.
    monkeypatch.setattr(controller.Controller, "run", execute)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *_, **__: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(publish=publish, wait=receive, close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(seal=lambda _, value: value, open=lambda _, value: value, close=lambda: None))
    output = tmp_path / "approval.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", role, "--workload", "full", "--expected-source", "a" * 40, "--output", str(output)])
    code = controller.main()
    captured = capsys.readouterr()
    return SimpleNamespace(record=json.loads(output.read_text()), code=code, state=state,
        output=output.read_text() + captured.out + captured.err)


APPROVAL_CASES = [
    ("windows", "pending_contact_wait", "pending_contact_wait", None),
    ("android", "implicit_contact_guard", "implicit_contact_guard", None),
    ("windows", "contact_decision", "contact_decision", None),
    ("android", "approved_contact_wait", "approved_contact_wait", None),
    ("windows", "reconnect_consent", "reconnect_consent", None),
    ("android", "approval_ready_observation", "approval_ready_observation", None),
    ("windows", "approval_acknowledgment", "approval_acknowledgment", None),
    ("android", "publish_failure", "approval_acknowledgment", "rendezvous_publish"),
    ("windows", "receive_failure", "approval_acknowledgment", "rendezvous_receive"),
    ("windows", "transferred_status_wait", "transferred_status_wait", "pairing_status"),
    ("android", "adopted_observation", "adopted_observation", None),
    ("windows", "transferred_cancel", "transferred_cancel", None),
    ("android", "transferred_cancel_check", "transferred_cancel_check", None),
    ("windows", "post_cancel_observation", "post_cancel_observation", None),
    ("android", "carrier_identity_check", "carrier_identity_check", None),
    ("windows", "path_inventory", "path_inventory", None),
    ("android", "path_read", "path_read", None),
]


@pytest.mark.parametrize("role,fault,stage,site", APPROVAL_CASES)
def test_actual_approval_report_retains_precise_substage_and_nested_site(tmp_path, monkeypatch, capsys, path_observer, role, fault, stage, site):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, role, fault)
    assert run.code == 1 and run.record["phase"] == "explicit_contact_approval"
    assert run.record["failure_substage"] == stage
    assert run.record.get("failure_site") == site and "sample_rejection_reason" not in run.record
    if fault == "transferred_status_wait":
        assert run.record["error_code"] == "supervisor_pairing_retired" and run.record["pairing_retirement"] == retirement_example()
    elif fault in {"approval_ready_observation", "adopted_observation", "post_cancel_observation"}:
        assert run.record["failure_type"] == "PeerFailure" and run.record["error_code"] == "scenario_deadline"
        assert run.state.sleeps == [0.25] * 480
    else: assert run.record["failure_type"] == "ValueError" and "error_code" not in run.record
    assert "PRIVATE_" not in run.output and "sample_request" not in run.record
    assert controller.FAILURE_SUBSTAGES == frozenset({case[2] for case in APPROVAL_CASES} | {"path_validation"})


@pytest.mark.parametrize("reason", ["sample_request", "sample_timestamp", "selected_transport", "application_counters", "selected_pair_identity"])
def test_actual_sample_rejection_report_contains_only_same_exception_reason(tmp_path, monkeypatch, capsys, path_observer, reason):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "android", reason)
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert run.record["failure_substage"] == "path_validation" and run.record["sample_rejection_reason"] == reason
    assert run.record["phase"] == "explicit_contact_approval" and "failure_site" not in run.record
    assert len(run.state.challenges) == 1 and "PRIVATE_" not in run.output
    assert run.state.challenges[0] not in run.output


@pytest.mark.parametrize("fault", ["forged", "unknown_stage", "unknown_reason", "stale_then_foreign", "stale_then_same", "stale_then_success", "success"])
def test_failure_metadata_never_attaches_to_foreign_stale_unknown_or_success(tmp_path, monkeypatch, capsys, path_observer, fault):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "android", fault)
    assert "sample_rejection_reason" not in run.record
    if fault == "unknown_reason": assert run.record["failure_substage"] == "path_validation"
    else: assert "failure_substage" not in run.record
    if fault in {"success", "stale_then_success"}:
        assert run.code == 0 and run.record["passed"] is True
        assert not {"failure_site", "pairing_state", "pairing_retirement", "failure_substage", "sample_rejection_reason"} & set(run.record)
        with pytest.raises(ValueError): evidence.verify_report(run.record, "a" * 40, "b" * 40, "android")
    else: assert run.code == 1
    assert "PRIVATE_" not in run.output


def test_cleanup_replacement_cannot_inherit_prior_sample_rejection_reason(tmp_path, monkeypatch, capsys, path_observer):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "android", "cleanup_substitution")
    assert run.code == 1 and run.record["failure_type"] == "PeerFailure" and run.record["error_code"] == "invalid_request"
    assert run.record["failure_substage"] == "path_validation" and "sample_rejection_reason" not in run.record
    assert len(run.state.challenges) == 1 and "PRIVATE_" not in run.output


MISSING_PAIRING_STATE = object()


@pytest.fixture
def negotiating_peer(monkeypatch):
    """Actual negotiate/wait/status scopes; inert peer and rendezvous boundaries."""
    state = SimpleNamespace(now=10.0, events=[], sleeps=[], on_sleep=None, status_value="awaiting_approval",
        foreign=False, stats_error=None, stats_value={"data_channel_state": "open"},
        resources=[{"logical_session": "logical-session", "physical_resource": "physical"}])
    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
        if state.on_sleep is not None: state.on_sleep()
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    def make(role):
        offer_status_read = False
        def begin(operation, pairing_role, **kwargs):
            state.operation = operation
            state.events.append("begin_" + pairing_role)
            assert kwargs["direct"] is True
            return {"operation_id": operation}
        def status(operation):
            nonlocal offer_status_read
            assert operation == state.operation
            if role == "windows" and not offer_status_read:
                offer_status_read = True
                state.events.append("offer_status")
                return {"operation_id": operation, "state": "offer_ready", "pairing_code": "offline-code"}
            state.events.append("status")
            reply = {"operation_id": "foreign-operation" if state.foreign else operation,
                "retirement": retirement_example()}
            if state.status_value is not MISSING_PAIRING_STATE: reply["state"] = copy.deepcopy(state.status_value)
            return reply
        def inventory():
            state.events.append("inventory")
            return {"resources": copy.deepcopy(state.resources)}
        def core(operation, params, key=None):
            assert key is None
            if operation == "call.settings_update":
                state.events.append("settings")
                return {}
            assert operation == "native.command" and params == {
                "command": "native_webrtc_stats", "payload": {"session_id": "logical-session"}}
            state.events.append("stats")
            if state.stats_error is not None: raise state.stats_error
            return state.stats_value
        def receive(partner, phase, *, timeout):
            assert (partner, phase, timeout) == ("windows", "offer", 180)
            state.events.append("receive")
            return {"shareable": "offline-code"}
        def publish(phase, value):
            assert (phase, value) == ("offer", {"shareable": "offline-code"})
            state.events.append("publish")
        peer = SimpleNamespace(pairing_begin=begin, pairing_status=status, inventory=inventory, core=core)
        instance = controller.Controller(role, peer, SimpleNamespace(wait=receive, publish=publish),
            SimpleNamespace(open=lambda phase, value: value, seal=lambda phase, value: value), {})
        instance.profile = "offline-profile"
        instance.default_call_settings = {}
        instance.broker_ice = {"iceServers": [{"urls": ["stun:offline.invalid"]}]}
        state.controller = instance
        state.prefix = (["settings", "begin_offer", "offer_status", "publish"] if role == "windows"
                        else ["settings", "receive", "begin_answer"])
        return state
    return make


@pytest.mark.parametrize("role", ["windows", "android"])
def test_negotiate_defers_reserved_before_inventory_and_stats_then_observes_same_resource(negotiating_peer, role):
    state = negotiating_peer(role)
    state.status_value = "reserved"
    def ready(): state.status_value = "awaiting_approval"
    state.on_sleep = ready
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.events == [*state.prefix, "status", "status", "inventory", "stats"]
    assert state.resources == [{"logical_session": "logical-session", "physical_resource": "physical"}]
    assert state.sleeps == [0.25]


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("value", [MISSING_PAIRING_STATE, None, False, True, 0, 1, "unknown", "RESERVED",
    PendingState("reserved"), "offer_ready", "awaiting_approval", "transferred"])
def test_negotiate_nonreserved_or_missing_state_keeps_original_sampling(negotiating_peer, role, value):
    state = negotiating_peer(role)
    state.status_value = value
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.events == [*state.prefix, "status", "inventory", "stats"] and state.sleeps == []


@pytest.mark.parametrize("value", [[], {}])
def test_negotiate_unhashable_status_keeps_original_status_failure(negotiating_peer, value):
    state = negotiating_peer("android")
    state.status_value = value
    with pytest.raises(TypeError) as failure:
        state.controller.negotiate("direct", "windows")
    assert state.controller.failure_site(failure.value) == "pairing_status"
    assert state.events == [*state.prefix, "status"] and state.sleeps == []


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("terminal", ["retired", "retiring", "foreign"])
def test_negotiate_reserved_gate_preserves_existing_terminal_and_identity_failures(negotiating_peer, role, terminal):
    state = negotiating_peer(role)
    state.status_value = "reserved" if terminal == "foreign" else terminal
    state.foreign = terminal == "foreign"
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == ("invalid_pairing_identity" if terminal == "foreign" else "supervisor_pairing_retired")
    assert state.controller.failure_site(failure.value) == "pairing_status"
    expected = {} if terminal == "foreign" else {"pairing_state": terminal, "pairing_retirement": retirement_example()}
    assert state.controller.failure_pairing(failure.value) == expected
    assert state.events == [*state.prefix, "status"] and state.sleeps == []


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("remaining,polls", [(120, 480), (0.5, 2)])
def test_negotiate_reserved_uses_existing_deadline_and_cadence(negotiating_peer, role, remaining, polls):
    state = negotiating_peer(role)
    state.status_value = "reserved"
    if remaining < 120: state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == "scenario_deadline" and state.controller.failure_site(failure.value) is None
    assert state.now == 10 + remaining and state.sleeps == [0.25] * polls
    assert state.events == [*state.prefix, *(["status"] * polls)]


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("released", ["stats_error", "retired", "foreign"])
def test_negotiate_after_reserved_preserves_original_error_and_site(negotiating_peer, role, released):
    state = negotiating_peer(role)
    state.status_value = "reserved"
    error = controller.PeerFailure("invalid_request")
    def finish():
        state.status_value = "retired" if released == "retired" else "awaiting_approval"
        state.foreign = released == "foreign"
        if released == "stats_error": state.stats_error = error
    state.on_sleep = finish
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    tail = ["status", "status"]
    if released == "stats_error":
        assert failure.value is error and state.controller.failure_site(error) == "negotiate_native_stats"
        assert state.controller.failure_pairing(error) == {}
        tail += ["inventory", "stats"]
    else:
        assert failure.value.code == ("invalid_pairing_identity" if released == "foreign" else "supervisor_pairing_retired")
        assert state.controller.failure_site(failure.value) == "pairing_status"
    assert state.events == [*state.prefix, *tail] and state.sleeps == [0.25]


@pytest.mark.parametrize("role", ["windows", "android"])
def test_negotiate_created_status_still_requires_original_open_channel_stats(negotiating_peer, role):
    state = negotiating_peer(role)
    state.status_value = "offer_ready"
    state.stats_value = {"data_channel_state": "connecting"}
    def open_channel(): state.stats_value = {"data_channel_state": "open"}
    state.on_sleep = open_channel
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.events == [*state.prefix, "status", "inventory", "stats", "status", "inventory", "stats"]
    assert state.sleeps == [0.25]


def run_android_preflight_report(tmp_path, monkeypatch, capsys, *, site=None, fault=None):
    """Actual main/start/environment; all subprocess and external services scripted."""
    import android_qualification
    import connection_ci
    script = scripted_android(monkeypatch, tmp_path, fault=site)
    context = {"source_commit": "a" * 40}
    events = []
    foreign = controller.PeerFailure("invalid_request")
    foreign.preflight_failure_site = "android_root"
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: context)
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(android_qualification, "APKS", script.apks)
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: script.emulator)
    def services():
        events.append("services")
        if fault == "after_success": raise foreign
        return {}
    monkeypatch.setattr(controller, "outbound_services", services)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: SimpleNamespace(process=None))
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: events.append("transport_closed")))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: events.append("rendezvous_closed")))
    def execute(instance):
        events.append("controller")
        return {}  # Incomplete synthetic execution, never qualified native evidence.
    monkeypatch.setattr(controller.Controller, "run", execute)
    if fault in {"foreign", "caught_then_success", "caught_then_same", "unscoped_same"}:
        start = script.emulator.start
        def intercepted_start(apks, *, diagnostics):
            with pytest.raises(subprocess.CalledProcessError):
                start(apks, diagnostics=diagnostics)
            if fault == "foreign": raise foreign
            if fault == "unscoped_same":
                with diagnostics.scope(None): pass
                raise script.failure
            script.fault = None
            start(apks, diagnostics=diagnostics)
            if fault == "caught_then_same": raise script.failure
        monkeypatch.setattr(script.emulator, "start", intercepted_start)
    if fault == "cleanup_substitution":
        close = script.emulator.close
        def substituting_close():
            close()
            if not events:
                events.append("cleanup_substitution")
                raise foreign
        monkeypatch.setattr(script.emulator, "close", substituting_close)
    output = tmp_path / "preflight-report.json"
    output.write_text(json.dumps({"passed": True, "preflight_failure_site": "PRIVATE_STALE_SITE", "pairing_state": "retired"}))
    monkeypatch.setattr(sys, "argv", ["native_interop_controller", "--role", "android", "--expected-source", "a" * 40,
        "--workload", "full", "--output", str(output)])
    exit_code = controller.main()
    record = json.loads(output.read_text())
    captured = capsys.readouterr()
    return SimpleNamespace(record=record, exit_code=exit_code, script=script, events=events,
        output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("site", (*ANDROID_START_SITES, *ANDROID_ENVIRONMENT_SITES))
def test_actual_precontroller_report_identifies_each_checked_command_only(tmp_path, monkeypatch, capsys, site):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys, site=site)
    assert run.exit_code == 1
    record = run.record
    assert record["passed"] is False and record["phase"] == "platform_outbound_preflight"
    assert record["failure_type"] == "CalledProcessError" and record["preflight_failure_site"] == site
    assert set(record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type", "preflight_failure_site"}
    sites = (*ANDROID_START_SITES, *ANDROID_ENVIRONMENT_SITES)
    expected = list(sites[:sites.index(site) + 1])
    if run.script.starts: expected.insert(2, "boot")
    if run.script.starts: expected.append("kill")
    assert run.script.calls == expected and run.events == []
    assert "PRIVATE_" not in run.output
    assert_android_cleaned(run.script)


@pytest.mark.parametrize("fault", ["foreign", "caught_then_same", "unscoped_same", "cleanup_substitution", "after_success"])
def test_precontroller_report_omits_foreign_or_cleared_command_attribution(tmp_path, monkeypatch, capsys, fault):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys,
        site=None if fault == "after_success" else "android_root_identity", fault=fault)
    assert run.exit_code == 1 and run.record["phase"] == "platform_outbound_preflight"
    expected_type = "CalledProcessError" if fault in {"caught_then_same", "unscoped_same"} else "PeerFailure"
    assert run.record["failure_type"] == expected_type
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type"}
    if expected_type == "PeerFailure":
        fields.add("error_code")
        assert run.record["error_code"] == "invalid_request"
    assert set(run.record) == fields
    assert "controller" not in run.events and "PRIVATE_" not in run.output
    assert not run.script.emulator.root.exists() and run.script.emulator.process is None


@pytest.mark.parametrize("caught", [False, True])
def test_success_report_omits_all_preflight_failure_metadata(tmp_path, monkeypatch, capsys, caught):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys,
        site="android_root_identity" if caught else None, fault="caught_then_success" if caught else None)
    assert run.exit_code == 0 and run.record["passed"] is True
    assert set(run.record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "context",
        "source_commit", "source_tree", "platform", "preflight", "artifacts", "execution"}
    assert run.events == ["services", "controller", "rendezvous_closed", "transport_closed"]
    assert "PRIVATE_" not in run.output and not run.script.emulator.root.exists()
    with pytest.raises(ValueError):
        evidence.verify_pair(interop_reports()[0], run.record, "a" * 40, "b" * 40)


def interop_reports(source="a" * 40, tree="b" * 40, android_artifacts=None, *, workload="full"):
    """Complete fake runs for rejection tests only; no dist report is written."""
    from android_qualification import APKS, CORE_APKS, CONSUMER_ARTIFACTS, INDEPENDENT_ARTIFACTS, ROOT
    plan = evidence.required_workload(workload)
    if android_artifacts is None:
        android_artifacts = {path.relative_to(ROOT).as_posix(): "e" * 64 for path in (*APKS, *CORE_APKS, *CONSUMER_ARTIFACTS, *INDEPENDENT_ARTIFACTS)}
    def message(name, role):
        other = "android" if role == "windows" else "windows"
        return {"outbound": evidence.digest([name, role]), "inbound": evidence.digest([name, other]),
                "authenticated_receipt": True, "inbound_records": 1, "outbound_records": 1, "receipt_roundtrip_ms": 1.0}
    def counts(active=0):
        return {"v": 1, "complete": True, "semantics": "native_allocation_leases", "capacity": 16,
                "reserved_count": active, "creating_count": 0, "allocated_count": active,
                "active_count": active, "retiring_count": 0, "availability": {name: True for name in evidence.ACCOUNTING}}
    def selection(name, role, service, scenario, count, sequence):
        return {"service": evidence.digest(service), "profile": evidence.digest([service, "profile"]),
            "resource": evidence.digest([role, name, "resource"]), "pair": evidence.digest([role, name, "pair"]),
            "sequence": sequence, "local_type": "host" if scenario == "direct" else "relay",
            "remote_type": "srflx" if scenario == "direct" else "relay",
            "relay_protocol": "not_applicable" if scenario == "direct" else "udp" if scenario in {None, "impaired"} else scenario.removeprefix("turn_"),
            "application": {name: count for name in evidence.APPLICATION}, "selected_pair_rtt_ms": 1.0,
            "adopted": True, "attached": True, "messaging_ready": True}
    result = []
    for role in ("windows", "android"):
        cases, iterations = [], []
        identity = evidence.digest([role, "identity"])
        for name, initiator in plan["paths"]:
            case_id = name + ":" + initiator
            before = selection(case_id, role, role + "initial", name, 0, 1)
            after = selection(case_id, role, role + "initial", name, 1, 2)
            negative = None
            if name in {"turn_tcp", "turn_tls", "impaired"}:
                negative = {"blocked_packets": 2 if role == "android" else None, "delivered_while_blocked": False,
                    "delivered_after_restore": True, "kernel_protocol": ("udp" if name == "impaired" else "tcp") if role == "android" else None,
                    "kernel_socket": evidence.digest([name, "kernel socket"]) if role == "android" else None,
                    "outbound": message("negative:" + name, role)["outbound"], "inbound": message("negative:" + name, role)["inbound"]}
            impairment = None
            if name == "impaired" and role == "android":
                impairment = {"kind": "android_emulator_linux_kernel_tc_netem", "delay_ms_each_way": 75,
                    "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1, "added_nominal_rtt_ms": 150,
                    "socket_correlation": "unique_own_pid_socket_and_kernel_flow", "loss_observed": False,
                    "counters": {direction: {"bytes": 1000, "packets": 10, "dropped": 0} for direction in ("egress", "ingress")}}
            cases.append({"scenario": name, "initiator": initiator, "supervisor_pairing": {
                "operation": evidence.digest([role, case_id, "operation"]), "role": "offer" if role == initiator else "answer",
                "state": "transferred", "transferred_cancel_preserves_carrier": True}, "before": before, "after": after,
                "native_delta": {name: 1 for name in evidence.APPLICATION},
                "messages": [message(f"{case_id}:{index}", role) for index in range(20 if name == "impaired" else 1)],
                "impairment": impairment, "negative": negative, "retired_host_accounting": counts()})
        for index in range(plan["iterations"]):
            generation = index // 10 + 1
            service = role + str(generation)
            previous = role + ("initial" if generation == 1 else str(generation - 1)) if index % 10 == 0 else service
            before = selection("warm:" + service, role, service, None, index % 10 * 2, index % 10 * 2 + 1)
            after = selection("warm:" + service, role, service, None, index % 10 * 2 + 1, index % 10 * 2 + 2)
            iterations.append({"iteration": index + 1, "cold_start": index % 10 == 0, "native_resources": 1,
                "warm_baseline_resources": 1, "previous_service": evidence.digest(previous), "current_service": evidence.digest(service),
                "identity": identity, "before": before, "after": after, "native_delta": {name: 1 for name in evidence.APPLICATION},
                "host_accounting": counts(1), "warm_baseline_host_accounting": counts(1), "message": message(f"soak:{index}", role)})
        result.append({"v": 1, "passed": True, "evidence_level": plan["level"], "role": role, "scope": plan["scope"], "workload": workload,
            "context": {"repository": "example/mesh", "repository_id": 1, "run_id": 2, "run_attempt": 1, "source_commit": source},
            "source_commit": source, "source_tree": tree,
            "platform": {"windows": True} if role == "windows" else {"emulated": True, "abi": "x86_64", "kvm": True},
            "preflight": {"turn_advertised_transports": ["tcp", "tls", "udp"], "mailbox_protocol": 2, "mailbox_writes_enabled": True,
                          "scope": "outbound health and advertisement only; no allocation or selected path"},
            "artifacts": {"sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64, "build_manifest_sha256": "f" * 64} if role == "windows" else dict(android_artifacts),
            "execution": {"identity": identity, "scenarios": cases, "receipt_iterations": iterations,
                "processes_started": (plan["iterations"] - 1) // 10 + 2, "forced_exits": (plan["iterations"] - 1) // 10 + 1,
                "clean_exits": 1, "webview_processes": 0, "cleanup": "passed"}})
        result[-1]["execution"]["final_host_accounting"] = counts()
    return tuple(result)


def test_complete_two_role_fixture_is_accepted_only_with_cross_matching_actual_message_identities():
    windows, android = interop_reports()
    assert evidence.verify_pair(windows, android, "a" * 40, "b" * 40) == (windows, android)


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("fault", ["source", "tree", "scope", "platform", "missing_case", "wrong_selected_protocol", "packet_delta",
    "no_receipt", "duplicate_message", "missing_negative", "block_no_packet", "delivered_under_block", "no_restore",
    "iteration_missing", "process_count", "cold_schedule", "old_service", "warm_growth", "native_lease_growth", "unknown_native_zero",
    "unretired_native", "identity_changed", "cleanup", "wrong_initiator", "manual_pairing", "cancel_reclaimed", "raw_extra"])
def test_native_matrix_rejects_partial_or_unexecuted_required_evidence(role, fault):
    reports = interop_reports()
    value = reports[0 if role == "windows" else 1]
    execution = value["execution"]
    case = next(case for case in execution["scenarios"] if case["scenario"] == "turn_tcp")
    if fault == "source": value["source_commit"] = "c" * 40
    elif fault == "tree": value["source_tree"] = "c" * 40
    elif fault == "scope": value["scope"] = "physical full native and media qualification"
    elif fault == "platform": value["platform"] = {"linux": True}
    elif fault == "missing_case": execution["scenarios"].pop()
    elif fault == "wrong_selected_protocol": case["after"]["relay_protocol"] = "udp"
    elif fault == "packet_delta": case["native_delta"]["enqueued_packets"] = 0
    elif fault == "no_receipt": case["messages"][0]["authenticated_receipt"] = False
    elif fault == "duplicate_message": execution["scenarios"][1]["messages"][0] = execution["scenarios"][0]["messages"][0]
    elif fault == "missing_negative": case["negative"] = None
    elif fault == "block_no_packet": case["negative"]["blocked_packets"] = 0
    elif fault == "delivered_under_block": case["negative"]["delivered_while_blocked"] = True
    elif fault == "no_restore": case["negative"]["delivered_after_restore"] = False
    elif fault == "iteration_missing": execution["receipt_iterations"].pop()
    elif fault == "process_count": execution["forced_exits"] = 0
    elif fault == "cold_schedule": execution["receipt_iterations"][1]["cold_start"] = True
    elif fault == "old_service": execution["receipt_iterations"][0]["current_service"] = execution["receipt_iterations"][0]["previous_service"]
    elif fault == "warm_growth": execution["receipt_iterations"][-1]["native_resources"] = 2
    elif fault == "native_lease_growth": execution["receipt_iterations"][-1]["host_accounting"]["reserved_count"] = 2
    elif fault == "unknown_native_zero": execution["final_host_accounting"]["complete"] = False
    elif fault == "unretired_native":
        execution["scenarios"][0]["retired_host_accounting"].update(reserved_count=1, allocated_count=1, retiring_count=1)
    elif fault == "identity_changed": execution["receipt_iterations"][-1]["identity"] = "f" * 64
    elif fault == "cleanup": execution["cleanup"] = "unavailable"
    elif fault == "wrong_initiator": case["initiator"] = "android"
    elif fault == "manual_pairing": case["supervisor_pairing"]["role"] = "manual"
    elif fault == "cancel_reclaimed": case["supervisor_pairing"]["transferred_cancel_preserves_carrier"] = False
    else: case["after"]["raw_sdp"] = "secret"
    with pytest.raises(ValueError): evidence.verify_pair(*reports, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["run", "attempt", "same_identity", "other_message", "other_negative", "other_iteration", "loss_profile", "fake_loss", "missing_rtt"])
def test_pair_cannot_mix_runs_peers_or_impairment_profiles(fault):
    windows, android = interop_reports()
    if fault == "run": android["context"]["run_id"] += 1
    elif fault == "attempt": android["context"]["run_attempt"] += 1
    elif fault == "same_identity": android["execution"]["identity"] = windows["execution"]["identity"]
    elif fault == "other_message": android["execution"]["scenarios"][0]["messages"][0]["inbound"] = "f" * 64
    elif fault == "other_negative": next(case for case in android["execution"]["scenarios"] if case["scenario"] == "turn_tcp")["negative"]["inbound"] = "f" * 64
    elif fault == "other_iteration": android["execution"]["receipt_iterations"][-1]["message"]["inbound"] = "f" * 64
    elif fault == "loss_profile": android["execution"]["scenarios"][-1]["impairment"]["loss_percent_each_way"] = 1
    elif fault == "fake_loss": android["execution"]["scenarios"][-1]["impairment"]["loss_observed"] = True
    else: android["execution"]["scenarios"][-1]["before"]["selected_pair_rtt_ms"] = None
    with pytest.raises(ValueError): evidence.verify_pair(windows, android, "a" * 40, "b" * 40)


def test_final_ci_context_cannot_reuse_a_passing_prior_attempt():
    reports = interop_reports()
    context = {**reports[0]["context"], "run_attempt": 2}
    with pytest.raises(ValueError, match="another workflow"):
        evidence.verify_pair(*reports, "a" * 40, "b" * 40, context=context)


def test_transport_filtering_uses_one_broker_url_and_never_counts_configuration_as_selected_evidence():
    ice = {"iceServers": [{"urls": ["stun:stun.example:3478"]},
        {"urls": ["turn:relay.example:3478?transport=udp", "turn:relay.example:3478?transport=tcp", "turns:relay.example:5349?transport=tcp"],
         "username": "synthetic", "credential": "synthetic"}]}
    for scenario, prefix in (("direct", "stun:"), ("turn_udp", "turn:"), ("turn_tcp", "turn:"), ("turn_tls", "turns:")):
        value, _ = controller.selected_ice(ice, scenario)
        assert len(value["iceServers"]) == len(value["iceServers"][0]["urls"]) == 1
        assert value["iceServers"][0]["urls"][0].startswith(prefix)
        assert "selected" not in value
    with pytest.raises(ValueError): controller.selected_ice({"iceServers": []}, "turn_tls")


def test_fixed_plan_and_phase_inventory_fit_ten_artifacts_per_job_including_final_report():
    assert checked_payload("control", {"scenarios": list(evidence.SCENARIOS), "iterations": 100, "cold_start_every": 10})
    windows = {"key", *OFFER_PHASES, *("negative_checked_" + name for name in ("turn_tcp", "turn_tls", "impaired"))}
    android = {"key", "offer", "approved", "impaired_ready", *("negative_ready_" + name for name in ("turn_tcp", "turn_tls", "impaired"))}
    assert len(windows) + 1 == 10 and len(android) + 1 <= 10
    assert all(name in APPROVAL_PHASES for name in windows | android if name.startswith("negative"))


def test_workflow_keeps_two_actual_concurrent_platform_jobs_and_owned_emulator_lifetime():
    path = controller.ROOT / ".github/workflows/native-interop.yml"
    workflow = yaml.safe_load(path.read_text())
    assert set(workflow["jobs"]) == {"native_windows_peer", "native_android_peer"}
    windows, android = (workflow["jobs"][name] for name in ("native_windows_peer", "native_android_peer"))
    assert windows["runs-on"] == "windows-latest" and android["runs-on"] == "ubuntu-latest"
    assert "needs" not in windows and "needs" not in android
    for role, job in (("windows", windows), ("android", android)):
        action = next(step for step in job["steps"] if step.get("uses") == "./scripts/native-interop-artifact")
        assert action["with"]["role"] == role and action["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
        assert action["with"]["workload"] == "${{ inputs.workload }}"
        assert next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))["with"]["fetch-depth"] == 0
        assert any(step.get("if") == "always()" and step.get("uses", "").startswith("actions/upload-artifact@") for step in job["steps"])
    assert not any(step.get("uses", "").startswith("reactivecircus/") for step in android["steps"])
    assert any("system-images;android-35;google_apis;x86_64" in step.get("run", "") for step in android["steps"])


def test_controller_uses_supervisor_pairing_and_both_direct_initiators():
    source = Path(controller.__file__).read_text()
    assert all(name in source for name in ("pairing_begin", "pairing_status", "pairing_cancel"))
    assert all(name not in source for name in ("native_webrtc_offer", "native_webrtc_accept",
        "native_webrtc_bind_onboarding", "native_webrtc_apply_answer", "signal_publish", "signal_fetch"))
    assert [(name, role) for name, role in evidence.PATH_CASES if name == "direct"] == [
        ("direct", "windows"), ("direct", "android")]


@pytest.mark.parametrize("mode", ["quick", "full"])
def test_workload_cannot_be_relabelled_or_substituted_for_the_other_matrix(mode):
    reports = interop_reports(workload=mode)
    evidence.verify_pair(*reports, "a" * 40, "b" * 40, workload=mode)
    other = "full" if mode == "quick" else "quick"
    with pytest.raises(ValueError):
        evidence.verify_pair(*reports, "a" * 40, "b" * 40, workload=other)
    # Changing labels alone cannot bypass the actual fixed native inventory.
    for report in reports:
        report.update(workload=other, scope=evidence.required_workload(other)["scope"],
                      evidence_level=evidence.required_workload(other)["level"])
    with pytest.raises(ValueError):
        evidence.verify_pair(*reports, "a" * 40, "b" * 40, workload=other)


FAILURE_REPORT_CASES = [
    ("android", "negotiate_settings_update", "negotiate_settings_update", "PeerFailure"),
    ("windows", "pairing_offer_begin", "pairing_offer_begin", "PeerFailure"),
    ("android", "pairing_answer_begin", "pairing_answer_begin", "PeerFailure"),
    ("windows", "pairing_status", "pairing_status", "PeerFailure"),
    ("windows", "rendezvous_publish", "rendezvous_publish", "PeerFailure"),
    ("android", "rendezvous_receive", "rendezvous_receive", "PeerFailure"),
    ("android", "negotiate_inventory", "negotiate_inventory", "PeerFailure"),
    ("android", "negotiate_native_stats", "negotiate_native_stats", "PeerFailure"),
    ("windows", "offer_identity", "pairing_offer_begin", "PeerFailure"),
    ("android", "answer_identity", "pairing_answer_begin", "PeerFailure"),
    ("windows", "status_retired", "pairing_status", "PeerFailure"),
    ("android", "inventory_shape", "negotiate_inventory", "KeyError"),
    ("android", "stats_shape", "negotiate_native_stats", "AttributeError"),
    ("windows", "publish_validation", "rendezvous_publish", "ValueError"),
    ("android", "receive_validation", "rendezvous_receive", "ValueError"),
    ("windows", "before_any_call", None, "ValueError"),
    ("windows", "after_success", None, "ValueError"),
    ("android", "after_success", None, "ValueError"),
    ("windows", "caught_then_unrelated", None, "ValueError"),
]


def run_negotiate_report(tmp_path, monkeypatch, capsys, role, fault, *, status_reply=None):
    # Actual main/negotiate/wait/report flow, synthetic peer/artifact boundaries.
    # No native process, network, service allocation or successful evidence claim.
    import connection_ci
    events = []
    def fail(name):
        if fault == name or (fault == "caught_then_unrelated" and name == "negotiate_settings_update"):
            raise controller.PeerFailure("invalid_request")

    class Peer:
        process = None
        def core(self, operation, params, key=None):
            assert key is None
            if operation == "call.settings_update":
                events.append("settings")
                fail("negotiate_settings_update")
                return {}
            assert operation == "native.command" and params == {
                "command": "native_webrtc_stats", "payload": {"session_id": "PRIVATE_LOGICAL"}}
            events.append("stats")
            fail("negotiate_native_stats")
            return None if fault == "stats_shape" else {"data_channel_state": "open"}
        def pairing_begin(self, operation, pairing_role, **kwargs):
            self.operation = operation
            events.append("begin_" + pairing_role)
            assert kwargs["direct"] is True
            if pairing_role == "answer": assert kwargs["pairing_code"] == "PRIVATE_SIGNED_CODE"
            fail("pairing_" + pairing_role + "_begin")
            return {"operation_id": "PRIVATE_OTHER_ID" if fault == pairing_role + "_identity" else operation}
        def pairing_status(self, operation):
            events.append("status")
            fail("pairing_status")
            if status_reply is not None: return status_reply(operation)
            return {"operation_id": operation, "state": "retired" if fault == "status_retired" else "offer_ready",
                    "pairing_code": "PRIVATE_SIGNED_CODE"}
        def inventory(self):
            events.append("inventory")
            fail("negotiate_inventory")
            return {"resources": [{}] if fault == "inventory_shape" else [{"logical_session": "PRIVATE_LOGICAL"}]}

    class Transport:
        def publish(self, *args):
            events.append("publish")
            fail("rendezvous_publish")
        def wait(self, partner, phase, *, timeout):
            assert partner == "windows" and phase == "offer" and timeout == 180
            events.append("receive")
            fail("rendezvous_receive")
            return {"shareable": "PRIVATE_SIGNED_CODE"}
        def close(self): pass

    class Rendezvous:
        def seal(self, phase, value):
            if fault == "publish_validation": raise ValueError("PRIVATE_URL/SDP/KEY publish")
            return value
        def open(self, phase, value):
            if fault == "receive_validation": raise ValueError("PRIVATE_URL/SDP/KEY receive")
            return value
        def close(self): pass

    def negotiate_only(instance):
        instance.profile = "PRIVATE_PROFILE"
        instance.default_call_settings = {}
        instance.broker_ice = {"iceServers": [] if fault == "before_any_call" else [{"urls": ["stun:PRIVATE_URL"]}]}
        if fault in {"caught_then_unrelated", "caught_status_then_unrelated", "caught_status_then_success", "caught_status_then_foreign"}:
            with pytest.raises(controller.PeerFailure): instance.negotiate("direct", "windows")
            if fault in {"caught_status_then_success", "caught_status_then_foreign"}: instance.pairing_status()
        else:
            instance.negotiate("direct", "windows")
        if fault == "success": return {}
        error = ValueError("PRIVATE_LATER_EXCEPTION/SDP/KEY")
        error.failure_site = "PRIVATE_CALLER_SUPPLIED_SITE"
        raise error

    context = {"source_commit": "a" * 40}
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: context)
    monkeypatch.setattr(controller, "binding", lambda *_: (Path("unused.exe"), {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *_, **__: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: Peer())
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: Peer())
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: Transport())
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: Rendezvous())
    monkeypatch.setattr(controller.Controller, "run", negotiate_only)
    output = tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", ["native_interop_controller", "--role", role, "--expected-source", "a" * 40,
                                      "--workload", "full", "--output", str(output)])
    exit_code = controller.main()
    record = json.loads(output.read_text())
    captured = capsys.readouterr()
    return SimpleNamespace(record=record, events=events, exit_code=exit_code,
        output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("role,fault,site,error_type", FAILURE_REPORT_CASES)
def test_actual_failure_report_selects_only_active_literal_call_site(tmp_path, monkeypatch, capsys, role, fault, site, error_type):
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, role, fault)
    record, events = run.record, run.events
    assert run.exit_code == 1
    assert record["passed"] is False and record["phase"] == "direct_supervisor_owned_pairing_windows"
    assert record["workload"] == "full" and record["failure_type"] == error_type
    if site is None: assert "failure_site" not in record
    else: assert record["failure_site"] == site and site in controller.FAILURE_SITES
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type"}
    if error_type == "PeerFailure":
        fields.add("error_code")
        expected_code = ("invalid_pairing_identity" if fault in {"offer_identity", "answer_identity"}
                         else "supervisor_pairing_retired" if fault == "status_retired" else "invalid_request")
        assert record["error_code"] == expected_code
    if site is not None: fields.add("failure_site")
    if fault == "status_retired":
        fields.add("pairing_state")
        assert record["pairing_state"] == "retired" and "pairing_retirement" not in record
    assert set(record) == fields
    success_path = (["settings", "begin_offer", "status", "publish", "status", "inventory", "stats"] if role == "windows"
                    else ["settings", "receive", "begin_answer", "status", "inventory", "stats"])
    assert events == success_path[:len(events)]  # No added/reordered/repeated requests.
    if fault == "after_success": assert events == success_path
    assert "PRIVATE_" not in run.output


def retirement_example():
    # Agreed first-causal-transition DTO, checked against C's shared sanitizer.
    value = {"phase": "gather_answer", "event": "failed", "reason": "invalid_document"}
    assert controller.validated_pairing_retirement(value) == value
    return value


RETIREMENT_CASES = ("valid", "absent", "null", "empty", "missing_phase", "missing_event", "missing_reason",
    "extra_private", "phase_private", "event_private", "reason_private", "foreign_identity", "stale_time",
    "phase_number", "event_array", "reason_object", "scalar", "array")


@pytest.mark.parametrize("state", ["retiring", "retired"])
@pytest.mark.parametrize("case", RETIREMENT_CASES)
def test_retirement_failure_retains_actual_state_and_only_shared_sanitized_cause(tmp_path, monkeypatch, capsys, state, case):
    valid = retirement_example()
    value = dict(valid)
    if case.startswith("missing_"): value.pop(case.removeprefix("missing_"))
    elif case == "extra_private": value["sdp"] = "PRIVATE_SDP"
    elif case.endswith("_private"): value[case.removesuffix("_private")] = "PRIVATE_ENUM"
    elif case == "foreign_identity": value["operation_id"] = "PRIVATE_FOREIGN_ID"
    elif case == "stale_time": value["sampled_at_ms"] = 123
    elif case == "phase_number": value["phase"] = 1
    elif case == "event_array": value["event"] = ["PRIVATE_EVENT"]
    elif case == "reason_object": value["reason"] = {"raw": "PRIVATE_REASON"}
    elif case == "null": value = None
    elif case == "empty": value = {}
    elif case == "scalar": value = "PRIVATE_RAW_ERROR"
    elif case == "array": value = [valid]
    def reply(operation):
        result = {"operation_id": operation, "state": state, "pairing_code": "PRIVATE_PAIRING_CODE",
                  "resource": "PRIVATE_RESOURCE", "url": "https://PRIVATE_URL", "raw_error": "PRIVATE_ERROR"}
        if case != "absent": result["retirement"] = value
        return result
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", "retirement", status_reply=reply)
    record = run.record
    assert run.exit_code == 1 and record["passed"] is False
    assert record["error_code"] == "supervisor_pairing_retired" and record["failure_site"] == "pairing_status"
    assert record["phase"] == "direct_supervisor_owned_pairing_windows" and record["workload"] == "full"
    assert record["pairing_state"] == state
    if case == "valid": assert record["pairing_retirement"] == valid
    else: assert "pairing_retirement" not in record
    assert set(record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type",
                           "error_code", "failure_site", "pairing_state"} | ({"pairing_retirement"} if case == "valid" else set())
    assert run.events == ["settings", "begin_offer", "status"]
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("state", ["retiring", "retired"])
def test_foreign_status_identity_cannot_attach_state_or_retirement(tmp_path, monkeypatch, capsys, state):
    value = retirement_example()
    def forbidden_sanitize(_): pytest.fail("Foreign status detail was inspected")
    monkeypatch.setattr(controller, "validated_pairing_retirement", forbidden_sanitize)
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", "foreign_status",
        status_reply=lambda _: {"operation_id": "PRIVATE_FOREIGN_ID", "state": state, "retirement": value})
    assert run.record["error_code"] == "invalid_pairing_identity" and run.record["failure_site"] == "pairing_status"
    assert "pairing_state" not in run.record and "pairing_retirement" not in run.record
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("fault", ["caught_status_then_unrelated", "caught_status_then_success", "caught_status_then_foreign"])
def test_retirement_detail_belongs_only_to_same_active_status_exception(tmp_path, monkeypatch, capsys, fault):
    value = retirement_example()
    calls = []
    def reply(operation):
        calls.append(operation)
        if len(calls) == 1: return {"operation_id": operation, "state": "retired", "retirement": value}
        return {"operation_id": "PRIVATE_OTHER_ID" if fault.endswith("foreign") else operation,
                "state": "retired" if fault.endswith("foreign") else "offer_ready", "retirement": value}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", fault, status_reply=reply)
    assert run.exit_code == 1 and run.record["passed"] is False
    assert "pairing_state" not in run.record and "pairing_retirement" not in run.record
    if fault.endswith("foreign"):
        assert run.record["failure_site"] == "pairing_status" and run.record["error_code"] == "invalid_pairing_identity"
    else:
        assert "failure_site" not in run.record and run.record["failure_type"] == "ValueError"
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("role", ["windows", "android"])
def test_successful_negotiate_report_never_gains_retirement_failure_fields(tmp_path, monkeypatch, capsys, role):
    value = retirement_example()
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, role, "success",
        status_reply=lambda operation: {"operation_id": operation, "state": "offer_ready",
            "pairing_code": "PRIVATE_SIGNED_CODE", "retirement": value})
    assert run.exit_code == 0 and run.record["passed"] is True
    assert not {"failure_site", "pairing_state", "pairing_retirement"} & set(run.record)
    assert "PRIVATE_" not in run.output
    # This intentionally incomplete component fixture cannot qualify native CI.
    with pytest.raises(ValueError): evidence.verify_report(run.record, "a" * 40, "b" * 40, role)
