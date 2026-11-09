"""Encrypted caller-scoped composer with atomic compare-and-set and enqueue."""

import hmac
import json
import secrets
import time

from ..chat_text import validate_chat_text
from ..errors import ValidationError
from ..record_projection import Projection
from ..vault import RecordConflict
from .composer import COMPOSER_LIMITS, ComposerAcceptance, ComposerState, ComposerUpdate
from .errors import ApiFailure
from .messages import Acceptance, MessageScope
from .service_messages import storage_errors


STATE = "api_composer"
UPDATES = "api_composer_update"
MIGRATION = "api_composer_migration"


class ComposerStorage:
    """Storage identity and source-erasure projections, independent of runtime."""

    def __init__(self, store):
        self.store = store
        store.register_batch_projection(self.erase_sources)

    def identifier(self, kind, *parts):
        return self.store.opaque_id(kind, json.dumps(parts, ensure_ascii=True, separators=(",", ":")))

    def token(self, scope, peer, kind, nonce=None):
        nonce = nonce or secrets.token_hex(16)
        tag = self.identifier("composer-token:v1", scope.caller, scope.profile, peer, kind, nonce)[:32]
        return nonce + tag

    def verify(self, scope, peer, kind, token):
        if (not isinstance(token, str) or len(token) != 64
                or not hmac.compare_digest(token, self.token(scope, peer, kind, token[:32]))):
            raise ApiFailure("forbidden")

    def empty_after(self, state):
        scope = MessageScope(state["caller"], state["profile"])
        return {**state, "text": "", "revision": self.token(scope, state["peer"], "revision"),
                "update_key": self.token(scope, state["peer"], "update")}

    def erase_sources(self, changes):
        if any(kind == MIGRATION for kind, _ in changes):
            return Projection()
        deleted = {identifier for (kind, identifier), value in changes.items()
                   if kind in {"draft", "contact"} and value is None}
        if not deleted:
            return Projection()
        records = tuple((STATE, identifier, self.empty_after(state))
            for identifier, state in self.store.items(STATE, limit=COMPOSER_LIMITS["composers_per_vault"])
            if state["peer"] in deleted)
        return Projection(records=records)


class ServiceComposer:
    def __init__(self, service, messages, *, legacy=False):
        self.service = service
        self.store = service.store
        self.messages = messages
        self.legacy = legacy
        storage = getattr(self.store, "_core_composer_storage", None)
        if storage is None:
            storage = ComposerStorage(self.store)
            self.store._core_composer_storage = storage
        self.storage = storage

    def _authority(self, scope, peer):
        self.messages._profile(scope.profile)
        return self.messages._approved_contact(peer)

    def _id(self, scope, peer):
        return self.storage.identifier("composer:v1", scope.caller, scope.profile, peer)

    def _migration_id(self, scope, peer):
        return self.storage.identifier("composer-migration:v1", scope.profile, peer)

    def _current(self, scope, peer):
        saved = self.store.get(STATE, self._id(scope, peer))
        if saved is not None:
            return saved
        legacy_kind = "draft" if self.legacy else "api_legacy_draft"
        legacy_id = peer if self.legacy else self.store.opaque_id(
            "core-legacy-draft:v1", scope.caller, scope.profile, peer)
        legacy = self.store.get(legacy_kind, legacy_id)
        marker = self.store.get(MIGRATION, self._migration_id(scope, peer))
        if self.legacy and marker is not None:
            legacy = None
        text = (legacy or {}).get("text", "")
        if not isinstance(text, str) or len(text.encode("utf-8")) > COMPOSER_LIMITS["composer_text_utf8_bytes"]:
            raise ApiFailure("internal")
        nonce = self.storage.identifier("composer-initial:v1", scope.caller, scope.profile, peer, legacy)[:32]
        return {"caller": scope.caller, "profile": scope.profile, "peer": peer,
                "revision": None, "text": text,
                "_legacy_source": legacy,
                "_legacy_kind": legacy_kind, "_legacy_id": legacy_id,
                "update_key": self.storage.token(scope, peer, "update", nonce), "last_send": None}

    def _send_id(self, scope, revision):
        return self.messages._identifier("core-api-enqueue:v1", scope.caller, scope.profile,
                                         "message.enqueue_draft", revision)

    def _accepted(self, scope, state, revision, *, explicit):
        receipt = self.store.get("api_enqueue", self._send_id(scope, revision))
        if receipt is None:
            if explicit:
                if revision == state["revision"]:
                    return {"revision": revision, "status": "not_accepted"}
                raise ApiFailure("idempotency_expired")
            return {**state["last_send"], "status": "expired"}
        if receipt.get("peer") != state["peer"]:
            raise ApiFailure("forbidden")
        message = self.store.get("message", receipt["message_id"])
        if receipt["expires_at"] <= time.time() or message is None:
            if explicit:
                raise ApiFailure("idempotency_expired")
            return {"revision": revision, "status": "expired", "accepted_at": receipt["accepted_at"],
                    "idempotency_expires_at": receipt["expires_at"]}
        return {"revision": revision, "status": "accepted",
                "acceptance": Acceptance(receipt["handle"], receipt["accepted_at"], receipt["expires_at"]),
                "text": message["text"],
                "draft_disposition": "cleared" if state["revision"] == receipt["cleared_revision"] else "superseded"}

    def _snapshot(self, scope, state, send_revision=None):
        latest = state.get("last_send")
        outcome = self._accepted(scope, state, latest["revision"], explicit=False) if latest else None
        lookup = self._accepted(scope, state, send_revision, explicit=True) if send_revision else None
        return ComposerState(state["revision"], state["text"], state["update_key"], outcome, lookup)

    def query(self, scope, peer, send_revision=None):
        with storage_errors(), self.store.read_snapshot():
            self._authority(scope, peer)
            if send_revision is not None:
                self.storage.verify(scope, peer, "revision", send_revision)
            return self._snapshot(scope, self._current(scope, peer), send_revision)

    def _new_state(self, scope, peer, state):
        if state["revision"] is None:
            rows = self.store.list(STATE)
            owned = sum((row["caller"], row["profile"]) == (scope.caller, scope.profile) for row in rows)
            if (len(rows) >= COMPOSER_LIMITS["composers_per_vault"]
                    or owned >= COMPOSER_LIMITS["composers_per_caller_profile"]):
                raise ApiFailure("resource_exhausted")
        return {key: value for key, value in state.items() if not key.startswith("_")}

    def _commit(self, expected, records, deletions=(), **options):
        try:
            self.store.conditional_put_and_delete(expected, records, deletions, schema_floor=2, **options)
        except RecordConflict as error:
            raise ApiFailure("conflict") from error

    def _update_records(self, scope, peer, key, state, expected_revision, text):
        now = time.time()
        rows = self.store.items(UPDATES)
        expired = [(UPDATES, identifier) for identifier, row in rows if row["expires_at"] <= now]
        active = [row for _, row in rows if row["expires_at"] > now]
        owned = sum((row["caller"], row["profile"]) == (scope.caller, scope.profile) for row in active)
        if (len(active) >= COMPOSER_LIMITS["composer_update_keys_per_vault"]
                or owned >= COMPOSER_LIMITS["composer_update_keys_per_caller_profile"]):
            raise ApiFailure("resource_exhausted")
        changed = state["text"] != text
        updated = self._new_state(scope, peer, state)
        if changed or updated["revision"] is None:
            updated["revision"] = self.storage.token(scope, peer, "revision")
        updated.update(text=text, update_key=self.storage.token(scope, peer, "update"))
        digest = self.storage.identifier("composer-update-input:v1", peer, expected_revision, text)
        receipt = {"caller": scope.caller, "profile": scope.profile, "digest": digest,
                   "applied_revision": updated["revision"], "changed": changed,
                   "expires_at": now + COMPOSER_LIMITS["composer_update_idempotency_seconds"]}
        return updated, receipt, expired

    def update(self, scope, peer, key, expected_revision, text):
        with storage_errors():
            contact = self._authority(scope, peer)
            self.storage.verify(scope, peer, "update", key)
            if expected_revision is not None:
                self.storage.verify(scope, peer, "revision", expected_revision)
            state = self._current(scope, peer)
            identifier = self.storage.identifier("composer-update:v1", scope.caller, scope.profile, key)
            previous = self.store.get(UPDATES, identifier)
            digest = self.storage.identifier("composer-update-input:v1", peer, expected_revision, text)
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
            updated, receipt, deletions = self._update_records(scope, peer, key, state, expected_revision, text)
            state_id = self._id(scope, peer)
            expected = {(STATE, state_id): None if state["revision"] is None else state, (UPDATES, identifier): None,
                        ("contact", peer): contact}
            records = [(STATE, state_id, updated), (UPDATES, identifier, receipt)]
            fences = []
            if state["revision"] is None:
                legacy = state.get("_legacy_source")
                source = (state["_legacy_kind"], state["_legacy_id"])
                expected[source] = legacy
                if self.legacy:
                    updated["legacy_migrated"] = True
                    records.append((MIGRATION, self._migration_id(scope, peer), {"caller": scope.caller}))
                deletions.append(source)
                fences.append(source)
            self._commit(expected, records, deletions, write_fences=fences)
            return ComposerUpdate(updated["revision"], receipt["changed"], self._snapshot(scope, updated))

    def enqueue(self, scope, peer, key, revision):
        with storage_errors():
            contact = self._authority(scope, peer)
            self.storage.verify(scope, peer, "revision", revision)
            if key != revision:
                raise ApiFailure("idempotency_conflict")
            state = self._current(scope, peer)
            identifier = self._send_id(scope, revision)
            previous = self.store.get("api_enqueue", identifier)
            if previous is not None:
                outcome = self._accepted(scope, state, revision, explicit=True)
                return ComposerAcceptance(outcome["acceptance"], revision,
                    outcome["draft_disposition"], self._snapshot(scope, state))
            if revision != state["revision"]:
                raise ApiFailure("conflict")
            try:
                validate_chat_text(state["text"])
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            digest = self.storage.identifier("composer-send-input:v1", peer, revision)
            message, receipt, records, deletions, expected = self.messages.prepare_enqueue(
                scope, contact, identifier, digest, state["text"])
            cleared = self.storage.empty_after(state)
            receipt.update(peer=peer, revision=revision, cleared_revision=cleared["revision"])
            cleared["last_send"] = {"revision": revision, "accepted_at": receipt["accepted_at"],
                                   "idempotency_expires_at": receipt["expires_at"]}
            state_id = self._id(scope, peer)
            expected.update({(STATE, state_id): state,
                ("api_enqueue", identifier): None, ("contact", peer): contact})
            records.append((STATE, state_id, cleared))
            self._commit(expected, records, deletions)
            self.messages._wake_outbox(message)
            return ComposerAcceptance(Acceptance(receipt["handle"], receipt["accepted_at"], receipt["expires_at"]),
                revision, "cleared", self._snapshot(scope, cleared))
