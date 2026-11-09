"""Concurrent actual packaged peers; artifacts carry encrypted setup/control only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service/src"))

from native_interop_artifacts import GithubArtifacts, context_from_environment
from native_interop_evidence import SCENARIOS, Samples, accounting, digest, selection, traffic
from native_interop_peers import AndroidEmulator, AndroidPeer, PeerFailure, WindowsPeer
from native_interop_preflight import android_environment, outbound_services
from native_interop_rendezvous import Rendezvous
from native_interop_workload import workload as required_workload
from test_packaged_lifecycle import source_identity

OFFERS = {"direct": "offer", **{name: "offer_" + name for name in SCENARIOS[1:5]}}


def selected_ice(value, scenario):
    servers = value.get("iceServers")
    if not isinstance(servers, list):
        raise ValueError("Production ICE configuration is unavailable")
    protocol = "udp" if scenario == "impaired" else scenario.removeprefix("turn_")
    for server in servers:
        urls = server.get("urls", [])
        for url in urls if isinstance(urls, list) else [urls]:
            if not isinstance(url, str):
                continue
            if scenario == "direct" and url.startswith("stun:"):
                return {"iceServers": [{"urls": [url]}], "iceTransportPolicy": "all"}, None
            actual = "tls" if url.startswith("turns:") else "tcp" if "transport=tcp" in url else "udp" if url.startswith("turn:") else None
            if actual == protocol:
                if not server.get("username") or not server.get("credential"):
                    raise ValueError("Short-lived TURN allocation credentials are unavailable")
                return {"iceServers": [{"urls": [url], "username": server["username"], "credential": server["credential"]}],
                        "iceTransportPolicy": "relay"}, url
    raise ValueError("Required ICE transport is not offered by the existing production broker")


def binding(role, source, tree):
    if role == "windows":
        from native_windows_evidence import artifact_binding, verify_report
        binary, value = artifact_binding(source)
        for kind in ("control", "lifecycle"):
            record = json.loads((ROOT / f"dist/reports/native-windows-{kind}.json").read_text())
            verify_report(record, source, tree, kind)
            if any(record[field] != value[field] for field in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")):
                raise ValueError("Retained Windows executable differs from the previously tested native artifact")
        return binary, {field: value[field] for field in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")}
    from android_qualification import APKS, CORE_APKS, CONSUMER_ARTIFACTS, INDEPENDENT_ARTIFACTS
    from connection_matrix import android_evidence
    record = json.loads((ROOT / "dist/reports/android-qualification.json").read_text())
    android_evidence(record, source, tree)
    for path in (*APKS, *CORE_APKS, *CONSUMER_ARTIFACTS, *INDEPENDENT_ARTIFACTS):
        name = path.relative_to(ROOT).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["artifacts"][name]:
            raise ValueError("Retained Android artifact differs from its executed qualification report")
    return None, dict(record["artifacts"])


class Controller:
    def __init__(self, role, peer, transport, rendezvous, context, *, workload="full"):
        self.role, self.peer, self.transport, self.rendezvous, self.context = role, peer, transport, rendezvous, context
        self.partner = "android" if role == "windows" else "windows"
        self.samples = Samples()
        self.deadline = time.monotonic() + 3000
        self.phase = "initialize"
        self.cases, self.cycles = [], []
        self.profile = self.contact = None
        self.identity = None
        self.pairing = None
        self.workload = required_workload(workload)

    def wait(self, action, *, timeout=90, interval=0.25):
        deadline = min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            result = action()
            if result:
                return result
            time.sleep(interval)
        raise PeerFailure("scenario_deadline")

    def core(self, operation, params=None, key=None):
        return self.peer.core(operation, params or {}, key)

    def native(self, command, **payload):
        return self.core("native.command", {"command": command, "payload": payload})

    def snapshot(self):
        return self.core("application.snapshot")

    def publish(self, phase, value):
        self.transport.publish(phase, self.rendezvous.seal(phase, value))

    def receive(self, phase):
        return self.rendezvous.open(phase, self.transport.wait(self.partner, phase, timeout=180))

    def initialize(self):
        from mesh_chat.call_settings import DEFAULT_SIGNAL_MAILBOX_URL, DEFAULT_TURN_BROKER_URL, DEFAULT_STUN_URLS
        self.peer.start()
        profiles = self.core("runtime.capabilities")["profiles"]
        if len(profiles) != 1:
            raise ValueError("Native qualification requires one fresh synthetic profile")
        self.profile = profiles[0]
        fresh = self.snapshot()
        if fresh.get("contacts") or fresh.get("messages"):
            raise ValueError("Initial pairing must not begin with approved contacts or messages")
        accounting(self.peer.inventory().get("host_accounting"), empty=True)
        self.identity = digest(fresh["profile"]["destination_hash"])
        self.core("settings.update", {"profile": self.profile, "settings": {
            "nearby_discovery": False, "lan_fallback": False, "help_route": False}})
        self.default_call_settings = {
            "stun_urls": list(DEFAULT_STUN_URLS), "turn_broker_url": DEFAULT_TURN_BROKER_URL,
            "turn_broker_consent": True, "signal_mailbox_url": DEFAULT_SIGNAL_MAILBOX_URL,
            "turn_url": None, "turn_username": None, "turn_credential": None,
            "relay_only": False, "store_call_signaling": True}
        self.core("call.settings_update", {"profile": self.profile, "settings": self.default_call_settings})
        self.broker_ice = self.core("call.ice_servers", {"profile": self.profile})["ice"]

    def pairing_status(self):
        value = self.peer.pairing_status(self.pairing)
        if value.get("operation_id") != self.pairing:
            raise PeerFailure("invalid_pairing_identity")
        if value.get("state") in {"retired", "retiring"}:
            raise PeerFailure("supervisor_pairing_retired")
        return value

    def negotiate(self, scenario, initiator):
        self.phase = scenario + "_supervisor_owned_pairing_" + initiator
        ice, turn_url = selected_ice(self.broker_ice, scenario)
        server = ice["iceServers"][0]
        settings = {**self.default_call_settings, "turn_broker_url": None, "turn_broker_consent": False,
            "stun_urls": server["urls"] if scenario == "direct" else [], "turn_url": turn_url,
            "turn_username": server.get("username"), "turn_credential": server.get("credential"),
            "relay_only": scenario != "direct"}
        self.core("call.settings_update", {"profile": self.profile, "settings": settings})
        self.pairing = str(uuid4())
        if self.role == initiator:
            admitted = self.peer.pairing_begin(self.pairing, "offer", direct=scenario == "direct")
            if admitted.get("operation_id") != self.pairing: raise PeerFailure("invalid_pairing_identity")
            code = self.wait(lambda: self.pairing_status().get("pairing_code"), timeout=120)
            self.publish(OFFERS[scenario], {"shareable": code})
        else:
            code = self.receive(OFFERS[scenario])["shareable"]
            admitted = self.peer.pairing_begin(self.pairing, "answer", pairing_code=code, direct=scenario == "direct")
            if admitted.get("operation_id") != self.pairing: raise PeerFailure("invalid_pairing_identity")
        def open_session():
            self.pairing_status()
            resources = self.peer.inventory()["resources"]
            if len(resources) != 1: return None
            logical = resources[0]["logical_session"]
            return logical if self.native("native_webrtc_stats", session_id=logical).get("data_channel_state") == "open" else None
        session = self.wait(open_session, timeout=120)
        return session, turn_url

    def approved_contact(self):
        values = self.snapshot().get("contacts", [])
        if len(values) == 1 and values[0].get("trust") in {"approved", "verified"}:
            return values[0]
        return None

    def retired(self):
        inventory = self.peer.inventory()
        counts = accounting(inventory.get("host_accounting"))
        if inventory["resources"] or any(counts[name] for name in ("reserved_count", "creating_count", "allocated_count", "active_count", "retiring_count")):
            return None
        return accounting(counts, empty=True)

    def warm_counts(self):
        counts = accounting(self.peer.inventory().get("host_accounting"))
        return counts if counts["active_count"] > 0 and counts["creating_count"] == counts["retiring_count"] == 0 else None

    def pair(self, session, initiator):
        self.phase = "explicit_contact_approval"
        if self.role == initiator:
            # The production supervisor sends the signed contact invitation;
            # the controller supplies only each person's explicit decision.
            pending = self.wait(lambda: next((item for item in self.snapshot().get("contacts", []) if item.get("trust") == "pending_request"), None))
            self.core("peer.approve", {"profile": self.profile, "peer": pending["core_handle"]})
        else:
            pending = self.wait(lambda: next((item for item in self.snapshot().get("contact_invitations", []) if item.get("state") == "pending"), None))
            if self.snapshot().get("contacts"):
                raise ValueError("Receiving the signed invitation silently created contact approval")
            self.core("contact.invitation", {"profile": self.profile, "action": "decide", "invitation": pending["id"], "accept": True})
        self.contact = self.wait(self.approved_contact)
        self.native("reconnect_consent_set", contact_id=self.contact["id"], auto_reconnect=False,
                    allow_direct_ip_disclosure=True)
        self.wait(lambda: self.observe(session, ready=True), timeout=120)
        if self.role == "android": self.publish("approved", {"approved": True})
        elif self.receive("approved") != {"approved": True}: raise ValueError("Peer approval was not explicit")

    def observe(self, logical=None, *, ready=True, scenario=None):
        inventory = self.peer.inventory()
        resources = [item for item in inventory["resources"] if logical is None or item["logical_session"] == logical]
        for resource in resources:
            requested = time.monotonic()
            value = self.peer.path(resource["logical_session"], resource["physical_resource"])
            if ready and any(value.get(field) is not True for field in ("adopted", "attached", "messaging_ready")):
                continue
            if value.get("status") != "selected":
                continue
            return self.samples.consume(value, inventory, requested, ready=ready, scenario=scenario)
        return None

    def text(self, scenario, index=0, *, sender=None, padded=False):
        value = f"mesh-native-ci:{self.context['run_id']}:{self.context['run_attempt']}:{scenario}:{index}:{sender or self.role}"
        # Retained snapshots for the entire matrix must remain inside the
        # production Core frame budget; impairment acts on real kernel packets.
        return value + (":" + "x" * 1024 if padded else "")

    def enqueue(self, text):
        result = self.core("message.enqueue", {"profile": self.profile, "recipient": self.contact["core_handle"],
            "kind": "text", "text": text}, uuid4().hex)
        if result.get("accepted") is not True:
            raise ValueError("Core did not durably accept the message")
        return result["message"]

    def delivered(self, handle):
        return self.core("message.query", {"profile": self.profile, "message": handle})["state"] == "delivered"

    def records(self, text, direction):
        return [item for item in self.snapshot().get("messages", []) if item.get("kind") == "chat"
                and item.get("text") == text and item.get("direction") == direction]

    def exchange(self, scenario, index=0, *, padded=False):
        own, other = self.text(scenario, index, padded=padded), self.text(scenario, index, sender=self.partner, padded=padded)
        started = time.monotonic()
        handle = self.enqueue(own)
        self.wait(lambda: self.delivered(handle), timeout=90)
        inbound = self.wait(lambda: self.records(other, "inbound"), timeout=90)
        outbound = self.records(own, "outbound")
        if len(inbound) != 1 or len(outbound) != 1 or not outbound[0].get("native_message_id"):
            raise ValueError("Native receipt exchange duplicated or lacks native delivery identity")
        return {"outbound": digest(outbound[0]["id"]), "inbound": digest(inbound[0]["id"]),
                "authenticated_receipt": True, "inbound_records": 1, "outbound_records": 1,
                "receipt_roundtrip_ms": (time.monotonic() - started) * 1000}, handle

    def negative(self, fault, scenario):
        self.phase = scenario + "_kernel_block_negative_control"
        if fault is not None:
            fault.block()
            self.publish("negative_ready_" + scenario, {"approved": True})
        elif self.receive("negative_ready_" + scenario) != {"approved": True}:
            raise ValueError("Kernel block admission was not acknowledged")
        handle = self.enqueue(self.text("blocked_path_" + scenario))
        until = time.monotonic() + 2
        while time.monotonic() < until:
            if self.delivered(handle):
                raise ValueError("Authenticated receipt arrived while the selected kernel path was blocked")
            time.sleep(0.1)
        packets = None
        if fault is not None:
            if self.receive("negative_checked_" + scenario) != {"approved": True}:
                raise ValueError("Remote blocked-path observation is missing")
            packets = fault.unblock()
            if packets <= 0:
                raise ValueError("Negative control has no actual dropped packets")
        else:
            self.publish("negative_checked_" + scenario, {"approved": True})
        self.wait(lambda: self.delivered(handle), timeout=90)
        inbound = self.wait(lambda: self.records(self.text("blocked_path_" + scenario, sender=self.partner), "inbound"), timeout=90)
        outbound = self.records(self.text("blocked_path_" + scenario), "outbound")
        if len(inbound) != 1 or len(outbound) != 1:
            raise ValueError("Blocked-path recovery duplicated the queued durable message")
        return {"blocked_packets": packets, "delivered_while_blocked": False, "delivered_after_restore": True,
                "kernel_protocol": fault.protocol if fault is not None else None,
                "kernel_socket": digest(fault.socket) if fault is not None else None,
                "outbound": digest(outbound[0]["id"]), "inbound": digest(inbound[0]["id"])}

    def path_case(self, scenario, initiator):
        session, url = self.negotiate(scenario, initiator)
        if self.contact is None: self.pair(session, initiator)
        self.wait(lambda: self.pairing_status().get("state") == "transferred", timeout=120)
        adopted = self.wait(lambda: self.observe(session, ready=True, scenario=scenario), timeout=120)
        cancelled = self.peer.pairing_cancel(self.pairing)
        if cancelled.get("operation_id") != self.pairing or cancelled.get("state") != "transferred":
            raise ValueError("Retired pairing intent tried to reclaim its transferred carrier")
        before = self.wait(lambda: self.observe(session, ready=True, scenario=scenario), timeout=120)
        if any(adopted[name] != before[name] for name in
               ("resource", "logical_session", "adapter_epoch", "service_incarnation")):
            raise ValueError("Transferred pairing cancellation replaced its adopted carrier")
        self.phase = scenario + "_authenticated_receipts"
        fault, impairment = None, None
        try:
            if scenario in {"turn_tcp", "turn_tls", "impaired"} and self.role == "android":
                from native_interop_faults import AndroidKernelPath
                fault = AndroidKernelPath(self.peer, before, url)
            if scenario == "impaired":
                if self.role == "android":
                    fault.install()
                    self.publish("impaired_ready", {"approved": True})
                elif self.receive("impaired_ready") != {"approved": True}:
                    raise ValueError("Actual kernel impairment admission is missing")
            messages = [self.exchange(scenario + ":" + initiator, index, padded=scenario == "impaired")[0]
                        for index in range(20 if scenario == "impaired" else 1)]
            negative = self.negative(fault, scenario) if scenario in {"turn_tcp", "turn_tls", "impaired"} else None
            after = self.observe(session, ready=True, scenario=scenario)
            if after is None: raise ValueError("Native selected path disappeared after receipt delivery")
            if fault is not None and scenario == "impaired": impairment = fault.report()
            if scenario == "impaired" and self.role == "android" and (
                    before["pair"]["rtt_ms"] is None or after["pair"]["rtt_ms"] is None):
                raise ValueError("Actual selected-pair baseline/impaired RTT is unavailable")
            self.cases.append({"scenario": scenario, "initiator": initiator, "supervisor_pairing": {
                "operation": digest(self.pairing), "role": "offer" if self.role == initiator else "answer", "state": "transferred",
                "transferred_cancel_preserves_carrier": True},
                "before": selection(before), "after": selection(after),
                "native_delta": traffic(before, after), "messages": messages, "impairment": impairment, "negative": negative})
        finally:
            if fault is not None: fault.close()
        self.phase = scenario + "_native_lease_retirement"
        self.native("native_webrtc_close", session_id=session)
        self.cases[-1]["retired_host_accounting"] = self.wait(self.retired, timeout=30)

    def cold_starts(self):
        self.phase = "cold_start_receipts"
        self.core("call.settings_update", {"profile": self.profile, "settings": self.default_call_settings})
        self.native("reconnect_consent_set", contact_id=self.contact["id"], auto_reconnect=True,
                    allow_direct_ip_disclosure=True)
        previous_message = None
        warm_resources = None
        warm_host = None
        for index in range(self.workload["iterations"]):
            previous = self.peer.inventory()["service_incarnation"]
            restarted = index % self.workload["cold_start_every"] == 0
            if restarted:
                self.peer.stop(crash=True)
                current = self.peer.start()
                if current["service_incarnation"] == previous:
                    raise ValueError("Cold start reused the previous service incarnation")
                self.profile = self.core("runtime.capabilities")["profiles"][0]
                self.contact = self.wait(self.approved_contact)
            else:
                current = self.peer.inventory()
            if digest(self.snapshot()["profile"]["destination_hash"]) != self.identity:
                raise ValueError("Cold start replaced the durable profile identity")
            if previous_message is not None and not self.delivered(previous_message):
                raise ValueError("Authenticated receipt did not survive the real process restart")
            before = self.wait(lambda: self.observe(ready=True), timeout=120)
            message, previous_message = self.exchange("cold_start_receipts", index)
            after = self.observe(before["logical_session"], ready=True)
            if after is None: raise ValueError("Cold-start receipt lost its exact native resource")
            resources = len(self.peer.inventory()["resources"])
            host_counts = self.wait(self.warm_counts, timeout=30)
            if warm_host is None: warm_host = host_counts
            if host_counts != warm_host:
                raise ValueError("Native retained allocation leases departed from the warm baseline")
            if warm_resources is None: warm_resources = resources
            if resources != warm_resources or resources <= 0:
                raise ValueError("Native resource accounting departed from the warm baseline")
            self.cycles.append({"iteration": index + 1, "cold_start": restarted, "native_resources": resources,
                "warm_baseline_resources": warm_resources, "previous_service": digest(previous),
                "host_accounting": host_counts, "warm_baseline_host_accounting": warm_host,
                "current_service": digest(current["service_incarnation"]), "identity": self.identity,
                "before": selection(before), "after": selection(after), "native_delta": traffic(before, after), "message": message})

    def run(self):
        self.initialize()
        self.transport.publish("key", self.rendezvous.public_manifest())
        self.rendezvous.bind_partner(self.transport.wait(self.partner, "key", timeout=900))
        # Both roles execute this fixed source-bound inventory. Keep bootstrap
        # uploads <=9/job, leaving room for the final retained report artifact.
        for scenario, initiator in self.workload["paths"]: self.path_case(scenario, initiator)
        self.cold_starts()
        self.phase = "clean_host_retirement"
        self.native("reconnect_consent_set", contact_id=self.contact["id"], auto_reconnect=False,
                    allow_direct_ip_disclosure=True)
        for resource in self.peer.inventory()["resources"]:
            self.native("native_webrtc_close", session_id=resource["logical_session"])
        final_accounting = self.wait(self.retired, timeout=30)
        webviews = 0
        if self.role == "windows":
            from check_native_windows_messaging import descendants
            webviews = sum("webview" in name for name in descendants(self.peer.process.pid))
            if webviews: raise ValueError("Native Windows messaging launched a WebView process")
        if self.role == "android": self.peer.stop(delete_profile=True)
        else: self.peer.stop()
        return {"identity": self.identity, "scenarios": self.cases, "receipt_iterations": self.cycles,
                "processes_started": self.peer.processes_started, "forced_exits": self.peer.forced_exits,
                "clean_exits": self.peer.clean_exits, "webview_processes": webviews,
                "final_host_accounting": final_accounting, "cleanup": "passed"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("windows", "android"))
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--workload", required=True, choices=("quick", "full"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = required_workload(args.workload)
    result = {"v": 1, "passed": False, "evidence_level": plan["level"], "role": args.role, "scope": plan["scope"], "workload": args.workload}
    peer = transport = rendezvous = controller = emulator = None
    phase = "source_artifact_binding"
    try:
        source, tree = source_identity(args.expected_source)
        from connection_ci import current_plan
        if current_plan()["native_workload"] != args.workload:
            raise ValueError("Native workload differs from source-bound event selection")
        context = context_from_environment()
        if context["source_commit"] != source: raise ValueError("Workflow source differs from checkout")
        binary, artifacts = binding(args.role, source, tree)
        phase = "platform_outbound_preflight"
        if args.role == "android":
            from android_qualification import APKS
            emulator = AndroidEmulator()
            emulator.start(APKS)
        platform = {"windows": True} if args.role == "windows" else android_environment()
        preflight = outbound_services()
        key = os.urandom(32)
        if args.role == "windows":
            parent = ROOT / ".test-tmp/native-interop-private"
            parent.mkdir(parents=True, exist_ok=True)
            peer = WindowsPeer(binary, parent / ("mesh-qualification-" + uuid4().hex), key)
        else:
            peer = AndroidPeer(key)
        transport = GithubArtifacts(context, args.role, ROOT / ".test-tmp/native-interop-rendezvous")
        rendezvous = Rendezvous(context, args.role)
        controller = Controller(args.role, peer, transport, rendezvous, context, workload=args.workload)
        execution = controller.run()
        if source_identity(source) != (source, tree): raise ValueError("Source changed during native qualification")
        result.update(passed=True, context=context, source_commit=source, source_tree=tree,
                      platform=platform, preflight=preflight, artifacts=artifacts, execution=execution)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    except Exception as error:
        result = {"v": 1, "passed": False, "evidence_level": plan["level"], "role": args.role, "scope": plan["scope"], "workload": args.workload,
                  "phase": controller.phase if controller is not None else phase, "failure_type": type(error).__name__}
        if isinstance(error, PeerFailure): result["error_code"] = error.code
        elif isinstance(getattr(error, "code", None), str): result["error_code"] = PeerFailure(error.code).code
    finally:
        if peer is not None and peer.process is not None:
            try: peer.stop(crash=True)
            except Exception: result["cleanup_failed"] = True
        if rendezvous is not None: rendezvous.close()
        if transport is not None: transport.close()
        if emulator is not None:
            try: emulator.close()
            except Exception:
                result.update(passed=False, cleanup_failed=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "role", "evidence_level")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
