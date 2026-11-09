"""Protected call acceptance and recovery, independent of renderer memory.

The catalog records ownership and signaling acceptance, never SDP or media
resources. Only an exact trusted host retirement acknowledgment permits replacing
an abandoned operation. A terminal signaling state or a new service epoch does
not establish that acknowledgment.
"""
from dataclasses import dataclass
import json
import time

from ..call_manager import ACTIVE_STATES, CallOutcomeRequiresResync
from ..errors import ContactNotApproved, ValidationError
from ..vault import RecordConflict
from ..webrtc_signaling import create_call_hangup
from .errors import ApiFailure
from .service_messages import storage_errors
from .requests import CALL_RECOVERY_OPERATIONS


CALL_OPERATION_LIMITS = {
    "call_operations_per_caller_profile": 256,
    "call_operations_per_vault": 4096,
    "call_operation_retention_seconds": 604800,
    "call_operation_keys_per_caller_profile": 4096,
    "call_operation_keys_per_vault": 65536,
}
_ACQUISITIONS = {"start", "answer", "restart", "answer_restart"}


@dataclass(frozen=True)
class CallRetirementTicket:
    operation_id: str
    call_id: str
    runtime_epoch: str
    caller: str
    profile: str
    owner_incarnation: str


@dataclass(frozen=True)
class CallRetirementAcknowledgment:
    ticket: CallRetirementTicket
    retired: bool


class CallOperationJournal:
    def __init__(self, service, retirement=None):
        self.service = service
        self.store = service.store
        # Trusted host injection only. Absence leaves cleanup pending.
        self.retirement = retirement

    def _identifier(self, operation_id):
        return self.store.opaque_id("core-call-operation:v1", operation_id)

    @staticmethod
    def _owned(row, scope):
        return (row.get("caller"), row.get("profile")) == (scope.caller, scope.profile)

    def rows(self, scope):
        with storage_errors(), self.service._dispatch_lock, self.store.read_snapshot():
            self.service._call_identity()
            return tuple(row for row in self.store.list("api_call_operation") if self._owned(row, scope))

    def observe(self, scope, operation_id):
        with storage_errors(), self.service._dispatch_lock, self.store.read_snapshot():
            self.service._call_identity()
            row = self.store.get("api_call_operation", self._identifier(operation_id))
            if row is None or not self._owned(row, scope):
                raise ApiFailure("forbidden")
            record = (self.store.get("call", row["call_id"]) if self.service.calls.persist
                      else self.service.calls._get(row["call_id"]))
            current = row["runtime_epoch"] == self.service._core_call_epoch
            # Read-only: do not run CallManager.get(), which expires ring state.
            state = record.get("state") if record is not None else None
            if row.get("retired_at") is not None:
                disposition = "retired"
            elif row.get("abandon_requested_at") is not None:
                disposition = "cleanup_pending"
            elif not current:
                disposition = "unknown_runtime"
            else:
                disposition = "live" if state in ACTIVE_STATES else "terminal_unretired"
            return {"operation_id": operation_id, "call_id": row["call_id"],
                    "runtime_epoch": row["runtime_epoch"], "action": row["action"],
                    "accepted_at": row["accepted_at"], "expires_at": row["expires_at"],
                    "expired": time.time() >= row["expires_at"], "current_runtime": current,
                    "state": state, "disposition": disposition,
                    "replacement_safe": disposition == "retired"}

    def _quota(self, scope):
        identifier = self.store.opaque_id("core-call-quota:v1", json.dumps([scope.caller, scope.profile], separators=(",", ":")))
        expected, values = {}, []
        for key, maximum in ((identifier, CALL_OPERATION_LIMITS["call_operation_keys_per_caller_profile"]),
                             ("global", CALL_OPERATION_LIMITS["call_operation_keys_per_vault"])):
            row = self.store.get("api_call_quota", key)
            count = (row or {"count": 0}).get("count")
            if type(count) is not int or count < 0:
                raise ApiFailure("unavailable")
            if count >= maximum:
                raise ApiFailure("resource_exhausted")
            expected[("api_call_quota", key)] = row
            values.append(("api_call_quota", key, {"count": count + 1}))
        return expected, values

    def _commit(self, operation_id, digest, outcome, records, deletions=(), *, collections=None, quota=None):
        receipt_id = self.store.opaque_id("workspace-operation", operation_id)
        values = [*records, ("workspace_operation", receipt_id, {
            "id": operation_id, "input_digest": digest, "outcome": outcome, "created_at": time.time()})]
        expected = {(kind, identifier): self.store.get(kind, identifier) for kind, identifier, _ in values}
        expected.update({(kind, identifier): self.store.get(kind, identifier) for kind, identifier in deletions})
        expected[("workspace_operation", receipt_id)] = None
        if quota is not None:
            expected.update(quota[0])
            values.extend(quota[1])
        try:
            self.store.conditional_put_and_delete(expected, values, deletions,
                                                  expected_collections=collections or {}, schema_floor=2)
        except RecordConflict as error:
            raise ApiFailure("conflict") from error

    def _signals(self, documents, operation_id):
        records, direct, workspaces, signal_rows = [], [], set(), []
        for index, (target, document) in enumerate(documents):
            values, message, workspace = self.service._prepare_keyed_call_signal(target, document, operation_id, index)
            records.extend(values)
            signal_rows.extend((kind, identifier) for kind, identifier, _ in values
                               if kind in {"message", "workspace_delivery"})
            if message is not None:
                direct.append(message)
            if workspace is not None:
                workspaces.add(workspace)
        return records, direct, workspaces, signal_rows

    def control(self, scope, action, params, operation_id):
        service = self.service
        with storage_errors(), service._dispatch_lock, self.store.read_snapshot():
            identity = service._call_identity()
            payload = {key: value for key, value in params.items() if key != "profile"}
            _, digest, replay = service._workspace_operation("core.call.control", operation_id, payload)
            if action == "start":
                contact_id = params["contact_id"]
            elif replay is not None:
                contact_id = replay["contact_id"]
            else:
                record = service.calls._get(params["call_id"])
                if record is None:
                    raise ApiFailure("invalid_request")
                contact_id = record["contact_id"]
            contact = service._require_call_peer(contact_id)
            if contact.get("trust") not in {"approved", "verified", "workspace"}:
                raise ApiFailure("forbidden")
            catalog = dict(self.store.items("api_call_operation"))
            call_id = replay["result"]["id"] if replay is not None else params.get("call_id")
            # Abandonment fences every later command for this exact call, including
            # old-key replay. It never causes a new call/SDP acquisition.
            if any(row["call_id"] == call_id and row.get("abandon_requested_at") is not None
                   for row in catalog.values()):
                raise ApiFailure("resync_required")
            if replay is not None:
                if replay.get("runtime_epoch") != service._core_call_epoch or service.calls.reload_committed(call_id) is None:
                    raise CallOutcomeRequiresResync("Call command belongs to an earlier resource view")
                return service.calls.get(call_id)
            if action in _ACQUISITIONS:
                if (sum(self._owned(row, scope) for row in catalog.values()) >= CALL_OPERATION_LIMITS["call_operations_per_caller_profile"]
                        or len(catalog) >= CALL_OPERATION_LIMITS["call_operations_per_vault"]):
                    raise ApiFailure("resource_exhausted")
                if any(row.get("retired_at") is None and (row.get("abandon_requested_at") is not None
                       or row["runtime_epoch"] != service._core_call_epoch or row["call_id"] != call_id
                       or row["owner_incarnation"] != self.retirement.owner_incarnation)
                       for row in catalog.values()):
                    raise ApiFailure("resync_required")
            quota = self._quota(scope)
            calls = dict(self.store.items("call"))
            prepared = service.calls.prepare_control(identity, contact, action, params, operation_id)
            records = [("call", row["id"], row) for row in prepared.records] if service.calls.persist else []
            deletions = [("call", identifier) for identifier in prepared.deletions] if service.calls.persist else []
            signal_records, direct, workspaces, signal_rows = self._signals(prepared.documents, operation_id)
            records.extend(signal_records)
            outcome = {"result": prepared.result, "contact_id": contact_id, "runtime_epoch": service._core_call_epoch}
            if action in _ACQUISITIONS:
                now = time.time()
                records.append(("api_call_operation", self._identifier(operation_id), {
                    "operation_id": operation_id, "caller": scope.caller, "profile": scope.profile,
                    "call_id": prepared.result["id"], "contact_id": contact_id, "action": action,
                    "runtime_epoch": service._core_call_epoch, "accepted_at": now,
                    "owner_incarnation": self.retirement.owner_incarnation,
                    "expires_at": now + CALL_OPERATION_LIMITS["call_operation_retention_seconds"],
                    "signal_rows": [list(item) for item in signal_rows], "cleanup_direct_ids": [],
                    "abandon_requested_at": None, "retired_at": None}))
            elif signal_rows:
                related = [(identifier, row) for identifier, row in catalog.items()
                           if row["call_id"] == prepared.result["id"] and row["runtime_epoch"] == service._core_call_epoch]
                if related:
                    identifier, row = max(related, key=lambda item: item[1]["accepted_at"])
                    records.append(("api_call_operation", identifier,
                                    {**row, "signal_rows": [*row["signal_rows"], *[list(item) for item in signal_rows]]}))
            self._commit(operation_id, digest, outcome, records, deletions,
                         collections={"api_call_operation": catalog, "call": calls}, quota=quota)
            service.calls.apply_prepared(prepared)
        for message in direct:
            service._queue_direct_retry(message)
            service._attempt(message)
        for workspace in workspaces:
            service._workspace_changed(workspace, resource_kind="call")
        service._changed()
        return prepared.result

    def abandon(self, scope, target_id, operation_id):
        service = self.service
        direct, cancelled = [], []
        with storage_errors(), service._dispatch_lock, self.store.read_snapshot():
            identity = service._call_identity()
            catalog = dict(self.store.items("api_call_operation"))
            row = catalog.get(self._identifier(target_id))
            if row is None or not self._owned(row, scope):
                raise ApiFailure("forbidden")
            _, digest, replay = service._workspace_operation("core.call.operation_abandon", operation_id, {"operation": target_id})
            if replay is None:
                quota = self._quota(scope)
                calls = dict(self.store.items("call"))
                now = time.time()
                records, deletions = [], []
                workspace_cancelled = []
                prepared = None
                if row.get("abandon_requested_at") is None:
                    record = service.calls._get(row["call_id"])
                    # This is a cancellation intent, valid even after peer
                    # revocation. It never authorizes another outbound invite.
                    if record is not None:
                        prepared = service.calls.prepare_control(identity, None, "end",
                            {"call_id": row["call_id"], "reason": "cancelled"}, operation_id)
                        if service.calls.persist:
                            records.extend(("call", item["id"], item) for item in prepared.records)
                    documents = ((row["contact_id"], create_call_hangup(identity,
                        call_id=row["call_id"], reason="cancelled", now=int(now))),)
                    # A revoked peer cannot receive a new transport handoff.
                    try:
                        peer = service._require_call_peer(row["contact_id"])
                        approved = peer.get("trust") in {"approved", "verified", "workspace"}
                    except (ContactNotApproved, ValidationError):
                        approved = False
                    if approved:
                        values, direct, _, _ = self._signals(documents, operation_id)
                        records.extend(values)
                    for identifier, related in catalog.items():
                        if related["call_id"] != row["call_id"]:
                            continue
                        records.append(("api_call_operation", identifier, {**related,
                            "abandon_requested_at": related.get("abandon_requested_at") or now, "cleanup_direct_ids": direct}))
                        for kind, signal in related["signal_rows"]:
                            original = self.store.get(kind, signal)
                            if original is not None:
                                # Protocol outbox rows are disposable after a
                                # durable cancellation intent. Removing them
                                # also fences startup retry and late callbacks;
                                # already handed-off native packets still need
                                # the exact retirement acknowledgment below.
                                deletions.append((kind, signal))
                                if kind == "message":
                                    cancelled.append(signal)
                                else:
                                    workspace_cancelled.append(signal)
                    if workspace_cancelled:
                        records.extend(service._due_records(remove=workspace_cancelled))
                self._commit(operation_id, digest, {"operation_id": target_id}, records, deletions,
                             collections={"api_call_operation": catalog, "call": calls}, quota=quota)
                if prepared is not None:
                    service.calls.apply_prepared(prepared)
            committed = self.store.get("api_call_operation", self._identifier(target_id))
            service.calls.reconcile_abandonment(committed["call_id"], committed["abandon_requested_at"])
            direct = committed["cleanup_direct_ids"]
        for message in cancelled:
            service._drop_direct_retry(message)
        for message in direct:
            service._queue_direct_retry(message)
        self._reconcile_retirement(scope, target_id)
        service._changed()
        return self.observe(scope, target_id)

    def _reconcile_retirement(self, scope, target_id):
        row = self.store.get("api_call_operation", self._identifier(target_id))
        if row is None or not self._owned(row, scope):
            raise ApiFailure("forbidden")
        if row.get("retired_at") is not None or self.retirement is None:
            return
        ticket = CallRetirementTicket(target_id, row["call_id"], row["runtime_epoch"],
                                     row["caller"], row["profile"], row["owner_incarnation"])
        try:
            acknowledgment = self.retirement.request_retirement(ticket)
        except Exception:
            return
        if not isinstance(acknowledgment, CallRetirementAcknowledgment) or acknowledgment.ticket != ticket:
            return
        acknowledge_call_retirement(self.service, acknowledgment)


def acknowledge_call_retirement(service, acknowledgment):
    """Private host completion: exact media drain, never public JSON authority.

    A host may call this after asynchronous retirement finishes, including on a
    replacement service that holds the same protected vault. An epoch transition
    alone does not authorize constructing a successful acknowledgment.
    """
    if (not isinstance(acknowledgment, CallRetirementAcknowledgment)
            or not isinstance(acknowledgment.ticket, CallRetirementTicket) or acknowledgment.retired is not True):
        return False
    ticket = acknowledgment.ticket
    store = service.store
    with storage_errors(), service._dispatch_lock, store.read_snapshot():
        identifier = store.opaque_id("core-call-operation:v1", ticket.operation_id)
        row = store.get("api_call_operation", identifier)
        if row is None:
            return False
        expected_ticket = CallRetirementTicket(row["operation_id"], row["call_id"], row["runtime_epoch"],
                                               row["caller"], row["profile"], row["owner_incarnation"])
        if ticket != expected_ticket or row.get("abandon_requested_at") is None:
            return False
        if row.get("retired_at") is not None:
            return True
        catalog = dict(store.items("api_call_operation"))
        retired_at = time.time()
        values = [("api_call_operation", key, {**related, "retired_at": retired_at})
                  for key, related in catalog.items()
                  if (related["call_id"], related["runtime_epoch"], related["owner_incarnation"]) ==
                     (ticket.call_id, ticket.runtime_epoch, ticket.owner_incarnation)
                  and related.get("abandon_requested_at") is not None]
        try:
            store.conditional_put_and_delete({("api_call_operation", identifier): row}, values,
                                            expected_collections={"api_call_operation": catalog})
        except RecordConflict:
            return False
    service._changed()
    return True
