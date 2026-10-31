"""Private adapter: accept signed pairing material through existing domain rules."""

from ..errors import InvitationExpired, InvitationInvalid, ValidationError
from .errors import ApiFailure
from .pairing import PairingObservation
from .service_messages import storage_errors


MAX_DOCUMENT = 1048576
TRUST = {"awaiting_consent", "pending_request", "approved", "verified"}
REQUESTABLE = {"awaiting_consent", "pending_request"}


class ServicePairing:
    def __init__(self, service):
        self._service = service

    def _require_local(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")

    def accept(self, profile, document):
        self._require_local(profile)
        if (not isinstance(document, str) or not 1 <= len(document) <= MAX_DOCUMENT):
            raise ApiFailure("invalid_request")
        with storage_errors():
            try:
                contact = self._service.accept_invitation(document)
            except (ValidationError, InvitationInvalid, InvitationExpired) as error:
                raise ApiFailure("invalid_request") from error
            contact_id, trust = contact.get("id"), contact.get("trust")
            if not isinstance(contact_id, str) or trust not in TRUST:
                raise ApiFailure("internal")
            return PairingObservation(contact_id, trust)

    def request(self, profile, contact_id):
        self._require_local(profile)
        with storage_errors():
            contact = self._service.store.get("contact", contact_id)
            if contact is None:
                raise ApiFailure("forbidden")
            if contact.get("trust") not in REQUESTABLE:
                raise ApiFailure("invalid_request")
            try:
                message = self._service.send_contact_request(contact_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            if (not isinstance(message, dict) or not isinstance(message.get("id"), str)
                    or message.get("kind") != "contact_request"
                    or message.get("direction") != "outbound"):
                raise ApiFailure("internal")
