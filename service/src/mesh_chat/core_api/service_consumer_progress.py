"""Durable consumer progress; never a peer receipt or delivery-state mutation."""

import time

from ..message_journal import JournalGap, RETENTION_SECONDS
from .errors import ApiFailure
from .recovery import Acknowledgment, MAX_CALLER_ACKNOWLEDGMENTS, MAX_VAULT_ACKNOWLEDGMENTS


class ServiceConsumerProgress:
    def __init__(self, store, journal, cursors, identifier):
        self._store = store
        self._journal = journal
        self._cursors = cursors
        self._identifier = identifier

    def _progress_id(self, scope):
        return self._identifier("core-api-consumer-progress:v1", scope.caller, scope.profile)

    def resume(self, scope, authority):
        progress = self._store.get("api_consumer_progress", self._progress_id(scope))
        if progress is None:
            raise ApiFailure("resync_required")
        self._cursors.validate(progress, authority, "events")
        self._cursors.require_live(progress)
        return progress

    def acknowledge(self, scope, authority, token, key):
        # Current scope and authority still apply to a lost-reply replay. Expired
        # input tokens may resolve an existing write but cannot create a new one.
        position = self._cursors.decode(scope, authority, token, "events")
        identifier = self._identifier("core-api-event-ack:v1", scope.caller, scope.profile, "events.ack", key)
        digest = self._identifier("core-api-event-ack-payload:v1", position["g"], position["a"], position["h"])
        previous = self._store.get("api_event_ack", identifier)
        if previous is not None:
            if previous["digest"] != digest:
                raise ApiFailure("idempotency_conflict")
            result = previous["result"]
            if result["expires_at"] <= time.time():
                raise ApiFailure("idempotency_expired")
            return Acknowledgment(**result)
        self._cursors.require_live(position)
        try:
            self._journal.read(position["h"], 1)
        except JournalGap as error:
            raise ApiFailure("resync_required") from error
        return self._commit(scope, position, identifier, digest)

    def _commit(self, scope, position, identifier, digest):
        progress_id = self._progress_id(scope)
        current = self._store.get("api_consumer_progress", progress_id)
        if (current is not None and (current["g"], current["a"]) == (position["g"], position["a"])
                and position["h"] < current["h"]):
            raise ApiFailure("conflict")
        quota_id = self._identifier("core-api-event-ack-quota:v1", scope.caller, scope.profile)
        count = (self._store.get("api_event_ack_quota", quota_id) or {"count": 0})["count"]
        if count >= MAX_CALLER_ACKNOWLEDGMENTS or self._store.record_count("api_event_ack") >= MAX_VAULT_ACKNOWLEDGMENTS:
            raise ApiFailure("resource_exhausted")
        now = time.time()
        expiry = now + RETENTION_SECONDS
        checkpoint = self._identifier("core-api-checkpoint:v1", scope.caller, scope.profile,
                                      position["g"], position["a"], position["h"])
        result = {"checkpoint": checkpoint, "acknowledged_at": now, "expires_at": expiry}
        self._store.put_many([
            ("api_consumer_progress", progress_id, {**position, "x": expiry}),
            ("api_event_ack", identifier, {"digest": digest, "result": result}),
            ("api_event_ack_quota", quota_id, {"count": count + 1}),
        ])
        return Acknowledgment(**result)
