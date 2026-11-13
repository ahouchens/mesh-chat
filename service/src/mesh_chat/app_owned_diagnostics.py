"""Read-only, bounded EOF observation for one app-owned public pairing intent."""

from .connection.diagnostics import validated_pairing_retirement
from .connection.model import Resource
from .connection.reconcile import connection_key


MAX_INTENTS = 32
LOCK_WAIT_SECONDS = 0.05
PAIRING_STATES = frozenset({
    "reserved", "offer_ready", "awaiting_approval", "retiring", "retired", "transferred",
})


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
        context = next(iter(contexts.values()))
        if type(context) is not dict:
            return unavailable(total)
        store = service.store
        if not _acquire(store._lock):
            return unavailable(total)
        try:
            rows = store.items("api_pairing_intent", limit=MAX_INTENTS + 1)
        finally:
            store._lock.release()
        if type(rows) is not list or len(rows) != 1:
            return unavailable(total)
        _, row = rows[0]
        if not _matches_public_intent(service, context, row):
            return unavailable(total)
        state = context["state"]
        retirement = None
        if state in {"retiring", "retired"}:
            owner = service._connection_runtime.owner
            if not _acquire(owner._lock):
                return unavailable(total)
            try:
                key = connection_key({"scope_kind": "pairing", "id": context["id"],
                                      "local_device_id": context["identity_hash"]})
                retirement = validated_pairing_retirement(owner.pairing_retirement_diagnostic(
                    key=key, runtime_epoch=context["runtime_epoch"], source=context["source"]))
            finally:
                owner._lock.release()
            if retirement is None or "unknown" in retirement.values():
                return unavailable(total)
        return {"status": "observed", "total_intents": total, "intents": [{
            "role": context["role"], "state": state, "retirement": retirement}]}
    finally:
        service._dispatch_lock.release()


def _matches_public_intent(service, context, row):
    if type(row) is not dict or context.get("role") not in {"offer", "answer"}:
        return False
    state = context.get("state")
    source = context.get("source")
    if (state not in PAIRING_STATES or not isinstance(source, Resource)
            or source.adapter_epoch != "native"):
        return False
    runtime = getattr(service, "_connection_runtime", None)
    owner = getattr(runtime, "owner", None)
    epoch = getattr(service, "_runtime_incarnation", None)
    identity = getattr(service, "_identity", None)
    identity_ref = context.get("identity")
    if (not isinstance(epoch, str) or not epoch or identity is None
            or not callable(identity_ref) or identity_ref() is not identity
            or getattr(owner, "runtime_epoch", None) != epoch):
        return False
    if not all(type(row.get(name)) is str and row[name] for name in
               ("caller", "profile", "pairing", "native_id", "runtime_epoch", "identity_hash")):
        return False
    if (row["profile"] != "local" or row["native_id"] != context.get("id")
            or row["runtime_epoch"] != context.get("runtime_epoch") or epoch != context["runtime_epoch"]
            or row["identity_hash"] != context.get("identity_hash")
            or type(row.get("cancel_requested")) is not bool):
        return False
    expected_terminal = state if state in {"retired", "transferred"} else None
    return row.get("terminal_state") == expected_terminal
