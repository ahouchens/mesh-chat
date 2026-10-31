"""Private adapter: accept signed pairing material through existing domain rules."""

from ..errors import InvitationExpired, InvitationInvalid, ValidationError
from .errors import ApiFailure
from .pairing import PairingObservation
from .service_messages import storage_errors


MAX_DOCUMENT = 1048576
TRUST = {"awaiting_consent", "pending_request", "approved", "verified"}


class ServicePairing:
    def __init__(self, service):
        self._service = service

    def accept(self, profile, document):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
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
