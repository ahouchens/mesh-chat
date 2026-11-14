"""Public partition behavior and aggregate evidence stay separate from gateway echo."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check_public_core_pair as fresh
import public_core_partition_controller as controller
import public_core_partition_evidence as evidence
from public_core_partition_flow import PartitionFlow, digest, text


PAIR_ID = "a" * 32


class Clock:
    def __init__(self): self.now = 0.0
    def clock(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Fault:
    def __init__(self, peer, drops=2): self.peer, self.blocked, self.drop_count = peer, False, drops
    def block(self): self.blocked = True
    def dropped(self): return self.drop_count
    def unblock(self):
        self.peer.restored = True
        self.blocked = False
        return {"app_uid_bound": True, "process_bound": True, "owned_route": True,
                "profile_restored": True, "dropped_packets": self.drop_count}


class Exchange:
    def __init__(self, peer, clock=None, restore_marker_delay=0):
        self.peer, self.phases = peer, []
        self.clock, self.restore_marker_delay = clock, restore_marker_delay
    def publish(self, phase, payload, deadline):
        assert payload == {} and deadline > 0
        if phase == "partition_restored" and self.restore_marker_delay:
            self.clock.sleep(self.restore_marker_delay)
        self.phases.append(("publish", phase))
    def receive(self, phase, deadline):
        assert deadline > 0
        self.phases.append(("receive", phase))
        if phase == "partition_restored": self.peer.restored = True
        return {}


class Peer:
    def __init__(self, role, *, premature=False, duplicate=False, changed_authority=False):
        self.role, self.other = role, "android" if role == "windows" else "windows"
        self.restored, self.sent = False, False
        self.premature, self.duplicate = premature, duplicate
        self.changed_authority = changed_authority
        self.calls = []

    def request(self, operation, params=None, key=None):
        self.calls.append((operation, params, key))
        if operation == "runtime.capabilities": return {"profiles": ["profile-1"]}
        if operation == "profile.query":
            return {"destination": "changed" if self.changed_authority and self.sent and self.restored else "identity",
                    "connections": ["connection-1"]}
        if operation == "connection.snapshot": return {"observation": {"messaging_ready": self.restored}}
        if operation == "message.enqueue":
            assert key and params["text"] == text(PAIR_ID, self.role)
            self.sent = True
            return {"accepted": True, "message": "message-1"}
        if operation == "message.query":
            return {"message": "message-1", "text": text(PAIR_ID, self.role),
                    "recipient": "peer-1", "state": "delivered" if self.restored or self.premature else "pending"}
        if operation == "application.snapshot":
            rows = []
            if self.sent:
                rows.append({"kind": "chat", "direction": "outbound", "text": text(PAIR_ID, self.role),
                             "contact_id": "contact-1", "state": "delivered" if self.restored else "pending"})
                if self.restored:
                    rows.append({"kind": "chat", "direction": "inbound", "text": text(PAIR_ID, self.other),
                                 "contact_id": "contact-1"})
                    if self.duplicate: rows.append(dict(rows[-1]))
            return {"contacts": [{"id": "contact-1", "core_handle": "peer-1", "trust": "approved"}],
                    "messages": rows}
        raise AssertionError(operation)


def run_flow(role, *, drops=2, restore_marker_delay=0, **kwargs):
    clock, peer = Clock(), Peer(role, **kwargs)
    exchange = Exchange(peer, clock, restore_marker_delay)
    fault = Fault(peer, drops) if role == "android" else None
    row = PartitionFlow(role, peer, exchange, PAIR_ID, 600, fault, clock.clock, clock.sleep).run()
    return row, exchange.phases


def baseline(role, pair_id):
    other = "android" if role == "windows" else "windows"
    return {"v": 1, "role": role, "pair_id": pair_id,
            "self_destination_sha256": digest("identity-" + role),
            "peer_destination_sha256": digest("identity-" + other),
            "explicit_decision": "request_approved" if role == "windows" else "invitation_accepted",
            "contact_count": 1, "contact_trust": "approved", "messaging_ready": True,
            "pairing_transferred": True, "cancel_preserved_transferred": True,
            "outbound_text_sha256": fresh.text_digest(pair_id, role),
            "outbound_message_count": 1, "outbound_delivered": True,
            "inbound_text_sha256": fresh.text_digest(pair_id, other),
            "inbound_message_count": 1, "public_request_count": 20}


def gateway_witness():
    return {"namespace": "owned_linux_network_namespace", "emulator_pid_bound": True,
            "adb_pid_bound": True, "cleanup": "passed", "impairment": {
                "kind": "android_emulator_host_gateway_tc_netem", "delay_ms_each_way": 75,
                "jitter_ms_each_way": 10, "loss_percent_each_way": .1, "added_nominal_rtt_ms": 150,
                "link_scope": "owned_host_namespace_veth", "loss_observed": True,
                "counters": {direction: {"bytes": 200, "packets": 2, "dropped": 1}
                             for direction in ("egress", "ingress")},
                "gateway_coverage": {"external_links": 1, "namespace_bound": True,
                    "ipv6_disabled": True, "veth_identity_current": True,
                    "directional_veth_packets": {"egress": 2, "ingress": 2}}}}


def reports():
    fields = {"repository": "ahouchens/mesh-chat", "repository_id": 123,
              "run_id": 456, "run_attempt": 1, "source_commit": "a" * 40}
    context = {**fields, "pair_id": fresh.pair_id_for(fields)}
    tree = "b" * 40
    inputs = {"windows": {"sdk_sha256": "c" * 64}, "android": {"apk_sha256": "d" * 64}}
    values = {}
    for role in fresh.ROLES:
        partition, _ = run_flow(role)
        partition["pair_id"] = context["pair_id"]
        partition["outbound_text_sha256"] = digest(text(context["pair_id"], role))
        partition["inbound_text_sha256"] = digest(text(context["pair_id"],
                                                   "android" if role == "windows" else "windows"))
        values[role] = {"v": 1, "passed": True, "evidence_level": evidence.LEVEL,
            "scenario": evidence.SCENARIO, "scope": evidence.SCOPE, "role": role,
            "context": context, "source_tree": tree,
            "flow": {"baseline": baseline(role, context["pair_id"]), "partition": partition},
            "inputs": inputs[role], "session": {"finished": True, "cleanup": True, "fault_closed": True},
            "gateway": gateway_witness() if role == "android" else None, "duration_seconds": 200.0}
    needs = {name: {"result": "success"} for name in fresh.JOBS}
    return values, context, tree, inputs, needs


def test_public_roles_queue_under_loss_and_recover_once_with_authority():
    android, phases = run_flow("android")
    windows, _ = run_flow("windows")
    assert 30_000 <= android["block_duration_ms"] <= 45_000
    assert android["fault_witness"]["dropped_packets"] > 0
    assert windows["fault_witness"] is None
    assert all(row["authority_unchanged"] and row["no_receipt_during_block"]
               and row["outbound_delivered"] for row in (android, windows))
    assert phases.index(("publish", "partition_blocked")) < phases.index(("publish", "partition_restored"))


def test_android_recovery_clock_starts_before_restored_marker_publish():
    android, _ = run_flow("android", restore_marker_delay=7)
    assert android["readiness_bound_origin"] == "fault_unblock"
    assert android["readiness_after_origin_ms"] >= 7_000


@pytest.mark.parametrize("condition", ["premature", "duplicate", "changed_authority"])
def test_public_partition_refuses_false_receipt_duplicate_or_authority_change(condition):
    with pytest.raises(ValueError):
        run_flow("android", **{condition: True})


def test_zero_app_uid_drops_cannot_pass_as_packaged_partition():
    with pytest.raises(ValueError, match="public_partition_no_app_packets_dropped"):
        run_flow("android", drops=0)


def test_exact_aggregate_requires_gateway_cleanup_and_never_promotes_selected_path():
    values, context, tree, inputs, needs = reports()
    assert evidence.verify_pair_reports(values["windows"], values["android"], context, tree, inputs, needs)
    altered = deepcopy(values["android"])
    altered["gateway"] = None
    with pytest.raises(ValueError, match="public_partition_gateway"):
        evidence.verify_role_report(altered, "android", context, tree, inputs["android"])
    altered = deepcopy(values["android"])
    altered["flow"]["partition"]["selected_path_qualified"] = True
    with pytest.raises(ValueError, match="public_partition_flow"):
        evidence.verify_role_report(altered, "android", context, tree, inputs["android"])
    altered = deepcopy(values["android"])
    altered["gateway"]["impairment"]["counters"]["egress"]["packets"] = 0
    with pytest.raises(ValueError, match="public_partition_impairment"):
        evidence.verify_role_report(altered, "android", context, tree, inputs["android"])
    needs["android"] = {"result": "skipped"}
    with pytest.raises(ValueError, match="public_partition_prerequisites"):
        evidence.verify_pair_reports(values["windows"], values["android"], context, tree, inputs, needs)


def test_cross_role_partition_message_digest_must_match():
    values, context, tree, inputs, needs = reports()
    changed = deepcopy(values["android"])
    changed["flow"]["partition"]["inbound_text_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        evidence.verify_pair_reports(values["windows"], changed, context, tree, inputs, needs)


def test_android_controller_binds_fault_after_installed_open_and_requires_rule_cleanup(monkeypatch, tmp_path):
    events = []
    fields = {"repository": "ahouchens/mesh-chat", "repository_id": 123,
              "run_id": 456, "run_attempt": 1, "source_commit": "a" * 40}
    context = {**fields, "pair_id": fresh.pair_id_for(fields)}
    class PeerSession:
        deadline = float("inf")
        def open(self): events.append("open")
        def close(self): events.append("peer_close"); return True
    class FaultSession:
        def bind(self, peer): assert peer is session; events.append("bind")
        def close(self): events.append("fault_close"); return False
    class ExchangeSession:
        def connect(self, deadline): assert deadline > 0; events.append("connect")
        def close(self): events.append("exchange_close")
    session, fault = PeerSession(), FaultSession()
    monkeypatch.setenv("PUBLIC_PAIR_SCENARIO", "partition")
    monkeypatch.setattr(controller.installed, "admitted_context", lambda *args: context)
    monkeypatch.setattr(controller.installed, "runner_temp", lambda: tmp_path)
    monkeypatch.setattr(controller.baseline_evidence, "source_identity", lambda source: (source, "b" * 40))
    monkeypatch.setattr(controller.installed, "producer_inputs", lambda *args: {"artifact": "bound"})
    monkeypatch.setattr(controller.installed, "verify_downloads", lambda *args: None)
    monkeypatch.setattr(controller.installed, "create_exchange", lambda *args: ExchangeSession())
    monkeypatch.setattr(controller.installed, "create_peer", lambda *args: session)
    monkeypatch.setattr(controller, "run_partition_role", lambda *args, **kwargs: (
        events.append("flow") or {"baseline": {"public_request_count": 20},
                                   "partition": {"additional_request_count": 10}}))
    monkeypatch.setattr(controller.evidence, "verify_partition_flow", lambda *args: None)
    monkeypatch.setattr(controller.installed, "finish_peer", lambda *args: events.append("finish"))
    result = controller.run("android", "a" * 40, "emulator-5554", fault=fault)
    assert result["passed"] is False and result["session"]["fault_closed"] is False
    assert events.index("open") < events.index("bind") < events.index("flow") < events.index("finish")
    assert events.index("fault_close") < events.index("peer_close")
