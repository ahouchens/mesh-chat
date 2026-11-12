"""Bounded, payload-free diagnostics. No peer identifiers leave this module."""

from collections import Counter, deque
from dataclasses import dataclass
from math import isfinite


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


GATHER_FAILURE_FIELDS = {
    "as_of": frozenset({"phase_deadline"}),
    "worker": frozenset({"queued", "started", "completed", "unknown"}),
    "stage": frozenset({"not_started", "ice_config", "native_accept", "answer_sign",
                         "bind_onboarding", "complete", "unknown"}),
    "stage_state": frozenset({"entered", "completed", "unknown"}),
    "last_completed": frozenset({"none", "ice_config", "native_accept", "answer_sign",
                                  "bind_onboarding", "unknown"}),
    "queue_age": frozenset({"lt1s", "1to5s", "5to20s", "20to25s", "gte25s", "unknown"}),
    "stage_age": frozenset({"lt1s", "1to5s", "5to20s", "20to25s", "gte25s", "unknown"}),
}


def validated_gather_failure(value) -> dict | None:
    """Copy only the frozen private, payload-free diagnostic schema."""
    if (type(value) is not dict or set(value) != set(GATHER_FAILURE_FIELDS)
            or any(type(key) is not str for key in value)
            or any(type(value[key]) is not str or value[key] not in choices
                   for key, choices in GATHER_FAILURE_FIELDS.items())):
        return None
    return {key: value[key] for key in GATHER_FAILURE_FIELDS}


def _age_bucket(start, end):
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not isfinite(start) or not isfinite(end) or end < start):
        return "unknown"
    elapsed = end - start
    return ("lt1s" if elapsed < 1 else "1to5s" if elapsed < 5 else
            "5to20s" if elapsed < 20 else "20to25s" if elapsed < 25 else "gte25s")


def gather_failure_at_deadline(deadline, worker_history, stage_history):
    """Select only fixed milestones that happened by the original phase deadline."""
    unknown = {"as_of": "phase_deadline", "worker": "unknown", "stage": "unknown",
               "stage_state": "unknown", "last_completed": "unknown",
               "queue_age": "unknown", "stage_age": "unknown"}
    if type(deadline) not in (int, float) or not isfinite(deadline):
        return unknown
    try:
        worker = "unknown"
        queued = started = None
        previous = float("-inf")
        saw_late = False
        for state, when in worker_history:
            if type(when) not in (int, float) or not isfinite(when) or when < previous:
                return unknown
            previous = when
            if when > deadline:
                saw_late = True
                continue
            if saw_late or state not in {"queued", "started", "completed"}:
                return unknown
            worker = state
            if state == "queued":
                queued = when
            elif state == "started":
                started = when
        queue_age = _age_bucket(queued, started if started is not None else deadline)
        def unknown_stage():
            return {"as_of": "phase_deadline", "worker": worker, "stage": "unknown",
                    "stage_state": "unknown", "last_completed": "unknown",
                    "queue_age": queue_age, "stage_age": "unknown"}
        stage = "not_started" if worker == "queued" and stage_history == () else "unknown"
        stage_state = "unknown"
        last_completed = "none" if worker == "queued" and stage_history == () else "unknown"
        entered = None
        entered_label = None
        stage_end = None
        previous = float("-inf")
        saw_late = False
        previous_stage = -1
        completed_stage = -1
        order = {"ice_config": 0, "native_accept": 1, "answer_sign": 2,
                 "bind_onboarding": 3, "complete": 4}
        for label, state, when in (() if stage_history is None else stage_history):
            if type(when) not in (int, float) or not isfinite(when) or when < previous:
                return unknown_stage()
            previous = when
            if when > deadline:
                saw_late = True
                continue
            if (saw_late or label not in order or state not in {"entered", "completed"}):
                return unknown_stage()
            index = order[label]
            if index < previous_stage or (label == "complete" and state != "completed"):
                return unknown_stage()
            if index > previous_stage:
                if (previous_stage >= 0 and
                        (index > previous_stage + 1 or completed_stage != previous_stage)):
                    last_completed = "unknown"
                entered = entered_label = None
                previous_stage = index
            if last_completed == "unknown" and index == 0 and state == "entered":
                last_completed = "none"
            stage, stage_state = label, state
            if state == "entered":
                if entered_label == label:
                    return unknown_stage()
                entered, entered_label, stage_end = when, label, deadline
            elif label == "complete":
                entered = entered_label = stage_end = None
            else:
                if completed_stage == index:
                    return unknown_stage()
                stage_end = when if entered_label == label else None
                last_completed = label
                completed_stage = index
        result = {"as_of": "phase_deadline", "worker": worker, "stage": stage,
                  "stage_state": stage_state, "last_completed": last_completed,
                  "queue_age": queue_age,
                  "stage_age": _age_bucket(entered, stage_end)}
        return validated_gather_failure(result) or unknown
    except (TypeError, ValueError):
        return unknown


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
