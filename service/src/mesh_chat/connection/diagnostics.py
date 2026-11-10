"""Bounded, payload-free diagnostics. No peer identifiers leave this module."""

from collections import Counter, deque
from dataclasses import dataclass


PAIRING_RETIREMENT_PHASES = frozenset({
    "discover", "wait_offer", "gather_offer", "gather_answer", "publish_offer",
    "publish_answer", "wait_answer", "apply_answer", "checking", "unknown",
})
PAIRING_RETIREMENT_EVENTS = frozenset({
    "tick", "failed", "result", "adopted", "context_changed", "handoff_rejected", "unknown",
})
PAIRING_RETIREMENT_REASONS = frozenset({
    "transient", "rate_limited", "configuration", "invalid_document", "revoked",
    "unsupported", "internal", "phase_timeout", "ineligible", "context_changed",
    "network_unavailable", "wrong_resource", "invalid_adoption", "invalid_handoff",
    "invalid_pending", "unverified_resource", "missing_handoff", "handoff_rejected", "unknown",
})


def validated_pairing_retirement(value) -> dict | None:
    """Select the exact private diagnostic DTO; never copy arbitrary errors."""
    allowed = {"phase": PAIRING_RETIREMENT_PHASES, "event": PAIRING_RETIREMENT_EVENTS,
               "reason": PAIRING_RETIREMENT_REASONS}
    if (type(value) is not dict or set(value) != set(allowed)
            or any(type(key) is not str for key in value)
            or any(type(value[key]) is not str or value[key] not in choices
                   for key, choices in allowed.items())):
        return None
    return {key: value[key] for key in allowed}


@dataclass(frozen=True)
class Record:
    sequence: int
    event: str
    previous: str
    current: str
    reason: str
    effects: tuple[str, ...]


class Diagnostics:
    def __init__(self, limit: int):
        self._records = deque(maxlen=limit)
        self._counts = Counter()
        self._sequence = 0

    def record(self, previous, event, result):
        self._sequence += 1
        self._counts[result.reason] += 1
        self._records.append(Record(self._sequence, type(event).__name__,
                             previous.reason, result.state.reason, result.reason,
                             tuple(type(effect).__name__ for effect in result.effects)))

    def snapshot(self):
        return tuple(self._records), dict(self._counts)
