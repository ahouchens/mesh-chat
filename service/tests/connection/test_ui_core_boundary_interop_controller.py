"""Controller/evidence component checks; synthetic reports are never CI proof."""

from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_evidence as evidence
from native_interop_rendezvous import APPROVAL_PHASES, OFFER_PHASES, checked_payload


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


@pytest.mark.parametrize("role,fault,site,error_type", [
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
])
def test_actual_failure_report_selects_only_active_literal_call_site(tmp_path, monkeypatch, capsys, role, fault, site, error_type):
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
        if fault == "caught_then_unrelated":
            with pytest.raises(controller.PeerFailure): instance.negotiate("direct", "windows")
        else:
            instance.negotiate("direct", "windows")
        error = ValueError("PRIVATE_LATER_EXCEPTION/SDP/KEY")
        error.failure_site = "PRIVATE_CALLER_SUPPLIED_SITE"
        raise error

    context = {"source_commit": "a" * 40}
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: context)
    monkeypatch.setattr(controller, "binding", lambda *_: (Path("unused.exe"), {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *_: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: Peer())
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: Peer())
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: Transport())
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: Rendezvous())
    monkeypatch.setattr(controller.Controller, "run", negotiate_only)
    output = tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", ["native_interop_controller", "--role", role, "--expected-source", "a" * 40,
                                      "--workload", "full", "--output", str(output)])
    assert controller.main() == 1
    record = json.loads(output.read_text())
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
    assert set(record) == fields
    success_path = (["settings", "begin_offer", "status", "publish", "status", "inventory", "stats"] if role == "windows"
                    else ["settings", "receive", "begin_answer", "status", "inventory", "stats"])
    assert events == success_path[:len(events)]  # No added/reordered/repeated requests.
    if fault == "after_success": assert events == success_path
    captured = capsys.readouterr()
    assert "PRIVATE_" not in output.read_text() + captured.out + captured.err
