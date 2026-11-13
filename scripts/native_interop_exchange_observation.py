"""Identifier-free baseline receipt evidence; never performs an extra query."""

from native_interop_diagnostics import RECOVERY_STATES

SCENARIOS = frozenset({"direct", "turn_udp", "turn_tcp", "turn_tls", "impaired"})
STAGES = frozenset({"receipt_delivery_wait", "receipt_inbound_wait",
                   "receipt_outbound_records", "receipt_record_validation"})
POLL_CAP = 512


def receipt_exchange_snapshot(value):
    if (type(value) is not dict or set(value) != {
            "scenario", "initiator", "index", "stage", "delivery", "records"}
            or type(value["scenario"]) is not str or value["scenario"] not in SCENARIOS
            or type(value["initiator"]) is not str or value["initiator"] not in {"windows", "android"}
            or type(value["stage"]) is not str or value["stage"] not in STAGES
            or type(value["index"]) is not int
            or not 0 <= value["index"] < (20 if value["scenario"] == "impaired" else 1)):
        return None
    delivery = value["delivery"]
    if (type(delivery) is not dict or set(delivery) != {"polls", "polls_capped",
            "first_state", "last_state", "transitions", "transitions_capped"}
            or any(type(delivery[key]) is not int or not 0 <= delivery[key] <= POLL_CAP
                   for key in ("polls", "transitions"))
            or any(type(delivery[key]) is not bool for key in ("polls_capped", "transitions_capped"))
            or delivery["transitions"] > delivery["polls"]
            or (delivery["polls_capped"] and delivery["polls"] != POLL_CAP)
            or (delivery["transitions_capped"] and
                (delivery["transitions"] != POLL_CAP or not delivery["polls_capped"]))
            or (not delivery["polls_capped"] and delivery["transitions"] > max(0, delivery["polls"] - 1))):
        return None
    first, last = delivery["first_state"], delivery["last_state"]
    if delivery["polls"] == 0:
        if first is not None or last is not None or delivery["transitions"]:
            return None
    elif (type(first) is not str or type(last) is not str
            or first not in RECOVERY_STATES or last not in RECOVERY_STATES
            or (delivery["transitions"] == 0 and first != last)):
        return None
    records = value["records"]
    if records is not None:
        if (type(records) is not dict or set(records) != {"polls", "polls_capped", "inbound",
                "inbound_capped", "outbound", "outbound_capped", "outbound_native_id_present"}
                or type(records["polls"]) is not int or not 1 <= records["polls"] <= POLL_CAP
                or type(records["polls_capped"]) is not bool
                or (records["polls_capped"] and records["polls"] != POLL_CAP)):
            return None
        for direction in ("inbound", "outbound"):
            count, capped = records[direction], records[direction + "_capped"]
            if (type(count) is not int or not 0 <= count <= 2 or type(capped) is not bool
                    or (capped and count != 2)):
                return None
        if records["outbound"] == 1:
            if type(records["outbound_native_id_present"]) is not bool:
                return None
        elif records["outbound_native_id_present"] is not None:
            return None
    return {**value, "delivery": dict(delivery), "records": dict(records) if records is not None else None}


class ReceiptExchangeObservation:
    def __init__(self, scenario, index, pairing, phase, handle, own, other):
        parts = scenario.split(":")
        if (len(parts) != 2 or parts[0] not in SCENARIOS or parts[1] not in {"windows", "android"}
                or type(index) is not int or not 0 <= index < (20 if parts[0] == "impaired" else 1)
                or phase != parts[0] + "_authenticated_receipts"
                or any(type(value) is not str or not value for value in (pairing, handle, own, other))
                or own == other):
            raise ValueError("Invalid receipt observation scope")
        self.scenario, self.initiator, self.index = *parts, index
        self.pairing, self.phase, self.handle = pairing, phase, handle
        self._own, self._other = own, other
        self._polls = self._transitions = 0
        self._polls_capped = self._transitions_capped = False
        self._first = self._last = self._records = self._error = None
        self._disabled = False

    def matches(self, phase, pairing):
        return not self._disabled and phase == self.phase and pairing == self.pairing

    def delivery(self, handle, state):
        if handle != self.handle:
            self._disabled = True
            return
        if type(state) is not str or state not in RECOVERY_STATES:
            self._disabled = True
            return
        if self._first is None:
            self._first = state
        elif state != self._last:
            self._transitions_capped |= self._transitions == POLL_CAP
            self._transitions = min(POLL_CAP, self._transitions + 1)
        self._polls_capped |= self._polls == POLL_CAP
        self._polls = min(POLL_CAP, self._polls + 1)
        self._last = state

    def records(self, messages):
        if type(messages) is not list or any(type(item) is not dict for item in messages):
            self._disabled = True
            return
        inbound = outbound = 0
        native = False
        for item in messages:
            if item.get("kind") != "chat":
                continue
            if item.get("direction") == "inbound" and item.get("text") == self._other:
                inbound += 1
            elif item.get("direction") == "outbound" and item.get("text") == self._own:
                outbound += 1
                native = type(item.get("native_message_id")) is str and bool(item["native_message_id"])
        previous = self._records
        polls = previous["polls"] if previous is not None else 0
        self._records = {"polls": min(POLL_CAP, polls + 1),
            "polls_capped": polls == POLL_CAP,
            "inbound": min(2, inbound), "inbound_capped": inbound > 2,
            "outbound": min(2, outbound), "outbound_capped": outbound > 2,
            "outbound_native_id_present": native if outbound == 1 else None}

    def failed(self, error):
        self._error = error

    def failure(self, error, phase, pairing, path):
        if (error is not self._error or not self.matches(phase, pairing)
                or type(path) is not dict or path.get("scenario") != self.scenario
                or path.get("stage") not in STAGES):
            return None
        # Construct a fixed schema; no handle, message content, record ID or operation leaves RAM.
        return receipt_exchange_snapshot({"scenario": self.scenario, "initiator": self.initiator, "index": self.index,
            "stage": path["stage"], "delivery": {"polls": self._polls,
                "polls_capped": self._polls_capped, "first_state": self._first,
                "last_state": self._last, "transitions": self._transitions,
                "transitions_capped": self._transitions_capped},
            "records": dict(self._records) if self._records is not None else None})
