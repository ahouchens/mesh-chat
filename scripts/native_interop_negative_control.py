"""Harness-only encrypted mailbox coordination for a selected-path block.

The room carries control acknowledgments, never application messages or receipts.
Only the existing run-bound artifact rendezvous may share its capability.
"""

import json
import math
import time

from mesh_chat import signal_mailbox

from native_interop_rendezvous import NEGATIVE_CASES, ROLES, checked_context


MAX_CONTROL_BYTES = 2048
POLL_SECONDS = 0.6
STAGE_SENDER = {"armed": "windows", "ready": "android", "checked": "windows"}
MAILBOX_ROLE = {"windows": "offer", "android": "answer"}
CONTROL_FIELDS = {"v", "context", "scenario", "sender", "recipient", "stage", "room_nonce"}


class NegativeControlError(ValueError):
    """A fixed, redacted qualification control failure."""


def new_capability(base):
    """Create one independent, short-lived encrypted room for a negative trial."""
    try:
        return signal_mailbox.create_pairing(base)
    except Exception:
        raise NegativeControlError("Negative-control capability is unavailable") from None


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate field")
        value[key] = item
    return value


class NegativeControlMailbox:
    def __init__(self, context, role, scenario, capability, *, base,
                 clock=time.monotonic, sleep=time.sleep):
        try:
            self.context = checked_context(context)
            if role not in ROLES or scenario not in NEGATIVE_CASES:
                raise ValueError("role or scenario")
            pair = signal_mailbox.parse_pairing(capability, base)
        except Exception:
            raise NegativeControlError("Negative-control capability or scope is invalid") from None
        self.role, self.scenario, self.base = role, scenario, base
        self.session, self.token, self.secret = pair["session"], pair["token"], pair["secret"]
        self.expires_at = pair["expires_at"]
        self.clock, self.sleep = clock, sleep
        self._sent, self._received = set(), set()

    def _live(self):
        if time.time() >= self.expires_at:
            raise NegativeControlError("Negative-control capability expired")

    def _expect_send(self, stage):
        if (type(stage) is not str or stage not in STAGE_SENDER
                or STAGE_SENDER[stage] != self.role or stage in self._sent):
            raise NegativeControlError("Negative-control stage is out of order")
        if stage == "ready" and "armed" not in self._received:
            raise NegativeControlError("Negative-control stage is out of order")
        if stage == "checked" and not ({"armed"} <= self._sent and {"ready"} <= self._received):
            raise NegativeControlError("Negative-control stage is out of order")

    def _expect_receive(self, stage):
        if (type(stage) is not str or stage not in STAGE_SENDER
                or STAGE_SENDER[stage] == self.role or stage in self._received):
            raise NegativeControlError("Negative-control stage is out of order")
        if stage == "ready" and "armed" not in self._sent:
            raise NegativeControlError("Negative-control stage is out of order")
        if stage == "checked" and not ({"armed"} <= self._received and {"ready"} <= self._sent):
            raise NegativeControlError("Negative-control stage is out of order")

    def _document(self, stage):
        return json.dumps({"v": 1, "context": self.context, "scenario": self.scenario,
                           "sender": self.role, "recipient": next(iter(ROLES - {self.role})),
                           "stage": stage, "room_nonce": self.session},
                          sort_keys=True, separators=(",", ":"))

    def send(self, stage):
        self._live()
        self._expect_send(stage)
        # Even an ambiguous HTTP failure cannot authorize another write.
        self._sent.add(stage)
        try:
            signal_mailbox.publish(self.base, self._document(stage), MAILBOX_ROLE[self.role],
                                   token=self.token, session=self.session, secret=self.secret)
        except Exception:
            raise NegativeControlError("Negative-control publish unavailable") from None
        self._live()
        return True

    def _stage(self, document, expected):
        try:
            if not isinstance(document, str) or not 0 < len(document.encode("utf-8")) <= MAX_CONTROL_BYTES:
                raise ValueError("document size")
            value = json.loads(document, object_pairs_hook=_unique_object)
            sender = STAGE_SENDER[expected]
            if (type(value) is not dict or set(value) != CONTROL_FIELDS
                    or type(value["v"]) is not int or value["v"] != 1
                    or checked_context(value["context"]) != self.context
                    or value["scenario"] != self.scenario
                    or value["sender"] != sender or value["recipient"] != self.role
                    or value["room_nonce"] != self.session):
                raise ValueError("foreign scope")
            stage = value["stage"]
            if stage == expected:
                return "expected"
            if expected == "checked" and stage == "armed" and "armed" in self._received:
                return "prior"
        except Exception:
            pass
        raise NegativeControlError("Negative-control document is invalid") from None

    def receive(self, stage, *, deadline):
        self._live()
        self._expect_receive(stage)
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or deadline <= self.clock()):
            raise NegativeControlError("Negative-control deadline is invalid or exhausted")
        sender = STAGE_SENDER[stage]
        while self.clock() < deadline:
            self._live()
            try:
                result = signal_mailbox.fetch(self.base, self.session, MAILBOX_ROLE[sender],
                                              token=self.token, secret=self.secret, pending=True)
            except Exception:
                raise NegativeControlError("Negative-control fetch unavailable") from None
            self._live()
            if self.clock() >= deadline:
                break
            if (type(result) is not dict or result.get("session_id") != self.session
                    or result.get("role") != MAILBOX_ROLE[sender]):
                raise NegativeControlError("Negative-control response is invalid")
            if (set(result) == {"session_id", "role", "document", "pending"}
                    and result["pending"] is True and result["document"] is None):
                pass
            elif set(result) == {"session_id", "role", "document"}:
                if self._stage(result["document"], stage) == "expected":
                    self._received.add(stage)
                    return True
            else:
                raise NegativeControlError("Negative-control response is invalid")
            remaining = deadline - self.clock()
            if remaining > 0:
                self.sleep(min(POLL_SECONDS, remaining))
        raise NegativeControlError("Negative-control deadline exhausted")
