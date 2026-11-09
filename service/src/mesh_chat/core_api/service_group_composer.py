"""Protected group drafts composed with actual prepared group acceptance."""

import hmac
import json
import secrets
import time

from ..record_projection import Projection
from .composer import COMPOSER_LIMITS, ComposerAcceptance, ComposerState, ComposerUpdate
from .errors import ApiFailure
from .messages import Acceptance
from .service_composer import ServiceComposer
from .service_messages import storage_errors


GROUP_COMPOSER_BOUNDS = dict(COMPOSER_LIMITS)
GROUP_COMPOSER_LIMITS = {"group_" + key: value for key, value in GROUP_COMPOSER_BOUNDS.items()}
STATE = "api_group_composer"
UPDATES = "api_group_composer_update"
SENDS = "api_group_composer_send"
MIGRATION = "api_group_composer_migration"
QUOTA = "api_group_composer_quota"


class GroupComposerStorage:
    def __init__(self, store):
        self.store = store
        store.register_batch_projection(self.erase_sources)

    def identifier(self, kind, *parts):
        return self.store.opaque_id("group-composer:" + kind,
            json.dumps(parts, ensure_ascii=True, separators=(",", ":")))

    def token(self, scope, group, purpose, nonce=None):
        nonce = nonce or secrets.token_hex(16)
        return nonce + self.identifier("token:v1", scope.caller, scope.profile, group, purpose, nonce)[:32]

    def verify(self, scope, group, purpose, token):
        if (not isinstance(token, str) or len(token) != 64 or not hmac.compare_digest(
                token, self.token(scope, group, purpose, token[:32]))):
            raise ApiFailure("forbidden")

    def empty_after(self, state):
        from .messages import MessageScope
        scope = MessageScope(state["caller"], state["profile"])
        return {**state, "text": "", "revision": self.token(scope, state["group"], "revision"),
                "update_key": self.token(scope, state["group"], "update")}

    def erase_sources(self, changes):
        profile = self.store.get("profile", "local") or {}
        destination = profile.get("destination_hash")
        erased = set()
        for (kind, identifier), value in changes.items():
            if kind == "group":
                member = next((item for item in (value or {}).get("members", [])
                               if item.get("destination_hash") == destination), {})
                if (value is None or value.get("status") != "active" or member.get("status") != "active"
                        or (value.get("posting_policy") == "owner_admins" and member.get("role") not in {"owner", "admin"})):
                    erased.add(identifier)
            if kind == "group_draft" and value is None and not any(k == MIGRATION for k, _ in changes):
                erased.add(identifier)
        if not erased:
            return Projection()
        records = tuple((STATE, identifier, self.empty_after(state))
            for identifier, state in self.store.items(STATE, limit=GROUP_COMPOSER_BOUNDS["composers_per_vault"])
            if state["group"] in erased and (STATE, identifier) not in changes)
        return Projection(records=records)


class ServiceGroupComposer:
    """Pure observations and one CAS joining revision, group plan and receipts."""

    def __init__(self, service, *, legacy=False):
        self.service, self.store, self.legacy = service, service.store, legacy
        storage = getattr(self.store, "_core_group_composer_storage", None)
        if storage is None:
            storage = GroupComposerStorage(self.store)
            self.store._core_group_composer_storage = storage
        self.storage = storage

    # The commit wrapper and snapshot selection are domain-independent; retain
    # the existing direct composer error mapping without sharing its identities.
    _commit = ServiceComposer._commit
    _snapshot = ServiceComposer._snapshot

    def _authority(self, scope, group):
        if scope.profile != "local":
            raise ApiFailure("forbidden")
        if self.service._identity is None:
            raise ApiFailure("locked")
        value, profile, _ = self.service.validate_group_composer(group)
        return {("group", group): value, ("profile", "local"): profile,
                ("identity", "local"): self.store.get("identity", "local")}

    def _id(self, scope, group):
        return self.storage.identifier("state:v1", scope.caller, scope.profile, group)

    def _source(self, scope, group):
        if self.legacy:
            return "group_draft", group
        return "api_legacy_group_draft", self.storage.identifier("legacy:v1", scope.caller, scope.profile, group)

    def _migration_id(self, scope, group):
        return self.storage.identifier("migration:v1", None if self.legacy else scope.caller, scope.profile, group)

    def _current(self, scope, group):
        state = self.store.get(STATE, self._id(scope, group))
        if state is not None:
            return state
        source = self._source(scope, group)
        legacy = self.store.get(*source)
        if self.store.get(MIGRATION, self._migration_id(scope, group)) is not None:
            legacy = None
        text = (legacy or {}).get("text", "")
        if not isinstance(text, str) or len(text.encode("utf-8")) > GROUP_COMPOSER_BOUNDS["composer_text_utf8_bytes"]:
            raise ApiFailure("internal")
        nonce = self.storage.identifier("initial:v1", scope.caller, scope.profile, group, legacy)[:32]
        return {"caller": scope.caller, "profile": scope.profile, "group": group,
                "revision": None, "text": text, "update_key": self.storage.token(scope, group, "update", nonce),
                "last_send": None, "_source": source, "_legacy": legacy}

    def _send_id(self, scope, revision):
        return self.storage.identifier("send:v1", scope.caller, scope.profile, revision)

    def _accepted(self, scope, state, revision, *, explicit):
        receipt = self.store.get(SENDS, self._send_id(scope, revision))
        if receipt is None:
            if explicit:
                if revision == state["revision"]:
                    return {"revision": revision, "status": "not_accepted"}
                raise ApiFailure("idempotency_expired")
            return {**state["last_send"], "status": "expired"}
        if receipt["group"] != state["group"]:
            raise ApiFailure("forbidden")
        message = self.store.get("group_message", receipt["message_id"])
        if receipt["expires_at"] <= time.time() or message is None:
            if explicit:
                raise ApiFailure("idempotency_expired")
            return {"revision": revision, "status": "expired", "accepted_at": receipt["accepted_at"],
                    "idempotency_expires_at": receipt["expires_at"]}
        if message.get("group_id") != state["group"]:
            raise ApiFailure("unavailable")
        return {"revision": revision, "status": "accepted", "text": message["text"],
                "acceptance": Acceptance(receipt["handle"], receipt["accepted_at"], receipt["expires_at"]),
                "draft_disposition": "cleared" if state["revision"] == receipt["cleared_revision"] else "superseded"}

    def query(self, scope, group, send_revision=None):
        with storage_errors(), self.store.read_snapshot():
            self._authority(scope, group)
            if send_revision is not None:
                self.storage.verify(scope, group, "revision", send_revision)
            return self._snapshot(scope, self._current(scope, group), send_revision)

    def _quota(self, scope, family):
        owned_id = self.storage.identifier("quota:v1", family, scope.caller, scope.profile)
        total_id = self.storage.identifier("quota:v1", family)
        expected, records = {}, []
        for identifier, maximum in ((owned_id, GROUP_COMPOSER_BOUNDS[family + "_per_caller_profile"]),
                                     (total_id, GROUP_COMPOSER_BOUNDS[family + "_per_vault"])):
            old = self.store.get(QUOTA, identifier)
            count = (old or {}).get("count", 0)
            if type(count) is not int or count < 0:
                raise ApiFailure("unavailable")
            if count >= maximum:
                raise ApiFailure("resource_exhausted")
            expected[(QUOTA, identifier)] = old
            records.append((QUOTA, identifier, {"count": count + 1}))
        return expected, records

    def update(self, scope, group, key, expected_revision, text):
        with storage_errors(), self.store.read_snapshot():
            expected = self._authority(scope, group)
            self.storage.verify(scope, group, "update", key)
            if expected_revision is not None:
                self.storage.verify(scope, group, "revision", expected_revision)
            state = self._current(scope, group)
            identifier = self.storage.identifier("update:v1", scope.caller, scope.profile, key)
            digest = self.storage.identifier("update-input:v1", group, expected_revision, text)
            previous = self.store.get(UPDATES, identifier)
            if previous is not None:
                if previous["digest"] != digest:
                    raise ApiFailure("idempotency_conflict")
                if previous["expires_at"] <= time.time():
                    raise ApiFailure("idempotency_expired")
                return ComposerUpdate(previous["applied_revision"], previous["changed"], self._snapshot(scope, state))
            if key != state["update_key"]:
                raise ApiFailure("idempotency_expired")
            if expected_revision != state["revision"]:
                raise ApiFailure("conflict")
            quotas, records = self._quota(scope, "composer_update_keys")
            expected.update(quotas)
            if state["revision"] is None:
                quotas, fresh = self._quota(scope, "composers")
                expected.update(quotas)
                records.extend(fresh)
            updated = {k: v for k, v in state.items() if not k.startswith("_")}
            changed = text != state["text"]
            if changed or state["revision"] is None:
                updated["revision"] = self.storage.token(scope, group, "revision")
            updated.update(text=text, update_key=self.storage.token(scope, group, "update"))
            receipt = {"digest": digest, "applied_revision": updated["revision"], "changed": changed,
                       "expires_at": time.time() + GROUP_COMPOSER_BOUNDS["composer_update_idempotency_seconds"]}
            expected.update({(STATE, self._id(scope, group)): None if state["revision"] is None else state,
                             (UPDATES, identifier): None})
            records.extend(((STATE, self._id(scope, group), updated), (UPDATES, identifier, receipt)))
            deletions, fences = [], []
            if state["revision"] is None:
                source = tuple(state["_source"])
                expected[source] = state["_legacy"]
                marker_id = self._migration_id(scope, group)
                expected[(MIGRATION, marker_id)] = self.store.get(MIGRATION, marker_id)
                records.append((MIGRATION, marker_id, {"caller": scope.caller}))
                deletions.append(source)
                fences.append(source)
            self._commit(expected, records, deletions, write_fences=fences)
            return ComposerUpdate(updated["revision"], changed, self._snapshot(scope, updated))

    def enqueue(self, scope, group, key, revision, operation_id):
        with storage_errors(), self.store.read_snapshot():
            expected = self._authority(scope, group)
            self.storage.verify(scope, group, "revision", revision)
            if key != revision:
                raise ApiFailure("idempotency_conflict")
            state = self._current(scope, group)
            identifier = self._send_id(scope, revision)
            previous = self.store.get(SENDS, identifier)
            if previous is not None:
                outcome = self._accepted(scope, state, revision, explicit=True)
                self._wake(previous["delivery_ids"])
                return ComposerAcceptance(outcome["acceptance"], revision,
                    outcome["draft_disposition"], self._snapshot(scope, state))
            if revision != state["revision"]:
                raise ApiFailure("conflict")
            digest = self.storage.identifier("send-input:v1", group, revision)
            if self.store.operation_result(operation_id, digest) is not None:
                raise ApiFailure("idempotency_expired")
            quotas, records = self._quota(scope, "composer_send_keys")
            prepared = self.service.prepare_group_send(group, state["text"], operation_id)
            expected.update(quotas)
            now = time.time()
            cleared = self.storage.empty_after(state)
            receipt = {"group": group, "message_id": prepared.result["message_id"],
                       "handle": self.storage.identifier("acceptance:v1", scope.caller, scope.profile, prepared.result["message_id"]),
                       "accepted_at": now, "expires_at": now + GROUP_COMPOSER_BOUNDS["composer_send_idempotency_seconds"],
                       "cleared_revision": cleared["revision"], "delivery_ids": list(prepared.delivery_ids)}
            cleared["last_send"] = {"revision": revision, "accepted_at": now,
                                   "idempotency_expires_at": receipt["expires_at"]}
            global_id = self.store.opaque_id("workspace-operation", operation_id)
            expected.update(prepared.expected)
            expected.update({(STATE, self._id(scope, group)): state, (SENDS, identifier): None,
                             ("workspace_operation", global_id): None})
            records.extend((*prepared.records, (STATE, self._id(scope, group), cleared), (SENDS, identifier, receipt),
                ("workspace_operation", global_id, {"id": operation_id, "input_digest": digest,
                    "outcome": {"message_id": prepared.result["message_id"]}, "created_at": now})))
            self._commit(expected, records, prepared.deletions, expected_collections=prepared.expected_collections)
            self._wake(prepared.delivery_ids)
            return ComposerAcceptance(Acceptance(receipt["handle"], now, receipt["expires_at"]),
                revision, "cleared", self._snapshot(scope, cleared))

    def _wake(self, delivery_ids):
        try:
            self.service.wake_group_outbox(delivery_ids)
            self.service._changed()
        except Exception:
            pass  # Durable outbox recovery does not depend on a wake hint.
