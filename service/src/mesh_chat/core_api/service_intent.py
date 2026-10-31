"""Private adapter: contact-wide connection intent over existing domain services.

The domain owns durable intent and its fences; this adapter only checks current
caller/profile authority and reports the resulting desired state. It applies no
retry policy and does not touch a runtime.
"""

from ..models import TrustState
from .errors import ApiFailure
from .intent import IntentObservation
from .service_messages import storage_errors


class ServiceIntent:
    def __init__(self, service):
        self._service = service
        self._store = service.store

    def _contact(self, profile, contact_id):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        contact = self._store.get("contact", contact_id)
        if contact is None or contact.get("trust") not in {
                TrustState.APPROVED.value, TrustState.VERIFIED.value}:
            raise ApiFailure("forbidden")
        return contact

    def _observation(self, contact_id):
        profiles = [profile for profile in self._service._reconnect_profiles_raw()
                    if contact_id in (profile.get("contact_id"), profile.get("id"))]
        active = any(bool(profile.get("active")) for profile in profiles)
        return IntentObservation("enabled" if active else "stopped", active)

    def apply(self, profile, contact_id, enabled):
        if type(enabled) is not bool:
            raise ApiFailure("invalid_request")
        with storage_errors():
            self._contact(profile, contact_id)
            if enabled:
                self._service.reconnect_start(contact_id)
            else:
                self._service.reconnect_stop(contact_id)
            return self._observation(contact_id)
