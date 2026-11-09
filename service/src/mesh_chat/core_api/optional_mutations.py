"""Atomic receipt parent for advertised optional caller-key mutations.

Retain bounded receipts after expiry so an old caller key cannot become fresh.
No SDK or renderer owns these rows. Preparation and projection run under the
vault snapshot lock; quota, global operation receipt and domain writes share CAS.
"""
import hashlib
import json
import time

from ..vault import RecordConflict
from .errors import ApiFailure
from .service_messages import storage_errors

OPTIONAL_KEY_LIMITS = {
    "optional_key_idempotency_seconds": 604800,
    "optional_keys_per_caller_profile": 4096,
    "optional_keys_per_vault": 65536,
}


class OptionalMutationJournal:
    def __init__(self, store):
        self.store = store

    def apply(self, scope, operation, operation_id, params, *, validate, prepare, select_outcome, project, reconcile):
        with storage_errors(), self.store.read_snapshot():
            validate()  # Current identity/contact/membership before fresh or replay.
            material = json.dumps(["core-optional-mutation:v1", operation, params],
                                  ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(material.encode("ascii")).hexdigest()
            receipt_id = self.store.opaque_id("core-optional-mutation:v1", operation_id)
            global_id = self.store.opaque_id("workspace-operation", operation_id)
            previous = self.store.operation_result(operation_id, digest)
            if previous is not None:
                receipt = self.store.get("api_optional_mutation", receipt_id)
                if receipt is None or (receipt.get("caller"), receipt.get("profile"), receipt.get("operation")) != (scope.caller, scope.profile, operation):
                    raise ApiFailure("unavailable")
                if receipt["expires_at"] <= time.time():
                    raise ApiFailure("idempotency_expired")
                selected = project(previous, receipt)
                outcome = previous
            else:
                quota_id = self.store.opaque_id("core-optional-quota:v1", json.dumps([scope.caller, scope.profile], separators=(",", ":")))
                quota = self.store.get("api_optional_quota", quota_id)
                count = (quota or {"count": 0}).get("count")
                if type(count) is not int or count < 0:
                    raise ApiFailure("unavailable")
                if (count >= OPTIONAL_KEY_LIMITS["optional_keys_per_caller_profile"] or
                        self.store.record_count("api_optional_mutation") >= OPTIONAL_KEY_LIMITS["optional_keys_per_vault"]):
                    raise ApiFailure("resource_exhausted")
                prepared = prepare()
                outcome = select_outcome(prepared)
                now = time.time()
                receipt = {"caller": scope.caller, "profile": scope.profile, "operation": operation,
                           "accepted_at": now, "expires_at": now + OPTIONAL_KEY_LIMITS["optional_key_idempotency_seconds"]}
                global_receipt = {"id": operation_id, "input_digest": digest, "outcome": outcome, "created_at": now}
                expected = {**prepared.expected, ("workspace_operation", global_id): None,
                            ("api_optional_mutation", receipt_id): None, ("api_optional_quota", quota_id): quota}
                records = [*prepared.records, ("workspace_operation", global_id, global_receipt),
                           ("api_optional_mutation", receipt_id, receipt), ("api_optional_quota", quota_id, {"count": count + 1})]
                try:
                    self.store.conditional_put_and_delete(expected, records, prepared.deletions,
                        expected_collections=prepared.expected_collections)
                except RecordConflict as error:
                    raise ApiFailure("conflict") from error
                selected = project(outcome, receipt)
        try:
            reconcile(outcome)  # Existing durable outbox only, never another mutation.
        except Exception:
            pass  # Restart recovers committed outbox even if the wake hint fails.
        return selected
