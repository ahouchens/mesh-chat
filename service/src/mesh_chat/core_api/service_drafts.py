"""Private adapter for typed direct-message drafts."""

from uuid import uuid4

from .drafts import DraftObservation
from .errors import ApiFailure
from .service_messages import storage_errors


class ServiceDrafts:
    def __init__(self, service):
        self._service = service

    def _contact(self, profile, contact_id):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        contact = self._service.store.get("contact", contact_id)
        if contact is None:
            raise ApiFailure("forbidden")
        return contact

    def get(self, profile, contact_id):
        with storage_errors():
            self._contact(profile, contact_id)
            draft = self._service.store.get("draft", contact_id) or {}
            text = draft.get("text", "")
            if not isinstance(text, str):
                raise ApiFailure("internal")
            return DraftObservation(text)

    def set(self, profile, contact_id, text):
        with storage_errors():
            self._contact(profile, contact_id)
            response, should_stop = self._service.dispatch({
                "v": 1, "id": uuid4().hex, "command": "save_draft",
                "payload": {"contact_id": contact_id, "text": text},
            })
            if should_stop or response.get("ok") is not True:
                raise ApiFailure("invalid_request")
            saved = response.get("result")
            if not isinstance(saved, dict) or not isinstance(saved.get("text"), str):
                raise ApiFailure("internal")
            return DraftObservation(saved["text"])
