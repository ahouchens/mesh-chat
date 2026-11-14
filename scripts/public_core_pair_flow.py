"""One public Core pairing and receipt scenario for an already open role session.

The caller owns installed artifacts, setup transport, host retirement and reports.
Only peer.request carries product operations; exchange carries sealed setup phases.
Messaging readiness here does not establish a physical ICE or native path.
"""

import hashlib
import math
import re
import time
from uuid import uuid4


ROLES = frozenset({"windows", "android"})
HEX32 = re.compile(r"[a-f0-9]{32}")
POLL_SECONDS = 5
FINISH_RESERVE_SECONDS = 60
MAX_REQUESTS = 96
ALTERNATE_PATHS = {"nearby_discovery": False, "lan_fallback": False, "help_route": False}
CALL_SETTINGS = ("stun_urls", "turn_url", "turn_username", "turn_broker_url",
                 "signal_mailbox_url", "store_call_signaling")


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(pair_id, role):
    return f"public-core-pair:v1:{pair_id}:{role}"


def _rows(value, name):
    rows = value.get(name)
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise ValueError("public_pair_view")
    return rows


class Flow:
    def __init__(self, role, peer, exchange, pair_id, deadline, clock, sleep):
        if (type(role) is not str or role not in ROLES or type(pair_id) is not str
                or HEX32.fullmatch(pair_id) is None or type(deadline) not in {int, float}
                or not math.isfinite(deadline) or deadline - clock() <= FINISH_RESERVE_SECONDS):
            raise ValueError("public_pair_arguments")
        self.role, self.peer, self.exchange = role, peer, exchange
        self.pair_id, self.deadline = pair_id, deadline
        self.clock, self.sleep = clock, sleep
        self.requests = 0
        self.profile = self.destination = self.pairing = self.contact = None

    def _budget(self):
        if self.clock() >= self.deadline - FINISH_RESERVE_SECONDS:
            raise TimeoutError("public_pair_deadline")
        return self.deadline - FINISH_RESERVE_SECONDS

    def request(self, operation, params=None, key=None):
        self._budget()
        if self.requests >= MAX_REQUESTS:
            raise ValueError("public_pair_request_budget")
        self.requests += 1
        value = self.peer.request(operation, params, key)
        self._budget()
        if type(value) is not dict:
            raise ValueError("public_pair_reply")
        return value

    def publish(self, phase, payload):
        limit = min(self._budget(), self.clock() + 90)
        self.exchange.publish(phase, payload, limit)
        if self.clock() >= limit:
            raise TimeoutError("public_pair_setup_deadline")

    def receive(self, phase):
        limit = min(self._budget(), self.clock() + 90)
        value = self.exchange.receive(phase, limit)
        if self.clock() >= limit:
            raise TimeoutError("public_pair_setup_deadline")
        if type(value) is not dict:
            raise ValueError("public_pair_setup")
        if phase != "offer_code" and value != {}:
            raise ValueError("public_pair_setup")
        return value

    def wait(self, phase, attempts, observe):
        phase_end = min(self._budget(), self.clock() + 90)
        for index in range(attempts):
            if self.clock() >= phase_end:
                raise TimeoutError("public_pair_" + phase)
            value = observe()
            if self.clock() >= phase_end:
                raise TimeoutError("public_pair_" + phase)
            if value is not None:
                return value
            if index + 1 == attempts:
                break
            target = self.clock() + POLL_SECONDS
            if target >= phase_end:
                break
            while self.clock() < target:
                self.sleep(target - self.clock())
            self._budget()
        raise TimeoutError("public_pair_" + phase)

    def snapshot(self):
        return self.request("application.snapshot")

    def fresh_profile(self):
        caps = self.request("runtime.capabilities")
        handles, operations = caps.get("profiles"), caps.get("operations")
        required = {"profile.create", "peer.pairing_begin", "peer.pairing_query",
                    "contact.invitation", "peer.approve", "connection.snapshot", "message.enqueue",
                    "message.query"}
        if (type(handles) is not list or len(handles) != 1 or type(handles[0]) is not str
                or not handles[0] or type(operations) is not list
                or any(type(item) is not str for item in operations)
                or not required <= set(operations) or "native.command" in operations):
            raise ValueError("public_pair_capabilities")
        empty = self.snapshot()
        if empty.get("profile") is not None or _rows(empty, "contacts") or _rows(empty, "messages"):
            raise ValueError("public_pair_not_fresh")
        name = "Independent " + self.role
        self.request("profile.create", {"display_name": name}, str(uuid4()))
        after = self.request("runtime.capabilities")
        if after.get("profiles") != handles:
            raise ValueError("public_pair_profile_handle")
        self.profile = handles[0]
        identity = self.request("profile.query", {"profile": self.profile})
        destination = identity.get("destination")
        if type(destination) is not str or HEX32.fullmatch(destination) is None:
            raise ValueError("public_pair_identity")
        self.destination = destination
        fresh = self.snapshot()
        if (type(fresh.get("profile")) is not dict
                or fresh["profile"].get("destination_hash") != destination
                or fresh["profile"].get("display_name") != name
                or _rows(fresh, "contacts") or _rows(fresh, "messages")):
            raise ValueError("public_pair_profile_snapshot")
        self.request("settings.update", {"profile": self.profile, "settings": ALTERNATE_PATHS})
        settings = self.request("settings.query", {"profile": self.profile}).get("settings")
        if type(settings) is not dict or any(settings.get(key) is not False for key in ALTERNATE_PATHS):
            raise ValueError("public_pair_alternate_paths")
        calls = self.request("call.settings_query", {"profile": self.profile}).get("settings")
        if (type(calls) is not dict or calls.get("turn_configured") is not False
                or calls.get("turn_username") is not None or any(key not in calls for key in CALL_SETTINGS)):
            raise ValueError("public_pair_call_settings")
        relay = {key: calls[key] for key in CALL_SETTINGS}
        relay.update(turn_broker_consent=True, relay_only=True)
        self.request("call.settings_update", {"profile": self.profile, "settings": relay})
        applied = self.request("call.settings_query", {"profile": self.profile}).get("settings")
        if type(applied) is not dict or applied.get("turn_broker_consent") is not True or applied.get("relay_only") is not True:
            raise ValueError("public_pair_relay_settings")

    def begin(self, role, code=None):
        params = {"profile": self.profile, "role": role, "allow_direct_ip_disclosure": False}
        if code is not None:
            params["pairing_code"] = code
        begun = self.request("peer.pairing_begin", params, str(uuid4()))
        pairing = begun.get("pairing")
        if type(pairing) is not str or not pairing:
            raise ValueError("public_pair_begin")
        self.pairing = pairing

    def offer(self):
        self.begin("offer")
        def code():
            state = self.request("peer.pairing_query", {"profile": self.profile, "pairing": self.pairing})
            if state.get("state") in {"retiring", "retired"}:
                raise ValueError("public_pair_retired")
            value = state.get("pairing_code")
            if value is None:
                return None
            if (state.get("state") != "offer_ready" or type(value) is not str
                    or not 1 <= len(value.encode("utf-8")) <= 2048):
                raise ValueError("public_pair_code")
            return value
        self.publish("offer_code", {"pairing_code": self.wait("offer_code", 6, code)})
        self.receive("invitation_accepted")
        def pending():
            contacts = _rows(self.snapshot(), "contacts")
            if len(contacts) > 1:
                raise ValueError("public_pair_extra_contact")
            return next((row for row in contacts if row.get("trust") == "pending_request"), None)
        request = self.wait("pending_request", 12, pending)
        handle = request.get("core_handle")
        if type(handle) is not str or not handle:
            raise ValueError("public_pair_pending_handle")
        approved = self.request("peer.approve", {"profile": self.profile, "peer": handle})
        if approved.get("trust") not in {"approved", "verified"}:
            raise ValueError("public_pair_approval")
        self.publish("approved", {})
        return "request_approved"

    def answer(self):
        value = self.receive("offer_code")
        code = value.get("pairing_code")
        if (set(value) != {"pairing_code"} or type(code) is not str
                or not 1 <= len(code.encode("utf-8")) <= 2048):
            raise ValueError("public_pair_code")
        self.begin("answer", code)
        def invitation():
            view = self.snapshot()
            invitations = [row for row in _rows(view, "contact_invitations") if row.get("state") == "pending"]
            if len(invitations) > 1 or _rows(view, "contacts"):
                raise ValueError("public_pair_implicit_contact")
            return invitations[0] if invitations else None
        pending = self.wait("invitation", 12, invitation)
        handle = pending.get("id")
        if type(handle) is not str or not handle:
            raise ValueError("public_pair_invitation")
        self.request("contact.invitation", {"profile": self.profile, "action": "decide",
                                             "invitation": handle, "accept": True})
        self.publish("invitation_accepted", {})
        self.receive("approved")
        return "invitation_accepted"

    def relationship(self):
        def approved():
            view = self.snapshot()
            contacts = _rows(view, "contacts")
            if len(contacts) > 1:
                raise ValueError("public_pair_extra_contact")
            if not contacts or contacts[0].get("trust") not in {"approved", "verified"}:
                return None
            return contacts[0]
        self.contact = self.wait("relationship", 10, approved)
        peer_destination = self.contact.get("destination_hash")
        if (type(peer_destination) is not str or HEX32.fullmatch(peer_destination) is None
                or peer_destination == self.destination or type(self.contact.get("core_handle")) is not str
                or not self.contact["core_handle"] or type(self.contact.get("id")) is not str):
            raise ValueError("public_pair_contact")
        return peer_destination

    def transfer_and_cancel(self):
        def transferred():
            state = self.request("peer.pairing_query", {"profile": self.profile, "pairing": self.pairing})
            if state.get("state") in {"retiring", "retired"}:
                raise ValueError("public_pair_retired")
            return state if state.get("state") == "transferred" else None
        self.wait("transfer", 6, transferred)
        cancelled = self.request("peer.pairing_cancel", {"profile": self.profile, "pairing": self.pairing}, str(uuid4()))
        if cancelled.get("state") != "transferred" or cancelled.get("pairing_code") is not None:
            raise ValueError("public_pair_cancel")
        contacts = _rows(self.snapshot(), "contacts")
        if (len(contacts) != 1 or contacts[0].get("id") != self.contact["id"]
                or contacts[0].get("trust") not in {"approved", "verified"}):
            raise ValueError("public_pair_cancel_contact")

    def ready(self):
        def observation():
            profile = self.request("profile.query", {"profile": self.profile})
            connections = profile.get("connections")
            if type(connections) is not list or len(connections) > 2 or any(type(item) is not str for item in connections):
                raise ValueError("public_pair_connections")
            ready = 0
            for handle in connections:
                value = self.request("connection.snapshot", {"profile": self.profile, "connection": handle})
                detail = value.get("observation")
                if type(detail) is not dict:
                    raise ValueError("public_pair_connection_observation")
                ready += detail.get("messaging_ready") is True
            if ready > 1:
                raise ValueError("public_pair_extra_ready")
            return True if ready == 1 else None
        self.wait("messaging_ready", 10, observation)
        self.publish("ready", {})
        self.receive("ready")

    def receipts(self):
        own_text = _text(self.pair_id, self.role)
        other_role = "android" if self.role == "windows" else "windows"
        other_text = _text(self.pair_id, other_role)
        handle = self.contact["core_handle"]
        sent = self.request("message.enqueue", {"profile": self.profile, "recipient": handle,
                                                "kind": "text", "text": own_text}, str(uuid4()))
        message = sent.get("message")
        if sent.get("accepted") is not True or type(message) is not str or not message:
            raise ValueError("public_pair_enqueue")
        def delivered():
            value = self.request("message.query", {"profile": self.profile, "message": message})
            if value.get("message") != message or value.get("text") != own_text or value.get("recipient") != handle:
                raise ValueError("public_pair_message")
            return True if value.get("state") == "delivered" else None
        self.wait("outbound_delivery", 8, delivered)
        def inbound():
            rows = [row for row in _rows(self.snapshot(), "messages")
                    if row.get("kind") == "chat" and row.get("direction") == "inbound"
                    and row.get("text") == other_text]
            if len(rows) > 1:
                raise ValueError("public_pair_duplicate_inbound")
            return rows[0] if rows else None
        inbound_row = self.wait("inbound_message", 8, inbound)
        if inbound_row.get("contact_id") != self.contact["id"]:
            raise ValueError("public_pair_inbound_contact")
        rows = [row for row in _rows(self.snapshot(), "messages")
                if row.get("kind") == "chat" and row.get("direction") == "outbound"
                and row.get("text") == own_text]
        if (len(rows) != 1 or rows[0].get("contact_id") != self.contact["id"]
                or rows[0].get("state") != "delivered"):
            raise ValueError("public_pair_outbound_record")
        self.publish("done", {})
        self.receive("done")
        return _digest(own_text), _digest(other_text)


def run_role(role, peer, exchange, *, pair_id, deadline, clock=time.monotonic, sleep=time.sleep):
    """Return only observed public Core facts; caller must positively finish both hosts."""
    flow = Flow(role, peer, exchange, pair_id, deadline, clock, sleep)
    flow.fresh_profile()
    decision = flow.offer() if role == "windows" else flow.answer()
    peer_destination = flow.relationship()
    flow.transfer_and_cancel()
    flow.ready()
    outbound_hash, inbound_hash = flow.receipts()
    return {"v": 1, "role": role, "pair_id": pair_id,
            "self_destination_sha256": _digest(flow.destination),
            "peer_destination_sha256": _digest(peer_destination),
            "explicit_decision": decision, "contact_count": 1,
            "contact_trust": flow.contact["trust"], "messaging_ready": True,
            "pairing_transferred": True, "cancel_preserved_transferred": True,
            "outbound_text_sha256": outbound_hash, "outbound_message_count": 1,
            "outbound_delivered": True, "inbound_text_sha256": inbound_hash,
            "inbound_message_count": 1, "public_request_count": flow.requests}
