"""Public caller intents over the existing protected native pairing actor.

Core records caller intent before admission; the actor records its own exact
child admission before native/mailbox work. Neither layer reconstructs an old
runtime's uncertain resources or turns a cancellation into carrier ownership.
"""
from hashlib import sha256
import json
import time
from uuid import UUID, uuid5
from weakref import ref

from ..call_manager import CallOutcomeRequiresResync
from ..errors import ContactNotApproved, NativeUnavailable, ValidationError
from ..native_webrtc_host import require_host
from ..signal_mailbox import parse_pairing
from ..vault import RecordConflict
from .errors import ApiFailure
from .pairing import PairingIntentObservation
from .service_messages import storage_errors


PAIRING_INTENT_LIMITS = {
    "pairing_intents_per_runtime": 32,
    "pairing_active_intents": 1,
    "pairing_intent_seconds": 300,
    "pairing_code_utf8_bytes": 2048,
    "pairing_key_idempotency_seconds": 604800,
    "pairing_keys_per_caller_profile": 4096,
    "pairing_keys_per_vault": 65536,
}
_TERMINAL = {"retired", "transferred"}


def _checkpoint_terminal(service, identifier, epoch, identity_hash, native_id, state):
    """Trusted actor callback, invoked after exact retirement/handoff proof."""
    if state not in _TERMINAL:
        raise ValueError("Pairing terminal acknowledgment is invalid")
    store = service.store
    with storage_errors(), service._dispatch_lock, store.read_snapshot():
        row = store.get("api_pairing_intent", identifier)
        if row is None or (row["runtime_epoch"], row["identity_hash"], row["native_id"]) != (epoch, identity_hash, native_id):
            raise ApiFailure("resync_required")
        if row["terminal_state"] is not None:
            return
        owner = store.get("api_pairing_owner", "active")
        expected = {("api_pairing_intent", identifier): row}
        deletions = []
        if owner == {"intent": identifier}:
            expected[("api_pairing_owner", "active")] = owner
            deletions.append(("api_pairing_owner", "active"))
        try:
            store.conditional_put_and_delete(expected,
                [("api_pairing_intent", identifier, {**row, "terminal_state": state})], deletions)
        except RecordConflict as error:
            raise ApiFailure("conflict") from error
    try:
        service._changed()
    except Exception:
        pass  # The durable acknowledgment remains available to query/reopen.


class ServicePairingIntents:
    def __init__(self, service, authorize):
        self.service, self.authorize = service, authorize
        self.available = False
        self.host = None
        if (getattr(service, "native_pairing_public_intents", False) is not True
                or getattr(service, "_connection_policy", None) != "shared-native"
                or getattr(service, "_connection_runtime", None) is None
                or not all(callable(getattr(service, name, None)) for name in
                           ("native_pairing_begin", "native_pairing_status", "native_pairing_cancel"))
                or not all(callable(getattr(service.store, name, None)) for name in
                           ("read_snapshot", "conditional_put_and_delete", "operation_result"))):
            return
        try:
            self.host = require_host(service._native_webrtc_host())
        except NativeUnavailable:
            return
        self.available = True

    def _require(self, scope):
        if not self.available:
            raise ApiFailure("unsupported_operation")
        if scope.profile != "local":
            raise ApiFailure("forbidden")
        if self.service._identity is None:
            raise ApiFailure("locked")
        from .session import Grant
        grant = self.authorize()
        if (not isinstance(grant, Grant) or grant.caller != scope.caller
                or "approve" not in grant.permissions or scope.profile not in grant.profiles):
            raise ApiFailure("forbidden")
        if self.service._shutdown.is_set() or self.service._native_webrtc_host() is not self.host:
            raise ApiFailure("unavailable")
        return self.service._require_profile()

    def _index(self, scope, pairing):
        return self.service.store.opaque_id("core-pairing-intent:v1", scope.caller, scope.profile, pairing)

    def _row(self, scope, pairing):
        profile = self._require(scope)
        identifier = self._index(scope, pairing)
        row = self.service.store.get("api_pairing_intent", identifier)
        if row is None or (row["caller"], row["profile"], row["pairing"], row["identity_hash"]) != (
                scope.caller, scope.profile, pairing, profile["identity_hash"]):
            raise ApiFailure("forbidden")
        if row["terminal_state"] is None and row["runtime_epoch"] != self.service._runtime_incarnation:
            raise ApiFailure("resync_required")
        if row["terminal_state"] is None and row["mailbox_url"] != self.service._call_settings.signal_mailbox_url:
            raise ApiFailure("resync_required")
        return identifier, row

    def _quota(self, scope):
        store = self.service.store
        identifier = store.opaque_id("core-pairing-quota:v1", json.dumps([scope.caller, scope.profile], separators=(",", ":")))
        expected, values = {}, []
        for key, maximum in ((identifier, PAIRING_INTENT_LIMITS["pairing_keys_per_caller_profile"]),
                             ("global", PAIRING_INTENT_LIMITS["pairing_keys_per_vault"])):
            row = store.get("api_pairing_quota", key)
            count = (row or {"count": 0}).get("count")
            if type(count) is not int or count < 0:
                raise ApiFailure("unavailable")
            if count >= maximum:
                raise ApiFailure("resource_exhausted")
            expected[("api_pairing_quota", key)] = row
            values.append(("api_pairing_quota", key, {"count": count + 1}))
        return expected, values

    def _commit(self, scope, operation_id, digest, outcome, expected, records):
        store = self.service.store
        quota_expected, quota_records = self._quota(scope)
        receipt_id = store.opaque_id("workspace-operation", operation_id)
        try:
            store.conditional_put_and_delete({**expected, **quota_expected, ("workspace_operation", receipt_id): None},
                [*records, *quota_records, ("workspace_operation", receipt_id, {
                    "id": operation_id, "input_digest": digest, "outcome": outcome, "created_at": time.time()})], schema_floor=2)
        except RecordConflict as error:
            raise ApiFailure("conflict") from error

    def _callbacks(self, scope, identifier, row):
        service_ref, identity_ref = ref(self.service), ref(self.service._identity)
        epoch, identity_hash, native_id = row["runtime_epoch"], row["identity_hash"], row["native_id"]
        resolve, host = self.authorize, self.host
        def authorized():
            try:
                from .session import Grant
                service = service_ref()
                if (service is None or service._shutdown.is_set() or service._identity is not identity_ref()
                        or service._runtime_incarnation != epoch or service._native_webrtc_host() is not host):
                    return False
                grant = resolve()
                return (isinstance(grant, Grant) and grant.caller == scope.caller
                        and scope.profile in grant.profiles and "approve" in grant.permissions)
            except Exception:
                return False
        def cancelled():
            try:
                service = service_ref()
                current = service.store.get("api_pairing_intent", identifier) if service is not None else None
                return current is None or current["cancel_requested"] is True
            except Exception:
                return True
        def terminal(state):
            service = service_ref()
            if service is None:
                raise ApiFailure("unavailable")
            _checkpoint_terminal(service, identifier, epoch, identity_hash, native_id, state)
        return authorized, cancelled, terminal

    def _admit(self, scope, identifier, row, params):
        authorized, cancelled, terminal = self._callbacks(scope, identifier, row)
        try:
            return self.service.native_pairing_begin(row["native_id"], role=params["role"], authorized=authorized,
                pairing_code=params.get("pairing_code"), allow_direct_ip_disclosure=params.get("allow_direct_ip_disclosure", False),
                cancel_requested=cancelled, on_terminal=terminal)
        except CallOutcomeRequiresResync as error:
            raise ApiFailure("resync_required") from error
        except NativeUnavailable as error:
            raise ApiFailure("unavailable") from error
        except ValidationError as error:
            raise ApiFailure("resync_required") from error

    def _owner_available(self):
        store = self.service.store
        owner = store.get("api_pairing_owner", "active")
        if owner is None:
            return
        row = store.get("api_pairing_intent", owner["intent"])
        if row is None or row["runtime_epoch"] != self.service._runtime_incarnation:
            raise ApiFailure("resync_required")
        # Read only the actor's protected terminal acknowledgment; never raw
        # SDP/native leases and never treat a missing context as retirement.
        context = getattr(self.service, "_native_pairing_contexts", {}).get(row["native_id"])
        state = context.get("state") if context is not None else None
        if state not in _TERMINAL:
            raise ApiFailure("resource_exhausted")
        _checkpoint_terminal(self.service, owner["intent"], row["runtime_epoch"], row["identity_hash"], row["native_id"], state)

    def begin(self, scope, pairing, params, operation_id):
        service, store = self.service, self.service.store
        with storage_errors(), service._dispatch_lock, store.read_snapshot():
            profile = self._require(scope)
            mailbox = service._call_settings.signal_mailbox_url
            if mailbox is None:
                raise ApiFailure("unavailable")
            payload = {"role": params["role"], "pairing_digest": sha256(params.get("pairing_code", "").encode()).hexdigest(),
                       "allow_direct_ip_disclosure": params.get("allow_direct_ip_disclosure", False)}
            _, digest, replay = service._workspace_operation("core.peer.pairing_begin", operation_id, payload)
            identifier = self._index(scope, pairing)
            if replay is None:
                if params["role"] == "answer":
                    try:
                        parse_pairing(params["pairing_code"], mailbox)
                    except ValidationError as error:
                        raise ApiFailure("invalid_request") from error
                self._owner_available()
                contexts = getattr(service, "_native_pairing_contexts", {})
                if (len(contexts) >= PAIRING_INTENT_LIMITS["pairing_intents_per_runtime"]
                        or any(context.get("state") not in _TERMINAL for context in contexts.values())):
                    raise ApiFailure("resource_exhausted")
                now = time.time()
                row = {"caller": scope.caller, "profile": scope.profile, "pairing": pairing,
                       "operation_id": operation_id, "native_id": str(uuid5(UUID(operation_id), "core-native-pairing:v1")),
                       "runtime_epoch": service._runtime_incarnation, "identity_hash": profile["identity_hash"],
                       "mailbox_url": mailbox,
                       "expires_at": now + PAIRING_INTENT_LIMITS["pairing_intent_seconds"],
                       "cancel_requested": False, "terminal_state": None}
                self._commit(scope, operation_id, digest, {"pairing": pairing},
                    {("api_pairing_intent", identifier): None, ("api_pairing_owner", "active"): None},
                    [("api_pairing_intent", identifier, row), ("api_pairing_owner", "active", {"intent": identifier})])
            else:
                if replay != {"pairing": pairing}:
                    raise ApiFailure("resync_required")
                identifier, row = self._row(scope, pairing)
            if row["terminal_state"] is None and not row["cancel_requested"]:
                self._admit(scope, identifier, row, params)
            result = self._observe(row)
        service._changed()
        return result

    def _observe(self, row):
        state, code, expires = row["terminal_state"], None, row["expires_at"]
        if state is None:
            if row["runtime_epoch"] != self.service._runtime_incarnation:
                raise ApiFailure("resync_required")
            receipt = self.service.store.get("workspace_operation", self.service.store.opaque_id("workspace-operation", row["native_id"]))
            if receipt is None:
                state = "retired" if row["cancel_requested"] else "reserved"
            else:
                context = getattr(self.service, "_native_pairing_contexts", {}).get(row["native_id"])
                if context is not None and context.get("state") in _TERMINAL:
                    return PairingIntentObservation(row["pairing"], context["state"], expires, None)
                try:
                    observation = self.service.native_pairing_status(row["native_id"])
                except CallOutcomeRequiresResync as error:
                    raise ApiFailure("resync_required") from error
                except NativeUnavailable as error:
                    raise ApiFailure("unavailable") from error
                state, code = observation["state"], observation.get("pairing_code")
                expires = min(expires, observation["expires_at"])
        return PairingIntentObservation(row["pairing"], state, expires, code)

    def query(self, scope, pairing):
        with storage_errors(), self.service._dispatch_lock, self.service.store.read_snapshot():
            _, row = self._row(scope, pairing)
            return self._observe(row)

    def cancel(self, scope, pairing, operation_id):
        service, store = self.service, self.service.store
        with storage_errors(), service._dispatch_lock, store.read_snapshot():
            identifier, row = self._row(scope, pairing)
            _, digest, replay = service._workspace_operation("core.peer.pairing_cancel", operation_id, {"pairing": pairing})
            if replay is None:
                self._commit(scope, operation_id, digest, {"pairing": pairing}, {("api_pairing_intent", identifier): row},
                             [("api_pairing_intent", identifier, {**row, "cancel_requested": True})])
                row = store.get("api_pairing_intent", identifier)
            if row["terminal_state"] is None:
                receipt = store.get("workspace_operation", store.opaque_id("workspace-operation", row["native_id"]))
                if receipt is None:
                    _checkpoint_terminal(service, identifier, row["runtime_epoch"], row["identity_hash"], row["native_id"], "retired")
                else:
                    try:
                        cancelled = service.native_pairing_cancel(row["native_id"])
                        if cancelled.get("state") in _TERMINAL:
                            _checkpoint_terminal(service, identifier, row["runtime_epoch"], row["identity_hash"], row["native_id"], cancelled["state"])
                    except CallOutcomeRequiresResync as error:
                        raise ApiFailure("resync_required") from error
                    except NativeUnavailable as error:
                        raise ApiFailure("unavailable") from error
            result = self._observe(store.get("api_pairing_intent", identifier))
        service._changed()
        return result
