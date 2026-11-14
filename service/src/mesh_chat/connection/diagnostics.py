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


CHECKING_OBSERVATION_FIELDS = {
    "as_of": frozenset({"last_checking_poll"}),
    "resource": frozenset({"current", "missing"}),
    "profile": frozenset({"not_checked", "unbound", "unavailable", "denied", "authorized"}),
    "ice": frozenset({"not_checked", "connected", "not_connected"}),
    "channel": frozenset({"not_checked", "open", "not_open"}),
}


def validated_checking_observation(retirement, value) -> dict | None:
    """A last-poll sample is evidence only for the exact checking timeout."""
    cause = validated_pairing_retirement(retirement)
    if (cause != {"phase": "checking", "event": "tick", "reason": "phase_timeout"}
            or type(value) is not dict or set(value) != set(CHECKING_OBSERVATION_FIELDS)
            or any(type(key) is not str for key in value)
            or any(type(value[key]) is not str or value[key] not in choices
                   for key, choices in CHECKING_OBSERVATION_FIELDS.items())):
        return None
    unchecked = value["ice"] == "not_checked" and value["channel"] == "not_checked"
    if ((value["resource"] == "missing") != (value["profile"] == "not_checked")
            or (value["ice"] == "not_checked") != (value["channel"] == "not_checked")
            or (value["profile"] in {"not_checked", "unbound", "unavailable"} and not unchecked)
            or (value["profile"] == "authorized" and unchecked)):
        return None
    return {key: value[key] for key in CHECKING_OBSERVATION_FIELDS}


GATHER_FAILURE_FIELDS = {
    "as_of": frozenset({"phase_deadline"}),
    "worker": frozenset({"queued", "started", "completed", "unknown"}),
    "stage": frozenset({"not_started", "ice_config", "native_offer", "offer_sign", "native_accept", "answer_sign",
                         "bind_onboarding", "complete", "unknown"}),
    "stage_state": frozenset({"entered", "completed", "unknown"}),
    "last_completed": frozenset({"none", "ice_config", "native_offer", "offer_sign", "native_accept", "answer_sign",
                                  "bind_onboarding", "unknown"}),
    "queue_age": frozenset({"lt1s", "1to5s", "5to20s", "20to25s", "gte25s", "unknown"}),
    "stage_age": frozenset({"lt1s", "1to5s", "5to20s", "20to25s", "gte25s", "unknown"}),
}
GATHER_STAGE_ORDER = {
    "gather_offer": {"ice_config": 0, "native_offer": 1, "offer_sign": 2, "complete": 3},
    "gather_answer": {"ice_config": 0, "native_accept": 1, "answer_sign": 2,
                      "bind_onboarding": 3, "complete": 4},
}
FAILED_GATHER_FAILURE_FIELDS = {
    **GATHER_FAILURE_FIELDS,
    "as_of": frozenset({"failed_result"}),
    "exception_kind": frozenset({"native_unavailable", "identity_mismatch", "validation_error", "unknown"}),
    "native_code": frozenset({"answer_failed", "network_monitor_failed", "session_closed",
                              "disposal_timeout", "no_candidates", "missing_data_channel",
                              "sdp_failed", "unknown", "not_applicable"}),
}


def validated_gather_failure(value) -> dict | None:
    """Copy only the frozen private, payload-free diagnostic schema."""
    if type(value) is not dict or type(value.get("as_of")) is not str:
        return None
    allowed = (GATHER_FAILURE_FIELDS if value.get("as_of") == "phase_deadline" else
               FAILED_GATHER_FAILURE_FIELDS if value.get("as_of") == "failed_result" else None)
    if (allowed is None or set(value) != set(allowed)
            or any(type(key) is not str for key in value)
            or any(type(value[key]) is not str or value[key] not in choices
                   for key, choices in allowed.items())):
        return None
    if allowed is FAILED_GATHER_FAILURE_FIELDS:
        kind, code = value["exception_kind"], value["native_code"]
        if ((kind == "native_unavailable" and code == "not_applicable")
                or (kind in {"identity_mismatch", "validation_error"} and code != "not_applicable")
                or (kind == "unknown" and code != "unknown")):
            return None
    return {key: value[key] for key in allowed}


def validated_gather_for_retirement(retirement, gather):
    """Require matching cause and as-of shape at each private projection edge."""
    cause = validated_pairing_retirement(retirement)
    selected = validated_gather_failure(gather)
    if cause is None or selected is None or cause["phase"] not in GATHER_STAGE_ORDER:
        return None
    stages = GATHER_STAGE_ORDER[cause["phase"]]
    if (selected["stage"] not in {"not_started", "unknown", *stages}
            or selected["last_completed"] not in {"none", "unknown", *(set(stages) - {"complete"})}):
        return None
    triplet = cause["event"], cause["reason"]
    if ((triplet == ("tick", "phase_timeout") and selected["as_of"] == "phase_deadline")
            or (triplet == ("failed", "invalid_document") and selected["as_of"] == "failed_result")):
        return selected
    return None


def _age_bucket(start, end):
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not isfinite(start) or not isfinite(end) or end < start):
        return "unknown"
    elapsed = end - start
    return ("lt1s" if elapsed < 1 else "1to5s" if elapsed < 5 else
            "5to20s" if elapsed < 20 else "20to25s" if elapsed < 25 else "gte25s")


def _gather_failure_at(cutoff, worker_history, stage_history, as_of, exception_kind=None,
                       native_code=None, *, phase="gather_answer"):
    """Select fixed milestones at the supervisor-custodied time only."""
    if phase not in GATHER_STAGE_ORDER or (phase == "gather_offer" and stage_history is None):
        return None
    if as_of == "failed_result":
        kind, code = exception_kind, native_code
        if validated_gather_failure({**{key: "unknown" for key in GATHER_FAILURE_FIELDS},
                                     "as_of": "failed_result", "exception_kind": kind,
                                     "native_code": code}) is None:
            kind = code = "unknown"
    else:
        kind = code = None
    def shaped(value):
        if as_of == "failed_result":
            return {**value, "exception_kind": kind, "native_code": code}
        return value
    unknown = shaped({"as_of": as_of, "worker": "unknown", "stage": "unknown",
               "stage_state": "unknown", "last_completed": "unknown",
               "queue_age": "unknown", "stage_age": "unknown"})
    if type(cutoff) not in (int, float) or not isfinite(cutoff):
        return unknown
    try:
        worker = "unknown"
        queued = started = None
        previous = float("-inf")
        saw_late = False
        for state, when in worker_history:
            if type(when) not in (int, float) or not isfinite(when) or when < previous:
                return None if phase == "gather_offer" else unknown
            previous = when
            if when > cutoff:
                saw_late = True
                continue
            if saw_late or state not in {"queued", "started", "completed"}:
                return None if phase == "gather_offer" else unknown
            worker = state
            if state == "queued":
                queued = when
            elif state == "started":
                started = when
        queue_age = _age_bucket(queued, started if started is not None else cutoff)
        def unknown_stage():
            return None if phase == "gather_offer" else shaped({"as_of": as_of, "worker": worker, "stage": "unknown",
                    "stage_state": "unknown", "last_completed": "unknown",
                    "queue_age": queue_age, "stage_age": "unknown"})
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
        order = GATHER_STAGE_ORDER[phase]
        for label, state, when in (() if stage_history is None else stage_history):
            if type(when) not in (int, float) or not isfinite(when) or when < previous:
                return unknown_stage()
            previous = when
            if when > cutoff:
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
                entered, entered_label, stage_end = when, label, cutoff
            elif label == "complete":
                entered = entered_label = stage_end = None
            else:
                if completed_stage == index:
                    return unknown_stage()
                stage_end = when if entered_label == label else None
                last_completed = label
                completed_stage = index
        result = shaped({"as_of": as_of, "worker": worker, "stage": stage,
                  "stage_state": stage_state, "last_completed": last_completed,
                  "queue_age": queue_age,
                  "stage_age": _age_bucket(entered, stage_end)})
        selected = validated_gather_failure(result)
        return selected if selected is not None else (None if phase == "gather_offer" else unknown)
    except (TypeError, ValueError):
        return None if phase == "gather_offer" else unknown


def gather_failure_at_deadline(deadline, worker_history, stage_history, *, phase="gather_answer"):
    """Existing timeout observation, unchanged at the original phase deadline."""
    return _gather_failure_at(deadline, worker_history, stage_history, "phase_deadline", phase=phase)


def gather_failure_at_result(now, worker_history, stage_history, exception_kind, native_code,
                             *, phase="gather_answer"):
    """Observe a classified gather failure at its accepted Failed.now."""
    return _gather_failure_at(now, worker_history, stage_history, "failed_result",
                              exception_kind, native_code, phase=phase)


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
