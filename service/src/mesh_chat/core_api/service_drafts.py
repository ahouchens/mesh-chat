"""Private adapter for typed direct-message drafts."""

from .drafts import DraftObservation
from .errors import ApiFailure
from .service_messages import storage_errors
from .service_composer import STATE


class ServiceDrafts:
    def __init__(self, service, *, legacy=False):
        self._service = service
        self._legacy = legacy

    def _contact(self, profile, contact_id):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        contact = self._service.store.get("contact", contact_id)
        if contact is None:
            raise ApiFailure("forbidden")
        return contact

    def _target(self, scope, contact_id):
        self._contact(scope.profile, contact_id)
        storage = getattr(self._service.store, "_core_composer_storage", None)
        if storage is not None:
            identifier = storage.identifier("composer:v1", scope.caller, scope.profile, contact_id)
            if self._service.store.get(STATE, identifier) is not None:
                raise ApiFailure("conflict")
        if self._legacy:
            return "draft", contact_id
        identifier = self._service.store.opaque_id("core-legacy-draft:v1",
            scope.caller, scope.profile, contact_id)
        return "api_legacy_draft", identifier

    def get(self, scope, contact_id):
        with storage_errors():
            draft = self._service.store.get(*self._target(scope, contact_id)) or {}
            text = draft.get("text", "")
            if not isinstance(text, str):
                raise ApiFailure("internal")
            return DraftObservation(text)

    def set(self, scope, contact_id, text):
        with storage_errors():
            kind, identifier = self._target(scope, contact_id)
            self._service.store.put(kind, identifier, {"contact_id": contact_id, "text": text})
            return DraftObservation(text)
