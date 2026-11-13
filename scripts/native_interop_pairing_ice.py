"""Failure-only projection of existing pairing status and native stats polls."""

import copy

from native_interop_ice_packets import correlation

GATHERING = frozenset({"new", "gathering", "complete", "unknown"})
RETIREMENT = {"phase": "checking", "event": "tick", "reason": "phase_timeout"}


class PairingIceObservation:
    def __init__(self, operation, phase):
        self.operation, self.phase = operation, phase
        self.resource = None
        self.first = self.last = None
        self.stats_unavailable = False
        self.failure = None

    def observe_stats(self, inventory, resource, stats):
        try:
            identity = tuple(resource[name] for name in ("logical_session", "physical_resource")) + tuple(
                inventory[name] for name in ("service_incarnation", "profile_incarnation"))
            if any(type(value) is not str or not value for value in identity): raise ValueError()
            if self.resource is not None and self.resource != identity: raise ValueError()
            self.resource = identity
            value = stats.get("ice_gathering_state")
            value = value if type(value) is str and value in GATHERING else "unknown"
            if self.first is None: self.first = value
            self.last = value
        except Exception:
            self.stats_unavailable = True
            self.first = self.last = None

    def bind_failure(self, error, status, retirement):
        if retirement != RETIREMENT: return
        try:
            from mesh_chat.connection.pairing_ice_diagnostics import validated_pairing_ice_diagnostic
            selected = validated_pairing_ice_diagnostic(status.get("ice_diagnostic"))
            self.failure = error, copy.deepcopy(selected)
        except Exception:
            self.failure = None

    def matches(self, error, operation, phase):
        return (self.failure is not None and self.failure[0] is error
                and self.operation == operation and self.phase == phase)

    def public(self):
        value = self.failure[1]
        if type(value) is not dict: return {}
        return {"pairing_ice": {"scope": "retained_sdp_candidates", **{
            k: copy.deepcopy(value[k]) for k in ("availability", "local", "remote")},
            "gathering": {"first": self.first, "last": self.last}
                if not self.stats_unavailable and self.resource is not None else None}}

    def private_correlation(self):
        value = self.failure[1]
        if type(value) is dict and correlation(value.get("correlation")) is not None:
            return dict(value["correlation"])
        return None
