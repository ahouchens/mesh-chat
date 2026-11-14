"""Public owner-restart scenario for already open installed Windows/Android peers.

The caller owns both sessions, sealed exchange transport, final retirement and
reports. Product observations use only public peer.request operations.
"""

import hashlib
import math
import re
import time
from uuid import uuid4

from public_core_pair_flow import FINISH_RESERVE_SECONDS, run_role as run_fresh_role
from public_core_restart_evidence import (ANDROID_CHECKS, WINDOWS_CHECKS,
    verify_restart_flow)


RESTART_RESERVE_SECONDS = 360
FINAL_RETIREMENT_SECONDS = 90
OVERALL_CLEANUP_SECONDS = 30
PHASE_SECONDS = 90
POLL_SECONDS = 5
ANDROID_MAX_REQUESTS = 126
WINDOWS_MAX_REQUESTS_PER_OWNER = 96
HEX32 = re.compile(r"[a-f0-9]{32}\Z")


def _text(pair_id, role, *, restart=False):
    domain = "public-core-restart" if restart else "public-core-pair"
    return f"{domain}:v1:{pair_id}:{role}"


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _rows(snapshot, name):
    rows = snapshot.get(name)
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise ValueError("public_restart_view")
    return rows


class RestartFlow:
    def __init__(self, role, peer, exchange, pair_id, overall_deadline, clock, sleep):
        peer_deadline = getattr(peer, "deadline", None)
        if (type(role) is not str or role not in {"windows", "android"}
                or type(pair_id) is not str or HEX32.fullmatch(pair_id) is None
                or type(overall_deadline) not in {int, float} or not math.isfinite(overall_deadline)
                or type(peer_deadline) not in {int, float} or not math.isfinite(peer_deadline)):
            raise ValueError("public_restart_arguments")
        self.role, self.other = role, "android" if role == "windows" else "windows"
        self.peer, self.exchange = peer, exchange
        self.pair_id, self.clock, self.sleep = pair_id, clock, sleep
        self.end = min(peer_deadline, overall_deadline - OVERALL_CLEANUP_SECONDS)
        if self.end - clock() <= RESTART_RESERVE_SECONDS:
            raise TimeoutError("public_restart_admission_deadline")
        # run_fresh_role's Flow subtracts its own 60-second finish reserve.
        self.baseline_deadline = self.end - RESTART_RESERVE_SECONDS + FINISH_RESERVE_SECONDS
        self.work_deadline = self.end - FINAL_RETIREMENT_SECONDS
        self.additional = 0
        self.after_reopen = 0
        self.reopened = False
        self.baseline = None
        self.profile = self.contact_handle = self.contact_id = None
        self.initial_process = getattr(peer, "process", None)
        self.initial_protocol = getattr(peer, "protocol", None) if role == "android" else None
        self.initial_data = getattr(peer, "data", None) if role == "windows" else None
        if (self.initial_process is None or self.initial_process.poll() is not None
                or (role == "android" and self.initial_protocol is None)
                or (role == "windows" and self.initial_data is None)):
            raise ValueError("public_restart_session_not_open")

    def _remaining(self):
        remaining = self.work_deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("public_restart_deadline")
        return remaining

    def _request(self, operation, params=None, key=None):
        self._remaining()
        if self.role == "android":
            if self.baseline["public_request_count"] + self.additional >= ANDROID_MAX_REQUESTS:
                raise ValueError("public_restart_request_budget")
        elif (self.after_reopen if self.reopened else
              self.baseline["public_request_count"] + self.additional) >= WINDOWS_MAX_REQUESTS_PER_OWNER:
            raise ValueError("public_restart_request_budget")
        value = self.peer.request(operation, params, key)
        self._remaining()
        if type(value) is not dict:
            raise ValueError("public_restart_reply")
        self.additional += 1
        if self.role == "windows" and self.reopened:
            self.after_reopen += 1
        return value

    def _phase(self, name, *, publish):
        limit = min(self.work_deadline, self.clock() + PHASE_SECONDS)
        self._remaining()
        if publish:
            self.exchange.publish(name, {}, limit)
        else:
            value = self.exchange.receive(name, limit)
            if type(value) is not dict or value != {}:
                raise ValueError("public_restart_phase_payload")
        if self.clock() >= limit:
            raise TimeoutError("public_restart_phase_deadline")

    def _wait(self, name, attempts, observe):
        limit = min(self.work_deadline, self.clock() + PHASE_SECONDS)
        for index in range(attempts):
            if self.clock() >= limit:
                raise TimeoutError("public_restart_" + name)
            value = observe()
            if self.clock() >= limit:
                raise TimeoutError("public_restart_" + name)
            if value is not None:
                return value
            if index + 1 < attempts and self.clock() + POLL_SECONDS < limit:
                self.sleep(POLL_SECONDS)
            else:
                break
        raise TimeoutError("public_restart_" + name)

    def _facts(self):
        capabilities = self._request("runtime.capabilities")
        handles, operations = capabilities.get("profiles"), capabilities.get("operations")
        required = {"profile.query", "connection.snapshot", "message.enqueue", "message.query"}
        if (type(handles) is not list or len(handles) != 1 or type(handles[0]) is not str or not handles[0]
                or type(operations) is not list or any(type(item) is not str for item in operations)
                or not required <= set(operations) or "native.command" in operations):
            raise ValueError("public_restart_profile_handle")
        profile = handles[0]
        identity = self._request("profile.query", {"profile": profile})
        destination = identity.get("destination")
        if (type(destination) is not str or HEX32.fullmatch(destination) is None
                or _digest(destination) != self.baseline["self_destination_sha256"]):
            raise ValueError("public_restart_identity")
        snapshot = self._request("application.snapshot")
        profile_view = snapshot.get("profile")
        contacts = _rows(snapshot, "contacts")
        if (type(profile_view) is not dict or profile_view.get("destination_hash") != destination
                or profile_view.get("display_name") != "Independent " + self.role
                or len(contacts) != 1):
            raise ValueError("public_restart_profile")
        contact = contacts[0]
        if (type(contact.get("id")) is not str or not contact["id"]
                or type(contact.get("core_handle")) is not str or not contact["core_handle"]
                or contact.get("trust") not in {"approved", "verified"}
                or type(contact.get("destination_hash")) is not str
                or _digest(contact["destination_hash"]) != self.baseline["peer_destination_sha256"]):
            raise ValueError("public_restart_contact")
        messages = _rows(snapshot, "messages")
        original = []
        for direction, role in (("outbound", self.role), ("inbound", self.other)):
            text = _text(self.pair_id, role)
            rows = [row for row in messages if row.get("kind") == "chat"
                    and row.get("direction") == direction and row.get("text") == text]
            if (len(rows) != 1 or type(rows[0].get("id")) is not str or not rows[0]["id"]
                    or rows[0].get("contact_id") != contact["id"]
                    or (direction == "outbound" and rows[0].get("state") != "delivered")):
                raise ValueError("public_restart_original_messages")
            original.append(rows[0]["id"])
        return {"destination": destination, "display_name": profile_view["display_name"],
                "contact_id": contact["id"], "contact_trust": contact["trust"],
                "peer_destination": contact["destination_hash"], "original_ids": tuple(original),
                "profile_handle": profile, "contact_handle": contact["core_handle"]}

    def _same_facts(self, expected):
        current = self._facts()
        durable = ("destination", "display_name", "contact_id", "contact_trust",
                   "peer_destination", "original_ids")
        if any(current[key] != expected[key] for key in durable):
            raise ValueError("public_restart_state_changed")
        self.profile, self.contact_id, self.contact_handle = (
            current["profile_handle"], current["contact_id"], current["contact_handle"])

    def _android_alive(self, process, protocol):
        if (self.peer.process is not process or self.peer.protocol is not protocol
                or process.poll() is not None or self.peer.confirmed_shutdown):
            raise ValueError("public_restart_android_session_changed")

    def _restart_owner(self, original):
        old_process, old_data = self.peer.process, self.peer.data
        if (old_process is not self.initial_process or old_data != self.initial_data
                or old_process.poll() is not None or self.peer.retired):
            raise ValueError("public_restart_owner_not_running")
        if self.peer.finish() is not True or not self.peer.retired or old_process.poll() != 0:
            raise ValueError("public_restart_owner_stop")
        self._phase("owner_stopped", publish=True)
        self._phase("android_continuous", publish=False)
        self._remaining()
        self.peer.reopen_same_data(self.end)
        if (self.peer.process is old_process or self.peer.process.poll() is not None
                or self.peer.retired or self.peer.data != old_data
                or type(self.peer.deadline) not in {int, float}
                or not math.isfinite(self.peer.deadline) or self.peer.deadline > self.end):
            raise ValueError("public_restart_owner_reopen")
        self.reopened = True
        self.additional = 0
        self._same_facts(original)
        self._phase("owner_reopened", publish=True)

    def _hold_android(self, original):
        process, protocol = self.peer.process, self.peer.protocol
        if process is not self.initial_process or protocol is not self.initial_protocol:
            raise ValueError("public_restart_android_not_running")
        self._phase("owner_stopped", publish=False)
        self._android_alive(process, protocol)
        self._same_facts(original)
        self._phase("android_continuous", publish=True)
        self._phase("owner_reopened", publish=False)
        self._android_alive(process, protocol)
        self._same_facts(original)
        self.android_process, self.android_protocol = process, protocol

    def _ready(self):
        def observe():
            connections = self._request("profile.query", {"profile": self.profile}).get("connections")
            if (type(connections) is not list or len(connections) > 2
                    or any(type(item) is not str or not item for item in connections)):
                raise ValueError("public_restart_connections")
            ready = 0
            for handle in connections:
                observation = self._request("connection.snapshot", {
                    "profile": self.profile, "connection": handle}).get("observation")
                if type(observation) is not dict:
                    raise ValueError("public_restart_connection_observation")
                ready += observation.get("messaging_ready") is True
            if ready > 1:
                raise ValueError("public_restart_extra_ready")
            return True if ready == 1 else None
        self._wait("messaging_ready", 10, observe)
        self._phase("restart_ready", publish=True)
        self._phase("restart_ready", publish=False)

    def _messages(self):
        own_text = _text(self.pair_id, self.role, restart=True)
        other_text = _text(self.pair_id, self.other, restart=True)
        sent = self._request("message.enqueue", {
            "profile": self.profile, "recipient": self.contact_handle,
            "kind": "text", "text": own_text}, str(uuid4()))
        message = sent.get("message")
        if sent.get("accepted") is not True or type(message) is not str or not message:
            raise ValueError("public_restart_enqueue")
        def delivered():
            value = self._request("message.query", {"profile": self.profile, "message": message})
            if (value.get("message") != message or value.get("text") != own_text
                    or value.get("recipient") != self.contact_handle):
                raise ValueError("public_restart_outbound")
            return True if value.get("state") == "delivered" else None
        self._wait("outbound_delivery", 8, delivered)
        def inbound():
            rows = [row for row in _rows(self._request("application.snapshot"), "messages")
                    if row.get("kind") == "chat" and row.get("direction") == "inbound"
                    and row.get("text") == other_text]
            if len(rows) > 1:
                raise ValueError("public_restart_duplicate_inbound")
            return rows[0] if rows else None
        row = self._wait("inbound_message", 8, inbound)
        if (type(row.get("id")) is not str or not row["id"]
                or row.get("contact_id") != self.contact_id):
            raise ValueError("public_restart_inbound_contact")
        view = self._request("application.snapshot")
        rows = [row for row in _rows(view, "messages") if row.get("kind") == "chat"
                and row.get("direction") == "outbound" and row.get("text") == own_text]
        inbound_rows = [item for item in _rows(view, "messages") if item.get("kind") == "chat"
                        and item.get("direction") == "inbound" and item.get("text") == other_text]
        if (len(rows) != 1 or len(inbound_rows) != 1
                or rows[0].get("id") != message or inbound_rows[0].get("id") != row["id"]
                or inbound_rows[0].get("contact_id") != self.contact_id
                or rows[0].get("contact_id") != self.contact_id
                or rows[0].get("state") != "delivered"):
            raise ValueError("public_restart_outbound_record")
        return _digest(own_text), _digest(other_text)

    def run(self):
        self.baseline = run_fresh_role(self.role, self.peer, self.exchange,
            pair_id=self.pair_id, deadline=self.baseline_deadline,
            clock=self.clock, sleep=self.sleep)
        from check_public_core_pair import verify_flow
        verify_flow(self.baseline, self.role, self.pair_id)
        if self.clock() >= self.end - RESTART_RESERVE_SECONDS:
            raise TimeoutError("public_restart_baseline_deadline")
        if self.role == "windows":
            if self.peer.sequence != self.baseline["public_request_count"]:
                raise ValueError("public_restart_baseline_count")
        elif self.peer.protocol.step != self.baseline["public_request_count"]:
            raise ValueError("public_restart_baseline_count")
        original = self._facts()
        self.profile, self.contact_id, self.contact_handle = (
            original["profile_handle"], original["contact_id"], original["contact_handle"])
        if self.role == "windows":
            before_stop = self.baseline["public_request_count"] + self.additional
            if self.peer.sequence != before_stop:
                raise ValueError("public_restart_before_stop_count")
            self._restart_owner(original)
        else:
            self._hold_android(original)
        self._ready()
        outbound_hash, inbound_hash = self._messages()
        self._same_facts(original)
        self._phase("restart_done", publish=True)
        self._phase("restart_done", publish=False)
        if self.role == "android":
            self._android_alive(self.android_process, self.android_protocol)
            total = self.baseline["public_request_count"] + self.additional
            if self.peer.protocol.step != total:
                raise ValueError("public_restart_total_count")
            counts = {"baseline": self.baseline["public_request_count"],
                      "additional": self.additional, "total": total}
        else:
            if self.peer.sequence != self.after_reopen:
                raise ValueError("public_restart_reopened_count")
            counts = {"baseline": self.baseline["public_request_count"],
                      "before_stop": before_stop, "after_reopen": self.after_reopen}
        outcome = {"v": 1, "role": self.role, "pair_id": self.pair_id,
                   "baseline": self.baseline,
                   "checks": dict(WINDOWS_CHECKS if self.role == "windows" else ANDROID_CHECKS),
                   "request_counts": counts,
                   "post_outbound_text_sha256": outbound_hash,
                   "post_inbound_text_sha256": inbound_hash,
                   "post_outbound_message_count": 1, "post_inbound_message_count": 1}
        return verify_restart_flow(outcome, self.role, self.pair_id)


def run_restart_role(role, peer, exchange, *, pair_id, overall_deadline,
                     clock=time.monotonic, sleep=time.sleep):
    return RestartFlow(role, peer, exchange, pair_id, overall_deadline, clock, sleep).run()
