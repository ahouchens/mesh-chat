"""One installed public-pair continuation under an externally owned Android loss rule.

Only the peer's public request method performs product operations. The Android
gateway fixture owns the OS rule; its control channel must stay usable while the
application UID is partitioned. This diagnostic does not identify the ICE path.
"""

import hashlib
import math
import time
from uuid import uuid4

from public_core_pair_flow import run_role


MIN_BLOCK_SECONDS = 30
MAX_BLOCK_SECONDS = 45
RECOVERY_SECONDS = 240
RECEIPT_SECONDS = 30
MAX_ADDITIONAL_REQUESTS = 100


def text(pair_id, role):
    return f"public-core-partition:v1:{pair_id}:{role}"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PartitionFlow:
    def __init__(self, role, peer, exchange, pair_id, deadline, fault, clock, sleep,
                 request_limit=MAX_ADDITIONAL_REQUESTS):
        if role not in {"windows", "android"} or (role == "android") != (fault is not None):
            raise ValueError("public_partition_fault_owner")
        self.role, self.other = role, "android" if role == "windows" else "windows"
        self.peer, self.exchange, self.pair_id = peer, exchange, pair_id
        self.deadline, self.fault, self.clock, self.sleep = deadline, fault, clock, sleep
        self.request_limit = min(request_limit, MAX_ADDITIONAL_REQUESTS)
        self.requests = 0

    def remaining(self, cap):
        value = min(cap, self.deadline - self.clock())
        if not math.isfinite(value) or value <= 0:
            raise TimeoutError("public_partition_deadline")
        return value

    def request(self, operation, params=None, key=None):
        self.remaining(30)
        if self.requests >= self.request_limit:
            raise ValueError("public_partition_request_budget")
        self.requests += 1
        value = self.peer.request(operation, params, key)
        self.remaining(30)
        if type(value) is not dict:
            raise ValueError("public_partition_reply")
        return value

    def publish(self, phase):
        limit = self.clock() + self.remaining(90)
        self.exchange.publish(phase, {}, limit)
        if self.clock() >= limit:
            raise TimeoutError("public_partition_control_deadline")

    def receive(self, phase):
        limit = self.clock() + self.remaining(90)
        if self.exchange.receive(phase, limit) != {} or self.clock() >= limit:
            raise ValueError("public_partition_control")

    def barrier(self, phase):
        self.publish(phase)
        self.receive(phase)

    def wait(self, label, seconds, observe, *, interval=3):
        end = self.clock() + self.remaining(seconds)
        while self.clock() < end:
            value = observe()
            if value is not None:
                return value
            self.sleep(min(interval, end - self.clock()))
        raise TimeoutError("public_partition_" + label)

    def identity(self):
        caps = self.request("runtime.capabilities")
        profiles = caps.get("profiles")
        if type(profiles) is not list or len(profiles) != 1 or type(profiles[0]) is not str:
            raise ValueError("public_partition_profile")
        profile = profiles[0]
        identity = self.request("profile.query", {"profile": profile})
        destination = identity.get("destination")
        snapshot = self.request("application.snapshot")
        contacts = snapshot.get("contacts")
        if (type(destination) is not str or not destination or type(contacts) is not list
                or len(contacts) != 1 or type(contacts[0]) is not dict
                or contacts[0].get("trust") not in {"approved", "verified"}
                or type(contacts[0].get("core_handle")) is not str
                or type(contacts[0].get("id")) is not str):
            raise ValueError("public_partition_authority")
        return profile, destination, {field: contacts[0][field] for field in
                                      ("id", "core_handle", "trust")}

    def ready(self, origin):
        known = []
        samples = 0
        def observe():
            nonlocal known, samples
            if samples % 5 == 0 or not known:
                caps = self.request("profile.query", {"profile": self.profile})
                known = caps.get("connections")
                if type(known) is not list or len(known) > 2:
                    raise ValueError("public_partition_connections")
            samples += 1
            active = 0
            for handle in known:
                if type(handle) is not str:
                    raise ValueError("public_partition_connection_handle")
                view = self.request("connection.snapshot", {"profile": self.profile, "connection": handle})
                observation = view.get("observation")
                if type(observation) is not dict:
                    raise ValueError("public_partition_connection_view")
                active += observation.get("messaging_ready") is True
            if active > 1:
                raise ValueError("public_partition_extra_ready")
            return True if active == 1 else None
        # Windows starts at the blocked marker, before restoration, so its
        # deadline is conservative without trusting clocks across runners.
        self.wait("readiness", RECOVERY_SECONDS - (self.clock() - origin), observe, interval=8)

    def delivered(self, handle, own):
        value = self.request("message.query", {"profile": self.profile, "message": handle})
        if value.get("message") != handle or value.get("text") != own or value.get("recipient") != self.contact["core_handle"]:
            raise ValueError("public_partition_message")
        return value.get("state") == "delivered"

    def records(self, own, other):
        rows = self.request("application.snapshot").get("messages")
        if type(rows) is not list or any(type(row) is not dict for row in rows):
            raise ValueError("public_partition_messages")
        outbound = [row for row in rows if row.get("kind") == "chat" and row.get("direction") == "outbound"
                    and row.get("text") == own]
        inbound = [row for row in rows if row.get("kind") == "chat" and row.get("direction") == "inbound"
                   and row.get("text") == other]
        if len(outbound) > 1 or len(inbound) > 1:
            raise ValueError("public_partition_duplicate")
        return outbound, inbound

    def run(self):
        self.profile, self.destination, self.contact = self.identity()
        self.barrier("partition_ready")
        blocked_at = None
        if self.role == "android":
            self.fault.block()
            blocked_at = self.clock()
            self.publish("partition_blocked")
        else:
            self.receive("partition_blocked")
            readiness_origin = self.clock()
        own, other = text(self.pair_id, self.role), text(self.pair_id, self.other)
        sent = self.request("message.enqueue", {"profile": self.profile,
            "recipient": self.contact["core_handle"], "kind": "text", "text": own}, str(uuid4()))
        handle = sent.get("message")
        if sent.get("accepted") is not True or type(handle) is not str or not handle:
            raise ValueError("public_partition_enqueue")
        def require_blocked():
            if self.delivered(handle, own):
                raise ValueError("public_partition_premature_receipt")
            outbound, inbound = self.records(own, other)
            if inbound or len(outbound) != 1:
                raise ValueError("public_partition_bypassed")
        require_blocked()
        self.sleep(2)
        require_blocked()
        if self.role == "windows":
            # The remote owner keeps the outage open until this observation is
            # sealed. A delivered state cannot be hidden by an early marker.
            self.sleep(20)
            require_blocked()
        self.barrier("partition_checked")
        witness = None
        if self.role == "android":
            while self.clock() - blocked_at < MIN_BLOCK_SECONDS:
                self.sleep(min(.25, MIN_BLOCK_SECONDS - (self.clock() - blocked_at)))
            require_blocked()
            if self.fault.dropped() <= 0:
                raise ValueError("public_partition_no_app_packets_dropped")
            witness = self.fault.unblock()
            readiness_origin = self.clock()
            duration = self.clock() - blocked_at
            if (duration > MAX_BLOCK_SECONDS or type(witness) is not dict
                    or witness.get("app_uid_bound") is not True
                    or witness.get("process_bound") is not True
                    or witness.get("owned_route") is not True
                    or witness.get("profile_restored") is not True
                    or type(witness.get("dropped_packets")) is not int
                    or witness["dropped_packets"] <= 0):
                raise ValueError("public_partition_fault_witness")
            self.publish("partition_restored")
        else:
            require_blocked()
            self.receive("partition_restored")
            duration = None
        self.ready(readiness_origin)
        ready_ms = int((self.clock() - readiness_origin) * 1000)
        delivered_at = self.clock()
        self.wait("receipt", RECEIPT_SECONDS, lambda: True if self.delivered(handle, own) else None)
        def inbound_observed():
            outbound, inbound = self.records(own, other)
            return (outbound, inbound) if inbound else None
        outbound, inbound = self.wait("inbound", RECEIPT_SECONDS - (self.clock() - delivered_at), inbound_observed)
        receipt_ms = int((self.clock() - delivered_at) * 1000)
        if (len(outbound) != 1 or len(inbound) != 1 or outbound[0].get("state") != "delivered"
                or outbound[0].get("contact_id") != self.contact["id"]
                or inbound[0].get("contact_id") != self.contact["id"]):
            raise ValueError("public_partition_record")
        profile, destination, contact = self.identity()
        if (profile, destination, contact) != (self.profile, self.destination, self.contact):
            raise ValueError("public_partition_authority_changed")
        self.barrier("partition_done")
        return {"v": 1, "role": self.role, "pair_id": self.pair_id,
            "outbound_text_sha256": digest(own), "inbound_text_sha256": digest(other),
            "outbound_message_count": 1, "inbound_message_count": 1,
            "outbound_delivered": True, "authority_unchanged": True,
            "no_receipt_during_block": True, "readiness_bound_origin": (
                "fault_unblock" if self.role == "android" else "blocked_marker"),
            "readiness_after_origin_ms": ready_ms,
            "receipt_after_readiness_ms": receipt_ms,
            "block_duration_ms": int(duration * 1000) if duration is not None else None,
            "fault_witness": witness, "selected_path_type": None,
            "selected_path_qualified": False, "additional_request_count": self.requests}


def run_partition_role(role, peer, exchange, *, pair_id, deadline, fault=None,
                       clock=time.monotonic, sleep=time.sleep):
    # Reserve time for the partition and its recovery before starting the
    # unchanged public pairing flow.
    baseline = run_role(role, peer, exchange, pair_id=pair_id,
                        deadline=deadline - 360, clock=clock, sleep=sleep)
    flow = PartitionFlow(role, peer, exchange, pair_id, deadline, fault, clock, sleep,
                         request_limit=126 - baseline["public_request_count"])
    return {"baseline": baseline, "partition": flow.run()}
