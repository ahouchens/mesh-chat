"""Fixed-label projection for one trusted transferred native carrier."""

from .model import Adopted, ContextChanged, Failed, Observed, Phase, Result, Tick


_EVENTS = {Tick: "tick", ContextChanged: "context_changed", Result: "result",
           Failed: "failed", Adopted: "adopted", Observed: "observed"}
_REASONS = frozenset({
    "carrier_lost", "phase_timeout", "ineligible", "context_changed",
    "network_unavailable", "transient", "rate_limited", "configuration",
    "invalid_document", "revoked", "unsupported", "internal",
    "wrong_resource", "invalid_adoption", "invalid_handoff", "invalid_pending",
    "unverified_resource", "missing_handoff", "stale_completion", "observed",
})
_PHASES = frozenset(phase.value for phase in Phase) | {"none"}
_HEALTH = frozenset({"absent", "open", "suspect", "closing"})


def carrier_fact(state, event, result, *, precursor):
    """Select labels at the transition edge; never retain event payloads."""
    phase = state.negotiation.phase.value if state.negotiation else "none"
    reason = result.reason
    fact = {"event": _EVENTS.get(type(event), "unknown"),
            "phase": phase if phase in _PHASES else "unknown",
            "reason": reason if reason in _REASONS else "unknown"}
    if not precursor:
        health = state.carrier.health.value if state.carrier else "absent"
        fact["prior_health"] = health if health in _HEALTH else "unknown"
    return fact


def carrier_projection(trace):
    if trace is None:
        return {"availability": "unavailable", "owner_loss": None,
                "suspect_precursor": None, "native_close": "unavailable", "order": "unknown"}
    native = ("callback_after_local_request" if trace.callback_close and trace.callback_after_request else
              "callback_without_local_request" if trace.callback_close else
              "local_request" if trace.local_close else "not_observed")
    order = trace.order if trace.owner_loss is not None and native != "not_observed" else (
        "not_observed" if trace.owner_loss is None and native == "not_observed" else "unknown")
    return {"availability": "selected",
            "owner_loss": dict(trace.owner_loss) if trace.owner_loss is not None else None,
            "suspect_precursor": dict(trace.suspect) if trace.suspect is not None else None,
            "native_close": native, "order": order}
