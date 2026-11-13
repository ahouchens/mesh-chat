"""Concurrent actual packaged peers; artifacts carry encrypted setup/control only."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service/src"))

from mesh_chat.connection.diagnostics import validated_gather_for_retirement, validated_pairing_retirement
from native_interop_artifacts import GithubArtifacts, RendezvousUnavailable, context_from_environment
from native_interop_evidence import SCENARIOS, SAMPLE_REJECTION_REASONS, Samples, accounting, digest, selection, traffic
from native_interop_faults import NativePathDiagnostics, path_failure_observation, path_stage
from native_interop_diagnostics import (NegativeControlDiagnostics, PreflightDiagnostics, RecoveryDeliveryDiagnostics,
    final_path_missing_observation, final_path_missing_reason, negative_control_error, negative_control_observation,
    negative_control_stage, record_final_path_skip, recovery_delivery_observation, rendezvous_observation,
    reset_negative_control)
from native_interop_peers import AndroidEmulator, AndroidPeer, PeerFailure, WindowsPeer
from native_interop_core_observation import core_failure_observation
from native_interop_preflight import (DEFAULT_SIGNAL_MAILBOX_URL, android_environment,
    android_network_diagnostic, outbound_services)
from native_interop_rendezvous import Rendezvous, checked_payload
from native_interop_workload import workload as required_workload
from test_packaged_lifecycle import source_identity

OFFERS = {"direct": "offer", **{name: "offer_" + name for name in SCENARIOS[1:5]}}
FAILURE_SITES = frozenset({"negotiate_settings_update", "pairing_offer_begin", "pairing_answer_begin",
    "pairing_status", "rendezvous_receive", "rendezvous_publish", "negotiate_inventory", "negotiate_native_stats",
    "initialize_peer_start", "initialize_runtime_capabilities", "initialize_snapshot", "initialize_inventory",
    "initialize_settings_update", "initialize_call_settings_update", "initialize_ice_servers",
    "initialize_key_publish", "initialize_key_wait", "initialize_key_bind"})
FAILURE_SUBSTAGES = frozenset({
    "pending_contact_wait", "implicit_contact_guard", "contact_decision", "approved_contact_wait",
    "reconnect_consent", "approval_ready_observation", "approval_acknowledgment", "transferred_status_wait",
    "adopted_observation", "transferred_cancel", "transferred_cancel_check", "post_cancel_observation",
    "carrier_identity_check", "path_inventory", "path_read", "path_validation",
})
RETIREMENT_COUNTS = ("reserved_count", "creating_count", "allocated_count", "active_count", "retiring_count")
RETIREMENT_STAGES = frozenset({"prepare", "completion_publish", "completion_receive", "commit", "poll"})
PAIRING_OPEN_LABELS = {
    "status": frozenset({"reserved", "offer_ready", "awaiting_approval", "transferred", "unknown"}),
    "resources": frozenset({"unread", "zero", "one", "multiple"}),
    "ice": frozenset({"unread", "new", "checking", "connected", "completed", "disconnected", "failed", "closed", "unknown"}),
    "channel": frozenset({"unread", "connecting", "open", "closing", "closed", "unknown"}),
}


def pairing_open_observation(value):
    """Copy only fixed labels from a controller poll into the public report."""
    if (type(value) is not dict or set(value) != set(PAIRING_OPEN_LABELS)
            or any(type(value[name]) is not str or value[name] not in labels
                   for name, labels in PAIRING_OPEN_LABELS.items())):
        return None
    return {name: value[name] for name in PAIRING_OPEN_LABELS}


def pairing_open_label(value, labels):
    return value if type(value) is str and value in labels else "unknown"


def retirement_failure_snapshot(value):
    fields = {"scenario", "initiator", "stage", "polls", "polls_capped", "last_observation"}
    if (type(value) is not dict or set(value) != fields
            or type(value["scenario"]) is not str or value["scenario"] not in SCENARIOS[:5]
            or type(value["initiator"]) is not str or value["initiator"] not in {"windows", "android"}
            or type(value["stage"]) is not str or value["stage"] not in RETIREMENT_STAGES
            or type(value["polls"]) is not int or not 0 <= value["polls"] <= 128
            or type(value["polls_capped"]) is not bool or (value["polls_capped"] and value["polls"] != 128)):
        return None
    last = value["last_observation"]
    if value["stage"] != "poll" and (value["polls"] != 0 or value["polls_capped"] or last is not None): return None
    if last is not None:
        if (value["polls"] == 0 or type(last) is not dict
                or set(last) != {"state", "resource_count", "resources_capped", "counts"}
                or type(last["state"]) is not str or last["state"] not in {"pending", "acknowledged"}
                or type(last["resource_count"]) is not int or not 0 <= last["resource_count"] <= 16
                or type(last["resources_capped"]) is not bool or (last["resources_capped"] and last["resource_count"] != 16)
                or type(last["counts"]) is not dict or set(last["counts"]) != set(RETIREMENT_COUNTS)
                or any(type(number) is not int or not 0 <= number <= 16 for number in last["counts"].values())):
            return None
        last = {**last, "counts": dict(last["counts"])}
    return {**value, "last_observation": last}


def carrier_retirement_state(value, request_id, *, admission=None):
    if (type(value) is not dict or set(value) != {"request_id", "state"}
            or type(value["request_id"]) is not str or value["request_id"] != request_id
            or type(value["state"]) is not str
            or value["state"] not in ({admission} if admission is not None else {"pending", "acknowledged"})):
        raise PeerFailure("invalid_carrier_retirement_reply")
    return value["state"]


def reconnect_association(profile, contact):
    fields = ("id", "contact_id", "destination_hash", "local_device_id", "remote_device_id")
    if (type(profile) is not dict
            or any(type(profile.get(name)) is not str or not profile[name] for name in fields)
            or profile["contact_id"] != contact["id"] or profile["destination_hash"] != contact["destination_hash"]
            or profile.get("auto_reconnect") is not True):
        raise ValueError("Cold-start reconnect consent has inconsistent association")
    return {name: profile[name] for name in fields}


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
    def __init__(self, role, peer, transport, rendezvous, context, *, workload="full", coverage_factory=None):
        self.role, self.peer, self.transport, self.rendezvous, self.context = role, peer, transport, rendezvous, context
        self.coverage_factory = coverage_factory
        self.partner = "android" if role == "windows" else "windows"
        self.samples = Samples()
        self.deadline = time.monotonic() + 3000
        self.phase = "initialize"
        self.cases, self.cycles = [], []
        self.profile = self.contact = None
        self.identity = None
        self.pairing = None
        self._operation_failure: tuple[Exception, str] | None = None
        self._pairing_failure: tuple[Exception, str, dict[str, str] | None,
                                     dict[str, str] | None] | None = None
        self._pairing_open_context = None
        self._pairing_open_active = False
        self._pairing_open_last = None
        self._pairing_open_failure = None
        self._substage_failure: tuple[Exception, str] | None = None
        self._retirement_context = self._retirement_failure = None
        self._path_diagnostics = None
        self._final_path_failure = None
        self._fault_cleanup_failure = None
        self._recovery_diagnostics = self._recovery_failure = None
        try: self._negative_diagnostics = NegativeControlDiagnostics()
        except Exception: self._negative_diagnostics = None
        self.workload = required_workload(workload)

    @contextmanager
    def _failure_scope(self, site):
        if site not in FAILURE_SITES:
            raise ValueError("Unknown native diagnostic site")
        self._operation_failure = None
        self._pairing_failure = None
        self._substage_failure = None
        self._retirement_failure = None
        try:
            yield
        except Exception as error:
            # Keep exception identity only in RAM. A later, unrelated error
            # must not inherit the label of a previous call or caught failure.
            self._operation_failure = error, site
            raise
        else:
            self._operation_failure = None
            self._pairing_failure = None
            self._substage_failure = None

    @contextmanager
    def _substage(self, stage):
        self._substage_failure = None
        if type(stage) is not str or stage not in FAILURE_SUBSTAGES:
            raise ValueError("Unknown native diagnostic substage")
        try:
            yield
        except Exception as error:
            observed = self._substage_failure
            if observed is None or observed[0] is not error:
                self._substage_failure = error, stage
            raise
        else:
            self._substage_failure = None

    def failure_observation(self, error):
        observed = self._substage_failure
        if (observed is None or observed[0] is not error or type(observed[1]) is not str
                or observed[1] not in FAILURE_SUBSTAGES):
            return {}
        selected = {"failure_substage": observed[1]}
        if observed[1] == "path_validation":
            reason = self.samples.failure_reason(error)
            if type(reason) is str and reason in SAMPLE_REJECTION_REASONS:
                selected["sample_rejection_reason"] = reason
        return selected

    def failure_site(self, error):
        observed = self._operation_failure
        return observed[1] if observed is not None and observed[0] is error and observed[1] in FAILURE_SITES else None

    def failure_core(self, error):
        try:
            if self.role != "android" or type(error) is not PeerFailure or error.code != "internal": return {}
            provider = getattr(self.peer, "core_failure_observation", None)
            selected = core_failure_observation(provider(error)) if callable(provider) else None
            return {"core_failure_observation": selected} if selected is not None else {}
        except Exception:
            return {}

    def failure_network(self, error, observation, site):
        """Optional CI environment facts after the primary Core failure has escaped."""
        try:
            if (self.role != "android" or type(error) is not PeerFailure or error.code != "internal"
                    or site != "initialize_ice_servers"
                    or observation != {"v": 1, "operation": "ice_servers", "stage": "broker_open",
                        "category": "network_unavailable", "cause": "name_resolution"}):
                return {}
            provider = getattr(self.peer, "network_diagnostic", None)
            remaining = self.deadline - time.monotonic()
            if not callable(provider) or remaining < 0.1: return {}
            selected = android_network_diagnostic(provider(timeout=min(2.0, remaining)))
            return {"android_network_diagnostic": selected} if selected is not None else {}
        except Exception:
            return {}

    def failure_retirement(self, error):
        try:
            observed = self._retirement_failure
            if observed is None or observed[0] is not error: return {}
            selected = retirement_failure_snapshot(observed[1])
            return {"carrier_retirement_failure": selected} if selected is not None else {}
        except Exception:
            return {}

    def failure_negative_control(self, error):
        try:
            observer = self._negative_diagnostics
            if type(observer) is not NegativeControlDiagnostics or observer._disabled is not False:
                return {}
            record = observer._failure
            if type(record) is not tuple or len(record) != 2 or record[0] is not error:
                return {}
            selected = negative_control_observation(observer.failure_observation(error))
            if selected != negative_control_observation(record[1]): return {}
            return {"negative_control": selected} if selected else {}
        except Exception:
            return {}

    def failure_recovery(self, error):
        try:
            record = self._recovery_failure
            if (type(record) is not tuple or len(record) != 4 or record[0] is not error
                    or record[3] is not self._recovery_diagnostics
                    or type(record[3]) is not RecoveryDeliveryDiagnostics
                    or self.phase != record[1] + "_kernel_block_negative_control"
                    or self.failure_negative_control(error) != {
                        "negative_control": {"scenario": record[1], "stage": "restored_delivery"}}):
                return {}
            selected = record[3].failure_observation(error, record[1], record[2])
            validated = recovery_delivery_observation(selected)
            return {"recovery_delivery": validated} if validated is not None else {}
        except Exception:
            return {}

    def failure_final_path(self, error):
        try:
            record = self._final_path_failure
            if (type(error) is not ValueError or type(record) is not tuple or len(record) != 2
                    or record[0] is not error):
                return {}
            selected = self.failure_negative_control(error).get("negative_control")
            if (type(selected) is not dict or selected.get("stage") != "final_observation"
                    or selected.get("reason") != "path_missing"
                    or selected.get("scenario") not in {"turn_tcp", "turn_tls", "impaired"}
                    or self.phase != selected["scenario"] + "_kernel_block_negative_control"):
                return {}
            reason = final_path_missing_observation(record[1])
            return {"final_path_missing": reason} if reason is not None else {}
        except Exception:
            return {}

    def failure_native_path(self, error):
        try:
            observer = self._path_diagnostics
            if type(observer) is not NativePathDiagnostics:
                return {}
            record = observer._failure
            if type(record) is not tuple or len(record) != 2 or record[0] is not error:
                return {}
            selected = path_failure_observation(observer.failure_observation(error))
            if (not selected or selected != path_failure_observation(record[1])
                    or self.phase != selected["scenario"] + "_authenticated_receipts"):
                return {}
            return {"native_path_failure": selected}
        except Exception:
            return {}

    def failure_kernel_cleanup(self, error):
        """Keep exact primary error identity and a separate fixed cleanup label."""
        try:
            record = self._fault_cleanup_failure
            if (type(record) is tuple and len(record) == 2 and record[0] is error
                    and type(record[1]) is dict
                    and record[1] == {"scenario": "impaired", "stage": "fault_cleanup",
                                      "reason": "cleanup_incomplete"}):
                return {"kernel_cleanup_failure": dict(record[1]), "cleanup_failed": True}
        except Exception:
            pass
        return {}

    def negative_traffic(self, before, after):
        with negative_control_stage(self._negative_diagnostics, "final_traffic"):
            return traffic(before, after)

    def endpoint_resource_current(self, before):
        inventory = self.peer.inventory()
        resources = inventory.get("resources")
        counts = accounting(inventory.get("host_accounting"))
        return (type(resources) is list and len(resources) == 1
                and resources[0].get("logical_session") == before["logical_session"]
                and resources[0].get("physical_resource") == before["resource"]
                and resources[0].get("adopted") is True
                and resources[0].get("owner_state") == "authorized"
                and inventory.get("service_incarnation") == before["service_incarnation"]
                and inventory.get("profile_incarnation") == before["profile_incarnation"]
                and counts["active_count"] == 1 and counts["creating_count"] == counts["retiring_count"] == 0)

    def _retirement_poll_observation(self, state=None, resources=None, counts=None):
        context = self._retirement_context
        if context is None: return
        if state is None:
            if context["polls"] == 128: context["polls_capped"] = True
            else: context["polls"] += 1
        else:
            context["last_observation"] = {"state": state, "resource_count": min(len(resources), 16),
                "resources_capped": len(resources) > 16, "counts": {name: counts[name] for name in RETIREMENT_COUNTS}}

    def failure_rendezvous(self, error):
        if (type(error) is not RendezvousUnavailable
                or self.failure_site(error) not in {"rendezvous_receive", "initialize_key_wait"}):
            return {}
        try:
            return rendezvous_observation(self.transport.failure_observation(error))
        except Exception:
            # Missing or faulty diagnostic observers must not replace the original failure.
            return {}

    def failure_pairing(self, error):
        observed = self._pairing_failure
        if observed is None or observed[0] is not error or self.failure_site(error) != "pairing_status":
            return {}
        selected: dict[str, object] = {"pairing_state": observed[1]}
        if observed[2] is not None:
            selected["pairing_retirement"] = dict(observed[2])
        if observed[3] is not None:
            selected["gather_failure"] = dict(observed[3])
        return selected

    def _observe_pairing_open(self, record):
        try:
            if self._pairing_open_active and self._pairing_open_context is not None:
                selected = pairing_open_observation(record)
                self._pairing_open_last = (self._pairing_open_context, selected) if selected is not None else None
        except Exception:
            self._pairing_open_last = None

    def _bind_pairing_open_failure(self, error):
        try:
            last = self._pairing_open_last
            if (self._pairing_open_active and last is not None
                    and last[0] == self._pairing_open_context):
                self._pairing_open_failure = error, last[0], last[1]
        except Exception:
            self._pairing_open_failure = None

    def failure_pairing_open(self, error):
        try:
            observed = self._pairing_open_failure
            if (observed is None or observed[0] is not error
                    or observed[1] != self._pairing_open_context
                    or observed[1] != (self.pairing, self._pairing_open_context[1], self.phase)):
                return {}
            if (type(error) is not PeerFailure
                    or not ((error.code == "supervisor_pairing_retired" and self.failure_site(error) == "pairing_status")
                            or (error.code == "scenario_deadline" and self.failure_site(error) is None))):
                return {}
            selected = pairing_open_observation(observed[2])
            return {"pairing_open_last": selected} if selected is not None else {}
        except Exception:
            return {}

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
        with self._failure_scope("rendezvous_publish"):
            self.transport.publish(phase, self.rendezvous.seal(phase, value))

    def receive(self, phase, *, timeout=180):
        with self._failure_scope("rendezvous_receive"):
            return self.rendezvous.open(phase, self.transport.wait(self.partner, phase, timeout=timeout))

    def initialize(self):
        from mesh_chat.call_settings import DEFAULT_SIGNAL_MAILBOX_URL, DEFAULT_TURN_BROKER_URL, DEFAULT_STUN_URLS
        with self._failure_scope("initialize_peer_start"):
            self.peer.start()
        with self._failure_scope("initialize_runtime_capabilities"):
            profiles = self.core("runtime.capabilities")["profiles"]
            if len(profiles) != 1:
                raise ValueError("Native qualification requires one fresh synthetic profile")
        self.profile = profiles[0]
        with self._failure_scope("initialize_snapshot"):
            fresh = self.snapshot()
            if fresh.get("contacts") or fresh.get("messages"):
                raise ValueError("Initial pairing must not begin with approved contacts or messages")
        with self._failure_scope("initialize_inventory"):
            accounting(self.peer.inventory().get("host_accounting"), empty=True)
        self.identity = digest(fresh["profile"]["destination_hash"])
        with self._failure_scope("initialize_settings_update"):
            self.core("settings.update", {"profile": self.profile, "settings": {
                "nearby_discovery": False, "lan_fallback": False, "help_route": False}})
        self.default_call_settings = {
            "stun_urls": list(DEFAULT_STUN_URLS), "turn_broker_url": DEFAULT_TURN_BROKER_URL,
            "turn_broker_consent": True, "signal_mailbox_url": DEFAULT_SIGNAL_MAILBOX_URL,
            "turn_url": None, "turn_username": None, "turn_credential": None,
            "relay_only": False, "store_call_signaling": True}
        with self._failure_scope("initialize_call_settings_update"):
            self.core("call.settings_update", {"profile": self.profile, "settings": self.default_call_settings})
        with self._failure_scope("initialize_ice_servers"):
            self.broker_ice = self.core("call.ice_servers", {"profile": self.profile})["ice"]

    def pairing_status(self):
        with self._failure_scope("pairing_status"):
            value = self.peer.pairing_status(self.pairing)
            if value.get("operation_id") != self.pairing:
                raise PeerFailure("invalid_pairing_identity")
            if value.get("state") in {"retired", "retiring"}:
                error = PeerFailure("supervisor_pairing_retired")
                retirement = validated_pairing_retirement(value.get("retirement"))
                gather = validated_gather_for_retirement(retirement, value.get("gather_failure"))
                self._pairing_failure = error, value["state"], retirement, gather
                self._bind_pairing_open_failure(error)
                raise error
            return value

    def negotiate(self, scenario, initiator):
        self._pairing_open_context = self._pairing_open_last = self._pairing_open_failure = None
        self._pairing_open_active = False
        self.phase = scenario + "_supervisor_owned_pairing_" + initiator
        ice, turn_url = selected_ice(self.broker_ice, scenario)
        server = ice["iceServers"][0]
        settings = {**self.default_call_settings, "turn_broker_url": None, "turn_broker_consent": False,
            "stun_urls": server["urls"] if scenario == "direct" else [], "turn_url": turn_url,
            "turn_username": server.get("username"), "turn_credential": server.get("credential"),
            "relay_only": scenario != "direct"}
        with self._failure_scope("negotiate_settings_update"):
            self.core("call.settings_update", {"profile": self.profile, "settings": settings})
        self.pairing = str(uuid4())
        self._pairing_open_context = (self.pairing, scenario, self.phase)
        if self.role == initiator:
            with self._failure_scope("pairing_offer_begin"):
                admitted = self.peer.pairing_begin(self.pairing, "offer", direct=scenario == "direct")
                if admitted.get("operation_id") != self.pairing: raise PeerFailure("invalid_pairing_identity")
            code = self.wait(lambda: self.pairing_status().get("pairing_code"), timeout=120)
            self.publish(OFFERS[scenario], {"shareable": code})
        else:
            code = self.receive(OFFERS[scenario])["shareable"]
            with self._failure_scope("pairing_answer_begin"):
                admitted = self.peer.pairing_begin(self.pairing, "answer", pairing_code=code, direct=scenario == "direct")
                if admitted.get("operation_id") != self.pairing: raise PeerFailure("invalid_pairing_identity")
        def open_session():
            status = self.pairing_status()
            record = {"status": pairing_open_label(status.get("state"), PAIRING_OPEN_LABELS["status"]),
                "resources": "unread", "ice": "unread", "channel": "unread"}
            self._observe_pairing_open(record)
            if type(status.get("state")) is str and status["state"] == "reserved":
                return None
            with self._failure_scope("negotiate_inventory"):
                resources = self.peer.inventory()["resources"]
                count = len(resources)
                record["resources"] = "zero" if count == 0 else "one" if count == 1 else "multiple"
                self._observe_pairing_open(record)
                if count != 1: return None
                logical = resources[0]["logical_session"]
            with self._failure_scope("negotiate_native_stats"):
                stats = self.native("native_webrtc_stats", session_id=logical)
                channel = stats.get("data_channel_state")
                try:
                    record["ice"] = pairing_open_label(stats.get("ice_connection_state"), PAIRING_OPEN_LABELS["ice"])
                    record["channel"] = pairing_open_label(channel, PAIRING_OPEN_LABELS["channel"])
                    self._observe_pairing_open(record)
                except Exception:
                    self._pairing_open_last = None
                return logical if channel == "open" else None
        self._pairing_open_active = True
        try:
            session = self.wait(open_session, timeout=120)
        except PeerFailure as error:
            if error.code == "scenario_deadline" and self.failure_site(error) is None:
                self._bind_pairing_open_failure(error)
            raise
        finally:
            self._pairing_open_active = False
        self._pairing_open_last = self._pairing_open_failure = None
        return session, turn_url

    def approved_contact(self):
        values = self.snapshot().get("contacts", [])
        if len(values) == 1 and values[0].get("trust") in {"approved", "verified"}:
            return values[0]
        return None

    def retired(self, *, operation_id=None, request_id=None, expected_service=None, expected_profile=None):
        correlated = operation_id is not None or request_id is not None
        if correlated:
            try: self._retirement_poll_observation()
            except Exception: self._retirement_context = None
            inventory = self.peer.inventory(operation_id=operation_id, request_id=request_id)
            if (type(inventory) is not dict or type(inventory.get("service_incarnation")) is not str
                    or type(inventory.get("profile_incarnation")) is not str
                    or inventory["service_incarnation"] != expected_service or inventory["profile_incarnation"] != expected_profile):
                raise PeerFailure("carrier_retirement_scope_changed")
            state = carrier_retirement_state(inventory.get("carrier_retirement"), request_id)
            if type(inventory.get("resources")) is not list:
                raise PeerFailure("invalid_carrier_retirement_inventory")
        else:
            inventory = self.peer.inventory()
        counts = accounting(inventory.get("host_accounting"))
        if correlated:
            try: self._retirement_poll_observation(state, inventory["resources"], counts)
            except Exception: self._retirement_context = None
        if (inventory["resources"] or any(counts[name] for name in RETIREMENT_COUNTS)
                or (correlated and state != "acknowledged")):
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
            with self._substage("pending_contact_wait"):
                pending = self.wait(lambda: next((item for item in self.snapshot().get("contacts", []) if item.get("trust") == "pending_request"), None))
            with self._substage("contact_decision"):
                self.core("peer.approve", {"profile": self.profile, "peer": pending["core_handle"]})
        else:
            with self._substage("pending_contact_wait"):
                pending = self.wait(lambda: next((item for item in self.snapshot().get("contact_invitations", []) if item.get("state") == "pending"), None))
            with self._substage("implicit_contact_guard"):
                if self.snapshot().get("contacts"):
                    raise ValueError("Receiving the signed invitation silently created contact approval")
            with self._substage("contact_decision"):
                self.core("contact.invitation", {"profile": self.profile, "action": "decide", "invitation": pending["id"], "accept": True})
        with self._substage("approved_contact_wait"):
            self.contact = self.wait(self.approved_contact)
        with self._substage("reconnect_consent"):
            self.native("reconnect_consent_set", contact_id=self.contact["id"], auto_reconnect=False,
                        allow_direct_ip_disclosure=True)
        with self._substage("approval_ready_observation"):
            self.wait(lambda: self.observe(session, ready=True), timeout=120)
        with self._substage("approval_acknowledgment"):
            if self.role == "android": self.publish("approved", {"approved": True})
            elif self.receive("approved") != {"approved": True}: raise ValueError("Peer approval was not explicit")

    def observe(self, logical=None, *, ready=True, scenario=None, missing_reasons=None):
        with self._substage("path_inventory"):
            inventory = self.peer.inventory()
            resources = [item for item in inventory["resources"] if logical is None or item["logical_session"] == logical]
            if not resources:
                record_final_path_skip(missing_reasons, "no_resource")
                return None
            if ready and len(resources) == 1:
                owner_state = resources[0].get("owner_state")
                if (type(owner_state) is str and owner_state == "unadopted"
                        and resources[0].get("adopted") is False):
                    record_final_path_skip(missing_reasons, "adopted_not_true")
                    return None
                if type(owner_state) is str and owner_state == "pending_adoption":
                    record_final_path_skip(missing_reasons, "pending_adoption")
                    return None
        for resource in resources:
            with self._substage("path_read"):
                sample_request = os.urandom(16).hex()
                requested = time.monotonic()
                value = self.peer.path(resource["logical_session"], resource["physical_resource"], sample_request)
            with self._substage("path_validation"):
                self.samples.check_request(value, sample_request)
                first_unready = None
                if ready:
                    for field, reason in (("adopted", "adopted_not_true"), ("attached", "attached_not_true"),
                                          ("messaging_ready", "messaging_ready_not_true")):
                        if value.get(field) is not True:
                            first_unready = reason
                            break
                if first_unready is not None:
                    record_final_path_skip(missing_reasons, first_unready)
                    continue
                if value.get("status") != "selected":
                    record_final_path_skip(missing_reasons, "nonselected")
                    continue
                return self.samples.consume(value, inventory, requested, sample_request=sample_request, ready=ready, scenario=scenario)
        return None

    def final_ready_observation(self, logical, scenario, deadline):
        """Use only the remaining restored-delivery window for relay readiness."""
        last_reasons = set()
        while time.monotonic() < deadline:
            reasons = set()
            value = self.observe(logical, ready=True, scenario=scenario, missing_reasons=reasons)
            if value is not None and time.monotonic() <= deadline:
                return value, reasons
            last_reasons = reasons
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.25, remaining))
        return None, last_reasons

    def text(self, scenario, index=0, *, sender=None, padded=False):
        value = f"mesh-native-ci:{self.context['run_id']}:{self.context['run_attempt']}:{scenario}:{index}:{sender or self.role}"
        # Retained snapshots for the entire matrix must remain inside the
        # production Core frame budget; impairment acts on real kernel packets.
        return value + (":" + "x" * 1024 if padded else "")

    def enqueue(self, text, *, negative_control=False):
        result = self.core("message.enqueue", {"profile": self.profile, "recipient": self.contact["core_handle"],
            "kind": "text", "text": text}, uuid4().hex)
        if result.get("accepted") is not True:
            error = ValueError("Core did not durably accept the message")
            if negative_control:
                negative_control_error(self._negative_diagnostics, "blocked_enqueue", error, "not_accepted")
            raise error
        return result["message"]

    def delivered(self, handle):
        state = self.core("message.query", {"profile": self.profile, "message": handle})["state"]
        try:
            observer = self._recovery_diagnostics
            if type(observer) is RecoveryDeliveryDiagnostics:
                observer.observe(handle, state, time.monotonic())
        except Exception:
            self._recovery_diagnostics = None  # Optional evidence cannot change the queried result.
        return state == "delivered"

    def records(self, text, direction):
        return [item for item in self.snapshot().get("messages", []) if item.get("kind") == "chat"
                and item.get("text") == text and item.get("direction") == direction]

    def exchange(self, scenario, index=0, *, padded=False, path_diagnostics=None):
        with path_stage(path_diagnostics, "receipt_enqueue"):
            own, other = self.text(scenario, index, padded=padded), self.text(scenario, index, sender=self.partner, padded=padded)
            started = time.monotonic()
            handle = self.enqueue(own)
        with path_stage(path_diagnostics, "receipt_delivery_wait"):
            self.wait(lambda: self.delivered(handle), timeout=90)
        with path_stage(path_diagnostics, "receipt_inbound_wait"):
            inbound = self.wait(lambda: self.records(other, "inbound"), timeout=90)
        with path_stage(path_diagnostics, "receipt_outbound_records"):
            outbound = self.records(own, "outbound")
        with path_stage(path_diagnostics, "receipt_record_validation"):
            if len(inbound) != 1 or len(outbound) != 1 or not outbound[0].get("native_message_id"):
                raise ValueError("Native receipt exchange duplicated or lacks native delivery identity")
            return {"outbound": digest(outbound[0]["id"]), "inbound": digest(inbound[0]["id"]),
                    "authenticated_receipt": True, "inbound_records": 1, "outbound_records": 1,
                    "receipt_roundtrip_ms": (time.monotonic() - started) * 1000}, handle

    def negative(self, fault, scenario):
        self.phase = scenario + "_kernel_block_negative_control"
        self._negative_diagnostics = reset_negative_control(self._negative_diagnostics, scenario)
        self._recovery_diagnostics = self._recovery_failure = None
        observer = self._negative_diagnostics
        if fault is not None:
            with negative_control_stage(observer, "kernel_block"): fault.block()
            with negative_control_stage(observer, "ready_publish"):
                self.publish("negative_ready_" + scenario, {"approved": True})
        else:
            with negative_control_stage(observer, "ready_receive"):
                if self.receive("negative_ready_" + scenario) != {"approved": True}:
                    raise negative_control_error(observer, "ready_receive",
                        ValueError("Kernel block admission was not acknowledged"), "not_acknowledged")
        with negative_control_stage(observer, "blocked_enqueue"):
            handle = self.enqueue(self.text("blocked_path_" + scenario), negative_control=True)
        try:
            self._recovery_diagnostics = RecoveryDeliveryDiagnostics(scenario, handle)
            self._recovery_diagnostics.start("blocked_receipt", time.monotonic())
        except Exception:
            self._recovery_diagnostics = None
        until = time.monotonic() + 2
        while time.monotonic() < until:
            with negative_control_stage(observer, "blocked_receipt"):
                if self.delivered(handle):
                    raise negative_control_error(observer, "blocked_receipt",
                        ValueError("Authenticated receipt arrived while the selected kernel path was blocked"), "receipt_while_blocked")
            time.sleep(0.1)
        packets = None
        if fault is not None:
            with negative_control_stage(observer, "checked_receive"):
                if self.receive("negative_checked_" + scenario) != {"approved": True}:
                    raise negative_control_error(observer, "checked_receive",
                        ValueError("Remote blocked-path observation is missing"), "not_acknowledged")
            with negative_control_stage(observer, "kernel_unblock"): packets = fault.unblock()
            with negative_control_stage(observer, "dropped_count"):
                if packets <= 0:
                    raise negative_control_error(observer, "dropped_count",
                        ValueError("Negative control has no actual dropped packets"), "no_dropped_packets")
        else:
            with negative_control_stage(observer, "checked_publish"):
                self.publish("negative_checked_" + scenario, {"approved": True})
        restoration_deadline = None
        try:
            if self._recovery_diagnostics is not None:
                try: self._recovery_diagnostics.start("restored_delivery", time.monotonic())
                except Exception: self._recovery_diagnostics = None
            with negative_control_stage(observer, "restored_delivery"):
                if scenario in {"turn_tcp", "turn_tls", "impaired"}:
                    # Receipt, inbound record, and final path share this one window.
                    restoration_deadline = min(self.deadline, time.monotonic() + 90)
                    self.wait(lambda: self.delivered(handle),
                              timeout=max(0, restoration_deadline - time.monotonic()))
                    if time.monotonic() > restoration_deadline:
                        raise PeerFailure("scenario_deadline")
                else:
                    self.wait(lambda: self.delivered(handle), timeout=90)
        except Exception as error:
            observed = self._recovery_diagnostics
            try:
                if type(observed) is RecoveryDeliveryDiagnostics:
                    observed.failed(error)
                    self._recovery_failure = error, scenario, handle, observed
            except Exception:
                self._recovery_failure = None
            raise
        with negative_control_stage(observer, "recovered_inbound"):
            if restoration_deadline is not None:
                remaining = restoration_deadline - time.monotonic()
                if remaining <= 0:
                    raise PeerFailure("scenario_deadline")
                inbound = self.wait(lambda: self.records(
                    self.text("blocked_path_" + scenario, sender=self.partner), "inbound"), timeout=remaining)
                if time.monotonic() > restoration_deadline:
                    raise PeerFailure("scenario_deadline")
            else:
                inbound = self.wait(lambda: self.records(
                    self.text("blocked_path_" + scenario, sender=self.partner), "inbound"), timeout=90)
        with negative_control_stage(observer, "recovered_records"):
            outbound = self.records(self.text("blocked_path_" + scenario), "outbound")
            if len(inbound) != 1 or len(outbound) != 1:
                raise negative_control_error(observer, "recovered_records",
                    ValueError("Blocked-path recovery duplicated the queued durable message"), "record_count")
        if fault is not None and (getattr(fault, "endpoint_mode", False) or getattr(fault, "uid_udp_mode", False)):
            with negative_control_stage(observer, "kernel_restore_current"):
                fault.require_current()
        self._recovery_diagnostics = self._recovery_failure = None
        return {"blocked_packets": packets, "delivered_while_blocked": False, "delivered_after_restore": True,
                "kernel_protocol": fault.protocol if fault is not None else None,
                "kernel_target": {"kind": fault.target_kind, "digest": digest(fault.target_material),
                                  "rule_count": fault.rule_count} if fault is not None else None,
                "outbound": digest(outbound[0]["id"]), "inbound": digest(inbound[0]["id"])}, restoration_deadline

    def path_case(self, scenario, initiator):
        self._retirement_context = self._retirement_failure = None
        self._final_path_failure = None
        self._fault_cleanup_failure = None
        self._negative_diagnostics = reset_negative_control(self._negative_diagnostics, scenario)
        session, url = self.negotiate(scenario, initiator)
        if self.contact is None: self.pair(session, initiator)
        with self._substage("transferred_status_wait"):
            self.wait(lambda: self.pairing_status().get("state") == "transferred", timeout=120)
        with self._substage("adopted_observation"):
            adopted = self.wait(lambda: self.observe(session, ready=True, scenario=scenario), timeout=120)
        with self._substage("transferred_cancel"):
            cancelled = self.peer.pairing_cancel(self.pairing)
        with self._substage("transferred_cancel_check"):
            if cancelled.get("operation_id") != self.pairing or cancelled.get("state") != "transferred":
                raise ValueError("Retired pairing intent tried to reclaim its transferred carrier")
        with self._substage("post_cancel_observation"):
            before = self.wait(lambda: self.observe(session, ready=True, scenario=scenario), timeout=120)
        with self._substage("carrier_identity_check"):
            if any(adopted[name] != before[name] for name in
                   ("resource", "logical_session", "adapter_epoch", "service_incarnation")):
                raise ValueError("Transferred pairing cancellation replaced its adopted carrier")
        self.phase = scenario + "_authenticated_receipts"
        try: self._path_diagnostics = NativePathDiagnostics(scenario)
        except Exception: self._path_diagnostics = None
        fault, impairment = None, None
        try:
            if scenario in {"turn_tcp", "turn_tls", "impaired"} and self.role == "android":
                from native_interop_faults import AndroidKernelPath
                fault = AndroidKernelPath(self.peer, before, url, diagnostics=self._negative_diagnostics,
                                          path_diagnostics=self._path_diagnostics,
                                          resource_check=lambda: self.endpoint_resource_current(before),
                                          control_urls=(DEFAULT_SIGNAL_MAILBOX_URL,),
                                          **({"coverage_factory": self.coverage_factory}
                                             if getattr(self, "coverage_factory", None) is not None else {}))
            if scenario == "impaired":
                if self.role == "android":
                    fault.install()
                    self.publish("impaired_ready", {"approved": True})
                elif self.receive("impaired_ready") != {"approved": True}:
                    raise ValueError("Actual kernel impairment admission is missing")
            messages = [self.exchange(scenario + ":" + initiator, index, padded=scenario == "impaired",
                                      path_diagnostics=self._path_diagnostics)[0]
                        for index in range(20 if scenario == "impaired" else 1)]
            negative, restoration_deadline = (self.negative(fault, scenario)
                if scenario in {"turn_tcp", "turn_tls", "impaired"} else (None, None))
            with negative_control_stage(self._negative_diagnostics, "final_observation"):
                missing_reasons = set() if scenario in {"turn_tcp", "turn_tls", "impaired"} else None
                if scenario in {"turn_tcp", "turn_tls", "impaired"}:
                    after, missing_reasons = self.final_ready_observation(
                        session, scenario, restoration_deadline)
                    if after is not None and time.monotonic() > restoration_deadline:
                        after, missing_reasons = None, set()
                    if after is not None and fault is not None and (
                            getattr(fault, "endpoint_mode", False) or getattr(fault, "uid_udp_mode", False)):
                        with negative_control_stage(self._negative_diagnostics, "kernel_restore_current"):
                            fault.require_current()
                        if time.monotonic() > restoration_deadline:
                            after, missing_reasons = None, set()
                elif missing_reasons is None:
                    after = self.observe(session, ready=True, scenario=scenario)
                else:
                    after = self.observe(session, ready=True, scenario=scenario, missing_reasons=missing_reasons)
                if after is None:
                    error = ValueError("Native selected path disappeared after receipt delivery")
                    if missing_reasons is not None:
                        try: reason = final_path_missing_reason(missing_reasons)
                        except Exception: reason = "unavailable"
                        self._final_path_failure = error, reason
                    raise negative_control_error(self._negative_diagnostics, "final_observation", error, "path_missing")
            with negative_control_stage(self._negative_diagnostics, "final_evidence"):
                if fault is not None and scenario == "impaired": impairment = fault.report()
                if scenario == "impaired" and self.role == "android" and (
                        before["pair"]["rtt_ms"] is None or after["pair"]["rtt_ms"] is None):
                    raise negative_control_error(self._negative_diagnostics, "final_evidence",
                        ValueError("Actual selected-pair baseline/impaired RTT is unavailable"), "rtt_unavailable")
                self.cases.append({"scenario": scenario, "initiator": initiator, "supervisor_pairing": {
                    "operation": digest(self.pairing), "role": "offer" if self.role == initiator else "answer", "state": "transferred",
                    "transferred_cancel_preserves_carrier": True},
                    "before": selection(before), "after": selection(after),
                    "native_delta": self.negative_traffic(before, after), "messages": messages, "impairment": impairment, "negative": negative})
        finally:
            if fault is not None:
                if scenario != "impaired":
                    with negative_control_stage(self._negative_diagnostics, "fault_cleanup"):
                        fault.close()
                else:
                    active = sys.exc_info()[1]
                    observer = self._negative_diagnostics
                    previous = getattr(observer, "_failure", None)
                    try:
                        with negative_control_stage(self._negative_diagnostics, "fault_cleanup"): fault.close()
                    except Exception as cleanup_error:
                        if active is not None:
                            if type(previous) is tuple and len(previous) == 2 and previous[0] is active:
                                try: observer._failure = previous
                                except Exception: pass
                            self._fault_cleanup_failure = (active, {"scenario": "impaired",
                                "stage": "fault_cleanup", "reason": "cleanup_incomplete"})
                            raise active from cleanup_error
                        raise
        self._path_diagnostics = None
        self._negative_diagnostics = reset_negative_control(self._negative_diagnostics)
        self.phase = scenario + "_native_lease_retirement"
        self._retirement_context = {"scenario": scenario, "initiator": initiator, "stage": "prepare",
            "polls": 0, "polls_capped": False, "last_observation": None}
        try:
            operation_id, request_id = self.pairing, os.urandom(16).hex()
            expected_service, expected_profile = after["service_incarnation"], after["profile_incarnation"]
            target = {"operation_id": operation_id, "request_id": request_id,
                "logical_session": after["logical_session"], "expected_physical": after["resource"],
                "expected_service_incarnation": expected_service, "expected_adapter_epoch": after["adapter_epoch"]}
            carrier_retirement_state(self.peer.retire_carrier(**target, action="prepare"), request_id, admission="prepared")
            phase = "case_complete_" + scenario + "_" + initiator
            self._retirement_context["stage"] = "completion_publish"
            self.publish(phase, {"completed": True})
            self._retirement_context["stage"] = "completion_receive"
            remaining = min(180, self.deadline - time.monotonic())
            if remaining <= 0: raise PeerFailure("scenario_deadline")
            marker = checked_payload(phase, self.receive(phase, timeout=remaining))
            if marker != {"completed": True}: raise ValueError("Peer case completion is missing")
            self._retirement_context["stage"] = "commit"
            carrier_retirement_state(self.peer.retire_carrier(**target, action="commit"), request_id, admission="pending")
            self._retirement_context["stage"] = "poll"
            self.cases[-1]["retired_host_accounting"] = self.wait(lambda: self.retired(
                operation_id=operation_id, request_id=request_id, expected_service=expected_service,
                expected_profile=expected_profile), timeout=30)
            self.cases[-1]["owner_retirement_acknowledged"] = True
        except Exception as error:
            try:
                selected = retirement_failure_snapshot(self._retirement_context)
                if selected is not None: self._retirement_failure = error, selected
            except Exception: self._retirement_failure = None
            raise
        else:
            self._retirement_failure = None
        finally:
            self._retirement_context = None

    def cold_starts(self):
        self.phase = "cold_start_receipts"
        self.core("call.settings_update", {"profile": self.profile, "settings": self.default_call_settings})
        consent = self.native("reconnect_consent_set", contact_id=self.contact["id"], auto_reconnect=True,
                    allow_direct_ip_disclosure=True)
        association = reconnect_association(consent["profile"], self.contact)
        payload = checked_payload("reconnect_capabilities", {"capabilities": consent["capabilities"]})
        self.publish("reconnect_capabilities", payload)
        partner = checked_payload("reconnect_capabilities", self.receive("reconnect_capabilities"))
        stored = self.native("reconnect_capabilities_store", document=partner["capabilities"],
            expected_contact_id=self.contact["id"], expected_peer_destination=self.contact["destination_hash"])
        if (type(stored) is not dict or stored.get("pending") is not False
                or reconnect_association(stored.get("profile"), self.contact) != association
                or stored["profile"].get("peer_auto_reconnect") is not True):
            raise ValueError("Cold-start reconnect consent is not reciprocal")
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
        with self._failure_scope("initialize_key_publish"):
            self.transport.publish("key", self.rendezvous.public_manifest())
        with self._failure_scope("initialize_key_wait"):
            partner_key = self.transport.wait(self.partner, "key", timeout=900)
        with self._failure_scope("initialize_key_bind"):
            self.rendezvous.bind_partner(partner_key)
        # Both roles execute this fixed source-bound inventory. Keep bootstrap
        # uploads bounded at Windows 16 / Android 14 (quick 7 each), plus one final report.
        for scenario, initiator in self.workload["paths"]: self.path_case(scenario, initiator)
        self.cold_starts()
        self.phase = "clean_host_retirement"
        self.native("reconnect_consent_set", contact_id=self.contact["id"], auto_reconnect=False,
                    allow_direct_ip_disclosure=True)
        self.core("connection.stop", {"profile": self.profile, "peer": self.contact["core_handle"]})
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


def main(*, gateway=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("windows", "android"))
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--workload", required=True, choices=("quick", "full"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = required_workload(args.workload)
    result = {"v": 1, "passed": False, "evidence_level": plan["level"], "role": args.role, "scope": plan["scope"], "workload": args.workload}
    peer = transport = rendezvous = controller = emulator = None
    preflight_diagnostics = PreflightDiagnostics()
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
            emulator.start(APKS, diagnostics=preflight_diagnostics)
            if gateway is not None:
                gateway.ready(emulator)
        platform = {"windows": True} if args.role == "windows" else android_environment(diagnostics=preflight_diagnostics)
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
        controller = Controller(args.role, peer, transport, rendezvous, context, workload=args.workload,
                                **({"coverage_factory": gateway.coverage} if gateway is not None else {}))
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
        if controller is None and phase == "platform_outbound_preflight":
            site = preflight_diagnostics.failure_site(error)
            if site is not None:
                result["preflight_failure_site"] = site
                result.update(preflight_diagnostics.failure_observation(error))
        if controller is not None:
            site = controller.failure_site(error)
            if site is not None: result["failure_site"] = site
            result.update(controller.failure_pairing(error))
            result.update(controller.failure_pairing_open(error))
            result.update(controller.failure_observation(error))
            result.update(controller.failure_rendezvous(error))
            result.update(controller.failure_retirement(error))
            result.update(controller.failure_negative_control(error))
            result.update(controller.failure_recovery(error))
            result.update(controller.failure_final_path(error))
            result.update(controller.failure_native_path(error))
            try: result.update(controller.failure_kernel_cleanup(error))
            except Exception: pass  # Optional cleanup metadata cannot replace the primary report.
            try:
                core = controller.failure_core(error)
                result.update(core)
                result.update(controller.failure_network(error, core.get("core_failure_observation"), site))
            except Exception: pass  # Optional private diagnostics cannot replace the primary report.
    finally:
        if peer is not None and peer.process is not None:
            try: peer.stop(crash=True)
            except Exception: result["cleanup_failed"] = True
        if rendezvous is not None: rendezvous.close()
        if transport is not None: transport.close()
        if emulator is not None:
            if gateway is not None:
                try: gateway.before_cleanup()
                except Exception: result.update(passed=False, cleanup_failed=True)
            try: emulator.close()
            except Exception:
                result.update(passed=False, cleanup_failed=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "role", "evidence_level")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
