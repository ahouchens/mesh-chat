"""Private adapter: expose the local signed invitation through existing rules."""

from ..errors import ValidationError
from .errors import ApiFailure
from .invitations import InvitationObservation
from .service_messages import storage_errors


MAX_DOCUMENT = 65536


class ServiceInvitations:
    def __init__(self, service):
        self._service = service

    def create(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        with storage_errors():
            try:
                formats = self._service.invitation()
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            document, link = formats.get("file"), formats.get("link")
            expires = formats.get("expires_at")
            if (not isinstance(document, str) or not isinstance(link, str)
                    or not 1 <= len(document) <= MAX_DOCUMENT
                    or not 1 <= len(link) <= MAX_DOCUMENT
                    or type(expires) not in {int, float}):
                raise ApiFailure("internal")
            return InvitationObservation(document, link, float(expires))
