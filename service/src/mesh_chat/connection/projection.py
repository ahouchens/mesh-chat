"""Redacted observations; connectivity is never an application receipt."""

from .model import Bridge, ConnectionState, Desired, Execution, Health


def snapshot(state: ConnectionState, now: float) -> dict:
    carrier = state.carrier
    ready = bool(carrier and carrier.health is Health.OPEN and carrier.bridge is Bridge.READY
                 and state.authority.authorized and state.desired is Desired.ENABLED
                 and state.execution is Execution.AVAILABLE)
    return {
        "v": 1,
        "runtime_epoch": state.runtime_epoch,
        "sequence": state.sequence,
        "profile_id": state.key.profile_id,
        "desired": state.desired.value,
        "execution": state.execution.value,
        "negotiation": state.negotiation.phase.value if state.negotiation else "idle",
        "carrier": carrier.health.value if carrier else "absent",
        "bridge": carrier.bridge.value if carrier else "detached",
        "messaging_ready": ready,
        "reason": state.reason,
        "retry_in": max(0, state.retry_at - now),
        "evidence_age": max(0, now - carrier.observed_at) if carrier else None,
    }
