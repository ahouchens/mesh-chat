"""Private profile bootstrap port, separate from public owner administration."""

from ..errors import InvitationExpired, InvitationInvalid, ValidationError
from .errors import ApiFailure
from .service_messages import storage_errors


PREVIEW_FIELDS = {
    "personal": {"display_name", "identity_hash", "destination_hash", "fingerprint",
                 "hints", "expires_at"},
    "workspace": {"name", "description", "owner_fingerprint", "member_count",
                  "retention_days", "expires_at"},
    "device_link": {"name", "member_display_name", "sponsor_fingerprint",
                    "device_count", "expires_at"},
}
CONSENT_FIELDS = {"requires_network_consent", "remote_profile", "participant_access",
                  "i2p_access_point", "requires_i2p_consent", "connection_reply_available",
                  "invitation_digest"}


class ServiceProfileBootstrap:
    def __init__(self, service):
        self._service = service

    def create(self, display_name, operation_id):
        with storage_errors():
            return self._service.create_profile(display_name, operation_id=operation_id)

    def preview(self, kind, document):
        # These existing verification paths do not adopt access, contact peers,
        # create identities, or accept/join. Saved-workspace metadata is excluded.
        verify = {"personal": self._service.preview_invitation,
                  "workspace": self._service.preview_workspace_invitation,
                  "device_link": self._service.preview_workspace_device_link}[kind]
        try:
            value = verify(document)
        except (InvitationExpired, InvitationInvalid, ValidationError) as error:
            raise ApiFailure("invalid_request") from error
        fields = PREVIEW_FIELDS[kind] | (CONSENT_FIELDS if kind != "device_link" else set())
        return {"kind": kind, "preview": {field: value[field] for field in fields if field in value}}
