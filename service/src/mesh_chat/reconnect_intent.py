"""Durable user intent, separate from signaling and connection lifecycle policy."""

from contextlib import nullcontext

from .models import TrustState


class ReconnectIntents:
    def __init__(self, service, now):
        self._service = service
        self._store = service.store
        self._runtime = getattr(service, "_connection_runtime", None)
        self._lock = getattr(service, "_dispatch_lock", nullcontext())
        self._now = now

    def start(self, contact_id, *, automatic):
        with self._lock:
            profiles = self._start_targets(contact_id, automatic)
            if not profiles:
                return
            now = self._now()
            self._store.put_many([
                ("reconnect_profile", profile["id"], {
                    **profile, "active": True, "state": "waiting_for_peer",
                    "last_error": "", "updated_at": now,
                }) for profile in profiles
            ])
            # No broad resume: excluded contacts keep their explicit Stop fences.
            if self._runtime is not None and not automatic:
                for target in dict.fromkeys(profile["contact_id"] for profile in profiles):
                    self._runtime.committed_start(target)
            self._service._changed()

    def _start_targets(self, contact_id, automatic):
        contacts = ([self._service._reconnect_contact(contact_id)] if contact_id is not None else [
            contact for contact in self._store.list("contact")
            if contact.get("trust") in {TrustState.APPROVED.value, TrustState.VERIFIED.value}
        ])
        profiles = [self._service._reconnect_profile_for_contact(contact["id"]) for contact in contacts]
        return [profile for profile in profiles
                if profile.get("auto_reconnect") and profile.get("remote_auto_reconnect")
                and not (automatic and profile.get("state") == "stopped")]

    def stop(self, contact_id):
        with self._lock:
            # Fencing precedes every storage read or write that might fail.
            if self._runtime is not None:
                self._runtime.fence(contact_id)
            profiles = [profile for profile in self._service._reconnect_profiles_raw()
                        if contact_id is None or contact_id in (profile.get("contact_id"), profile.get("id"))]
            if self._runtime is not None:
                self._service.retire_unmanaged_native_connections({profile["id"] for profile in profiles})
            journal = getattr(self._service, "_carrier_journal", None)
            if journal is not None:
                # Deliberately independent: even failed intent persistence must
                # not leave a reusable recovery binding for the retired carrier.
                journal.invalidate(contact_id)
            self._commit_stop(profiles, all_profiles=contact_id is None)
            if self._runtime is None:
                self._close_legacy_peers(profiles)
            self._service._changed()

    def _close_legacy_peers(self, profiles):
        close_native = getattr(self._service, "close_native_reconnect_session", None)
        if close_native is None:
            return
        failure = None
        for profile in profiles:
            try:
                close_native(profile["id"])
            except Exception as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    def _commit_stop(self, profiles, *, all_profiles):
        now = self._now()
        records = [("reconnect_profile", profile["id"], {
            **profile, "active": False, "state": "stopped", "updated_at": now,
        }) for profile in profiles]
        if all_profiles:
            records.append(("reconnect_state", "current", {
                "v": 1, "state": "stopped", "detail": "", "attempt_id": "", "updated_at": now,
            }))
        if records:
            self._store.put_many(records)
