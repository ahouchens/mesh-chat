"""Private adapter: explicit approval and revocation over existing domain rules.

Approval only accepts a pending request; an already-approved or verified peer is a
convergent no-op. Revocation blocks the peer and is likewise convergent. The
domain owns durability and its authority fence; this adapter never grants consent
defaults or quietly retries.
"""

from ..errors import ValidationError
from ..models import TrustState
from .errors import ApiFailure
from .relationship import RelationshipObservation
from .service_messages import storage_errors


APPROVED = {TrustState.APPROVED.value, TrustState.VERIFIED.value}
PENDING = {TrustState.PENDING_REQUEST.value}


class ServiceRelationship:
    def __init__(self, service):
        self._service = service
        self._store = service.store

    def _contact(self, profile, contact_id):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        contact = self._store.get("contact", contact_id)
        if contact is None:
            raise ApiFailure("forbidden")
        return contact

    def _observation(self, contact_id):
        contact = self._store.get("contact", contact_id)
        if contact is None:
            raise ApiFailure("forbidden")
        return RelationshipObservation(contact["trust"])

    def approve(self, profile, contact_id):
        return self._apply(profile, contact_id, True)

    def revoke(self, profile, contact_id):
        return self._apply(profile, contact_id, False)

    def _apply(self, profile, contact_id, approve):
        with storage_errors():
            contact = self._contact(profile, contact_id)
            trust = contact.get("trust")
            if approve:
                if trust in APPROVED:
                    return RelationshipObservation(trust)
                if trust not in PENDING:
                    raise ApiFailure("forbidden")
                try:
                    self._service.approve_request(contact_id)
                except ValidationError as error:
                    raise ApiFailure("invalid_request") from error
                return self._observation(contact_id)
            if trust == TrustState.BLOCKED.value:
                return RelationshipObservation(trust)
            try:
                self._service.block_contact(contact_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return self._observation(contact_id)
