"""Private adapter: expose the local signed invitation through existing rules."""

from ..errors import ValidationError
from .errors import ApiFailure
from .invitations import InvitationObservation
from .service_messages import storage_errors


MAX_DOCUMENT = 65536


class ServiceInvitations:
    def __init__(self, service):
        self._service = service

    def create(self, profile, *, connection_mode=None, manual_setup_id=None,
               external_host=None, external_port=None, i2p_access_point=None,
               i2p_label=None):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        with storage_errors():
            try:
                formats = self._service.invitation(
                    connection_mode=connection_mode,
                    manual_setup_id=manual_setup_id,
                    external_host=external_host,
                    external_port=external_port,
                    i2p_access_point=i2p_access_point,
                    i2p_label=i2p_label,
                )
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            document, link, text = formats.get("file"), formats.get("link"), formats.get("text")
            expires = formats.get("expires_at")
            host = formats.get("host_session_id")
            if (not isinstance(document, str) or not isinstance(link, str)
                    or not isinstance(text, str)
                    or not 1 <= len(document) <= MAX_DOCUMENT
                    or not 1 <= len(link) <= MAX_DOCUMENT
                    or not 1 <= len(text) <= MAX_DOCUMENT
                    or type(expires) not in {int, float}
                    or (host is not None and (not isinstance(host, str) or not 8 <= len(host) <= 128))):
                raise ApiFailure("internal")
            return InvitationObservation(document, link, text, float(expires), host)
