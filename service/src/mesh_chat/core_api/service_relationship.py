"""Private adapter: explicit approval and revocation over existing domain rules.

Approval only accepts a pending request; an already-approved or verified peer is a
convergent no-op. Revocation blocks the peer and is likewise convergent. The
domain owns durability and its authority fence; this adapter never grants consent
defaults or quietly retries.
"""

from ..errors import ContactInUse, ValidationError
from ..models import TrustState
from .errors import ApiFailure
from .relationship import PeerDeletionObservation, RelationshipObservation
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


    def unblock(self, profile, contact_id):
        with storage_errors():
            contact = self._contact(profile, contact_id)
            if contact.get("trust") != TrustState.BLOCKED.value:
                raise ApiFailure("forbidden")
            try:
                self._service.unblock_contact(contact_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return self._observation(contact_id)

    def delete(self, profile, contact_id):
        with storage_errors():
            self._contact(profile, contact_id)
            try:
                self._service.delete_contact(contact_id)
            except ContactInUse as error:
                raise ApiFailure("conflict") from error
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return PeerDeletionObservation(True)


    def update(self, profile, contact_id, action, display_name):
        with storage_errors():
            contact = self._contact(profile, contact_id)
            try:
                if action == "rename":
                    self._service.update_contact(contact_id, display_name)
                elif action == "verify":
                    self._service.verify_contact(contact_id)
                elif action == "unverify":
                    self._service.unverify_contact(contact_id)
                else:
                    raise ApiFailure("invalid_request")
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return self._observation(contact_id)


    def decide(self, profile, contact_id, accept):
        with storage_errors():
            contact = self._contact(profile, contact_id)
            if contact.get("trust") != TrustState.PENDING_REQUEST.value:
                raise ApiFailure("forbidden")
            try:
                if accept:
                    self._service.approve_request(contact_id)
                else:
                    self._service.decline_request(contact_id)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            return self._observation(contact_id)
