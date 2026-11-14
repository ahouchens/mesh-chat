"""Bounded EOF observation of a proven app-owned public pairing intent."""

from dataclasses import dataclass

from .connection.diagnostics import (
    validated_checking_observation, validated_gather_for_retirement, validated_pairing_retirement,
)
from .connection.model import Resource
from .connection.reconcile import connection_key


APP_CALLER = "mesh-core-independent-application"
MAX_INTENTS = 32
LOCK_WAIT_SECONDS = 0.05
PAIRING_STATES = frozenset({
    "reserved", "offer_ready", "awaiting_approval", "retiring", "retired", "transferred",
})
_AMBIGUOUS = object()


@dataclass(frozen=True, eq=False, repr=False)
class PairingProvenance:
    service: object
    store: object
    context: dict
    identity: object
    record_id: str
    caller: str
    profile: str
    pairing: str
    native_id: str
    runtime_epoch: str
    identity_hash: str
    role: str


def capture_public_pairing(service, record_id, row, context):
    """Retain admission proof under the existing dispatch/store snapshot.

    The caller has already committed or loaded the exact durable row under
    the store snapshot. Capture verifies its index without rereading it;
    observation at EOF performs no vault or database operations.
    """
    try:
        _capture_public_pairing(service, record_id, row, context)
    except Exception:
        pass  # Diagnostic failure must never affect a public pairing admission.


def _capture_public_pairing(service, record_id, row, context):
    if (type(row) is not dict or type(context) is not dict
            or type(record_id) is not str or not record_id
            or row.get("caller") != APP_CALLER or row.get("profile") != "local"
            or context.get("role") not in {"offer", "answer"}):
        return
    for name in ("pairing", "native_id", "runtime_epoch", "identity_hash"):
        if type(row.get(name)) is not str or not row[name]:
            return
    store = service.store
    if (record_id != store.opaque_id("core-pairing-intent:v1", APP_CALLER, "local", row["pairing"])
            or service._native_pairing_contexts.get(row["native_id"]) is not context
            or context.get("id") != row["native_id"]
            or context.get("runtime_epoch") != row["runtime_epoch"]
            or context.get("identity_hash") != row["identity_hash"]
            or service._runtime_incarnation != row["runtime_epoch"]):
        return
    identity = service._identity
    identity_ref = context.get("identity")
    if identity is None or not callable(identity_ref) or identity_ref() is not identity:
        return
    proof = PairingProvenance(service, store, context, identity, record_id,
        APP_CALLER, "local", row["pairing"], row["native_id"], row["runtime_epoch"],
        row["identity_hash"], context["role"])
    previous = getattr(service, "_app_owned_pairing_diagnostic_provenance", None)
    if previous is None:
        service._app_owned_pairing_diagnostic_provenance = proof
    elif (type(previous) is not PairingProvenance
            or previous.service is not service or previous.store is not store
            or previous.context is not context or previous.identity is not identity
            or (previous.record_id, previous.caller, previous.profile, previous.pairing,
                previous.native_id, previous.runtime_epoch, previous.identity_hash, previous.role)
            != (proof.record_id, proof.caller, proof.profile, proof.pairing,
                proof.native_id, proof.runtime_epoch, proof.identity_hash, proof.role)):
        service._app_owned_pairing_diagnostic_provenance = _AMBIGUOUS


def unavailable(total_intents=0):
    return {"status": "unavailable", "total_intents": total_intents, "intents": []}


def _acquire(lock):
    return lock.acquire(timeout=LOCK_WAIT_SECONDS)


def observe_pairing(service):
    """Project fixed labels only; unknown identity, custody or lock state fails closed."""
    try:
        return _observe_pairing(service)
    except Exception:
        return unavailable()


def _observe_pairing(service):
    if service is None or not _acquire(service._dispatch_lock):
        return unavailable()
    try:
        contexts = getattr(service, "_native_pairing_contexts", None)
        if type(contexts) is not dict or len(contexts) > MAX_INTENTS:
            return unavailable()
        total = len(contexts)
        if total != 1:
            return unavailable(total)
        proof = getattr(service, "_app_owned_pairing_diagnostic_provenance", None)
        if type(proof) is not PairingProvenance or not _matches_provenance(service, contexts, proof):
            return unavailable(total)
        context = proof.context
        state = context["state"]
        retirement = None
        gather = None
        checking = None
        if state in {"retiring", "retired"}:
            owner = service._connection_runtime.owner
            if not _acquire(owner._lock):
                return unavailable(total)
            try:
                if owner.runtime_epoch != proof.runtime_epoch:
                    return unavailable(total)
                key = connection_key({"scope_kind": "pairing", "id": proof.native_id,
                                      "local_device_id": proof.identity_hash})
                retirement = validated_pairing_retirement(owner.pairing_retirement_diagnostic(
                    key=key, runtime_epoch=proof.runtime_epoch, source=context["source"]))
                gather_phase = "gather_offer" if proof.role == "offer" else "gather_answer"
                if retirement is not None and retirement["phase"] == gather_phase:
                    try:
                        provider = getattr(service, "_native_pairing_gather_failure_snapshot", None)
                        gather = validated_gather_for_retirement(
                            retirement, provider(context, retirement)) if callable(provider) else None
                    except Exception:
                        pass  # Optional evidence cannot replace the proven retirement row.
                if retirement == {"phase": "checking", "event": "tick", "reason": "phase_timeout"}:
                    try:
                        provider = getattr(service, "_native_pairing_checking_observation_snapshot", None)
                        checking = validated_checking_observation(
                            retirement, provider(context, retirement)) if callable(provider) else None
                    except Exception:
                        pass  # Optional evidence cannot replace the proven retirement row.
            finally:
                owner._lock.release()
            if retirement is None or "unknown" in retirement.values():
                return unavailable(total)
        intent = {"role": proof.role, "state": state, "retirement": retirement}
        if gather is not None:
            intent["gather_failure"] = gather
        if checking is not None:
            intent["checking_observation"] = checking
        return {"status": "observed", "total_intents": total, "intents": [intent]}
    finally:
        service._dispatch_lock.release()


def _matches_provenance(service, contexts, proof):
    context = proof.context
    source = context.get("source")
    identity_ref = context.get("identity")
    return (proof.service is service and proof.store is service.store
            and proof.caller == APP_CALLER and proof.profile == "local"
            and type(proof.record_id) is str and bool(proof.record_id)
            and type(proof.pairing) is str and bool(proof.pairing)
            and type(context) is dict and contexts.get(proof.native_id) is context
            and context.get("id") == proof.native_id
            and context.get("runtime_epoch") == proof.runtime_epoch
            and context.get("identity_hash") == proof.identity_hash
            and context.get("role") == proof.role and proof.role in {"offer", "answer"}
            and context.get("state") in PAIRING_STATES
            and isinstance(source, Resource) and source.adapter_epoch == "native"
            and service._runtime_incarnation == proof.runtime_epoch
            and service._identity is proof.identity
            and callable(identity_ref) and identity_ref() is proof.identity)
